from gear_optimizer.candidate_ev import evaluate_candidate
from gear_optimizer.game_rules import load_characters, load_game, load_probability_models
from gear_optimizer.presets import load_candidate_example, load_current_example
from gear_optimizer.reporting import (
    candidate_analysis_report_markdown,
    current_analysis_report_markdown,
    first_version_acceptance_report_markdown,
)
from gear_optimizer.scoring import analyse_current_gear
from gear_optimizer.strategy import build_strategy_sweep, top_strategy


def test_current_analysis_report_answers_acceptance_questions():
    game = load_game("zzz")
    character = next(
        item
        for item in load_characters("zzz")
        if item.id == "zzz_starlight_billy"
    )
    probability_model = load_probability_models("zzz")[0]
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    analysis = analyse_current_gear(pieces, game, character)
    rows = build_strategy_sweep(game, character, probability_model, analysis)
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

    report = current_analysis_report_markdown(
        game,
        character,
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
        rows,
        probability_model=probability_model,
        pieces=pieces,
    )

    assert "# 绝区零 星徽·比利 装备词条分析报告" in report
    assert "## 攻略结论" in report
    assert "| 优先级 | 主题 | 行动 | 理由 |" in report
    assert "| 1 | 母盘 |" in report
    assert "| 2 | 当前补弱 |" in report
    assert "最弱：6号位" in report
    assert "| 3 | 特殊资源 | 校音器先留；共鸣核先留 |" in report
    assert "| 4 | 长期目标 |" in report
    assert "## 核算明细" in report
    assert "## 当前装备结论" in report
    assert "| 当前哪件最弱 | 6号位" in report
    assert "| 现在优先固定/刷哪里 |" in report
    assert "## 调律结论" in report
    assert "现在应该固定几号位" in report
    assert "长期绝对最优目标" in report
    assert "## 算法验收速览" not in report
    assert "## 下一步行动清单" not in report
    assert "## 资源投入守则" not in report
    assert "## 当前/长期投入对照" not in report
    assert "## 套装槽位规划" not in report
    assert "## 套装方案对比" not in report
    assert "## 策略上下文" in report
    assert "| 项目 | 当前值 | 策略影响 |" in report
    assert "| 当前套装方案 | 云岿如我 4 + 折枝剑歌 2" in report
    assert "| 套装组 2 | 折枝剑歌：0/2，缺 2" in report
    assert "| 主属性倾向 | 4号位：暴击率 / 暴击伤害" in report
    assert "## 概率与资源假设" in report
    assert "| 假设 | 当前值 | 说明 |" in report
    assert "| 目标套装概率 | 100.0%" in report
    assert "校音器/固定主属性" in report
    assert "## 桌面结果区调律期望管理" in report
    assert "随机/固定都会把新盘加入库存后重求当前套装约束下的最优组合" in report
    assert "### 随机 vs 固定位置收益效率" in report
    assert "| 策略 | 目标套装 | 位置 | 主属性 | 固定副属性 | horizon | immediate_EV | option_EV | horizon_EV | 期望提升 | 代表路径 | 预期搭配 | 互补位 | 套装约束 | 质量提升 | 有效提升 | 母盘/次 | 校音器/次 | 共鸣核/次 | 质量/母盘 | 有效/母盘 | 排序向量/母盘 | 相对随机 |" in report
    assert "| 随机位置 | 云岿如我 | 1-6 随机 |" in report
    assert "| 固定位置 | 折枝剑歌 | 6号位 |" in report
    assert "未满足套装硬约束，不作为当前 horizon 推荐" in report
    assert "### 固定主属性省母盘阶梯" in report
    assert "| 位置 | 当前补弱顺位 | 推荐主属性 | 当前质量分 | 当前有效词条 | 提升目标 | 目标质量分 | 不锁主属性有效提升 | 固定主属性有效提升 | 不锁主属性概率 | 固定主属性概率 | 不锁主属性母盘 | 固定主属性母盘 | 省母盘 | 期望校音器 |" in report
    assert "| 6号位 | 1 | 生命值百分比 | 1.0 | 1.0 | +1 | 2.0 |" in report
    assert "### 固定副属性省母盘阶梯" in report
    assert "| 位置 | 当前补弱顺位 | 主属性 | 锁定副属性 | 当前有效词条 | 提升目标 | 目标质量分 | 固定主属性有效提升 | 锁副属性有效提升 | 固定主属性概率 | 锁副属性概率 | 固定主属性母盘 | 锁副属性母盘 | 省母盘 | 期望校音器 | 期望共鸣核 |" in report
    assert "| 6号位 | 1 | 生命值百分比 | 暴击率 + 暴击伤害 | 1.0 | +1 |" in report
    assert "### 胚子挡位概率解释" in report
    assert "| 5号位 | 3 | 物理伤害 | 4 | 4中3 |" in report
    assert "| 6号位 | 1 | 生命值百分比 | 3 | 3中2 |" in report
    assert "校音器折算" not in report
    assert "折算母盘" not in report
    assert "## 套装阶段拆解" in report
    assert "| 顺序 | 阶段 | 目标 | 进度 | 缺口 | 排序分 | 算法依据 | 当前动作 | 推荐让位 | 依据 |" in report
    assert "| 1 | 2 件套 | 折枝剑歌" in report
    assert "算法排序" in report
    assert "6号位 -> 折枝剑歌" in report
    assert "## 当前推荐目标成本阶梯" in report
    assert "| 阶梯 | 策略名称 | 锁定范围 | 可接受套装 | 套装概率来源 | 候选概率 | 期望母盘 | 期望校音器 | 期望共鸣核 | 固定副词条依据 | 增量解释 |" in report
    assert "折枝剑歌" in report
    assert "单套装 100.0%" in report
    assert "暴击率（核心）" in report
    assert "| 5 | 固定位置 + 固定主属性 + 固定 2 个副属性" in report
    assert "| 位置 | 套装 | 主属性 | 保留 | 有效词条 | 质量分 | 评级 | 替换标签 | 副词条明细 |" in report


def test_candidate_analysis_report_answers_upgrade_questions():
    game = load_game("zzz")
    character = next(
        item
        for item in load_characters("zzz")
        if item.id == "zzz_starlight_billy"
    )
    analysis = analyse_current_gear(
        load_current_example("examples/zzz_billy_current.yaml"),
        game,
        character,
    )
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    result = evaluate_candidate(candidate, game, character)

    report = candidate_analysis_report_markdown(
        game,
        character,
        candidate,
        result,
        analysis,
    )

    assert "# 绝区零 星徽·比利 候选胚子分析报告" in report
    assert "## 候选结论" in report
    assert "这个胚子值不值得继续" in report
    assert "候选补位价值" in report
    assert "套装目标匹配" in report
    assert "不补规划缺口" in report
    assert "长期观察" in report
    assert "强化观察点" in report
    assert "+6 看是否命中有效词条" in report
    assert "## 下一跳止损卡" in report
    assert "| 当前动作 | 强化到 +6 |" in report
    assert "| 未命中或歪到低价值 | 暂停观察，等资源宽裕再决定 |" in report
    assert "替换当前同位置提升" in report
    assert "主属性是否符合目标" in report
    assert "符合长期方案" in report
    assert "当前优先缺口是 2 件套" in report
    assert "后续命中概率" in report
    assert "## 候选结果概率" in report
    assert "| 目标 | 概率 | 依据 |" in report
    assert "超过当前同位置" in report
    assert "达到 good 评级" in report
    assert "## 强化路径" in report
    assert "| +6 | 随机命中已有副属性 | 50.0%" in report
    assert "## 最终有效词条分布" in report
    assert "## 最终质量分布" in report
    assert "- 建议：继续" in report


def test_candidate_report_uses_locked_position_context():
    game = load_game("zzz")
    character = next(
        item
        for item in load_characters("zzz")
        if item.id == "zzz_starlight_billy"
    )
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    pieces[4] = pieces[4].model_copy(update={"locked": True})
    analysis = analyse_current_gear(pieces, game, character)
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    result = evaluate_candidate(candidate, game, character)

    report = candidate_analysis_report_markdown(
        game,
        character,
        candidate,
        result,
        analysis,
    )

    assert "- 建议：仅过渡" in report
    assert "当前位已锁定" in report
    assert "| 超过当前同位置 | - | 当前 5号位 已标记保留锁定" in report


def test_first_version_acceptance_report_answers_all_core_questions():
    game = load_game("zzz")
    character = next(
        item
        for item in load_characters("zzz")
        if item.id == "zzz_starlight_billy"
    )
    probability_model = load_probability_models("zzz")[0]
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    analysis = analyse_current_gear(pieces, game, character)
    rows = build_strategy_sweep(game, character, probability_model, analysis)
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
    candidate = load_candidate_example("examples/zzz_candidate_slot5.yaml")
    result = evaluate_candidate(candidate, game, character)

    report = first_version_acceptance_report_markdown(
        game,
        character,
        candidate,
        result,
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
        probability_model=probability_model,
    )

    assert "# 绝区零 星徽·比利 算法验收总览" in report
    assert "## 六个核心问题" in report
    assert "| 验收问题 | 当前答案 | 依据 | 入口 |" in report
    assert "| 我当前 6 件盘哪件最差？ | 6号位 |" in report
    assert "| 这个新胚子还值不值得强化？ | 继续 |" in report
    assert "| 现在应该固定几号位？ |" in report
    assert "校音器该不该用？" in report
    assert "共鸣核该不该留？" in report
    assert "长期最优和当前提升是否冲突？" in report
    assert "## 高优先级问题闭环" in report
    assert "| 编号 | 问题 | 闭环状态 | 验收入口 | 证据 |" in report
    assert "| 1 | localhost 形态能不能做成 App | 已切到 PySide6 原生桌面入口和 Windows exe 打包 |" in report
    assert "不再保留 Web 入口" in report
    assert "| 12 | 桌面结果区需要调律操作期望管理 | 已增加随机/固定位置收益表、固定主属性和固定副属性省母盘阶梯 |" in report
    assert "## 下一步操作卡" in report
    assert "| 顺序 | 行动 | 入口 | 目标 | 调律范围 | 资源提示 | 原因 |" in report
    assert "| 1 | 先补 2 件套 | 调律策略比较 -> 套装阶段拆解 / 桌面结果区调律期望管理 | 折枝剑歌 6号位" in report
    assert "| 2 | 保留长期目标 | 调律策略比较 -> 长期目标 / 桌面结果区调律期望管理 | 云岿如我 5号位 物理伤害" in report
    assert "| 3 | 继续强化候选 | 候选胚子评估 -> 下一跳止损卡 / 最终分布图 | 云岿如我 5号位 物理伤害 | 候选胚子强化 |" in report
    assert "## 资源投入守则" not in report
    assert "## 当前/长期投入对照" not in report
    assert "## 候选胚子结论" in report
    assert "## 候选下一跳止损卡" in report
    assert "| 当前动作 | 强化到 +6 |" in report
    assert "## 桌面结果区调律期望管理" in report
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
