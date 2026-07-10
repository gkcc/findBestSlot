from __future__ import annotations

from typing import Any

from gear_optimizer.models import CharacterPreset, CurrentGearAnalysis, GameRules, StrategyRow
from gear_optimizer.strategy import (
    strategy_set_probability_source,
    strategy_target_set_scope,
)


def _requirement_name(item: dict) -> str:
    if item.get("set_names"):
        return " / ".join(item["set_names"])
    return item["set_name"]


def _stage_name(item: dict) -> str:
    role = item.get("role", "")
    pieces = item.get("required", 0)
    if role.startswith("core") or pieces >= 4:
        return "核心 4 件"
    if role.startswith("flex") or role.startswith("pair") or pieces == 2:
        return "2 件套"
    return f"{pieces} 件套"


def set_plan_lock_conflict_text(set_plan: dict | None) -> str:
    if not set_plan or set_plan.get("is_unrestricted"):
        return ""
    if set_plan.get("feasible_with_locks", True):
        return ""

    locked_count = set_plan.get("locked_piece_count", 0)
    unlocked_count = set_plan.get("unlocked_position_count", 0)
    needed = set_plan.get("minimum_unlocked_needed", 0)
    gap = set_plan.get("locked_capacity_gap", 0)
    conflict_sets = {
        item["set_name"]
        for item in set_plan.get("locked_conflicts", [])
        if item.get("set_name")
    }
    conflict_note = (
        f" 锁定冲突套装：{' / '.join(sorted(conflict_sets))}。"
        if conflict_sets
        else ""
    )
    return (
        f"锁定冲突：已锁定 {locked_count} 件，剩余可调整 {unlocked_count} 件；"
        f"当前方案至少还需要 {needed} 个可调整位置，差 {gap} 件。"
        f"{conflict_note}建议先解锁冲突盘、切换套装方案，或接受过渡。"
    )


def set_plan_step_text(analysis: CurrentGearAnalysis) -> str:
    if not analysis.set_plan:
        return "套装阶段：当前角色没有设置套装组合，先按主属性和副词条质量补弱。"
    if analysis.set_plan["is_unrestricted"]:
        return "套装阶段：当前完全不限套装，调律策略只看位置、主属性和副词条期望。"

    lock_conflict = set_plan_lock_conflict_text(analysis.set_plan)
    if analysis.set_plan["satisfied"]:
        if analysis.relative_priority:
            top = analysis.relative_priority[0]
            return (
                f"套装阶段：{analysis.set_plan['name']} 已满足，"
                f"下一步优先看 {top['position_name']} 的主属性和副词条质量提升。"
                f"{' ' + lock_conflict if lock_conflict else ''}"
            )
        text = f"套装阶段：{analysis.set_plan['name']} 已满足，下一步按主属性和副词条质量优化。"
        return f"{text} {lock_conflict}" if lock_conflict else text

    missing = analysis.set_plan["missing"]
    if not missing:
        text = f"套装阶段：{analysis.set_plan['name']} 接近满足，优先处理评分最低的位置。"
        return f"{text} {lock_conflict}" if lock_conflict else text

    target = missing[0]
    stage = _stage_name(target)
    requirement = _requirement_name(target)
    prefix = "先补核心 4 件" if "4" in stage else "先补 2 件套"
    text = (
        f"套装阶段：{prefix}，目标是 {requirement} "
        f"{target['current']}/{target['required']}，还差 {target['missing']} 件。"
    )
    top = target.get("stage_replacement")
    if top:
        text += (
            f" 当前最适合让位的是 {top['position']} 号位，"
            f"让位压力 {top['replacement_pressure']:g}。"
        )
    if lock_conflict:
        text += f" {lock_conflict}"
    return text


def set_plan_stage_rows(
    game: GameRules,
    analysis: CurrentGearAnalysis,
) -> list[dict[str, Any]]:
    if not analysis.set_plan:
        return [
            {
                "order": 1,
                "stage": "未配置",
                "target": "-",
                "progress": "-",
                "missing": "-",
                "priority_score": "-",
                "algorithm_basis": "未配置套装方案，不做阶段排序。",
                "action": "按主属性和副词条质量补弱",
                "replacement": "-",
                "basis": "当前角色没有设置套装方案。",
            }
        ]
    if analysis.set_plan["is_unrestricted"]:
        return [
            {
                "order": 1,
                "stage": "不限套装",
                "target": analysis.set_plan["name"],
                "progress": "-",
                "missing": 0,
                "priority_score": "-",
                "algorithm_basis": "当前完全不限套装，不做阶段排序。",
                "action": "按主属性和副词条质量补弱",
                "replacement": "-",
                "basis": "当前方案不约束 4+2 或 2+2+2。",
            }
        ]

    suggestions = analysis.set_plan.get("suggested_replacements", [])
    top_suggestion = suggestions[0] if suggestions else None
    first_missing = (
        analysis.set_plan["missing"][0]
        if analysis.set_plan.get("missing")
        else None
    )
    rows = []
    lock_conflict = set_plan_lock_conflict_text(analysis.set_plan)
    if lock_conflict:
        rows.append(
            {
                "order": 1,
                "stage": "锁定冲突",
                "target": analysis.set_plan["name"],
                "progress": (
                    f"{analysis.set_plan.get('unlocked_position_count', 0)} 可调整 / "
                    f"{analysis.set_plan.get('minimum_unlocked_needed', 0)} 需要"
                ),
                "missing": analysis.set_plan.get("locked_capacity_gap", 0),
                "priority_score": "-",
                "algorithm_basis": "先判定锁定盘是否让当前套装方案可完成。",
                "action": "先处理锁定盘",
                "replacement": "解锁 / 改方案 / 接受过渡",
                "basis": lock_conflict,
            }
        )

    missing_items = analysis.set_plan.get("missing", [])
    ordered_items = missing_items + [
        item
        for item in analysis.set_plan["requirements"]
        if item not in missing_items
    ]

    for order, item in enumerate(ordered_items, start=len(rows) + 1):
        is_missing = item["missing"] > 0
        is_first_missing = first_missing is item
        algorithm_basis = item.get("stage_priority_basis", "-")
        if not is_missing:
            action = "已满足，除非盘面质量很差否则保留"
            replacement = "保留达标件"
            basis = algorithm_basis
        elif is_first_missing:
            action = "优先补齐"
            stage_suggestion = item.get("stage_replacement") or top_suggestion
            if stage_suggestion:
                position_name = game.position_name(stage_suggestion["position"])
                replacement = f"{position_name} -> {stage_suggestion['target_set']}"
                basis = (
                    f"{algorithm_basis} "
                    f"{position_name} 当前 {stage_suggestion['current_set']}，"
                    f"质量分 {stage_suggestion['weighted_score']:g}，"
                    f"让位压力 {stage_suggestion['replacement_pressure']:g}。"
                )
            else:
                replacement = "先找低分或偏离主属性的位置"
                basis = f"{algorithm_basis} 该阶段有缺口，但当前没有明显可让位盘。"
        else:
            action = "后续补齐"
            replacement = "先完成前一缺口"
            basis = f"{algorithm_basis} 当前优先级低于前面的未满足阶段。"

        rows.append(
            {
                "order": order,
                "stage": _stage_name(item),
                "target": _requirement_name(item),
                "progress": f"{item['current']}/{item['required']}",
                "missing": item["missing"],
                "priority_score": item.get("stage_priority_score", 0.0),
                "algorithm_basis": algorithm_basis,
                "action": action,
                "replacement": replacement,
                "basis": basis,
            }
        )
    return rows


def _strategy_target_label(row: StrategyRow | None) -> str:
    if row is None:
        return "暂无策略"
    main = row.target_main_stat if row.fixed_main_stat else "不定主属性"
    return f"{strategy_target_set_scope(row)} {row.target_position_name} {main}"


def _strategy_scope_label(row: StrategyRow | None) -> str:
    return row.strategy_name if row is not None else "暂无策略"


def _strategy_resource_hint(row: StrategyRow | None) -> str:
    if row is None:
        return "先补齐盘面信息，再判断资源投入。"
    if row.expected_cores > 0:
        return "该目标需要固定副属性，默认先保留共鸣核，只把它当极限毕业选项。"
    if row.expected_tuners > 0:
        return "校音器只用于锁主属性；若当前补弱和长期目标冲突，优先留给长期目标。"
    return "先用母盘和固定位置自然筛，不急着消耗校音器或共鸣核。"


def _stage_action_text(item: dict[str, Any]) -> str:
    stage = _stage_name(item)
    return "先补核心 4 件" if "4" in stage else "先补 2 件套"


def set_plan_next_action_rows(
    game: GameRules,
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    set_plan = analysis.set_plan

    if not set_plan:
        rows.append(
            {
                "order": 1,
                "action": "按主属性 / 副词条补弱",
                "entry": "调律策略比较 -> 全局调律推荐 / 桌面结果区调律期望管理",
                "target": _strategy_target_label(current_best),
                "tuning_scope": _strategy_scope_label(current_best),
                "resource_hint": _strategy_resource_hint(current_best),
                "reason": "当前角色未配置套装组合，先按主属性命中和副词条质量缺口排序。",
            }
        )
    elif set_plan["is_unrestricted"]:
        rows.append(
            {
                "order": 1,
                "action": "不限套装补弱",
                "entry": "调律策略比较 -> 全局调律推荐 / 桌面结果区调律期望管理",
                "target": _strategy_target_label(current_best),
                "tuning_scope": _strategy_scope_label(current_best),
                "resource_hint": _strategy_resource_hint(current_best),
                "reason": "当前方案完全不限套装，调律目标只由位置、主属性和副词条质量决定。",
            }
        )
    else:
        lock_conflict = set_plan_lock_conflict_text(set_plan)
        if lock_conflict:
            rows.append(
                {
                    "order": 1,
                    "action": "先处理锁定盘",
                    "entry": "当前装备评分 -> 盘面方块；侧栏 -> 目标套装方案",
                    "target": set_plan["name"],
                    "tuning_scope": "暂停套装调律投入",
                    "resource_hint": "先不要为当前套装方案消耗校音器或共鸣核。",
                    "reason": lock_conflict,
                }
            )
        elif set_plan["satisfied"]:
            rows.append(
                {
                    "order": 1,
                    "action": "套装已满足，转向质量补强",
                    "entry": "调律策略比较 -> 全局调律推荐 / 桌面结果区调律期望管理",
                    "target": _strategy_target_label(current_best),
                    "tuning_scope": _strategy_scope_label(current_best),
                    "resource_hint": _strategy_resource_hint(current_best),
                    "reason": "当前 4+2 / 2+2+2 目标已达成，下一步只替换主属性偏离或质量分明显落后的盘。",
                }
            )
        else:
            missing = set_plan.get("missing") or []
            if not missing:
                rows.append(
                    {
                        "order": 1,
                        "action": "按当前评分补弱",
                        "entry": "调律策略比较 -> 全局调律推荐 / 桌面结果区调律期望管理",
                        "target": _strategy_target_label(current_best),
                        "tuning_scope": _strategy_scope_label(current_best),
                        "resource_hint": _strategy_resource_hint(current_best),
                        "reason": "套装方案没有显式缺口，当前按主属性偏离和质量分缺口排序。",
                    }
                )
                target = None
            else:
                target = missing[0]
            if target is None:
                pass
            else:
                replacement = target.get("stage_replacement")
                if replacement:
                    position_name = game.position_name(replacement["position"])
                    target_label = (
                        f"{_requirement_name(target)} {position_name} "
                        f"（{replacement['current_set']} -> {replacement['target_set']}）"
                    )
                    replacement_reason = (
                        f"{position_name} 当前 {replacement['current_set']}，"
                        f"质量分 {replacement['weighted_score']:g}，"
                        f"让位压力 {replacement['replacement_pressure']:g}。"
                    )
                else:
                    target_label = _requirement_name(target)
                    replacement_reason = "当前没有明显低成本让位盘，先筛同阶段候选再比较。"
                rows.append(
                    {
                        "order": 1,
                        "action": _stage_action_text(target),
                        "entry": "调律策略比较 -> 套装阶段拆解 / 桌面结果区调律期望管理",
                        "target": target_label,
                        "tuning_scope": _strategy_scope_label(current_best),
                        "resource_hint": _strategy_resource_hint(current_best),
                        "reason": (
                            f"{_stage_name(target)}缺 {target.get('missing', 0)} 件。"
                            f"{replacement_reason}"
                            f"{target.get('stage_priority_basis', '')}"
                        ),
                    }
                )

    if long_term_best is not None:
        rows.append(
            {
                "order": len(rows) + 1,
                "action": "保留长期目标",
                "entry": "调律策略比较 -> 长期目标 / 桌面结果区调律期望管理",
                "target": _strategy_target_label(long_term_best),
                "tuning_scope": _strategy_scope_label(long_term_best),
                "resource_hint": (
                    "长期目标与当前补弱一致，可以合并投入。"
                    if current_best is not None
                    and strategy_target_set_scope(current_best)
                    == strategy_target_set_scope(long_term_best)
                    and current_best.target_position == long_term_best.target_position
                    else _strategy_resource_hint(long_term_best)
                ),
                "reason": strategy_alignment_text(current_best, long_term_best),
            }
        )

    return rows


def strategy_text(
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    game: GameRules,
    character: CharacterPreset,
) -> tuple[str, str]:
    if current_best is None or long_term_best is None:
        return ("暂无当前策略推荐。", "暂无长期策略推荐。")

    current_main = (
        current_best.target_main_stat
        if current_best.fixed_main_stat
        else "不定主属性"
    )
    long_main = (
        long_term_best.target_main_stat
        if long_term_best.fixed_main_stat
        else "不定主属性"
    )
    current_text = (
        f"当前相对提升最优：{current_best.strategy_name}，"
        f"{strategy_target_set_scope(current_best)} {current_best.target_position_name}，"
        f"{current_main}。原因：当前评分缺口最大，"
        f"{strategy_set_probability_source(current_best)}，"
        f"当前提升评分为 {current_best.current_relative_gain_score:g}。"
    )
    long_text = (
        f"长期绝对最优：{long_term_best.strategy_name}，"
        f"{strategy_target_set_scope(long_term_best)} {long_term_best.target_position_name} "
        f"{long_main}。原因：主属性稀缺度、有效副词条约束和理论上限综合评分最高，"
        f"{strategy_set_probability_source(long_term_best)}，"
        f"长期价值评分为 {long_term_best.long_term_value_score:g}。"
    )
    if character.notes:
        long_text += f" {character.notes}"
    return current_text, long_text


def strategy_alignment_text(
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
) -> str:
    if current_best is None or long_term_best is None:
        return "长期目标和当前补弱关系：暂无足够策略结果。"

    same_position = current_best.target_position == long_term_best.target_position
    same_set = current_best.target_set == long_term_best.target_set
    same_main = (
        not current_best.fixed_main_stat
        or not long_term_best.fixed_main_stat
        or current_best.target_main_stat == long_term_best.target_main_stat
    )
    if same_position and same_set and same_main:
        return (
            "长期目标和当前补弱基本一致：可以围绕同一位置继续投入，"
            "资源使用不会明显偏离长期上限。"
        )

    current_resource = (
        "校音器"
        if current_best.expected_tuners > 0 and current_best.expected_cores == 0
        else "共鸣核"
        if current_best.expected_cores > 0
        else "母盘"
    )
    long_resource = (
        "共鸣核"
        if long_term_best.expected_cores > 0
        else "校音器"
        if long_term_best.expected_tuners > 0
        else "母盘"
    )
    return (
        "长期目标和当前补弱存在冲突："
        f"当前更想补 {current_best.target_set} {current_best.target_position_name}，"
        f"长期更偏向 {long_term_best.target_set} {long_term_best.target_position_name}"
        f" {long_term_best.target_main_stat}。"
        f"建议短期用{current_resource}处理当前短板，"
        f"把{long_resource}优先留给长期目标；特殊资源不要追着短期弱位乱花。"
    )


def _expected_label(value: float) -> str:
    if value == float("inf"):
        return "∞"
    return f"{value:.1f}"


def _same_resource_target(row: StrategyRow, other: StrategyRow) -> bool:
    same_main = (
        not row.fixed_main_stat
        or not other.fixed_main_stat
        or row.target_main_stat == other.target_main_stat
    )
    return (
        row.target_set == other.target_set
        and row.target_position == other.target_position
        and same_main
    )


def resource_decision_text(
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
) -> tuple[str, str]:
    if tuner_best is None:
        tuner_text = "校音器：暂无需要固定主属性的高价值策略，先用母盘和固定位置自然筛。"
    elif long_term_best is not None and not _same_resource_target(tuner_best, long_term_best):
        tuner_text = (
            f"校音器：先别急用。短期最想锁 {tuner_best.target_set} "
            f"{tuner_best.target_position_name} {tuner_best.target_main_stat}，"
            f"但长期目标更偏 {long_term_best.target_set} "
            f"{long_term_best.target_position_name} {long_term_best.target_main_stat}。"
        )
    elif tuner_best.current_relative_gain_score >= 80:
        tuner_text = (
            f"校音器：可以用在 {tuner_best.target_set} "
            f"{tuner_best.target_position_name} {tuner_best.target_main_stat}。"
            f"原因：当前提升评分 {tuner_best.current_relative_gain_score:g}，"
            f"固定主属性期望消耗约 {_expected_label(tuner_best.expected_tuners)} 个校音器。"
        )
    elif tuner_best.current_relative_gain_score >= 55:
        tuner_text = (
            f"校音器：可以观察 {tuner_best.target_set} "
            f"{tuner_best.target_position_name} {tuner_best.target_main_stat}，"
            f"但当前提升评分只有 {tuner_best.current_relative_gain_score:g}，不建议重仓。"
        )
    else:
        tuner_text = (
            f"校音器：先攒着。当前最佳固定主属性目标是 {tuner_best.target_position_name} "
            f"{tuner_best.target_main_stat}，"
            f"提升评分 {tuner_best.current_relative_gain_score:g}，优先级还不够高。"
        )

    if core_best is None:
        core_text = "共鸣核：暂无需要固定副属性的策略，先保留。"
    elif long_term_best is not None and _same_resource_target(core_best, long_term_best):
        core_text = (
            f"共鸣核：仍建议保留为主。它只对应固定副属性，当前可观察的长期目标是 "
            f"{core_best.target_set} {core_best.target_position_name} "
            f"{core_best.target_main_stat}，期望消耗约 "
            f"{_expected_label(core_best.expected_cores)} 个共鸣核。"
        )
    else:
        core_text = (
            f"共鸣核：先留。当前候选 {core_best.target_position_name} "
            f"{core_best.target_main_stat} 需要锁副属性，"
            "不作为默认补弱路径；等它和长期目标完全一致且母盘差距很大时再考虑。"
        )

    return tuner_text, core_text
