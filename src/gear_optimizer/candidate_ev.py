from __future__ import annotations

from collections import defaultdict
from math import isclose

from gear_optimizer.models import (
    CandidateEvaluation,
    CandidatePiece,
    CharacterPreset,
    DistributionPoint,
    GameRules,
    WeightedDistributionPoint,
)
from gear_optimizer.probability import normalise_weights, probability_next_stat_in_set
from gear_optimizer.scoring import effective_lines, effective_rolls, weighted_effective_score


def _recommendation_thresholds(character: CharacterPreset) -> dict[str, float]:
    good_threshold = character.rating_thresholds.get("good", 4.0)
    weighted_continue = min(good_threshold, character.weighted_target_score)
    return {
        "effective_continue": character.target_effective_rolls * (2.0 / 3.0),
        "effective_promising": character.target_effective_rolls * 0.5,
        "effective_transition": character.target_effective_rolls * (1.0 / 3.0),
        "weighted_continue": weighted_continue,
        "weighted_pause": weighted_continue * 0.8,
        "weighted_gain_floor": max(weighted_continue * 0.2, 0.4),
    }


def _recommend(
    expected: float,
    current: float,
    weighted_expected: float,
    weighted_current: float,
    character: CharacterPreset,
) -> tuple[str, str]:
    thresholds = _recommendation_thresholds(character)
    gain = expected - current
    weighted_gain = weighted_expected - weighted_current
    if expected >= thresholds["effective_continue"]:
        if weighted_expected >= thresholds["weighted_continue"]:
            return (
                "继续",
                "最终有效词条期望达到角色观察线，且质量期望达到当前评分目标，值得继续强化观察。",
            )
        if weighted_expected >= thresholds["weighted_pause"]:
            return (
                "暂停",
                "原始有效词条期望不错，但质量收益没有拉满，建议看资源压力再继续。",
            )
        return (
            "仅过渡",
            "原始有效词条期望看起来不错，但主要落在低优先级词条上，更适合作为过渡盘。",
        )
    if expected >= thresholds["effective_promising"] and gain >= 1.0:
        if weighted_gain < thresholds["weighted_gain_floor"]:
            return (
                "仅过渡",
                "有一定有效词条上升空间，但质量收益偏低，不建议重投入资源。",
            )
        return "暂停", "有一定上升空间，但离稳定好盘还有距离，建议看资源压力再决定。"
    if expected >= thresholds["effective_transition"]:
        return "仅过渡", "最终期望偏低，更适合作为临时过渡盘，不建议重投入资源。"
    return "放弃", "有效词条基础和后续命中期望都偏低，继续强化的机会成本较高。"


def _rounded(value: float) -> float:
    if isclose(value, round(value), abs_tol=1e-12):
        return float(round(value))
    return round(value, 6)


def _initial_line_weights(
    piece: CandidatePiece,
    character: CharacterPreset,
    line_count: int,
) -> tuple[float, ...]:
    weights = [character.weight_for(line.stat) for line in piece.substats]
    weights.extend([0.0] * max(line_count - len(weights), 0))
    return tuple(weights[:line_count])


def _draw_probabilities(
    available_stats: list[str],
    weights: dict[str, float],
) -> list[tuple[str | None, float]]:
    if not available_stats:
        return [(None, 1.0)]
    normalised = normalise_weights(available_stats, weights)
    return list(normalised.items())


def evaluate_candidate(
    piece: CandidatePiece,
    game: GameRules,
    character: CharacterPreset,
) -> CandidateEvaluation:
    current_effective = effective_rolls(piece, character)
    current_lines = effective_lines(piece, character)
    current_weighted = weighted_effective_score(piece, character)
    existing_stats = [line.stat for line in piece.substats]
    warnings: list[str] = []
    if len(existing_stats) < piece.initial_substat_count:
        warnings.append("当前副属性数量少于初始词条数；缺失词条会按未知无效词条保守处理。")

    line_count = max(len(existing_stats), piece.initial_substat_count)
    if (
        piece.initial_substat_count == 3
        and piece.level >= game.enhancement.initial_add_level
        and line_count < 4
    ):
        warnings.append("+3 后应已有第 4 个副属性；缺失词条会按未知无效词条保守处理。")
        line_count = 4

    events = [
        level
        for level in game.enhancement.event_levels
        if level > piece.level and level <= game.enhancement.max_level
    ]
    needs_add = (
        piece.initial_substat_count == 3
        and line_count < 4
        and piece.level < game.enhancement.initial_add_level
    )
    remaining_roll_events = len(events) - (1 if events and needs_add else 0)
    remaining_roll_events = max(remaining_roll_events, 0)

    event_descriptions: list[str] = []
    event_rows: list[dict[str, float | int | str]] = []
    per_event_hit_probabilities: list[float] = []
    per_event_expected_weighted_gains: list[float] = []

    available_for_add = game.available_substats(piece.main_stat, existing_stats)
    desired_for_add = {
        stat for stat in available_for_add if character.is_effective(stat)
    }
    add_effective_probability = probability_next_stat_in_set(
        available_for_add,
        desired_for_add,
        game.sub_stat_probabilities,
    )
    add_draw_probabilities = _draw_probabilities(
        available_for_add,
        game.sub_stat_probabilities,
    )
    add_expected_weighted_gain = sum(
        probability * (character.weight_for(stat) if stat else 0.0)
        for stat, probability in add_draw_probabilities
    )

    states: dict[tuple[float, float, tuple[float, ...]], float] = {
        (
            current_effective,
            current_weighted,
            _initial_line_weights(piece, character, line_count),
        ): 1.0
    }

    for index, level in enumerate(events):
        next_states: defaultdict[tuple[float, float, tuple[float, ...]], float] = defaultdict(float)
        is_add_event = needs_add and index == 0
        if is_add_event:
            weighted_gain_sum = add_expected_weighted_gain
            description = (
                f"+{level} 先补第 4 个副属性；补出有效词条概率约 {add_effective_probability:.1%}，"
                f"质量期望增量约 {add_expected_weighted_gain:.2f}。"
            )
            event_descriptions.append(description)
            event_rows.append(
                {
                    "level": level,
                    "event": "补第 4 副属性",
                    "hit_probability": _rounded(add_effective_probability),
                    "expected_weighted_gain": _rounded(add_expected_weighted_gain),
                    "description": description,
                }
            )
            per_event_hit_probabilities.append(add_effective_probability)
            for (score, weighted_score, line_weights), state_probability in states.items():
                for stat, draw_probability in add_draw_probabilities:
                    stat_weight = character.weight_for(stat) if stat else 0.0
                    next_weights = tuple(list(line_weights) + [stat_weight])[:4]
                    next_score = score + (1 if stat_weight > 0 else 0)
                    next_weighted_score = weighted_score + stat_weight
                    next_states[
                        (
                            _rounded(next_score),
                            _rounded(next_weighted_score),
                            next_weights,
                        )
                    ] += state_probability * draw_probability
        else:
            weighted_probability_sum = 0.0
            weighted_gain_sum = 0.0
            for (score, weighted_score, line_weights), probability in states.items():
                count = len(line_weights)
                if count == 0:
                    next_states[(score, weighted_score, line_weights)] += probability
                    continue
                effective_count = sum(1 for weight in line_weights if weight > 0)
                hit_probability = effective_count / count
                weighted_probability_sum += probability * hit_probability
                weighted_gain_sum += probability * (sum(line_weights) / count)
                for line_weight in line_weights:
                    next_score = score + (1 if line_weight > 0 else 0)
                    next_weighted_score = weighted_score + line_weight
                    next_states[
                        (
                            _rounded(next_score),
                            _rounded(next_weighted_score),
                            line_weights,
                        )
                    ] += probability / count
            event_probability = weighted_probability_sum
            description = (
                f"+{level} 随机命中已有副属性；命中有效词条概率约 {event_probability:.1%}，"
                f"质量期望增量约 {weighted_gain_sum:.2f}。"
            )
            event_descriptions.append(description)
            event_rows.append(
                {
                    "level": level,
                    "event": "随机命中已有副属性",
                    "hit_probability": _rounded(event_probability),
                    "expected_weighted_gain": _rounded(weighted_gain_sum),
                    "description": description,
                }
            )
            per_event_hit_probabilities.append(event_probability)
        per_event_expected_weighted_gains.append(_rounded(weighted_gain_sum))
        states = dict(next_states)

    distribution_map: defaultdict[float, float] = defaultdict(float)
    weighted_distribution_map: defaultdict[float, float] = defaultdict(float)
    for (score, weighted_score, _line_weights), probability in states.items():
        distribution_map[score] += probability
        weighted_distribution_map[weighted_score] += probability

    distribution = [
        DistributionPoint(effective_rolls=score, probability=probability)
        for score, probability in sorted(distribution_map.items())
        if probability > 1e-12
    ]
    weighted_distribution = [
        WeightedDistributionPoint(weighted_score=score, probability=probability)
        for score, probability in sorted(weighted_distribution_map.items())
        if probability > 1e-12
    ]
    expected = sum(point.effective_rolls * point.probability for point in distribution)
    expected = _rounded(expected)
    expected_weighted = sum(
        point.weighted_score * point.probability for point in weighted_distribution
    )
    expected_weighted = _rounded(expected_weighted)

    recommendation, reason = _recommend(
        expected,
        current_effective,
        expected_weighted,
        current_weighted,
        character,
    )
    return CandidateEvaluation(
        current_effective_rolls=current_effective,
        current_effective_lines=current_lines,
        current_weighted_score=_rounded(current_weighted),
        remaining_upgrade_events=len(events),
        remaining_roll_events=remaining_roll_events,
        per_event_hit_probabilities=per_event_hit_probabilities,
        per_event_expected_weighted_gains=per_event_expected_weighted_gains,
        event_rows=event_rows,
        event_descriptions=event_descriptions,
        final_expected_effective_rolls=expected,
        final_expected_weighted_score=expected_weighted,
        distribution=distribution,
        weighted_distribution=weighted_distribution,
        recommendation=recommendation,  # type: ignore[arg-type]
        reason=reason,
        warnings=warnings,
    )
