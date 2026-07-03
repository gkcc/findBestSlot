from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from gear_optimizer.models import CharacterPreset, GameRules, ProbabilityModel, position_key
from gear_optimizer.probability import normalise_weights


@dataclass(frozen=True)
class PieceQualityOutcome:
    quality_score: float
    quality_vector: tuple[float, ...]
    probability: float


@dataclass(frozen=True)
class PositionQualityOutcome:
    position: str | int
    main_stat: str
    quality_score: float
    quality_vector: tuple[float, ...]
    probability: float


_FRESH_QUALITY_DISTRIBUTION_CACHE: dict[tuple, tuple[PieceQualityOutcome, ...]] = {}
_POSITION_QUALITY_DISTRIBUTION_CACHE: dict[tuple, tuple[PositionQualityOutcome, ...]] = {}
_PROBABILITY_EPSILON = 1e-12


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


def quality_from_roll_state(
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


def _game_distribution_key(game: GameRules) -> tuple:
    return (
        game.id,
        tuple((position_key(rule.id), tuple(rule.main_stats)) for rule in game.positions),
        tuple(game.sub_stats),
        tuple(sorted(game.sub_stat_probabilities.items())),
        game.enhancement.max_level,
        game.enhancement.step,
        game.enhancement.initial_add_level,
        tuple(game.enhancement.event_levels),
    )


def _character_distribution_key(character: CharacterPreset) -> tuple:
    priority = character.substat_priority
    return (
        character.id,
        tuple(character.priority_stats()),
        tuple(priority.core if priority else ()),
        tuple(priority.usable if priority else ()),
        tuple(sorted(character.effective_substats.items())),
        tuple(sorted((position_key(key), tuple(values)) for key, values in character.preferred_main_stats.items())),
    )


def _probability_distribution_key(probability_model: ProbabilityModel) -> tuple:
    return (
        probability_model.id,
        tuple(sorted(probability_model.initial_substat_count_probabilities.items())),
    )


def _fresh_quality_distribution_key(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    main_stat: str,
    required_substats: tuple[str, ...],
) -> tuple:
    return (
        _game_distribution_key(game),
        _character_distribution_key(character),
        _probability_distribution_key(probability_model),
        main_stat,
        _canonical_stats(game, tuple(dict.fromkeys(required_substats))),
    )


def fresh_piece_quality_distribution(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    main_stat: str,
    required_substats: tuple[str, ...] = (),
) -> tuple[PieceQualityOutcome, ...]:
    key = _fresh_quality_distribution_key(
        game,
        character,
        probability_model,
        main_stat,
        required_substats,
    )
    cached = _FRESH_QUALITY_DISTRIBUTION_CACHE.get(key)
    if cached is not None:
        return cached

    distribution: defaultdict[tuple[float, tuple[float, ...]], float] = defaultdict(float)
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
            quality_score, quality_vector = quality_from_roll_state(state, character)
            distribution[(quality_score, quality_vector)] += count_probability * probability

    outcomes = tuple(
        PieceQualityOutcome(quality_score, quality_vector, probability)
        for (quality_score, quality_vector), probability in sorted(
            distribution.items(),
            key=lambda item: (item[0][0], item[0][1]),
        )
        if probability > _PROBABILITY_EPSILON
    )
    _FRESH_QUALITY_DISTRIBUTION_CACHE[key] = outcomes
    return outcomes


def _position_distribution_key(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    position: str | int,
    fixed_main_stat: str | None,
    required_substats: tuple[str, ...],
) -> tuple:
    return (
        _game_distribution_key(game),
        _character_distribution_key(character),
        _probability_distribution_key(probability_model),
        position_key(position),
        fixed_main_stat,
        _canonical_stats(game, tuple(dict.fromkeys(required_substats))),
    )


def position_quality_distribution(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    position: str | int,
    fixed_main_stat: str | None = None,
    required_substats: tuple[str, ...] = (),
) -> tuple[PositionQualityOutcome, ...]:
    key = _position_distribution_key(
        game,
        character,
        probability_model,
        position,
        fixed_main_stat,
        required_substats,
    )
    cached = _POSITION_QUALITY_DISTRIBUTION_CACHE.get(key)
    if cached is not None:
        return cached

    valid_main_stats = game.main_stats_for(position)
    main_stats = [fixed_main_stat] if fixed_main_stat else valid_main_stats
    outcomes: list[PositionQualityOutcome] = []
    for main_stat in main_stats:
        if main_stat not in valid_main_stats:
            continue
        main_probability = 1.0 if fixed_main_stat else game.main_stat_probability(position, main_stat)
        if main_probability <= 0:
            continue
        for outcome in fresh_piece_quality_distribution(
            game,
            character,
            probability_model,
            main_stat,
            required_substats,
        ):
            probability = main_probability * outcome.probability
            if probability > _PROBABILITY_EPSILON:
                outcomes.append(
                    PositionQualityOutcome(
                        position=position,
                        main_stat=main_stat,
                        quality_score=outcome.quality_score,
                        quality_vector=outcome.quality_vector,
                        probability=probability,
                    )
                )

    result = tuple(outcomes)
    _POSITION_QUALITY_DISTRIBUTION_CACHE[key] = result
    return result


def action_position_quality_distribution(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel,
    target_position: str | int | None,
    fixed_main_stat: str | None = None,
    required_substats: tuple[str, ...] = (),
) -> tuple[PositionQualityOutcome, ...]:
    if target_position is not None:
        return position_quality_distribution(
            game,
            character,
            probability_model,
            target_position,
            fixed_main_stat=fixed_main_stat,
            required_substats=required_substats,
        )
    if fixed_main_stat is not None:
        # Fixed main stat actions always target a concrete position in current rules.
        return tuple()

    outcomes: list[PositionQualityOutcome] = []
    position_probability = 1.0 / len(game.positions) if game.positions else 0.0
    for rule in game.positions:
        for outcome in position_quality_distribution(
            game,
            character,
            probability_model,
            rule.id,
            required_substats=required_substats,
        ):
            probability = position_probability * outcome.probability
            if probability > _PROBABILITY_EPSILON:
                outcomes.append(
                    PositionQualityOutcome(
                        position=outcome.position,
                        main_stat=outcome.main_stat,
                        quality_score=outcome.quality_score,
                        quality_vector=outcome.quality_vector,
                        probability=probability,
                    )
                )
    return tuple(outcomes)


def clear_piece_distribution_caches() -> None:
    _FRESH_QUALITY_DISTRIBUTION_CACHE.clear()
    _POSITION_QUALITY_DISTRIBUTION_CACHE.clear()


def piece_distribution_cache_sizes() -> dict[str, int]:
    return {
        "fresh_quality": len(_FRESH_QUALITY_DISTRIBUTION_CACHE),
        "position_quality": len(_POSITION_QUALITY_DISTRIBUTION_CACHE),
    }
