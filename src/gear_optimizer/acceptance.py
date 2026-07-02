from __future__ import annotations

import argparse
import json
from pathlib import Path

from gear_optimizer.candidate_ev import evaluate_candidate
from gear_optimizer.game_rules import (
    load_characters,
    load_game,
    load_probability_models,
    validate_candidate_against_game,
    validate_current_gear_against_game,
)
from gear_optimizer.presets import load_candidate_example, load_current_example
from gear_optimizer.reporting import first_version_acceptance_report_markdown
from gear_optimizer.scoring import analyse_current_gear
from gear_optimizer.strategy import build_strategy_sweep, top_strategy

DEFAULT_GAME = "zzz"
DEFAULT_CHARACTER = "zzz_starlight_billy"
DEFAULT_PROBABILITY_MODEL = "zzz_default"
DEFAULT_CURRENT = "examples/zzz_billy_current.yaml"
DEFAULT_CANDIDATE = "examples/zzz_candidate_slot5.yaml"

ACCEPTANCE_CHECKS = [
    ("six_core_questions", "六个核心问题", "## 六个核心问题"),
    ("weakest_piece", "当前 6 件盘哪件最差", "| 我当前 6 件盘哪件最差？ | 6号位 |"),
    ("candidate_upgrade", "候选胚子是否值得强化", "| 这个新胚子还值不值得强化？ | 继续 |"),
    ("fixed_position", "现在应该固定几号位", "现在应该固定几号位？"),
    ("tuner_decision", "校音器该不该用", "校音器：先别急用"),
    ("core_decision", "共鸣核该不该留", "共鸣核：先留"),
    ("alignment", "长期最优和当前提升是否冲突", "长期最优和当前提升是否冲突？"),
    (
        "today_action_summary",
        "今日行动摘要",
        (
            "## 今日行动摘要",
            "| 1 | 先刷/调律 | 先补 2 件套 |",
            "| 2 | 特殊资源 | 校音器先留；共鸣核默认保留 |",
            "| 3 | 候选胚子 | 强化到 +6 |",
            "| 4 | 长期提醒 | 保留长期目标；特殊资源不要追短期弱位 |",
        ),
    ),
    (
        "priority_closure",
        "12 个高优先级问题闭环",
        (
            "## 高优先级问题闭环",
            "| 12 | 桌面结果区需要调律操作期望管理 | 已增加随机/固定位置收益表、固定主属性和固定副属性省母盘阶梯 |",
        ),
    ),
    (
        "next_action",
        "下一步操作卡",
        (
            "## 下一步操作卡",
            "| 1 | 先补 2 件套 |",
            "| 2 | 保留长期目标 |",
            "| 3 | 继续强化候选 |",
        ),
    ),
    (
        "candidate_stop_loss",
        "候选下一跳止损卡",
        (
            "## 候选下一跳止损卡",
            "| 当前动作 | 强化到 +6 |",
            "| 未命中或歪到低价值 | 暂停观察，等资源宽裕再决定 |",
        ),
    ),
    (
        "position_efficiency",
        "随机 vs 固定位置收益效率",
        (
            "## 桌面结果区调律期望管理",
            "### 随机 vs 固定位置收益效率",
            "| 随机位置 | 云岿如我 | 1-6 随机 |",
            "| 固定位置 | 折枝剑歌 | 6号位 |",
        ),
    ),
    (
        "fixed_main_ladder",
        "固定主属性省母盘阶梯",
        (
            "### 固定主属性省母盘阶梯",
            "| 6号位 | 1 | 生命值百分比 |",
            "| +1 |",
        ),
    ),
    (
        "fixed_substat_ladder",
        "固定副属性省母盘阶梯",
        (
            "### 固定副属性省母盘阶梯",
            "| 6号位 | 1 | 生命值百分比 | 暴击率 |",
            "| 暴击率 + 暴击伤害 |",
        ),
    ),
    (
        "initial_tier_explanation",
        "胚子挡位概率解释",
        (
            "### 胚子挡位概率解释",
            "| 5号位 | 3 | 物理伤害 | 4 | 4中3 |",
            "| 6号位 | 1 | 生命值百分比 | 3 | 3中2 |",
        ),
    ),
]


def _pick_by_id(items, item_id: str, label: str):
    for item in items:
        if item.id == item_id:
            return item
    available = ", ".join(item.id for item in items) or "-"
    raise ValueError(f"Unknown {label}: {item_id}. Available: {available}")


def build_first_version_acceptance_report(
    game_id: str = DEFAULT_GAME,
    character_id: str = DEFAULT_CHARACTER,
    probability_model_id: str = DEFAULT_PROBABILITY_MODEL,
    current_path: str | Path = DEFAULT_CURRENT,
    candidate_path: str | Path = DEFAULT_CANDIDATE,
) -> str:
    game = load_game(game_id)
    character = _pick_by_id(load_characters(game_id), character_id, "character")
    probability_model = _pick_by_id(
        load_probability_models(game_id),
        probability_model_id,
        "probability model",
    )
    pieces = load_current_example(current_path)
    candidate = load_candidate_example(candidate_path)

    validate_current_gear_against_game(pieces, game, require_complete=True)
    validate_candidate_against_game(candidate, game)

    analysis = analyse_current_gear(pieces, game, character)
    strategy_rows = build_strategy_sweep(game, character, probability_model, analysis)
    current_best = top_strategy(strategy_rows, "current_relative_gain_score")
    long_term_best = top_strategy(strategy_rows, "long_term_value_score")
    tuner_best = top_strategy(
        [row for row in strategy_rows if row.fixed_main_stat and row.expected_tuners > 0],
        "current_relative_gain_score",
    )
    core_best = top_strategy(
        [row for row in strategy_rows if row.expected_cores > 0],
        "current_relative_gain_score",
    )
    result = evaluate_candidate(candidate, game, character)

    return first_version_acceptance_report_markdown(
        game,
        character,
        candidate,
        result,
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
        probability_model=probability_model,
    )


def _as_markers(marker: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(marker, str):
        return (marker,)
    return marker


def acceptance_check_rows(report: str) -> list[dict[str, str]]:
    rows = []
    for check_id, label, marker in ACCEPTANCE_CHECKS:
        markers = _as_markers(marker)
        missing = [item for item in markers if item not in report]
        passed = not missing
        rows.append(
            {
                "id": check_id,
                "检查项": label,
                "状态": "ok" if passed else "missing",
                "证据": "；".join(markers),
                "缺失": "；".join(missing),
            }
        )
    return rows


def acceptance_checks_pass(rows: list[dict[str, str]]) -> bool:
    return all(row["状态"] == "ok" for row in rows)


def format_acceptance_checks(rows: list[dict[str, str]]) -> str:
    width = max(len(row["检查项"]) for row in rows)
    return "\n".join(
        f"{row['检查项']:<{width}}  {row['状态']:<7}  {row['证据']}"
        for row in rows
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an algorithm acceptance report for gacha-gear-optimizer.",
    )
    parser.add_argument("--game", default=DEFAULT_GAME, help="Game id.")
    parser.add_argument("--character", default=DEFAULT_CHARACTER, help="Character preset id.")
    parser.add_argument(
        "--probability-model",
        default=DEFAULT_PROBABILITY_MODEL,
        help="Probability model id.",
    )
    parser.add_argument("--current", default=DEFAULT_CURRENT, help="Current gear YAML path.")
    parser.add_argument("--candidate", default=DEFAULT_CANDIDATE, help="Candidate YAML path.")
    parser.add_argument(
        "--output",
        default="",
        help="Optional output Markdown path. Omit to print to stdout.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the generated report contains the algorithm acceptance evidence.",
    )
    parser.add_argument(
        "--check-json",
        default="",
        help="Optional path to write machine-readable acceptance check rows.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_first_version_acceptance_report(
        game_id=args.game,
        character_id=args.character,
        probability_model_id=args.probability_model,
        current_path=args.current,
        candidate_path=args.candidate,
    )
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"Wrote acceptance report: {output_path}")
    else:
        print(report)
    if args.check or args.check_json:
        rows = acceptance_check_rows(report)
        if args.check_json:
            json_path = Path(args.check_json)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"Wrote acceptance checks: {json_path}")
        if args.check:
            print(format_acceptance_checks(rows))
        return 0 if acceptance_checks_pass(rows) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
