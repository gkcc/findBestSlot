from gear_optimizer.game_rules import load_characters, load_game
from gear_optimizer.models import GearPiece, SetPlan, SetRequirement, SubstatLine
from gear_optimizer.presets import load_current_example
from gear_optimizer.scoring import analyse_current_gear


def _billy():
    return next(character for character in load_characters("zzz") if character.id == "zzz_starlight_billy")


def test_billy_current_gear_finds_slot_6_as_weakest():
    game = load_game("zzz")
    character = _billy()
    pieces = load_current_example("examples/zzz_billy_current.yaml")

    analysis = analyse_current_gear(pieces, game, character)

    assert analysis.weakest_position == 6
    slot6 = next(score for score in analysis.scores if score.position == 6)
    assert slot6.effective_rolls == 1
    assert slot6.rating == "weak"
    assert analysis.relative_priority[0]["position"] == 6


def test_billy_set_plan_tracks_missing_two_piece_set():
    game = load_game("zzz")
    character = _billy()
    pieces = load_current_example("examples/zzz_billy_current.yaml")

    analysis = analyse_current_gear(pieces, game, character)

    assert analysis.set_plan is not None
    assert analysis.set_plan["name"] == "云岿如我 4 + 折枝剑歌 2"
    assert not analysis.set_plan["satisfied"]
    assert len(analysis.set_plan["missing"]) == 1
    missing = analysis.set_plan["missing"][0]
    assert {
        "set_name": missing["set_name"],
        "required": missing["required"],
        "current": missing["current"],
        "missing": missing["missing"],
        "set_names": missing.get("set_names", [missing["set_name"]]),
        "label": missing.get("label", missing["set_name"]),
        "role": missing["role"],
    } == {
        "set_name": "折枝剑歌",
        "required": 2,
        "current": 0,
        "missing": 2,
        "set_names": ["折枝剑歌"],
        "label": "折枝剑歌",
        "role": "pair2",
    }
    assert missing["stage_priority_score"] > 0
    assert "算法排序" in missing["stage_priority_basis"]
    assert analysis.set_plan["target_sets"] == [
        "云岿如我",
        "折枝剑歌",
    ]
    assert analysis.set_plan["position_pressures"]["6"]["replacement_badge"] == "优先替换"
    assert analysis.set_plan["position_pressures"]["1"]["replacement_badge"] == "可替换"
    target_by_position = {
        row["position"]: row
        for row in analysis.set_plan["position_targets"]
    }
    assert target_by_position[5]["target_set"] == "折枝剑歌"
    assert target_by_position[5]["status"] == "建议让位"
    assert target_by_position[6]["target_set"] == "折枝剑歌"
    assert target_by_position[6]["target_group"] == "折枝剑歌"
    assert target_by_position[6]["status"] == "建议让位"
    assert "让位压力" in target_by_position[6]["reason"]


def test_locked_piece_is_scored_but_not_recommended_for_replacement():
    game = load_game("zzz")
    character = _billy()
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    pieces[5] = pieces[5].model_copy(update={"locked": True})

    analysis = analyse_current_gear(pieces, game, character)

    assert analysis.weakest_position == 6
    assert analysis.set_plan is not None
    slot6_pressure = analysis.set_plan["position_pressures"]["6"]
    assert slot6_pressure["locked"]
    assert slot6_pressure["replacement_badge"] == "已锁定"
    assert slot6_pressure["replacement_pressure"] == 0
    assert analysis.set_plan["suggested_replacements"][0]["position"] != 6
    assert analysis.relative_priority[0]["position"] != 6
    assert analysis.relative_priority[-1]["position"] == 6


def test_set_plan_reports_when_locked_pieces_make_plan_infeasible():
    game = load_game("zzz")
    character = _billy()
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    for index in range(5):
        pieces[index] = pieces[index].model_copy(update={"locked": True})

    analysis = analyse_current_gear(pieces, game, character)

    assert analysis.set_plan is not None
    assert not analysis.set_plan["feasible_with_locks"]
    assert analysis.set_plan["locked_piece_count"] == 5
    assert analysis.set_plan["unlocked_position_count"] == 1
    assert analysis.set_plan["minimum_unlocked_needed"] == 2
    assert analysis.set_plan["locked_capacity_gap"] == 1
    assert analysis.set_plan["locked_requirement_rows"][1] == {
        "target": "折枝剑歌",
        "selected_set": "折枝剑歌",
        "required": 2,
        "locked_current": 0,
        "minimum_unlocked_needed": 2,
    }


def test_effective_roll_count_and_quality_score_follow_priority_order_without_weights():
    game = load_game("zzz")
    character = _billy()
    pieces = load_current_example("examples/zzz_billy_current.yaml")

    analysis = analyse_current_gear(pieces, game, character)
    slot6 = next(score for score in analysis.scores if score.position == 6)
    slot6_priority = next(row for row in analysis.relative_priority if row["position"] == 6)

    assert slot6.effective_rolls == 1
    assert slot6.weighted_score == 1
    assert slot6_priority["current_effective_rolls"] == 1
    assert slot6_priority["current_weighted_score"] == 1
    detail_by_stat = {item["stat"]: item for item in slot6.substat_details}
    assert detail_by_stat["暴击率"]["priority"] == "核心"
    assert detail_by_stat["暴击率"]["priority_rank"] == 1
    assert "weight" not in detail_by_stat["暴击率"]
    assert detail_by_stat["攻击力"]["priority"] == "无效"


def test_substat_details_distinguish_core_usable_and_invalid_stats():
    game = load_game("zzz")
    character = _billy()
    pieces = load_current_example("examples/zzz_billy_current.yaml")

    analysis = analyse_current_gear(pieces, game, character)
    slot1 = next(score for score in analysis.scores if score.position == 1)
    detail_by_stat = {item["stat"]: item for item in slot1.substat_details}

    assert detail_by_stat["暴击率"]["priority"] == "核心"
    assert detail_by_stat["暴击伤害"]["priority"] == "核心"
    assert detail_by_stat["生命值百分比"]["priority"] == "核心"
    assert detail_by_stat["防御力"]["priority"] == "无效"
    assert detail_by_stat["生命值百分比"]["weighted_score"] == 2
    assert detail_by_stat["生命值百分比"]["priority_rank"] == 3


def test_set_replacement_pressure_keeps_excellent_piece_when_filling_two_piece_gap():
    game = load_game("zzz")
    character = _billy()
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    pieces[4] = GearPiece(
        position=5,
        set_name="云岿如我",
        main_stat="物理伤害",
        level=15,
        substats=[
            SubstatLine(stat="攻击力", rolls=2),
            SubstatLine(stat="防御力", rolls=1),
            SubstatLine(stat="穿透值", rolls=1),
            SubstatLine(stat="异常精通", rolls=1),
        ],
    )
    pieces[5] = GearPiece(
        position=6,
        set_name="云岿如我",
        main_stat="生命值百分比",
        level=15,
        substats=[
            SubstatLine(stat="暴击率", rolls=3),
            SubstatLine(stat="暴击伤害", rolls=2),
            SubstatLine(stat="防御力", rolls=1),
            SubstatLine(stat="攻击力", rolls=0),
        ],
    )

    analysis = analyse_current_gear(pieces, game, character)

    assert analysis.set_plan is not None
    assert analysis.set_plan["surplus"] == [
        {
            "set_name": "云岿如我",
            "required": 4,
            "current": 6,
            "surplus": 2,
        }
    ]
    assert analysis.set_plan["suggested_replacements"][0]["position"] == 5
    assert analysis.set_plan["position_pressures"]["5"]["replacement_badge"] == "优先替换"
    assert analysis.set_plan["position_pressures"]["6"]["replacement_badge"] == "可替换"
    assert (
        analysis.set_plan["position_pressures"]["5"]["replacement_pressure"]
        > analysis.set_plan["position_pressures"]["6"]["replacement_pressure"]
    )
    target_by_position = {
        row["position"]: row
        for row in analysis.set_plan["position_targets"]
    }
    assert target_by_position[6]["target_set"] == "云岿如我"
    assert target_by_position[6]["status"] == "规划保留"
    assert target_by_position[6]["action"] == "保留为核心 4 件"
    assert target_by_position[5]["target_set"] == "折枝剑歌"
    assert target_by_position[5]["status"] == "建议让位"


def test_set_replacement_badge_marks_pieces_as_keep_when_set_plan_is_satisfied():
    game = load_game("zzz")
    character = _billy()
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    pieces[4] = GearPiece(
        position=5,
        set_name="折枝剑歌",
        main_stat="物理伤害",
        level=15,
        substats=[
            SubstatLine(stat="暴击率", rolls=1),
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="生命值百分比", rolls=0),
            SubstatLine(stat="攻击力", rolls=4),
        ],
    )
    pieces[5] = GearPiece(
        position=6,
        set_name="折枝剑歌",
        main_stat="生命值百分比",
        level=15,
        substats=[
            SubstatLine(stat="暴击率", rolls=0),
            SubstatLine(stat="攻击力", rolls=2),
            SubstatLine(stat="防御力", rolls=2),
            SubstatLine(stat="穿透值", rolls=1),
        ],
    )

    analysis = analyse_current_gear(pieces, game, character)

    assert analysis.set_plan is not None
    assert analysis.set_plan["satisfied"]
    assert analysis.set_plan["position_pressures"]["5"]["replacement_badge"] == "保留"
    assert analysis.set_plan["position_pressures"]["6"]["replacement_badge"] == "保留"


def test_flexible_two_piece_plan_marks_unselected_alternative_as_replaceable():
    game = load_game("zzz")
    character = _billy().model_copy(update={"default_set_plan": "cloud_4_flex_2"})
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    for index, set_name in enumerate(
        ["云岿如我", "云岿如我", "啄木鸟电音", "啄木鸟电音", "河豚电音", "河豚电音"]
    ):
        pieces[index] = pieces[index].model_copy(update={"set_name": set_name})

    analysis = analyse_current_gear(pieces, game, character)

    assert analysis.set_plan is not None
    assert analysis.set_plan["missing"][0]["set_name"] == "云岿如我"
    assert analysis.set_plan["surplus"] == [
        {
            "set_name": "河豚电音",
            "required": 0,
            "current": 2,
            "surplus": 2,
        }
    ]
    assert analysis.set_plan["position_pressures"]["5"]["replaceable_for_set_plan"]
    assert analysis.set_plan["position_pressures"]["6"]["replaceable_for_set_plan"]


def test_custom_main_stat_targets_affect_piece_preference():
    game = load_game("zzz")
    character = _billy().model_copy(
        update={"preferred_main_stats": {"5": ["生命值百分比"]}}
    )
    pieces = load_current_example("examples/zzz_billy_current.yaml")

    analysis = analyse_current_gear(pieces, game, character)

    slot5 = next(score for score in analysis.scores if score.position == 5)
    assert slot5.main_stat == "物理伤害"
    assert not slot5.main_stat_preferred


def test_main_stat_mismatch_becomes_prominent_current_priority():
    game = load_game("zzz")
    character = _billy().model_copy(
        update={"preferred_main_stats": {"5": ["生命值百分比"]}}
    )
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    pieces[5] = GearPiece(
        position=6,
        set_name="云岿如我",
        main_stat="生命值百分比",
        level=15,
        substats=[
            SubstatLine(stat="暴击率", rolls=3),
            SubstatLine(stat="暴击伤害", rolls=2),
            SubstatLine(stat="攻击力", rolls=0),
            SubstatLine(stat="防御力", rolls=0),
        ],
    )

    analysis = analyse_current_gear(pieces, game, character)

    assert analysis.relative_priority[0]["position"] == 5
    assert analysis.relative_priority[0]["main_stat"] == "物理伤害"
    assert analysis.relative_priority[0]["main_stat_target"] == "生命值百分比"
    assert analysis.relative_priority[0]["main_stat_issue"] == "偏离目标"


def test_custom_set_plan_can_model_fixed_two_two_two():
    game = load_game("zzz")
    character = _billy()
    custom_plan = SetPlan(
        id="test_2_2_2",
        name="云岿如我 2 + 啄木鸟电音 2 + 激素朋克 2",
        requirements=[
            SetRequirement(set_name="云岿如我", pieces=2),
            SetRequirement(set_name="啄木鸟电音", pieces=2),
            SetRequirement(set_name="激素朋克", pieces=2),
        ],
    )
    character = character.model_copy(
        update={"set_plans": [custom_plan], "default_set_plan": custom_plan.id}
    )
    pieces = load_current_example("examples/zzz_billy_current.yaml")

    analysis = analyse_current_gear(pieces, game, character)

    assert analysis.set_plan is not None
    assert analysis.set_plan["target_sets"] == ["云岿如我", "啄木鸟电音", "激素朋克"]
    assert [
        {
            "set_name": item["set_name"],
            "required": item["required"],
            "current": item["current"],
            "missing": item["missing"],
        }
        for item in analysis.set_plan["missing"]
    ] == [
        {
            "set_name": "啄木鸟电音",
            "required": 2,
            "current": 0,
            "missing": 2,
        },
        {
            "set_name": "激素朋克",
            "required": 2,
            "current": 0,
            "missing": 2,
        },
    ]
    assert all("算法排序" in item["stage_priority_basis"] for item in analysis.set_plan["missing"])
