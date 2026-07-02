import yaml

from gear_optimizer.exporting import (
    candidate_yaml,
    character_target_yaml,
    current_gear_yaml,
    probability_model_yaml,
)
from gear_optimizer.game_rules import load_characters, load_probability_models
from gear_optimizer.models import CandidatePiece, GearPiece, SubstatLine
from gear_optimizer.presets import (
    load_candidate_yaml_text,
    load_character_target_yaml_text,
    load_current_yaml_text,
    load_probability_model_yaml_text,
)


def test_current_gear_yaml_exports_example_compatible_structure():
    pieces = [
        GearPiece(
            position=6,
            set_name="云岿如我",
            main_stat="生命值百分比",
            level=15,
            substats=[
                SubstatLine(stat="暴击率", rolls=0),
                SubstatLine(stat="攻击力", rolls=2),
            ],
        )
    ]

    data = yaml.safe_load(
        current_gear_yaml(
            "zzz",
            "zzz_starlight_billy",
            pieces,
            "导出测试",
        )
    )

    assert data["game"] == "zzz"
    assert data["character"] == "zzz_starlight_billy"
    assert data["label"] == "导出测试"
    assert data["pieces"][0]["position"] == 6
    assert "locked" not in data["pieces"][0]
    assert data["pieces"][0]["substats"][0] == {"stat": "暴击率", "rolls": 0}

    metadata, imported_pieces = load_current_yaml_text(
        current_gear_yaml(
            "zzz",
            "zzz_starlight_billy",
            pieces,
            "导出测试",
        )
    )
    assert metadata["game"] == "zzz"
    assert imported_pieces == pieces

    locked_piece = pieces[0].model_copy(update={"locked": True})
    locked_data = yaml.safe_load(
        current_gear_yaml(
            "zzz",
            "zzz_starlight_billy",
            [locked_piece],
            "锁定导出测试",
        )
    )
    assert locked_data["pieces"][0]["locked"] is True
    _metadata, imported_locked = load_current_yaml_text(
        current_gear_yaml("zzz", "zzz_starlight_billy", [locked_piece])
    )
    assert imported_locked == [locked_piece]


def test_current_gear_yaml_preserves_initial_substat_count():
    piece = GearPiece(
        position=5,
        set_name="云岿如我",
        main_stat="物理伤害",
        initial_substat_count=3,
        level=3,
        substats=[
            SubstatLine(stat="暴击率", rolls=0),
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="生命值百分比", rolls=0),
            SubstatLine(stat="攻击力百分比", rolls=0),
        ],
    )

    yaml_text = current_gear_yaml("zzz", "zzz_starlight_billy", [piece])
    data = yaml.safe_load(yaml_text)
    assert data["pieces"][0]["initial_substat_count"] == 3

    _metadata, imported_pieces = load_current_yaml_text(yaml_text)
    assert imported_pieces == [piece]


def test_character_target_yaml_preserves_configurable_targets():
    character = next(
        item
        for item in load_characters("zzz")
        if item.id == "zzz_starlight_billy"
    )

    data = yaml.safe_load(character_target_yaml(character))

    assert data["id"] == "zzz_starlight_billy"
    assert data["target_set"] == "云岿如我"
    assert data["preferred_main_stats"]["4"] == ["暴击率", "暴击伤害"]
    assert "effective_substats" not in data
    assert data["substat_priority"]["core"] == ["暴击率", "暴击伤害", "生命值百分比"]
    assert data["substat_priority"]["usable"] == []
    assert data["default_set_plan"] == "cloud_4_branch_2"
    assert data["target_effective_rolls"] == 6.0
    assert data["target_weighted_score"] == 6.0
    assert data["rating_thresholds"]["good"] == 4.0
    assert any(plan["id"] == "cloud_4_branch_2" for plan in data["set_plans"])
    assert any(plan["id"] == "cloud_4_flex_2" for plan in data["set_plans"])

    _metadata, imported_character = load_character_target_yaml_text(
        character_target_yaml(character)
    )
    assert imported_character == character


def test_candidate_yaml_round_trips_through_candidate_loader():
    candidate = CandidatePiece(
        position=4,
        set_name="云岿如我",
        main_stat="暴击率",
        initial_substat_count=3,
        level=3,
        substats=[
            SubstatLine(stat="攻击力百分比", rolls=0),
            SubstatLine(stat="防御力百分比", rolls=0),
            SubstatLine(stat="穿透值", rolls=0),
            SubstatLine(stat="暴击伤害", rolls=0),
        ],
    )

    metadata, imported_candidate = load_candidate_yaml_text(
        candidate_yaml("zzz", candidate, "候选导出测试")
    )

    assert metadata["game"] == "zzz"
    assert metadata["label"] == "候选导出测试"
    assert imported_candidate == candidate


def test_probability_model_yaml_round_trips_through_probability_loader():
    model = load_probability_models("zzz")[0]

    metadata, imported_model = load_probability_model_yaml_text(
        probability_model_yaml(model)
    )

    assert metadata["game"] == "zzz"
    assert metadata["id"] == model.id
    assert imported_model == model
