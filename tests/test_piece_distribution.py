from collections import defaultdict

import pytest

import gear_optimizer.position_ev as position_ev
from gear_optimizer.game_rules import load_characters, load_game, load_probability_models
from gear_optimizer.piece_distribution import (
    action_position_quality_distribution,
    clear_piece_distribution_caches,
    fresh_piece_quality_distribution,
    piece_distribution_cache_sizes,
    position_quality_distribution,
)


def _billy_context():
    game = load_game("zzz")
    character = next(
        item
        for item in load_characters("zzz")
        if item.id == "zzz_starlight_billy"
    )
    probability_model = next(
        item
        for item in load_probability_models("zzz")
        if item.id == "zzz_default"
    )
    return game, character, probability_model


def _outcome_dict(outcomes):
    return {
        (outcome.quality_score, outcome.quality_vector): outcome.probability
        for outcome in outcomes
    }


def _legacy_quality_dict(game, character, probability_model, main_stat, required_substats=()):
    distribution = defaultdict(float)
    for count_text, count_probability in probability_model.initial_substat_count_probabilities.items():
        initial_count = int(count_text)
        initial_states = position_ev._initial_roll_states(
            game,
            main_stat,
            initial_count,
            required_substats,
        )
        final_states = position_ev._advance_roll_states(game, main_stat, initial_states, initial_count)
        for state, probability in final_states.items():
            quality_score, quality_vector = position_ev._quality_from_roll_state(state, character)
            distribution[(quality_score, quality_vector)] += count_probability * probability
    return {
        key: probability
        for key, probability in distribution.items()
        if probability > 1e-12
    }


@pytest.mark.parametrize(
    ("main_stat", "required_substats"),
    [
        ("生命值", ()),
        ("暴击率", ()),
        ("暴击伤害", ("暴击率",)),
        ("物理伤害", ("暴击率", "暴击伤害")),
        ("能量自动回复", ("暴击率", "暴击伤害", "生命值百分比")),
    ],
)
def test_fresh_quality_distribution_matches_legacy_roll_enumeration(main_stat, required_substats):
    game, character, probability_model = _billy_context()

    actual = _outcome_dict(
        fresh_piece_quality_distribution(
            game,
            character,
            probability_model,
            main_stat,
            required_substats,
        )
    )
    expected = _legacy_quality_dict(
        game,
        character,
        probability_model,
        main_stat,
        required_substats,
    )

    assert actual.keys() == expected.keys()
    for key, probability in expected.items():
        assert actual[key] == pytest.approx(probability)
    assert sum(actual.values()) == pytest.approx(1.0)


def test_position_distribution_handles_fixed_and_mixed_main_stats():
    game, character, probability_model = _billy_context()

    slot_one = position_quality_distribution(game, character, probability_model, 1)
    assert {outcome.main_stat for outcome in slot_one} == {"生命值"}
    assert sum(outcome.probability for outcome in slot_one) == pytest.approx(1.0)

    slot_four = position_quality_distribution(game, character, probability_model, 4)
    probability_by_main = defaultdict(float)
    for outcome in slot_four:
        probability_by_main[outcome.main_stat] += outcome.probability
    assert set(probability_by_main) == set(game.main_stats_for(4))
    for main_stat in game.main_stats_for(4):
        assert probability_by_main[main_stat] == pytest.approx(
            game.main_stat_probability(4, main_stat)
        )
    assert sum(probability_by_main.values()) == pytest.approx(1.0)

    fixed = position_quality_distribution(
        game,
        character,
        probability_model,
        4,
        fixed_main_stat="暴击率",
    )
    assert {outcome.main_stat for outcome in fixed} == {"暴击率"}
    assert sum(outcome.probability for outcome in fixed) == pytest.approx(1.0)


def test_random_position_distribution_is_mixture_of_fixed_positions():
    game, character, probability_model = _billy_context()

    random_distribution = action_position_quality_distribution(
        game,
        character,
        probability_model,
        target_position=None,
    )
    fixed_total = 0.0
    for rule in game.positions:
        fixed_total += sum(
            outcome.probability
            for outcome in position_quality_distribution(game, character, probability_model, rule.id)
        ) / len(game.positions)

    assert sum(outcome.probability for outcome in random_distribution) == pytest.approx(1.0)
    assert sum(outcome.probability for outcome in random_distribution) == pytest.approx(fixed_total)


def test_illegal_required_substats_return_empty_distribution():
    game, character, probability_model = _billy_context()

    assert (
        fresh_piece_quality_distribution(
            game,
            character,
            probability_model,
            "暴击率",
            ("暴击率",),
        )
        == ()
    )
    assert (
        fresh_piece_quality_distribution(
            game,
            character,
            probability_model,
            "暴击率",
            ("不存在的副词条",),
        )
        == ()
    )


def test_fresh_candidate_rows_use_precomputed_quality_distribution():
    game, character, probability_model = _billy_context()
    clear_piece_distribution_caches()

    rows = position_ev._fresh_candidate_row_distribution(
        game,
        character,
        probability_model,
        5,
        "云岿如我",
        "物理伤害",
        required_substats=("暴击率",),
    )

    expected = fresh_piece_quality_distribution(
        game,
        character,
        probability_model,
        "物理伤害",
        ("暴击率",),
    )
    assert len(rows) == len(expected)
    assert sum(probability for _row, probability in rows) == pytest.approx(1.0)
    assert piece_distribution_cache_sizes()["fresh_quality"] >= 1
    assert {
        (row["quality_score"], row["quality_vector"], probability)
        for row, probability in rows
    } == {
        (outcome.quality_score, outcome.quality_vector, outcome.probability)
        for outcome in expected
    }
