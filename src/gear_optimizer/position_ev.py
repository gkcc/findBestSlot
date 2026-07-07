from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from itertools import combinations
import json
from math import inf, isfinite
import os
import time
from typing import Any

from gear_optimizer.models import CharacterPreset, CurrentGearAnalysis, GameRules, GearPiece, ProbabilityModel, position_key
from gear_optimizer.piece_distribution import fresh_piece_quality_distribution
from gear_optimizer.probability import normalise_weights
from gear_optimizer.scoring import score_piece, score_quality_sort_key, substat_quality_vector

ACTION_EV_ROWS_CACHE_MAX_SIZE = 32
RESOURCE_MARGINAL_EV_ROWS_CACHE_MAX_SIZE = 32
BEST_COMBO_VALUE_CACHE_MAX_SIZE = 5000
AGGREGATED_ACTION_OUTCOME_CACHE_MAX_SIZE = 1000
STATE_TRANSITION_CACHE_MAX_SIZE = 5000

_ACTION_EV_ROWS_CACHE: OrderedDict[str, list[dict[str, float | str]]] = OrderedDict()
_RESOURCE_MARGINAL_EV_ROWS_CACHE: OrderedDict[str, list[dict[str, float | str]]] = OrderedDict()
_BEST_COMBO_VALUE_CACHE: OrderedDict[tuple, tuple[float, ...]] = OrderedDict()
_AGGREGATED_ACTION_OUTCOME_CACHE: OrderedDict[tuple, list[tuple[list[dict], float]]] = OrderedDict()
_STATE_TRANSITION_CACHE: OrderedDict[tuple, list[tuple[EvState, float]]] = OrderedDict()
_VECTOR_EPSILON = 1e-9
_DISPLAY_EPSILON = 0.0005
_SOURCE_CURRENT = "current"
_SOURCE_INVENTORY = "inventory"
_SOURCE_OUTCOME = "outcome"
_MIXED_RANDOM_LOADOUT_LABEL = "混合结果，不存在唯一典型搭配"
_REPRESENTATIVE_PATH_NOTE = "代表路径仅用于审计；真实 H=2 EV 已对所有 outcome 加权。"
ProgressCallback = Callable[[dict[str, object]], None]


def _lru_get(cache: OrderedDict, key: object) -> object | None:
    try:
        value = cache[key]
    except KeyError:
        return None
    cache.move_to_end(key)
    return value


def _lru_set(cache: OrderedDict, key: object, value: object, max_size: int) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > max_size:
        cache.popitem(last=False)


@dataclass(frozen=True)
class ActionSpec:
    strategy: str
    set_label: str
    set_options: tuple[str, ...] = ()
    target_position: str | int | None = None
    fixed_main_stat: str | None = None
    required_substats: tuple[str, ...] = ()
    upgrade_inventory_id: str | None = None
    upgrade_label: str | None = None


@dataclass(frozen=True)
class ParallelActionValueResult:
    spec: ActionSpec
    value: tuple[float, ...] = ()
    seconds: float = 0.0
    error: str | None = None


def _emit_progress(
    progress_callback: ProgressCallback | None,
    event: str,
    **payload: object,
) -> None:
    if progress_callback is None:
        return
    progress_callback({"event": event, **payload})


def _canonical_stats(game: GameRules, stats: tuple[str, ...]) -> tuple[str, ...]:
    order = {stat: index for index, stat in enumerate(game.sub_stats)}
    return tuple(sorted(stats, key=lambda stat: order.get(stat, len(order))))


def _canonical_roll_state(
    game: GameRules,
    items: tuple[tuple[str, int], ...],
) -> tuple[tuple[str, int], ...]:
    order = {stat: index for index, stat in enumerate(game.sub_stats)}
    return tuple(sorted(items, key=lambda item: order.get(item[0], len(order))))


def _weighted_draws(stats: list[str], weights: dict[str, float]) -> list[tuple[str, float]]:
    if not stats:
        return []
    return list(normalise_weights(stats, weights).items())


def _add_substat_draws(
    game: GameRules,
    piece: GearPiece,
    selected_stats: list[str],
) -> list[tuple[str, float]]:
    available = game.available_substats(piece.main_stat, selected_stats)
    if (
        game.enhancement.revealed_next_substat_supported
        and piece.revealed_next_substat
        and piece.revealed_next_substat in available
    ):
        return [(piece.revealed_next_substat, 1.0)]
    return _weighted_draws(available, game.sub_stat_probabilities)


def _effective_revealed_next_substat(piece: GearPiece, game: GameRules) -> str:
    revealed = piece.revealed_next_substat or ""
    if not revealed or not game.enhancement.revealed_next_substat_supported:
        return ""
    if not (
        piece.initial_substat_count == 3
        and piece.level < game.enhancement.initial_add_level
        and len(piece.substats) == 3
    ):
        return ""
    selected_stats = [line.stat for line in piece.substats]
    return revealed if revealed in game.available_substats(piece.main_stat, selected_stats) else ""


def _initial_stat_states(
    game: GameRules,
    main_stat: str,
    line_count: int,
    required_substats: tuple[str, ...] = (),
) -> dict[tuple[str, ...], float]:
    required = _canonical_stats(game, tuple(dict.fromkeys(required_substats)))
    available_required = set(game.available_substats(main_stat))
    if any(stat not in available_required for stat in required) or len(required) > line_count:
        return {}

    states: dict[tuple[str, ...], float] = {required: 1.0}
    for _ in range(line_count - len(required)):
        next_states: defaultdict[tuple[str, ...], float] = defaultdict(float)
        for selected, probability in states.items():
            available = game.available_substats(main_stat, list(selected))
            for stat, draw_probability in _weighted_draws(available, game.sub_stat_probabilities):
                next_states[_canonical_stats(game, tuple([*selected, stat]))] += probability * draw_probability
        states = dict(next_states)
    return states


def _initial_roll_states(
    game: GameRules,
    main_stat: str,
    line_count: int,
    required_substats: tuple[str, ...] = (),
) -> dict[tuple[tuple[str, int], ...], float]:
    required = _canonical_stats(game, tuple(dict.fromkeys(required_substats)))
    available_required = set(game.available_substats(main_stat))
    if any(stat not in available_required for stat in required) or len(required) > line_count:
        return {}

    states: dict[tuple[tuple[str, int], ...], float] = {
        _canonical_roll_state(game, tuple((stat, 0) for stat in required)): 1.0
    }
    for _ in range(line_count - len(required)):
        next_states: defaultdict[tuple[tuple[str, int], ...], float] = defaultdict(float)
        for selected, probability in states.items():
            selected_stats = [stat for stat, _rolls in selected]
            available = game.available_substats(main_stat, selected_stats)
            for stat, draw_probability in _weighted_draws(available, game.sub_stat_probabilities):
                next_state = _canonical_roll_state(game, tuple([*selected, (stat, 0)]))
                next_states[next_state] += probability * draw_probability
        states = dict(next_states)
    return states


def _advance_roll_states(
    game: GameRules,
    main_stat: str,
    states: dict[tuple[tuple[str, int], ...], float],
    initial_count: int,
) -> dict[tuple[tuple[str, int], ...], float]:
    roll_states = dict(states)
    for index, _level in enumerate(game.enhancement.event_levels):
        next_states: defaultdict[tuple[tuple[str, int], ...], float] = defaultdict(float)
        is_add_event = initial_count == 3 and index == 0
        for selected, probability in roll_states.items():
            if is_add_event:
                selected_stats = [stat for stat, _rolls in selected]
                draws = _weighted_draws(
                    game.available_substats(main_stat, selected_stats),
                    game.sub_stat_probabilities,
                )
                if not draws:
                    next_states[selected] += probability
                    continue
                for stat, draw_probability in draws:
                    next_state = _canonical_roll_state(game, tuple([*selected, (stat, 0)]))
                    next_states[next_state] += probability * draw_probability
                continue
            if not selected:
                next_states[selected] += probability
                continue
            for stat_index, (stat, rolls) in enumerate(selected):
                updated = list(selected)
                updated[stat_index] = (stat, rolls + 1)
                next_states[_canonical_roll_state(game, tuple(updated))] += probability / len(selected)
        roll_states = dict(next_states)
    return roll_states


def _fresh_piece_outcome_distribution(
    game: GameRules,
    position: str | int,
    set_name: str,
    main_stat: str,
    probability_model: ProbabilityModel,
    required_substats: tuple[str, ...] = (),
) -> list[tuple[GearPiece, float]]:
    distribution: defaultdict[tuple[tuple[str, int], int], float] = defaultdict(float)
    for count_text, count_probability in probability_model.initial_substat_count_probabilities.items():
        initial_count = int(count_text)
        initial_states = _initial_roll_states(
            game,
            main_stat,
            initial_count,
            required_substats,
        )
        final_states = _advance_roll_states(game, main_stat, initial_states, initial_count)
        for state, probability in final_states.items():
            distribution[(state, initial_count)] += count_probability * probability

    pieces: list[tuple[GearPiece, float]] = []
    for (state, initial_count), probability in distribution.items():
        pieces.append(
            (
                GearPiece(
                    position=position,
                    set_name=set_name,
                    main_stat=main_stat,
                    level=game.enhancement.max_level,
                    substats=[
                        {"stat": stat, "rolls": rolls}
                        for stat, rolls in state
                    ],
                    initial_substat_count=initial_count,
                ),
                probability,
            )
        )
    return pieces


def _set_plan_satisfied(combo: tuple[dict, ...], character: CharacterPreset) -> bool:
    plan = character.active_set_plan()
    if plan is None or plan.is_unrestricted:
        return True
    counts: defaultdict[str, int] = defaultdict(int)
    for piece in combo:
        counts[piece["set_name"]] += 1

    requirements = list(plan.requirements)

    def can_satisfy(index: int) -> bool:
        if index >= len(requirements):
            return True
        requirement = requirements[index]
        for set_name in requirement.set_names:
            if counts[set_name] < requirement.pieces:
                continue
            counts[set_name] -= requirement.pieces
            if can_satisfy(index + 1):
                counts[set_name] += requirement.pieces
                return True
            counts[set_name] += requirement.pieces
        return False

    return can_satisfy(0)


def _set_plan_assignment(
    combo: tuple[dict, ...],
    character: CharacterPreset,
) -> dict[str, int] | None:
    plan = character.active_set_plan()
    if plan is None or plan.is_unrestricted:
        return {}

    requirements = list(plan.requirements)
    assignment: dict[int, int] = {}
    used_indexes: set[int] = set()

    def can_assign(requirement_index: int) -> bool:
        if requirement_index >= len(requirements):
            return True
        requirement = requirements[requirement_index]
        for set_name in requirement.set_names:
            candidates = [
                index
                for index, piece in enumerate(combo)
                if index not in used_indexes and piece["set_name"] == set_name
            ]
            if len(candidates) < requirement.pieces:
                continue
            for selected_indexes in combinations(candidates, requirement.pieces):
                for index in selected_indexes:
                    used_indexes.add(index)
                    assignment[index] = requirement_index
                if can_assign(requirement_index + 1):
                    return True
                for index in selected_indexes:
                    used_indexes.remove(index)
                    assignment.pop(index, None)
        return False

    if not can_assign(0):
        return None
    return {
        position_key(combo[index]["position"]): requirement_index
        for index, requirement_index in assignment.items()
    }


def _zero_vector(character: CharacterPreset) -> tuple[float, ...]:
    priority = character.substat_priority
    if priority is None:
        return tuple(0.0 for _ in range(1 + len(character.priority_stats())))
    return tuple(0.0 for _ in range(2 + len(priority.core) + len(priority.usable)))


def _sum_vectors(vectors: list[tuple[float, ...]]) -> tuple[float, ...]:
    if not vectors:
        return ()
    return tuple(sum(vector[index] for vector in vectors) for index in range(len(vectors[0])))


def _current_inventory_rows(
    analysis: CurrentGearAnalysis,
    character: CharacterPreset,
) -> list[dict]:
    rows = []
    for score in analysis.scores:
        rows.append(
            {
                "position": score.position,
                "set_name": score.set_name,
                "main_preferred": score.main_stat_preferred,
                "effective_rolls": score.effective_rolls,
                "quality_score": score.weighted_score,
                "quality_vector": score_quality_sort_key(score, character),
                "locked": score.locked,
                "source": _SOURCE_CURRENT,
            }
        )
    return rows


def _candidate_inventory_row(
    piece: GearPiece,
    game: GameRules,
    character: CharacterPreset,
    source: str = _SOURCE_INVENTORY,
) -> dict:
    score = score_piece(piece, game, character)
    return {
        "position": piece.position,
        "set_name": piece.set_name,
        "main_preferred": score.main_stat_preferred,
        "effective_rolls": score.effective_rolls,
        "quality_score": score.weighted_score,
        "quality_vector": substat_quality_vector(piece, character),
        "locked": piece.locked,
        "level": piece.level,
        "source": source,
        "_effective_revealed_next_substat": _effective_revealed_next_substat(piece, game),
    }


def _future_roll_state_distribution(
    piece: GearPiece,
    game: GameRules,
) -> dict[tuple[tuple[str, int], ...], float]:
    states: dict[tuple[tuple[str, int], ...], float] = {
        _canonical_roll_state(
            game,
            tuple((line.stat, line.rolls) for line in piece.substats),
        ): 1.0
    }
    events = [
        level
        for level in game.enhancement.event_levels
        if level > piece.level and level <= game.enhancement.max_level
    ]
    needs_add = (
        piece.initial_substat_count == 3
        and len(piece.substats) < 4
        and piece.level < game.enhancement.initial_add_level
    )
    for index, _level in enumerate(events):
        next_states: defaultdict[tuple[tuple[str, int], ...], float] = defaultdict(float)
        is_add_event = needs_add and index == 0
        for state, probability in states.items():
            if is_add_event:
                selected_stats = [stat for stat, _rolls in state]
                draws = _add_substat_draws(game, piece, selected_stats)
                if not draws:
                    next_states[state] += probability
                    continue
                for stat, draw_probability in draws:
                    next_state = _canonical_roll_state(game, tuple([*state, (stat, 0)]))
                    next_states[next_state] += probability * draw_probability
                continue
            if not state:
                next_states[state] += probability
                continue
            for stat_index, (stat, rolls) in enumerate(state):
                updated = list(state)
                updated[stat_index] = (stat, rolls + 1)
                next_states[_canonical_roll_state(game, tuple(updated))] += probability / len(state)
        states = dict(next_states)
    return states


def _expected_upgrade_quality(
    piece: GearPiece,
    game: GameRules,
    character: CharacterPreset,
) -> tuple[float, tuple[float, ...]]:
    expected_score = 0.0
    expected_vector = list(_zero_vector(character))
    for state, probability in _future_roll_state_distribution(piece, game).items():
        quality_score, quality_vector = _quality_from_roll_state(state, character)
        expected_score += quality_score * probability
        for index, value in enumerate(quality_vector):
            expected_vector[index] += value * probability
    return round(expected_score, 6), tuple(round(value, 6) for value in expected_vector)


def _expected_upgrade_loadout_row(
    row: dict,
    game: GameRules,
    character: CharacterPreset,
) -> dict:
    piece = row.get("_piece")
    if not isinstance(piece, GearPiece) or piece.level >= game.enhancement.max_level:
        return row
    expected_score, expected_vector = _expected_upgrade_quality(piece, game, character)
    projected = dict(row)
    projected["_current_effective_rolls"] = row.get("effective_rolls", 0.0)
    projected["_current_quality_score"] = row.get("quality_score", 0.0)
    projected["_current_quality_vector"] = row.get("quality_vector", ())
    projected["_expected_upgrade"] = True
    projected["_expected_level"] = game.enhancement.max_level
    projected["_allow_unfinished_loadout"] = True
    projected["effective_rolls"] = expected_score
    projected["quality_score"] = expected_score
    projected["quality_vector"] = expected_vector
    projected.pop("_value_vector", None)
    return projected


def _piece_contribution_key(row: dict) -> tuple[float, ...]:
    return (
        float(bool(row["main_preferred"])),
        *tuple(float(value) for value in row["quality_vector"]),
        float(row["effective_rolls"]),
        float(row["quality_score"]),
    )


def _normalise_inventory_rows(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
) -> list[dict]:
    upgrade_sources: list[dict] = []
    locked_by_position: dict[str, dict] = {}
    best_by_position_set: dict[tuple[str, str], dict] = {}
    for row in inventory:
        piece = row.get("_piece")
        if isinstance(piece, GearPiece) and piece.level < game.enhancement.max_level:
            upgrade_sources.append(row)
            if not row.get("_allow_unfinished_loadout", False):
                continue

        position = position_key(row["position"])
        if row.get("locked") and row.get("source") == _SOURCE_CURRENT:
            current = locked_by_position.get(position)
            if current is None or _piece_contribution_key(row) > _piece_contribution_key(current):
                locked_by_position[position] = row
            continue

        key = (position, str(row["set_name"]))
        current = best_by_position_set.get(key)
        if current is None or _piece_contribution_key(row) > _piece_contribution_key(current):
            best_by_position_set[key] = row

    return [
        *upgrade_sources,
        *[
            locked_by_position[key]
            for key in sorted(locked_by_position)
        ],
        *[
            best_by_position_set[key]
            for key in sorted(best_by_position_set)
            if key[0] not in locked_by_position
        ],
    ]


def _inventory_piece_id(index: int) -> str:
    return f"piece:{index}"


def _coerce_inventory_rows(
    inventory: Sequence[GearPiece | dict],
    game: GameRules,
    character: CharacterPreset,
    current_count: int = 0,
    include_upgrade_expectation: bool = False,
) -> list[dict]:
    rows: list[dict] = []
    for index, item in enumerate(inventory):
        if isinstance(item, GearPiece):
            source = _SOURCE_CURRENT if index < current_count else _SOURCE_INVENTORY
            row = _candidate_inventory_row(item, game, character, source=source)
            row["_inventory_id"] = _inventory_piece_id(index)
            row["_piece"] = item
            if include_upgrade_expectation:
                row = _expected_upgrade_loadout_row(row, game, character)
            rows.append(row)
        else:
            row = dict(item)
            if include_upgrade_expectation:
                row = _expected_upgrade_loadout_row(row, game, character)
            rows.append(row)
    return _normalise_inventory_rows(rows, game, character)


def inventory_rows_from_pieces(
    pieces: Sequence[GearPiece],
    game: GameRules,
    character: CharacterPreset,
    current_count: int = 0,
    include_upgrade_expectation: bool = False,
) -> list[dict]:
    rows = []
    for index, piece in enumerate(pieces):
        source = _SOURCE_CURRENT if index < current_count else _SOURCE_INVENTORY
        row = _candidate_inventory_row(piece, game, character, source=source)
        row["_inventory_id"] = _inventory_piece_id(index)
        row["_piece"] = piece
        if include_upgrade_expectation:
            row = _expected_upgrade_loadout_row(row, game, character)
        rows.append(row)
    return _normalise_inventory_rows(rows, game, character)


@dataclass
class EvState:
    rows: tuple[dict, ...]
    signature: tuple[tuple, ...]
    locked_positions: tuple[str, ...]
    upgrade_source_ids: tuple[str, ...]

    @classmethod
    def from_inventory(
        cls,
        inventory: Sequence[GearPiece | dict],
        game: GameRules,
        character: CharacterPreset,
        current_count: int = 0,
        include_upgrade_expectation: bool = False,
    ) -> "EvState":
        return cls.from_rows(
            _coerce_inventory_rows(
                inventory,
                game,
                character,
                current_count=current_count,
                include_upgrade_expectation=include_upgrade_expectation,
            ),
            game,
            character,
        )

    @classmethod
    def from_rows(
        cls,
        rows: Sequence[dict],
        game: GameRules,
        character: CharacterPreset,
    ) -> "EvState":
        normalised = tuple(_normalise_inventory_rows([dict(row) for row in rows], game, character))
        locked_positions = tuple(
            sorted(
                {
                    position_key(row["position"])
                    for row in normalised
                    if row.get("locked") and row.get("source") == _SOURCE_CURRENT
                }
            )
        )
        upgrade_source_ids = tuple(
            sorted(
                str(row.get("_inventory_id"))
                for row in normalised
                if _is_upgrade_source(row, game) and row.get("_inventory_id")
            )
        )
        return cls(
            rows=normalised,
            signature=_inventory_signature(list(normalised)),
            locked_positions=locked_positions,
            upgrade_source_ids=upgrade_source_ids,
        )

    def to_inventory_rows(self) -> list[dict]:
        return [dict(row) for row in self.rows]

    def best_loadout_value(
        self,
        game: GameRules,
        character: CharacterPreset,
    ) -> tuple[float, ...]:
        return _best_combo_value(self.to_inventory_rows(), game, character)

    def best_loadout_rows(
        self,
        game: GameRules,
        character: CharacterPreset,
    ) -> tuple[dict, ...]:
        return _best_combo_rows(self.to_inventory_rows(), game, character)

    def best_by_position_set(self, game: GameRules) -> dict[tuple[str, str], dict]:
        best: dict[tuple[str, str], dict] = {}
        for row in self.rows:
            if not _is_loadout_candidate(row, game):
                continue
            position = position_key(row["position"])
            if position in self.locked_positions and not (
                row.get("locked") and row.get("source") == _SOURCE_CURRENT
            ):
                continue
            key = (position, str(row["set_name"]))
            current = best.get(key)
            if current is None or _piece_contribution_key(row) > _piece_contribution_key(current):
                best[key] = row
        return best

    def with_candidate_row(
        self,
        candidate_row: dict,
        game: GameRules,
        character: CharacterPreset,
    ) -> "EvState":
        candidate = dict(candidate_row)
        candidate.setdefault("source", _SOURCE_OUTCOME)
        position = position_key(candidate["position"])
        if position in self.locked_positions:
            return self

        key = (position, str(candidate["set_name"]))
        current = self.best_by_position_set(game).get(key)
        if current is not None and _piece_contribution_key(current) >= _piece_contribution_key(candidate):
            return self
        return EvState.from_rows([*self.rows, candidate], game, character)

    def with_replaced_upgrade_source(
        self,
        inventory_id: str,
        next_row: dict,
        game: GameRules,
        character: CharacterPreset,
    ) -> "EvState":
        replaced = False
        rows: list[dict] = []
        for row in self.rows:
            if row.get("_inventory_id") == inventory_id and not replaced:
                rows.append(dict(next_row))
                replaced = True
            else:
                rows.append(dict(row))
        if not replaced:
            rows.append(dict(next_row))
        next_state = EvState.from_rows(rows, game, character)
        return self if next_state.signature == self.signature else next_state


def _quality_from_roll_state(
    state: tuple[tuple[str, int], ...],
    character: CharacterPreset,
) -> tuple[float, tuple[float, ...]]:
    counts = {stat: 0.0 for stat in character.priority_stats()}
    for stat, rolls in state:
        if stat in counts:
            counts[stat] += 1 + rolls
    priority = character.substat_priority
    if priority is None:
        total = sum(counts.values())
        return total, (total, *[counts[stat] for stat in character.priority_stats()])
    core_total = sum(counts[stat] for stat in priority.core)
    usable_total = sum(counts[stat] for stat in priority.usable)
    total = core_total + usable_total
    return total, (
        core_total,
        *[counts[stat] for stat in priority.core],
        usable_total,
        *[counts[stat] for stat in priority.usable],
    )


def _fresh_candidate_row_distribution(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    position: str | int,
    set_name: str,
    main_stat: str,
    required_substats: tuple[str, ...] = (),
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]] | None = None,
) -> list[tuple[dict, float]]:
    cache_key = (main_stat, required_substats)
    cached = quality_cache.get(cache_key) if quality_cache is not None else None
    if cached is None:
        cached = [
            (outcome.quality_score, outcome.quality_vector, outcome.probability)
            for outcome in fresh_piece_quality_distribution(
                game,
                character,
                probability_model,
                main_stat,
                required_substats,
            )
        ]
        if quality_cache is not None:
            quality_cache[cache_key] = cached

    preferred_mains = character.preferred_mains_for(position)
    main_preferred = not preferred_mains or main_stat in preferred_mains
    return [
        (
            {
                "position": position,
                "set_name": set_name,
                "main_stat": main_stat,
                "level": game.enhancement.max_level,
                "main_preferred": main_preferred,
                "effective_rolls": quality_score,
                "quality_score": quality_score,
                "quality_vector": quality_vector,
                "locked": False,
                "source": _SOURCE_OUTCOME,
            },
            probability,
        )
        for quality_score, quality_vector, probability in cached
    ]


def _row_value(row: dict, character: CharacterPreset) -> tuple[float, ...]:
    cached = row.get("_value_vector")
    if isinstance(cached, tuple):
        return cached
    value = (
        float(bool(row["main_preferred"])),
        *tuple(float(value) for value in row["quality_vector"]),
        float(row["effective_rolls"]),
        float(row["quality_score"]),
    )
    row["_value_vector"] = value
    return value


def _combo_value(combo: tuple[dict, ...], character: CharacterPreset) -> tuple[float, ...]:
    value = tuple(0.0 for _ in _row_value({"main_preferred": False, "quality_vector": _zero_vector(character), "effective_rolls": 0.0, "quality_score": 0.0}, character))
    for row in combo:
        value = _add_vectors(value, _row_value(row, character))
    return value


def _is_upgrade_source(row: dict, game: GameRules) -> bool:
    piece = row.get("_piece")
    return isinstance(piece, GearPiece) and piece.level < game.enhancement.max_level


def _is_loadout_candidate(row: dict, game: GameRules) -> bool:
    return not _is_upgrade_source(row, game) or bool(row.get("_allow_unfinished_loadout", False))


def _loadout_options_by_position(
    inventory: list[dict],
    game: GameRules,
) -> list[list[dict]]:
    by_position: dict[str, list[dict]] = defaultdict(list)
    locked_by_position: dict[str, list[dict]] = defaultdict(list)
    for row in inventory:
        if not _is_loadout_candidate(row, game):
            continue
        key = position_key(row["position"])
        if row.get("locked") and row.get("source") == _SOURCE_CURRENT:
            locked_by_position[key].append(row)
        else:
            by_position[key].append(row)

    options: list[list[dict]] = []
    for rule in game.positions:
        key = position_key(rule.id)
        choices = locked_by_position.get(key) or by_position.get(key, [])
        if not choices:
            return []
        options.append(choices)
    return options


def _set_count_names(character: CharacterPreset) -> list[str]:
    plan = character.active_set_plan()
    if plan is None or plan.is_unrestricted:
        return []
    return sorted({set_name for requirement in plan.requirements for set_name in requirement.set_names})


def _advance_count_state(
    state: tuple[int, ...],
    row: dict,
    set_index: dict[str, int],
    max_count: int,
) -> tuple[int, ...]:
    index = set_index.get(str(row["set_name"]))
    if index is None:
        return state
    next_state = list(state)
    next_state[index] = min(next_state[index] + 1, max_count)
    return tuple(next_state)


def _count_state_satisfies_plan(
    state: tuple[int, ...],
    set_names: list[str],
    character: CharacterPreset,
) -> bool:
    plan = character.active_set_plan()
    if plan is None or plan.is_unrestricted:
        return True

    counts = {set_name: state[index] for index, set_name in enumerate(set_names)}
    requirements = list(plan.requirements)

    def can_satisfy(index: int) -> bool:
        if index >= len(requirements):
            return True
        requirement = requirements[index]
        for set_name in requirement.set_names:
            if counts.get(set_name, 0) < requirement.pieces:
                continue
            counts[set_name] -= requirement.pieces
            if can_satisfy(index + 1):
                counts[set_name] += requirement.pieces
                return True
            counts[set_name] += requirement.pieces
        return False

    return can_satisfy(0)


def _best_loadout_dp(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    return_combo: bool = False,
) -> tuple[float, ...] | tuple[dict, ...]:
    options = _loadout_options_by_position(inventory, game)
    if not options:
        return tuple()

    if all(len(choices) == 1 for choices in options):
        combo = tuple(choices[0] for choices in options)
        return combo if return_combo else _combo_value(combo, character)

    if character.active_set_plan() is None or character.active_set_plan().is_unrestricted:
        combo = tuple(max(choices, key=lambda row: _row_value(row, character)) for choices in options)
        return combo if return_combo else _combo_value(combo, character)

    set_names = _set_count_names(character)
    set_index = {set_name: index for index, set_name in enumerate(set_names)}
    max_count = len(game.positions)
    initial_state = tuple(0 for _ in set_names)
    zero_value = tuple(0.0 for _ in _row_value(
        {
            "main_preferred": False,
            "quality_vector": _zero_vector(character),
            "effective_rolls": 0.0,
            "quality_score": 0.0,
        },
        character,
    ))

    if return_combo:
        value_states: dict[tuple[int, ...], tuple[float, ...]] = {initial_state: zero_value}
        layers: list[dict[tuple[int, ...], tuple[tuple[float, ...], tuple[int, ...], dict]]] = []
        for choices in options:
            next_states: dict[tuple[int, ...], tuple[tuple[float, ...], tuple[int, ...], dict]] = {}
            for count_state, value in value_states.items():
                for row in choices:
                    next_state = _advance_count_state(count_state, row, set_index, max_count)
                    next_value = _add_vectors(value, _row_value(row, character))
                    current = next_states.get(next_state)
                    if current is None or next_value > current[0]:
                        next_states[next_state] = (next_value, count_state, row)
            layers.append(next_states)
            value_states = {
                count_state: value
                for count_state, (value, _previous_state, _row) in next_states.items()
            }
        if not value_states:
            return tuple()
        satisfied_states = [
            count_state
            for count_state in value_states
            if _count_state_satisfies_plan(count_state, set_names, character)
        ]
        candidate_states = satisfied_states or list(value_states)
        best_state = max(candidate_states, key=lambda count_state: value_states[count_state])
        combo_reversed = []
        current_state = best_state
        for layer in reversed(layers):
            _value, previous_state, row = layer[current_state]
            combo_reversed.append(row)
            current_state = previous_state
        return tuple(reversed(combo_reversed))

    value_states: dict[tuple[int, ...], tuple[float, ...]] = {initial_state: zero_value}
    for choices in options:
        next_states: dict[tuple[int, ...], tuple[float, ...]] = {}
        for count_state, value in value_states.items():
            for row in choices:
                next_state = _advance_count_state(count_state, row, set_index, max_count)
                next_value = _add_vectors(value, _row_value(row, character))
                current = next_states.get(next_state)
                if current is None or next_value > current:
                    next_states[next_state] = next_value
        value_states = next_states
    if not value_states:
        return tuple()
    satisfied_values = [
        value
        for count_state, value in value_states.items()
        if _count_state_satisfies_plan(count_state, set_names, character)
    ]
    return max(satisfied_values or list(value_states.values()))


def _candidate_combos(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
) -> list[tuple[dict, ...]]:
    combo = _best_loadout_dp(inventory, game, character, return_combo=True)
    return [combo] if combo else []


def _best_combo_rows(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    return_combo: bool = True,
) -> tuple[dict, ...]:
    if not return_combo:
        raise ValueError("_best_combo_rows requires return_combo=True; use _best_combo_value for value-only DP")
    return _best_loadout_dp(inventory, game, character, return_combo=True)


def _best_combo_value(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
) -> tuple[float, ...]:
    return _best_loadout_dp(inventory, game, character, return_combo=False)


def best_loadout_value(
    inventory: Sequence[GearPiece | dict],
    game: GameRules,
    character: CharacterPreset,
    current_count: int = 0,
    include_upgrade_expectation: bool = False,
) -> tuple[float, ...]:
    return _best_combo_value(
        _coerce_inventory_rows(
            inventory,
            game,
            character,
            current_count=current_count,
            include_upgrade_expectation=include_upgrade_expectation,
        ),
        game,
        character,
    )


def best_loadout_rows(
    inventory: Sequence[GearPiece | dict],
    game: GameRules,
    character: CharacterPreset,
    current_count: int = 0,
    include_upgrade_expectation: bool = False,
) -> list[dict]:
    rows = _coerce_inventory_rows(
        inventory,
        game,
        character,
        current_count=current_count,
        include_upgrade_expectation=include_upgrade_expectation,
    )
    return [dict(row) for row in _best_combo_rows(rows, game, character)]


def _positive_gain(
    new_value: tuple[float, ...],
    current_value: tuple[float, ...],
) -> tuple[float, ...]:
    if not new_value or not _vector_greater(new_value, current_value):
        return tuple(0.0 for _ in current_value)
    return tuple(
        _clean_vector_value(max(new_value[index] - current_value[index], 0.0))
        for index in range(len(current_value))
    )


def _add_vectors(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    if not left:
        return right
    return tuple(left[index] + right[index] for index in range(len(left)))


def _scale_vector(vector: tuple[float, ...], factor: float) -> tuple[float, ...]:
    return tuple(value * factor for value in vector)


def _vector_greater(left: tuple[float, ...], right: tuple[float, ...]) -> bool:
    for left_value, right_value in zip(left, right):
        difference = left_value - right_value
        if difference > _VECTOR_EPSILON:
            return True
        if difference < -_VECTOR_EPSILON:
            return False
    return len(left) > len(right)


def _clean_vector_value(value: float) -> float:
    return 0.0 if abs(value) <= _VECTOR_EPSILON else value


def _clean_vector(vector: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(_clean_vector_value(float(value)) for value in vector)


def _subtract_vectors(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    if not left:
        return tuple()
    if not right:
        return left
    return tuple(left[index] - right[index] for index in range(min(len(left), len(right))))


def _set_action_groups(character: CharacterPreset) -> list[tuple[str, list[str]]]:
    plan = character.active_set_plan()
    if plan and not plan.is_unrestricted:
        return [
            (" / ".join(requirement.set_names), list(requirement.set_names))
            for requirement in plan.requirements
        ]
    return [(character.target_set, [character.target_set])]


def _set_distribution(
    probability_model: ProbabilityModel,
    set_options: list[str],
) -> list[tuple[str, float]]:
    probability = min(
        probability_model.target_set_probability * max(len(set_options), 1),
        1.0,
    )
    if probability <= 0 or not set_options:
        return []
    return [(set_name, probability / len(set_options)) for set_name in set_options]


def _inventory_row_signature(row: dict) -> tuple:
    cached = row.get("_inventory_signature")
    if isinstance(cached, tuple):
        return cached
    piece = row.get("_piece")
    piece_signature = (
        (
            piece.level,
            piece.initial_substat_count,
            tuple((line.stat, line.rolls) for line in piece.substats),
            str(row.get("_effective_revealed_next_substat") or ""),
        )
        if isinstance(piece, GearPiece)
        else tuple()
    )
    signature = (
        position_key(row["position"]),
        row["set_name"],
        bool(row["main_preferred"]),
        bool(row.get("locked", False)),
        str(row.get("source") or _SOURCE_INVENTORY),
        bool(row.get("_allow_unfinished_loadout", False)),
        round(float(row["effective_rolls"]), 6),
        round(float(row["quality_score"]), 6),
        tuple(round(float(value), 6) for value in row["quality_vector"]),
        piece_signature,
    )
    row["_inventory_signature"] = signature
    return signature


def _inventory_signature(inventory: list[dict]) -> tuple[tuple, ...]:
    return tuple(
        sorted(_inventory_row_signature(piece) for piece in inventory)
    )


def _set_plan_cache_key(character: CharacterPreset) -> str | None:
    plan = character.active_set_plan()
    return (
        json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        if plan
        else None
    )


def _game_cache_key(game: GameRules) -> tuple:
    return (
        game.id,
        game.model_dump_json(),
    )


def _character_cache_key(character: CharacterPreset) -> tuple:
    return (
        character.id,
        character.model_dump_json(),
    )


def _probability_model_cache_key(probability_model: ProbabilityModel) -> tuple:
    return (
        probability_model.id,
        probability_model.target_set_probability,
        tuple(sorted(probability_model.initial_substat_count_probabilities.items())),
        tuple(sorted(probability_model.resource_costs.items())),
    )


def _best_combo_cache_key(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
) -> tuple:
    return (_game_cache_key(game), _character_cache_key(character), _inventory_signature(inventory))


def _cached_best_combo_value(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
) -> tuple[float, ...]:
    key = _best_combo_cache_key(inventory, game, character)
    cached = _lru_get(_BEST_COMBO_VALUE_CACHE, key)
    if cached is not None:
        return cached
    value = _best_combo_value(inventory, game, character)
    _lru_set(_BEST_COMBO_VALUE_CACHE, key, value, BEST_COMBO_VALUE_CACHE_MAX_SIZE)
    return value


def _aggregate_inventory_outcomes(
    outcomes: list[tuple[list[dict], float]],
    game: GameRules,
    character: CharacterPreset,
) -> list[tuple[list[dict], float]]:
    grouped: dict[tuple[tuple, ...], tuple[list[dict], float]] = {}
    for inventory, probability in outcomes:
        normalised_inventory = _normalise_inventory_rows(inventory, game, character)
        signature = _inventory_signature(normalised_inventory)
        existing = grouped.get(signature)
        if existing is None:
            grouped[signature] = (normalised_inventory, probability)
        else:
            grouped[signature] = (existing[0], existing[1] + probability)
    return [
        (inventory, probability)
        for inventory, probability in grouped.values()
        if probability > 1e-12
    ]


def _aggregated_action_outcomes_for_spec(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    spec: ActionSpec,
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]] | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_depth: int = 0,
) -> list[tuple[list[dict], float]]:
    key = (
        _game_cache_key(game),
        _character_cache_key(character),
        _probability_model_cache_key(probability_model),
        _inventory_signature(inventory),
        spec,
    )
    cached = _lru_get(_AGGREGATED_ACTION_OUTCOME_CACHE, key)
    if cached is not None:
        _emit_progress(
            progress_callback,
            "aggregated_outcome_cache_hit",
            depth=progress_depth,
        )
        return cached
    _emit_progress(
        progress_callback,
        "outcome_distribution_start",
        depth=progress_depth,
        action_strategy=spec.strategy,
        action_set=spec.set_label,
    )
    raw_outcomes = _action_outcome_distribution(
        inventory,
        game,
        character,
        probability_model,
        spec,
        quality_cache=quality_cache,
        progress_callback=progress_callback,
        progress_depth=progress_depth,
    )
    _emit_progress(
        progress_callback,
        "outcome_distribution_done",
        depth=progress_depth,
        total=len(raw_outcomes),
        action_strategy=spec.strategy,
        action_set=spec.set_label,
    )
    _emit_progress(
        progress_callback,
        "outcome_aggregate_start",
        depth=progress_depth,
        completed=0,
        total=len(raw_outcomes),
    )
    outcomes = _aggregate_inventory_outcomes(raw_outcomes, game, character)
    _emit_progress(
        progress_callback,
        "outcome_aggregate_done",
        depth=progress_depth,
        completed=len(raw_outcomes),
        total=len(raw_outcomes),
        result_total=len(outcomes),
    )
    _lru_set(
        _AGGREGATED_ACTION_OUTCOME_CACHE,
        key,
        outcomes,
        AGGREGATED_ACTION_OUTCOME_CACHE_MAX_SIZE,
    )
    _emit_progress(
        progress_callback,
        "aggregated_outcome_cache_miss",
        depth=progress_depth,
    )
    return outcomes


def _position_sort_index(game: GameRules) -> dict[str, int]:
    return {position_key(rule.id): index for index, rule in enumerate(game.positions)}


def _sorted_combo_rows(combo: Sequence[dict], game: GameRules) -> list[dict]:
    order = _position_sort_index(game)
    return sorted(
        combo,
        key=lambda row: (order.get(position_key(row["position"]), 999), position_key(row["position"])),
    )


def _combo_set_count_label(combo: Sequence[dict]) -> str:
    counts = Counter(str(row["set_name"]) for row in combo)
    if not counts:
        return "-"
    return " + ".join(
        f"{set_name}{count}"
        for set_name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


def _combo_piece_label(row: dict, game: GameRules) -> str:
    return f"{game.position_name(row['position'])}{row['set_name']}"


def _combo_loadout_label(combo: Sequence[dict], game: GameRules) -> str:
    if not combo:
        return "-"
    positions = " / ".join(_combo_piece_label(row, game) for row in _sorted_combo_rows(combo, game))
    return f"{_combo_set_count_label(combo)}；{positions}"


def _set_plan_status_label(combo: Sequence[dict], character: CharacterPreset) -> str:
    plan = character.active_set_plan()
    if plan is None or plan.is_unrestricted:
        return "不限套装"
    return (
        f"满足{plan.name}"
        if _set_plan_satisfied(tuple(combo), character)
        else f"未满足{plan.name}硬约束"
    )


def _new_rows_between(previous_inventory: list[dict], next_inventory: list[dict]) -> list[dict]:
    previous_counts = Counter(_inventory_row_signature(row) for row in previous_inventory)
    new_rows: list[dict] = []
    for row in next_inventory:
        signature = _inventory_row_signature(row)
        if previous_counts[signature] > 0:
            previous_counts[signature] -= 1
        else:
            new_rows.append(row)
    return new_rows


def _rows_present_in_combo(rows: Sequence[dict], combo: Sequence[dict]) -> list[dict]:
    combo_counts = Counter(_inventory_row_signature(row) for row in combo)
    present: list[dict] = []
    for row in rows:
        signature = _inventory_row_signature(row)
        if combo_counts[signature] > 0:
            combo_counts[signature] -= 1
            present.append(row)
    return present


def _combo_without_rows(combo: Sequence[dict], rows_to_remove: Sequence[dict]) -> list[dict]:
    remove_counts = Counter(_inventory_row_signature(row) for row in rows_to_remove)
    remaining: list[dict] = []
    for row in combo:
        signature = _inventory_row_signature(row)
        if remove_counts[signature] > 0:
            remove_counts[signature] -= 1
        else:
            remaining.append(row)
    return remaining


def _select_representative_outcome(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    spec: ActionSpec,
    remaining_horizon: int,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]],
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]],
) -> tuple[list[dict], float, tuple[float, ...]] | None:
    outcomes = _aggregated_action_outcomes_for_spec(
        inventory,
        game,
        character,
        probability_model,
        spec,
        quality_cache=quality_cache,
    )
    if not outcomes:
        return None

    best: tuple[list[dict], float, tuple[float, ...]] | None = None
    for next_inventory, probability in outcomes:
        if remaining_horizon > 0:
            value = lookahead_inventory_value(
                next_inventory,
                game,
                character,
                probability_model,
                horizon=remaining_horizon,
                memo=memo,
                quality_cache=quality_cache,
            )
        else:
            value = _cached_best_combo_value(next_inventory, game, character)
        if best is None or value > best[2] or (value == best[2] and probability > best[1]):
            best = (next_inventory, probability, value)
    return best


def _best_followup_spec(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    horizon: int,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]],
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]],
) -> ActionSpec | None:
    current_value = _cached_best_combo_value(inventory, game, character)
    best_spec: ActionSpec | None = None
    best_value = current_value
    for spec in _lookahead_action_specs(game, character, inventory):
        value = _expected_action_value(
            inventory,
            game,
            character,
            probability_model,
            spec,
            horizon,
            memo,
            quality_cache,
        )
        if value > best_value:
            best_value = value
            best_spec = spec
    return best_spec


def _representative_action_plan_labels(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    first_spec: ActionSpec,
    horizon: int,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]],
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]],
) -> tuple[str, str, str, str, list[dict]]:
    if not _cached_best_combo_value(inventory, game, character):
        return "-", "-", "-", "-", []
    if first_spec.strategy == "随机位置":
        positions = " / ".join(game.position_name(rule.id) for rule in game.positions)
        if horizon > 1:
            path = (
                f"随机位置是 {positions} 的概率混合；"
                f"horizon={max(horizon, 1)} 按实际命中位置进入条件策略，第二步在 outcome state 下递归最优"
            )
        else:
            path = f"随机位置是 {positions} 的概率混合；horizon=1 只评估单步 outcome"
        return (
            path,
            _MIXED_RANDOM_LOADOUT_LABEL,
            "请查看 H=2 方案条件分支；固定位置行可辅助审计",
            "混合动作：每个条件分支分别验算套装硬约束",
            [],
        )

    current_inventory = inventory
    current_spec: ActionSpec | None = first_spec
    action_rows: list[dict] = []
    path_parts: list[str] = []
    steps = max(horizon, 1)

    for step_index in range(1, steps + 1):
        if current_spec is None:
            break
        selected = _select_representative_outcome(
            current_inventory,
            game,
            character,
            probability_model,
            current_spec,
            steps - step_index,
            memo,
            quality_cache,
        )
        if selected is None:
            path_parts.append(f"第{step_index}步 {_action_progress_label(current_spec, game)} 无可用命中")
            break

        next_inventory, probability, _value = selected
        new_rows = _new_rows_between(current_inventory, next_inventory)
        action_rows.extend(new_rows)
        if new_rows:
            new_label = " / ".join(_combo_piece_label(row, game) for row in _sorted_combo_rows(new_rows, game))
        else:
            new_label = "未改变当前库存代表状态"
        path_parts.append(
            f"第{step_index}步 {new_label}（代表命中 {probability:.1%}）"
        )
        current_inventory = next_inventory
        if step_index >= steps:
            break
        current_spec = _best_followup_spec(
            current_inventory,
            game,
            character,
            probability_model,
            steps - step_index,
            memo,
            quality_cache,
        )

    final_combo = _best_combo_rows(current_inventory, game, character)
    if not final_combo:
        return "；".join(path_parts) if path_parts else "-", "-", "-", "-", []

    selected_action_rows = _rows_present_in_combo(action_rows, final_combo)
    complement_rows = _combo_without_rows(final_combo, selected_action_rows)
    path_label = "；".join(path_parts) if path_parts else "-"
    loadout_label = _combo_loadout_label(final_combo, game)
    set_plan_status = _set_plan_status_label(final_combo, character)
    if selected_action_rows:
        complement_label = _combo_loadout_label(complement_rows, game)
    else:
        complement_label = "代表新盘未进入最终搭配；" + _combo_loadout_label(final_combo, game)
    return path_label, loadout_label, complement_label, set_plan_status, [dict(row) for row in final_combo]


def _action_plan_label(spec: ActionSpec, game: GameRules) -> str:
    return _action_progress_label(spec, game)


def _fixed_position_branch_spec(first_spec: ActionSpec, position: str | int) -> ActionSpec:
    if first_spec.required_substats:
        strategy = "固定位置 + 固定主属性 + 固定副属性"
    elif first_spec.fixed_main_stat:
        strategy = "固定位置 + 固定主属性"
    else:
        strategy = "固定位置"
    set_options = first_spec.set_options or (first_spec.set_label,)
    return ActionSpec(
        strategy,
        first_spec.set_label,
        tuple(set_options),
        position,
        fixed_main_stat=first_spec.fixed_main_stat,
        required_substats=first_spec.required_substats,
    )


def _representative_new_piece_label(
    previous_inventory: list[dict],
    next_inventory: list[dict],
    game: GameRules,
    probability: float,
) -> str:
    new_rows = _new_rows_between(previous_inventory, next_inventory)
    if not new_rows:
        return f"未改变当前库存代表状态（代表命中 {probability:.1%}）"
    label = " / ".join(_combo_piece_label(row, game) for row in _sorted_combo_rows(new_rows, game))
    return f"{label}（代表命中 {probability:.1%}）"


def _best_followup_decision(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    horizon: int,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]],
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]],
) -> tuple[ActionSpec | None, str, str]:
    if horizon <= 0:
        return None, "-", "没有剩余步数"
    followup_spec = _best_followup_spec(
        inventory,
        game,
        character,
        probability_model,
        horizon,
        memo,
        quality_cache,
    )
    if followup_spec is None:
        return None, "-", f"该 outcome state 下 exact horizon={horizon} lookahead 未找到正提升 action"
    return (
        followup_spec,
        _action_plan_label(followup_spec, game),
        f"来自该 outcome state 的 exact horizon={horizon} lookahead",
    )


def _representative_final_loadout_after_followup(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    followup_spec: ActionSpec | None,
    followup_horizon: int,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]],
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]],
) -> tuple[str, str]:
    final_inventory = inventory
    if followup_spec is not None:
        selected = _select_representative_outcome(
            inventory,
            game,
            character,
            probability_model,
            followup_spec,
            max(followup_horizon - 1, 0),
            memo,
            quality_cache,
        )
        if selected is not None:
            final_inventory = selected[0]
    final_combo = _best_combo_rows(final_inventory, game, character)
    return _combo_loadout_label(final_combo, game), _set_plan_status_label(final_combo, character)


def _representative_branch_summary(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    first_spec: ActionSpec,
    horizon: int,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]],
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]],
) -> dict[str, Any]:
    selected = _select_representative_outcome(
        inventory,
        game,
        character,
        probability_model,
        first_spec,
        max(horizon - 1, 0),
        memo,
        quality_cache,
    )
    if selected is None:
        second_step = "-"
    else:
        next_inventory, _probability, _value = selected
        _followup_spec, followup_label, reason = _best_followup_decision(
            next_inventory,
            game,
            character,
            probability_model,
            max(horizon - 1, 0),
            memo,
            quality_cache,
        )
        second_step = followup_label if followup_label != "-" else f"-（{reason}）"
    return {
        "方案类型": "代表路径",
        "第二步策略摘要": second_step,
        "条件分支": [],
        "代表路径说明": _REPRESENTATIVE_PATH_NOTE,
    }


def _random_position_condition_branches(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    first_spec: ActionSpec,
    horizon: int,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]],
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]],
) -> list[dict[str, Any]]:
    if not game.positions:
        return []
    condition_probability = 1.0 / len(game.positions)
    branches: list[dict[str, Any]] = []
    for rule in game.positions:
        branch_spec = _fixed_position_branch_spec(first_spec, rule.id)
        selected = _select_representative_outcome(
            inventory,
            game,
            character,
            probability_model,
            branch_spec,
            max(horizon - 1, 0),
            memo,
            quality_cache,
        )
        condition = f"第1步命中 {game.position_name(rule.id)}"
        if selected is None:
            combo = _best_combo_rows(inventory, game, character)
            branches.append(
                {
                    "条件": condition,
                    "条件概率": condition_probability,
                    "代表新盘": "无可用代表 outcome",
                    "第二步 action": "-",
                    "第二步原因": "第一步无可用代表 outcome，无法生成条件后续 action",
                    "代表最终搭配": _combo_loadout_label(combo, game),
                    "套装约束": _set_plan_status_label(combo, character),
                }
            )
            continue

        next_inventory, probability, _value = selected
        followup_spec, followup_label, reason = _best_followup_decision(
            next_inventory,
            game,
            character,
            probability_model,
            max(horizon - 1, 0),
            memo,
            quality_cache,
        )
        final_loadout, set_plan_status = _representative_final_loadout_after_followup(
            next_inventory,
            game,
            character,
            probability_model,
            followup_spec,
            max(horizon - 1, 0),
            memo,
            quality_cache,
        )
        branches.append(
            {
                "条件": condition,
                "条件概率": condition_probability,
                "代表新盘": _representative_new_piece_label(inventory, next_inventory, game, probability),
                "第二步 action": followup_label,
                "第二步原因": reason,
                "代表最终搭配": final_loadout,
                "套装约束": set_plan_status,
            }
        )
    return branches


def _action_plan_explain_fields(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    spec: ActionSpec,
    horizon: int,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]],
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]],
) -> dict[str, Any]:
    first_action = _action_plan_label(spec, game)
    if horizon <= 1:
        return {
            "方案类型": "单步",
            "第一步 action": first_action,
            "第二步策略摘要": "-",
            "条件分支": [],
            "代表路径说明": "-",
        }
    if spec.strategy == "随机位置":
        branches = _random_position_condition_branches(
            inventory,
            game,
            character,
            probability_model,
            spec,
            horizon,
            memo,
            quality_cache,
        )
        return {
            "方案类型": "条件策略",
            "第一步 action": first_action,
            "第二步策略摘要": f"按命中位置分 {len(branches)} 个条件分支；第二步来自 exact lookahead",
            "条件分支": branches,
            "代表路径说明": "随机位置是混合结果，不存在唯一代表最终搭配；请查看条件分支。",
        }

    fields = _representative_branch_summary(
        inventory,
        game,
        character,
        probability_model,
        spec,
        horizon,
        memo,
        quality_cache,
    )
    fields["第一步 action"] = first_action
    return fields


def _action_position_items(
    game: GameRules,
    target_position: str | int | None,
) -> list[tuple[str | int, float]]:
    if target_position is not None:
        return [(target_position, 1.0)]
    return [(rule.id, 1.0 / len(game.positions)) for rule in game.positions]


def _candidate_distribution_for_action(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    set_options: list[str],
    target_position: str | int | None,
    fixed_main_stat: str | None = None,
    required_substats: tuple[str, ...] = (),
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]] | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_depth: int = 0,
) -> list[tuple[dict, float]]:
    work_items: list[tuple[str | int, float, str, float, str, float]] = []
    for position, position_probability in _action_position_items(game, target_position):
        valid_main_stats = game.main_stats_for(position)
        main_stats = [fixed_main_stat] if fixed_main_stat else valid_main_stats
        for set_name, set_probability in _set_distribution(probability_model, set_options):
            if not game.set_available_for_position(set_name, position):
                continue
            for main_stat in main_stats:
                if main_stat not in valid_main_stats:
                    continue
                main_probability = (
                    1.0
                    if fixed_main_stat
                    else game.main_stat_probability(position, main_stat)
                )
                if main_probability <= 0:
                    continue
                work_items.append(
                    (
                        position,
                        position_probability,
                        set_name,
                        set_probability,
                        main_stat,
                        main_probability,
                    )
                )

    _emit_progress(
        progress_callback,
        "candidate_generation_start",
        depth=progress_depth,
        completed=0,
        total=len(work_items),
    )
    distribution: list[tuple[dict, float]] = []
    for work_index, (
        position,
        position_probability,
        set_name,
        set_probability,
        main_stat,
        main_probability,
    ) in enumerate(work_items, start=1):
        _emit_progress(
            progress_callback,
            "candidate_generation_step_start",
            depth=progress_depth,
            completed=work_index - 1,
            total=len(work_items),
            action_position=position,
            action_set=set_name,
            action_main_stat=main_stat,
        )
        before_count = len(distribution)
        for candidate_row, outcome_probability in _fresh_candidate_row_distribution(
            game,
            character,
            probability_model,
            position,
            set_name,
            main_stat,
            required_substats=required_substats,
            quality_cache=quality_cache,
        ):
            probability = (
                position_probability
                * set_probability
                * main_probability
                * outcome_probability
            )
            if probability > 0:
                distribution.append((candidate_row, probability))
        _emit_progress(
            progress_callback,
            "candidate_generation_step_done",
            depth=progress_depth,
            completed=work_index,
            total=len(work_items),
            action_position=position,
            action_set=set_name,
            action_main_stat=main_stat,
            generated=len(distribution) - before_count,
        )
    return distribution


def _roll_state_from_piece(game: GameRules, piece: GearPiece) -> tuple[tuple[str, int], ...]:
    return _canonical_roll_state(
        game,
        tuple((line.stat, line.rolls) for line in piece.substats),
    )


def _advance_existing_roll_states(
    game: GameRules,
    piece: GearPiece,
    states: dict[tuple[tuple[str, int], ...], float],
) -> dict[tuple[tuple[str, int], ...], float]:
    roll_states = dict(states)
    events = [
        level
        for level in game.enhancement.event_levels
        if level > piece.level and level <= game.enhancement.max_level
    ]
    needs_add = (
        piece.initial_substat_count == 3
        and len(piece.substats) < 4
        and piece.level < game.enhancement.initial_add_level
    )
    for index, _level in enumerate(events):
        next_states: defaultdict[tuple[tuple[str, int], ...], float] = defaultdict(float)
        is_add_event = needs_add and index == 0
        for selected, probability in roll_states.items():
            if is_add_event:
                selected_stats = [stat for stat, _rolls in selected]
                draws = _add_substat_draws(game, piece, selected_stats)
                if not draws:
                    next_states[selected] += probability
                    continue
                for stat, draw_probability in draws:
                    next_state = _canonical_roll_state(game, tuple([*selected, (stat, 0)]))
                    next_states[next_state] += probability * draw_probability
                continue
            if not selected:
                next_states[selected] += probability
                continue
            for stat_index, (stat, rolls) in enumerate(selected):
                updated = list(selected)
                updated[stat_index] = (stat, rolls + 1)
                next_states[_canonical_roll_state(game, tuple(updated))] += probability / len(selected)
        roll_states = dict(next_states)
    return roll_states


def _upgrade_candidate_row_distribution(
    row: dict,
    game: GameRules,
    character: CharacterPreset,
) -> list[tuple[dict, float]]:
    piece = row.get("_piece")
    if not isinstance(piece, GearPiece) or piece.level >= game.enhancement.max_level:
        return []
    initial_state = _roll_state_from_piece(game, piece)
    final_states = _advance_existing_roll_states(game, piece, {initial_state: 1.0})
    distribution: defaultdict[tuple[float, tuple[float, ...], tuple[tuple[str, int], ...]], float] = defaultdict(float)
    for state, probability in final_states.items():
        quality_score, quality_vector = _quality_from_roll_state(state, character)
        distribution[(quality_score, quality_vector, state)] += probability

    rows: list[tuple[dict, float]] = []
    for (quality_score, quality_vector, state), probability in distribution.items():
        upgraded_piece = GearPiece(
            position=piece.position,
            set_name=piece.set_name,
            main_stat=piece.main_stat,
            level=game.enhancement.max_level,
            substats=[{"stat": stat, "rolls": rolls} for stat, rolls in state],
            locked=piece.locked,
            initial_substat_count=piece.initial_substat_count,
        )
        upgraded_row = _candidate_inventory_row(
            upgraded_piece,
            game,
            character,
            source=str(row.get("source") or _SOURCE_INVENTORY),
        )
        if "_inventory_id" in row:
            upgraded_row["_inventory_id"] = row["_inventory_id"]
        upgraded_row["_piece"] = upgraded_piece
        upgraded_row["effective_rolls"] = quality_score
        upgraded_row["quality_score"] = quality_score
        upgraded_row["quality_vector"] = quality_vector
        rows.append((upgraded_row, probability))
    return rows


def _replace_inventory_row(
    inventory: list[dict],
    inventory_id: str,
    next_row: dict,
) -> list[dict]:
    replaced = False
    next_inventory = []
    for row in inventory:
        if row.get("_inventory_id") == inventory_id and not replaced:
            next_inventory.append(next_row)
            replaced = True
        else:
            next_inventory.append(row)
    return next_inventory if replaced else [*inventory, next_row]


def _main_stat_action_options(
    game: GameRules,
    character: CharacterPreset,
    position: str | int,
) -> list[str]:
    preferred = [
        main
        for main in character.preferred_mains_for(position)
        if main in game.main_stats_for(position)
    ]
    return preferred or list(game.main_stats_for(position))


def _fixed_substat_action_options(
    game: GameRules,
    character: CharacterPreset,
    main_stat: str,
    lock_counts: tuple[int, ...] = (1, 2),
) -> list[tuple[str, ...]]:
    available_stats = set(game.available_substats(main_stat))
    priority_tiers = [
        [stat for stat in tier if stat in available_stats]
        for tier in character.priority_tiers()
    ]
    priority_tiers = [tier for tier in priority_tiers if tier]
    options: list[tuple[str, ...]] = []
    for lock_count in lock_counts:
        prefixes: list[tuple[str, ...]] = [tuple()]
        remaining = lock_count
        for tier in priority_tiers:
            if remaining <= 0:
                break
            if len(tier) <= remaining:
                prefixes = [(*prefix, *tier) for prefix in prefixes]
                remaining -= len(tier)
                continue
            prefixes = [
                (*prefix, *combo)
                for prefix in prefixes
                for combo in combinations(tier, remaining)
            ]
            remaining = 0
            break
        if remaining == 0:
            options.extend(prefix for prefix in prefixes if len(prefix) == lock_count)
    return list(dict.fromkeys(options))


def _set_options_available_for_position(
    game: GameRules,
    set_options: Sequence[str],
    position: str | int,
) -> bool:
    return any(game.set_available_for_position(set_name, position) for set_name in set_options)


def _generation_action_specs(
    game: GameRules,
    character: CharacterPreset,
    include_fixed_main: bool = True,
    include_fixed_substats: bool = True,
) -> list[ActionSpec]:
    specs: list[ActionSpec] = []
    for set_label, set_options_list in _set_action_groups(character):
        set_options = tuple(set_options_list)
        label = set_label or " / ".join(set_options)
        for rule in game.positions:
            if not _set_options_available_for_position(game, set_options, rule.id):
                continue
            specs.append(ActionSpec("固定位置", label, set_options, rule.id))
            if not include_fixed_main or len(game.main_stats_for(rule.id)) <= 1:
                continue
            for main_stat in _main_stat_action_options(game, character, rule.id):
                specs.append(
                    ActionSpec(
                        "固定位置 + 固定主属性",
                        label,
                        set_options,
                        rule.id,
                        fixed_main_stat=main_stat,
                    )
                )
                if not include_fixed_substats:
                    continue
                for required_substats in _fixed_substat_action_options(game, character, main_stat):
                    specs.append(
                        ActionSpec(
                            "固定位置 + 固定主属性 + 固定副属性",
                            label,
                            set_options,
                            rule.id,
                            fixed_main_stat=main_stat,
                            required_substats=required_substats,
                        )
                    )
        if game.random_position_actions:
            specs.append(ActionSpec("随机位置", label, tuple(set_options), None))
    return specs


def _fixed_main_refinement_action_specs(
    game: GameRules,
    character: CharacterPreset,
    fixed_spec: ActionSpec,
) -> list[ActionSpec]:
    if fixed_spec.strategy != "固定位置" or fixed_spec.target_position is None:
        return []
    if len(game.main_stats_for(fixed_spec.target_position)) <= 1:
        return []

    specs: list[ActionSpec] = []
    for main_stat in _main_stat_action_options(game, character, fixed_spec.target_position):
        specs.append(
            ActionSpec(
                "固定位置 + 固定主属性",
                fixed_spec.set_label,
                fixed_spec.set_options,
                fixed_spec.target_position,
                fixed_main_stat=main_stat,
            )
        )
    return specs


def _fixed_substat_refinement_action_specs(
    game: GameRules,
    character: CharacterPreset,
    fixed_main_spec: ActionSpec,
) -> list[ActionSpec]:
    if (
        fixed_main_spec.strategy != "固定位置 + 固定主属性"
        or fixed_main_spec.target_position is None
        or not fixed_main_spec.fixed_main_stat
    ):
        return []

    return [
        ActionSpec(
            "固定位置 + 固定主属性 + 固定副属性",
            fixed_main_spec.set_label,
            fixed_main_spec.set_options,
            fixed_main_spec.target_position,
            fixed_main_stat=fixed_main_spec.fixed_main_stat,
            required_substats=required_substats,
        )
        for required_substats in _fixed_substat_action_options(
            game,
            character,
            fixed_main_spec.fixed_main_stat,
        )
    ]


def _requirement_action_label(set_options: Sequence[str]) -> str:
    return " / ".join(set_options)


def _dominant_generation_specs_for_target(
    game: GameRules,
    character: CharacterPreset,
    set_label: str,
    set_options: tuple[str, ...],
    position: str | int,
) -> list[ActionSpec]:
    if not _set_options_available_for_position(game, set_options, position):
        return []
    main_options = _main_stat_action_options(game, character, position)
    if len(game.main_stats_for(position)) <= 1:
        return [ActionSpec("固定位置", set_label, set_options, position)]

    specs: list[ActionSpec] = []
    for main_stat in main_options:
        substat_options = _fixed_substat_action_options(game, character, main_stat)
        if substat_options:
            specs.append(
                ActionSpec(
                    "固定位置 + 固定主属性 + 固定副属性",
                    set_label,
                    set_options,
                    position,
                    fixed_main_stat=main_stat,
                    required_substats=substat_options[-1],
                )
            )
        else:
            specs.append(
                ActionSpec(
                    "固定位置 + 固定主属性",
                    set_label,
                    set_options,
                    position,
                    fixed_main_stat=main_stat,
                )
            )
    return specs


def _dominant_generation_action_specs(
    game: GameRules,
    character: CharacterPreset,
) -> list[ActionSpec]:
    specs: list[ActionSpec] = []
    for set_label, set_options_list in _set_action_groups(character):
        set_options = tuple(set_options_list)
        label = set_label or " / ".join(set_options)
        for rule in game.positions:
            specs.extend(
                _dominant_generation_specs_for_target(
                    game,
                    character,
                    label,
                    set_options,
                    rule.id,
                )
            )
    return specs


def _dedupe_action_specs(specs: Sequence[ActionSpec]) -> list[ActionSpec]:
    return list(dict.fromkeys(specs))


def _set_plan_frontier_action_specs(
    game: GameRules,
    character: CharacterPreset,
    inventory: list[dict],
) -> list[ActionSpec]:
    plan = character.active_set_plan()
    if plan is None or plan.is_unrestricted:
        return []

    best_combo = _best_combo_rows(inventory, game, character)
    if not best_combo:
        return []

    requirements = list(plan.requirements)
    selected_ids = {id(row) for row in best_combo}
    assignment_by_position = _set_plan_assignment(best_combo, character)
    specs: list[ActionSpec] = []

    if assignment_by_position is None:
        set_counts: defaultdict[str, int] = defaultdict(int)
        for row in best_combo:
            set_counts[str(row["set_name"])] += 1
        for requirement in requirements:
            current_count = max((set_counts[name] for name in requirement.set_names), default=0)
            if current_count >= requirement.pieces:
                continue
            set_options = tuple(requirement.set_names)
            label = _requirement_action_label(set_options)
            for rule in game.positions:
                if str(next((row["set_name"] for row in best_combo if position_key(row["position"]) == position_key(rule.id)), "")) in set_options:
                    continue
                specs.extend(
                    _dominant_generation_specs_for_target(
                        game,
                        character,
                        label,
                        set_options,
                        rule.id,
                    )
                )
        return _dedupe_action_specs(specs)

    positions_by_requirement: defaultdict[int, list[str | int]] = defaultdict(list)
    for row in best_combo:
        requirement_index = assignment_by_position.get(position_key(row["position"]))
        if requirement_index is not None:
            positions_by_requirement[requirement_index].append(row["position"])

    for row in inventory:
        if not _is_loadout_candidate(row, game):
            continue
        if id(row) in selected_ids:
            continue
        current_requirement_index = assignment_by_position.get(position_key(row["position"]))
        if current_requirement_index is None:
            continue
        possible_requirement_indexes = [
            index
            for index, requirement in enumerate(requirements)
            if str(row["set_name"]) in requirement.set_names
        ]
        for target_requirement_index in possible_requirement_indexes:
            if target_requirement_index == current_requirement_index:
                continue
            complement_requirement = requirements[current_requirement_index]
            set_options = tuple(complement_requirement.set_names)
            label = _requirement_action_label(set_options)
            for position in positions_by_requirement[target_requirement_index]:
                specs.extend(
                    _dominant_generation_specs_for_target(
                        game,
                        character,
                        label,
                        set_options,
                        position,
                    )
                )

    return _dedupe_action_specs(specs)


def _upgrade_action_specs(inventory: list[dict], game: GameRules) -> list[ActionSpec]:
    specs = []
    for row in inventory:
        piece = row.get("_piece")
        inventory_id = row.get("_inventory_id")
        if not isinstance(piece, GearPiece) or not inventory_id:
            continue
        if piece.level >= game.enhancement.max_level:
            continue
        specs.append(
            ActionSpec(
                "强化库存胚子",
                str(row.get("set_name", "-")),
                upgrade_inventory_id=str(inventory_id),
                upgrade_label=f"{piece.position}号位 {piece.set_name} {piece.main_stat} +{piece.level}",
            )
        )
    return specs


def _lookahead_action_specs(
    game: GameRules,
    character: CharacterPreset,
    inventory: list[dict],
) -> list[ActionSpec]:
    return _dedupe_action_specs(
        [
            *_dominant_generation_action_specs(game, character),
            *_set_plan_frontier_action_specs(game, character, inventory),
            *_upgrade_action_specs(inventory, game),
        ]
    )


def _action_outcome_distribution(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    spec: ActionSpec,
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]] | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_depth: int = 0,
) -> list[tuple[list[dict], float]]:
    if spec.upgrade_inventory_id:
        target = next(
            (row for row in inventory if row.get("_inventory_id") == spec.upgrade_inventory_id),
            None,
        )
        if target is None:
            return []
        _emit_progress(
            progress_callback,
            "upgrade_generation_start",
            depth=progress_depth,
            completed=0,
            total=1,
            action_strategy=spec.strategy,
            action_set=spec.set_label,
        )
        upgraded_rows = _upgrade_candidate_row_distribution(
            target,
            game,
            character,
        )
        _emit_progress(
            progress_callback,
            "upgrade_generation_done",
            depth=progress_depth,
            completed=1,
            total=1,
            action_strategy=spec.strategy,
            action_set=spec.set_label,
            generated=len(upgraded_rows),
        )
        return [
            (
                _replace_inventory_row(inventory, spec.upgrade_inventory_id, upgraded_row),
                probability,
            )
            for upgraded_row, probability in upgraded_rows
        ]

    return [
        ([*inventory, candidate_row], probability)
        for candidate_row, probability in _candidate_distribution_for_action(
            game,
            character,
            probability_model,
            list(spec.set_options),
            spec.target_position,
            fixed_main_stat=spec.fixed_main_stat,
            required_substats=spec.required_substats,
            quality_cache=quality_cache,
            progress_callback=progress_callback,
            progress_depth=progress_depth,
        )
    ]


def _state_transition_cache_key(
    state: EvState,
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    spec: ActionSpec,
) -> tuple:
    return (
        _game_cache_key(game),
        _character_cache_key(character),
        _probability_model_cache_key(probability_model),
        state.signature,
        spec,
    )


def _merge_state_transition(
    transitions: dict[tuple, tuple[EvState, float]],
    state: EvState,
    probability: float,
) -> None:
    if probability <= 1e-12:
        return
    existing = transitions.get(state.signature)
    if existing is None:
        transitions[state.signature] = (state, probability)
    else:
        transitions[state.signature] = (existing[0], existing[1] + probability)


def state_transition_for_action(
    state: EvState,
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    spec: ActionSpec,
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]] | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_depth: int = 0,
) -> list[tuple[EvState, float]]:
    cache_key = _state_transition_cache_key(state, game, character, probability_model, spec)
    cached = _lru_get(_STATE_TRANSITION_CACHE, cache_key)
    if cached is not None:
        _emit_progress(
            progress_callback,
            "state_transition_cache_hit",
            depth=progress_depth,
            action_strategy=spec.strategy,
            action_set=spec.set_label,
        )
        return cached

    _emit_progress(
        progress_callback,
        "state_transition_cache_miss",
        depth=progress_depth,
        action_strategy=spec.strategy,
        action_set=spec.set_label,
    )
    transitions: dict[tuple, tuple[EvState, float]] = {}
    total_probability = 0.0
    if spec.upgrade_inventory_id:
        target = next(
            (row for row in state.rows if row.get("_inventory_id") == spec.upgrade_inventory_id),
            None,
        )
        if target is not None:
            for upgraded_row, probability in _upgrade_candidate_row_distribution(target, game, character):
                next_state = state.with_replaced_upgrade_source(
                    spec.upgrade_inventory_id,
                    upgraded_row,
                    game,
                    character,
                )
                _merge_state_transition(transitions, next_state, probability)
                total_probability += probability
    else:
        for candidate_row, probability in _candidate_distribution_for_action(
            game,
            character,
            probability_model,
            list(spec.set_options),
            spec.target_position,
            fixed_main_stat=spec.fixed_main_stat,
            required_substats=spec.required_substats,
            quality_cache=quality_cache,
        ):
            next_state = state.with_candidate_row(candidate_row, game, character)
            _merge_state_transition(transitions, next_state, probability)
            total_probability += probability

    if total_probability < 1.0:
        _merge_state_transition(transitions, state, 1.0 - total_probability)

    result = [
        (next_state, probability)
        for next_state, probability in transitions.values()
        if probability > 1e-12
    ]
    _lru_set(_STATE_TRANSITION_CACHE, cache_key, result, STATE_TRANSITION_CACHE_MAX_SIZE)
    return result


def expected_state_action_value(
    state: EvState,
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    spec: ActionSpec,
    horizon: int,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]] | None = None,
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]] | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_depth: int = 0,
) -> tuple[float, ...]:
    current_value = state.best_loadout_value(game, character)
    expected = tuple(0.0 for _ in current_value)
    if not current_value:
        return expected

    memo = memo if memo is not None else {}
    transitions = state_transition_for_action(
        state,
        game,
        character,
        probability_model,
        spec,
        quality_cache=quality_cache,
        progress_callback=progress_callback,
        progress_depth=progress_depth,
    )
    _emit_progress(
        progress_callback,
        "outcomes_start",
        depth=progress_depth,
        horizon=horizon,
        completed=0,
        total=len(transitions),
    )
    for transition_index, (next_state, probability) in enumerate(transitions, start=1):
        next_value = lookahead_state_value(
            next_state,
            game,
            character,
            probability_model,
            horizon=max(horizon - 1, 0),
            memo=memo,
            quality_cache=quality_cache,
            progress_callback=progress_callback,
            progress_depth=progress_depth + 1,
        )
        expected = _add_vectors(expected, _scale_vector(next_value, probability))
        _emit_progress(
            progress_callback,
            "outcome_done",
            depth=progress_depth,
            horizon=horizon,
            completed=transition_index,
            total=len(transitions),
            probability=probability,
        )
    return expected


def lookahead_state_value(
    state: EvState,
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    horizon: int = 1,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]] | None = None,
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]] | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_depth: int = 0,
) -> tuple[float, ...]:
    if horizon <= 0:
        return state.best_loadout_value(game, character)

    memo = memo if memo is not None else {}
    key = (horizon, state.signature)
    if key in memo:
        _emit_progress(
            progress_callback,
            "memo_hit",
            depth=progress_depth,
            horizon=horizon,
        )
        return memo[key]

    current_value = state.best_loadout_value(game, character)
    specs = _lookahead_action_specs(game, character, state.to_inventory_rows())
    values = []
    _emit_progress(
        progress_callback,
        "state_start",
        depth=progress_depth,
        horizon=horizon,
        completed=0,
        total=len(specs),
    )
    for spec_index, spec in enumerate(specs, start=1):
        _emit_progress(
            progress_callback,
            "state_action_start",
            depth=progress_depth,
            horizon=horizon,
            completed=spec_index - 1,
            total=len(specs),
            action_strategy=spec.strategy,
            action_set=spec.set_label,
        )
        values.append(
            expected_state_action_value(
                state,
                game,
                character,
                probability_model,
                spec,
                horizon,
                memo=memo,
                quality_cache=quality_cache,
                progress_callback=progress_callback,
                progress_depth=progress_depth,
            )
        )
        _emit_progress(
            progress_callback,
            "state_action_done",
            depth=progress_depth,
            horizon=horizon,
            completed=spec_index,
            total=len(specs),
            action_strategy=spec.strategy,
            action_set=spec.set_label,
        )
    memo[key] = max([current_value, *values], default=current_value)
    _emit_progress(
        progress_callback,
        "state_done",
        depth=progress_depth,
        horizon=horizon,
        total=len(specs),
    )
    return memo[key]


def lookahead_inventory_value_state_dp(
    inventory: Sequence[GearPiece | dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    horizon: int = 1,
    current_count: int = 0,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]] | None = None,
) -> tuple[float, ...]:
    state = EvState.from_inventory(
        inventory,
        game,
        character,
        current_count=current_count,
    )
    return lookahead_state_value(
        state,
        game,
        character,
        probability_model,
        horizon=horizon,
        memo=memo,
    )


def configured_action_ev_workers() -> int:
    raw_value = os.environ.get("GEAR_OPTIMIZER_WORKERS")
    if raw_value:
        try:
            return max(1, int(raw_value))
        except ValueError:
            return 1
    return max(1, (os.cpu_count() or 2) - 1)


def _expected_state_action_value_worker(payload: tuple) -> ParallelActionValueResult:
    (
        rows,
        game,
        character,
        probability_model,
        spec,
        horizon,
    ) = payload
    started = time.perf_counter()
    try:
        state = EvState.from_rows(rows, game, character)
        value = expected_state_action_value(
            state,
            game,
            character,
            probability_model,
            spec,
            horizon,
            memo={},
            quality_cache={},
        )
        return ParallelActionValueResult(
            spec=spec,
            value=value,
            seconds=round(time.perf_counter() - started, 6),
        )
    except BaseException as exc:
        return ParallelActionValueResult(
            spec=spec,
            seconds=round(time.perf_counter() - started, 6),
            error=f"{type(exc).__name__}: {exc}",
        )


def parallel_expected_state_action_values(
    state: EvState,
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    specs: Sequence[ActionSpec],
    horizon: int,
    workers: int | None = None,
) -> list[ParallelActionValueResult]:
    worker_count = configured_action_ev_workers() if workers is None else max(1, workers)
    rows = state.to_inventory_rows()
    if worker_count <= 1 or len(specs) <= 1:
        return [
            _expected_state_action_value_worker(
                (rows, game, character, probability_model, spec, horizon)
            )
            for spec in specs
        ]

    results_by_index: dict[int, ParallelActionValueResult] = {}
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(
                _expected_state_action_value_worker,
                (rows, game, character, probability_model, spec, horizon),
            ): index
            for index, spec in enumerate(specs)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results_by_index[index] = future.result()
            except BaseException as exc:
                results_by_index[index] = ParallelActionValueResult(
                    spec=specs[index],
                    error=f"{type(exc).__name__}: {exc}",
                )
    return [results_by_index[index] for index in range(len(specs))]


def _expected_action_value(
    inventory: list[dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    spec: ActionSpec,
    horizon: int,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]],
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]] | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_depth: int = 0,
) -> tuple[float, ...]:
    current_value = _cached_best_combo_value(inventory, game, character)
    expected = tuple(0.0 for _ in current_value)
    if not current_value:
        return expected

    total_probability = 0.0
    outcomes = _aggregated_action_outcomes_for_spec(
        inventory,
        game,
        character,
        probability_model,
        spec,
        quality_cache=quality_cache,
        progress_callback=progress_callback,
        progress_depth=progress_depth,
    )
    outcome_total = len(outcomes)
    _emit_progress(
        progress_callback,
        "outcomes_start",
        depth=progress_depth,
        horizon=horizon,
        completed=0,
        total=outcome_total,
    )
    for outcome_index, (next_inventory, probability) in enumerate(outcomes, start=1):
        next_value = lookahead_inventory_value(
            next_inventory,
            game,
            character,
            probability_model,
            horizon=max(horizon - 1, 0),
            memo=memo,
            quality_cache=quality_cache,
            progress_callback=progress_callback,
            progress_depth=progress_depth + 1,
        )
        expected = _add_vectors(expected, _scale_vector(next_value, probability))
        total_probability += probability
        _emit_progress(
            progress_callback,
            "outcome_done",
            depth=progress_depth,
            horizon=horizon,
            completed=outcome_index,
            total=outcome_total,
            probability=probability,
        )

    if total_probability < 1.0:
        fallback_value = lookahead_inventory_value(
            inventory,
            game,
            character,
            probability_model,
            horizon=max(horizon - 1, 0),
            memo=memo,
            quality_cache=quality_cache,
            progress_callback=progress_callback,
            progress_depth=progress_depth + 1,
        )
        expected = _add_vectors(expected, _scale_vector(fallback_value, 1.0 - total_probability))
    return expected


def lookahead_inventory_value(
    inventory: Sequence[GearPiece | dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    horizon: int = 1,
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]] | None = None,
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]] | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_depth: int = 0,
) -> tuple[float, ...]:
    rows = _coerce_inventory_rows(inventory, game, character)
    if horizon <= 0:
        return _cached_best_combo_value(rows, game, character)

    memo = memo if memo is not None else {}
    key = (horizon, _inventory_signature(rows))
    if key in memo:
        _emit_progress(
            progress_callback,
            "memo_hit",
            depth=progress_depth,
            horizon=horizon,
        )
        return memo[key]

    current_value = _cached_best_combo_value(rows, game, character)
    specs = _lookahead_action_specs(game, character, rows)
    values = []
    _emit_progress(
        progress_callback,
        "state_start",
        depth=progress_depth,
        horizon=horizon,
        completed=0,
        total=len(specs),
    )
    for spec_index, spec in enumerate(specs, start=1):
        _emit_progress(
            progress_callback,
            "state_action_start",
            depth=progress_depth,
            horizon=horizon,
            completed=spec_index - 1,
            total=len(specs),
            action_strategy=spec.strategy,
            action_set=spec.set_label,
        )
        values.append(
            _expected_action_value(
                rows,
                game,
                character,
                probability_model,
                spec,
                horizon,
                memo,
                quality_cache,
                progress_callback=progress_callback,
                progress_depth=progress_depth,
            )
        )
        _emit_progress(
            progress_callback,
            "state_action_done",
            depth=progress_depth,
            horizon=horizon,
            completed=spec_index,
            total=len(specs),
            action_strategy=spec.strategy,
            action_set=spec.set_label,
        )
    memo[key] = max([current_value, *values], default=current_value)
    _emit_progress(
        progress_callback,
        "state_done",
        depth=progress_depth,
        horizon=horizon,
        total=len(specs),
    )
    return memo[key]


def lookahead_action_gain(
    inventory: Sequence[GearPiece | dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    set_options: list[str],
    target_position: str | int | None,
    horizon: int = 1,
    fixed_main_stat: str | None = None,
    required_substats: tuple[str, ...] = (),
) -> tuple[float, ...]:
    rows = _coerce_inventory_rows(inventory, game, character)
    current_value = _cached_best_combo_value(rows, game, character)
    if not current_value:
        return tuple()
    spec = ActionSpec(
        "自定义 action",
        " / ".join(set_options),
        tuple(set_options),
        target_position,
        fixed_main_stat=fixed_main_stat,
        required_substats=required_substats,
    )
    value = _expected_action_value(
        rows,
        game,
        character,
        probability_model,
        spec,
        max(horizon, 1),
        memo={},
        quality_cache={},
    )
    return _positive_gain(value, current_value)


def immediate_piece_gain(
    inventory: Sequence[GearPiece | dict],
    piece: GearPiece | dict,
    game: GameRules,
    character: CharacterPreset,
) -> tuple[float, ...]:
    rows = _coerce_inventory_rows(inventory, game, character)
    current_value = _cached_best_combo_value(rows, game, character)
    piece_row = _coerce_inventory_rows([piece], game, character)[0]
    next_value = _cached_best_combo_value([*rows, piece_row], game, character)
    return _positive_gain(next_value, current_value)


def option_piece_gain(
    inventory: Sequence[GearPiece | dict],
    piece: GearPiece | dict,
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    horizon: int = 1,
) -> tuple[float, ...]:
    rows = _coerce_inventory_rows(inventory, game, character)
    piece_row = _coerce_inventory_rows([piece], game, character)[0]
    with_piece = [*rows, piece_row]
    immediate_value = _cached_best_combo_value(with_piece, game, character)
    future_value = lookahead_inventory_value(
        with_piece,
        game,
        character,
        probability_model,
        horizon=horizon,
        memo={},
        quality_cache={},
    )
    return _positive_gain(future_value, immediate_value)


def _expected_action_gain(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    analysis: CurrentGearAnalysis,
    set_options: list[str],
    target_position: str | int | None,
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]] | None = None,
    inventory_rows: list[dict] | None = None,
) -> tuple[float, ...]:
    current_inventory = (
        [dict(row) for row in inventory_rows]
        if inventory_rows is not None
        else _current_inventory_rows(analysis, character)
    )
    current_value = _cached_best_combo_value(current_inventory, game, character)
    expected = tuple(0.0 for _ in current_value)
    if not current_value:
        return expected

    for candidate_row, probability in _candidate_distribution_for_action(
        game,
        character,
        probability_model,
        set_options,
        target_position,
        quality_cache=quality_cache,
    ):
        next_value = _cached_best_combo_value(
            [*current_inventory, candidate_row],
            game,
            character,
        )
        gain = _positive_gain(next_value, current_value)
        expected = _add_vectors(expected, _scale_vector(gain, probability))
    return expected


def action_gain_for_spec(
    inventory: Sequence[GearPiece | dict],
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    spec: ActionSpec,
    horizon: int = 1,
) -> tuple[float, ...]:
    rows = _coerce_inventory_rows(inventory, game, character)
    current_value = _cached_best_combo_value(rows, game, character)
    if not current_value:
        return tuple()
    value = _expected_action_value(
        rows,
        game,
        character,
        probability_model,
        spec,
        max(horizon, 1),
        memo={},
        quality_cache={},
    )
    return _positive_gain(value, current_value)


def _action_costs(
    spec: ActionSpec,
    probability_model: ProbabilityModel,
) -> tuple[float, float, float]:
    if spec.strategy == "随机位置":
        mother = probability_model.resource_cost("mother_disk_random_position_attempt", 3.0)
    elif spec.strategy == "强化库存胚子":
        mother = 0.0
    else:
        mother = probability_model.resource_cost("mother_disk_fixed_position_attempt", 6.0)
    tuner = (
        probability_model.resource_cost("tuner_per_fixed_main_attempt", 1.0)
        if spec.fixed_main_stat
        else 0.0
    )
    core = _fixed_substat_extra_resource_cost(
        probability_model,
        len(spec.required_substats),
    )
    return mother, tuner, core


def _fixed_substat_extra_resource_cost(
    probability_model: ProbabilityModel,
    lock_count: int,
) -> float:
    if lock_count <= 0:
        return 0.0
    configured = probability_model.resource_cost(
        f"core_fixed_substat_{lock_count}_attempt",
        -1.0,
    )
    if configured >= 0:
        return configured
    return probability_model.resource_cost("core_per_fixed_substat_attempt", 1.0) * lock_count


def _action_position_scope_label(game: GameRules) -> str:
    keys = [position_key(rule.id) for rule in game.positions]
    if keys and all(key.isdigit() for key in keys):
        numbers = [int(key) for key in keys]
        ordered = sorted(numbers)
        if ordered == list(range(ordered[0], ordered[-1] + 1)):
            return f"{ordered[0]}-{ordered[-1]}"
    return " / ".join(game.position_name(rule.id) for rule in game.positions)


def _action_position_label(spec: ActionSpec, game: GameRules) -> str:
    if spec.strategy == "随机位置":
        return f"{_action_position_scope_label(game)} 随机"
    if spec.strategy == "强化库存胚子":
        return spec.upgrade_label or "库存胚子"
    if spec.target_position is None:
        return "-"
    return game.position_name(spec.target_position)


def _action_main_label(spec: ActionSpec) -> str:
    return spec.fixed_main_stat or "不固定"


def _action_substat_label(spec: ActionSpec) -> str:
    return " + ".join(spec.required_substats) if spec.required_substats else "不固定"


def _action_type_label(spec: ActionSpec) -> str:
    if spec.strategy == "强化库存胚子":
        return "库存升级机会"
    return "调律母盘"


def _action_progress_label(spec: ActionSpec, game: GameRules) -> str:
    if spec.strategy == "强化库存胚子":
        return f"升级已有库存（非调律） / {_action_position_label(spec, game)}"
    parts = [spec.strategy, spec.set_label]
    position = _action_position_label(spec, game)
    if position != "-":
        parts.append(position)
    if spec.fixed_main_stat:
        parts.append(spec.fixed_main_stat)
    if spec.required_substats:
        parts.append("+".join(spec.required_substats))
    return " / ".join(str(part) for part in parts if part)


def _quality_vector_label(vector: tuple[float, ...], character: CharacterPreset) -> str:
    if not vector:
        return "-"

    def append_part(parts: list[str], label: str, value: float) -> None:
        if value >= _DISPLAY_EPSILON:
            parts.append(f"{label}+{value:.3f}")
        elif value <= -_DISPLAY_EPSILON:
            parts.append(f"{label}{value:.3f}")

    priority = character.substat_priority
    main_gain = vector[0]
    quality = vector[1:-2]
    effective_gain = vector[-2]
    parts = []
    append_part(parts, "主属性", main_gain)
    if priority:
        core_total = quality[0] if quality else 0.0
        usable_index = 1 + len(priority.core)
        usable_total = quality[usable_index] if usable_index < len(quality) else 0.0
        append_part(parts, "核心", core_total)
        append_part(parts, "可用", usable_total)
    append_part(parts, "有效", effective_gain)
    return "，".join(parts) if parts else "0"


def _vector_efficiency(vector: tuple[float, ...], cost: float) -> tuple[float, ...]:
    if cost <= 0:
        return vector
    return tuple(value / cost for value in vector)


def _action_ev_cache_key(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    analysis: CurrentGearAnalysis,
    inventory_rows: list[dict] | None = None,
    horizon: int = 1,
    use_state_dp: bool = False,
) -> str:
    plan = character.active_set_plan()
    priority = character.substat_priority
    data = {
        "fingerprints": {
            "game": _game_cache_key(game),
            "character": _character_cache_key(character),
            "probability_model": _probability_model_cache_key(probability_model),
        },
        "game": {
            "id": game.id,
            "positions": [position.model_dump(mode="json") for position in game.positions],
            "sets": game.sets,
            "position_set_names": game.position_set_names,
            "random_position_actions": game.random_position_actions,
            "sub_stats": game.sub_stats,
            "main_stat_probabilities": game.main_stat_probabilities,
            "sub_stat_probabilities": game.sub_stat_probabilities,
            "enhancement": game.enhancement.model_dump(mode="json"),
        },
        "character": {
            "id": character.id,
            "priority": priority.model_dump(mode="json") if priority else None,
            "preferred_main_stats": character.preferred_main_stats,
            "set_plan": plan.model_dump(mode="json") if plan else None,
        },
        "probability_model": {
            "id": probability_model.id,
            "target_set_probability": probability_model.target_set_probability,
            "initial_substat_count_probabilities": probability_model.initial_substat_count_probabilities,
            "resource_costs": probability_model.resource_costs,
        },
        "horizon": horizon,
        "engine": "state_dp" if use_state_dp else "inventory_recursive",
        "scores": [
            {
                "position": score.position,
                "set_name": score.set_name,
                "main_stat": score.main_stat,
                "locked": score.locked,
                "main_stat_preferred": score.main_stat_preferred,
                "effective_rolls": score.effective_rolls,
                "quality_score": score.weighted_score,
                "substat_details": score.substat_details,
            }
            for score in analysis.scores
        ],
        "inventory_rows": [
            {
                "position": row["position"],
                "set_name": row["set_name"],
                "locked": row.get("locked", False),
                "source": row.get("source", _SOURCE_INVENTORY),
                "allow_unfinished_loadout": row.get("_allow_unfinished_loadout", False),
                "main_preferred": row["main_preferred"],
                "effective_rolls": row["effective_rolls"],
                "quality_score": row["quality_score"],
                "quality_vector": row["quality_vector"],
                "piece_signature": (
                    row["_piece"].level,
                    row["_piece"].initial_substat_count,
                    [(line.stat, line.rolls) for line in row["_piece"].substats],
                    _effective_revealed_next_substat(row["_piece"], game),
                )
                if isinstance(row.get("_piece"), GearPiece)
                else None,
            }
            for row in (inventory_rows or [])
        ],
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _comparison_scope_label(spec: ActionSpec, relative: str, game: GameRules) -> str:
    if spec.strategy == "随机位置":
        return f"随机混合：{_action_position_scope_label(game)} 固定位置按概率加权；不是单一代表搭配"
    if spec.strategy == "固定位置":
        return f"固定位置基础行；{relative.replace('随机', '随机混合')}"
    if spec.strategy == "固定位置 + 固定主属性":
        return f"相对同位置固定位置；{relative}"
    if spec.strategy == "固定位置 + 固定主属性 + 固定副属性":
        return f"相对同位置锁主属性；{relative}"
    if spec.strategy == "强化库存胚子":
        return "库存升级机会；非调律母盘，不消耗母盘，不折算强化材料"
    return relative


def _relative_action_label(
    spec: ActionSpec,
    efficiency: tuple[float, ...],
    set_plan_blocked: bool,
    random_efficiency_by_set: dict[str, tuple[float, ...]],
    base_fixed_efficiency_by_target: dict[tuple[str, str], tuple[float, ...]],
    fixed_main_efficiency_by_target: dict[tuple[str, str, str], tuple[float, ...]],
    *,
    defer_fixed_random_comparison: bool = False,
    random_baseline_enabled: bool = True,
) -> str:
    if set_plan_blocked:
        return "未满足套装硬约束，不作为当前 horizon 推荐"
    if spec.strategy == "随机位置":
        return "基准"
    if spec.strategy == "强化库存胚子":
        return "库存升级机会"
    if spec.strategy == "固定位置 + 固定主属性":
        fixed_key = (spec.set_label, position_key(spec.target_position))
        fixed_efficiency = base_fixed_efficiency_by_target.get(fixed_key, tuple())
        if not random_baseline_enabled:
            return (
                "优于固定位置，才建议锁主属性"
                if fixed_efficiency and _vector_greater(efficiency, fixed_efficiency)
                else "不如固定位置，不建议锁主属性"
            )
        return (
            "固定位置已优于随机；优于固定位置，才建议锁主属性"
            if fixed_efficiency and _vector_greater(efficiency, fixed_efficiency)
            else "固定位置已优于随机；不如固定位置，不建议锁主属性"
        )
    if spec.strategy == "固定位置 + 固定主属性 + 固定副属性":
        fixed_main_key = (
            spec.set_label,
            position_key(spec.target_position),
            str(spec.fixed_main_stat),
        )
        fixed_main_efficiency = fixed_main_efficiency_by_target.get(fixed_main_key, tuple())
        if not random_baseline_enabled:
            return (
                "优于锁主属性，才建议锁副属性"
                if fixed_main_efficiency and _vector_greater(efficiency, fixed_main_efficiency)
                else "不如锁主属性，不建议锁副属性"
            )
        return (
            "锁主属性已优于固定位置；优于锁主属性，才建议锁副属性"
            if fixed_main_efficiency and _vector_greater(efficiency, fixed_main_efficiency)
            else "锁主属性已优于固定位置；不如锁主属性，不建议锁副属性"
        )
    if not random_baseline_enabled and spec.strategy == "固定位置":
        return "固定位置基准"
    random_efficiency = random_efficiency_by_set.get(spec.set_label, tuple())
    if defer_fixed_random_comparison and spec.strategy == "固定位置" and not random_efficiency:
        return "等待随机基准"
    return (
        "优于随机，才建议固定"
        if random_efficiency and _vector_greater(efficiency, random_efficiency)
        else "不如随机，不建议固定"
    )


def _remember_action_efficiency(
    spec: ActionSpec,
    efficiency: tuple[float, ...],
    relative: str,
    base_fixed_efficiency_by_target: dict[tuple[str, str], tuple[float, ...]],
    fixed_main_efficiency_by_target: dict[tuple[str, str, str], tuple[float, ...]],
) -> None:
    if spec.strategy == "固定位置" and relative in {
        "优于随机，才建议固定",
        "固定位置基准",
    }:
        base_fixed_efficiency_by_target[
            (spec.set_label, position_key(spec.target_position))
        ] = efficiency
    elif (
        spec.strategy == "固定位置 + 固定主属性"
        and spec.fixed_main_stat
        and relative in {
            "固定位置已优于随机；优于固定位置，才建议锁主属性",
            "优于固定位置，才建议锁主属性",
        }
    ):
        fixed_main_efficiency_by_target[
            (spec.set_label, position_key(spec.target_position), spec.fixed_main_stat)
        ] = efficiency


def _initial_weight_states(
    game: GameRules,
    character: CharacterPreset,
    main_stat: str,
    line_count: int,
) -> dict[tuple[float, ...], float]:
    weight_states: defaultdict[tuple[float, ...], float] = defaultdict(float)
    for selected, probability in _initial_stat_states(game, main_stat, line_count).items():
        weights = tuple(character.weight_for(stat) for stat in selected)
        weight_states[weights] += probability
    return dict(weight_states)


def _advance_stat_states(
    game: GameRules,
    character: CharacterPreset,
    main_stat: str,
    states: dict[tuple[str, ...], float],
    initial_count: int,
) -> dict[tuple[float, float, tuple[float, ...]], float]:
    stat_states: dict[tuple[float, float, tuple[float, ...], tuple[str, ...]], float] = {
        (
            sum(1 for stat in selected if character.weight_for(stat) > 0),
            sum(character.weight_for(stat) for stat in selected),
            tuple(character.weight_for(stat) for stat in selected),
            selected,
        ): probability
        for selected, probability in states.items()
    }

    for index, _level in enumerate(game.enhancement.event_levels):
        next_states: defaultdict[tuple[float, float, tuple[float, ...], tuple[str, ...]], float] = defaultdict(float)
        is_add_event = initial_count == 3 and index == 0
        for (effective_score, weighted_score, weights, selected), probability in stat_states.items():
            if is_add_event:
                available = game.available_substats(main_stat, list(selected))
                draws = _weighted_draws(available, game.sub_stat_probabilities)
                if not draws:
                    next_states[(effective_score, weighted_score, weights, selected)] += probability
                    continue
                for stat, draw_probability in draws:
                    stat_weight = character.weight_for(stat)
                    next_selected = _canonical_stats(game, tuple([*selected, stat]))
                    next_weights = tuple(character.weight_for(item) for item in next_selected)
                    next_states[
                        (
                            effective_score + (1 if stat_weight > 0 else 0),
                            weighted_score + stat_weight,
                            next_weights,
                            next_selected,
                        )
                    ] += probability * draw_probability
                continue
            if not weights:
                next_states[(effective_score, weighted_score, weights, selected)] += probability
                continue
            for stat in selected:
                weight = character.weight_for(stat)
                next_states[
                    (
                        effective_score + (1 if weight > 0 else 0),
                        weighted_score + weight,
                        weights,
                        selected,
                    )
                ] += probability / len(weights)
        stat_states = dict(next_states)

    score_states: defaultdict[tuple[float, float, tuple[float, ...]], float] = defaultdict(float)
    for (effective_score, weighted_score, weights, _selected), probability in stat_states.items():
        score_states[(effective_score, weighted_score, weights)] += probability
    return dict(score_states)


def expected_fresh_piece_weighted_score(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    main_stat: str,
) -> float:
    distribution = fresh_piece_weighted_score_distribution(
        game,
        character,
        probability_model,
        main_stat,
    )
    return round(
        sum(score * probability for score, probability in distribution.items()),
        4,
    )


def expected_fresh_piece_effective_score(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    main_stat: str,
    required_substats: tuple[str, ...] = (),
) -> float:
    distribution = fresh_piece_effective_score_distribution(
        game,
        character,
        probability_model,
        main_stat,
        required_substats,
    )
    return round(
        sum(score * probability for score, probability in distribution.items()),
        4,
    )


def fresh_piece_weighted_score_distribution(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    main_stat: str,
    required_substats: tuple[str, ...] = (),
) -> dict[float, float]:
    distribution: defaultdict[float, float] = defaultdict(float)
    for count_text, count_probability in probability_model.initial_substat_count_probabilities.items():
        initial_count = int(count_text)
        initial_states = _initial_stat_states(
            game,
            main_stat,
            initial_count,
            required_substats,
        )
        final_states = _advance_stat_states(
            game,
            character,
            main_stat,
            initial_states,
            initial_count,
        )
        for (_effective_score, weighted_score, _weights), probability in final_states.items():
            distribution[round(weighted_score, 6)] += count_probability * probability
    return dict(sorted(distribution.items()))


def fresh_piece_effective_score_distribution(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    main_stat: str,
    required_substats: tuple[str, ...] = (),
) -> dict[float, float]:
    distribution: defaultdict[float, float] = defaultdict(float)
    for count_text, count_probability in probability_model.initial_substat_count_probabilities.items():
        initial_count = int(count_text)
        initial_states = _initial_stat_states(
            game,
            main_stat,
            initial_count,
            required_substats,
        )
        final_states = _advance_stat_states(
            game,
            character,
            main_stat,
            initial_states,
            initial_count,
        )
        for (effective_score, _weighted_score, _weights), probability in final_states.items():
            distribution[round(effective_score, 6)] += count_probability * probability
    return dict(sorted(distribution.items()))


def initial_substat_tier_rows(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    analysis: CurrentGearAnalysis,
) -> list[dict[str, float | str]]:
    priority_by_position = {
        position_key(item["position"]): index + 1
        for index, item in enumerate(analysis.relative_priority)
    }
    rows: list[dict[str, float | str]] = []
    for rule in game.positions:
        key = position_key(rule.id)
        preferred_mains = [
            main
            for main in (character.preferred_mains_for(key) or list(rule.main_stats))
            if main in rule.main_stats
        ]
        if not preferred_mains:
            continue
        main_stat = preferred_mains[0]
        for count_text, count_probability in probability_model.initial_substat_count_probabilities.items():
            initial_count = int(count_text)
            initial_states = _initial_stat_states(game, main_stat, initial_count)
            grouped: defaultdict[int, list[tuple[tuple[str, ...], float]]] = defaultdict(list)
            for selected, probability in initial_states.items():
                effective_lines = sum(1 for stat in selected if character.weight_for(stat) > 0)
                grouped[effective_lines].append((selected, probability))
            for effective_lines, state_items in sorted(grouped.items(), reverse=True):
                tier_probability = sum(probability for _selected, probability in state_items)
                conditional_states = {
                    selected: probability / tier_probability
                    for selected, probability in state_items
                    if tier_probability > 0
                }
                final_states = _advance_stat_states(
                    game,
                    character,
                    main_stat,
                    conditional_states,
                    initial_count,
                )
                final_expected = sum(
                    weighted_score * probability
                    for (_effective_score, weighted_score, _weights), probability in final_states.items()
                )
                final_effective_expected = sum(
                    effective_score * probability
                    for (effective_score, _weighted_score, _weights), probability in final_states.items()
                )
                rows.append(
                    {
                        "_sort_priority": priority_by_position.get(key, 999),
                        "_sort_count": initial_count,
                        "_sort_lines": -effective_lines,
                        "位置": game.position_name(rule.id),
                        "当前补弱顺位": priority_by_position.get(key, "-"),
                        "参考主属性": main_stat,
                        "初始词条数": initial_count,
                        "胚子挡位": f"{initial_count}中{effective_lines}",
                        "条件概率": round(tier_probability, 6),
                        "总出现概率": round(count_probability * tier_probability, 6),
                        "满级有效期望": round(final_effective_expected, 3),
                        "满级质量期望": round(final_expected, 3),
                    }
                )
    sorted_rows = sorted(
        rows,
        key=lambda row: (row["_sort_priority"], row["_sort_count"], row["_sort_lines"]),
    )
    return [
        {key: value for key, value in row.items() if not key.startswith("_sort_")}
        for row in sorted_rows
    ]


def _probability_at_least(distribution: dict[float, float], threshold: float) -> float:
    return sum(probability for score, probability in distribution.items() if score >= threshold)


def _expected_cost(cost_per_attempt: float, probability: float) -> float:
    if probability <= 0:
        return inf
    return cost_per_attempt / probability


def _saved_mother_disks_for_equal_gain(
    base_gain: float,
    resource_gain: float,
    mother_cost_per_attempt: float,
) -> float:
    if resource_gain <= base_gain:
        return 0.0
    if base_gain <= 0:
        return inf
    base_attempts_for_resource_gain = mother_cost_per_attempt * resource_gain / base_gain
    return max(base_attempts_for_resource_gain - mother_cost_per_attempt, 0.0)


def _advanced_material_equivalent_attempts(
    probability_model: ProbabilityModel,
) -> float:
    configured = probability_model.resource_cost(
        "advanced_material_equivalent_fixed_position_attempts",
        -1.0,
    )
    if configured >= 0:
        return configured
    remains_cost = probability_model.resource_cost("self_modeling_resin_remains_cost", 0.0)
    remains_per_attempt = probability_model.resource_cost("remains_per_fixed_position_attempt", 0.0)
    if remains_cost > 0 and remains_per_attempt > 0:
        return remains_cost / remains_per_attempt
    return 0.0


def _material_opportunity_row_fields(
    saved_effective: float,
    saved_quality: float,
    advanced_material_count: float,
    probability_model: ProbabilityModel,
) -> dict[str, float | str]:
    equivalent_attempts = _advanced_material_equivalent_attempts(probability_model)
    opportunity_cost = advanced_material_count * equivalent_attempts

    def net_saved(saved: float) -> float:
        if isfinite(saved):
            return saved - opportunity_cost
        return inf

    net_effective = net_saved(saved_effective)
    net_quality = net_saved(saved_quality)
    if opportunity_cost <= 0:
        decision = "未配置高级素材折算"
    elif isfinite(saved_effective) and saved_effective <= opportunity_cost:
        decision = "不推荐：有效口径省量未超过高级素材机会成本"
    else:
        decision = "推荐：有效口径省量超过高级素材机会成本"
    return {
        "高级素材折算普通合成/个": round(equivalent_attempts, 3),
        "高级素材机会成本": round(opportunity_cost, 3),
        "有效净省母盘": round(net_effective, 3) if isfinite(net_effective) else "∞",
        "质量净省母盘": round(net_quality, 3) if isfinite(net_quality) else "∞",
        "素材判断": decision,
    }


def fixed_main_gain_ladder_rows(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    analysis: CurrentGearAnalysis,
    gain_targets: tuple[float, ...] = (1.0, 2.0, 3.0),
) -> list[dict[str, float | str]]:
    current_by_position = {
        position_key(score.position): score.weighted_score
        for score in analysis.scores
    }
    current_effective_by_position = {
        position_key(score.position): score.effective_rolls
        for score in analysis.scores
    }
    priority_by_position = {
        position_key(item["position"]): index + 1
        for index, item in enumerate(analysis.relative_priority)
    }
    fixed_position_cost = probability_model.resource_cost("mother_disk_fixed_position_attempt", 6.0)
    tuner_cost = probability_model.resource_cost("tuner_per_fixed_main_attempt", 1.0)
    rows: list[dict[str, float | str]] = []

    for rule in game.positions:
        key = position_key(rule.id)
        current_score = current_by_position.get(key, 0.0)
        current_effective = current_effective_by_position.get(key, 0.0)
        preferred_mains = [
            main
            for main in (character.preferred_mains_for(key) or list(rule.main_stats))
            if main in rule.main_stats
        ]
        if not preferred_mains:
            continue
        distributions = {
            main: fresh_piece_weighted_score_distribution(game, character, probability_model, main)
            for main in preferred_mains
        }
        effective_expectations = {
            main: expected_fresh_piece_effective_score(game, character, probability_model, main)
            for main in preferred_mains
        }
        unfixed_effective_gain = sum(
            game.main_stat_probability(key, main)
            * max(effective_expectations[main] - current_effective, 0.0)
            for main in preferred_mains
        )
        for target_gain in gain_targets:
            threshold = current_score + target_gain
            unfixed_probability = sum(
                game.main_stat_probability(key, main)
                * _probability_at_least(distributions[main], threshold)
                for main in preferred_mains
            )
            unfixed_mother_disks = _expected_cost(fixed_position_cost, unfixed_probability)
            fixed_candidates: list[tuple[float, float, str]] = []
            for main in preferred_mains:
                probability = _probability_at_least(distributions[main], threshold)
                fixed_candidates.append(
                    (
                        probability,
                        _expected_cost(fixed_position_cost, probability),
                        main,
                    )
                )
            fixed_probability, fixed_mother_disks, best_main = max(
                fixed_candidates,
                key=lambda item: (
                    item[0],
                    -fixed_candidates.index(item),
                ),
            )
            expected_tuners = _expected_cost(tuner_cost, fixed_probability)
            if not isfinite(unfixed_mother_disks) and not isfinite(fixed_mother_disks):
                mother_saved = 0.0
            else:
                mother_saved = max(unfixed_mother_disks - fixed_mother_disks, 0.0)
            rows.append(
                {
                    "_sort_priority": priority_by_position.get(key, 999),
                    "_sort_gain": target_gain,
                    "位置": game.position_name(rule.id),
                    "当前补弱顺位": priority_by_position.get(key, "-"),
                    "推荐主属性": best_main,
                    "当前质量分": round(current_score, 3),
                    "当前有效词条": round(current_effective, 3),
                    "提升目标": f"+{target_gain:g}",
                    "目标质量分": round(threshold, 3),
                    "不锁主属性有效提升": round(unfixed_effective_gain, 3),
                    "固定主属性有效提升": round(
                        max(effective_expectations[best_main] - current_effective, 0.0),
                        3,
                    ),
                    "不锁主属性概率": round(unfixed_probability, 6),
                    "固定主属性概率": round(fixed_probability, 6),
                    "不锁主属性母盘": round(unfixed_mother_disks, 3) if isfinite(unfixed_mother_disks) else "∞",
                    "固定主属性母盘": round(fixed_mother_disks, 3) if isfinite(fixed_mother_disks) else "∞",
                    "省母盘": round(mother_saved, 3) if isfinite(mother_saved) else "∞",
                    "期望校音器": round(expected_tuners, 3) if isfinite(expected_tuners) else "∞",
                }
            )
    sorted_rows = sorted(rows, key=lambda row: (row["_sort_priority"], row["_sort_gain"]))
    return [
        {key: value for key, value in row.items() if not key.startswith("_sort_")}
        for row in sorted_rows
    ]


def fixed_substat_gain_ladder_rows(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    analysis: CurrentGearAnalysis,
    gain_targets: tuple[float, ...] = (1.0, 2.0, 3.0),
    lock_counts: tuple[int, ...] = (1, 2),
) -> list[dict[str, float | str]]:
    current_by_position = {
        position_key(score.position): score.weighted_score
        for score in analysis.scores
    }
    current_effective_by_position = {
        position_key(score.position): score.effective_rolls
        for score in analysis.scores
    }
    priority_by_position = {
        position_key(item["position"]): index + 1
        for index, item in enumerate(analysis.relative_priority)
    }
    fixed_position_cost = probability_model.resource_cost("mother_disk_fixed_position_attempt", 6.0)
    tuner_cost = probability_model.resource_cost("tuner_per_fixed_main_attempt", 1.0)
    rows: list[dict[str, float | str]] = []

    for rule in game.positions:
        key = position_key(rule.id)
        current_score = current_by_position.get(key, 0.0)
        current_effective = current_effective_by_position.get(key, 0.0)
        preferred_mains = [
            main
            for main in (character.preferred_mains_for(key) or list(rule.main_stats))
            if main in rule.main_stats
        ]
        if not preferred_mains:
            continue
        main_distributions = {
            main: fresh_piece_weighted_score_distribution(game, character, probability_model, main)
            for main in preferred_mains
        }
        main_effective_expectations = {
            main: expected_fresh_piece_effective_score(game, character, probability_model, main)
            for main in preferred_mains
        }
        for target_gain in gain_targets:
            threshold = current_score + target_gain
            fixed_main_candidates = [
                (
                    _probability_at_least(main_distributions[main], threshold),
                    main,
                )
                for main in preferred_mains
            ]
            fixed_main_probability, best_main = max(
                fixed_main_candidates,
                key=lambda item: (item[0], -fixed_main_candidates.index(item)),
            )
            fixed_main_mother_disks = _expected_cost(fixed_position_cost, fixed_main_probability)
            available_effective = [
                stat
                for stat in character.ordered_effective_substats()
                if stat in game.available_substats(best_main)
            ]
            for lock_count in lock_counts:
                fixed_substats = tuple(available_effective[:lock_count])
                if len(fixed_substats) < lock_count:
                    continue
                locked_distribution = fresh_piece_weighted_score_distribution(
                    game,
                    character,
                    probability_model,
                    best_main,
                    fixed_substats,
                )
                locked_effective_expectation = expected_fresh_piece_effective_score(
                    game,
                    character,
                    probability_model,
                    best_main,
                    fixed_substats,
                )
                locked_probability = _probability_at_least(locked_distribution, threshold)
                locked_mother_disks = _expected_cost(fixed_position_cost, locked_probability)
                expected_tuners = _expected_cost(tuner_cost, locked_probability)
                expected_cores = _expected_cost(
                    _fixed_substat_extra_resource_cost(probability_model, lock_count),
                    locked_probability,
                )
                if not isfinite(fixed_main_mother_disks) and not isfinite(locked_mother_disks):
                    mother_saved = 0.0
                else:
                    mother_saved = max(fixed_main_mother_disks - locked_mother_disks, 0.0)
                rows.append(
                    {
                        "_sort_priority": priority_by_position.get(key, 999),
                        "_sort_gain": target_gain,
                        "_sort_lock": lock_count,
                        "位置": game.position_name(rule.id),
                        "当前补弱顺位": priority_by_position.get(key, "-"),
                        "主属性": best_main,
                        "锁定副属性": " + ".join(fixed_substats),
                        "当前有效词条": round(current_effective, 3),
                        "提升目标": f"+{target_gain:g}",
                        "目标质量分": round(threshold, 3),
                        "固定主属性有效提升": round(
                            max(main_effective_expectations[best_main] - current_effective, 0.0),
                            3,
                        ),
                        "锁副属性有效提升": round(
                            max(locked_effective_expectation - current_effective, 0.0),
                            3,
                        ),
                        "固定主属性概率": round(fixed_main_probability, 6),
                        "锁副属性概率": round(locked_probability, 6),
                        "固定主属性母盘": round(fixed_main_mother_disks, 3)
                        if isfinite(fixed_main_mother_disks)
                        else "∞",
                        "锁副属性母盘": round(locked_mother_disks, 3)
                        if isfinite(locked_mother_disks)
                        else "∞",
                        "省母盘": round(mother_saved, 3) if isfinite(mother_saved) else "∞",
                        "期望校音器": round(expected_tuners, 3) if isfinite(expected_tuners) else "∞",
                        "期望共鸣核": round(expected_cores, 3) if isfinite(expected_cores) else "∞",
                    }
                )
    sorted_rows = sorted(
        rows,
        key=lambda row: (row["_sort_priority"], row["_sort_gain"], row["_sort_lock"]),
    )
    return [
        {key: value for key, value in row.items() if not key.startswith("_sort_")}
        for row in sorted_rows
    ]


def position_strategy_efficiency_rows(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    analysis: CurrentGearAnalysis,
    inventory_pieces: Sequence[GearPiece] | None = None,
    horizon: int = 1,
    progress_callback: ProgressCallback | None = None,
    use_state_dp: bool = False,
) -> list[dict[str, float | str]]:
    inventory_rows = (
        inventory_rows_from_pieces(
            inventory_pieces,
            game,
            character,
            current_count=len(analysis.scores),
        )
        if inventory_pieces is not None
        else _current_inventory_rows(analysis, character)
    )
    cache_key = _action_ev_cache_key(
        game,
        character,
        probability_model,
        analysis,
        inventory_rows=inventory_rows,
        horizon=horizon,
        use_state_dp=use_state_dp,
    )
    cached = _lru_get(_ACTION_EV_ROWS_CACHE, cache_key)
    if cached is not None:
        _emit_progress(
            progress_callback,
            "cache_hit",
            phase="action_ev",
            completed=1,
            total=1,
            label="已使用上次精确计算缓存",
        )
        return [dict(row) for row in cached]

    rows: list[dict[str, float | str]] = []
    random_efficiency_by_set: dict[str, tuple[float, ...]] = {}
    base_fixed_efficiency_by_target: dict[tuple[str, str], tuple[float, ...]] = {}
    fixed_main_efficiency_by_target: dict[tuple[str, str, str], tuple[float, ...]] = {}
    generation_specs = _generation_action_specs(
        game,
        character,
        include_fixed_main=False,
        include_fixed_substats=False,
    )
    base_fixed_specs = [
        spec for spec in generation_specs if spec.strategy == "固定位置"
    ]
    random_specs = [
        spec for spec in generation_specs if spec.strategy == "随机位置"
    ]
    upgrade_specs = _upgrade_action_specs(inventory_rows, game)
    base_specs = [
        *base_fixed_specs,
        *random_specs,
        *upgrade_specs,
    ]
    specs = list(base_specs)
    current_value = _cached_best_combo_value(inventory_rows, game, character)
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]] = {}
    state_memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]] = {}
    base_state = EvState.from_rows(inventory_rows, game, character) if use_state_dp else None
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]] = {}
    action_value_cache: dict[tuple[ActionSpec, int], tuple[float, ...]] = {}
    total_units = len(specs) * (2 if horizon > 1 else 1)
    completed_units = 0.0
    dp_states = 0
    dp_steps = 0
    memo_hits = 0
    aggregated_outcome_cache_hits = 0
    aggregated_outcome_cache_misses = 0
    state_transition_cache_hits = 0
    state_transition_cache_misses = 0

    _emit_progress(
        progress_callback,
        "start",
        phase="action_ev",
        completed=0,
        total=total_units,
        label=f"准备计算 {len(specs)} 个基础 action",
        dp_steps=dp_steps,
        aggregated_outcome_cache_hits=aggregated_outcome_cache_hits,
        aggregated_outcome_cache_misses=aggregated_outcome_cache_misses,
        state_transition_cache_hits=state_transition_cache_hits,
        state_transition_cache_misses=state_transition_cache_misses,
    )

    def run_action_value(
        spec: ActionSpec,
        spec_index: int,
        unit_label: str,
        unit_horizon: int,
    ) -> tuple[float, ...]:
        nonlocal completed_units, dp_states, dp_steps, memo_hits
        nonlocal aggregated_outcome_cache_hits, aggregated_outcome_cache_misses
        nonlocal state_transition_cache_hits, state_transition_cache_misses

        action_label = _action_progress_label(spec, game)
        _emit_progress(
            progress_callback,
            "unit_start",
            phase="action_ev",
            completed=completed_units,
            total=total_units,
            label=action_label,
            unit_label=unit_label,
            spec_index=spec_index,
            spec_total=len(specs),
            action_strategy=spec.strategy,
            action_set=spec.set_label,
            dp_states=dp_states,
            dp_steps=dp_steps,
            memo_hits=memo_hits,
            aggregated_outcome_cache_hits=aggregated_outcome_cache_hits,
            aggregated_outcome_cache_misses=aggregated_outcome_cache_misses,
            state_transition_cache_hits=state_transition_cache_hits,
            state_transition_cache_misses=state_transition_cache_misses,
        )

        def unit_progress(event: dict[str, object]) -> None:
            nonlocal dp_states, dp_steps, memo_hits
            nonlocal aggregated_outcome_cache_hits, aggregated_outcome_cache_misses
            nonlocal state_transition_cache_hits, state_transition_cache_misses
            event_name = str(event.get("event", ""))
            depth = int(event.get("depth") or 0)
            if event_name == "state_done":
                dp_states += 1
            if event_name in {
                "outcome_done",
                "state_action_start",
                "state_action_done",
                "memo_hit",
                "outcome_distribution_done",
                "outcome_aggregate_done",
                "candidate_generation_step_done",
                "upgrade_generation_done",
                "state_transition_cache_hit",
                "state_transition_cache_miss",
            }:
                dp_steps += 1
            if event_name == "memo_hit":
                memo_hits += 1
            if event_name == "aggregated_outcome_cache_hit":
                aggregated_outcome_cache_hits += 1
            elif event_name == "aggregated_outcome_cache_miss":
                aggregated_outcome_cache_misses += 1
            if event_name == "state_transition_cache_hit":
                state_transition_cache_hits += 1
            elif event_name == "state_transition_cache_miss":
                state_transition_cache_misses += 1

            completed = completed_units
            if event_name == "outcome_done" and depth == 0:
                outcome_total = float(event.get("total") or 0)
                if outcome_total > 0:
                    completed += float(event.get("completed") or 0) / outcome_total

            _emit_progress(
                progress_callback,
                "unit_progress",
                phase="action_ev",
                completed=completed,
                total=total_units,
                label=action_label,
                unit_label=unit_label,
                spec_index=spec_index,
                spec_total=len(specs),
                action_strategy=spec.strategy,
                action_set=spec.set_label,
                dp_states=dp_states,
                dp_steps=dp_steps,
                memo_hits=memo_hits,
                aggregated_outcome_cache_hits=aggregated_outcome_cache_hits,
                aggregated_outcome_cache_misses=aggregated_outcome_cache_misses,
                state_transition_cache_hits=state_transition_cache_hits,
                state_transition_cache_misses=state_transition_cache_misses,
                inner_event=event_name,
                inner_depth=depth,
                inner_horizon=event.get("horizon"),
                inner_completed=event.get("completed"),
                inner_total=event.get("total"),
                inner_action_strategy=event.get("action_strategy"),
                inner_action_set=event.get("action_set"),
                inner_action_position=event.get("action_position"),
                inner_action_main_stat=event.get("action_main_stat"),
            )

        if use_state_dp and base_state is not None:
            value = expected_state_action_value(
                base_state,
                game,
                character,
                probability_model,
                spec,
                unit_horizon,
                memo=state_memo,
                quality_cache=quality_cache,
                progress_callback=unit_progress,
            )
        else:
            value = _expected_action_value(
                inventory_rows,
                game,
                character,
                probability_model,
                spec,
                unit_horizon,
                memo,
                quality_cache,
                progress_callback=unit_progress,
            )
        completed_units += 1
        _emit_progress(
            progress_callback,
            "unit_done",
            phase="action_ev",
            completed=completed_units,
            total=total_units,
            label=action_label,
            unit_label=unit_label,
            spec_index=spec_index,
            spec_total=len(specs),
            action_strategy=spec.strategy,
            action_set=spec.set_label,
            dp_states=dp_states,
            dp_steps=dp_steps,
            memo_hits=memo_hits,
            aggregated_outcome_cache_hits=aggregated_outcome_cache_hits,
            aggregated_outcome_cache_misses=aggregated_outcome_cache_misses,
            state_transition_cache_hits=state_transition_cache_hits,
            state_transition_cache_misses=state_transition_cache_misses,
        )
        action_value_cache[(spec, unit_horizon)] = value
        return value

    def direct_action_value(
        spec: ActionSpec,
        unit_horizon: int,
    ) -> tuple[float, ...]:
        cached = action_value_cache.get((spec, unit_horizon))
        if cached is not None:
            return cached
        if use_state_dp and base_state is not None:
            value = expected_state_action_value(
                base_state,
                game,
                character,
                probability_model,
                spec,
                unit_horizon,
                memo=state_memo,
                quality_cache=quality_cache,
            )
        else:
            value = _expected_action_value(
                inventory_rows,
                game,
                character,
                probability_model,
                spec,
                unit_horizon,
                memo,
                quality_cache,
            )
        action_value_cache[(spec, unit_horizon)] = value
        return value

    def random_action_value_from_fixed_positions(
        spec: ActionSpec,
        unit_horizon: int,
    ) -> tuple[float, ...]:
        expected = tuple(0.0 for _ in current_value)
        for position, probability in _action_position_items(game, None):
            branch_spec = _fixed_position_branch_spec(spec, position)
            branch_value = direct_action_value(branch_spec, unit_horizon)
            expected = _add_vectors(expected, _scale_vector(branch_value, probability))
        return expected

    def complete_derived_action_value(
        spec: ActionSpec,
        spec_index: int,
        unit_label: str,
        unit_horizon: int,
        value: tuple[float, ...],
    ) -> tuple[float, ...]:
        nonlocal completed_units
        action_label = _action_progress_label(spec, game)
        _emit_progress(
            progress_callback,
            "unit_start",
            phase="action_ev",
            completed=completed_units,
            total=total_units,
            label=f"{action_label}（由固定位置分支汇总）",
            unit_label=unit_label,
            spec_index=spec_index,
            spec_total=len(specs),
            action_strategy=spec.strategy,
            action_set=spec.set_label,
            dp_states=dp_states,
            dp_steps=dp_steps,
            memo_hits=memo_hits,
            aggregated_outcome_cache_hits=aggregated_outcome_cache_hits,
            aggregated_outcome_cache_misses=aggregated_outcome_cache_misses,
            state_transition_cache_hits=state_transition_cache_hits,
            state_transition_cache_misses=state_transition_cache_misses,
            derived_from_fixed_positions=True,
        )
        action_value_cache[(spec, unit_horizon)] = value
        completed_units += 1
        _emit_progress(
            progress_callback,
            "unit_done",
            phase="action_ev",
            completed=completed_units,
            total=total_units,
            label=f"{action_label}（固定位置分支平均）",
            unit_label=unit_label,
            spec_index=spec_index,
            spec_total=len(specs),
            action_strategy=spec.strategy,
            action_set=spec.set_label,
            dp_states=dp_states,
            dp_steps=dp_steps,
            memo_hits=memo_hits,
            aggregated_outcome_cache_hits=aggregated_outcome_cache_hits,
            aggregated_outcome_cache_misses=aggregated_outcome_cache_misses,
            state_transition_cache_hits=state_transition_cache_hits,
            state_transition_cache_misses=state_transition_cache_misses,
            derived_from_fixed_positions=True,
        )
        return value

    def append_row(
        spec: ActionSpec,
        spec_index: int,
        *,
        derive_random_from_fixed_positions: bool = False,
        defer_fixed_random_comparison: bool = False,
    ) -> dict[str, float | str]:
        immediate_action_value = None
        if horizon > 1:
            if derive_random_from_fixed_positions:
                immediate_action_value = complete_derived_action_value(
                    spec,
                    spec_index,
                    "即时收益",
                    1,
                    random_action_value_from_fixed_positions(spec, 1),
                )
            else:
                immediate_action_value = run_action_value(
                    spec,
                    spec_index,
                    "即时收益",
                    1,
                )
        if derive_random_from_fixed_positions:
            action_value = complete_derived_action_value(
                spec,
                spec_index,
                f"horizon={max(horizon, 1)}",
                max(horizon, 1),
                random_action_value_from_fixed_positions(spec, max(horizon, 1)),
            )
        else:
            action_value = run_action_value(
                spec,
                spec_index,
                f"horizon={max(horizon, 1)}",
                max(horizon, 1),
            )
        gain = _positive_gain(action_value, current_value)
        immediate_gain = (
            _positive_gain(immediate_action_value, current_value)
            if immediate_action_value is not None
            else gain
        )
        option_gain = _positive_gain(gain, immediate_gain)
        mother_cost, tuner_cost, core_cost = _action_costs(spec, probability_model)
        efficiency = _vector_efficiency(gain, mother_cost)
        if spec.strategy == "随机位置":
            random_efficiency_by_set[spec.set_label] = efficiency

        quality_gain = gain[-1] if gain else 0.0
        effective_gain = gain[-2] if gain else 0.0
        quality_efficiency = efficiency[-1] if efficiency else 0.0
        effective_efficiency = efficiency[-2] if efficiency else 0.0
        (
            representative_path,
            representative_loadout,
            complement_loadout,
            set_plan_status,
            representative_loadout_rows,
        ) = (
            _representative_action_plan_labels(
                inventory_rows,
                game,
                character,
                probability_model,
                spec,
                horizon,
                memo,
                quality_cache,
            )
        )
        explain_fields = _action_plan_explain_fields(
            inventory_rows,
            game,
            character,
            probability_model,
            spec,
            horizon,
            memo,
            quality_cache,
        )
        set_plan_blocked = set_plan_status.startswith("未满足")
        relative = _relative_action_label(
            spec,
            efficiency,
            set_plan_blocked,
            random_efficiency_by_set,
            base_fixed_efficiency_by_target,
            fixed_main_efficiency_by_target,
            defer_fixed_random_comparison=defer_fixed_random_comparison,
            random_baseline_enabled=bool(random_specs),
        )
        _remember_action_efficiency(
            spec,
            efficiency,
            relative,
            base_fixed_efficiency_by_target,
            fixed_main_efficiency_by_target,
        )
        row: dict[str, float | str] = {
            "动作类型": _action_type_label(spec),
            "策略": spec.strategy,
            "目标套装": spec.set_label,
            "位置": _action_position_label(spec, game),
            "主属性": _action_main_label(spec),
            "固定副属性": _action_substat_label(spec),
            "horizon": horizon,
            "immediate_EV": _quality_vector_label(immediate_gain, character),
            "option_EV": _quality_vector_label(option_gain, character),
            "horizon_EV": _quality_vector_label(gain, character),
            "期望提升": _quality_vector_label(gain, character),
            "方案类型": explain_fields["方案类型"],
            "第一步 action": explain_fields["第一步 action"],
            "第二步策略摘要": explain_fields["第二步策略摘要"],
            "代表路径": representative_path,
            "预期搭配": representative_loadout,
            "代表分支搭配": representative_loadout,
            "互补位": complement_loadout,
            "套装约束": set_plan_status,
            "条件分支": explain_fields["条件分支"],
            "代表路径说明": explain_fields["代表路径说明"],
            "_representative_loadout_rows": representative_loadout_rows,
            "_upgrade_inventory_id": spec.upgrade_inventory_id or "",
            "质量提升": round(quality_gain, 3),
            "有效提升": round(effective_gain, 3),
            "母盘/次": round(mother_cost, 3),
            "校音器/次": round(tuner_cost, 3),
            "共鸣核/次": round(core_cost, 3),
            "高级素材/次": round(tuner_cost + core_cost, 3),
            "质量/母盘": round(quality_efficiency, 4),
            "有效/母盘": round(effective_efficiency, 4),
            "排序向量/母盘": _quality_vector_label(efficiency, character),
            "_sort_vector": efficiency,
            "相对随机": relative,
            "比较口径": _comparison_scope_label(spec, relative, game),
        }
        rows.append(row)
        return row

    base_fixed_rows: list[tuple[ActionSpec, dict[str, float | str]]] = []
    for spec in base_fixed_specs:
        spec_index = specs.index(spec) + 1
        row = append_row(
            spec,
            spec_index,
            defer_fixed_random_comparison=True,
        )
        base_fixed_rows.append((spec, row))

    for spec in random_specs:
        spec_index = specs.index(spec) + 1
        append_row(
            spec,
            spec_index,
            derive_random_from_fixed_positions=True,
        )

    fixed_main_specs: list[ActionSpec] = []
    for spec, row in base_fixed_rows:
        set_plan_status = str(row.get("套装约束") or "")
        efficiency = _row_sort_vector(row)
        relative = _relative_action_label(
            spec,
            efficiency,
            set_plan_status.startswith("未满足"),
            random_efficiency_by_set,
            base_fixed_efficiency_by_target,
            fixed_main_efficiency_by_target,
            random_baseline_enabled=bool(random_specs),
        )
        row["相对随机"] = relative
        row["比较口径"] = _comparison_scope_label(spec, relative, game)
        _remember_action_efficiency(
            spec,
            efficiency,
            relative,
            base_fixed_efficiency_by_target,
            fixed_main_efficiency_by_target,
        )
        if relative in {"优于随机，才建议固定", "固定位置基准"}:
            fixed_main_specs.extend(_fixed_main_refinement_action_specs(game, character, spec))

    for spec in upgrade_specs:
        spec_index = specs.index(spec) + 1
        append_row(spec, spec_index)

    fixed_main_specs = _dedupe_action_specs(fixed_main_specs)
    winning_fixed_main_specs: list[ActionSpec] = []
    if fixed_main_specs:
        specs = [*base_specs, *fixed_main_specs]
        total_units += len(fixed_main_specs) * (2 if horizon > 1 else 1)
        _emit_progress(
            progress_callback,
            "refinement_start",
            phase="action_ev",
            completed=completed_units,
            total=total_units,
            label=f"固定位置优于随机，继续计算 {len(fixed_main_specs)} 个锁主属性 action",
            dp_states=dp_states,
            dp_steps=dp_steps,
            memo_hits=memo_hits,
            aggregated_outcome_cache_hits=aggregated_outcome_cache_hits,
            aggregated_outcome_cache_misses=aggregated_outcome_cache_misses,
            state_transition_cache_hits=state_transition_cache_hits,
            state_transition_cache_misses=state_transition_cache_misses,
        )
        for spec_index, spec in enumerate(fixed_main_specs, start=len(base_specs) + 1):
            row = append_row(spec, spec_index)
            if (
                spec.strategy == "固定位置 + 固定主属性"
                and row["相对随机"]
                in {
                    "固定位置已优于随机；优于固定位置，才建议锁主属性",
                    "优于固定位置，才建议锁主属性",
                }
            ):
                winning_fixed_main_specs.append(spec)

    fixed_substat_specs: list[ActionSpec] = []
    for spec in winning_fixed_main_specs:
        fixed_substat_specs.extend(_fixed_substat_refinement_action_specs(game, character, spec))
    fixed_substat_specs = _dedupe_action_specs(fixed_substat_specs)
    if fixed_substat_specs:
        specs = [*base_specs, *fixed_main_specs, *fixed_substat_specs]
        total_units += len(fixed_substat_specs) * (2 if horizon > 1 else 1)
        _emit_progress(
            progress_callback,
            "refinement_start",
            phase="action_ev",
            completed=completed_units,
            total=total_units,
            label=f"锁主属性优于固定位置，继续计算 {len(fixed_substat_specs)} 个锁副属性 action",
            dp_states=dp_states,
            dp_steps=dp_steps,
            memo_hits=memo_hits,
            aggregated_outcome_cache_hits=aggregated_outcome_cache_hits,
            aggregated_outcome_cache_misses=aggregated_outcome_cache_misses,
            state_transition_cache_hits=state_transition_cache_hits,
            state_transition_cache_misses=state_transition_cache_misses,
        )
        for spec_index, spec in enumerate(
            fixed_substat_specs,
            start=len(base_specs) + len(fixed_main_specs) + 1,
        ):
            append_row(spec, spec_index)

    _lru_set(_ACTION_EV_ROWS_CACHE, cache_key, [dict(row) for row in rows], ACTION_EV_ROWS_CACHE_MAX_SIZE)
    _emit_progress(
        progress_callback,
        "complete",
        phase="action_ev",
        completed=total_units,
        total=total_units,
        label="Action EV 计算完成",
        dp_states=dp_states,
        dp_steps=dp_steps,
        memo_hits=memo_hits,
        aggregated_outcome_cache_hits=aggregated_outcome_cache_hits,
        aggregated_outcome_cache_misses=aggregated_outcome_cache_misses,
        state_transition_cache_hits=state_transition_cache_hits,
        state_transition_cache_misses=state_transition_cache_misses,
    )
    return rows


def _row_sort_vector(row: dict[str, float | str]) -> tuple[float, ...]:
    raw = row.get("_sort_vector")
    if isinstance(raw, tuple):
        return _clean_vector(tuple(float(value) for value in raw))
    if isinstance(raw, list):
        return _clean_vector(tuple(float(value) for value in raw))
    return _clean_vector((
        float(row.get("质量/母盘") or 0.0),
        float(row.get("有效/母盘") or 0.0),
    ))


def _row_float(row: dict[str, float | str], key: str) -> float:
    try:
        return float(row.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _row_has_positive_gain(row: dict[str, float | str]) -> bool:
    if _row_float(row, "有效提升") > _VECTOR_EPSILON:
        return True
    if _row_float(row, "质量提升") > _VECTOR_EPSILON:
        return True
    return any(value > _VECTOR_EPSILON for value in _row_sort_vector(row))


def _row_has_effective_gain(row: dict[str, float | str]) -> bool:
    if "有效提升" in row:
        return _row_float(row, "有效提升") > _VECTOR_EPSILON
    return _row_float(row, "有效/母盘") > _VECTOR_EPSILON


def _best_upgrade_opportunity_row(
    rows: list[dict[str, float | str]],
    *,
    effective_only: bool = False,
) -> dict[str, float | str] | None:
    candidates = [
        row
        for row in rows
        if row.get("策略") == "强化库存胚子"
        and (_row_has_effective_gain(row) if effective_only else _row_has_positive_gain(row))
        and not str(row.get("套装约束") or "").startswith("未满足")
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (
            _row_float(row, "有效提升"),
            _row_float(row, "质量提升"),
            _row_sort_vector(row),
        ),
    )


def _is_recommendable_action_row(row: dict[str, float | str]) -> bool:
    strategy = str(row.get("策略") or "")
    relative = str(row.get("相对随机") or "")
    set_plan_status = str(row.get("套装约束") or "")
    if set_plan_status.startswith("未满足"):
        return False
    if strategy == "随机位置":
        return True
    if strategy == "固定位置":
        return relative in {"优于随机，才建议固定", "固定位置基准"}
    if strategy == "固定位置 + 固定主属性":
        return relative in {
            "固定位置已优于随机；优于固定位置，才建议锁主属性",
            "优于固定位置，才建议锁主属性",
        }
    if strategy == "固定位置 + 固定主属性 + 固定副属性":
        return relative in {
            "锁主属性已优于固定位置；优于锁主属性，才建议锁副属性",
            "优于锁主属性，才建议锁副属性",
        }
    return False


def resource_marginal_ev_rows(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    analysis: CurrentGearAnalysis,
    inventory_pieces: Sequence[GearPiece] | None = None,
    horizon: int = 1,
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, float | str]]:
    inventory_rows = (
        inventory_rows_from_pieces(
            inventory_pieces,
            game,
            character,
            current_count=len(analysis.scores),
        )
        if inventory_pieces is not None
        else _current_inventory_rows(analysis, character)
    )
    cache_key = "resource:" + _action_ev_cache_key(
        game,
        character,
        probability_model,
        analysis,
        inventory_rows=inventory_rows,
        horizon=horizon,
    )
    cached = _lru_get(_RESOURCE_MARGINAL_EV_ROWS_CACHE, cache_key)
    if cached is not None:
        _emit_progress(
            progress_callback,
            "cache_hit",
            phase="resource_ev",
            completed=1,
            total=1,
            label="已使用上次特殊资源 EV 缓存",
        )
        return [dict(row) for row in cached]

    rows: list[dict[str, float | str]] = []
    fixed_position_cost = probability_model.resource_cost("mother_disk_fixed_position_attempt", 6.0)
    tuner_cost = probability_model.resource_cost("tuner_per_fixed_main_attempt", 1.0)
    current_value = _cached_best_combo_value(inventory_rows, game, character)
    memo: dict[tuple[int, tuple[tuple, ...]], tuple[float, ...]] = {}
    quality_cache: dict[tuple[str, tuple[str, ...]], list[tuple[float, tuple[float, ...], float]]] = {}
    total_units = 0
    for _set_label, set_options_list in _set_action_groups(character):
        for rule in game.positions:
            if len(game.main_stats_for(rule.id)) <= 1:
                continue
            total_units += 1
            for main_stat in _main_stat_action_options(game, character, rule.id):
                total_units += 1
                total_units += len(_fixed_substat_action_options(game, character, main_stat))

    completed_units = 0.0
    dp_states = 0
    memo_hits = 0

    _emit_progress(
        progress_callback,
        "start",
        phase="resource_ev",
        completed=0,
        total=total_units,
        label=f"准备计算 {total_units} 个特殊资源对照 action",
    )

    def gain_for_spec(spec: ActionSpec) -> tuple[float, ...]:
        nonlocal completed_units, dp_states, memo_hits
        if not current_value:
            return tuple()

        action_label = _action_progress_label(spec, game)
        _emit_progress(
            progress_callback,
            "unit_start",
            phase="resource_ev",
            completed=completed_units,
            total=total_units,
            label=action_label,
            unit_label=f"horizon={max(horizon, 1)}",
            dp_states=dp_states,
            memo_hits=memo_hits,
        )

        def unit_progress(event: dict[str, object]) -> None:
            nonlocal dp_states, memo_hits
            event_name = str(event.get("event", ""))
            depth = int(event.get("depth") or 0)
            if event_name == "state_done":
                dp_states += 1
            elif event_name == "memo_hit":
                memo_hits += 1

            completed = completed_units
            if event_name == "outcome_done" and depth == 0:
                outcome_total = float(event.get("total") or 0)
                if outcome_total > 0:
                    completed += float(event.get("completed") or 0) / outcome_total
            _emit_progress(
                progress_callback,
                "unit_progress",
                phase="resource_ev",
                completed=completed,
                total=total_units,
                label=action_label,
                unit_label=f"horizon={max(horizon, 1)}",
                dp_states=dp_states,
                memo_hits=memo_hits,
            )

        value = _expected_action_value(
            inventory_rows,
            game,
            character,
            probability_model,
            spec,
            max(horizon, 1),
            memo,
            quality_cache,
            progress_callback=unit_progress,
        )
        completed_units += 1
        _emit_progress(
            progress_callback,
            "unit_done",
            phase="resource_ev",
            completed=completed_units,
            total=total_units,
            label=action_label,
            unit_label=f"horizon={max(horizon, 1)}",
            dp_states=dp_states,
            memo_hits=memo_hits,
        )
        return _positive_gain(value, current_value)

    for set_label, set_options_list in _set_action_groups(character):
        set_options = tuple(set_options_list)
        for rule in game.positions:
            if len(game.main_stats_for(rule.id)) <= 1:
                continue
            base_spec = ActionSpec("固定位置", set_label, set_options, rule.id)
            base_gain = gain_for_spec(base_spec)
            for main_stat in _main_stat_action_options(game, character, rule.id):
                fixed_main_spec = ActionSpec(
                    "固定位置 + 固定主属性",
                    set_label,
                    set_options,
                    rule.id,
                    fixed_main_stat=main_stat,
                )
                fixed_main_gain = gain_for_spec(fixed_main_spec)
                main_marginal = _subtract_vectors(fixed_main_gain, base_gain)
                main_saved_effective = _saved_mother_disks_for_equal_gain(
                    base_gain[-2] if base_gain else 0.0,
                    fixed_main_gain[-2] if fixed_main_gain else 0.0,
                    fixed_position_cost,
                )
                main_saved_quality = _saved_mother_disks_for_equal_gain(
                    base_gain[-1] if base_gain else 0.0,
                    fixed_main_gain[-1] if fixed_main_gain else 0.0,
                    fixed_position_cost,
                )
                rows.append(
                    {
                        "资源": "校音器",
                        "目标套装": set_label,
                        "位置": game.position_name(rule.id),
                        "主属性": main_stat,
                        "固定副属性": "不固定",
                        "基准action": "固定位置，不固定主属性",
                        "资源action": "固定位置 + 固定主属性",
                        "边际提升": _quality_vector_label(main_marginal, character),
                        "边际有效提升": round(main_marginal[-2], 3) if main_marginal else 0.0,
                        "边际质量提升": round(main_marginal[-1], 3) if main_marginal else 0.0,
                        "母盘/次": round(fixed_position_cost, 3),
                        "同等有效省母盘": round(main_saved_effective, 3)
                        if isfinite(main_saved_effective)
                        else "∞",
                        "同等质量省母盘": round(main_saved_quality, 3)
                        if isfinite(main_saved_quality)
                        else "∞",
                        "期望校音器/次": round(tuner_cost, 3),
                        "期望共鸣核/次": 0.0,
                        "高级素材增量/次": round(tuner_cost, 3),
                        **_material_opportunity_row_fields(
                            main_saved_effective,
                            main_saved_quality,
                            tuner_cost,
                            probability_model,
                        ),
                    }
                )
                for required_substats in _fixed_substat_action_options(game, character, main_stat):
                    fixed_substat_spec = ActionSpec(
                        "固定位置 + 固定主属性 + 固定副属性",
                        set_label,
                        set_options,
                        rule.id,
                        fixed_main_stat=main_stat,
                        required_substats=required_substats,
                    )
                    fixed_substat_gain = gain_for_spec(fixed_substat_spec)
                    substat_marginal = _subtract_vectors(fixed_substat_gain, fixed_main_gain)
                    substat_saved_effective = _saved_mother_disks_for_equal_gain(
                        fixed_main_gain[-2] if fixed_main_gain else 0.0,
                        fixed_substat_gain[-2] if fixed_substat_gain else 0.0,
                        fixed_position_cost,
                    )
                    substat_saved_quality = _saved_mother_disks_for_equal_gain(
                        fixed_main_gain[-1] if fixed_main_gain else 0.0,
                        fixed_substat_gain[-1] if fixed_substat_gain else 0.0,
                        fixed_position_cost,
                    )
                    core_cost = _fixed_substat_extra_resource_cost(
                        probability_model,
                        len(required_substats),
                    )
                    rows.append(
                        {
                            "资源": "共鸣核",
                            "目标套装": set_label,
                            "位置": game.position_name(rule.id),
                            "主属性": main_stat,
                            "固定副属性": " + ".join(required_substats),
                            "基准action": "固定位置 + 固定主属性",
                            "资源action": "固定位置 + 固定主属性 + 固定副属性",
                            "边际提升": _quality_vector_label(substat_marginal, character),
                            "边际有效提升": round(substat_marginal[-2], 3)
                            if substat_marginal
                            else 0.0,
                            "边际质量提升": round(substat_marginal[-1], 3)
                            if substat_marginal
                            else 0.0,
                            "母盘/次": round(fixed_position_cost, 3),
                            "同等有效省母盘": round(substat_saved_effective, 3)
                            if isfinite(substat_saved_effective)
                            else "∞",
                            "同等质量省母盘": round(substat_saved_quality, 3)
                            if isfinite(substat_saved_quality)
                            else "∞",
                            "期望校音器/次": round(tuner_cost, 3),
                            "期望共鸣核/次": round(core_cost, 3),
                            "高级素材增量/次": round(core_cost, 3),
                            **_material_opportunity_row_fields(
                                substat_saved_effective,
                                substat_saved_quality,
                                core_cost,
                                probability_model,
                            ),
                        }
                    )
    _lru_set(
        _RESOURCE_MARGINAL_EV_ROWS_CACHE,
        cache_key,
        [dict(row) for row in rows],
        RESOURCE_MARGINAL_EV_ROWS_CACHE_MAX_SIZE,
    )
    _emit_progress(
        progress_callback,
        "complete",
        phase="resource_ev",
        completed=total_units,
        total=total_units,
        label="特殊资源 EV 计算完成",
        dp_states=dp_states,
        memo_hits=memo_hits,
    )
    return rows


def recommended_action_ev_row(
    rows: list[dict[str, float | str]],
) -> dict[str, float | str] | None:
    if not rows:
        return None
    candidates = [row for row in rows if _is_recommendable_action_row(row)]
    if not candidates:
        candidates = [
            row
            for row in rows
            if row.get("策略") == "随机位置"
            and not str(row.get("套装约束") or "").startswith("未满足")
        ]
    if not candidates:
        return None
    return max(
        candidates,
        key=_row_sort_vector,
    )


def _brief_recommended_action_row(
    rows: list[dict[str, float | str]],
) -> dict[str, float | str] | None:
    candidates = [
        row
        for row in rows
        if _is_recommendable_action_row(row) and _row_has_effective_gain(row)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (
            _row_float(row, "有效/母盘"),
            _row_float(row, "有效提升"),
            _row_sort_vector(row),
        ),
    )


def action_ev_brief(rows: list[dict[str, float | str]]) -> str:
    audit_best = recommended_action_ev_row(rows)
    best = _brief_recommended_action_row(rows)
    if best is None:
        upgrade = _best_upgrade_opportunity_row(rows, effective_only=True)
        if upgrade is not None:
            if audit_best is not None:
                return (
                    "当前 horizon 没有有效提升为正的可推荐调律 action；"
                    "存在库存升级机会："
                    f"{upgrade.get('目标套装', '-')} {upgrade.get('位置', '-')}，"
                    f"有效提升 {upgrade.get('有效提升', '-')}；"
                    "排序最高调律 action 仅有非有效收益，作为审计信息保留："
                    f"{audit_best['策略']} {audit_best['目标套装']} {audit_best['位置']}。"
                )
            return (
                "当前 horizon 没有可推荐调律 action；"
                "存在库存升级机会："
                f"{upgrade.get('目标套装', '-')} {upgrade.get('位置', '-')}，"
                f"有效提升 {upgrade.get('有效提升', '-')}；"
                "库存升级机会不参与主调律推荐排序。"
            )
        if rows and all(str(row.get("套装约束") or "").startswith("未满足") for row in rows):
            return "当前 horizon 没有满足套装硬约束的 action；请提高 horizon 或先补齐套装缺口。"
        if audit_best is not None:
            comparison = str(audit_best.get("比较口径") or audit_best.get("相对随机") or "-")
            return (
                "当前 horizon 的排序最高调律 action 仅有非有效收益，"
                "桌面主口径暂无有效提升 action："
                f"{audit_best['策略']} {audit_best['目标套装']} {audit_best['位置']}，"
                f"有效/母盘 {audit_best.get('有效/母盘', '-')}；"
                f"{comparison}；{audit_best.get('套装约束', '-')}。"
                f"审计排序向量/母盘 {audit_best.get('排序向量/母盘', '-')}。"
            )
        return "暂无 action EV 结果。"
    loadout = str(best.get("代表分支搭配") or best.get("预期搭配") or "-")
    comparison = str(best.get("比较口径") or best.get("相对随机") or "-")
    audit_note = ""
    if audit_best is not None and audit_best is not best:
        audit_note = (
            "引擎审计排序最高为："
            f"{audit_best['策略']} {audit_best['目标套装']} {audit_best['位置']}。"
        )
    return (
        f"{best['策略']}：{best['目标套装']} {best['位置']}，"
        f"有效提升 {best.get('有效提升', '-')}，"
        f"有效/母盘 {best['有效/母盘']}；"
        f"{comparison}；{best.get('套装约束', '-')}。代表分支搭配：{loadout}。"
        f"审计排序向量/母盘 {best.get('排序向量/母盘', '-')}。"
        f"{audit_note}"
    )
