import pytest
from pydantic import ValidationError
from pathlib import Path

from gear_optimizer.game_rules import (
    load_characters,
    load_game,
    load_probability_models,
    project_root,
    validate_candidate_against_game,
    validate_character_against_game,
    validate_current_gear_against_game,
)
from gear_optimizer import game_rules
from gear_optimizer.models import (
    CandidatePiece,
    CharacterPreset,
    GameRules,
    GearPiece,
    ProbabilityModel,
    SubstatLine,
    position_key,
)
from gear_optimizer.presets import (
    list_candidate_examples,
    list_current_examples,
    load_candidate_example,
    load_current_example,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_project_root_prefers_pyinstaller_bundle_root(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "configs" / "games").mkdir(parents=True)
    (bundle / "examples").mkdir()
    (bundle / "desktop_app.py").write_text("# bundled app", encoding="utf-8")
    (bundle / "pyproject.toml").write_text("[project]\nname='bundle'\n", encoding="utf-8")

    monkeypatch.setattr(game_rules.sys, "_MEIPASS", str(bundle), raising=False)

    assert project_root() == bundle.resolve()


@pytest.mark.parametrize("game_id", ["zzz", "hsr"])
def test_every_position_has_configured_main_stat_probabilities(game_id):
    game = load_game(game_id)

    for position in game.positions:
        key = position_key(position.id)
        probabilities = game.main_stat_probabilities.get(key)
        assert probabilities is not None
        assert set(probabilities) == set(position.main_stats)
        assert sum(probabilities.values()) == pytest.approx(1.0)


def test_key_main_stat_probabilities_are_explicitly_configured():
    zzz = load_game("zzz")
    hsr = load_game("hsr")

    assert zzz.main_stat_probability(5, "物理伤害") == pytest.approx(1 / 9)
    assert zzz.main_stat_probability(6, "生命值百分比") == pytest.approx(1 / 6)
    assert hsr.main_stat_probability("body", "暴击率") == pytest.approx(0.1)
    assert hsr.main_stat_probability("feet", "速度") == pytest.approx(0.12)
    assert hsr.main_stat_probability("sphere", "物理属性伤害") == pytest.approx(0.09)
    assert hsr.main_stat_probability("rope", "能量恢复效率") == pytest.approx(0.0510204082)


def test_zzz_set_icons_point_to_local_assets():
    game = load_game("zzz")

    assert game.set_icons
    assert set(game.set_icons) == set(game.sets)
    assert {"云岿如我", "啄木鸟电音", "拂晓行纪", "呼啸沙龙"}.issubset(game.sets)
    assert len(game.sets) >= 28
    for set_name, relative_path in game.set_icons.items():
        assert set_name in game.sets
        assert (PROJECT_ROOT / relative_path).exists()


def test_zzz_set_effects_cover_local_drive_disc_sets():
    game = load_game("zzz")

    assert game.set_effects
    assert set(game.set_effects) == set(game.sets)
    woodpecker = game.set_effect("啄木鸟电音")
    assert woodpecker is not None
    assert "暴击率" in (woodpecker.two_piece or "")
    assert "普通攻击" in (woodpecker.four_piece or "")


def test_hsr_placeholder_sets_cover_relic_and_planar_display():
    game = load_game("hsr")
    character = next(item for item in load_characters("hsr") if item.id == "hsr_placeholder")
    model = load_probability_models("hsr")[0]

    assert game.sets == ["占位遗器套装", "占位位面饰品套装"]
    assert set(game.set_effects) == set(game.sets)
    assert "遗器 4 件套" in (game.set_effect("占位遗器套装").four_piece or "")
    assert "位面饰品 2 件套" in (game.set_effect("占位位面饰品套装").two_piece or "")
    assert character.active_set_plan().name == "占位遗器 4 + 占位位面 2"
    assert model.target_set_probability == pytest.approx(1.0)
    assert game.sets_for_position("head") == ["占位遗器套装"]
    assert game.sets_for_position("sphere") == ["占位位面饰品套装"]
    assert not game.set_available_for_position("占位位面饰品套装", "head")
    assert not game.set_available_for_position("占位遗器套装", "rope")
    assert model.resource_cost("advanced_material_fixed_main_attempt") == pytest.approx(1.0)
    assert model.resource_cost("advanced_material_fixed_main_1_substat_attempt") == pytest.approx(2.0)
    assert model.resource_cost("advanced_material_fixed_main_2_substats_attempt") == pytest.approx(5.0)


def test_hsr_validation_rejects_planar_set_on_outer_relic_position():
    game = load_game("hsr")
    piece = GearPiece(
        position="head",
        set_name="占位位面饰品套装",
        main_stat="生命值",
        level=15,
        substats=[],
    )

    with pytest.raises(ValueError, match="not available for position"):
        validate_current_gear_against_game([piece], game)


def test_current_and_candidate_examples_validate_against_games():
    for game_id in ["zzz", "hsr"]:
        game = load_game(game_id)
        for item in list_current_examples(game_id):
            validate_current_gear_against_game(load_current_example(item["path"]), game)
        for item in list_candidate_examples(game_id):
            validate_candidate_against_game(load_candidate_example(item["path"]), game)


def test_gear_validation_rejects_level_and_rolls_outside_game_rules():
    game = load_game("zzz")

    with pytest.raises(ValueError, match="level"):
        validate_current_gear_against_game(
            [
                GearPiece(
                    position=6,
                    set_name="云岿如我",
                    main_stat="生命值百分比",
                    level=14,
                    substats=[],
                )
            ],
            game,
        )

    with pytest.raises(ValueError, match="roll total"):
        validate_current_gear_against_game(
            [
                GearPiece(
                    position=6,
                    set_name="云岿如我",
                    main_stat="生命值百分比",
                    level=3,
                    substats=[
                        SubstatLine(stat="暴击率", rolls=2),
                    ],
                )
            ],
            game,
        )


def test_candidate_validation_respects_initial_three_line_visibility():
    game = load_game("zzz")
    candidate = CandidatePiece(
        position=5,
        set_name="云岿如我",
        main_stat="物理伤害",
        initial_substat_count=3,
        level=0,
        substats=[
            SubstatLine(stat="暴击率", rolls=0),
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="生命值百分比", rolls=0),
            SubstatLine(stat="攻击力百分比", rolls=0),
        ],
    )

    with pytest.raises(ValueError, match="at most 3 substats"):
        validate_candidate_against_game(candidate, game)


def test_current_gear_validation_respects_initial_three_line_roll_timing():
    game = load_game("zzz")
    too_many_visible_at_zero = GearPiece(
        position=5,
        set_name="云岿如我",
        main_stat="物理伤害",
        initial_substat_count=3,
        level=0,
        substats=[
            SubstatLine(stat="暴击率", rolls=0),
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="生命值百分比", rolls=0),
            SubstatLine(stat="攻击力百分比", rolls=0),
        ],
    )

    with pytest.raises(ValueError, match="at most 3 substats"):
        validate_current_gear_against_game([too_many_visible_at_zero], game)

    just_added_fourth_line = too_many_visible_at_zero.model_copy(update={"level": 3})
    validate_current_gear_against_game([just_added_fourth_line], game)

    rolled_on_add_level = just_added_fourth_line.model_copy(
        update={
            "substats": [
                SubstatLine(stat="暴击率", rolls=1),
                SubstatLine(stat="暴击伤害", rolls=0),
                SubstatLine(stat="生命值百分比", rolls=0),
                SubstatLine(stat="攻击力百分比", rolls=0),
            ]
        }
    )
    with pytest.raises(ValueError, match="roll total"):
        validate_current_gear_against_game([rolled_on_add_level], game)


def test_current_gear_validation_rejects_duplicate_positions_and_unknown_stats():
    game = load_game("zzz")
    pieces = [
        GearPiece(
            position=6,
            set_name="云岿如我",
            main_stat="生命值百分比",
            level=0,
            substats=[],
        ),
        GearPiece(
            position=6,
            set_name="云岿如我",
            main_stat="生命值百分比",
            level=0,
            substats=[],
        ),
    ]

    with pytest.raises(ValueError, match="duplicate position"):
        validate_current_gear_against_game(pieces, game)

    with pytest.raises(ValueError, match="unknown stats"):
        validate_current_gear_against_game(
            [
                GearPiece(
                    position=6,
                    set_name="云岿如我",
                    main_stat="生命值百分比",
                    level=0,
                    substats=[SubstatLine(stat="不存在词条", rolls=0)],
                )
            ],
            game,
        )


@pytest.mark.parametrize("game_id", ["zzz", "hsr"])
def test_loaded_probability_models_have_valid_initial_substat_distribution(game_id):
    models = load_probability_models(game_id)

    assert models
    for model in models:
        assert set(model.initial_substat_count_probabilities) == {"3", "4"}
        assert sum(model.initial_substat_count_probabilities.values()) == pytest.approx(1.0)
        assert 0 <= model.target_set_probability <= 1
        assert all(value >= 0 for value in model.resource_costs.values())


def _minimal_game_config() -> dict:
    return {
        "id": "test",
        "name": "测试",
        "gear_name": "测试装备",
        "positions": [
            {
                "id": "slot",
                "name": "位置",
                "main_stats": ["A", "B"],
            }
        ],
        "sub_stats": ["X", "Y"],
        "main_stat_probabilities": {
            "slot": {
                "A": 0.5,
                "B": 0.5,
            }
        },
        "sub_stat_probabilities": {
            "X": 1.0,
            "Y": 1.0,
        },
    }


def test_game_rules_reject_unknown_main_stat_probability_keys():
    data = _minimal_game_config()
    data["main_stat_probabilities"]["slot"] = {"A": 0.5, "C": 0.5}

    with pytest.raises(ValidationError, match="must match main_stats"):
        GameRules.model_validate(data)


def test_game_rules_reject_unknown_set_icon_keys():
    data = _minimal_game_config()
    data["sets"] = ["套装A"]
    data["set_icons"] = {"不存在套装": "assets/missing.png"}

    with pytest.raises(ValidationError, match="set_icons"):
        GameRules.model_validate(data)


def test_game_rules_reject_unknown_set_effect_keys():
    data = _minimal_game_config()
    data["sets"] = ["套装A"]
    data["set_effects"] = {
        "不存在套装": {
            "two_piece": "测试 2 件效果",
            "four_piece": "测试 4 件效果",
        }
    }

    with pytest.raises(ValidationError, match="set_effects"):
        GameRules.model_validate(data)


def test_game_rules_reject_main_stat_probabilities_that_do_not_sum_to_one():
    data = _minimal_game_config()
    data["main_stat_probabilities"]["slot"] = {"A": 0.7, "B": 0.7}

    with pytest.raises(ValidationError, match="must sum to 1.0"):
        GameRules.model_validate(data)


def test_game_rules_reject_unknown_substat_probability_keys():
    data = _minimal_game_config()
    data["sub_stat_probabilities"]["Z"] = 1.0

    with pytest.raises(ValidationError, match="unknown stats"):
        GameRules.model_validate(data)


def test_game_rules_reject_board_layout_with_unknown_position():
    data = _minimal_game_config()
    data["board_layout"] = [["slot", "missing"]]

    with pytest.raises(ValidationError, match="unknown positions"):
        GameRules.model_validate(data)


def test_game_rules_reject_board_layout_with_duplicate_positions():
    data = _minimal_game_config()
    data["board_layout"] = [["slot", "slot"]]

    with pytest.raises(ValidationError, match="duplicate positions"):
        GameRules.model_validate(data)


def test_game_rules_reject_board_layout_missing_positions():
    data = _minimal_game_config()
    data["positions"].append(
        {
            "id": "slot2",
            "name": "位置2",
            "main_stats": ["A"],
        }
    )
    data["main_stat_probabilities"]["slot2"] = {"A": 1.0}
    data["board_layout"] = [["slot"]]

    with pytest.raises(ValidationError, match="missing positions"):
        GameRules.model_validate(data)


def _minimal_probability_model_config() -> dict:
    return {
        "id": "test_probability",
        "game": "zzz",
        "name": "测试概率模型",
        "target_set_probability": 0.5,
        "initial_substat_count_probabilities": {
            "3": 0.8,
            "4": 0.2,
        },
        "resource_costs": {
            "mother_disk_per_attempt": 1.0,
        },
    }


def test_probability_model_rejects_target_set_probability_out_of_range():
    data = _minimal_probability_model_config()
    data["target_set_probability"] = 1.5

    with pytest.raises(ValidationError, match="target_set_probability"):
        ProbabilityModel.model_validate(data)


def test_probability_model_rejects_missing_initial_substat_count_probabilities():
    data = _minimal_probability_model_config()
    data["initial_substat_count_probabilities"] = {"3": 1.0}

    with pytest.raises(ValidationError, match="exactly 3 and 4"):
        ProbabilityModel.model_validate(data)


def test_probability_model_rejects_initial_substat_probabilities_that_do_not_sum_to_one():
    data = _minimal_probability_model_config()
    data["initial_substat_count_probabilities"] = {"3": 0.7, "4": 0.7}

    with pytest.raises(ValidationError, match="must sum to 1.0"):
        ProbabilityModel.model_validate(data)


def test_probability_model_rejects_negative_resource_costs():
    data = _minimal_probability_model_config()
    data["resource_costs"] = {"mother_disk_per_attempt": -1.0}

    with pytest.raises(ValidationError, match="resource_costs"):
        ProbabilityModel.model_validate(data)


def _minimal_character_config() -> dict:
    return {
        "id": "test_character",
        "game": "zzz",
        "name": "测试角色",
        "target_set": "云岿如我",
        "effective_substats": {"暴击率": 1.0},
        "preferred_main_stats": {"4": ["暴击率"]},
        "default_set_plan": "test_plan",
        "set_plans": [
            {
                "id": "test_plan",
                "name": "测试方案",
                "requirements": [
                    {
                        "set_name": "云岿如我",
                        "pieces": 4,
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize("game_id", ["zzz", "hsr"])
def test_loaded_characters_validate_against_games(game_id):
    characters = load_characters(game_id)

    assert characters


def test_zzz_character_targets_are_not_limited_to_starlight_billy():
    characters = load_characters("zzz")
    by_id = {character.id: character for character in characters}

    assert {"zzz_starlight_billy", "zzz_template_anomaly"}.issubset(by_id)
    billy = by_id["zzz_starlight_billy"]
    assert billy.substat_priority is not None
    assert billy.substat_priority.core == ["暴击率", "暴击伤害", "生命值百分比"]
    assert billy.substat_priority.usable == []
    assert billy.weight_for("暴击率") == 1.0
    assert billy.weight_for("生命值百分比") == 1.0
    assert billy.ordered_effective_substats() == ["暴击率", "暴击伤害", "生命值百分比"]
    assert billy.default_set_plan == "cloud_4_branch_2"
    assert billy.active_set_plan().name == "云岿如我 4 + 折枝剑歌 2"
    assert billy.active_set_plan().requirements[1].set_name == "折枝剑歌"
    non_default_notes = [
        plan.notes or ""
        for plan in billy.set_plans
        if plan.id != billy.default_set_plan
    ]
    assert not any("默认长期目标" in note for note in non_default_notes)
    anomaly = by_id["zzz_template_anomaly"]
    assert anomaly.target_set == "自由蓝调"
    assert anomaly.preferred_mains_for(4) == ["异常精通"]
    assert anomaly.preferred_mains_for(6) == ["异常掌控"]
    assert anomaly.weight_for("异常精通") == 1.0
    assert anomaly.ordered_effective_substats() == ["异常精通", "攻击力百分比", "穿透值"]
    assert anomaly.active_set_plan().name == "自由蓝调 4 + 摇摆爵士 2"


def test_character_rejects_negative_effective_weights():
    data = _minimal_character_config()
    data["effective_substats"] = {"暴击率": -1.0}

    with pytest.raises(ValidationError, match="negative weights"):
        CharacterPreset.model_validate(data)


def test_character_can_derive_effective_substats_from_priority_groups():
    data = _minimal_character_config()
    data.pop("effective_substats")
    data["substat_priority"] = {
        "core": ["暴击率", "暴击伤害"],
        "usable": ["生命值百分比"],
    }

    character = CharacterPreset.model_validate(data)

    assert character.effective_substats == {
        "暴击率": 1.0,
        "暴击伤害": 1.0,
        "生命值百分比": 1.0,
    }
    assert character.ordered_effective_substats() == ["暴击率", "暴击伤害", "生命值百分比"]


def test_character_rejects_duplicate_priority_stats():
    data = _minimal_character_config()
    data.pop("effective_substats")
    data["substat_priority"] = {
        "core": ["暴击率"],
        "usable": ["暴击率"],
    }

    with pytest.raises(ValidationError, match="duplicate stats"):
        CharacterPreset.model_validate(data)


def test_character_rejects_negative_weighted_target_score():
    data = _minimal_character_config()
    data["target_weighted_score"] = -1.0

    with pytest.raises(ValidationError, match="target_weighted_score"):
        CharacterPreset.model_validate(data)


def test_character_weighted_target_score_falls_back_for_legacy_session_objects():
    character = CharacterPreset.model_construct(
        id="legacy",
        game="zzz",
        name="旧 session 角色",
        target_set="云岿如我",
        effective_substats={"暴击率": 1.0},
        target_effective_rolls=4.5,
        rating_thresholds={"usable": 2.0, "good": 4.0, "excellent": 6.0},
    )

    assert character.weighted_target_score == 4.5


def test_character_rejects_missing_default_set_plan():
    data = _minimal_character_config()
    data["default_set_plan"] = "missing"

    with pytest.raises(ValidationError, match="default_set_plan"):
        CharacterPreset.model_validate(data)


def test_character_rejects_unknown_effective_substats():
    data = _minimal_character_config()
    data["effective_substats"] = {"不存在词条": 1.0}
    character = CharacterPreset.model_validate(data)

    with pytest.raises(ValueError, match="unknown stats"):
        validate_character_against_game(character, load_game("zzz"))


def test_character_rejects_unknown_preferred_position():
    data = _minimal_character_config()
    data["preferred_main_stats"] = {"9": ["暴击率"]}
    character = CharacterPreset.model_validate(data)

    with pytest.raises(ValueError, match="unknown position"):
        validate_character_against_game(character, load_game("zzz"))


def test_character_rejects_unknown_preferred_main_stat():
    data = _minimal_character_config()
    data["preferred_main_stats"] = {"4": ["物理伤害"]}
    character = CharacterPreset.model_validate(data)

    with pytest.raises(ValueError, match="unknown main stats"):
        validate_character_against_game(character, load_game("zzz"))


def test_character_rejects_unknown_set_plan_sets():
    data = _minimal_character_config()
    data["set_plans"][0]["requirements"][0]["set_name"] = "不存在套装"
    character = CharacterPreset.model_validate(data)

    with pytest.raises(ValueError, match="unknown sets"):
        validate_character_against_game(character, load_game("zzz"))


def test_character_rejects_set_plan_requiring_more_pieces_than_game_positions():
    data = _minimal_character_config()
    data["set_plans"][0]["requirements"] = [
        {
            "set_name": "云岿如我",
            "pieces": 4,
        },
        {
            "set_name": "啄木鸟电音",
            "pieces": 4,
        },
    ]
    character = CharacterPreset.model_validate(data)

    with pytest.raises(ValueError, match="requires 8 pieces"):
        validate_character_against_game(character, load_game("zzz"))


def test_character_rejects_unknown_target_set():
    data = _minimal_character_config()
    data["target_set"] = "不存在套装"
    character = CharacterPreset.model_validate(data)

    with pytest.raises(ValueError, match="target_set"):
        validate_character_against_game(character, load_game("zzz"))
