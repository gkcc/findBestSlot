from __future__ import annotations

from gear_optimizer.models import (
    CandidateEvaluation,
    CandidatePiece,
    CharacterPreset,
    CurrentGearAnalysis,
    GameRules,
    GearPiece,
    ProbabilityModel,
    StrategyRow,
    position_key,
)
from gear_optimizer.conclusions import (
    candidate_conclusion_rows,
    candidate_contextual_recommendation,
    candidate_next_step_rows,
    candidate_outcome_rows,
    current_gear_conclusion_rows,
    expected_cost_label,
    first_version_acceptance_rows,
    first_version_next_action_rows,
    high_priority_closure_rows,
    probability_model_assumption_rows,
    strategy_brief,
    strategy_conclusion_rows,
    today_action_summary_rows,
)
from gear_optimizer.recommendation import (
    resource_decision_text,
    set_plan_next_action_rows,
    set_plan_stage_rows,
    strategy_alignment_text,
)
from gear_optimizer.position_ev import (
    action_ev_brief,
    fixed_main_gain_ladder_rows,
    fixed_substat_gain_ladder_rows,
    initial_substat_tier_rows,
    position_strategy_efficiency_rows,
    recommended_action_ev_row,
    resource_marginal_ev_rows,
)
from gear_optimizer.strategy import (
    strategy_context_rows,
    strategy_cost_ladder,
)


def _markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    def clean(value: str) -> str:
        return str(value).replace("\n", " ").replace("|", "/")

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(clean(value) for value in row) + " |")
    return lines


def _effective_substat_priority_text(character: CharacterPreset) -> str:
    priority = character.substat_priority
    core = list(priority.core) if priority else character.priority_stats()
    usable = list(priority.usable) if priority else []
    parts = []
    if core:
        parts.append(f"核心：{' > '.join(core)}")
    if usable:
        parts.append(f"可用：{' > '.join(usable)}")
    return "；".join(parts) if parts else "未配置"


def _strategy_conclusion_markdown(
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
) -> list[str]:
    rows = strategy_conclusion_rows(
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
    )
    return _markdown_table(
        ["问题", "结论", "依据"],
        [[row["问题"], row["结论"], row["依据"]] for row in rows],
    )


def _strategy_context_markdown(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel | None,
    analysis: CurrentGearAnalysis,
) -> list[str]:
    if probability_model is None:
        return ["_未提供概率模型，无法生成策略上下文。_"]
    rows = strategy_context_rows(game, character, probability_model, analysis)
    return _markdown_table(
        ["项目", "当前值", "策略影响"],
        [[row["项目"], row["当前值"], row["策略影响"]] for row in rows],
    )


def _current_gear_conclusion_markdown(
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
) -> list[str]:
    rows = current_gear_conclusion_rows(
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
    )
    return _markdown_table(
        ["问题", "结论", "依据"],
        [[row["问题"], row["结论"], row["依据"]] for row in rows],
    )


def _conclusion_by_question(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["问题"]: row for row in rows}


def _current_acceptance_markdown(
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
    action_ev_rows: list[dict[str, float | str]] | None = None,
) -> list[str]:
    rows = current_gear_conclusion_rows(
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
        include_strategy_resources=True,
    )
    by_question = _conclusion_by_question(rows)
    items = [
        ("我当前 6 件盘哪件最差？", "当前哪件最弱", "看当前装备评分和柱状图。"),
        ("这个新胚子还值不值得强化？", None, "切到候选胚子评估页，看候选验收速览。"),
        ("现在应该固定几号位？", "现在优先固定/刷哪里", "看调律策略比较的全局推荐和随机 vs 固定位置表。"),
        ("校音器该不该用？", "校音器该不该用", "只对应固定主属性，先看是否和长期目标一致。"),
        ("共鸣核该不该留？", "共鸣核该不该留", "只对应固定副属性，默认作为极限毕业资源。"),
        ("长期最优和当前提升是否冲突？", "长期和当前是否冲突", "看长期绝对最优与当前补弱是否同目标。"),
    ]
    table_rows = [
        [
            question,
            by_question.get(source, {}).get("结论", "见候选页")
            if source
            else "见候选页",
            next_step,
        ]
        for question, source, next_step in items
    ]
    if action_ev_rows:
        for row in table_rows:
            if row[0] == "现在应该固定几号位？":
                row[1] = action_ev_brief(action_ev_rows)
                row[2] = "看攻略结论和随机 vs 固定位置收益效率。"
                break
    return _markdown_table(
        ["验收问题", "当前答案", "怎么继续看"],
        table_rows,
    )


def _first_version_acceptance_markdown(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
    action_ev_rows: list[dict[str, float | str]] | None = None,
) -> list[str]:
    rows = first_version_acceptance_rows(
        game,
        character,
        candidate,
        result,
        analysis,
        current_best,
        long_term_best,
        tuner_best,
        core_best,
        include_strategy_resources=True,
    )
    if action_ev_rows:
        for row in rows:
            if row["验收问题"] == "现在应该固定几号位？":
                row["当前答案"] = action_ev_brief(action_ev_rows)
                row["依据"] = "Action EV 按完整概率分布枚举；固定位置只有单位母盘收益高于随机位置时才推荐。"
                row["入口"] = "调律策略比较 -> 攻略结论 / 随机 vs 固定位置收益效率"
                break
    return _markdown_table(
        ["验收问题", "当前答案", "依据", "入口"],
        [
            [row["验收问题"], row["当前答案"], row["依据"], row["入口"]]
            for row in rows
        ],
    )


def _high_priority_closure_markdown() -> list[str]:
    return _markdown_table(
        ["编号", "问题", "闭环状态", "验收入口", "证据"],
        [
            [
                row["编号"],
                row["问题"],
                row["闭环状态"],
                row["验收入口"],
                row["证据"],
            ]
            for row in high_priority_closure_rows()
        ],
    )


def _set_plan_stage_markdown(
    game: GameRules,
    analysis: CurrentGearAnalysis,
) -> list[str]:
    rows = set_plan_stage_rows(game, analysis)
    return _markdown_table(
        ["顺序", "阶段", "目标", "进度", "缺口", "排序分", "算法依据", "当前动作", "推荐让位", "依据"],
        [
            [
                str(row["order"]),
                row["stage"],
                row["target"],
                str(row["progress"]),
                str(row["missing"]),
                str(row["priority_score"]),
                row["algorithm_basis"],
                row["action"],
                row["replacement"],
                row["basis"],
            ]
            for row in rows
        ],
    )


def _next_action_markdown(
    game: GameRules,
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
) -> list[str]:
    rows = set_plan_next_action_rows(game, analysis, current_best, long_term_best)
    return _action_rows_markdown(rows)


def _action_rows_markdown(rows: list[dict]) -> list[str]:
    return _markdown_table(
        ["顺序", "行动", "入口", "目标", "调律范围", "资源提示", "原因"],
        [
            [
                str(row["order"]),
                row["action"],
                row.get("entry", "调律策略比较 -> 全局调律推荐"),
                row["target"],
                row["tuning_scope"],
                row["resource_hint"],
                row["reason"],
            ]
            for row in rows
        ],
    )


def _today_action_summary_markdown(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
) -> list[str]:
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
    return _markdown_table(
        ["优先级", "主题", "动作", "目标", "理由", "入口"],
        [
            [
                row["优先级"],
                row["主题"],
                row["动作"],
                row["目标"],
                row["理由"],
                row["入口"],
            ]
            for row in rows
        ],
    )


def _first_sentence(text: str) -> str:
    if not text:
        return "-"
    sentence = str(text).split("。", 1)[0].strip()
    return f"{sentence}。" if sentence else str(text)


def _compact_resource_action(tuner_text: str, core_text: str) -> str:
    tuner_hold = any(word in tuner_text for word in ["先别急", "先攒", "暂无"])
    core_hold = any(word in core_text for word in ["先留", "保留", "暂无"])
    tuner_action = "校音器先留" if tuner_hold else "校音器可观察"
    core_action = "共鸣核先留" if core_hold else "共鸣核只看极限毕业"
    return f"{tuner_action}；{core_action}"


def _action_ev_guide_text(action_ev_rows: list[dict[str, float | str]]) -> tuple[str, str]:
    row = recommended_action_ev_row(action_ev_rows)
    if row is None:
        return "暂无母盘 action", "缺少概率模型或当前盘面。"
    action = "固定位置" if row.get("策略") == "固定位置" else "随机位置"
    target = f"{row['目标套装']} {row['位置']}"
    reason = (
        f"排序向量/母盘 {row.get('排序向量/母盘', '-')}，有效/母盘 {row['有效/母盘']}；"
        f"{row['相对随机']}。"
    )
    return f"{action}：{target}", reason


def _strategy_guide_markdown(
    action_ev_rows: list[dict[str, float | str]],
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
) -> list[str]:
    ev_action, ev_reason = _action_ev_guide_text(action_ev_rows)
    tuner_text, core_text = resource_decision_text(tuner_best, core_best, long_term_best)
    return _markdown_table(
        ["优先级", "主题", "行动", "理由"],
        [
            ["1", "母盘", ev_action, ev_reason],
            ["2", "当前补弱", f"{analysis.weakest_position_name or '-'} 最弱", f"最弱：{analysis.weakest_position_name or '-'}；只看当前盘面最容易补强的位置。"],
            ["3", "特殊资源", _compact_resource_action(tuner_text, core_text), f"{_first_sentence(tuner_text)} {_first_sentence(core_text)}"],
            ["4", "长期目标", strategy_brief(long_term_best, include_resources=True), _first_sentence(strategy_alignment_text(current_best, long_term_best))],
        ],
    )


def _same_ladder_target(row: StrategyRow, target: StrategyRow) -> bool:
    return (
        row.target_set == target.target_set
        and row.target_position == target.target_position
    )


def _cost_ladder_for_target(
    strategy_rows: list[StrategyRow] | None,
    target: StrategyRow | None,
) -> list[StrategyRow]:
    if not strategy_rows or target is None:
        return []
    rows = [row for row in strategy_rows if _same_ladder_target(row, target)]
    order = {
        "随机位置，不定主属性": 0,
        "固定位置，不定主属性": 1,
        "固定位置 + 固定主属性": 2,
        "固定位置 + 固定主属性 + 固定 1 个副属性": 3,
        "固定位置 + 固定主属性 + 固定 2 个副属性": 4,
    }
    return sorted(rows, key=lambda row: order.get(row.strategy_name, 99))


def _strategy_ladder_markdown(rows: list[StrategyRow]) -> list[str]:
    if not rows:
        return ["暂无调律成本阶梯。"]
    ladder = strategy_cost_ladder(rows)
    table_rows = []
    for item in ladder:
        table_rows.append(
            [
                str(item["stage"]),
                item["strategy_name"],
                item["locked_scope"],
                item["target_set_scope"],
                item["set_probability_source"],
                f"{item['candidate_probability']:.3%}",
                expected_cost_label(item["expected_mother_disks"]),
                expected_cost_label(item["expected_tuners"]),
                expected_cost_label(item["expected_cores"]),
                item["fixed_substat_note"],
                item["incremental_note"],
            ]
        )
    return _markdown_table(
        [
            "阶梯",
            "策略名称",
            "锁定范围",
            "可接受套装",
            "套装概率来源",
            "候选概率",
            "期望母盘",
            "期望校音器",
            "期望共鸣核",
            "固定副词条依据",
            "增量解释",
        ],
        table_rows,
    )


def _probability_model_assumption_markdown(model: ProbabilityModel | None) -> list[str]:
    if model is None:
        return ["暂无概率模型假设。"]
    rows = probability_model_assumption_rows(model)
    return _markdown_table(
        ["假设", "当前值", "说明"],
        [[row["假设"], row["当前值"], row["说明"]] for row in rows],
    )


def _position_strategy_efficiency_markdown(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel | None,
    analysis: CurrentGearAnalysis,
) -> list[str]:
    if probability_model is None:
        return ["暂无概率模型，无法计算随机/固定位置收益。"]
    rows = position_strategy_efficiency_rows(game, character, probability_model, analysis)
    return _markdown_table(
        [
            "策略",
            "目标套装",
            "位置",
            "主属性",
            "固定副属性",
            "horizon",
            "immediate_EV",
            "option_EV",
            "horizon_EV",
            "期望提升",
            "质量提升",
            "有效提升",
            "母盘/次",
            "校音器/次",
            "共鸣核/次",
            "质量/母盘",
            "有效/母盘",
            "排序向量/母盘",
            "相对随机",
        ],
        [
            [
                row["策略"],
                row["目标套装"],
                row["位置"],
                row.get("主属性", "不固定"),
                row.get("固定副属性", "不固定"),
                row.get("horizon", 1),
                row.get("immediate_EV", row["期望提升"]),
                row.get("option_EV", "0"),
                row.get("horizon_EV", row["期望提升"]),
                row["期望提升"],
                row["质量提升"],
                row["有效提升"],
                row["母盘/次"],
                row.get("校音器/次", 0.0),
                row.get("共鸣核/次", 0.0),
                row["质量/母盘"],
                row["有效/母盘"],
                row["排序向量/母盘"],
                row["相对随机"],
            ]
            for row in rows
        ],
    )


def _fixed_main_gain_ladder_markdown(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel | None,
    analysis: CurrentGearAnalysis,
) -> list[str]:
    if probability_model is None:
        return ["暂无概率模型，无法计算固定主属性省母盘阶梯。"]
    rows = fixed_main_gain_ladder_rows(game, character, probability_model, analysis)
    return _markdown_table(
        [
            "位置",
            "当前补弱顺位",
            "推荐主属性",
            "当前质量分",
            "当前有效词条",
            "提升目标",
            "目标质量分",
            "不锁主属性有效提升",
            "固定主属性有效提升",
            "不锁主属性概率",
            "固定主属性概率",
            "不锁主属性母盘",
            "固定主属性母盘",
            "省母盘",
            "期望校音器",
        ],
        [
            [
                row["位置"],
                row["当前补弱顺位"],
                row["推荐主属性"],
                row["当前质量分"],
                row["当前有效词条"],
                row["提升目标"],
                row["目标质量分"],
                row["不锁主属性有效提升"],
                row["固定主属性有效提升"],
                row["不锁主属性概率"],
                row["固定主属性概率"],
                row["不锁主属性母盘"],
                row["固定主属性母盘"],
                row["省母盘"],
                row["期望校音器"],
            ]
            for row in rows
        ],
    )


def _fixed_substat_gain_ladder_markdown(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel | None,
    analysis: CurrentGearAnalysis,
) -> list[str]:
    if probability_model is None:
        return ["暂无概率模型，无法计算固定副属性省母盘阶梯。"]
    rows = fixed_substat_gain_ladder_rows(game, character, probability_model, analysis)
    return _markdown_table(
        [
            "位置",
            "当前补弱顺位",
            "主属性",
            "锁定副属性",
            "当前有效词条",
            "提升目标",
            "目标质量分",
            "固定主属性有效提升",
            "锁副属性有效提升",
            "固定主属性概率",
            "锁副属性概率",
            "固定主属性母盘",
            "锁副属性母盘",
            "省母盘",
            "期望校音器",
            "期望共鸣核",
        ],
        [
            [
                row["位置"],
                row["当前补弱顺位"],
                row["主属性"],
                row["锁定副属性"],
                row["当前有效词条"],
                row["提升目标"],
                row["目标质量分"],
                row["固定主属性有效提升"],
                row["锁副属性有效提升"],
                row["固定主属性概率"],
                row["锁副属性概率"],
                row["固定主属性母盘"],
                row["锁副属性母盘"],
                row["省母盘"],
                row["期望校音器"],
                row["期望共鸣核"],
            ]
            for row in rows
        ],
    )


def _resource_marginal_ev_markdown(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel | None,
    analysis: CurrentGearAnalysis,
) -> list[str]:
    if probability_model is None:
        return ["暂无概率模型，无法计算特殊资源全局边际 EV。"]
    rows = resource_marginal_ev_rows(game, character, probability_model, analysis)
    return _markdown_table(
        [
            "资源",
            "目标套装",
            "位置",
            "主属性",
            "固定副属性",
            "基准action",
            "资源action",
            "边际提升",
            "边际有效提升",
            "边际质量提升",
            "母盘/次",
            "同等有效省母盘",
            "同等质量省母盘",
            "期望校音器/次",
            "期望共鸣核/次",
        ],
        [
            [
                row["资源"],
                row["目标套装"],
                row["位置"],
                row["主属性"],
                row["固定副属性"],
                row["基准action"],
                row["资源action"],
                row["边际提升"],
                row["边际有效提升"],
                row["边际质量提升"],
                row["母盘/次"],
                row["同等有效省母盘"],
                row["同等质量省母盘"],
                row["期望校音器/次"],
                row["期望共鸣核/次"],
            ]
            for row in rows
        ],
    )


def _initial_substat_tier_markdown(
    game: GameRules,
    character: CharacterPreset,
    probability_model: ProbabilityModel | None,
    analysis: CurrentGearAnalysis,
) -> list[str]:
    if probability_model is None:
        return ["暂无概率模型，无法计算胚子挡位概率。"]
    rows = initial_substat_tier_rows(game, character, probability_model, analysis)
    return _markdown_table(
        [
            "位置",
            "当前补弱顺位",
            "参考主属性",
            "初始词条数",
            "胚子挡位",
            "条件概率",
            "总出现概率",
            "满级有效期望",
            "满级质量期望",
        ],
        [
            [
                row["位置"],
                row["当前补弱顺位"],
                row["参考主属性"],
                row["初始词条数"],
                row["胚子挡位"],
                row["条件概率"],
                row["总出现概率"],
                row["满级有效期望"],
                row["满级质量期望"],
            ]
            for row in rows
        ],
    )


def _substat_detail_label(details: list[dict]) -> str:
    values = []
    for detail in details:
        if detail["priority"] == "无效":
            values.append(f"{detail['stat']}({detail['priority']})")
        else:
            values.append(
                f"{detail['stat']} {detail['total_rolls']:g}次"
                f"·{detail['priority']}"
                f"{'#' + str(detail['priority_rank']) if detail.get('priority_rank') else ''}"
            )
    return "；".join(values) if values else "-"


def _score_rows_markdown(analysis: CurrentGearAnalysis) -> list[str]:
    rows = [
        "| 位置 | 套装 | 主属性 | 保留 | 有效词条 | 质量分 | 评级 | 替换标签 | 副词条明细 |",
        "| --- | --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for score in analysis.scores:
        pressure = (
            analysis.set_plan["position_pressures"].get(position_key(score.position), {})
            if analysis.set_plan
            else {}
        )
        rows.append(
            "| "
            + " | ".join(
                [
                    score.position_name,
                    score.set_name,
                    score.main_stat,
                    "是" if score.locked else "否",
                    f"{score.effective_rolls:g}",
                    f"{score.weighted_score:g}",
                    score.rating,
                    pressure.get("replacement_badge", "保留"),
                    _substat_detail_label(score.substat_details),
                ]
            )
            + " |"
        )
    return rows


def _candidate_conclusion_markdown(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
) -> list[str]:
    rows = candidate_conclusion_rows(game, character, candidate, result, analysis)
    return _markdown_table(
        ["问题", "结论", "依据"],
        [[row["问题"], row["结论"], row["依据"]] for row in rows],
    )


def _candidate_outcome_markdown(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
) -> list[str]:
    rows = candidate_outcome_rows(game, character, candidate, result, analysis)
    return _markdown_table(
        ["目标", "概率", "依据"],
        [[row["目标"], row["概率"], row["依据"]] for row in rows],
    )


def _candidate_next_step_markdown(result: CandidateEvaluation) -> list[str]:
    return _markdown_table(
        ["场景", "动作", "依据"],
        [
            [row["场景"], row["动作"], row["依据"]]
            for row in candidate_next_step_rows(result)
        ],
    )


def _candidate_event_markdown(result: CandidateEvaluation) -> list[str]:
    if not result.event_rows:
        return ["暂无剩余强化路径。"]
    return _markdown_table(
        ["等级", "事件", "命中有效概率", "质量期望增量", "说明"],
        [
            [
                f"+{row['level']}",
                row["event"],
                f"{row['hit_probability']:.1%}",
                f"{row['expected_weighted_gain']:.2f}",
                row["description"],
            ]
            for row in result.event_rows
        ],
    )


def _candidate_distribution_markdown(result: CandidateEvaluation) -> list[str]:
    rows = []
    for point in result.distribution:
        rows.append([f"{point.effective_rolls:g}", f"{point.probability:.1%}"])
    return _markdown_table(["最终有效词条次数", "概率"], rows)


def _candidate_weighted_distribution_markdown(result: CandidateEvaluation) -> list[str]:
    rows = []
    for point in result.weighted_distribution:
        rows.append([f"{point.weighted_score:g}", f"{point.probability:.1%}"])
    return _markdown_table(["最终质量分", "概率"], rows)


def candidate_analysis_report_markdown(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
) -> str:
    contextual_recommendation, _contextual_reason = candidate_contextual_recommendation(
        candidate,
        result,
        analysis,
    )
    lines = [
        f"# {game.name} {character.name} 候选胚子分析报告",
        "",
        "## 候选结论",
        "",
        *_candidate_conclusion_markdown(game, character, candidate, result, analysis),
        "",
        "## 下一跳止损卡",
        "",
        *_candidate_next_step_markdown(result),
        "",
        "## 候选结果概率",
        "",
        *_candidate_outcome_markdown(game, character, candidate, result, analysis),
        "",
        "## 候选基础",
        "",
        f"- 位置：{game.position_name(candidate.position)}",
        f"- 套装：{candidate.set_name}",
        f"- 主属性：{candidate.main_stat}",
        f"- 当前等级：+{candidate.level}",
        f"- 初始词条数：{candidate.initial_substat_count}",
        f"- 当前有效词条：{result.current_effective_rolls:g}",
        f"- 当前质量分：{result.current_weighted_score:g}",
        f"- 满级有效词条期望：{result.final_expected_effective_rolls:g}",
        f"- 满级质量期望：{result.final_expected_weighted_score:g}",
        f"- 建议：{contextual_recommendation}",
        "",
        "## 强化路径",
        "",
        *_candidate_event_markdown(result),
        "",
        "## 最终有效词条分布",
        "",
        *_candidate_distribution_markdown(result),
        "",
        "## 最终质量分布",
        "",
        *_candidate_weighted_distribution_markdown(result),
        "",
    ]
    if result.warnings:
        lines.extend(["## 注意事项", ""])
        lines.extend(f"- {warning}" for warning in result.warnings)
        lines.append("")
    return "\n".join(lines)


def first_version_acceptance_report_markdown(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
    probability_model: ProbabilityModel | None = None,
) -> str:
    action_ev_rows = (
        position_strategy_efficiency_rows(game, character, probability_model, analysis)
        if probability_model
        else []
    )
    lines = [
        f"# {game.name} {character.name} 第一版验收总览",
        "",
        "## 攻略结论",
        "",
        *_strategy_guide_markdown(
            action_ev_rows,
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
        ),
        "",
        "## 六个核心问题",
        "",
        *_first_version_acceptance_markdown(
            game,
            character,
            candidate,
            result,
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
            action_ev_rows,
        ),
        "",
        "## 核算明细",
        "",
        "## 今日行动摘要",
        "",
        *_today_action_summary_markdown(
            game,
            character,
            candidate,
            result,
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
        ),
        "",
        "## 高优先级问题闭环",
        "",
        *_high_priority_closure_markdown(),
        "",
        "## 下一步操作卡",
        "",
        *_action_rows_markdown(
            first_version_next_action_rows(
                game,
                character,
                candidate,
                result,
                analysis,
                current_best,
                long_term_best,
            )
        ),
        "",
        "## 当前装备结论",
        "",
        *_current_gear_conclusion_markdown(
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
        ),
        "",
        "## 候选胚子结论",
        "",
        *_candidate_conclusion_markdown(game, character, candidate, result, analysis),
        "",
        "## 候选下一跳止损卡",
        "",
        *_candidate_next_step_markdown(result),
        "",
        "## 调律结论",
        "",
        *_strategy_conclusion_markdown(
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
        ),
        "",
        "## 当前调律期望管理",
        "",
        "按完整概率分布做理论期望，不做抽样模拟；随机/固定都会把新盘加入库存后重求当前套装约束下的最优组合；同时展示有效词条提升/母盘和质量提升/母盘；固定主属性只展示省母盘和期望校音器，不做资源折算。",
        "",
        "### 随机 vs 固定位置收益效率",
        "",
        *_position_strategy_efficiency_markdown(
            game,
            character,
            probability_model,
            analysis,
        ),
        "",
        "### 固定主属性省母盘阶梯",
        "",
        *_fixed_main_gain_ladder_markdown(
            game,
            character,
            probability_model,
            analysis,
        ),
        "",
        "### 固定副属性省母盘阶梯",
        "",
        *_fixed_substat_gain_ladder_markdown(
            game,
            character,
            probability_model,
            analysis,
        ),
        "",
        "### 特殊资源全局边际 EV",
        "",
        *_resource_marginal_ev_markdown(
            game,
            character,
            probability_model,
            analysis,
        ),
        "",
        "### 胚子挡位概率解释",
        "",
        "初始 3 词条按概率模型作为主流；4中3 只有在主属性没有挤占有效副词条时才可能出现。",
        "",
        *_initial_substat_tier_markdown(
            game,
            character,
            probability_model,
            analysis,
        ),
        "",
    ]
    return "\n".join(lines)


def current_analysis_report_markdown(
    game: GameRules,
    character: CharacterPreset,
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
    strategy_rows: list[StrategyRow] | None = None,
    probability_model: ProbabilityModel | None = None,
    pieces: list[GearPiece] | None = None,
) -> str:
    action_ev_rows = (
        position_strategy_efficiency_rows(game, character, probability_model, analysis)
        if probability_model
        else []
    )
    lines = [
        f"# {game.name} {character.name} 装备词条分析报告",
        "",
        "## 攻略结论",
        "",
        *_strategy_guide_markdown(
            action_ev_rows,
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
        ),
        "",
        "## 核算明细",
        "",
        "## 当前装备结论",
        "",
        *_current_gear_conclusion_markdown(
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
        ),
        "",
        "## 调律结论",
        "",
        *_strategy_conclusion_markdown(
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
        ),
        "",
        "## 策略上下文",
        "",
        *_strategy_context_markdown(game, character, probability_model, analysis),
        "",
        "## 概率与资源假设",
        "",
        *_probability_model_assumption_markdown(probability_model),
        "",
        "## 当前调律期望管理",
        "",
        "按完整概率分布做理论期望，不做抽样模拟；随机/固定都会把新盘加入库存后重求当前套装约束下的最优组合；同时展示有效词条提升/母盘和质量提升/母盘；固定主属性只展示省母盘和期望校音器，不做资源折算。",
        "",
        "### 随机 vs 固定位置收益效率",
        "",
        *_position_strategy_efficiency_markdown(
            game,
            character,
            probability_model,
            analysis,
        ),
        "",
        "### 固定主属性省母盘阶梯",
        "",
        *_fixed_main_gain_ladder_markdown(
            game,
            character,
            probability_model,
            analysis,
        ),
        "",
        "### 固定副属性省母盘阶梯",
        "",
        *_fixed_substat_gain_ladder_markdown(
            game,
            character,
            probability_model,
            analysis,
        ),
        "",
        "### 特殊资源全局边际 EV",
        "",
        *_resource_marginal_ev_markdown(
            game,
            character,
            probability_model,
            analysis,
        ),
        "",
        "### 胚子挡位概率解释",
        "",
        "初始 3 词条按概率模型作为主流；4中3 只有在主属性没有挤占有效副词条时才可能出现。",
        "",
        *_initial_substat_tier_markdown(
            game,
            character,
            probability_model,
            analysis,
        ),
        "",
        "## 套装阶段拆解",
        "",
        *_set_plan_stage_markdown(game, analysis),
        "",
        "## 当前推荐目标成本阶梯",
        "",
        *_strategy_ladder_markdown(
            _cost_ladder_for_target(strategy_rows, current_best)
        ),
        "",
        "## 角色目标",
        "",
        f"- 套装方案：{analysis.set_plan['name'] if analysis.set_plan else character.target_set}",
        f"- 有效副词条优先级：{_effective_substat_priority_text(character)}",
        "",
        "## 当前装备评分",
        "",
        *_score_rows_markdown(analysis),
        "",
    ]
    return "\n".join(lines)
