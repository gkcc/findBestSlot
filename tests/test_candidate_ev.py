import pytest
from pydantic import ValidationError

from gear_optimizer.candidate_ev import evaluate_candidate
from gear_optimizer.game_rules import load_characters, load_game
from gear_optimizer.models import CandidatePiece, CharacterPreset, GearPiece, SubstatLine
from gear_optimizer.presets import (
    list_candidate_examples,
    list_current_examples,
    load_candidate_example,
    load_current_example,
)


def _billy():
    return next(character for character in load_characters("zzz") if character.id == "zzz_starlight_billy")


def _hsr_placeholder():
    return next(character for character in load_characters("hsr") if character.id == "hsr_placeholder")


def test_slot5_physical_three_of_two_after_bad_plus_three_expects_four():
    game = load_game("zzz")
    character = _billy()
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")

    result = evaluate_candidate(candidate, game, character)

    assert result.current_effective_rolls == 2
    assert result.remaining_roll_events == 4
    assert result.per_event_hit_probabilities == [0.5, 0.5, 0.5, 0.5]
    assert [row["event"] for row in result.event_rows] == ["随机命中已有副属性"] * 4
    assert result.event_rows[0]["level"] == 6
    assert result.event_rows[0]["hit_probability"] == 0.5
    assert result.final_expected_effective_rolls == 4
    assert result.current_weighted_score == 2
    assert result.per_event_expected_weighted_gains == [0.5, 0.5, 0.5, 0.5]
    assert result.final_expected_weighted_score == 4
    assert sum(point.probability for point in result.weighted_distribution) == pytest.approx(1.0)
    assert result.recommendation == "继续"


def test_candidate_recommendation_respects_character_target_lines():
    game = load_game("zzz")
    character = _billy().model_copy(
        update={
            "target_effective_rolls": 9.0,
            "target_weighted_score": 9.0,
        }
    )
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")

    result = evaluate_candidate(candidate, game, character)

    assert result.final_expected_effective_rolls == 4
    assert result.final_expected_weighted_score == 4
    assert result.recommendation == "仅过渡"


def test_slot4_crit_three_of_zero_after_crit_damage_plus_three_expects_two():
    game = load_game("zzz")
    character = _billy()
    candidate = load_candidate_example("examples/zzz_candidate_slot4.yaml")

    result = evaluate_candidate(candidate, game, character)

    assert result.current_effective_rolls == 1
    assert result.remaining_roll_events == 4
    assert result.per_event_hit_probabilities == [0.25, 0.25, 0.25, 0.25]
    assert [row["level"] for row in result.event_rows] == [6, 9, 12, 15]
    assert result.event_rows[0]["event"] == "随机命中已有副属性"
    assert result.final_expected_effective_rolls == 2
    assert result.current_weighted_score == 1
    assert result.final_expected_weighted_score == 2
    assert result.recommendation == "仅过渡"
    assert sum(point.probability for point in result.distribution) == pytest.approx(1.0)


def test_missing_plus_three_substat_is_treated_as_unknown_invalid_line():
    game = load_game("zzz")
    character = _billy()
    candidate = CandidatePiece(
        position=5,
        set_name="云岿如我",
        main_stat="物理伤害",
        initial_substat_count=3,
        level=3,
        substats=[
            SubstatLine(stat="暴击率", rolls=0),
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="攻击力百分比", rolls=0),
        ],
    )

    result = evaluate_candidate(candidate, game, character)

    assert result.remaining_roll_events == 4
    assert result.per_event_hit_probabilities == [0.5, 0.5, 0.5, 0.5]
    assert result.final_expected_effective_rolls == 4
    assert any("+3 后应已有第 4 个副属性" in warning for warning in result.warnings)


def test_candidate_examples_are_filtered_by_game():
    zzz_examples = list_candidate_examples("zzz")
    hsr_examples = list_candidate_examples("hsr")

    assert {item["label"] for item in zzz_examples} == {
        "4号暴击，3中0，+3 出暴伤",
        "5号物伤，3中2，+3 歪",
    }
    assert [item["path"].replace("\\", "/") for item in hsr_examples] == [
        "examples/hsr_candidate_body.yaml"
    ]


def test_hsr_candidate_example_runs_candidate_ev_placeholder_path():
    game = load_game("hsr")
    character = _hsr_placeholder()
    candidate = load_candidate_example("examples/hsr_candidate_body.yaml")

    result = evaluate_candidate(candidate, game, character)

    assert result.current_effective_rolls == 1
    assert result.remaining_upgrade_events == 5
    assert result.remaining_roll_events == 4
    assert result.event_rows[0]["event"] == "补第 4 副属性"
    assert result.event_rows[0]["hit_probability"] == pytest.approx(0.125)
    assert result.final_expected_effective_rolls > result.current_effective_rolls
    assert sum(point.probability for point in result.distribution) == pytest.approx(1.0)


def test_current_examples_are_filtered_by_game_and_character():
    billy_examples = list_current_examples("zzz", "zzz_starlight_billy")
    unknown_examples = list_current_examples("zzz", "unknown_character")
    hsr_examples = list_current_examples("hsr")
    hsr_character_examples = list_current_examples("hsr", "hsr_placeholder")

    assert [item["path"].replace("\\", "/") for item in billy_examples] == [
        "examples/zzz_billy_current.yaml"
    ]
    assert billy_examples[0]["character"] == "zzz_starlight_billy"
    assert unknown_examples == []
    assert [item["path"].replace("\\", "/") for item in hsr_examples] == [
        "examples/hsr_placeholder_current.yaml"
    ]
    assert hsr_character_examples == hsr_examples
    assert load_current_example(hsr_examples[0]["path"])[0].position == "head"


def test_candidate_recommendation_ignores_legacy_numeric_weight_magnitude():
    game = load_game("zzz")
    data = _billy().model_dump(mode="json")
    data.pop("substat_priority", None)
    data["effective_substats"] = {
        "暴击率": 0.35,
        "暴击伤害": 0.35,
        "生命值百分比": 0.2,
    }
    character = CharacterPreset.model_validate(data)
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")

    result = evaluate_candidate(candidate, game, character)

    assert character.ordered_effective_substats() == ["暴击率", "暴击伤害", "生命值百分比"]
    assert result.final_expected_effective_rolls == 4
    assert result.final_expected_weighted_score == 4
    assert result.recommendation == "继续"


def test_level_zero_three_line_candidate_event_rows_start_with_add_line():
    game = load_game("zzz")
    character = _billy()
    candidate = CandidatePiece(
        position=5,
        set_name="云岿如我",
        main_stat="物理伤害",
        initial_substat_count=3,
        level=0,
        substats=[
            SubstatLine(stat="暴击率", rolls=0),
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="攻击力百分比", rolls=0),
        ],
    )

    result = evaluate_candidate(candidate, game, character)

    assert result.remaining_upgrade_events == 5
    assert result.remaining_roll_events == 4
    assert result.event_rows[0]["level"] == 3
    assert result.event_rows[0]["event"] == "补第 4 副属性"
    assert result.event_rows[0]["hit_probability"] > 0
    assert [row["event"] for row in result.event_rows[1:]] == ["随机命中已有副属性"] * 4


def test_gear_models_reject_main_stat_repeated_as_substat():
    with pytest.raises(ValidationError, match="main_stat cannot appear"):
        GearPiece(
            position=4,
            set_name="云岿如我",
            main_stat="暴击率",
            substats=[SubstatLine(stat="暴击率", rolls=0)],
        )

    with pytest.raises(ValidationError, match="main_stat cannot appear"):
        CandidatePiece(
            position=5,
            set_name="云岿如我",
            main_stat="物理伤害",
            initial_substat_count=3,
            substats=[SubstatLine(stat="物理伤害", rolls=0)],
        )


def test_gear_models_reject_duplicate_substats():
    with pytest.raises(ValidationError, match="substats must be unique"):
        GearPiece(
            position=6,
            set_name="云岿如我",
            main_stat="生命值百分比",
            substats=[
                SubstatLine(stat="暴击率", rolls=0),
                SubstatLine(stat="暴击率", rolls=1),
            ],
        )

    with pytest.raises(ValidationError, match="substats must be unique"):
        CandidatePiece(
            position=5,
            set_name="云岿如我",
            main_stat="物理伤害",
            initial_substat_count=3,
            substats=[
                SubstatLine(stat="暴击伤害", rolls=0),
                SubstatLine(stat="暴击伤害", rolls=0),
            ],
        )
