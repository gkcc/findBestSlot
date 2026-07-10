from __future__ import annotations

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

