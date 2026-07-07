from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from gear_optimizer.models import CharacterPreset, GameRules, GearPiece, ProbabilityModel, position_key
from gear_optimizer.portfolio_models import (
    PortfolioActionRow,
    PortfolioGain,
    PortfolioMode,
    PortfolioPieceCheckRow,
    PortfolioTarget,
)
from gear_optimizer.position_ev import (
    ActionSpec,
    EvState,
    _action_costs,
    _action_main_label,
    _action_position_items,
    _action_position_label,
    _action_progress_label,
    _action_substat_label,
    _action_type_label,
    _advance_existing_roll_states,
    _best_combo_rows,
    _cached_best_combo_value,
    _candidate_inventory_row,
    _dedupe_action_specs,
    _fresh_piece_outcome_distribution,
    _generation_action_specs,
    _inventory_piece_id,
    _inventory_row_signature,
    _is_loadout_candidate,
    _normalise_inventory_rows,
    _piece_contribution_key,
    _positive_gain,
    _roll_state_from_piece,
    _set_distribution,
    _upgrade_action_specs,
)

_EPSILON = 1e-9
PortfolioActionScope = Literal["tuning", "upgrade", "all"]


@dataclass(frozen=True)
class BuildProgressAudit:
    gain: float = 0.0
    set_progress_detail: str = "-"
    position_coverage_detail: str = "-"
    main_stat_hit_detail: str = "-"
    candidate_observation_detail: str = "-"


def _portfolio_delta_scalar(gain_vector: tuple[float, ...]) -> float:
    return sum(max(float(value), 0.0) for value in gain_vector)


def _add_delta_vectors(left: list[float], right: tuple[float, ...], probability: float) -> list[float]:
    if not left:
        left = [0.0 for _ in right]
    return [
        left[index] + max(float(value), 0.0) * probability
        for index, value in enumerate(right)
    ]


def _portfolio_action_specs(
    game: GameRules,
    targets: Sequence[PortfolioTarget],
    base_rows: list[dict],
    action_scope: PortfolioActionScope,
) -> list[ActionSpec]:
    specs: list[ActionSpec] = []
    if action_scope in {"tuning", "all"}:
        for target in targets:
            specs.extend(
                _generation_action_specs(
                    game,
                    target.character,
                    include_fixed_main=True,
                    include_fixed_substats=False,
                )
            )
    if action_scope in {"upgrade", "all"}:
        specs.extend(_upgrade_action_specs(base_rows, game))
    return _dedupe_action_specs(specs)


def _target_rows_for_pool(
    current_pieces: Sequence[GearPiece],
    inventory_pieces: Sequence[GearPiece],
    game: GameRules,
    character: CharacterPreset,
) -> list[dict]:
    rows = []
    for index, piece in enumerate(current_pieces):
        row = _candidate_inventory_row(piece, game, character, source="current")
        row["_inventory_id"] = f"current:{index}"
        row["_piece"] = piece
        rows.append(row)
    for index, piece in enumerate(inventory_pieces):
        row = _candidate_inventory_row(piece, game, character, source="inventory")
        row["_inventory_id"] = f"inventory:{index}"
        row["_piece"] = piece
        rows.append(row)
    return _normalise_inventory_rows(rows, game, character)


def _target_rows(
    pieces: Sequence[GearPiece],
    game: GameRules,
    character: CharacterPreset,
    current_count: int,
) -> list[dict]:
    rows = []
    for index, piece in enumerate(pieces):
        source = "current" if index < current_count else "inventory"
        row = _candidate_inventory_row(piece, game, character, source=source)
        row["_inventory_id"] = _inventory_piece_id(index)
        row["_piece"] = piece
        rows.append(row)
    return _normalise_inventory_rows(rows, game, character)


def _upgrade_piece_distribution(
    row: dict,
    game: GameRules,
) -> list[tuple[GearPiece, float]]:
    piece = row.get("_piece")
    if not isinstance(piece, GearPiece) or piece.level >= game.enhancement.max_level:
        return []
    initial_state = _roll_state_from_piece(game, piece)
    final_states = _advance_existing_roll_states(game, piece, {initial_state: 1.0})
    grouped: defaultdict[tuple[tuple[str, int], ...], float] = defaultdict(float)
    for state, probability in final_states.items():
        grouped[state] += probability
    return [
        (
            GearPiece(
                position=piece.position,
                set_name=piece.set_name,
                main_stat=piece.main_stat,
                level=game.enhancement.max_level,
                substats=[{"stat": stat, "rolls": rolls} for stat, rolls in state],
                locked=piece.locked,
                initial_substat_count=piece.initial_substat_count,
            ),
            probability,
        )
        for state, probability in grouped.items()
        if probability > 0
    ]


def _raw_outcome_piece_distribution(
    spec: ActionSpec,
    base_rows: list[dict],
    game: GameRules,
    probability_model: ProbabilityModel,
) -> list[tuple[GearPiece, float]]:
    if spec.upgrade_inventory_id:
        target = next(
            (row for row in base_rows if row.get("_inventory_id") == spec.upgrade_inventory_id),
            None,
        )
        return _upgrade_piece_distribution(target, game) if target is not None else []

    distribution: list[tuple[GearPiece, float]] = []
    for position, position_probability in _action_position_items(game, spec.target_position):
        valid_main_stats = game.main_stats_for(position)
        main_stats = [spec.fixed_main_stat] if spec.fixed_main_stat else valid_main_stats
        for set_name, set_probability in _set_distribution(probability_model, list(spec.set_options)):
            if not game.set_available_for_position(set_name, position):
                continue
            for main_stat in main_stats:
                if main_stat not in valid_main_stats:
                    continue
                main_probability = (
                    1.0
                    if spec.fixed_main_stat
                    else game.main_stat_probability(position, main_stat)
                )
                if main_probability <= 0:
                    continue
                for piece, piece_probability in _fresh_piece_outcome_distribution(
                    game,
                    position,
                    set_name,
                    main_stat,
                    probability_model,
                    required_substats=spec.required_substats,
                ):
                    probability = (
                        position_probability
                        * set_probability
                        * main_probability
                        * piece_probability
                    )
                    if probability > 0:
                        distribution.append((piece, probability))
    return distribution


def _coarse_outcome_piece_distribution(
    spec: ActionSpec,
    game: GameRules,
    probability_model: ProbabilityModel,
) -> list[tuple[GearPiece, float]]:
    distribution: list[tuple[GearPiece, float]] = []
    for position, position_probability in _action_position_items(game, spec.target_position):
        valid_main_stats = game.main_stats_for(position)
        main_stats = [spec.fixed_main_stat] if spec.fixed_main_stat else valid_main_stats
        substats = [
            {"stat": stat, "rolls": 0}
            for stat in spec.required_substats
            if stat in game.available_substats(str(spec.fixed_main_stat or ""), [])
            or stat in game.sub_stats
        ]
        for set_name, set_probability in _set_distribution(probability_model, list(spec.set_options)):
            if not game.set_available_for_position(set_name, position):
                continue
            for main_stat in main_stats:
                if main_stat not in valid_main_stats:
                    continue
                main_probability = (
                    1.0
                    if spec.fixed_main_stat
                    else game.main_stat_probability(position, main_stat)
                )
                probability = position_probability * set_probability * main_probability
                if probability <= 0:
                    continue
                distribution.append(
                    (
                        GearPiece(
                            position=position,
                            set_name=set_name,
                            main_stat=main_stat,
                            level=game.enhancement.max_level,
                            substats=substats,
                            initial_substat_count=max(len(substats), 3),
                        ),
                        probability,
                    )
                )
    return distribution


def _row_enters_best_loadout(row: dict, inventory: list[dict], game: GameRules, character: CharacterPreset) -> bool:
    signature = _inventory_row_signature(row)
    combo = _best_combo_rows(inventory, game, character)
    return any(_inventory_row_signature(combo_row) == signature for combo_row in combo)


def _candidate_rows_for_position(rows: list[dict], game: GameRules, position: object) -> list[dict]:
    key = position_key(position)
    return [
        row
        for row in rows
        if _is_loadout_candidate(row, game)
        and position_key(row["position"]) == key
    ]


def _same_position_set_blocker(
    rows: list[dict],
    candidate_row: dict,
    game: GameRules,
) -> dict | None:
    position = position_key(candidate_row["position"])
    set_name = str(candidate_row["set_name"])
    for row in rows:
        if not _is_loadout_candidate(row, game):
            continue
        if position_key(row["position"]) != position or str(row["set_name"]) != set_name:
            continue
        if _piece_contribution_key(row) >= _piece_contribution_key(candidate_row):
            return row
    return None


def _frontier_count_for_sets(
    rows: list[dict],
    game: GameRules,
    set_names: Sequence[str],
    required: int,
) -> int:
    allowed = set(set_names)
    positions = {
        position_key(row["position"])
        for row in rows
        if _is_loadout_candidate(row, game)
        and str(row["set_name"]) in allowed
    }
    return min(len(positions), required)


def _build_progress_audit(
    rows: list[dict],
    target: PortfolioTarget,
    game: GameRules,
    outcome_piece: GearPiece,
) -> BuildProgressAudit:
    position_name = game.position_name(outcome_piece.position)
    try:
        set_available = game.set_available_for_position(outcome_piece.set_name, outcome_piece.position)
    except KeyError:
        set_available = False
    if not set_available:
        detail = f"不计入进度：{outcome_piece.set_name}不可用于{position_name}"
        return BuildProgressAudit(
            set_progress_detail=detail,
            position_coverage_detail=detail,
            main_stat_hit_detail=detail,
            candidate_observation_detail=detail,
        )

    candidate_row = _candidate_inventory_row(outcome_piece, game, target.character, source="outcome")
    blocker = _same_position_set_blocker(rows, candidate_row, game)
    if blocker is not None:
        detail = f"不计入进度：{position_name}已有更优或等价的{outcome_piece.set_name}盘"
        return BuildProgressAudit(
            set_progress_detail=detail,
            position_coverage_detail=f"不计入覆盖：{detail}",
            main_stat_hit_detail=f"不计入主属性：{detail}",
            candidate_observation_detail=f"不计入观察：{detail}",
        )

    plan = target.character.active_set_plan()
    set_signal = False
    set_detail = "不限套装，不计入套装进度"
    if plan is not None and not plan.is_unrestricted:
        matching_requirements = [
            requirement
            for requirement in plan.requirements
            if outcome_piece.set_name in requirement.set_names
        ]
        if not matching_requirements:
            detail = f"不计入进度：{outcome_piece.set_name}不在目标套装方案{plan.name}中"
            return BuildProgressAudit(
                set_progress_detail=detail,
                position_coverage_detail=detail,
                main_stat_hit_detail=detail,
                candidate_observation_detail=detail,
            )
        next_rows = [*rows, candidate_row]
        progress_details: list[str] = []
        for requirement in matching_requirements:
            before = _frontier_count_for_sets(rows, game, requirement.set_names, requirement.pieces)
            after = _frontier_count_for_sets(next_rows, game, requirement.set_names, requirement.pieces)
            label = " / ".join(requirement.set_names)
            if after > before:
                set_signal = True
                progress_details.append(f"{label}目标{requirement.pieces}件，当前可行{before}件，加入后可行{after}件")
            else:
                progress_details.append(f"不计入进度：{label}目标{requirement.pieces}件仍为{before}件")
        set_detail = "；".join(progress_details)

    position_signal = not _candidate_rows_for_position(rows, game, outcome_piece.position)
    position_detail = (
        f"覆盖缺失位置：{position_name}"
        if position_signal
        else f"{position_name}已有可用候选，不计入位置覆盖"
    )

    preferred_mains = target.character.preferred_mains_for(outcome_piece.position)
    main_signal = bool(preferred_mains and outcome_piece.main_stat in preferred_mains)
    main_detail = (
        f"命中目标主属性：{position_name}{outcome_piece.main_stat}"
        if main_signal
        else f"{position_name}主属性{outcome_piece.main_stat}未命中目标"
        if preferred_mains
        else f"{position_name}未配置主属性限制"
    )

    effective_stats = [
        line.stat
        for line in outcome_piece.substats
        if target.character.is_effective(line.stat)
    ]
    observation_signal = bool(effective_stats)
    observation_detail = (
        "有效胚子可观察：" + "、".join(dict.fromkeys(effective_stats))
        if observation_signal
        else "副属性暂未命中有效词条"
    )

    gain = 1.0 if any([set_signal, position_signal, main_signal, observation_signal]) else 0.0
    return BuildProgressAudit(
        gain=gain,
        set_progress_detail=set_detail,
        position_coverage_detail=position_detail,
        main_stat_hit_detail=main_detail,
        candidate_observation_detail=observation_detail,
    )


def _summarize_details(details: Sequence[str]) -> str:
    values = [
        detail
        for detail in dict.fromkeys(str(item) for item in details)
        if detail and detail != "-"
    ]
    if not values:
        return "-"
    if len(values) <= 3:
        return "；".join(values)
    return "；".join(values[:3]) + f"；另{len(values) - 3}项"


def _target_gain_for_outcome(
    rows: list[dict],
    state: EvState,
    current_value: tuple[float, ...],
    target: PortfolioTarget,
    game: GameRules,
    spec: ActionSpec,
    outcome_piece: GearPiece,
) -> tuple[float, tuple[float, ...], bool]:
    if not current_value:
        return 0.0, tuple(), False
    if spec.upgrade_inventory_id:
        original = next(
            (row for row in rows if row.get("_inventory_id") == spec.upgrade_inventory_id),
            None,
        )
        if original is None:
            return 0.0, tuple(), False
        next_row = _candidate_inventory_row(
            outcome_piece,
            game,
            target.character,
            source=str(original.get("source") or "inventory"),
        )
        next_row["_inventory_id"] = spec.upgrade_inventory_id
        next_row["_piece"] = outcome_piece
        next_state = state.with_replaced_upgrade_source(
            spec.upgrade_inventory_id,
            next_row,
            game,
            target.character,
        )
    else:
        next_row = _candidate_inventory_row(
            outcome_piece,
            game,
            target.character,
            source="outcome",
        )
        next_state = state.with_candidate_row(next_row, game, target.character)

    if next_state.signature == state.signature:
        return 0.0, tuple(), False

    next_inventory = next_state.to_inventory_rows()
    next_value = next_state.best_loadout_value(game, target.character)
    gain_vector = _positive_gain(next_value, current_value)
    scalar_gain = _portfolio_delta_scalar(gain_vector)
    enters_best = scalar_gain > _EPSILON and _row_enters_best_loadout(
        next_row,
        next_inventory,
        game,
        target.character,
    )
    return scalar_gain, gain_vector, enters_best


def _mode_gain(mode: PortfolioMode, weighted_gains: list[tuple[PortfolioTarget, float]]) -> float:
    if mode == PortfolioMode.WEIGHTED_SUM:
        return sum(target.weight * max(gain, 0.0) for target, gain in weighted_gains)
    return max((max(gain, 0.0) for _target, gain in weighted_gains), default=0.0)


def _entered_best_loadout_summary(gains: list[PortfolioGain]) -> str:
    parts = [
        f"{gain.name} {gain.entered_best_loadout_probability:.1%}"
        for gain in gains
        if gain.entered_best_loadout_probability > _EPSILON
    ]
    return "；".join(parts) if parts else "无 outcome 进入任一代理人更优搭配"


def portfolio_action_rows(
    game: GameRules,
    probability_model: ProbabilityModel,
    targets: Sequence[PortfolioTarget],
    current_pieces: Sequence[GearPiece],
    inventory_pieces: Sequence[GearPiece] | None = None,
    *,
    mode: PortfolioMode = PortfolioMode.ANY_USEFUL,
    horizon: int = 1,
    action_scope: PortfolioActionScope = "tuning",
) -> list[PortfolioActionRow]:
    if horizon != 1:
        raise ValueError("Portfolio/BOX EV Phase 1 only supports horizon=1")
    if action_scope not in {"tuning", "upgrade", "all"}:
        raise ValueError("action_scope must be one of: tuning, upgrade, all")
    if not targets:
        return []

    inventory_pieces = inventory_pieces or []
    rows_by_agent = {
        target.agent_id: _target_rows_for_pool(
            target.current_pieces if target.current_pieces is not None else current_pieces,
            inventory_pieces,
            game,
            target.character,
        )
        for target in targets
    }
    states_by_agent = {
        target.agent_id: EvState.from_rows(
            rows_by_agent[target.agent_id],
            game,
            target.character,
        )
        for target in targets
    }
    current_values = {
        target.agent_id: states_by_agent[target.agent_id].best_loadout_value(
            game,
            target.character,
        )
        for target in targets
    }
    all_targets_incomplete = all(not current_values[target.agent_id] for target in targets)
    base_rows = rows_by_agent[targets[0].agent_id]
    specs = _portfolio_action_specs(
        game,
        targets,
        base_rows,
        action_scope,
    )

    result_rows: list[PortfolioActionRow] = []
    for spec in specs:
        outcomes = (
            _coarse_outcome_piece_distribution(spec, game, probability_model)
            if all_targets_incomplete and not spec.upgrade_inventory_id
            else _raw_outcome_piece_distribution(spec, base_rows, game, probability_model)
        )
        if not outcomes:
            continue

        expected_by_agent = {target.agent_id: 0.0 for target in targets}
        expected_delta_by_agent: dict[str, list[float]] = {target.agent_id: [] for target in targets}
        useful_probability_by_agent = {target.agent_id: 0.0 for target in targets}
        entered_probability_by_agent = {target.agent_id: 0.0 for target in targets}
        build_probability_by_agent = {target.agent_id: 0.0 for target in targets}
        build_gain_by_agent = {target.agent_id: 0.0 for target in targets}
        detail_buckets = {
            target.agent_id: {
                "set": [],
                "position": [],
                "main": [],
                "observation": [],
            }
            for target in targets
        }
        useful_probability = 0.0
        build_progress_probability = 0.0
        build_progress_gain = 0.0
        portfolio_ev = 0.0

        for outcome_piece, probability in outcomes:
            gains: list[tuple[PortfolioTarget, float]] = []
            build_hits: list[bool] = []
            for target in targets:
                gain, gain_vector, enters_best = _target_gain_for_outcome(
                    rows_by_agent[target.agent_id],
                    states_by_agent[target.agent_id],
                    current_values[target.agent_id],
                    target,
                    game,
                    spec,
                    outcome_piece,
                )
                gains.append((target, gain))
                expected_delta_by_agent[target.agent_id] = _add_delta_vectors(
                    expected_delta_by_agent[target.agent_id],
                    gain_vector,
                    probability,
                )
                if enters_best:
                    entered_probability_by_agent[target.agent_id] += probability
                if gain <= _EPSILON:
                    audit = _build_progress_audit(
                        rows_by_agent[target.agent_id],
                        target,
                        game,
                        outcome_piece,
                    )
                    build_gain_by_agent[target.agent_id] += probability * audit.gain
                    if audit.gain > _EPSILON:
                        build_probability_by_agent[target.agent_id] += probability
                        build_hits.append(True)
                    else:
                        build_hits.append(False)
                    detail_buckets[target.agent_id]["set"].append(audit.set_progress_detail)
                    detail_buckets[target.agent_id]["position"].append(audit.position_coverage_detail)
                    detail_buckets[target.agent_id]["main"].append(audit.main_stat_hit_detail)
                    detail_buckets[target.agent_id]["observation"].append(audit.candidate_observation_detail)
                else:
                    build_hits.append(False)
            for target, gain in gains:
                positive_gain = max(gain, 0.0)
                expected_by_agent[target.agent_id] += probability * positive_gain
                if positive_gain > _EPSILON:
                    useful_probability_by_agent[target.agent_id] += probability
            outcome_portfolio_gain = _mode_gain(mode, gains)
            portfolio_ev += probability * outcome_portfolio_gain
            if any(gain > _EPSILON for _target, gain in gains):
                useful_probability += probability
            if any(build_hits):
                build_progress_probability += probability
                build_progress_gain += probability

        portfolio_gains = [
            PortfolioGain(
                agent_id=target.agent_id,
                name=target.name,
                target_template_id=target.character.id,
                weight=target.weight,
                immediate_gain=round(expected_by_agent[target.agent_id], 6),
                expected_gain=round(expected_by_agent[target.agent_id], 6),
                useful_probability=round(useful_probability_by_agent[target.agent_id], 6),
                expected_delta_vector=[
                    round(value, 6)
                    for value in expected_delta_by_agent[target.agent_id]
                ],
                entered_best_loadout_probability=round(
                    entered_probability_by_agent[target.agent_id],
                    6,
                ),
                build_progress_probability=round(
                    build_probability_by_agent[target.agent_id],
                    6,
                ),
                build_progress_gain=round(build_gain_by_agent[target.agent_id], 6),
                set_progress_detail=_summarize_details(detail_buckets[target.agent_id]["set"]),
                position_coverage_detail=_summarize_details(detail_buckets[target.agent_id]["position"]),
                main_stat_hit_detail=_summarize_details(detail_buckets[target.agent_id]["main"]),
                candidate_observation_detail=_summarize_details(
                    detail_buckets[target.agent_id]["observation"]
                ),
            )
            for target in targets
        ]
        beneficiary_gains = [
            gain for gain in portfolio_gains if gain.expected_gain > _EPSILON
        ]
        best_beneficiary = max(
            beneficiary_gains,
            key=lambda gain: (gain.expected_gain * gain.weight, gain.expected_gain),
            default=None,
        )
        mother_cost, tuner_cost, core_cost = _action_costs(spec, probability_model)
        ev_per_mother = portfolio_ev / mother_cost if mother_cost > 0 else portfolio_ev
        result_rows.append(
            PortfolioActionRow(
                mode=mode,
                action_spec=spec,
                action_type=_action_type_label(spec),
                action_label=_action_progress_label(spec, game),
                target_set=spec.set_label,
                position=_action_position_label(spec, game),
                main_stat=_action_main_label(spec),
                fixed_substats=_action_substat_label(spec),
                portfolio_ev=round(portfolio_ev, 6),
                ev_per_mother=round(ev_per_mother, 6),
                useful_probability=round(useful_probability, 6),
                best_beneficiary_agent=best_beneficiary.name if best_beneficiary else "",
                beneficiary_count=len(beneficiary_gains),
                target_gains=portfolio_gains,
                mode_note=mode.note
                + " BOX 主 EV 使用 outcome 加入代理人盘池后 best_loadout_value 的正 delta 聚合；"
                + "建设审计单独展示，不参与主 EV 排序。"
                + " Phase 1：仅 H=1，不做同队装备互斥精确分配。",
                mother_cost=mother_cost,
                tuner_cost=tuner_cost,
                core_cost=core_cost,
                entered_best_loadout_summary=_entered_best_loadout_summary(portfolio_gains),
                build_progress_probability=round(build_progress_probability, 6),
                build_progress_gain=round(build_progress_gain, 6),
                set_progress_detail=_summarize_details(
                    gain.set_progress_detail for gain in portfolio_gains
                ),
                position_coverage_detail=_summarize_details(
                    gain.position_coverage_detail for gain in portfolio_gains
                ),
                main_stat_hit_detail=_summarize_details(
                    gain.main_stat_hit_detail for gain in portfolio_gains
                ),
                candidate_observation_detail=_summarize_details(
                    gain.candidate_observation_detail for gain in portfolio_gains
                ),
            )
        )

    return sorted(
        result_rows,
        key=lambda row: (
            row.ev_per_mother,
            row.portfolio_ev,
            row.useful_probability,
            max(
                (gain.entered_best_loadout_probability for gain in row.target_gains),
                default=0.0,
            ),
            row.beneficiary_count,
        ),
        reverse=True,
    )


def _expected_upgrade_piece_gain(
    rows: list[dict],
    current_value: tuple[float, ...],
    piece: GearPiece,
    game: GameRules,
    character: CharacterPreset,
) -> tuple[float, tuple[float, ...]]:
    piece_row = _candidate_inventory_row(piece, game, character, source="outcome")
    piece_row["_inventory_id"] = "box_check_piece"
    piece_row["_piece"] = piece
    distribution = _upgrade_piece_distribution(piece_row, game)
    if not distribution:
        next_value = _cached_best_combo_value([*rows, piece_row], game, character)
        gain_vector = _positive_gain(next_value, current_value)
        return _portfolio_delta_scalar(gain_vector), gain_vector

    expected_scalar = 0.0
    expected_vector: list[float] = []
    for upgraded_piece, probability in distribution:
        upgraded_row = _candidate_inventory_row(upgraded_piece, game, character, source="outcome")
        upgraded_row["_inventory_id"] = "box_check_piece"
        upgraded_row["_piece"] = upgraded_piece
        next_value = _cached_best_combo_value([*rows, upgraded_row], game, character)
        gain_vector = _positive_gain(next_value, current_value)
        expected_scalar += probability * _portfolio_delta_scalar(gain_vector)
        expected_vector = _add_delta_vectors(expected_vector, gain_vector, probability)
    return expected_scalar, tuple(expected_vector)


def portfolio_piece_check_rows(
    game: GameRules,
    probability_model: ProbabilityModel,
    targets: Sequence[PortfolioTarget],
    current_pieces: Sequence[GearPiece],
    inventory_pieces: Sequence[GearPiece] | None,
    piece: GearPiece,
) -> list[PortfolioPieceCheckRow]:
    all_pieces = [*current_pieces, *(inventory_pieces or [])]
    current_count = len(current_pieces)
    rows: list[PortfolioPieceCheckRow] = []
    for target in targets:
        inventory_rows = _target_rows(all_pieces, game, target.character, current_count)
        current_value = _cached_best_combo_value(inventory_rows, game, target.character)
        piece_row = _candidate_inventory_row(piece, game, target.character, source="outcome")
        piece_row["_inventory_id"] = "box_check_piece"
        piece_row["_piece"] = piece
        immediate_value = _cached_best_combo_value(
            [*inventory_rows, piece_row],
            game,
            target.character,
        )
        immediate_vector = _positive_gain(immediate_value, current_value)
        immediate_gain = _portfolio_delta_scalar(immediate_vector)
        upgrade_gain, upgrade_vector = _expected_upgrade_piece_gain(
            inventory_rows,
            current_value,
            piece,
            game,
            target.character,
        )
        observation_gain = max(upgrade_gain - immediate_gain, 0.0)
        rows.append(
            PortfolioPieceCheckRow(
                agent_id=target.agent_id,
                name=target.name,
                target_template_id=target.character.id,
                immediate_gain=round(immediate_gain, 6),
                immediate_delta_vector=[round(value, 6) for value in immediate_vector],
                upgrade_expected_gain=round(upgrade_gain, 6),
                upgrade_expected_delta_vector=[round(value, 6) for value in upgrade_vector],
                upgrade_observation_gain=round(observation_gain, 6),
                worth_observing=immediate_gain > _EPSILON or upgrade_gain > _EPSILON,
                note=(
                    "即时进入/提升 best_loadout"
                    if immediate_gain > _EPSILON
                    else "即时不提升；看强化期望"
                    if upgrade_gain > _EPSILON
                    else "暂不值得强化观察"
                ),
            )
        )
    return sorted(
        rows,
        key=lambda row: (
            row.worth_observing,
            row.upgrade_expected_gain,
            row.immediate_gain,
        ),
        reverse=True,
    )
