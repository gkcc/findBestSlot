from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any

from gear_optimizer.game_rules import PROJECT_ROOT, load_characters, load_game, load_probability_models
from gear_optimizer.position_ev import (
    best_loadout_value,
    fixed_main_gain_ladder_rows,
    fixed_substat_gain_ladder_rows,
    initial_substat_tier_rows,
    inventory_rows_from_pieces,
    position_strategy_efficiency_rows,
    recommended_action_ev_row,
    resource_marginal_ev_rows,
)
from gear_optimizer.scoring import analyse_current_gear
from gear_optimizer.user_current_gear import current_gear_store_path, load_user_current_gears
from gear_optimizer.user_set_plans import load_user_set_plans, set_plan_store_path


GAME_ID = "zzz"
CHARACTER_ID = "zzz_starlight_billy"
OUTPUT_DIR = PROJECT_ROOT / "reports" / "gpt_audit_gear_optimizer"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _visible_rows(rows: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in row.items() if not str(key).startswith("_")}
        for row in rows
    ]


def _visible_row(row: dict) -> dict:
    return {key: value for key, value in row.items() if not str(key).startswith("_")}


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return lines


def _detail_label(details: list[dict]) -> str:
    values = []
    for detail in details:
        if detail["priority"] == "无效":
            values.append(f"{detail['stat']} {detail['total_rolls']:g}次 无效")
        else:
            values.append(
                f"{detail['stat']} {detail['total_rolls']:g}次 "
                f"{detail['priority']}#{detail.get('priority_rank', '-')}"
            )
    return "；".join(values)


def _copy_raw_inputs(output_dir: Path) -> list[dict[str, str]]:
    raw_dir = output_dir / "raw_inputs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    sources = [
        ("game_rules", PROJECT_ROOT / "configs" / "games" / f"{GAME_ID}.yaml"),
        (
            "character_target",
            PROJECT_ROOT / "configs" / "characters" / f"{CHARACTER_ID}.yaml",
        ),
        (
            "probability_model",
            PROJECT_ROOT / "configs" / "probabilities" / f"{GAME_ID}_default.yaml",
        ),
        ("saved_current_gear", current_gear_store_path(GAME_ID, CHARACTER_ID)),
        ("saved_set_plan", set_plan_store_path(GAME_ID, CHARACTER_ID)),
    ]
    copied = []
    for label, source in sources:
        if not source.exists():
            continue
        destination = raw_dir / f"{label}.yaml"
        shutil.copyfile(source, destination)
        copied.append(
            {
                "label": label,
                "source": str(source),
                "copied_to": str(destination),
            }
        )
    return copied


def build_audit_bundle(action_ev_horizon: int = 1) -> dict:
    game = load_game(GAME_ID)
    character = next(item for item in load_characters(GAME_ID) if item.id == CHARACTER_ID)
    user_set_plans = load_user_set_plans(GAME_ID, CHARACTER_ID)
    if user_set_plans:
        character = character.model_copy(
            update={
                "set_plans": user_set_plans,
                "default_set_plan": user_set_plans[0].id,
            }
        )
    probability_model = load_probability_models(GAME_ID)[0]
    saved_gears = load_user_current_gears(GAME_ID, CHARACTER_ID)
    if not saved_gears:
        raise RuntimeError("没有找到保存的当前盘面。")
    current = saved_gears[0]
    pieces = current["pieces"]
    analysis = analyse_current_gear(pieces, game, character)
    inventory_rows = inventory_rows_from_pieces(pieces, game, character)
    action_rows = position_strategy_efficiency_rows(
        game,
        character,
        probability_model,
        analysis,
        inventory_pieces=pieces,
        horizon=action_ev_horizon,
    )
    best_action = recommended_action_ev_row(action_rows)

    return {
        "generated_at": _utc_now(),
        "scope": {
            "game": GAME_ID,
            "character": CHARACTER_ID,
            "inventory_source": str(current_gear_store_path(GAME_ID, CHARACTER_ID)),
            "inventory_label": current["label"],
            "inventory_note": "当前导出库存只包含保存盘面里的 pieces；未录入的背包/备选盘不会参与 best_loadout。",
            "action_ev_horizon": action_ev_horizon,
            "calculation": "exact_enumeration_not_sampling",
            "lookahead_pruning": "horizon>1 时使用确定性套装可行性前沿：若库存里有未上身且能跨套装要求换位的候选件，只展开能补回被挤出套装要求的位置/套装 action；没有明确互补缺口时回退到完整 dominant future action 集。",
        },
        "formulas": {
            "best_loadout": "B(I)=max_{6件组合满足套装方案} (主属性命中数, 副词条优先级向量, 有效词条数, 质量分)",
            "single_step_action_ev": "EV(a)=sum_o P(o|a) * max(B(I+o)-B(I), 0)",
            "finite_lookahead": "V_h(I)=max_a E[V_{h-1}(I+o_a)], V_0(I)=B(I)",
            "piece_immediate": "immediate(piece)=B(I+piece)-B(I)",
            "piece_option": "option(piece,h)=V_h(I+piece)-B(I+piece)",
        },
        "rules": {
            "main_stat_probabilities": game.main_stat_probabilities,
            "sub_stat_relative_probabilities": game.sub_stat_probabilities,
            "initial_substat_count_probabilities": probability_model.initial_substat_count_probabilities,
            "resource_costs": probability_model.resource_costs,
            "target_set_probability": probability_model.target_set_probability,
            "enhancement": game.enhancement.model_dump(mode="json"),
        },
        "character_priority": {
            "core_order": character.substat_priority.core if character.substat_priority else [],
            "usable_order": character.substat_priority.usable if character.substat_priority else [],
            "note": "没有副词条小数系数；同组内按列表顺序比较。",
            "set_plan": character.active_set_plan().model_dump(mode="json")
            if character.active_set_plan()
            else None,
        },
        "current_inventory": {
            "best_loadout_value": best_loadout_value(pieces, game, character),
            "inventory_rows": [_visible_row(row) for row in inventory_rows],
            "score_rows": [score.model_dump(mode="json") for score in analysis.scores],
            "set_plan_analysis": analysis.set_plan,
        },
        "ui_results": {
            "best_action": _visible_row(best_action) if best_action else None,
            "action_ev_rows": _visible_rows(action_rows),
            "fixed_main_ladder_rows": fixed_main_gain_ladder_rows(
                game,
                character,
                probability_model,
                analysis,
            ),
            "fixed_substat_ladder_rows": fixed_substat_gain_ladder_rows(
                game,
                character,
                probability_model,
                analysis,
            ),
            "resource_marginal_ev_rows": resource_marginal_ev_rows(
                game,
                character,
                probability_model,
                analysis,
                inventory_pieces=pieces,
                horizon=action_ev_horizon,
            ),
            "initial_substat_tier_rows": initial_substat_tier_rows(
                game,
                character,
                probability_model,
                analysis,
            ),
        },
        "implementation_limits_to_review": [
            "界面默认 action EV 仍是 horizon=1；需要多步报告时用 scripts/generate_gpt_audit.py --horizon 2 显式生成。",
            "如果用户没有把背包中未穿装备录入 pieces，导出结果无法代表完整背包库存。",
            "horizon>1 的套装可行性前沿会递归重算：例如 1/3 是 2 件套、2/4/5/6 是 4 件套时，新增 1号位 4 件套后，下一步只展开 2/4/5/6 的 2 件套互补 action。",
            "已新增固定主属性/固定副属性的全局边际 EV 表；旧省母盘阶梯仍是单件阈值诊断表，不应当替代全局 EV。",
        ],
    }


def build_markdown(bundle: dict) -> str:
    rows = bundle["current_inventory"]["score_rows"]
    action_rows = _visible_rows(bundle["ui_results"]["action_ev_rows"])
    best = bundle["ui_results"]["best_action"] or {}
    lines = [
        "# GPT 审核输入：理论期望、排序口径与当前结果",
        "",
        "## 直接回答",
        "",
        "给定盘面、概率和规则后，期望可以直接理论计算；本项目这里不应该靠抽样。当前 action EV 的生成方式是枚举初始词条数、初始副词条、强化事件和主属性/位置/套装概率后求和。",
        "",
        "## 本次导出口径",
        "",
        f"- 当前库存来源：`{bundle['scope']['inventory_source']}`",
        f"- 当前库存标签：{bundle['scope']['inventory_label']}",
        f"- 库存限制：{bundle['scope']['inventory_note']}",
        f"- Action EV horizon：{bundle['scope']['action_ev_horizon']}（表中同时列 immediate_EV、option_EV、horizon_EV）",
        f"- 可行性剪枝：{bundle['scope']['lookahead_pruning']}",
        "- 副词条评价：核心顺序 "
        + " > ".join(bundle["character_priority"]["core_order"])
        + "；可用顺序 "
        + " > ".join(bundle["character_priority"]["usable_order"]),
        "- 没有副词条小数系数；排序用优先级向量。",
        "",
        "## 公式",
        "",
        *[f"- {key}: `{value}`" for key, value in bundle["formulas"].items()],
        "",
        "## 当前结论",
        "",
        f"- 推荐 action：{best.get('策略', '-')} {best.get('目标套装', '-')} {best.get('位置', '-')}",
        f"- 推荐依据：排序向量/母盘 {best.get('排序向量/母盘', '-')}；有效/母盘 {best.get('有效/母盘', '-')}",
        f"- 当前 best_loadout value：`{bundle['current_inventory']['best_loadout_value']}`",
        "",
        "## 当前盘面",
        "",
        *_markdown_table(
            ["位置", "套装", "主属性", "有效词条", "质量分", "评级", "副词条"],
            [
                [
                    row["position_name"],
                    row["set_name"],
                    row["main_stat"],
                    row["effective_rolls"],
                    row["weighted_score"],
                    row["rating"],
                    _detail_label(row["substat_details"]),
                ]
                for row in rows
            ],
        ),
        "",
        "## Action EV 结果",
        "",
        *_markdown_table(
            [
                "策略",
                "目标套装",
                "位置",
                "主属性",
                "固定副属性",
                "horizon",
                "immediate_EV",
                "option_EV",
                "horizon_EV",
                "期望提升",
                "排序向量/母盘",
                "有效/母盘",
                "校音器/次",
                "共鸣核/次",
                "相对随机",
            ],
            [
                [
                    row["策略"],
                    row["目标套装"],
                    row["位置"],
                    row.get("主属性", "不固定"),
                    row.get("固定副属性", "不固定"),
                    row.get("horizon", 1),
                    row.get("immediate_EV", row["期望提升"]),
                    row.get("option_EV", "0"),
                    row.get("horizon_EV", row["期望提升"]),
                    row["期望提升"],
                    row["排序向量/母盘"],
                    row["有效/母盘"],
                    row.get("校音器/次", 0.0),
                    row.get("共鸣核/次", 0.0),
                    row["相对随机"],
                ]
                for row in action_rows
            ],
        ),
        "",
        "## 特殊资源全局边际 EV",
        "",
        *_markdown_table(
            [
                "资源",
                "目标套装",
                "位置",
                "主属性",
                "固定副属性",
                "基准action",
                "资源action",
                "边际提升",
                "同等有效省母盘",
                "同等质量省母盘",
                "期望校音器/次",
                "期望共鸣核/次",
            ],
            [
                [
                    row["资源"],
                    row["目标套装"],
                    row["位置"],
                    row["主属性"],
                    row["固定副属性"],
                    row["基准action"],
                    row["资源action"],
                    row["边际提升"],
                    row["同等有效省母盘"],
                    row["同等质量省母盘"],
                    row["期望校音器/次"],
                    row["期望共鸣核/次"],
                ]
                for row in bundle["ui_results"]["resource_marginal_ev_rows"]
            ],
        ),
        "",
        "## 当前仍需注意",
        "",
        *[f"- {item}" for item in bundle["implementation_limits_to_review"]],
        "",
        "## 请 GPT 审核",
        "",
        "1. 单步 action EV 是否等价于枚举求和，而不是模拟。",
        "2. best_loadout 是否按完整传入库存自由选择 6 件，并允许 4+2 在不同位置迁移。",
        "3. `排序向量/母盘` 是否比标量质量分更符合“副词条只排序”的需求。",
        "4. 特殊资源全局边际 EV 是否和 action horizon 口径一致。",
        "",
        f"机器可读 JSON：`{OUTPUT_DIR / 'audit_bundle_theoretical_ev.json'}`",
        f"原始 YAML：`{OUTPUT_DIR / 'raw_inputs'}`",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate GPT audit bundle for action EV.")
    parser.add_argument("--horizon", type=int, default=1, choices=[1, 2])
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bundle = build_audit_bundle(action_ev_horizon=args.horizon)
    bundle["raw_inputs"] = _copy_raw_inputs(OUTPUT_DIR)
    json_path = OUTPUT_DIR / "audit_bundle_theoretical_ev.json"
    md_path = OUTPUT_DIR / "audit_report_for_gpt_theoretical_ev.md"
    json_path.write_text(
        json.dumps(_jsonable(bundle), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(build_markdown(_jsonable(bundle)), encoding="utf-8")
    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
