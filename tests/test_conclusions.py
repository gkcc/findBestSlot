from gear_optimizer.candidate_ev import evaluate_candidate
from gear_optimizer.conclusions import (
    candidate_conclusion_rows,
    candidate_next_step_rows,
    candidate_outcome_rows,
    current_gear_conclusion_rows,
    probability_model_assumption_rows,
    set_plan_status_text,
    strategy_cost_basis,
    strategy_conclusion_rows,
    strategy_probability_scope,
)
from gear_optimizer.game_rules import load_characters, load_game, load_probability_models
from gear_optimizer.models import CandidatePiece, SubstatLine
from gear_optimizer.presets import load_candidate_example, load_current_example
from gear_optimizer.scoring import analyse_current_gear
from gear_optimizer.strategy import build_strategy_sweep, top_strategy


def _billy_context():
    game = load_game("zzz")
    character = next(
        item
        for item in load_characters("zzz")
        if item.id == "zzz_starlight_billy"
    )
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(
        load_current_example("examples/zzz_billy_current.yaml"),
        game,
        character,
    )
    rows = build_strategy_sweep(game, character, probability_model, analysis)
    return game, character, analysis, rows


def test_candidate_conclusion_rows_answer_upgrade_decision():
    game, character, analysis, _rows = _billy_context()
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    result = evaluate_candidate(candidate, game, character)

    rows = candidate_conclusion_rows(game, character, candidate, result, analysis)
    by_question = {row["问题"]: row for row in rows}

    assert by_question["这个胚子值不值得继续"]["结论"] == "继续"
    assert by_question["候选补位价值"]["结论"] == "长期观察"
    assert "套装判断：符合长期方案" in by_question["候选补位价值"]["依据"]
    assert "主属性命中目标" in by_question["候选补位价值"]["依据"]
    assert by_question["强化观察点"]["结论"] == "+6 看是否命中有效词条"
    assert "命中有效概率 50.0%" in by_question["强化观察点"]["依据"]
    assert "命中配置内有效词条就继续" in by_question["强化观察点"]["依据"]
    assert by_question["替换当前同位置提升"]["结论"] == "暂不优于当前盘"
    assert by_question["套装目标匹配"]["结论"] == "不补规划缺口"
    assert "套装目标：建议让位" in by_question["套装目标匹配"]["依据"]
    assert "目标 折枝剑歌" in by_question["套装目标匹配"]["依据"]
    assert by_question["套装是否符合方案"]["结论"] == "符合长期方案"
    assert "当前优先缺口是 2 件套" in by_question["套装是否符合方案"]["依据"]
    assert "折枝剑歌" in by_question["套装是否符合方案"]["依据"]
    assert "50.0%" in by_question["后续命中概率"]["结论"]
    assert "暴击率" in by_question["当前副词条构成"]["结论"]


def test_candidate_next_step_rows_turn_checkpoint_into_stop_loss_card():
    game, character, analysis, _rows = _billy_context()
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    result = evaluate_candidate(candidate, game, character)

    rows = candidate_next_step_rows(result)
    by_scene = {row["场景"]: row for row in rows}

    assert by_scene["当前动作"]["动作"] == "强化到 +6"
    assert "命中有效概率 50.0%" in by_scene["当前动作"]["依据"]
    assert by_scene["命中有效/高优先级"]["动作"] == "继续强化到下一节点"
    assert by_scene["未命中或歪到低价值"]["动作"] == "暂停观察，等资源宽裕再决定"


def test_candidate_set_status_identifies_current_set_gap_hit():
    game, character, analysis, _rows = _billy_context()
    candidate = CandidatePiece(
        position=6,
        set_name="折枝剑歌",
        main_stat="生命值百分比",
        initial_substat_count=3,
        level=3,
        substats=[
            SubstatLine(stat="暴击率", rolls=0),
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="攻击力", rolls=0),
            SubstatLine(stat="防御力", rolls=0),
        ],
    )
    result = evaluate_candidate(candidate, game, character)

    rows = candidate_conclusion_rows(game, character, candidate, result, analysis)
    by_question = {row["问题"]: row for row in rows}

    assert by_question["套装是否符合方案"]["结论"] == "命中当前缺口"
    assert "当前优先阶段是 2 件套" in by_question["套装是否符合方案"]["依据"]
    assert "候选 折枝剑歌 可以直接补这个缺口" in by_question["套装是否符合方案"]["依据"]
    assert "让位压力" in by_question["套装是否符合方案"]["依据"]
    assert by_question["套装目标匹配"]["结论"] == "命中让位目标"
    assert "套装目标：建议让位" in by_question["套装目标匹配"]["依据"]
    assert "目标 折枝剑歌" in by_question["套装目标匹配"]["依据"]
    assert by_question["候选补位价值"]["结论"] == "当前强补位"
    assert "套装判断：命中当前缺口" in by_question["候选补位价值"]["依据"]
    assert "当前最弱位" in by_question["候选补位价值"]["依据"]


def test_candidate_outcomes_include_slot_plan_match_probability():
    game, character, analysis, _rows = _billy_context()
    matching_candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    matching_result = evaluate_candidate(matching_candidate, game, character)
    off_plan_candidate = matching_candidate.model_copy(update={"set_name": "摇摆爵士"})
    off_plan_result = evaluate_candidate(off_plan_candidate, game, character)

    matching_rows = candidate_outcome_rows(
        game,
        character,
        matching_candidate,
        matching_result,
        analysis,
    )
    off_plan_rows = candidate_outcome_rows(
        game,
        character,
        off_plan_candidate,
        off_plan_result,
        analysis,
    )
    matching = {
        row["目标"]: row
        for row in matching_rows
    }["命中套装目标并超过当前"]
    off_plan = {
        row["目标"]: row
        for row in off_plan_rows
    }["命中套装目标并超过当前"]

    assert matching["概率"] == "-"
    assert "不匹配规划目标" in matching["依据"]
    assert off_plan["概率"] == "-"
    assert "不匹配规划目标" in off_plan["依据"]


def test_candidate_checkpoint_status_handles_add_fourth_line():
    game, character, analysis, _rows = _billy_context()
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

    rows = candidate_conclusion_rows(game, character, candidate, result, analysis)
    by_question = {row["问题"]: row for row in rows}

    assert by_question["强化观察点"]["结论"] == "+3 看补出的第 4 词条"
    assert "下一跳是 +3 先补第 4 个副属性" in by_question["强化观察点"]["依据"]
    assert "命中有效概率" in by_question["强化观察点"]["依据"]


def test_candidate_checkpoint_status_handles_finished_candidate():
    game, character, analysis, _rows = _billy_context()
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml").model_copy(
        update={"level": 15}
    )
    result = evaluate_candidate(candidate, game, character)

    rows = candidate_conclusion_rows(game, character, candidate, result, analysis)
    by_question = {row["问题"]: row for row in rows}

    assert by_question["强化观察点"]["结论"] == "已无强化观察点"
    assert "没有剩余强化事件" in by_question["强化观察点"]["依据"]


def test_candidate_outcome_rows_show_result_probabilities():
    game, character, analysis, _rows = _billy_context()
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    result = evaluate_candidate(candidate, game, character)

    rows = candidate_outcome_rows(game, character, candidate, result, analysis)
    by_target = {row["目标"]: row for row in rows}

    assert set(by_target) == {
        "超过当前同位置",
        "命中套装目标并超过当前",
        "达到角色目标线",
        "达到质量目标线",
        "达到 good 评级",
        "达到 excellent 评级",
    }
    assert by_target["超过当前同位置"]["概率"].endswith("%")
    assert by_target["超过当前同位置"]["概率"] == "31.2%"
    assert by_target["命中套装目标并超过当前"]["概率"] == "-"
    assert by_target["达到角色目标线"]["概率"] == "6.2%"
    assert by_target["达到质量目标线"]["概率"] == "6.2%"
    assert by_target["达到 good 评级"]["概率"] == "68.8%"
    assert "当前 5号位 质量分" in by_target["超过当前同位置"]["依据"]
    assert "最终有效词条次数" in by_target["达到角色目标线"]["依据"]
    assert "最终质量分" in by_target["达到质量目标线"]["依据"]
    assert "最终质量分" in by_target["达到 excellent 评级"]["依据"]


def test_candidate_conclusion_respects_locked_current_position():
    game, character, _analysis, _rows = _billy_context()
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    pieces[4] = pieces[4].model_copy(update={"locked": True})
    analysis = analyse_current_gear(pieces, game, character)
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    result = evaluate_candidate(candidate, game, character)

    conclusion_rows = candidate_conclusion_rows(game, character, candidate, result, analysis)
    by_question = {row["问题"]: row for row in conclusion_rows}
    outcome_rows = candidate_outcome_rows(game, character, candidate, result, analysis)
    by_target = {row["目标"]: row for row in outcome_rows}

    assert result.recommendation == "继续"
    assert by_question["这个胚子值不值得继续"]["结论"] == "仅过渡"
    assert "已标记保留锁定" in by_question["这个胚子值不值得继续"]["依据"]
    assert by_question["候选补位价值"]["结论"] == "仅备用/过渡"
    assert "当前位已锁定" in by_question["候选补位价值"]["依据"]
    assert by_question["替换当前同位置提升"]["结论"] == "当前位已锁定"
    assert by_target["超过当前同位置"]["概率"] == "-"
    assert "已标记保留锁定" in by_target["超过当前同位置"]["依据"]


def test_strategy_conclusion_rows_answer_resource_questions():
    _game, _character, analysis, rows = _billy_context()
    current_best = top_strategy(rows, "current_relative_gain_score")
    long_term_best = top_strategy(rows, "long_term_value_score")
    tuner_best = top_strategy(
        [row for row in rows if row.fixed_main_stat and row.expected_tuners > 0],
        "current_relative_gain_score",
    )
    core_best = top_strategy(
        [row for row in rows if row.expected_cores > 0],
        "current_relative_gain_score",
    )

    conclusion_rows = strategy_conclusion_rows(
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
        include_strategy_resources=True,
    )
    by_question = {row["问题"]: row for row in conclusion_rows}

    assert "6号位" in by_question["现在应该固定几号位"]["结论"]
    assert "5号位" in by_question["长期绝对最优目标"]["结论"]
    assert "校音器：先别急用" in by_question["校音器该不该用"]["结论"]
    assert "共鸣核：先留" in by_question["共鸣核该不该留"]["结论"]
    assert "存在冲突" in by_question["长期和当前是否冲突"]["结论"]
    assert "先补 2 件套" in by_question["套装阶段"]["结论"]
    assert "可接受套装：折枝剑歌" in by_question["现在应该固定几号位"]["依据"]
    assert "单套装 100.0%" in by_question["现在应该固定几号位"]["依据"]
    assert "未固定主属性" in by_question["现在应该固定几号位"]["依据"]
    assert "不代表目标主属性或毕业概率" in by_question["现在应该固定几号位"]["依据"]
    assert "云岿如我 4 + 折枝剑歌 2" in set_plan_status_text(analysis)


def test_strategy_probability_scope_prevents_naked_candidate_probability():
    _game, _character, _analysis, rows = _billy_context()
    current_best = top_strategy(rows, "current_relative_gain_score")
    fixed_main = next(row for row in rows if row.fixed_main_stat and not row.fixed_substats)

    assert current_best is not None
    assert not current_best.fixed_main_stat
    assert "不代表目标主属性或毕业概率" in strategy_probability_scope(current_best)
    assert "当前调律期望管理" in strategy_cost_basis(current_best)
    assert "固定主属性只消耗校音器" in strategy_probability_scope(fixed_main)


def test_current_gear_conclusion_rows_answer_acceptance_questions():
    _game, _character, analysis, rows = _billy_context()
    current_best = top_strategy(rows, "current_relative_gain_score")
    long_term_best = top_strategy(rows, "long_term_value_score")
    tuner_best = top_strategy(
        [row for row in rows if row.fixed_main_stat and row.expected_tuners > 0],
        "current_relative_gain_score",
    )
    core_best = top_strategy(
        [row for row in rows if row.expected_cores > 0],
        "current_relative_gain_score",
    )

    conclusion_rows = current_gear_conclusion_rows(
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
        include_strategy_resources=True,
    )
    by_question = {row["问题"]: row for row in conclusion_rows}

    assert "6号位" in by_question["当前哪件最弱"]["结论"]
    assert "6号位" in by_question["现在优先固定/刷哪里"]["结论"]
    assert "先补 2 件套" in by_question["套装先补 4 还是 2"]["结论"]
    assert "校音器：先别急用" in by_question["校音器该不该用"]["结论"]
    assert "共鸣核：先留" in by_question["共鸣核该不该留"]["结论"]
    assert "存在冲突" in by_question["长期和当前是否冲突"]["结论"]


def test_current_gear_conclusion_distinguishes_effective_rolls_and_weighted_score():
    _game, _character, analysis, rows = _billy_context()
    current_best = top_strategy(rows, "current_relative_gain_score")
    long_term_best = top_strategy(rows, "long_term_value_score")

    conclusion_rows = current_gear_conclusion_rows(
        analysis,
        current_best,
        long_term_best,
        tuner_best=None,
        core_best=None,
    )
    by_question = {row["问题"]: row for row in conclusion_rows}
    basis = by_question["现在优先固定/刷哪里"]["依据"]

    assert "当前有效词条 1" in basis
    assert "质量分 1" in basis


def test_probability_model_assumption_rows_explain_cost_inputs():
    probability_model = load_probability_models("zzz")[0]

    rows = probability_model_assumption_rows(probability_model)
    by_assumption = {row["假设"]: row for row in rows}

    assert by_assumption["目标套装概率"]["当前值"] == "100.0%"
    assert by_assumption["初始 3 词条概率"]["当前值"] == "80.0%"
    assert by_assumption["母盘/随机位置"]["当前值"] == "3"
    assert by_assumption["母盘/固定位置"]["当前值"] == "6"
    assert by_assumption["校音器/固定主属性"]["说明"].startswith("固定主属性")
    assert by_assumption["共鸣核/固定副属性"]["当前值"] == "1"
    assert "校音器折算母盘" not in by_assumption
    assert "共鸣核折算母盘" not in by_assumption
