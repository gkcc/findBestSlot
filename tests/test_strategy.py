import pytest

from gear_optimizer.game_rules import load_characters, load_game, load_probability_models
from gear_optimizer.models import GearPiece, SetPlan, SetRequirement, SubstatLine, SubstatPriority
from gear_optimizer.presets import load_current_example
from gear_optimizer.recommendation import (
    resource_decision_text,
    set_plan_next_action_rows,
    set_plan_stage_rows,
    set_plan_step_text,
    strategy_alignment_text,
    strategy_text,
)
from gear_optimizer.scoring import analyse_current_gear
from gear_optimizer.strategy import (
    build_strategy_rows,
    build_strategy_sweep,
    fixed_substat_note,
    strategy_context_rows,
    strategy_cost_ladder,
    top_strategy,
)


def _billy():
    return next(character for character in load_characters("zzz") if character.id == "zzz_starlight_billy")


def test_strategy_table_contains_five_comparable_rows():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)

    rows = build_strategy_rows(
        game,
        character,
        probability_model,
        analysis,
        target_position=6,
        target_main_stat="生命值百分比",
        fixed_substats=["暴击率", "暴击伤害"],
    )

    assert len(rows) == 5
    assert rows[0].strategy_name == "随机位置，不定主属性"
    assert rows[0].probability_breakdown["set"] == pytest.approx(1.0)
    assert rows[0].probability_breakdown["position"] == pytest.approx(1 / 6)
    assert rows[0].probability_breakdown["main_stat"] == pytest.approx(1.0)
    assert rows[0].probability_breakdown["substats"] == pytest.approx(1.0)
    assert rows[0].candidate_probability == pytest.approx(1 / 6)
    assert rows[0].expected_mother_disks == pytest.approx(18.0)
    assert rows[4].probability_breakdown["main_stat"] == pytest.approx(1.0)
    assert rows[4].probability_breakdown["substats"] == pytest.approx(1.0)
    assert rows[4].candidate_probability == pytest.approx(
        rows[4].probability_breakdown["set"]
        * rows[4].probability_breakdown["position"]
        * rows[4].probability_breakdown["main_stat"]
        * rows[4].probability_breakdown["substats"]
    )
    assert all(row.candidate_probability > 0 for row in rows)
    assert top_strategy(rows, "current_relative_gain_score") is not None


def test_strategy_cost_ladder_explains_incremental_resource_costs():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)
    rows = build_strategy_rows(
        game,
        character,
        probability_model,
        analysis,
        target_position=6,
        target_main_stat="生命值百分比",
        fixed_substats=["暴击率", "暴击伤害"],
    )

    ladder = strategy_cost_ladder(rows)

    assert len(ladder) == 5
    assert ladder[0]["locked_scope"] == "不锁定位置/主属性/副属性"
    assert ladder[0]["target_set_scope"] == "云岿如我"
    assert ladder[1]["locked_scope"] == "位置"
    assert ladder[1]["probability_multiplier_vs_previous"] == pytest.approx(6.0)
    assert ladder[1]["mother_disk_multiplier_vs_previous"] == pytest.approx(1 / 3)
    assert "母盘期望下降" in ladder[1]["incremental_note"]
    assert ladder[2]["locked_scope"] == "位置 + 主属性"
    assert ladder[2]["mother_disk_multiplier_vs_previous"] == pytest.approx(1.0)
    assert "新增校音器" in ladder[2]["incremental_note"]
    assert "新增共鸣核" in ladder[3]["incremental_note"]
    assert ladder[4]["locked_scope"] == "位置 + 主属性 + 2 个副属性"


def test_strategy_rows_can_omit_fixed_substat_paths_for_normal_decisions():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)
    rows = build_strategy_rows(
        game,
        character,
        probability_model,
        analysis,
        target_position=6,
        target_main_stat="生命值百分比",
        fixed_substats=[],
        include_fixed_substat_strategies=False,
    )

    assert [row.strategy_name for row in rows] == [
        "随机位置，不定主属性",
        "固定位置，不定主属性",
        "固定位置 + 固定主属性",
    ]
    assert all(row.expected_cores == 0 for row in rows)
    assert all(not row.fixed_substats for row in rows)


def test_strategy_cost_ladder_keeps_flexible_set_scope_visible():
    game = load_game("zzz")
    character = _billy().model_copy(update={"default_set_plan": "cloud_4_flex_2"})
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)
    rows = build_strategy_sweep(game, character, probability_model, analysis)
    current_best = top_strategy(rows, "current_relative_gain_score")
    target_rows = [
        row
        for row in rows
        if current_best is not None
        and row.target_set == current_best.target_set
        and row.target_position == current_best.target_position
    ]

    ladder = strategy_cost_ladder(target_rows)

    assert ladder
    assert ladder[0]["target_set_scope"] == "啄木鸟电音 / 河豚电音 / 激素朋克"
    assert ladder[0]["set_probability_source"] == "3 个可接受套装合并，套装概率 100.0%"
    assert ladder[0]["candidate_probability"] == pytest.approx(1 / 6)


def test_strategy_context_rows_explain_active_set_plan_groups():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)

    rows = strategy_context_rows(game, character, probability_model, analysis)

    assert rows[0] == {
        "项目": "当前套装方案",
        "当前值": "云岿如我 4 + 折枝剑歌 2",
        "策略影响": "未满足；策略扫描按方案拆分套装组，并把缺口阶段加入当前提升评分。",
    }
    assert any(
        row["项目"] == "套装组 1"
        and row["当前值"] == "云岿如我：4/4，溢出 2，缺 0"
        and row["策略影响"] == "单套装 100.0%"
        for row in rows
    )
    assert any(
        row["项目"] == "套装组 2"
        and row["当前值"] == "折枝剑歌：0/2，缺 2"
        and row["策略影响"] == "单套装 100.0%"
        for row in rows
    )
    priority_row = next(row for row in rows if row["项目"] == "当前优先阶段")
    assert "2 件套 -> 折枝剑歌" in priority_row["当前值"]
    assert "算法排序" in priority_row["策略影响"]
    assert any(
        row["项目"] == "主属性倾向"
        and "4号位：暴击率 / 暴击伤害" in row["当前值"]
        and "6号位：生命值百分比" in row["当前值"]
        for row in rows
    )
    assert any(
        row["项目"] == "副词条优先级"
        and "核心：暴击率 > 暴击伤害 > 生命值百分比" in row["当前值"]
        and "可用：" not in row["当前值"]
        and "按配置顺位排序" in row["策略影响"]
        for row in rows
    )


def test_strategy_context_rows_for_unrestricted_plan_skip_set_stages():
    game = load_game("zzz")
    plan = SetPlan(id="unrestricted", name="完全不限", requirements=[])
    character = _billy().model_copy(
        update={"set_plans": [plan], "default_set_plan": plan.id}
    )
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)

    rows = strategy_context_rows(game, character, probability_model, analysis)

    assert rows[0] == {
        "项目": "当前套装方案",
        "当前值": "完全不限",
        "策略影响": "不限套装，调律只看位置、主属性和副词条质量。",
    }
    assert {row["项目"] for row in rows} == {
        "当前套装方案",
        "主属性倾向",
        "副词条优先级",
    }


def test_strategy_can_target_missing_set_plan_piece():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)

    cloud_rows = build_strategy_rows(
        game,
        character,
        probability_model,
        analysis,
        target_position=6,
        target_main_stat="生命值百分比",
        fixed_substats=["暴击率", "暴击伤害"],
        target_set="云岿如我",
    )
    branch_rows = build_strategy_rows(
        game,
        character,
        probability_model,
        analysis,
        target_position=6,
        target_main_stat="生命值百分比",
        fixed_substats=["暴击率", "暴击伤害"],
        target_set="折枝剑歌",
    )

    assert branch_rows[0].target_set == "折枝剑歌"
    assert branch_rows[0].current_relative_gain_score > cloud_rows[0].current_relative_gain_score


def test_strategy_sweep_groups_flexible_set_options_for_probability():
    game = load_game("zzz")
    character = _billy().model_copy(update={"default_set_plan": "cloud_4_flex_2"})
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)

    rows = build_strategy_sweep(game, character, probability_model, analysis)
    flex_rows = [
        row
        for row in rows
        if row.target_set == "啄木鸟电音 / 河豚电音 / 激素朋克"
        and row.target_position == 6
        and row.strategy_name == "固定位置，不定主属性"
    ]

    assert flex_rows
    assert flex_rows[0].target_set_options == ["啄木鸟电音", "河豚电音", "激素朋克"]
    assert flex_rows[0].probability_breakdown["set"] == pytest.approx(1.0)
    assert flex_rows[0].candidate_probability == pytest.approx(1.0)


def test_strategy_prefers_filling_set_gap_on_weak_piece_over_excellent_piece():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
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

    slot5_rows = build_strategy_rows(
        game,
        character,
        probability_model,
        analysis,
        target_position=5,
        target_main_stat="物理伤害",
        fixed_substats=["暴击率", "暴击伤害"],
        target_set="折枝剑歌",
    )
    slot6_rows = build_strategy_rows(
        game,
        character,
        probability_model,
        analysis,
        target_position=6,
        target_main_stat="生命值百分比",
        fixed_substats=["暴击率", "暴击伤害"],
        target_set="折枝剑歌",
    )

    assert (
        top_strategy(slot5_rows, "current_relative_gain_score").current_relative_gain_score
        > top_strategy(slot6_rows, "current_relative_gain_score").current_relative_gain_score
    )


def test_strategy_current_priority_ignores_locked_position():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    pieces[5] = pieces[5].model_copy(update={"locked": True})
    analysis = analyse_current_gear(pieces, game, character)

    rows = build_strategy_sweep(game, character, probability_model, analysis)
    slot6_rows = [row for row in rows if row.target_position == 6]
    current_best = top_strategy(rows, "current_relative_gain_score")

    assert slot6_rows
    assert all(row.current_relative_gain_score == 0 for row in slot6_rows)
    assert current_best is not None
    assert current_best.target_position != 6


def test_strategy_default_substats_follow_character_priority_order():
    game = load_game("zzz")
    character = _billy().model_copy(
        update={
            "substat_priority": SubstatPriority(
                core=["生命值百分比", "暴击率"],
                usable=["暴击伤害"],
            ),
            "effective_substats": {
                "暴击伤害": 1.0,
                "生命值百分比": 1.0,
                "暴击率": 1.0,
            }
        }
    )
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)

    rows = build_strategy_rows(
        game,
        character,
        probability_model,
        analysis,
        target_position=5,
        target_main_stat="物理伤害",
    )

    assert rows[3].fixed_substats == ["生命值百分比"]
    assert rows[4].fixed_substats == ["生命值百分比", "暴击率"]
    assert rows[3].fixed_substat_details == [
        {"stat": "生命值百分比", "priority": "核心", "priority_rank": 1}
    ]
    assert fixed_substat_note(rows[4]) == "生命值百分比（核心）、暴击率（核心）"


def test_strategy_fixed_substat_note_uses_core_priority_from_template():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)

    rows = build_strategy_rows(
        game,
        character,
        probability_model,
        analysis,
        target_position=5,
        target_main_stat="物理伤害",
        fixed_substats=["生命值百分比", "暴击率"],
    )

    assert fixed_substat_note(rows[4]) == "生命值百分比（核心）、暴击率（核心）"
    assert rows[4].fixed_substat_details[0]["priority"] == "核心"
    assert rows[4].fixed_substat_details[1]["priority"] == "核心"


def test_strategy_values_fixing_wrong_main_stat():
    game = load_game("zzz")
    character = _billy().model_copy(
        update={"preferred_main_stats": {"5": ["生命值百分比"]}}
    )
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(
        load_current_example("examples/zzz_billy_current.yaml"),
        game,
        character,
    )

    rows = build_strategy_rows(
        game,
        character,
        probability_model,
        analysis,
        target_position=5,
        target_main_stat="生命值百分比",
        fixed_substats=["暴击率", "暴击伤害"],
        target_set="云岿如我",
    )

    fixed_position = rows[1]
    fixed_main = rows[2]

    assert fixed_position.strategy_name == "固定位置，不定主属性"
    assert fixed_main.strategy_name == "固定位置 + 固定主属性"
    assert fixed_main.current_relative_gain_score > fixed_position.current_relative_gain_score


def test_global_strategy_sweep_recommends_current_slot_and_long_term_target():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)

    rows = build_strategy_sweep(game, character, probability_model, analysis)
    current_best = top_strategy(rows, "current_relative_gain_score")
    long_term_best = top_strategy(rows, "long_term_value_score")

    assert len(rows) == 2 * 33
    assert current_best is not None
    assert current_best.target_position == 6
    assert current_best.fixed_position
    assert current_best.target_set == "折枝剑歌"
    assert current_best.target_set_options == ["折枝剑歌"]
    assert long_term_best is not None
    assert long_term_best.target_position == 5
    assert long_term_best.target_main_stat == "物理伤害"
    assert long_term_best.fixed_substats == []


def test_strategy_sweep_scans_all_preferred_main_stats_for_position():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)

    rows = build_strategy_sweep(
        game,
        character,
        probability_model,
        analysis,
        target_sets=["云岿如我"],
    )
    slot4_fixed_main_rows = [
        row
        for row in rows
        if row.target_position == 4
        and row.fixed_main_stat
        and row.strategy_name == "固定位置 + 固定主属性"
    ]
    slot4_unfixed_rows = [
        row
        for row in rows
        if row.target_position == 4
        and not row.fixed_main_stat
    ]

    assert {row.target_main_stat for row in slot4_fixed_main_rows} == {"暴击率", "暴击伤害"}
    assert len(slot4_unfixed_rows) == 2


def test_strategy_alignment_text_reports_conflict_and_alignment():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)
    rows = build_strategy_sweep(game, character, probability_model, analysis)
    current_best = top_strategy(rows, "current_relative_gain_score")
    long_term_best = top_strategy(rows, "long_term_value_score")

    conflict_text = strategy_alignment_text(current_best, long_term_best)
    aligned_text = strategy_alignment_text(current_best, current_best)

    assert "存在冲突" in conflict_text
    assert "6号位" in conflict_text
    assert "5号位" in conflict_text
    assert "基本一致" in aligned_text


def test_strategy_text_uses_character_notes_instead_of_hardcoded_character_branch():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)
    rows = build_strategy_sweep(game, character, probability_model, analysis)
    current_best = top_strategy(rows, "current_relative_gain_score")
    long_term_best = top_strategy(rows, "long_term_value_score")

    current_text, long_text = strategy_text(current_best, long_term_best, game, character)
    _no_notes_current, no_notes_long = strategy_text(
        current_best,
        long_term_best,
        game,
        character.model_copy(update={"id": "custom_character", "name": "自定义角色", "notes": None}),
    )

    assert "当前相对提升最优：" in current_text
    assert current_best.strategy_name in current_text
    assert "折枝剑歌" in current_text
    assert "单套装 100.0%" in current_text
    assert character.notes in long_text
    assert "对星徽·比利来说" not in no_notes_long


def test_set_plan_step_text_prioritizes_flexible_two_piece_after_core_four():
    game = load_game("zzz")
    character = _billy()
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)

    text = set_plan_step_text(analysis)

    assert "先补 2 件套" in text
    assert "折枝剑歌" in text
    assert "6 号位" in text


def test_set_plan_next_action_rows_turn_stage_order_into_action_plan():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)
    rows = build_strategy_sweep(game, character, probability_model, analysis)
    current_best = top_strategy(rows, "current_relative_gain_score")
    long_term_best = top_strategy(rows, "long_term_value_score")

    actions = set_plan_next_action_rows(game, analysis, current_best, long_term_best)

    assert actions[0]["action"] == "先补 2 件套"
    assert "套装阶段拆解" in actions[0]["entry"]
    assert actions[0]["target"] == "折枝剑歌 6号位 （云岿如我 -> 折枝剑歌）"
    assert actions[0]["tuning_scope"] == "固定位置，不定主属性"
    assert "母盘和固定位置自然筛" in actions[0]["resource_hint"]
    assert "2 件套缺 2 件" in actions[0]["reason"]
    assert "让位压力" in actions[0]["reason"]
    assert actions[1]["action"] == "保留长期目标"
    assert "长期目标" in actions[1]["entry"]
    assert actions[1]["target"] == "云岿如我 5号位 物理伤害"
    assert "校音器" in actions[1]["resource_hint"]
    assert "存在冲突" in actions[1]["reason"]


def test_set_plan_stage_rows_explain_first_missing_stage_and_replacement():
    game = load_game("zzz")
    character = _billy()
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)

    rows = set_plan_stage_rows(game, analysis)

    assert rows[0]["stage"] == "2 件套"
    assert rows[0]["action"] == "优先补齐"
    assert rows[0]["target"] == "折枝剑歌"
    assert rows[0]["priority_score"] > rows[1]["priority_score"]
    assert "算法排序" in rows[0]["algorithm_basis"]
    assert "缺口 2 件" in rows[0]["algorithm_basis"]
    assert "可让位压力" in rows[0]["algorithm_basis"]
    assert rows[0]["replacement"] == "6号位 -> 折枝剑歌"
    assert "让位压力" in rows[0]["basis"]
    assert rows[1]["stage"] == "核心 4 件"
    assert rows[1]["action"].startswith("已满足")


def test_set_plan_next_action_rows_pause_resources_on_lock_conflict():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    pieces[0] = pieces[0].model_copy(update={"set_name": "摇摆爵士", "locked": True})
    pieces[1] = pieces[1].model_copy(update={"set_name": "摇摆爵士", "locked": True})
    analysis = analyse_current_gear(pieces, game, character)
    rows = build_strategy_sweep(game, character, probability_model, analysis)

    actions = set_plan_next_action_rows(
        game,
        analysis,
        top_strategy(rows, "current_relative_gain_score"),
        top_strategy(rows, "long_term_value_score"),
    )

    assert actions[0]["action"] == "先处理锁定盘"
    assert "目标套装方案" in actions[0]["entry"]
    assert actions[0]["target"] == "云岿如我 4 + 折枝剑歌 2"
    assert actions[0]["tuning_scope"] == "暂停套装调律投入"
    assert actions[0]["resource_hint"] == "先不要为当前套装方案消耗校音器或共鸣核。"
    assert "锁定冲突" in actions[0]["reason"]


def test_set_plan_stage_replacement_ignores_locked_weak_piece():
    game = load_game("zzz")
    character = _billy()
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    pieces[5] = pieces[5].model_copy(update={"locked": True})
    analysis = analyse_current_gear(pieces, game, character)

    rows = set_plan_stage_rows(game, analysis)
    stage_replacement = analysis.set_plan["missing"][0]["stage_replacement"]

    assert rows[0]["stage"] == "2 件套"
    assert stage_replacement["position"] != 6
    assert rows[0]["replacement"] != "6号位 -> 折枝剑歌"
    assert "可让位压力" in rows[0]["algorithm_basis"]


def test_set_plan_step_text_prioritizes_core_four_when_missing():
    game = load_game("zzz")
    character = _billy().model_copy(update={"default_set_plan": "cloud_4_flex_2"})
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    for index, set_name in enumerate(
        ["云岿如我", "云岿如我", "啄木鸟电音", "啄木鸟电音", "河豚电音", "河豚电音"]
    ):
        pieces[index] = pieces[index].model_copy(update={"set_name": set_name})
    analysis = analyse_current_gear(pieces, game, character)

    text = set_plan_step_text(analysis)

    assert "先补核心 4 件" in text
    assert "云岿如我" in text


def test_set_plan_stage_rows_prioritize_core_four_when_missing():
    game = load_game("zzz")
    character = _billy().model_copy(update={"default_set_plan": "cloud_4_flex_2"})
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    for index, set_name in enumerate(
        ["云岿如我", "云岿如我", "啄木鸟电音", "啄木鸟电音", "河豚电音", "河豚电音"]
    ):
        pieces[index] = pieces[index].model_copy(update={"set_name": set_name})
    analysis = analyse_current_gear(pieces, game, character)

    rows = set_plan_stage_rows(game, analysis)

    assert rows[0]["stage"] == "核心 4 件"
    assert rows[0]["target"] == "云岿如我"
    assert rows[0]["action"] == "优先补齐"
    assert rows[0]["missing"] == 2
    assert "核心 4 件 基础" in rows[0]["algorithm_basis"]
    assert rows[1]["action"].startswith("已满足")


def test_set_plan_stage_algorithm_prefers_core_four_when_both_stages_missing():
    game = load_game("zzz")
    plan = SetPlan(
        id="auto_stage_order",
        name="云岿如我 4 + 啄木鸟 2",
        requirements=[
            SetRequirement(
                role="core4",
                set_name="云岿如我",
                pieces=4,
                priority=2,
            ),
            SetRequirement(
                role="flex2",
                set_names=["啄木鸟电音", "河豚电音"],
                pieces=2,
                priority=1,
            ),
        ],
    )
    character = _billy().model_copy(
        update={"set_plans": [plan], "default_set_plan": plan.id}
    )
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    for index, set_name in enumerate(
        ["云岿如我", "云岿如我", "摇摆爵士", "摇摆爵士", "震星迪斯科", "震星迪斯科"]
    ):
        pieces[index] = pieces[index].model_copy(update={"set_name": set_name})
    analysis = analyse_current_gear(pieces, game, character)

    text = set_plan_step_text(analysis)
    rows = set_plan_stage_rows(game, analysis)

    assert "先补核心 4 件" in text
    assert "云岿如我" in text
    assert rows[0]["stage"] == "核心 4 件"
    assert rows[0]["target"] == "云岿如我"
    assert rows[0]["action"] == "优先补齐"
    assert rows[0]["priority_score"] > rows[1]["priority_score"]
    assert "算法排序" in rows[0]["basis"]
    assert rows[1]["stage"] == "2 件套"
    assert rows[1]["action"] == "后续补齐"


def test_set_plan_stage_rows_surface_locked_set_plan_conflict():
    game = load_game("zzz")
    character = _billy()
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    pieces[0] = pieces[0].model_copy(update={"set_name": "摇摆爵士", "locked": True})
    pieces[1] = pieces[1].model_copy(update={"set_name": "摇摆爵士", "locked": True})
    analysis = analyse_current_gear(pieces, game, character)

    text = set_plan_step_text(analysis)
    rows = set_plan_stage_rows(game, analysis)

    assert "锁定冲突" in text
    assert "摇摆爵士" in text
    assert rows[0]["stage"] == "锁定冲突"
    assert rows[0]["missing"] == 2
    assert rows[0]["replacement"] == "解锁 / 改方案 / 接受过渡"
    assert rows[1]["stage"] == "2 件套"
    assert rows[1]["action"] == "优先补齐"


def test_set_plan_step_text_moves_to_stat_quality_when_satisfied():
    game = load_game("zzz")
    character = _billy()
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    pieces[4] = pieces[4].model_copy(update={"set_name": "折枝剑歌"})
    pieces[5] = pieces[5].model_copy(update={"set_name": "折枝剑歌"})
    analysis = analyse_current_gear(pieces, game, character)

    text = set_plan_step_text(analysis)

    assert "已满足" in text
    assert "主属性" in text
    assert "副词条" in text


def test_resource_decision_text_answers_tuner_and_core_usage():
    game = load_game("zzz")
    character = _billy()
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)
    rows = build_strategy_sweep(game, character, probability_model, analysis)
    long_term_best = top_strategy(rows, "long_term_value_score")
    tuner_best = top_strategy(
        [row for row in rows if row.fixed_main_stat and row.expected_tuners > 0],
        "current_relative_gain_score",
    )
    core_best = top_strategy(
        [row for row in rows if row.expected_cores > 0],
        "current_relative_gain_score",
    )

    tuner_text, core_text = resource_decision_text(tuner_best, core_best, long_term_best)
    _same_tuner_text, aligned_core_text = resource_decision_text(
        tuner_best,
        long_term_best,
        long_term_best,
    )

    assert "校音器：先别急用" in tuner_text
    assert "6号位" in tuner_text
    assert "共鸣核：先留" in core_text
    assert "6号位" in core_text
    assert "共鸣核：仍建议保留为主" in aligned_core_text
