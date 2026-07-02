from __future__ import annotations

from math import inf
from typing import Any

from gear_optimizer.models import (
    CharacterPreset,
    CurrentGearAnalysis,
    GameRules,
    GearPiece,
    ProbabilityModel,
    StrategyRow,
    position_key,
)
from gear_optimizer.probability import probability_required_substats

MAIN_STAT_MISMATCH_FIXED_MAIN_BONUS = 30.0
MAIN_STAT_MISMATCH_POSITION_BONUS = 12.0


def _missing_target_sets(missing: list[dict]) -> set[str]:
    values: set[str] = set()
    for item in missing:
        values.add(item["set_name"])
        values.update(item.get("set_names", []))
    return values


def _substat_priority_label(character: CharacterPreset, stat: str) -> str:
    return character.priority_group_for(stat) or "不可用"


def _fixed_substat_details(
    character: CharacterPreset,
    fixed_substats: list[str],
) -> list[dict[str, Any]]:
    return [
        {
            "stat": stat,
            "priority": _substat_priority_label(character, stat),
            "priority_rank": character.priority_rank_for(stat),
        }
        for stat in fixed_substats
    ]


def fixed_substat_note(row: StrategyRow | None) -> str:
    if row is None or not row.fixed_substats:
        return "不固定副属性"
    details = row.fixed_substat_details or [
        {"stat": stat, "priority": "未知", "priority_rank": None}
        for stat in row.fixed_substats
    ]
    return "、".join(
        f"{detail['stat']}（{detail['priority']}）"
        for detail in details
    )


def _expected(cost_per_attempt: float, probability: float) -> float:
    if probability <= 0:
        return inf
    return cost_per_attempt / probability


def _candidate_probability(
    game: GameRules,
    probability_model: ProbabilityModel,
    target_position: str | int,
    target_main_stat: str,
    fixed_position: bool,
    fixed_main_stat: bool,
    fixed_substats: list[str],
) -> float:
    breakdown = _probability_breakdown(
        game,
        probability_model,
        target_position,
        target_main_stat,
        fixed_position,
        fixed_main_stat,
        fixed_substats,
    )
    probability = 1.0
    for value in breakdown.values():
        probability *= value
    return probability


def _probability_breakdown(
    game: GameRules,
    probability_model: ProbabilityModel,
    target_position: str | int,
    target_main_stat: str,
    fixed_position: bool,
    fixed_main_stat: bool,
    fixed_substats: list[str],
    target_set_options: list[str] | None = None,
) -> dict[str, float]:
    position_probability = 1.0 if fixed_position else 1.0 / len(game.positions)
    main_stat_probability = 1.0
    if fixed_main_stat:
        main_stat_probability = (
            1.0
            if game.main_stat_probability(target_position, target_main_stat) > 0
            else 0.0
        )
    substat_probability = 1.0
    if fixed_substats:
        available_substats = set(game.available_substats(target_main_stat))
        substat_probability = (
            1.0
            if all(stat in available_substats for stat in fixed_substats)
            else 0.0
        )
    set_option_count = max(len(target_set_options or []), 1)
    set_probability = min(
        probability_model.target_set_probability * set_option_count,
        1.0,
    )
    return {
        "set": set_probability,
        "position": position_probability,
        "main_stat": main_stat_probability,
        "substats": substat_probability,
    }


def _initial_substat_probability(
    game: GameRules,
    probability_model: ProbabilityModel,
    target_main_stat: str,
    fixed_substats: list[str],
) -> float:
    available = game.available_substats(target_main_stat)
    probability = 0.0
    for count, count_probability in probability_model.initial_substat_count_probabilities.items():
        probability += count_probability * probability_required_substats(
            fixed_substats,
            available,
            game.sub_stat_probabilities,
            draw_count=int(count),
        )
    return probability


def _long_term_score(
    game: GameRules,
    character: CharacterPreset,
    target_set: str,
    target_position: str | int,
    target_main_stat: str,
    fixed_main_stat: bool,
    fixed_substats: list[str],
    target_set_options: list[str] | None = None,
) -> float:
    score = 35.0
    preferred = target_main_stat in character.preferred_mains_for(target_position)
    if fixed_main_stat and preferred:
        score += 25.0
    if fixed_main_stat:
        main_probability = game.main_stat_probability(target_position, target_main_stat)
        score += min((1.0 / main_probability) * 2.0, 20.0) if main_probability else 0.0
    if fixed_substats:
        score -= min(len(fixed_substats) * 8.0, 16.0)
    set_plan = character.active_set_plan()
    if set_plan and not set_plan.is_unrestricted:
        target_sets = set(set_plan.target_sets)
        options = set(target_set_options or [target_set])
        if options & target_sets:
            score += 8.0
        else:
            score -= 12.0
    return round(min(score, 100.0), 1)


def _relative_score(
    analysis: CurrentGearAnalysis,
    character: CharacterPreset,
    target_set: str,
    target_position: str | int,
    target_main_stat: str,
    fixed_position: bool,
    fixed_main_stat: bool,
    fixed_substats: list[str],
    target_set_options: list[str] | None = None,
) -> float:
    locked_by_position = {
        position_key(piece.position): piece.locked for piece in analysis.scores
    }
    if locked_by_position.get(position_key(target_position), False):
        return 0.0

    score_by_position = {
        position_key(piece.position): piece.weighted_score for piece in analysis.scores
    }
    piece_by_position = {
        position_key(piece.position): piece for piece in analysis.scores
    }
    current = score_by_position.get(position_key(target_position), 0.0)
    gap = max(character.weighted_target_score - current, 0.0)
    score = gap * 12.0
    if (
        analysis.weakest_position is not None
        and position_key(analysis.weakest_position) == position_key(target_position)
    ):
        score += 22.0
    if fixed_position:
        score += 5.0
    if fixed_main_stat and target_main_stat in character.preferred_mains_for(target_position):
        score += 10.0
    current_piece = piece_by_position.get(position_key(target_position))
    preferred_mains = character.preferred_mains_for(target_position)
    if current_piece is not None and not current_piece.main_stat_preferred:
        if fixed_main_stat and target_main_stat in preferred_mains:
            score += MAIN_STAT_MISMATCH_FIXED_MAIN_BONUS
        elif fixed_position:
            score += MAIN_STAT_MISMATCH_POSITION_BONUS
    if fixed_substats:
        score -= min(len(fixed_substats) * 4.0, 8.0)
    set_by_position = {
        position_key(piece.position): piece.set_name for piece in analysis.scores
    }
    current_set = set_by_position.get(position_key(target_position))
    if analysis.set_plan and not analysis.set_plan["is_unrestricted"]:
        target_sets = set(analysis.set_plan["target_sets"])
        missing_sets = _missing_target_sets(analysis.set_plan["missing"])
        pressure = analysis.set_plan["position_pressures"].get(
            position_key(target_position),
            {},
        ).get("replacement_pressure", 0.0)
        options = set(target_set_options or [target_set])
        if options & missing_sets:
            score += min(pressure * 4.0, 24.0)
        elif options & target_sets:
            score += 2.0
        if current_set not in target_sets and options & target_sets:
            score += 8.0
    return round(min(score, 100.0), 1)


def build_strategy_rows(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    analysis: CurrentGearAnalysis,
    target_position: str | int,
    target_main_stat: str,
    fixed_substats: list[str] | None = None,
    target_set: str | None = None,
    target_set_options: list[str] | None = None,
    include_fixed_substat_strategies: bool = True,
) -> list[StrategyRow]:
    target_set = target_set or character.target_set
    target_set_options = list(dict.fromkeys(target_set_options or [target_set]))
    desired_substats = list(fixed_substats or [])
    if include_fixed_substat_strategies and not desired_substats:
        desired_substats = character.ordered_effective_substats(exclude=target_main_stat)[:2]

    strategy_specs = [
        ("随机位置，不定主属性", False, False, []),
        ("固定位置，不定主属性", True, False, []),
        ("固定位置 + 固定主属性", True, True, []),
    ]
    if include_fixed_substat_strategies and desired_substats:
        strategy_specs.extend(
            [
                ("固定位置 + 固定主属性 + 固定 1 个副属性", True, True, desired_substats[:1]),
                ("固定位置 + 固定主属性 + 固定 2 个副属性", True, True, desired_substats[:2]),
            ]
        )

    rows: list[StrategyRow] = []
    for name, fixed_position, fixed_main, required_substats in strategy_specs:
        probability_breakdown = _probability_breakdown(
            game,
            probability_model,
            target_position,
            target_main_stat,
            fixed_position,
            fixed_main,
            required_substats,
            target_set_options,
        )
        candidate_probability = 1.0
        for probability in probability_breakdown.values():
            candidate_probability *= probability
        expected_attempts = 1.0 / candidate_probability if candidate_probability > 0 else inf
        mother_disk_cost = (
            probability_model.resource_cost(
                "mother_disk_fixed_position_attempt",
                probability_model.resource_cost(
                    "mother_disk_per_attempt",
                    1.0,
                ),
            )
            if fixed_position
            else probability_model.resource_cost(
                "mother_disk_random_position_attempt",
                probability_model.resource_cost(
                    "mother_disk_per_attempt",
                    1.0,
                ),
            )
        )
        mother_disks = mother_disk_cost * expected_attempts
        tuners = (
            probability_model.resource_cost("tuner_per_fixed_main_attempt", 1.0)
            * expected_attempts
            if fixed_main
            else 0.0
        )
        cores = 0.0
        if required_substats:
            cores += (
                probability_model.resource_cost("core_per_fixed_substat_attempt", 1.0)
                * len(required_substats)
            )
        cores = cores * expected_attempts if cores else 0.0

        long_term = _long_term_score(
            game,
            character,
            target_set,
            target_position,
            target_main_stat,
            fixed_main,
            required_substats,
            target_set_options,
        )
        relative = _relative_score(
            analysis,
            character,
            target_set,
            target_position,
            target_main_stat,
            fixed_position,
            fixed_main,
            required_substats,
            target_set_options,
        )
        if relative >= long_term + 10:
            recommendation = "偏当前补弱"
        elif long_term >= relative + 10:
            recommendation = "偏长期最优"
        else:
            recommendation = "长期与当前基本一致"

        rows.append(
            StrategyRow(
                strategy_name=name,
                target_set=target_set,
                target_set_options=target_set_options,
                target_position=target_position,
                target_position_name=game.position_name(target_position),
                target_main_stat=target_main_stat if fixed_main else "不定",
                fixed_position=fixed_position,
                fixed_main_stat=fixed_main,
                fixed_substats=required_substats,
                fixed_substat_details=_fixed_substat_details(character, required_substats),
                probability_breakdown=probability_breakdown,
                candidate_probability=candidate_probability,
                expected_mother_disks=mother_disks,
                expected_tuners=tuners,
                expected_cores=cores,
                long_term_value_score=long_term,
                current_relative_gain_score=relative,
                recommendation=recommendation,
            )
        )
    return rows


def _safe_ratio(current: float, previous: float) -> float | None:
    if previous in {0.0, inf} or current == inf:
        return None
    return current / previous


def _locked_scope(row: StrategyRow) -> str:
    values = []
    if row.fixed_position:
        values.append("位置")
    if row.fixed_main_stat:
        values.append("主属性")
    if row.fixed_substats:
        values.append(f"{len(row.fixed_substats)} 个副属性")
    return " + ".join(values) if values else "不锁定位置/主属性/副属性"


def strategy_target_set_scope(row: StrategyRow) -> str:
    options = row.target_set_options or [row.target_set]
    return " / ".join(options)


def strategy_set_probability_source(row: StrategyRow) -> str:
    options = row.target_set_options or [row.target_set]
    set_probability = row.probability_breakdown.get("set", 0.0)
    if len(options) <= 1:
        return f"单套装 {set_probability:.1%}"
    return f"{len(options)} 个可接受套装合并，套装概率 {set_probability:.1%}"


def _target_set_scope(row: StrategyRow) -> str:
    return strategy_target_set_scope(row)


def _set_probability_source(row: StrategyRow) -> str:
    return strategy_set_probability_source(row)


def _set_option_probability_source(
    probability_model: ProbabilityModel,
    options: list[str],
) -> str:
    set_probability = min(
        probability_model.target_set_probability * max(len(options), 1),
        1.0,
    )
    if len(options) <= 1:
        return f"单套装 {set_probability:.1%}"
    return f"{len(options)} 个可接受套装合并，套装概率 {set_probability:.1%}"


def _preferred_main_summary(game: GameRules, character: CharacterPreset) -> str:
    values = []
    for position in game.positions:
        preferred = character.preferred_mains_for(position.id)
        if preferred:
            values.append(
                f"{position.name}：{' / '.join(preferred)}"
            )
    return "；".join(values) if values else "未限制"


def _substat_weight_summary(character: CharacterPreset) -> str:
    priority = character.substat_priority
    core_stats = priority.core if priority else character.priority_stats()
    usable_stats = priority.usable if priority else []
    if not core_stats and not usable_stats:
        return "未配置"
    parts = []
    if core_stats:
        parts.append(f"核心：{' > '.join(core_stats)}")
    if usable_stats:
        parts.append(f"可用：{' > '.join(usable_stats)}")
    return "；".join(parts)


def _stage_label(item: dict[str, Any]) -> str:
    role = str(item.get("role", ""))
    required = int(item.get("required", 0))
    if role.startswith("core") or required >= 4:
        return "核心 4 件"
    return f"{required} 件套"


def strategy_context_rows(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    analysis: CurrentGearAnalysis,
) -> list[dict[str, Any]]:
    set_plan = analysis.set_plan
    if not set_plan:
        set_plan_name = character.target_set
        set_plan_status = "未配置套装组合，策略按目标套装单独扫描。"
    elif set_plan["is_unrestricted"]:
        set_plan_name = set_plan["name"]
        set_plan_status = "不限套装，调律只看位置、主属性和副词条质量。"
    else:
        status = "已满足" if set_plan["satisfied"] else "未满足"
        set_plan_name = set_plan["name"]
        set_plan_status = (
            f"{status}；策略扫描按方案拆分套装组，并把缺口阶段加入当前提升评分。"
        )

    rows: list[dict[str, Any]] = [
        {
            "项目": "当前套装方案",
            "当前值": set_plan_name,
            "策略影响": set_plan_status,
        },
        {
            "项目": "主属性倾向",
            "当前值": _preferred_main_summary(game, character),
            "策略影响": "全局扫描优先使用这些主属性；未配置的位置才退回该位置第一个主属性。",
        },
        {
            "项目": "副词条优先级",
            "当前值": _substat_weight_summary(character),
            "策略影响": "固定 1/2 个副词条时默认按配置顺位排序，未选择的副词条不参与目标。",
        },
    ]

    if not set_plan or set_plan["is_unrestricted"]:
        return rows

    for index, requirement in enumerate(set_plan["requirements"], start=1):
        options = list(requirement.get("set_names") or [requirement["set_name"]])
        current = int(requirement.get("current", 0))
        required = int(requirement.get("required", 0))
        missing = int(requirement.get("missing", 0))
        displayed_current = min(current, required)
        surplus = max(current - required, 0)
        progress = f"{displayed_current}/{required}"
        if surplus:
            progress = f"{progress}，溢出 {surplus}"
        rows.append(
            {
                "项目": f"套装组 {index}",
                "当前值": (
                    f"{' / '.join(options)}：{progress}，缺 {missing}"
                ),
                "策略影响": _set_option_probability_source(probability_model, options),
            }
        )

    missing = set_plan.get("missing") or []
    if missing:
        target = missing[0]
        target_options = list(target.get("set_names") or [target["set_name"]])
        rows.append(
            {
                "项目": "当前优先阶段",
                "当前值": (
                    f"{_stage_label(target)} -> {' / '.join(target_options)}，"
                    f"缺 {target.get('missing', 0)}"
                ),
                "策略影响": target.get(
                    "stage_priority_basis",
                    "按缺口、进度和可让位盘质量排序。",
                ),
            }
        )
    else:
        rows.append(
            {
                "项目": "当前优先阶段",
                "当前值": "套装组合已满足",
            "策略影响": "当前调律优先转向主属性修正和副词条质量提升。",
            }
        )

    return rows


def _incremental_resource_note(row: StrategyRow, previous: StrategyRow | None) -> str:
    if previous is None:
        return "基础随机筛选。"
    tuner_delta = row.expected_tuners - previous.expected_tuners
    core_delta = row.expected_cores - previous.expected_cores
    notes = []
    if tuner_delta > 0:
        notes.append(f"新增校音器期望 {tuner_delta:.1f}")
    if core_delta > 0:
        notes.append(f"新增共鸣核期望 {core_delta:.1f}")
    if row.expected_mother_disks < previous.expected_mother_disks:
        notes.append("母盘期望下降")
    elif row.expected_mother_disks > previous.expected_mother_disks:
        notes.append("母盘期望上升")
    return "；".join(notes) + "。" if notes else "特殊资源不变。"


def strategy_cost_ladder(rows: list[StrategyRow]) -> list[dict[str, Any]]:
    values = []
    previous: StrategyRow | None = None
    for index, row in enumerate(rows, start=1):
        values.append(
            {
                "stage": index,
                "strategy_name": row.strategy_name,
                "locked_scope": _locked_scope(row),
                "target_set_scope": _target_set_scope(row),
                "set_probability_source": _set_probability_source(row),
                "candidate_probability": row.candidate_probability,
                "expected_mother_disks": row.expected_mother_disks,
                "expected_tuners": row.expected_tuners,
                "expected_cores": row.expected_cores,
                "fixed_substat_note": fixed_substat_note(row),
                "mother_disk_multiplier_vs_previous": (
                    _safe_ratio(row.expected_mother_disks, previous.expected_mother_disks)
                    if previous
                    else None
                ),
                "probability_multiplier_vs_previous": (
                    _safe_ratio(row.candidate_probability, previous.candidate_probability)
                    if previous
                    else None
                ),
                "incremental_note": _incremental_resource_note(row, previous),
            }
        )
        previous = row
    return values


def _strategy_target_sets(
    game: GameRules,
    character: CharacterPreset,
) -> list[str]:
    set_plan = character.active_set_plan()
    if set_plan and not set_plan.is_unrestricted:
        return set_plan.target_sets
    return list(dict.fromkeys([character.target_set] + game.sets))


def _strategy_target_set_groups(
    game: GameRules,
    character: CharacterPreset,
    target_sets: list[str] | None = None,
) -> list[tuple[str, list[str]]]:
    if target_sets is not None:
        return [(set_name, [set_name]) for set_name in target_sets]

    set_plan = character.active_set_plan()
    if set_plan and not set_plan.is_unrestricted:
        groups = []
        for requirement in set_plan.requirements:
            options = list(dict.fromkeys(requirement.set_names))
            label = " / ".join(options)
            groups.append((label, options))
        return groups

    return [(set_name, [set_name]) for set_name in _strategy_target_sets(game, character)]


def _strategy_main_stats(
    game: GameRules,
    character: CharacterPreset,
    target_position: str | int,
) -> list[str]:
    main_options = game.main_stats_for(target_position)
    preferred = [
        stat
        for stat in character.preferred_mains_for(target_position)
        if stat in main_options
    ]
    if preferred:
        return preferred
    return main_options[:1]


def build_strategy_sweep(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    analysis: CurrentGearAnalysis,
    target_sets: list[str] | None = None,
) -> list[StrategyRow]:
    rows: list[StrategyRow] = []
    set_groups_to_scan = _strategy_target_set_groups(game, character, target_sets)
    for target_set, target_set_options in set_groups_to_scan:
        for position in game.positions:
            for main_index, target_main_stat in enumerate(
                _strategy_main_stats(game, character, position.id)
            ):
                target_rows = build_strategy_rows(
                    game,
                    character,
                    probability_model,
                    analysis,
                    target_position=position.id,
                    target_main_stat=target_main_stat,
                    fixed_substats=None,
                    target_set=target_set,
                    target_set_options=target_set_options,
                )
                if main_index:
                    target_rows = [row for row in target_rows if row.fixed_main_stat]
                rows.extend(target_rows)
    return rows


def top_strategy(rows: list[StrategyRow], field: str) -> StrategyRow | None:
    if not rows:
        return None
    if field == "long_term_value_score":
        return max(rows, key=lambda row: (getattr(row, field), -row.candidate_probability))
    if field == "current_relative_gain_score":
        return max(rows, key=lambda row: (getattr(row, field), row.candidate_probability))
    return max(rows, key=lambda row: getattr(row, field))
