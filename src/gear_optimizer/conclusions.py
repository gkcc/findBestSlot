from __future__ import annotations

from gear_optimizer.models import (
    CandidateEvaluation,
    CandidatePiece,
    CharacterPreset,
    CurrentGearAnalysis,
    GameRules,
    ProbabilityModel,
    StrategyRow,
    position_key,
)
from gear_optimizer.recommendation import (
    resource_decision_text,
    set_plan_next_action_rows,
    set_plan_lock_conflict_text,
    set_plan_step_text,
    strategy_alignment_text,
)
from gear_optimizer.strategy import (
    fixed_substat_note,
    strategy_set_probability_source,
    strategy_target_set_scope,
)


def expected_cost_label(value: float) -> str:
    if value == float("inf"):
        return "∞"
    return f"{value:.1f}"


def score_for_position(analysis: CurrentGearAnalysis, position: str | int):
    key = position_key(position)
    for score in analysis.scores:
        if position_key(score.position) == key:
            return score
    return None


def strategy_brief(row: StrategyRow | None, include_resources: bool = False) -> str:
    if row is None:
        return "暂无可用策略。"
    main = row.target_main_stat if row.fixed_main_stat else "不定主属性"
    substats = fixed_substat_note(row)
    text = (
        f"{row.strategy_name}：{row.target_set} {row.target_position_name}，"
        f"{main}，{substats}"
    )
    if include_resources:
        tuner = "用校音器" if row.expected_tuners > 0 else "不消耗校音器"
        core = "用共鸣核" if row.expected_cores > 0 else "不消耗共鸣核"
        text += f"；{tuner}，{core}"
    return f"{text}。"


def strategy_probability_scope(row: StrategyRow | None) -> str:
    if row is None:
        return "暂无概率口径。"
    locked_parts = ["套装"]
    if row.fixed_position:
        locked_parts.append("位置")
    if row.fixed_main_stat:
        locked_parts.append("主属性")
    if row.fixed_substats:
        locked_parts.append(f"{len(row.fixed_substats)} 个副属性")
    scope = " + ".join(locked_parts)
    if not row.fixed_main_stat:
        return (
            f"候选概率口径：{scope} 命中；未固定主属性，"
            "不代表目标主属性或毕业概率；"
            "主属性和强化档位看当前调律期望管理"
        )
    if row.fixed_substats:
        return (
            f"候选概率口径：{scope} 命中；该路径会消耗共鸣核，"
            "只作为极限毕业观察"
        )
    return f"候选概率口径：{scope} 命中；固定主属性只消耗校音器，不锁副属性"


def strategy_cost_basis(row: StrategyRow | None) -> str:
    if row is None:
        return "暂无可用策略。"
    return (
        f"候选概率 {row.candidate_probability:.3%}；"
        f"{strategy_probability_scope(row)}；"
        f"可接受套装：{strategy_target_set_scope(row)}；"
        f"{strategy_set_probability_source(row)}；"
        f"期望母盘 {expected_cost_label(row.expected_mother_disks)}，"
        f"校音器 {expected_cost_label(row.expected_tuners)}，"
        f"共鸣核 {expected_cost_label(row.expected_cores)}；"
        f"固定副属性：{fixed_substat_note(row)}；"
        f"当前提升评分 {row.current_relative_gain_score:g}，"
        f"长期价值评分 {row.long_term_value_score:g}。"
    )


def set_plan_status_text(analysis: CurrentGearAnalysis) -> str:
    if not analysis.set_plan:
        return "当前角色没有设置套装方案。"
    if analysis.set_plan["is_unrestricted"]:
        return f"套装方案：{analysis.set_plan['name']}。当前不约束 4+2 或 2+2+2。"
    parts = [
        f"{_set_requirement_label(item)} {item['current']}/{item['required']}"
        for item in analysis.set_plan["requirements"]
    ]
    status = "已满足" if analysis.set_plan["satisfied"] else "未满足"
    text = f"套装方案：{analysis.set_plan['name']}（{status}）：{'，'.join(parts)}。"
    lock_conflict = set_plan_lock_conflict_text(analysis.set_plan)
    if lock_conflict:
        text += f" {lock_conflict}"
    suggestions = analysis.set_plan.get("suggested_replacements", [])
    if suggestions:
        top = suggestions[0]
        text += (
            f" 优先考虑把 {top['position']} 号位调成 {top['target_set']}，"
            f"因为当前套装可让位且替换压力最高（{top['replacement_pressure']:g}）。"
        )
    return text


def probability_model_assumption_rows(model: ProbabilityModel) -> list[dict[str, str]]:
    rows = [
        {
            "假设": "目标套装概率",
            "当前值": _probability_label(model.target_set_probability),
            "说明": "调律指定套装时可设为 100%；刷本随机产出时再按实际来源改低。",
        }
    ]
    for count, probability in sorted(
        model.initial_substat_count_probabilities.items(),
        key=lambda item: int(item[0]),
    ):
        rows.append(
            {
                "假设": f"初始 {count} 词条概率",
                "当前值": _probability_label(probability),
                "说明": "候选胚子初始副属性数量分布。",
            }
        )

    resource_labels = {
        "mother_disk_random_position_attempt": ("母盘/随机位置", "不固定位置时每次调律尝试的母盘成本。"),
        "mother_disk_fixed_position_attempt": ("母盘/固定位置", "固定位置时每次调律尝试的母盘成本。"),
        "tuner_per_fixed_main_attempt": ("校音器/固定主属性", "固定主属性时每次尝试消耗的校音器。"),
        "core_per_fixed_substat_attempt": ("共鸣核/固定副属性", "每固定 1 个副属性时每次尝试消耗的共鸣核。"),
    }
    defaults = {
        "mother_disk_random_position_attempt": 3.0,
        "mother_disk_fixed_position_attempt": 6.0,
        "tuner_per_fixed_main_attempt": 1.0,
        "core_per_fixed_substat_attempt": 1.0,
    }
    for key, (label, description) in resource_labels.items():
        rows.append(
            {
                "假设": label,
                "当前值": f"{model.resource_cost(key, defaults[key]):g}",
                "说明": description,
            }
        )
    if model.notes:
        rows.append(
            {
                "假设": "模型备注",
                "当前值": model.name,
                "说明": model.notes,
            }
        )
    return rows


def current_gear_conclusion_rows(
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
    include_strategy_resources: bool = False,
) -> list[dict[str, str]]:
    weakest_score = (
        score_for_position(analysis, analysis.weakest_position)
        if analysis.weakest_position is not None
        else None
    )
    weakest_basis = (
        f"评级 {weakest_score.rating}，质量分 {weakest_score.weighted_score:g}，"
        f"有效词条 {weakest_score.effective_rolls:g}。"
        if weakest_score
        else "暂无可评分装备。"
    )

    priority = analysis.relative_priority[0] if analysis.relative_priority else None
    priority_basis = (
        f"相对提升优先级 {priority['priority_score']:g}，"
        f"当前有效词条 {priority.get('current_effective_rolls', 0):g}，"
        f"质量分 {priority.get('current_weighted_score', priority['current_score']):g}，"
        f"主属性状态 {priority.get('main_stat_issue', '-')}，"
        f"替换标签 {priority.get('set_replacement_badge', '-')}。"
        if priority
        else "暂无相对提升排序。"
    )

    tuner_text, core_text = resource_decision_text(
        tuner_best,
        core_best,
        long_term_best,
    )
    return [
        {
            "问题": "当前哪件最弱",
            "结论": analysis.weakest_position_name or "-",
            "依据": weakest_basis,
        },
        {
            "问题": "现在优先固定/刷哪里",
            "结论": strategy_brief(
                current_best,
                include_resources=include_strategy_resources,
            ),
            "依据": priority_basis,
        },
        {
            "问题": "套装先补 4 还是 2",
            "结论": set_plan_step_text(analysis),
            "依据": set_plan_status_text(analysis),
        },
        {
            "问题": "校音器该不该用",
            "结论": tuner_text,
            "依据": (
                f"固定主属性期望消耗 {expected_cost_label(tuner_best.expected_tuners)}。"
                if tuner_best is not None
                else "暂无固定主属性策略。"
            ),
        },
        {
            "问题": "共鸣核该不该留",
            "结论": core_text,
            "依据": (
                f"固定副属性期望消耗 {expected_cost_label(core_best.expected_cores)}。"
                if core_best is not None
                else "暂无固定副属性策略。"
            ),
        },
        {
            "问题": "长期和当前是否冲突",
            "结论": strategy_alignment_text(current_best, long_term_best),
            "依据": (
                "当前："
                f"{strategy_brief(current_best, include_resources=include_strategy_resources)} "
                "长期："
                f"{strategy_brief(long_term_best, include_resources=include_strategy_resources)}"
            ),
        },
    ]


def _rows_by_question(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["问题"]: row for row in rows}


def strategy_conclusion_rows(
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
    include_strategy_resources: bool = False,
) -> list[dict[str, str]]:
    tuner_text, core_text = resource_decision_text(
        tuner_best,
        core_best,
        long_term_best,
    )
    current_position = (
        current_best.target_position_name
        if current_best is not None and current_best.fixed_position
        else "不固定位置"
    )
    long_position = (
        long_term_best.target_position_name
        if long_term_best is not None
        else "-"
    )
    return [
        {
            "问题": "现在应该固定几号位",
            "结论": (
                f"{current_position}；"
                f"{strategy_brief(current_best, include_resources=include_strategy_resources)}"
            ),
            "依据": strategy_cost_basis(current_best),
        },
        {
            "问题": "长期绝对最优目标",
            "结论": strategy_brief(
                long_term_best,
                include_resources=include_strategy_resources,
            ),
            "依据": strategy_cost_basis(long_term_best),
        },
        {
            "问题": "校音器该不该用",
            "结论": tuner_text,
            "依据": strategy_cost_basis(tuner_best),
        },
        {
            "问题": "共鸣核该不该留",
            "结论": core_text,
            "依据": strategy_cost_basis(core_best),
        },
        {
            "问题": "长期和当前是否冲突",
            "结论": strategy_alignment_text(current_best, long_term_best),
            "依据": f"当前目标位置：{current_position}；长期目标位置：{long_position}。",
        },
        {
            "问题": "套装阶段",
            "结论": set_plan_step_text(analysis),
            "依据": set_plan_status_text(analysis),
        },
    ]


def candidate_conclusion_rows(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
) -> list[dict[str, str]]:
    upgrade_conclusion, upgrade_basis = candidate_contextual_recommendation(
        candidate,
        result,
        analysis,
    )
    main_conclusion, main_basis = _candidate_main_status(game, character, candidate)
    set_conclusion, set_basis = _candidate_set_status(candidate, analysis)
    fit_conclusion, fit_basis = _candidate_fit_status(
        game,
        character,
        candidate,
        result,
        analysis,
        set_conclusion,
    )
    slot_plan_conclusion, slot_plan_basis = _candidate_slot_plan_status(
        game,
        candidate,
        result,
        analysis,
    )
    checkpoint_conclusion, checkpoint_basis = _candidate_checkpoint_status(result)
    replacement_conclusion, replacement_basis = _candidate_replacement_status(
        game,
        candidate,
        result,
        analysis,
    )
    return [
        {
            "问题": "这个胚子值不值得继续",
            "结论": upgrade_conclusion,
            "依据": upgrade_basis,
        },
        {
            "问题": "候选补位价值",
            "结论": fit_conclusion,
            "依据": fit_basis,
        },
        {
            "问题": "套装目标匹配",
            "结论": slot_plan_conclusion,
            "依据": slot_plan_basis,
        },
        {
            "问题": "强化观察点",
            "结论": checkpoint_conclusion,
            "依据": checkpoint_basis,
        },
        {
            "问题": "替换当前同位置提升",
            "结论": replacement_conclusion,
            "依据": replacement_basis,
        },
        {
            "问题": "主属性是否符合目标",
            "结论": main_conclusion,
            "依据": main_basis,
        },
        {
            "问题": "套装是否符合方案",
            "结论": set_conclusion,
            "依据": set_basis,
        },
        {
            "问题": "后续命中概率",
            "结论": _candidate_probability_list(result),
            "依据": (
                f"剩余随机命中 {result.remaining_roll_events} 次；"
                f"最终期望 {result.final_expected_effective_rolls:g} 有效 / "
                f"{result.final_expected_weighted_score:g} 质量分。"
            ),
        },
        {
            "问题": "当前副词条构成",
            "结论": _candidate_substat_summary(candidate, character),
            "依据": "核心、可用、无效由当前角色副词条优先级决定；未配置可用词条时只显示核心和无效。",
        },
    ]


def candidate_next_step_rows(result: CandidateEvaluation) -> list[dict[str, str]]:
    if not result.event_rows:
        return [
            {
                "场景": "当前状态",
                "动作": "直接按最终结果判断",
                "依据": "当前候选没有剩余强化事件；不需要再做下一跳止损。",
            }
        ]

    first = result.event_rows[0]
    level = int(first["level"])
    event = str(first["event"])
    hit_probability = float(first["hit_probability"])
    expected_weighted_gain = float(first["expected_weighted_gain"])
    event_label = (
        "补第 4 个副属性"
        if event == "补第 4 副属性"
        else "随机命中已有副属性"
    )

    if result.recommendation == "继续":
        hit_action = "继续强化到下一节点"
        miss_action = "暂停观察，等资源宽裕再决定"
    elif result.recommendation == "暂停":
        hit_action = "命中高优先级词条才继续"
        miss_action = "先停手，不再重投入"
    elif result.recommendation == "仅过渡":
        hit_action = "只作为过渡盘继续低成本观察"
        miss_action = "止损，当过渡盘处理"
    else:
        hit_action = "仅验证一次低成本事件"
        miss_action = "放弃，不再投入"

    return [
        {
            "场景": "当前动作",
            "动作": f"强化到 +{level}",
            "依据": (
                f"下一跳是 +{level} {event_label}；命中有效概率 "
                f"{hit_probability:.1%}，质量期望增量 {expected_weighted_gain:.2f}。"
            ),
        },
        {
            "场景": "命中有效/高优先级",
            "动作": hit_action,
            "依据": "命中后再按新的有效词条数、质量分和下一跳概率复查。",
        },
        {
            "场景": "未命中或歪到低价值",
            "动作": miss_action,
            "依据": "止损优先级由当前候选建议决定，避免把强化材料继续压在低期望路径上。",
        },
    ]


def first_version_acceptance_rows(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
    include_strategy_resources: bool = False,
) -> list[dict[str, str]]:
    current_rows = _rows_by_question(
        current_gear_conclusion_rows(
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
            include_strategy_resources=include_strategy_resources,
        )
    )
    strategy_rows = _rows_by_question(
        strategy_conclusion_rows(
            analysis,
            current_best,
            long_term_best,
            tuner_best,
            core_best,
            include_strategy_resources=include_strategy_resources,
        )
    )
    candidate_rows = _rows_by_question(
        candidate_conclusion_rows(game, character, candidate, result, analysis)
    )
    items = [
        ("我当前 6 件盘哪件最差？", current_rows, "当前哪件最弱", "当前装备评分"),
        ("这个新胚子还值不值得强化？", candidate_rows, "这个胚子值不值得继续", "候选胚子评估"),
        ("现在应该固定几号位？", strategy_rows, "现在应该固定几号位", "调律策略比较"),
        ("校音器该不该用？", strategy_rows, "校音器该不该用", "调律策略比较"),
        ("共鸣核该不该留？", strategy_rows, "共鸣核该不该留", "调律策略比较"),
        ("长期最优和当前提升是否冲突？", strategy_rows, "长期和当前是否冲突", "调律策略比较"),
    ]
    return [
        {
            "验收问题": question,
            "当前答案": source_rows.get(source_question, {}).get("结论", "-"),
            "依据": source_rows.get(source_question, {}).get("依据", "-"),
            "入口": entry,
        }
        for question, source_rows, source_question, entry in items
    ]


def high_priority_closure_rows() -> list[dict[str, str]]:
    return [
        {
            "编号": "1",
            "问题": "localhost 形态能不能做成 App",
            "闭环状态": "已切到 PySide6 原生桌面入口和 Windows exe 打包",
            "验收入口": "README / gacha-gear-optimizer-desktop / scripts/build_windows_app.ps1",
            "证据": "桌面入口直接启动 PySide6 窗口，不再保留 Web 入口或浏览器 app window；PyInstaller 脚本会打包 src、configs、examples、assets 和 PySide6 runtime。",
        },
        {
            "编号": "2",
            "问题": "套装方案入口过重、像是在做方案对比",
            "闭环状态": "已收窄为目标套装输入",
            "验收入口": "侧栏 -> 目标套装方案 / 套装效果预览",
            "证据": "侧栏只选择 4+2、2+2+2 或不限套装，并展示对应 2/4 件套效果；不再提供方案管理、保存、自由组合或方案对比入口。",
        },
        {
            "编号": "3",
            "问题": "目标套装概率和资源成本意义不明",
            "闭环状态": "已增加概率与资源假设说明",
            "验收入口": "侧栏 -> 概率模型参数；调律策略比较 -> 概率与资源假设",
            "证据": "目标套装概率、母盘、校音器、共鸣核均有解释；ZZZ/HSR 指定目标口径为 100%，不再把校音器/共鸣核折算成母盘参数。",
        },
        {
            "编号": "4",
            "问题": "副词条只按顺序配置",
            "闭环状态": "已改为优先级分组输入",
            "验收入口": "侧栏 -> 副词条优先级",
            "证据": "用户只选择副词条优先级顺序，算法按顺位排序，不要求也不生成副词条小数系数。",
        },
        {
            "编号": "5",
            "问题": "评分目标必要性不清楚",
            "闭环状态": "已降级为高级可选项并加解释",
            "验收入口": "侧栏 -> 评分目标",
            "证据": "默认可不改；说明有效词条目标线、质量分目标线和评级线只影响观察线/显示分界。",
        },
        {
            "编号": "6",
            "问题": "2K 屏盘面过大且布局不符合 ZZZ",
            "闭环状态": "已改成固定宽度 2x3 矩阵布局",
            "验收入口": "当前装备评分 -> 盘面方块；侧栏 -> 盘面显示密度",
            "证据": "棋盘容器不再随 2K 宽屏拉满；ZZZ 使用上排 1/2/3、下排 4/5/6；盘面状态移到下方摘要，不再挤占中间格。",
        },
        {
            "编号": "7",
            "问题": "盘面模板能不能按角色保存",
            "闭环状态": "已支持角色维度本地保存",
            "验收入口": "当前装备评分 -> 盘面状态摘要下方保存当前盘面 / 盘面模板",
            "证据": "保存入口前置；加载、删除当前盘面模板；源码模式写入 user_data，打包版写入用户数据目录。",
        },
        {
            "编号": "8",
            "问题": "盘面编辑校验和保存反馈不友好",
            "闭环状态": "已增加实时更新、盘面状态摘要和保存前检查",
            "验收入口": "当前装备评分 -> 每个盘面弹窗 / 盘面状态摘要 / 盘面模板",
            "证据": "单盘编辑会实时写入当前会话并重新校验；等级、可见副词条、roll 预算自动约束；状态摘要显示保存就绪、自动校验和保存路径。",
        },
        {
            "编号": "9",
            "问题": "校音器应只对应固定主属性且优先长期目标",
            "闭环状态": "已形成资源原则",
            "验收入口": "调律策略比较 -> 调律结论 / 当前调律期望管理",
            "证据": "当前补弱与长期冲突时提示校音器先留；固定主属性只消耗校音器，不涉及共鸣核。",
        },
        {
            "编号": "10",
            "问题": "不固定副属性却消耗共鸣核的矛盾",
            "闭环状态": "已把共鸣核移出常规策略，并新增固定副属性省母盘阶梯",
            "验收入口": "调律策略比较 -> 固定副属性省母盘阶梯 / 固定副属性 / 共鸣核观察",
            "证据": "普通策略不锁副属性，期望共鸣核为 0；锁副属性只在阶梯表中单独展示省母盘和期望共鸣核，不做资源折算。",
        },
        {
            "编号": "11",
            "问题": "目标套装概率 50% 与调律 100% 冲突",
            "闭环状态": "已改为指定套装 100% 口径",
            "验收入口": "概率模型参数 / 概率与资源假设",
            "证据": "ZZZ 默认目标套装概率 100%；HSR 占位模型也按指定目标 100% 展示。",
        },
        {
            "编号": "12",
            "问题": "结果页需要调律操作期望管理",
            "闭环状态": "已增加随机/固定位置收益表、固定主属性和固定副属性省母盘阶梯",
            "验收入口": "调律策略比较 -> 随机 vs 固定位置收益效率 / 固定主属性省母盘阶梯 / 固定副属性省母盘阶梯",
            "证据": "按完整概率分布做理论期望，不做抽样模拟；随机/固定都会把新盘加入库存后重求最优组合；固定主属性和固定副属性只展示省母盘、校音器、共鸣核，不做资源折算。",
        },
    ]


def first_version_next_action_rows(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
) -> list[dict[str, object]]:
    rows = [
        dict(row)
        for row in set_plan_next_action_rows(
            game,
            analysis,
            current_best,
            long_term_best,
        )
    ]
    for row in rows:
        row.setdefault("entry", "调律策略比较 -> 全局调律推荐")
    candidate_rows = _rows_by_question(
        candidate_conclusion_rows(game, character, candidate, result, analysis)
    )
    upgrade = candidate_rows.get("这个胚子值不值得继续", {})
    checkpoint = candidate_rows.get("强化观察点", {})
    recommendation = upgrade.get("结论", result.recommendation)
    action_by_recommendation = {
        "继续": "继续强化候选",
        "暂停": "暂停候选观察",
        "放弃": "放弃候选",
        "仅过渡": "仅作过渡候选",
    }
    position_name = game.position_name(candidate.position)
    rows.append(
        {
            "order": len(rows) + 1,
            "action": action_by_recommendation.get(
                recommendation,
                f"{recommendation}候选",
            ),
            "entry": "候选胚子评估 -> 下一跳止损卡 / 最终分布图",
            "target": f"{candidate.set_name} {position_name} {candidate.main_stat}",
            "tuning_scope": "候选胚子强化",
            "resource_hint": (
                f"{checkpoint.get('结论', '按下一强化节点观察')}；"
                "强化材料按节点投入，不涉及校音器/共鸣核。"
            ),
            "reason": upgrade.get("依据", result.reason),
        }
    )
    return rows


def _today_special_resource_action(tuner_text: str, core_text: str) -> str:
    if "可以用在" in tuner_text:
        tuner_action = "校音器可考虑"
    elif "可以观察" in tuner_text:
        tuner_action = "校音器只观察"
    elif "暂无需要固定主属性" in tuner_text:
        tuner_action = "校音器不用急"
    else:
        tuner_action = "校音器先留"

    if "仍建议保留为主" in core_text:
        core_action = "共鸣核保留为主"
    elif "暂无需要固定副属性" in core_text or "先保留" in core_text or "先留" in core_text:
        core_action = "共鸣核默认保留"
    else:
        core_action = "共鸣核仅观察"
    return f"{tuner_action}；{core_action}"


def today_action_summary_rows(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
) -> list[dict[str, str]]:
    action_rows = first_version_next_action_rows(
        game,
        character,
        candidate,
        result,
        analysis,
        current_best,
        long_term_best,
    )
    first_action = action_rows[0] if action_rows else {}
    guardrails = {
        row["资源/操作"]: row
        for row in resource_guardrail_rows(current_best, long_term_best, tuner_best, core_best)
    }
    tuner_text, core_text = resource_decision_text(tuner_best, core_best, long_term_best)
    resource_action = _today_special_resource_action(tuner_text, core_text)
    candidate_steps = candidate_next_step_rows(result)
    first_candidate_step = candidate_steps[0] if candidate_steps else {}
    candidate_recommendation, candidate_reason = candidate_contextual_recommendation(
        candidate,
        result,
        analysis,
    )
    position_name = game.position_name(candidate.position)

    return [
        {
            "优先级": "1",
            "主题": "先刷/调律",
            "动作": str(first_action.get("action", "按当前最弱位补强")),
            "目标": str(first_action.get("target", strategy_brief(current_best))),
            "理由": str(first_action.get("resource_hint", first_action.get("reason", "-"))),
            "入口": str(first_action.get("entry", "调律策略比较 -> 全局调律推荐")),
        },
        {
            "优先级": "2",
            "主题": "特殊资源",
            "动作": resource_action,
            "目标": "校音器 / 共鸣核",
            "理由": (
                f"{guardrails.get('校音器', {}).get('当前结论', '-')}"
                f" {guardrails.get('共鸣核', {}).get('当前结论', '-')}"
            ),
            "入口": "验收总览 -> 当前调律期望管理 / 调律策略比较 -> 固定主属性省母盘阶梯",
        },
        {
            "优先级": "3",
            "主题": "候选胚子",
            "动作": str(first_candidate_step.get("动作", candidate_recommendation)),
            "目标": f"{candidate.set_name} {position_name} {candidate.main_stat}",
            "理由": (
                f"当前建议：{candidate_recommendation}。"
                f"{first_candidate_step.get('依据', candidate_reason)}"
            ),
            "入口": "候选胚子评估 -> 下一跳止损卡",
        },
        {
            "优先级": "4",
            "主题": "长期提醒",
            "动作": "保留长期目标；特殊资源不要追短期弱位",
            "目标": strategy_brief(long_term_best),
            "理由": strategy_alignment_text(current_best, long_term_best),
            "入口": "验收总览 -> 六个核心问题 / 调律策略比较 -> 全局调律推荐",
        },
    ]


def _guardrail_target_label(row: StrategyRow | None) -> str:
    if row is None:
        return "暂无可用目标"
    main_stat = row.target_main_stat if row.target_main_stat != "不定" else "不定主属性"
    return f"{strategy_target_set_scope(row)} {row.target_position_name} {main_stat}"


def _guardrail_cost_label(row: StrategyRow | None) -> str:
    if row is None:
        return "-"
    parts = [f"母盘 {expected_cost_label(row.expected_mother_disks)}"]
    if row.expected_tuners > 0:
        parts.append(f"校音器 {expected_cost_label(row.expected_tuners)}")
    if row.expected_cores > 0:
        parts.append(f"共鸣核 {expected_cost_label(row.expected_cores)}")
    return "，".join(parts)


def resource_guardrail_rows(
    current_best: StrategyRow | None,
    long_term_best: StrategyRow | None,
    tuner_best: StrategyRow | None,
    core_best: StrategyRow | None,
) -> list[dict[str, str]]:
    tuner_text, core_text = resource_decision_text(tuner_best, core_best, long_term_best)
    current_target = _guardrail_target_label(current_best)
    long_target = _guardrail_target_label(long_term_best)
    current_cost = _guardrail_cost_label(current_best)
    long_cost = _guardrail_cost_label(long_term_best)

    return [
        {
            "资源/操作": "随机位置母盘",
            "默认动作": "只顺手筛",
            "启用条件": "多个位置都能接受，或当前没有明确单点弱位。",
            "当前结论": (
                "当前已有明确目标时，不把 1/6 位置随机当主路线；"
                "先参考固定位置母盘口径。"
            ),
        },
        {
            "资源/操作": "固定位置母盘",
            "默认动作": "当前补弱首选",
            "启用条件": "最弱位置或套装缺口明确，且不需要动校音器/共鸣核。",
            "当前结论": f"当前补弱看 {current_target}；期望资源 {current_cost}。",
        },
        {
            "资源/操作": "校音器",
            "默认动作": "先留",
            "启用条件": (
                "只用于固定主属性；当短期补弱与长期目标一致，且折算后仍明显划算时再用。"
            ),
            "当前结论": f"{tuner_text} 长期参考 {long_target}；期望资源 {long_cost}。",
        },
        {
            "资源/操作": "共鸣核",
            "默认动作": "默认保留",
            "启用条件": "只用于固定副属性，属于极限毕业观察，不纳入常规补弱决策。",
            "当前结论": core_text,
        },
    ]


def candidate_outcome_rows(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
) -> list[dict[str, str]]:
    current_score = score_for_position(analysis, candidate.position)
    position_name = game.position_name(candidate.position)
    good_threshold = character.rating_thresholds.get("good", 4.0)
    excellent_threshold = character.rating_thresholds.get("excellent", 6.0)
    target_threshold = character.target_effective_rolls
    weighted_target_threshold = character.weighted_target_score
    rows = [
        {
            "目标": "达到角色目标线",
            "概率": _probability_label(
                sum(
                    point.probability
                    for point in result.distribution
                    if point.effective_rolls >= target_threshold
                )
            ),
            "依据": f"最终有效词条次数达到 {target_threshold:g} 或以上。",
        },
        {
            "目标": "达到质量目标线",
            "概率": _probability_label(
                sum(
                    point.probability
                    for point in result.weighted_distribution
                    if point.weighted_score >= weighted_target_threshold
                )
            ),
            "依据": f"最终质量分达到 {weighted_target_threshold:g} 或以上。",
        },
        {
            "目标": "达到 good 评级",
            "概率": _probability_label(
                sum(
                    point.probability
                    for point in result.weighted_distribution
                    if point.weighted_score >= good_threshold
                )
            ),
            "依据": f"最终质量分达到 {good_threshold:g} 或以上。",
        },
        {
            "目标": "达到 excellent 评级",
            "概率": _probability_label(
                sum(
                    point.probability
                    for point in result.weighted_distribution
                    if point.weighted_score >= excellent_threshold
                )
            ),
            "依据": f"最终质量分达到 {excellent_threshold:g} 或以上。",
        },
    ]
    if current_score is None:
        rows.insert(
            0,
            {
                "目标": "超过当前同位置",
                "概率": "-",
                "依据": f"当前装备里没有 {position_name} 的对比盘。",
            },
        )
    elif current_score.locked:
        rows.insert(
            0,
            {
                "目标": "超过当前同位置",
                "概率": "-",
                "依据": f"当前 {position_name} 已标记保留锁定，不作为替换目标计算。",
            },
        )
    else:
        rows.insert(
            0,
            {
                "目标": "超过当前同位置",
                "概率": _probability_label(
                    sum(
                        point.probability
                        for point in result.weighted_distribution
                        if point.weighted_score > current_score.weighted_score
                    )
                ),
                "依据": (
                    f"当前 {position_name} 质量分 {current_score.weighted_score:g}；"
                    "按最终质量分严格超过当前盘计算。"
                ),
            },
        )
    slot_plan_row = _slot_plan_for_candidate(analysis, candidate)
    if slot_plan_row is None:
        rows.insert(
            1,
            {
                "目标": "命中套装目标并超过当前",
                "概率": "-",
                "依据": "当前没有可用套装目标。",
            },
        )
    elif current_score is None:
        rows.insert(
            1,
            {
                "目标": "命中套装目标并超过当前",
                "概率": "-",
                "依据": f"候选套装{_slot_plan_match_text(candidate, slot_plan_row)}；缺少当前同位置对比盘。",
            },
        )
    elif current_score.locked:
        rows.insert(
            1,
            {
                "目标": "命中套装目标并超过当前",
                "概率": "-",
                "依据": f"候选套装{_slot_plan_match_text(candidate, slot_plan_row)}；当前位已锁定，不作为替换目标计算。",
            },
        )
    elif _candidate_matches_slot_plan(candidate, slot_plan_row):
        rows.insert(
            1,
            {
                "目标": "命中套装目标并超过当前",
                "概率": _probability_label(
                    sum(
                        point.probability
                        for point in result.weighted_distribution
                        if point.weighted_score > current_score.weighted_score
                    )
                ),
                "依据": (
                    f"套装目标：{slot_plan_row['status']}，"
                    f"目标 {slot_plan_row['target_group']}；"
                    f"当前 {position_name} 质量分 {current_score.weighted_score:g}。"
                ),
            },
        )
    else:
        rows.insert(
            1,
            {
                "目标": "命中套装目标并超过当前",
                "概率": "-",
                "依据": (
                    f"套装目标：{slot_plan_row['status']}，"
                    f"目标 {slot_plan_row['target_group']}；"
                    f"候选为 {candidate.set_name}，不匹配规划目标。"
                ),
            },
        )
    return rows


def _set_requirement_label(item: dict) -> str:
    label = item.get("label", item["set_name"])
    if item.get("set_names"):
        return f"{label}（当前按 {item['set_name']}）"
    return label


def _probability_label(value: float) -> str:
    return f"{value:.1%}"


def _candidate_substat_summary(candidate: CandidatePiece, character: CharacterPreset) -> str:
    if not candidate.substats:
        return "尚未填写副属性。"
    parts = []
    for line in candidate.substats:
        label = character.priority_group_for(line.stat) or "无效"
        parts.append(f"{line.stat}（{label}，roll {line.rolls}）")
    return "；".join(parts)


def candidate_contextual_recommendation(
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
) -> tuple[str, str]:
    current_score = score_for_position(analysis, candidate.position)
    if current_score is None or not current_score.locked:
        return result.recommendation, result.reason
    return (
        "仅过渡",
        (
            f"{result.reason} 但当前 {current_score.position_name} 已标记保留锁定，"
            "不建议为了替换该位置继续重投入；除非作为其他角色/备用盘，否则仅按过渡盘处理。"
        ),
    )


def _candidate_main_status(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
) -> tuple[str, str]:
    preferred = character.preferred_mains_for(candidate.position)
    position_name = game.position_name(candidate.position)
    if not preferred:
        return "未限制", f"{position_name} 当前没有设置主属性倾向。"
    preferred_label = "、".join(preferred)
    if candidate.main_stat in preferred:
        return "命中目标", f"{position_name} 目标主属性：{preferred_label}。"
    return "偏离目标", f"{position_name} 目标主属性：{preferred_label}，当前为 {candidate.main_stat}。"


def _candidate_stage_name(item: dict) -> str:
    role = str(item.get("role", ""))
    required = int(item.get("required", 0))
    if role.startswith("core") or required >= 4:
        return "核心 4 件"
    return f"{required} 件套"


def _candidate_requirement_options(item: dict) -> list[str]:
    return list(item.get("set_names") or [item["set_name"]])


def _candidate_set_status(
    candidate: CandidatePiece,
    analysis: CurrentGearAnalysis,
) -> tuple[str, str]:
    if not analysis.set_plan:
        return "未配置", "当前角色没有套装方案。"
    if analysis.set_plan["is_unrestricted"]:
        return "不限套装", f"当前方案为 {analysis.set_plan['name']}，套装不影响候选结论。"

    target_sets = analysis.set_plan["target_sets"]
    pressure = analysis.set_plan["position_pressures"].get(position_key(candidate.position), {})
    pressure_label = pressure.get("replacement_badge", "保留")
    pressure_value = pressure.get("replacement_pressure", 0.0)
    target_label = "、".join(target_sets)
    missing = analysis.set_plan.get("missing") or []
    if missing:
        first_missing = missing[0]
        stage_options = _candidate_requirement_options(first_missing)
        stage_label = "、".join(stage_options)
        stage_name = _candidate_stage_name(first_missing)
        if candidate.set_name in stage_options:
            return (
                "命中当前缺口",
                (
                    f"当前优先阶段是 {stage_name}：{stage_label}，"
                    f"候选 {candidate.set_name} 可以直接补这个缺口；"
                    f"该位置当前替换标签：{pressure_label}，让位压力 {pressure_value:g}。"
                ),
            )
        if candidate.set_name in target_sets:
            return (
                "符合长期方案",
                (
                    f"候选 {candidate.set_name} 属于目标方案（{target_label}），"
                    f"但当前优先缺口是 {stage_name}：{stage_label}；"
                    f"该位置当前替换标签：{pressure_label}。"
                ),
            )
        return (
            "不补当前方案",
            (
                f"当前优先缺口是 {stage_name}：{stage_label}；"
                f"候选为 {candidate.set_name}，不在目标方案 {target_label} 内；"
                f"该位置当前替换标签：{pressure_label}。"
            ),
        )

    if candidate.set_name in target_sets:
        return (
            "符合方案",
            (
                f"当前方案目标套装：{target_label}，且套装阶段已满足；"
                f"该位置当前替换标签：{pressure_label}。"
            ),
        )
    return (
        "不符合方案",
        (
            f"当前方案目标套装：{target_label}，且套装阶段已满足；"
            f"候选为 {candidate.set_name}，该位置当前替换标签：{pressure_label}。"
        ),
    )


def _slot_plan_for_candidate(
    analysis: CurrentGearAnalysis,
    candidate: CandidatePiece,
) -> dict | None:
    if not analysis.set_plan:
        return None
    for row in analysis.set_plan.get("position_targets", []):
        if position_key(row["position"]) == position_key(candidate.position):
            return row
    return None


def _candidate_matches_slot_plan(candidate: CandidatePiece, slot_plan_row: dict) -> bool:
    options = slot_plan_row.get("target_options") or [slot_plan_row.get("target_set")]
    return candidate.set_name in options


def _slot_plan_match_text(candidate: CandidatePiece, slot_plan_row: dict) -> str:
    if _candidate_matches_slot_plan(candidate, slot_plan_row):
        return f"命中规划目标 {slot_plan_row['target_group']}"
    return f"不匹配规划目标 {slot_plan_row['target_group']}（候选为 {candidate.set_name}）"


def _candidate_slot_plan_status(
    game: GameRules,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
) -> tuple[str, str]:
    slot_plan_row = _slot_plan_for_candidate(analysis, candidate)
    position_name = game.position_name(candidate.position)
    if slot_plan_row is None:
        if analysis.set_plan and analysis.set_plan.get("is_unrestricted"):
            return "不限套装", "当前方案不限制槽位套装，候选只按主属性和副词条质量判断。"
        return "未配置", "当前没有可用套装目标。"

    current_score = score_for_position(analysis, candidate.position)
    current_score_text = (
        f"当前 {position_name} 质量分 {current_score.weighted_score:g}；"
        if current_score
        else f"当前没有 {position_name} 对比盘；"
    )
    weighted_gain = (
        result.final_expected_weighted_score - current_score.weighted_score
        if current_score
        else result.final_expected_weighted_score
    )
    match_text = _slot_plan_match_text(candidate, slot_plan_row)
    basis = (
        f"套装目标：{slot_plan_row['status']}，"
        f"动作 {slot_plan_row['action']}，"
        f"目标 {slot_plan_row['target_group']}；"
        f"候选套装{match_text}；"
        f"{current_score_text}"
        f"候选满级质量期望 {result.final_expected_weighted_score:g}，"
        f"相对变化 {weighted_gain:+g}。"
    )

    if current_score and current_score.locked:
        return "锁定位置，仅备用", f"{basis} 当前位已锁定，不建议作为替换目标继续重投入。"
    if _candidate_matches_slot_plan(candidate, slot_plan_row):
        status = slot_plan_row.get("status", "")
        if status == "建议让位":
            return "命中让位目标", basis
        if status == "候补让位":
            return "命中候补目标", basis
        if status in {"规划保留", "锁定保留"}:
            return "命中保留目标", basis
        if status == "质量优化":
            return "套装不冲突", basis
        return "命中规划目标", basis

    status = slot_plan_row.get("status", "")
    if status in {"建议让位", "候补让位"}:
        return "不补规划缺口", basis
    if status in {"规划保留", "锁定保留"}:
        return "偏离保留目标", basis
    return "偏离规划目标", basis


def _candidate_fit_status(
    game: GameRules,
    character: CharacterPreset,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
    set_conclusion: str,
) -> tuple[str, str]:
    current_score = score_for_position(analysis, candidate.position)
    position_name = game.position_name(candidate.position)
    if current_score is None:
        return "缺少当前盘", f"当前装备里没有 {position_name}，只能看胚子自身期望。"
    weighted_gain = result.final_expected_weighted_score - current_score.weighted_score
    preferred = character.preferred_mains_for(candidate.position)
    main_ok = not preferred or candidate.main_stat in preferred
    main_text = (
        "主属性命中目标"
        if main_ok
        else f"主属性偏离目标（目标：{'、'.join(preferred)}）"
    )
    weakest_text = (
        "当前最弱位"
        if position_key(analysis.weakest_position) == position_key(candidate.position)
        else "非当前最弱位"
    )
    pressure = (
        analysis.set_plan["position_pressures"].get(position_key(candidate.position), {})
        if analysis.set_plan
        else {}
    )
    badge = pressure.get("replacement_badge", "保留")
    pressure_value = pressure.get("replacement_pressure", 0.0)
    basis = (
        f"{position_name} 是{weakest_text}；{main_text}；"
        f"套装判断：{set_conclusion}；替换标签 {badge}，让位压力 {pressure_value:g}；"
        f"候选满级质量期望较当前 {weighted_gain:+g}。"
    )

    if current_score.locked:
        return "仅备用/过渡", f"{basis} 当前位已锁定，不按替换该位置计算补位价值。"
    if set_conclusion == "命中当前缺口" and main_ok:
        if (
            weighted_gain >= 1.0
            or position_key(analysis.weakest_position) == position_key(candidate.position)
            or badge == "优先替换"
        ):
            return "当前强补位", basis
        return "套装补位", basis
    if set_conclusion == "命中当前缺口":
        return "套装过渡", basis
    if (
        position_key(analysis.weakest_position) == position_key(candidate.position)
        and main_ok
        and weighted_gain > 0
    ):
        return "当前补弱", basis
    if set_conclusion in {"符合长期方案", "符合方案"} and main_ok:
        if result.recommendation in {"继续", "暂停"}:
            return "长期观察", basis
        return "长期过渡", basis
    if weighted_gain > 0 and main_ok:
        return "仅词条观察", basis
    return "低补位价值", basis


def _candidate_checkpoint_status(result: CandidateEvaluation) -> tuple[str, str]:
    if not result.event_rows:
        return (
            "已无强化观察点",
            "当前候选没有剩余强化事件，直接按最终期望和结果分布判断。",
        )
    first = result.event_rows[0]
    level = int(first["level"])
    event = str(first["event"])
    hit_probability = float(first["hit_probability"])
    expected_weighted_gain = float(first["expected_weighted_gain"])

    if result.recommendation == "继续":
        stop_rule = "命中配置内有效词条就继续；若没有质量收益，转为暂停观察。"
    elif result.recommendation == "暂停":
        stop_rule = "只有命中高优先级词条才继续；歪到低优先级或无效词条就先停。"
    elif result.recommendation == "仅过渡":
        stop_rule = "只建议低成本观察；没有命中核心词条就止损，当过渡盘处理。"
    else:
        stop_rule = "整体期望偏低，不建议继续投入；除非只是验证一次低成本事件。"

    if event == "补第 4 副属性":
        conclusion = f"+{level} 看补出的第 4 词条"
        detail = "先补第 4 个副属性"
    else:
        conclusion = f"+{level} 看是否命中有效词条"
        detail = "随机命中已有副属性"

    return (
        conclusion,
        (
            f"下一跳是 +{level} {detail}；命中有效概率 {hit_probability:.1%}，"
            f"质量期望增量 {expected_weighted_gain:.2f}。{stop_rule}"
        ),
    )


def _candidate_replacement_status(
    game: GameRules,
    candidate: CandidatePiece,
    result: CandidateEvaluation,
    analysis: CurrentGearAnalysis,
) -> tuple[str, str]:
    current_score = score_for_position(analysis, candidate.position)
    position_name = game.position_name(candidate.position)
    if current_score is None:
        return "缺少当前盘", f"当前装备里没有 {position_name} 的评分。"
    if current_score.locked:
        return (
            "当前位已锁定",
            (
                f"当前 {position_name} 已标记保留锁定；候选可以看自身期望，"
                "但不计入替换该位置的收益。"
            ),
        )

    raw_gain = result.final_expected_effective_rolls - current_score.effective_rolls
    weighted_gain = result.final_expected_weighted_score - current_score.weighted_score
    if weighted_gain >= 1.0:
        conclusion = "明显有望替换"
    elif weighted_gain > 0:
        conclusion = "小幅有望替换"
    else:
        conclusion = "暂不优于当前盘"
    basis = (
        f"当前 {position_name}：{current_score.effective_rolls:g} 有效 / "
        f"{current_score.weighted_score:g} 质量分；候选满级期望："
        f"{result.final_expected_effective_rolls:g} 有效 / "
        f"{result.final_expected_weighted_score:g} 质量分；"
        f"期望差：{raw_gain:+g} 有效 / {weighted_gain:+g} 质量分。"
    )
    return conclusion, basis


def _candidate_probability_list(result: CandidateEvaluation) -> str:
    if not result.event_rows:
        return "无剩余强化事件。"
    return "；".join(
        f"+{row['level']} {row['event']} {row['hit_probability']:.1%}"
        for row in result.event_rows
    )
