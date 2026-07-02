import json

from gear_optimizer.acceptance import (
    acceptance_check_rows,
    acceptance_checks_pass,
    build_first_version_acceptance_report,
    format_acceptance_checks,
    main as acceptance_main,
)
from gear_optimizer.candidate_ev import evaluate_candidate
from gear_optimizer.game_rules import load_characters, load_game, load_probability_models
from gear_optimizer.presets import load_candidate_example, load_current_example
from gear_optimizer.recommendation import (
    resource_decision_text,
    strategy_alignment_text,
)
from gear_optimizer.scoring import analyse_current_gear
from gear_optimizer.strategy import (
    build_strategy_rows,
    build_strategy_sweep,
    strategy_cost_ladder,
    top_strategy,
)
from gear_optimizer.conclusions import (
    candidate_conclusion_rows,
    current_gear_conclusion_rows,
    first_version_acceptance_rows,
    first_version_next_action_rows,
    high_priority_closure_rows,
    resource_guardrail_rows,
    strategy_conclusion_rows,
    today_action_summary_rows,
)


def _billy_context():
    game = load_game("zzz")
    character = next(
        item
        for item in load_characters("zzz")
        if item.id == "zzz_starlight_billy"
    )
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(load_current_example("examples/zzz_billy_current.yaml"), game, character)
    strategy_rows = build_strategy_sweep(game, character, probability_model, analysis)
    return game, character, probability_model, analysis, strategy_rows


def test_first_version_answers_current_gear_and_resource_questions():
    game, character, probability_model, analysis, strategy_rows = _billy_context()
    current_best = top_strategy(strategy_rows, "current_relative_gain_score")
    long_term_best = top_strategy(strategy_rows, "long_term_value_score")
    tuner_best = top_strategy(
        [row for row in strategy_rows if row.fixed_main_stat and row.expected_tuners > 0],
        "current_relative_gain_score",
    )
    core_best = top_strategy(
        [row for row in strategy_rows if row.expected_cores > 0],
        "current_relative_gain_score",
    )
    tuner_text, core_text = resource_decision_text(
        tuner_best,
        core_best,
        long_term_best,
    )

    assert analysis.weakest_position == 6
    assert analysis.weakest_position_name == "6号位"
    assert analysis.relative_priority[0]["position"] == 6
    assert current_best is not None
    assert current_best.target_position == 6
    assert current_best.target_set == "折枝剑歌"
    assert current_best.target_set_options == ["折枝剑歌"]
    assert current_best.fixed_position
    assert long_term_best is not None
    assert long_term_best.target_position == 5
    assert long_term_best.target_main_stat == "物理伤害"
    assert "存在冲突" in strategy_alignment_text(current_best, long_term_best)
    assert "校音器：先别急用" in tuner_text
    assert "共鸣核：先留" in core_text

    target_rows = build_strategy_rows(
        game,
        character,
        probability_model,
        analysis,
        target_position=6,
        target_main_stat="生命值百分比",
        fixed_substats=["暴击率", "暴击伤害"],
        target_set=current_best.target_set,
        target_set_options=current_best.target_set_options,
    )
    cost_ladder = strategy_cost_ladder(target_rows)
    assert [row["stage"] for row in cost_ladder] == [1, 2, 3, 4, 5]
    assert cost_ladder[0]["expected_tuners"] == 0
    assert cost_ladder[1]["expected_tuners"] == 0
    assert cost_ladder[2]["expected_tuners"] > cost_ladder[1]["expected_tuners"]
    assert cost_ladder[3]["expected_cores"] > cost_ladder[2]["expected_cores"]
    assert cost_ladder[4]["expected_cores"] > cost_ladder[3]["expected_cores"]


def test_first_version_answers_candidate_upgrade_questions():
    game, character, _probability_model, _analysis, _strategy_rows = _billy_context()

    slot5 = evaluate_candidate(
        load_candidate_example("examples/zzz_candidate_slot5.yaml"),
        game,
        character,
    )
    slot4 = evaluate_candidate(
        load_candidate_example("examples/zzz_candidate_slot4.yaml"),
        game,
        character,
    )

    assert slot5.current_effective_rolls == 2
    assert slot5.remaining_roll_events == 4
    assert slot5.per_event_hit_probabilities == [0.5, 0.5, 0.5, 0.5]
    assert slot5.final_expected_effective_rolls == 4
    assert slot5.recommendation == "继续"

    assert slot4.current_effective_rolls == 1
    assert slot4.remaining_roll_events == 4
    assert slot4.per_event_hit_probabilities == [0.25, 0.25, 0.25, 0.25]
    assert slot4.final_expected_effective_rolls == 2
    assert slot4.recommendation == "仅过渡"


def test_first_version_final_acceptance_questions_have_answer_rows():
    game, character, probability_model, analysis, strategy_rows = _billy_context()
    current_best = top_strategy(strategy_rows, "current_relative_gain_score")
    long_term_best = top_strategy(strategy_rows, "long_term_value_score")
    tuner_best = top_strategy(
        [row for row in strategy_rows if row.fixed_main_stat and row.expected_tuners > 0],
        "current_relative_gain_score",
    )
    core_best = top_strategy(
        [row for row in strategy_rows if row.expected_cores > 0],
        "current_relative_gain_score",
    )
    current_rows = current_gear_conclusion_rows(
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
        include_strategy_resources=True,
    )
    strategy_rows_for_questions = strategy_conclusion_rows(
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
        include_strategy_resources=True,
    )
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    candidate_result = evaluate_candidate(candidate, game, character)
    candidate_rows = candidate_conclusion_rows(
        game,
        character,
        candidate,
        candidate_result,
        analysis,
    )
    questions = {
        row["问题"]: row["结论"]
        for row in current_rows + strategy_rows_for_questions + candidate_rows
    }

    assert questions["当前哪件最弱"] == "6号位"
    assert questions["这个胚子值不值得继续"] == "继续"
    assert "6号位" in questions["现在应该固定几号位"]
    assert "校音器：先别急用" in questions["校音器该不该用"]
    assert "共鸣核：先留" in questions["共鸣核该不该留"]
    assert "存在冲突" in questions["长期和当前是否冲突"]


def test_first_version_acceptance_rows_unify_current_candidate_and_strategy():
    game, character, probability_model, analysis, strategy_rows = _billy_context()
    current_best = top_strategy(strategy_rows, "current_relative_gain_score")
    long_term_best = top_strategy(strategy_rows, "long_term_value_score")
    tuner_best = top_strategy(
        [row for row in strategy_rows if row.fixed_main_stat and row.expected_tuners > 0],
        "current_relative_gain_score",
    )
    core_best = top_strategy(
        [row for row in strategy_rows if row.expected_cores > 0],
        "current_relative_gain_score",
    )
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    candidate_result = evaluate_candidate(candidate, game, character)

    rows = first_version_acceptance_rows(
        game,
        character,
        candidate,
        candidate_result,
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
        include_strategy_resources=True,
    )
    by_question = {row["验收问题"]: row for row in rows}

    assert list(by_question) == [
        "我当前 6 件盘哪件最差？",
        "这个新胚子还值不值得强化？",
        "现在应该固定几号位？",
        "校音器该不该用？",
        "共鸣核该不该留？",
        "长期最优和当前提升是否冲突？",
    ]
    assert by_question["我当前 6 件盘哪件最差？"]["当前答案"] == "6号位"
    assert by_question["这个新胚子还值不值得强化？"]["当前答案"] == "继续"
    assert by_question["这个新胚子还值不值得强化？"]["入口"] == "候选胚子评估"
    assert "6号位" in by_question["现在应该固定几号位？"]["当前答案"]
    assert "校音器：先别急用" in by_question["校音器该不该用？"]["当前答案"]
    assert "共鸣核：先留" in by_question["共鸣核该不该留？"]["当前答案"]
    assert "存在冲突" in by_question["长期最优和当前提升是否冲突？"]["当前答案"]


def test_high_priority_closure_rows_cover_user_feedback_items():
    rows = high_priority_closure_rows()
    by_number = {row["编号"]: row for row in rows}

    assert len(rows) == 12
    assert "PySide6 原生桌面入口" in by_number["1"]["闭环状态"]
    assert "Windows exe 打包" in by_number["1"]["闭环状态"]
    assert "不再保留 Web 入口" in by_number["1"]["证据"]
    assert "目标套装方案" in by_number["2"]["验收入口"]
    assert "副词条优先级" in by_number["4"]["验收入口"]
    assert "2x3 矩阵" in by_number["6"]["闭环状态"]
    assert "下排 4/5/6" in by_number["6"]["证据"]
    assert "保存当前盘面" in by_number["7"]["验收入口"]
    assert "保存入口前置" in by_number["7"]["证据"]
    assert "实时更新" in by_number["8"]["闭环状态"]
    assert "盘面状态摘要" in by_number["8"]["验收入口"]
    assert "固定副属性省母盘阶梯" in by_number["10"]["闭环状态"]
    assert "不做资源折算" in by_number["10"]["证据"]
    assert "指定目标 100%" in by_number["11"]["证据"]
    assert "随机/固定都会把新盘加入库存后重求最优组合" in by_number["12"]["证据"]
    assert "固定主属性和固定副属性只展示省母盘、校音器、共鸣核" in by_number["12"]["证据"]


def test_first_version_next_action_rows_include_candidate_upgrade_action():
    game, character, probability_model, analysis, strategy_rows = _billy_context()
    current_best = top_strategy(strategy_rows, "current_relative_gain_score")
    long_term_best = top_strategy(strategy_rows, "long_term_value_score")
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    candidate_result = evaluate_candidate(candidate, game, character)

    rows = first_version_next_action_rows(
        game,
        character,
        candidate,
        candidate_result,
        analysis,
        current_best,
        long_term_best,
    )
    by_action = {row["action"]: row for row in rows}

    assert "先补 2 件套" in by_action
    assert "保留长期目标" in by_action
    assert "继续强化候选" in by_action
    assert by_action["继续强化候选"]["target"] == "云岿如我 5号位 物理伤害"
    assert by_action["继续强化候选"]["entry"] == "候选胚子评估 -> 下一跳止损卡 / 最终分布图"
    assert by_action["继续强化候选"]["tuning_scope"] == "候选胚子强化"
    assert "强化材料按节点投入" in by_action["继续强化候选"]["resource_hint"]


def test_today_action_summary_rows_surface_plain_next_actions():
    game, character, probability_model, analysis, strategy_rows = _billy_context()
    current_best = top_strategy(strategy_rows, "current_relative_gain_score")
    long_term_best = top_strategy(strategy_rows, "long_term_value_score")
    tuner_best = top_strategy(
        [row for row in strategy_rows if row.fixed_main_stat and row.expected_tuners > 0],
        "current_relative_gain_score",
    )
    core_best = top_strategy(
        [row for row in strategy_rows if row.expected_cores > 0],
        "current_relative_gain_score",
    )
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    result = evaluate_candidate(candidate, game, character)

    rows = today_action_summary_rows(
        game,
        character,
        candidate,
        result,
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
    )
    by_topic = {row["主题"]: row for row in rows}

    assert [row["优先级"] for row in rows] == ["1", "2", "3", "4"]
    assert by_topic["先刷/调律"]["动作"] == "先补 2 件套"
    assert "折枝剑歌 6号位" in by_topic["先刷/调律"]["目标"]
    assert by_topic["特殊资源"]["动作"] == "校音器先留；共鸣核默认保留"
    assert "校音器：先别急用" in by_topic["特殊资源"]["理由"]
    assert by_topic["候选胚子"]["动作"] == "强化到 +6"
    assert "当前建议：继续" in by_topic["候选胚子"]["理由"]
    assert "保留长期目标" in by_topic["长期提醒"]["动作"]
    assert "云岿如我 5号位" in by_topic["长期提醒"]["目标"]


def test_today_action_summary_allows_tuner_when_target_is_aligned_and_high_value():
    game, character, probability_model, analysis, strategy_rows = _billy_context()
    tuner_best = top_strategy(
        [row for row in strategy_rows if row.fixed_main_stat and row.expected_tuners > 0],
        "current_relative_gain_score",
    )
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    result = evaluate_candidate(candidate, game, character)

    rows = today_action_summary_rows(
        game,
        character,
        candidate,
        result,
        analysis,
        tuner_best,
        tuner_best,
        tuner_best,
        None,
    )
    by_topic = {row["主题"]: row for row in rows}

    assert by_topic["特殊资源"]["动作"] == "校音器可考虑；共鸣核默认保留"
    assert "校音器：可以用在" in by_topic["特殊资源"]["理由"]


def test_resource_guardrail_rows_state_resource_boundaries():
    game, character, probability_model, analysis, strategy_rows = _billy_context()
    current_best = top_strategy(strategy_rows, "current_relative_gain_score")
    long_term_best = top_strategy(strategy_rows, "long_term_value_score")
    tuner_best = top_strategy(
        [row for row in strategy_rows if row.fixed_main_stat and row.expected_tuners > 0],
        "current_relative_gain_score",
    )
    core_best = top_strategy(
        [row for row in strategy_rows if row.expected_cores > 0],
        "current_relative_gain_score",
    )

    rows = resource_guardrail_rows(current_best, long_term_best, tuner_best, core_best)
    by_resource = {row["资源/操作"]: row for row in rows}

    assert by_resource["随机位置母盘"]["默认动作"] == "只顺手筛"
    assert "1/6" in by_resource["随机位置母盘"]["当前结论"]
    assert by_resource["固定位置母盘"]["默认动作"] == "当前补弱首选"
    assert "折枝剑歌 6号位" in by_resource["固定位置母盘"]["当前结论"]
    assert by_resource["校音器"]["默认动作"] == "先留"
    assert "只用于固定主属性" in by_resource["校音器"]["启用条件"]
    assert "校音器：先别急用" in by_resource["校音器"]["当前结论"]
    assert by_resource["共鸣核"]["默认动作"] == "默认保留"
    assert "固定副属性" in by_resource["共鸣核"]["启用条件"]


def test_first_version_acceptance_report_builder_uses_default_billy_sample():
    report = build_first_version_acceptance_report()

    assert "# 绝区零 星徽·比利 第一版验收总览" in report
    assert "| 我当前 6 件盘哪件最差？ | 6号位 |" in report
    assert "| 这个新胚子还值不值得强化？ | 继续 |" in report
    assert "校音器该不该用？" in report
    assert "长期最优和当前提升是否冲突？" in report
    assert "## 今日行动摘要" in report
    assert "| 1 | 先刷/调律 | 先补 2 件套 | 折枝剑歌 6号位" in report
    assert "| 2 | 特殊资源 | 校音器先留；共鸣核默认保留 | 校音器 / 共鸣核 |" in report
    assert "| 3 | 候选胚子 | 强化到 +6 | 云岿如我 5号位 物理伤害 |" in report
    assert "| 4 | 长期提醒 | 保留长期目标；特殊资源不要追短期弱位 | 固定位置 + 固定主属性：云岿如我 5号位，物理伤害，不固定副属性。 |" in report
    assert "## 高优先级问题闭环" in report
    assert "| 12 | 结果页需要调律操作期望管理 | 已增加随机/固定位置收益表、固定主属性和固定副属性省母盘阶梯 |" in report
    assert "## 下一步操作卡" in report
    assert "先补 2 件套" in report
    assert "## 资源投入守则" not in report
    assert "## 当前/长期投入对照" not in report
    assert "| 3 | 继续强化候选 | 候选胚子评估 -> 下一跳止损卡 / 最终分布图 | 云岿如我 5号位 物理伤害 | 候选胚子强化 |" in report
    assert "## 当前调律期望管理" in report
    assert "### 随机 vs 固定位置收益效率" in report
    assert "| 随机位置 | 云岿如我 | 1-6 随机 |" in report
    assert "| 固定位置 | 折枝剑歌 | 6号位 |" in report
    assert "### 固定主属性省母盘阶梯" in report
    assert "| 6号位 | 1 | 生命值百分比 | 1.0 | 1.0 | +1 | 2.0 |" in report
    assert "### 固定副属性省母盘阶梯" in report
    assert "| 6号位 | 1 | 生命值百分比 | 暴击率 + 暴击伤害 | 1.0 | +1 |" in report
    assert "### 胚子挡位概率解释" in report
    assert "| 5号位 | 3 | 物理伤害 | 4 | 4中3 |" in report
    assert "校音器折算" not in report
    assert "## 候选下一跳止损卡" in report
    assert "| 当前动作 | 强化到 +6 |" in report


def test_acceptance_check_rows_validate_generated_report_markers():
    report = build_first_version_acceptance_report()
    rows = acceptance_check_rows(report)
    by_id = {row["id"]: row for row in rows}

    assert acceptance_checks_pass(rows)
    assert by_id["six_core_questions"]["状态"] == "ok"
    assert by_id["candidate_stop_loss"]["状态"] == "ok"
    assert by_id["today_action_summary"]["状态"] == "ok"
    assert "| 1 | 先刷/调律 | 先补 2 件套 |" in by_id["today_action_summary"]["证据"]
    assert by_id["position_efficiency"]["状态"] == "ok"
    assert by_id["fixed_main_ladder"]["状态"] == "ok"
    assert by_id["fixed_substat_ladder"]["状态"] == "ok"
    assert by_id["initial_tier_explanation"]["状态"] == "ok"
    assert "今日行动摘要" in by_id["today_action_summary"]["检查项"]
    assert "随机 vs 固定位置收益效率" in by_id["position_efficiency"]["检查项"]
    assert "固定主属性省母盘阶梯" in by_id["fixed_main_ladder"]["检查项"]
    assert "固定副属性省母盘阶梯" in by_id["fixed_substat_ladder"]["检查项"]
    assert "胚子挡位概率解释" in by_id["initial_tier_explanation"]["检查项"]
    assert "candidate_stop_loss" in {row["id"] for row in rows}
    assert "ok" in format_acceptance_checks(rows)


def test_acceptance_check_rows_detect_missing_report_markers():
    rows = acceptance_check_rows("# empty")

    assert not acceptance_checks_pass(rows)
    assert {row["状态"] for row in rows} == {"missing"}


def test_acceptance_check_rows_require_business_markers_not_only_section_titles():
    report = "\n".join(
        [
            "## 今日行动摘要",
            "## 下一步操作卡",
            "## 候选下一跳止损卡",
            "## 当前调律期望管理",
            "### 随机 vs 固定位置收益效率",
            "### 固定主属性省母盘阶梯",
            "### 固定副属性省母盘阶梯",
            "### 胚子挡位概率解释",
        ]
    )
    rows = acceptance_check_rows(report)
    by_id = {row["id"]: row for row in rows}

    assert not acceptance_checks_pass(rows)
    assert by_id["today_action_summary"]["状态"] == "missing"
    assert "| 1 | 先刷/调律 | 先补 2 件套 |" in by_id["today_action_summary"]["缺失"]
    assert by_id["position_efficiency"]["状态"] == "missing"
    assert "| 随机位置 | 云岿如我 | 1-6 随机 |" in by_id["position_efficiency"]["缺失"]
    assert by_id["fixed_main_ladder"]["状态"] == "missing"
    assert "| 6号位 | 1 | 生命值百分比 |" in by_id["fixed_main_ladder"]["缺失"]
    assert by_id["fixed_substat_ladder"]["状态"] == "missing"
    assert "| 暴击率 + 暴击伤害 |" in by_id["fixed_substat_ladder"]["缺失"]
    assert by_id["initial_tier_explanation"]["状态"] == "missing"
    assert "| 5号位 | 3 | 物理伤害 | 4 | 4中3 |" in by_id["initial_tier_explanation"]["缺失"]


def test_first_version_acceptance_cli_can_write_report_and_checks(tmp_path, capsys):
    output = tmp_path / "acceptance.md"
    checks = tmp_path / "checks.json"

    assert acceptance_main(["--output", str(output), "--check", "--check-json", str(checks)]) == 0

    captured = capsys.readouterr()
    report = output.read_text(encoding="utf-8")
    assert "Wrote acceptance report:" in captured.out
    assert "Wrote acceptance checks:" in captured.out
    assert "六个核心问题" in captured.out
    assert "ok" in captured.out
    assert str(output) in captured.out
    assert str(checks) in captured.out
    assert checks.exists()
    check_rows = json.loads(checks.read_text(encoding="utf-8"))
    assert all(row["状态"] == "ok" for row in check_rows)
    assert any(row["id"] == "priority_closure" for row in check_rows)
    assert "# 绝区零 星徽·比利 第一版验收总览" in report
    assert "| 这个新胚子还值不值得强化？ | 继续 |" in report
    assert "继续强化候选" in report
    assert "## 当前调律期望管理" in report
