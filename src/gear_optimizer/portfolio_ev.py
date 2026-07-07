from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from gear_optimizer.models import CharacterPreset, GameRules, GearPiece, ProbabilityModel
from gear_optimizer.portfolio_models import (
    PortfolioActionRow,
    PortfolioGain,
    PortfolioMode,
    PortfolioPieceCheckRow,
    PortfolioTarget,
)
from gear_optimizer.position_ev import (
    ActionSpec,
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
    _normalise_inventory_rows,
    _positive_gain,
    _replace_inventory_row,
    _roll_state_from_piece,
    _set_distribution,
    _upgrade_action_specs,
)

_EPSILON = 1e-9


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
) -> list[ActionSpec]:
    specs: list[ActionSpec] = []
    for target in targets:
        specs.extend(
            _generation_action_specs(
                game,
                target.character,
                include_fixed_main=True,
                include_fixed_substats=False,
            )
        )
    specs.extend(_upgrade_action_specs(base_rows, game))
    return _dedupe_action_specs(specs)


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


def _row_enters_best_loadout(row: dict, inventory: list[dict], game: GameRules, character: CharacterPreset) -> bool:
    signature = _inventory_row_signature(row)
    combo = _best_combo_rows(inventory, game, character)
    return any(_inventory_row_signature(combo_row) == signature for combo_row in combo)


def _target_gain_for_outcome(
    rows: list[dict],
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
        next_inventory = _replace_inventory_row(rows, spec.upgrade_inventory_id, next_row)
    else:
        next_row = _candidate_inventory_row(
            outcome_piece,
            game,
            target.character,
            source="outcome",
        )
        next_inventory = [*rows, next_row]

    next_value = _cached_best_combo_value(next_inventory, game, target.character)
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
) -> list[PortfolioActionRow]:
    if horizon != 1:
        raise ValueError("Portfolio/BOX EV Phase 1 only supports horizon=1")
    if not targets:
        return []

    inventory_pieces = inventory_pieces or []
    all_pieces = [*current_pieces, *inventory_pieces]
    current_count = len(current_pieces)
    rows_by_agent = {
        target.agent_id: _target_rows(all_pieces, game, target.character, current_count)
        for target in targets
    }
    current_values = {
        target.agent_id: _cached_best_combo_value(
            rows_by_agent[target.agent_id],
            game,
            target.character,
        )
        for target in targets
    }
    base_rows = rows_by_agent[targets[0].agent_id]
    specs = _portfolio_action_specs(game, targets, base_rows)

    result_rows: list[PortfolioActionRow] = []
    for spec in specs:
        outcomes = _raw_outcome_piece_distribution(spec, base_rows, game, probability_model)
        if not outcomes:
            continue

        expected_by_agent = {target.agent_id: 0.0 for target in targets}
        expected_delta_by_agent: dict[str, list[float]] = {target.agent_id: [] for target in targets}
        useful_probability_by_agent = {target.agent_id: 0.0 for target in targets}
        entered_probability_by_agent = {target.agent_id: 0.0 for target in targets}
        useful_probability = 0.0
        portfolio_ev = 0.0

        for outcome_piece, probability in outcomes:
            gains: list[tuple[PortfolioTarget, float]] = []
            for target in targets:
                gain, gain_vector, enters_best = _target_gain_for_outcome(
                    rows_by_agent[target.agent_id],
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
            for target, gain in gains:
                positive_gain = max(gain, 0.0)
                expected_by_agent[target.agent_id] += probability * positive_gain
                if positive_gain > _EPSILON:
                    useful_probability_by_agent[target.agent_id] += probability
            outcome_portfolio_gain = _mode_gain(mode, gains)
            portfolio_ev += probability * outcome_portfolio_gain
            if any(gain > _EPSILON for _target, gain in gains):
                useful_probability += probability

        portfolio_gains = [
            PortfolioGain(
                agent_id=target.agent_id,
                name=target.name,
                target_template_id=target.character.id,
                weight=target.weight,
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
                + " BOX EV 使用 outcome 加入库存后 best_loadout_value 的正 delta 聚合，不按主属性/副词条粗判。"
                + " Phase 1：仅 H=1，不做同队装备互斥精确分配。",
                mother_cost=mother_cost,
                tuner_cost=tuner_cost,
                core_cost=core_cost,
                entered_best_loadout_summary=_entered_best_loadout_summary(portfolio_gains),
            )
        )

    return sorted(
        result_rows,
        key=lambda row: (
            row.ev_per_mother,
            row.portfolio_ev,
            row.useful_probability,
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
