from __future__ import annotations

from functools import lru_cache
from math import isfinite


def normalise_weights(stats: list[str], weights: dict[str, float]) -> dict[str, float]:
    positive = {stat: max(weights.get(stat, 1.0), 0.0) for stat in stats}
    total = sum(positive.values())
    if total <= 0:
        return {stat: 1.0 / len(stats) for stat in stats} if stats else {}
    return {stat: weight / total for stat, weight in positive.items()}


def probability_next_stat_in_set(
    available_stats: list[str],
    desired_stats: set[str],
    weights: dict[str, float],
) -> float:
    if not available_stats:
        return 0.0
    normalised = normalise_weights(available_stats, weights)
    return sum(probability for stat, probability in normalised.items() if stat in desired_stats)


def probability_required_substats(
    required_stats: list[str],
    available_stats: list[str],
    weights: dict[str, float],
    draw_count: int = 4,
) -> float:
    """Probability that all required stats appear in a weighted draw without replacement."""
    required = tuple(dict.fromkeys(required_stats))
    if not required:
        return 1.0
    if any(stat not in available_stats for stat in required):
        return 0.0
    if draw_count < len(required):
        return 0.0

    stats = tuple(available_stats)
    stat_to_index = {stat: index for index, stat in enumerate(stats)}
    weights_tuple = tuple(max(weights.get(stat, 1.0), 0.0) for stat in stats)
    required_indices = frozenset(stat_to_index[stat] for stat in required)

    @lru_cache(maxsize=None)
    def recurse(remaining_indices: tuple[int, ...], remaining_required: frozenset[int], draws: int) -> float:
        if not remaining_required:
            return 1.0
        if draws <= 0 or draws < len(remaining_required):
            return 0.0
        total_weight = sum(weights_tuple[index] for index in remaining_indices)
        if total_weight <= 0 or not isfinite(total_weight):
            return 0.0

        probability = 0.0
        for index in remaining_indices:
            next_remaining = tuple(item for item in remaining_indices if item != index)
            next_required = (
                frozenset(item for item in remaining_required if item != index)
                if index in remaining_required
                else remaining_required
            )
            probability += (
                weights_tuple[index]
                / total_weight
                * recurse(next_remaining, next_required, draws - 1)
            )
        return probability

    return recurse(tuple(range(len(stats))), required_indices, min(draw_count, len(stats)))

