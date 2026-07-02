import pytest
from streamlit.testing.v1 import AppTest

from gear_optimizer.game_rules import load_characters, load_probability_models
from gear_optimizer.models import CandidatePiece, GearPiece, SubstatLine
from gear_optimizer.user_current_gear import save_user_current_gear

pytestmark = pytest.mark.streamlit_ui


def test_app_shows_rules_overview_and_hsr_can_render():
    app = AppTest.from_file("app.py")
    app.run(timeout=30)
    tables = list(app.dataframe) + list(app.table)

    assert not app.exception
    assert any(expander.label == "盘面模板" for expander in app.expander)
    assert any(expander.label == "规则概览" for expander in app.expander)
    assert any(expander.label == "导入/导出" for expander in app.expander)
    assert any(expander.label == "候选 YAML" for expander in app.expander)
    assert any(expander.label == "概率模型 YAML" for expander in app.expander)
    assert any(expander.label == "概率模型参数" for expander in app.expander)
    assert any(expander.label == "概率模型导出" for expander in app.expander)
    assert any(
        widget.label == "盘面显示密度"
        and widget.value == "紧凑"
        and widget.options == ["紧凑", "标准", "宽松"]
        for widget in app.selectbox
    )
    assert any("盘面方块尺寸：6.2rem" in caption.value for caption in app.caption)
    assert any("--gear-tile-size: 6.2rem" in markdown.value for markdown in app.markdown)
    assert any("--gear-board-width" in markdown.value for markdown in app.markdown)
    assert any("st-key-gear_board_shell_" in markdown.value for markdown in app.markdown)
    assert any("button svg" in markdown.value and "display: none" in markdown.value for markdown in app.markdown)
    assert any(
        "绝区零指定套装调律时，目标套装概率按 100% 处理" in info.value
        for info in app.info
    )
    assert any(
        {"参数", "怎么理解"}.issubset(set(table.value.columns))
        and "目标套装概率" in set(table.value["参数"])
        and any("指定套装调律为 100%" in value for value in table.value["怎么理解"])
        and any("只锁主属性" in value for value in table.value["怎么理解"])
        and any("不作为常规补弱路径" in value for value in table.value["怎么理解"])
        for table in app.table
    )
    assert any(expander.label == "当前目标摘要" for expander in app.expander)
    assert any(widget.label == "当前装备示例" for widget in app.selectbox)
    assert any(button.label == "载入示例盘面" for button in app.button)
    assert any(button.label == "清空为手动输入" for button in app.button)
    assert any(widget.label == "盘面模板名称" for widget in app.text_input)
    assert any(button.label == "保存当前盘面" for button in app.button)
    assert any(markdown.value == "保存当前盘面" for markdown in app.markdown)
    assert any("盘位编辑会实时写入当前会话" in caption.value for caption in app.caption)
    assert any(markdown.value == "盘面状态摘要" for markdown in app.markdown)
    assert any(
        {"项目", "状态", "说明"}.issubset(set(getattr(table.value, "columns", [])))
        and {
            "保存就绪",
            "盘面完整度",
            "自动校验",
            "等级 / roll 约束",
            "保存路径",
        }.issubset(set(table.value["项目"]))
        and "可保存" in set(table.value["状态"])
        and "本机用户数据" in set(table.value["状态"])
        for table in app.table
    )
    assert any(markdown.value == "保存前检查" for markdown in app.markdown)
    assert any(
        {"检查项", "状态", "说明"}.issubset(set(getattr(table.value, "columns", [])))
        and "盘面完整度" in set(table.value["检查项"])
        and "等级 / roll / 词条" in set(table.value["检查项"])
        and "保存位置" in set(table.value["检查项"])
        and "本机用户数据" in set(table.value["状态"])
        for table in app.table
    )
    assert any(expander.label == "评分目标" for expander in app.expander)
    assert any(widget.label == "有效词条目标线" for widget in app.number_input)
    assert any(widget.label == "质量分目标线" for widget in app.number_input)
    assert any(widget.label == "usable 评级线" for widget in app.number_input)
    assert any(widget.label == "good 评级线" for widget in app.number_input)
    assert any(widget.label == "excellent 评级线" for widget in app.number_input)
    assert any(
        "高级可选项：普通使用不必改" in info.value
        for info in app.info
    )
    assert any(button.label == "恢复角色模板评分目标" for button in app.button)
    assert any(
        {"参数", "是否必须", "影响"}.issubset(set(getattr(table.value, "columns", [])))
        and "有效词条目标线" in set(table.value["参数"])
        and "否，默认即可" in set(table.value["是否必须"])
        for table in app.table
    )
    assert any(
        "评级线只决定 weak / usable / good / excellent" in caption.value
        for caption in app.caption
    )
    assert any("只需要按顺序选择副词条，不需要填写小数" in info.value for info in app.info)
    assert any(markdown.value == "当前优先级预览" for markdown in app.markdown)
    assert any(
        {"分组", "顺位", "副词条", "算法作用"}.issubset(
            set(getattr(table.value, "columns", []))
        )
        and "核心" in set(table.value["分组"])
        and "暴击率" in set(table.value["副词条"])
        and any("优先作为评分" in value for value in table.value["算法作用"])
        for table in app.table
    )
    assert any(
        {"套装方案", "套装要求", "主属性倾向", "副词条优先级"}.issubset(
            set(table.value["项目"])
        )
        for table in app.table
        if "项目" in getattr(table.value, "columns", [])
    )
    assert any(expander.label == "目标套装方案" for expander in app.expander)
    assert any(
        widget.label == "目标结构"
        and widget.value == "4+2"
        and widget.options == ["4+2", "2+2+2", "不限套装"]
        for widget in app.selectbox
    )
    assert any(widget.label == "4 件套" and widget.value == "云岿如我" for widget in app.selectbox)
    assert any(widget.label == "2 件套" and widget.value == "折枝剑歌" for widget in app.selectbox)
    assert not any(expander.label == "套装方案管理" for expander in app.expander)
    assert any(markdown.value == "当前结论" for markdown in app.markdown)
    assert not any(markdown.value == "第一版验收速览" for markdown in app.markdown)
    assert any(subheader.value == "第一版验收总览" for subheader in app.subheader)
    assert any(markdown.value == "六个核心问题" for markdown in app.markdown)
    assert any(expander.label == "核算细节：高优先级问题闭环" for expander in app.expander)
    assert any(
        "校音器该不该用？" in markdown.value
        and "校音器：先别急用" in markdown.value
        for markdown in app.markdown
    )
    assert any(
        {"编号", "问题", "闭环状态", "验收入口", "证据"}.issubset(
            set(getattr(dataframe.value, "columns", []))
        )
        and "1" in set(dataframe.value["编号"])
        and "12" in set(dataframe.value["编号"])
        and "已增加随机/固定位置收益表、固定主属性和固定副属性省母盘阶梯" in set(dataframe.value["闭环状态"])
        for dataframe in app.dataframe
    )
    assert any(expander.label == "核算细节：当前调律期望管理" for expander in app.expander)
    assert any(
        "固定主属性只展示省母盘和期望校音器，不做资源折算"
        in caption.value
        for caption in app.caption
    )
    assert any(
        {"验收问题", "当前答案", "依据", "入口"}.issubset(
            set(getattr(dataframe.value, "columns", []))
        )
        and "这个新胚子还值不值得强化？" in set(dataframe.value["验收问题"])
        and "见候选页" not in set(dataframe.value["当前答案"])
        and "候选胚子评估" in set(dataframe.value["入口"])
        for dataframe in app.dataframe
    )
    assert any(expander.label == "核算细节：今日行动摘要" for expander in app.expander)
    assert any(
        {"优先级", "主题", "动作", "目标", "理由", "入口"}.issubset(
            set(getattr(table.value, "columns", []))
        )
        and {"先刷/调律", "特殊资源", "候选胚子", "长期提醒"}.issubset(
            set(table.value["主题"])
        )
        and any("校音器先留" in value for value in table.value["动作"])
        and any("强化到 +" in value for value in table.value["动作"])
        for table in app.table
    )
    assert any(expander.label == "核算细节：下一步操作卡" for expander in app.expander)
    assert any(
        {"行动", "入口", "目标", "调律范围", "资源提示", "原因"}.issubset(
            set(getattr(table.value, "columns", []))
        )
        and "先补 2 件套" in set(table.value["行动"])
        and "保留长期目标" in set(table.value["行动"])
        and any("候选" in action for action in set(table.value["行动"]))
        and any("套装阶段拆解" in entry for entry in set(table.value["入口"]))
        and any("候选胚子评估" in entry for entry in set(table.value["入口"]))
        and "候选胚子强化" in set(table.value["调律范围"])
        for table in app.table
    )
    assert not any(markdown.value == "资源投入守则" for markdown in app.markdown)
    assert not any(markdown.value == "当前/长期投入对照" for markdown in app.markdown)
    assert any(expander.label == "核算细节：随机 vs 固定位置收益效率" for expander in app.expander)
    assert any(expander.label == "核算细节：固定主属性省母盘阶梯" for expander in app.expander)
    assert any(expander.label == "核算细节：固定副属性省母盘阶梯" for expander in app.expander)
    assert any(expander.label == "核算细节：胚子挡位概率解释" for expander in app.expander)
    assert any(
        {"策略", "目标套装", "位置", "期望提升", "质量/母盘", "有效/母盘", "相对随机"}.issubset(
            set(getattr(dataframe.value, "columns", []))
        )
        and "随机位置" in set(dataframe.value["策略"])
        and "1-6 随机" in set(dataframe.value["位置"])
        for dataframe in app.dataframe
    )
    assert any(
        {"位置", "当前补弱顺位", "提升目标", "不锁主属性有效提升", "固定主属性有效提升", "不锁主属性母盘", "固定主属性母盘", "省母盘", "期望校音器"}.issubset(
            set(getattr(dataframe.value, "columns", []))
        )
        and "6号位" in set(dataframe.value["位置"])
        and "+1" in set(dataframe.value["提升目标"])
        for dataframe in app.dataframe
    )
    assert any(
        {"位置", "锁定副属性", "固定主属性有效提升", "锁副属性有效提升", "锁副属性母盘", "省母盘", "期望共鸣核"}.issubset(
            set(getattr(dataframe.value, "columns", []))
        )
        and "6号位" in set(dataframe.value["位置"])
        and "暴击率 + 暴击伤害" in set(dataframe.value["锁定副属性"])
        for dataframe in app.dataframe
    )
    assert any("盘面状态" in markdown.value for markdown in app.markdown)
    assert any(
        "data:image/png;base64" in markdown.value
        and "gear_tile_zzz_6" in markdown.value
        for markdown in app.markdown
    )
    assert any(
        "gear_tile_zzz_6" in markdown.value
        and "plan_yield" in markdown.value
        for markdown in app.markdown
    )
    assert any("保留此盘" in checkbox.label for checkbox in app.checkbox)
    assert any(
        {
            "当前哪件最弱",
            "现在优先固定/刷哪里",
            "套装先补 4 还是 2",
            "校音器该不该用",
            "共鸣核该不该留",
            "长期和当前是否冲突",
        }.issubset(set(dataframe.value["问题"]))
        for dataframe in tables
        if "问题" in getattr(dataframe.value, "columns", [])
    )
    assert any(expander.label == "套装保留/让位判断" for expander in app.expander)
    assert any(
        {"规划目标", "规划动作", "规划状态"}.issubset(set(table.value["项目"]))
        and "建议让位" in set(table.value["当前值"])
        and "调律为折枝剑歌" in set(table.value["当前值"])
        for table in app.table
        if "项目" in getattr(table.value, "columns", [])
        and "当前值" in getattr(table.value, "columns", [])
    )
    assert any(
        {"优先级", "主题", "行动", "理由"}.issubset(
            set(getattr(table.value, "columns", []))
        )
        and {"母盘", "当前补弱", "特殊资源", "长期目标"}.issubset(
            set(table.value["主题"])
        )
        and any("最弱：6号位" in value for value in table.value["理由"])
        for table in app.table
    )
    assert any(
        "副词条明细" in getattr(dataframe.value, "columns", [])
        for dataframe in app.dataframe
    )
    assert any(
        {"有效词条", "质量分", "相对提升优先级"}.issubset(
            set(getattr(dataframe.value, "columns", []))
        )
        for dataframe in app.dataframe
    )
    assert any("套装阶段：先补 2 件套" in info.value for info in app.info)
    assert any(expander.label == "核算细节：概率与套装阶段" for expander in app.expander)
    assert any(
        {"阶段", "目标", "进度", "缺口", "排序分", "算法依据", "当前动作", "推荐让位"}.issubset(
            set(getattr(table.value, "columns", []))
        )
        for table in tables
    )
    assert any("校音器：先别急用" in info.value for info in app.info)
    assert any("共鸣核：先留" in warning.value for warning in app.warning)
    assert any(markdown.value == "候选结论" for markdown in app.markdown)
    assert any(markdown.value == "下一跳止损卡" for markdown in app.markdown)
    assert any(
        {"场景", "动作", "依据"}.issubset(
            set(getattr(dataframe.value, "columns", []))
        )
        and "当前动作" in set(dataframe.value["场景"])
        and any("强化到 +" in action for action in dataframe.value["动作"])
        and "未命中或歪到低价值" in set(dataframe.value["场景"])
        for dataframe in app.dataframe
    )
    assert any(markdown.value == "候选验收速览" for markdown in app.markdown)
    assert any(
        {"验收问题", "当前答案", "怎么继续看"}.issubset(
            set(getattr(dataframe.value, "columns", []))
        )
        and "这个新胚子还值不值得强化？" in set(dataframe.value["验收问题"])
        and "下一跳该看什么？" in set(dataframe.value["验收问题"])
        for dataframe in app.dataframe
    )
    assert any(markdown.value == "候选结果概率" for markdown in app.markdown)
    assert any(
        {
            "这个胚子值不值得继续",
            "替换当前同位置提升",
            "主属性是否符合目标",
            "套装是否符合方案",
            "套装目标匹配",
            "后续命中概率",
        }.issubset(set(dataframe.value["问题"]))
        for dataframe in tables
        if "问题" in getattr(dataframe.value, "columns", [])
    )
    assert any(
        {
            "超过当前同位置",
            "达到角色目标线",
            "达到质量目标线",
            "命中套装目标并超过当前",
            "达到 good 评级",
            "达到 excellent 评级",
        }.issubset(
            set(table.value["目标"])
        )
        for table in tables
        if "目标" in getattr(table.value, "columns", [])
    )
    assert any(subheader.value == "攻略结论" for subheader in app.subheader)
    assert any(expander.label == "核算细节：资源判断和调律结论" for expander in app.expander)
    assert any(expander.label == "核算细节：策略上下文" for expander in app.expander)
    assert any(
        {"项目", "当前值", "策略影响"}.issubset(
            set(getattr(table.value, "columns", []))
        )
        and "当前套装方案" in set(table.value["项目"])
        and "当前优先阶段" in set(table.value["项目"])
        for table in tables
    )
    assert not any(markdown.value == "套装方案对比" for markdown in app.markdown)
    assert any(
        {
            "现在应该固定几号位",
            "长期绝对最优目标",
            "校音器该不该用",
            "共鸣核该不该留",
            "长期和当前是否冲突",
            "套装阶段",
        }.issubset(set(dataframe.value["问题"]))
        for dataframe in tables
        if "问题" in getattr(dataframe.value, "columns", [])
    )
    assert any(
        {"目标套装概率", "初始 3 词条概率", "母盘/随机位置", "校音器/固定主属性"}.issubset(
            set(table.value["假设"])
        )
        and "校音器折算母盘" not in set(table.value["假设"])
        for table in tables
        if "假设" in getattr(table.value, "columns", [])
    )
    assert any(markdown.value == "强化路径明细" for markdown in app.markdown)
    assert any("补第 4 副属性" in caption.value for caption in app.caption)
    assert any(
        {"等级", "事件", "命中有效概率", "质量期望增量"}.issubset(
            set(getattr(dataframe.value, "columns", []))
        )
        for dataframe in app.dataframe
    )
    assert any("概率拆解 = 套装概率" in caption.value for caption in app.caption)
    assert any(
        {
            "资源口径",
            "决策性质",
            "期望校音器",
            "期望共鸣核",
        }.issubset(set(getattr(dataframe.value, "columns", [])))
        and "固定主属性只消耗校音器；不消耗共鸣核" in set(dataframe.value["资源口径"])
        and "极限毕业观察，默认保留共鸣核" in set(dataframe.value["决策性质"])
        for dataframe in app.dataframe
    )
    assert any(expander.label == "核算细节：手动目标策略比较" for expander in app.expander)
    assert any(
        widget.label == "目标套装"
        and widget.value == "折枝剑歌"
        and "折枝剑歌" in widget.options
        for widget in app.selectbox
    )
    assert any(expander.label == "固定副属性 / 共鸣核观察" for expander in app.expander)
    assert any(
        "普通调律决策默认不锁副属性" in caption.value
        for caption in app.caption
    )
    assert any(
        widget.label == "目标副属性（极限毕业）"
        and widget.value == []
        for widget in app.multiselect
    )
    assert any(
            {"锁定范围", "可接受套装", "套装概率来源", "母盘相对上一档", "概率相对上一档", "增量解释"}.issubset(
                set(getattr(dataframe.value, "columns", []))
            )
            and "单套装 100.0%" in set(dataframe.value["套装概率来源"])
            for dataframe in app.dataframe
        )
    assert any(
        "副属性优先级" in getattr(dataframe.value, "columns", [])
        for dataframe in app.dataframe
    )
    assert any(
        "固定副词条依据" in getattr(dataframe.value, "columns", [])
        for dataframe in app.dataframe
    )
    assert any(
        "概率拆解" in getattr(dataframe.value, "columns", [])
        for dataframe in app.dataframe
    )
    assert any(
        {"套装概率", "位置概率", "主属性概率", "副属性概率"}.issubset(
            set(getattr(dataframe.value, "columns", []))
        )
        for dataframe in app.dataframe
    )
    assert any(
        "可接受套装" in getattr(dataframe.value, "columns", [])
        for dataframe in app.dataframe
    )
    assert any(
        "套装概率来源" in getattr(dataframe.value, "columns", [])
        for dataframe in app.dataframe
    )
    assert not any(markdown.value == "当前调律期望管理" for markdown in app.markdown)
    assert not any(markdown.value == "操作建议卡" for markdown in app.markdown)
    assert not any(markdown.value == "校音器盈亏线" for markdown in app.markdown)
    assert not any(markdown.value == "期望速览卡" for markdown in app.markdown)
    assert not any(markdown.value == "档位期望矩阵" for markdown in app.markdown)
    assert not any(markdown.value == "策略期望决策表" for markdown in app.markdown)
    assert any(expander.label == "核算细节：当前调律期望管理" for expander in app.expander)
    assert any(
        "固定主属性只展示省母盘和期望校音器，不做资源折算" in caption.value
        for caption in app.caption
    )
    assert any(expander.label == "核算细节：固定副属性省母盘阶梯" for expander in app.expander)

    game_select = next(widget for widget in app.selectbox if widget.label == "游戏")
    game_select.set_value("崩坏：星穹铁道 (hsr)")
    app.run(timeout=30)

    assert not app.exception
    assert any(expander.label == "规则概览" for expander in app.expander)
    assert any(widget.value == "崩坏：星穹铁道 (hsr)" for widget in app.selectbox)
    assert any(widget.label == "目标结构" and widget.value == "4+2" for widget in app.selectbox)
    assert any(widget.label == "4 件套" and widget.value == "占位遗器套装" for widget in app.selectbox)
    assert any(widget.label == "2 件套" and widget.value == "占位位面饰品套装" for widget in app.selectbox)
    assert any(
        "假设" in getattr(table.value, "columns", [])
        and "目标套装概率" in set(table.value["假设"])
        and "100.0%" in set(table.value["当前值"])
        for table in app.table
    )
    assert any("占位遗器 2 件套效果" in caption.value for caption in app.caption)
    assert any("占位位面饰品 2 件套效果" in caption.value for caption in app.caption)
    assert any(
        widget.label == "当前装备示例"
        and any("崩铁占位遗器示例" in option for option in widget.options)
        for widget in app.selectbox
    )
    assert any(
        widget.label == "候选示例" and "崩铁躯干暴击，3中1，等速度" in widget.options
        for widget in app.selectbox
    )
    assert all(
        any(part in markdown.value for markdown in app.markdown)
        for part in ["头部", "手部", "躯干", "脚部", "位面球", "连结绳"]
    )
    assert any(
        {"头部", "手部", "躯干", "脚部", "位面球", "连结绳"}.issubset(
            set(dataframe.value["位置"])
        )
        for dataframe in app.dataframe
        if "位置" in getattr(dataframe.value, "columns", [])
    )


def test_current_editor_constrains_levels_and_roll_inputs():
    app = AppTest.from_file("app.py")
    app.run(timeout=30)

    assert not app.exception

    level_widgets = [
        widget
        for widget in app.selectbox
        if widget.label in {"等级", "当前等级"}
    ]
    assert level_widgets
    assert all(widget.options == ["0", "3", "6", "9", "12", "15"] for widget in level_widgets)

    roll_widgets = [
        widget
        for widget in app.number_input
        if widget.label == "roll 次数"
    ]
    assert roll_widgets
    assert any(widget.max == 5 for widget in roll_widgets)
    assert all(widget.min == 0 for widget in roll_widgets)
    assert all(widget.value <= widget.max for widget in roll_widgets)
    assert any("当前编辑预览" in caption.value for caption in app.caption)
    assert any("roll 预算按等级和初始词条数自动限制" in caption.value for caption in app.caption)
    assert any("修改后会实时写入当前会话" in caption.value for caption in app.caption)
    assert any(markdown.value == "编辑状态" for markdown in app.markdown)
    assert not any(button.label == "应用此盘修改" for button in app.button)
    assert any(
        {"实时更新", "可见副属性", "roll 预算", "实际生效副属性", "校验"}.issubset(
            set(table.value["项目"])
        )
        for table in app.table
        if "项目" in getattr(table.value, "columns", [])
    )


def test_current_editor_surfaces_hidden_and_clamped_input_warnings():
    app = AppTest.from_file("app.py")
    app.session_state["current_1_base_level"] = 0
    app.session_state["current_1_base_initial"] = 3
    app.session_state["current_1_base_roll_0"] = 99
    app.run(timeout=30)

    assert not app.exception
    assert any("1号位 副属性 4 当前等级不可见" in caption.value for caption in app.caption)
    assert any("1号位 副属性 1 roll 次数超出剩余预算" in caption.value for caption in app.caption)
    assert any("本盘有" in warning.value and "自动校验" in warning.value for warning in app.warning)


def test_rating_threshold_inputs_are_order_protected():
    app = AppTest.from_file("app.py")
    app.session_state["rating_usable_zzz_zzz_starlight_billy_base"] = 5.0
    app.session_state["rating_good_zzz_zzz_starlight_billy_base"] = 1.0
    app.session_state["rating_excellent_zzz_zzz_starlight_billy_base"] = 2.0

    app.run(timeout=30)

    assert not app.exception
    usable_threshold = next(
        widget
        for widget in app.number_input
        if widget.label == "usable 评级线"
        and getattr(widget, "key", "")
        == "rating_usable_zzz_zzz_starlight_billy_base"
    )
    good_threshold = next(
        widget
        for widget in app.number_input
        if widget.label == "good 评级线"
        and getattr(widget, "key", "")
        == "rating_good_zzz_zzz_starlight_billy_base"
    )
    excellent_threshold = next(
        widget
        for widget in app.number_input
        if widget.label == "excellent 评级线"
        and getattr(widget, "key", "")
        == "rating_excellent_zzz_zzz_starlight_billy_base"
    )
    assert usable_threshold.value == 5.0
    assert good_threshold.value == 5.0
    assert excellent_threshold.value == 5.0


def test_target_score_reset_button_restores_character_defaults():
    app = AppTest.from_file("app.py")
    app.session_state["target_effective_rolls_zzz_zzz_starlight_billy_base"] = 3.0
    app.session_state["target_weighted_score_zzz_zzz_starlight_billy_base"] = 3.5
    app.session_state["rating_usable_zzz_zzz_starlight_billy_base"] = 1.0
    app.session_state["rating_good_zzz_zzz_starlight_billy_base"] = 2.0
    app.session_state["rating_excellent_zzz_zzz_starlight_billy_base"] = 3.0
    app.run(timeout=30)

    reset_button = next(button for button in app.button if button.label == "恢复角色模板评分目标")
    reset_button.click()
    app.run(timeout=30)

    assert not app.exception
    effective_target = next(
        widget
        for widget in app.number_input
        if widget.label == "有效词条目标线"
        and getattr(widget, "key", "")
        == "target_effective_rolls_zzz_zzz_starlight_billy_base"
    )
    weighted_target = next(
        widget
        for widget in app.number_input
        if widget.label == "质量分目标线"
        and getattr(widget, "key", "")
        == "target_weighted_score_zzz_zzz_starlight_billy_base"
    )

    assert effective_target.value == 6.0
    assert weighted_target.value == 6.0


def test_current_template_clear_refreshes_piece_editor_defaults():
    app = AppTest.from_file("app.py")
    app.run(timeout=30)

    clear_button = next(button for button in app.button if button.label == "清空为手动输入")
    clear_button.click()
    app.run(timeout=30)

    assert not app.exception
    slot6_main = next(
        widget
        for widget in app.selectbox
        if widget.label == "主属性"
        and getattr(widget, "key", "") == "current_6_base_1_main"
    )
    assert slot6_main.value == "攻击力百分比"


def test_current_import_digest_refreshes_piece_editor_defaults():
    app = AppTest.from_file("app.py")
    app.session_state["current_6_base_main"] = "攻击力百分比"
    app.session_state["current_import_digest::zzz::zzz_starlight_billy"] = (
        "fedcba9876543210"
    )
    imported_piece = GearPiece(
        position=6,
        set_name="云岿如我",
        main_stat="生命值百分比",
        level=15,
        substats=[
            SubstatLine(stat="暴击率", rolls=0),
            SubstatLine(stat="攻击力", rolls=2),
            SubstatLine(stat="防御力", rolls=2),
            SubstatLine(stat="穿透值", rolls=1),
        ],
    )
    app.session_state["current_piece_state::zzz::zzz_starlight_billy"] = {
        "6": {
            "position": 6,
            "set_name": imported_piece.set_name,
            "main_stat": imported_piece.main_stat,
            "level": imported_piece.level,
            "initial_count": 4,
            "substats": [
                {"stat": line.stat, "rolls": line.rolls}
                for line in imported_piece.substats
            ],
        }
    }

    app.run(timeout=30)

    assert not app.exception
    imported_main = next(
        widget
        for widget in app.selectbox
        if widget.label == "主属性"
        and getattr(widget, "key", "") == "current_6_fedcba987654_main"
    )
    assert imported_main.value == "生命值百分比"


def test_current_template_picker_lists_saved_user_templates(tmp_path, monkeypatch):
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path))
    save_user_current_gear(
        "zzz",
        "zzz_starlight_billy",
        [
            GearPiece(
                position=1,
                set_name="云岿如我",
                main_stat="生命值",
                level=0,
                substats=[],
            )
        ],
        "我的比利盘面",
    )
    app = AppTest.from_file("app.py")
    app.run(timeout=30)

    assert not app.exception
    assert any(
        widget.label == "当前装备示例"
        and "已保存：我的比利盘面" in widget.options
        for widget in app.selectbox
    )
    template_widget = next(widget for widget in app.selectbox if widget.label == "当前装备示例")
    template_widget.set_value("已保存：我的比利盘面")
    app.run(timeout=30)

    assert not app.exception
    assert any(button.label == "删除已保存盘面" for button in app.button)


def test_sidebar_supports_target_set_structure_configuration():
    app = AppTest.from_file("app.py")
    app.run(timeout=30)

    assert not app.exception

    structure_widget = next(widget for widget in app.selectbox if widget.label == "目标结构")
    assert structure_widget.options == ["4+2", "2+2+2", "不限套装"]

    structure_widget.set_value("2+2+2")
    app.run(timeout=30)

    assert not app.exception
    assert any(widget.label == "二件套 A" and "呼啸沙龙" in widget.options for widget in app.selectbox)
    assert any(widget.label == "二件套 B" for widget in app.selectbox)
    assert any(widget.label == "二件套 C" for widget in app.selectbox)
    assert any(
        "折枝剑歌" in str(table.value.to_dict("records"))
        and "副词条优先级" in set(table.value["项目"])
        for table in app.table
        if "项目" in getattr(table.value, "columns", [])
    )


def test_sidebar_four_two_uses_algorithmic_stage_order_and_effect_preview():
    app = AppTest.from_file("app.py")
    app.run(timeout=30)

    assert not app.exception

    structure_widget = next(widget for widget in app.selectbox if widget.label == "目标结构")
    structure_widget.set_value("4+2")
    app.run(timeout=30)

    assert not app.exception
    assert not any(radio.label == "补齐顺序" for radio in app.radio)
    assert any(
        "先补哪一段、哪一号位由当前盘面自动排序" in caption.value
        for caption in app.caption
    )
    assert any(widget.label == "4 件套" and widget.value == "云岿如我" for widget in app.selectbox)
    assert any(widget.label == "2 件套" and widget.value == "折枝剑歌" for widget in app.selectbox)
    assert any(expander.label == "套装效果预览" for expander in app.expander)
    assert not any(expander.label == "套装方案管理" for expander in app.expander)
    assert not any(button.label == "保存当前方案" for button in app.button)
    assert any("2件：暴击伤害 +16%" in caption.value for caption in app.caption)


def test_sidebar_can_switch_to_non_billy_zzz_character_template():
    app = AppTest.from_file("app.py")
    app.run(timeout=30)

    assert not app.exception

    character_widget = next(widget for widget in app.selectbox if widget.label == "角色模板")
    assert "ZZZ 泛用异常模板 (zzz_template_anomaly)" in character_widget.options

    character_widget.set_value("ZZZ 泛用异常模板 (zzz_template_anomaly)")
    app.run(timeout=30)

    assert not app.exception
    assert any(
        "自由蓝调 4 + 摇摆爵士 2" in str(table.value.to_dict("records"))
        and "核心：异常精通" in str(table.value.to_dict("records"))
        for table in app.table
        if "项目" in getattr(table.value, "columns", [])
    )
    assert any(widget.label == "目标结构" and widget.value == "4+2" for widget in app.selectbox)
    assert any(widget.label == "4 件套" and widget.value == "自由蓝调" for widget in app.selectbox)
    assert any(widget.label == "2 件套" and widget.value == "摇摆爵士" for widget in app.selectbox)


def test_board_density_control_changes_tile_css():
    app = AppTest.from_file("app.py")
    app.run(timeout=30)

    density_widget = next(widget for widget in app.selectbox if widget.label == "盘面显示密度")
    density_widget.set_value("标准")
    app.run(timeout=30)

    assert not app.exception
    assert any("盘面方块尺寸：7.4rem" in caption.value for caption in app.caption)
    assert any("--gear-tile-size: 7.4rem" in markdown.value for markdown in app.markdown)


def test_candidate_import_digest_refreshes_manual_editor_defaults():
    app = AppTest.from_file("app.py")
    app.session_state["candidate_zzz_手动输入_position"] = 4
    app.session_state["candidate_zzz_手动输入_main"] = "暴击率"
    app.session_state["candidate_zzz_手动输入_level"] = 0
    app.session_state["candidate_import::zzz::zzz_starlight_billy"] = CandidatePiece(
        position=5,
        set_name="云岿如我",
        main_stat="物理伤害",
        initial_substat_count=3,
        level=3,
        substats=[
            SubstatLine(stat="暴击率", rolls=0),
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="攻击力百分比", rolls=0),
            SubstatLine(stat="防御力", rolls=0),
        ],
    )
    app.session_state["candidate_import_digest::zzz::zzz_starlight_billy"] = (
        "abcdef1234567890"
    )

    app.run(timeout=30)

    assert not app.exception
    candidate_position = next(
        widget
        for widget in app.selectbox
        if widget.label == "位置"
        and getattr(widget, "key", "") == "candidate_zzz_手动输入_abcdef123456_position"
    )
    candidate_main = next(
        widget
        for widget in app.selectbox
        if widget.label == "主属性"
        and getattr(widget, "key", "") == "candidate_zzz_手动输入_abcdef123456_main"
    )
    assert candidate_position.value == 5
    assert candidate_main.value == "物理伤害"


def test_character_target_import_refreshes_sidebar_target_controls():
    character = next(
        item
        for item in load_characters("zzz")
        if item.id == "zzz_starlight_billy"
    ).model_copy(
        update={
            "target_effective_rolls": 4.5,
            "target_weighted_score": 5.5,
            "effective_substats": {
                "暴击率": 2.0,
                "暴击伤害": 1.0,
                "生命值百分比": 0.25,
            },
            "rating_thresholds": {
                "usable": 1.5,
                "good": 3.5,
                "excellent": 5.5,
            },
        }
    )
    app = AppTest.from_file("app.py")
    app.session_state["character_target_import::zzz::zzz_starlight_billy"] = character
    app.session_state["character_target_digest::zzz::zzz_starlight_billy"] = (
        "123456abcdef7890"
    )

    app.run(timeout=30)

    assert not app.exception
    core_priority = next(
        widget
        for widget in app.multiselect
        if widget.label == "核心副词条（从左到右优先）"
        and getattr(widget, "key", "")
        == "substat_priority_core_zzz_zzz_starlight_billy_123456abcdef"
    )
    usable_priority = next(
        widget
        for widget in app.multiselect
        if widget.label == "可用/过渡副词条（从左到右优先）"
        and getattr(widget, "key", "")
        == "substat_priority_usable_zzz_zzz_starlight_billy_123456abcdef"
    )
    effective_target = next(
        widget
        for widget in app.number_input
        if widget.label == "有效词条目标线"
        and getattr(widget, "key", "")
        == "target_effective_rolls_zzz_zzz_starlight_billy_123456abcdef"
    )
    weighted_target = next(
        widget
        for widget in app.number_input
        if widget.label == "质量分目标线"
        and getattr(widget, "key", "")
        == "target_weighted_score_zzz_zzz_starlight_billy_123456abcdef"
    )
    usable_threshold = next(
        widget
        for widget in app.number_input
        if widget.label == "usable 评级线"
        and getattr(widget, "key", "")
        == "rating_usable_zzz_zzz_starlight_billy_123456abcdef"
    )
    good_threshold = next(
        widget
        for widget in app.number_input
        if widget.label == "good 评级线"
        and getattr(widget, "key", "")
        == "rating_good_zzz_zzz_starlight_billy_123456abcdef"
    )
    excellent_threshold = next(
        widget
        for widget in app.number_input
        if widget.label == "excellent 评级线"
        and getattr(widget, "key", "")
        == "rating_excellent_zzz_zzz_starlight_billy_123456abcdef"
    )
    assert core_priority.value == ["暴击率", "暴击伤害"]
    assert usable_priority.value == ["生命值百分比"]
    assert effective_target.value == 4.5
    assert weighted_target.value == 5.5
    assert usable_threshold.value == 1.5
    assert good_threshold.value == 3.5
    assert excellent_threshold.value == 5.5


def test_probability_model_import_overrides_selected_probability_model():
    model = load_probability_models("zzz")[0].model_copy(
        update={"name": "测试覆盖概率", "target_set_probability": 0.25}
    )
    app = AppTest.from_file("app.py")
    app.session_state["probability_model_import::zzz::zzz_default"] = model

    app.run(timeout=30)

    assert not app.exception
    assert any(
        "当前正在使用导入的概率模型覆盖本配置" in caption.value
        for caption in app.caption
    )
    target_set_probability = next(
        widget
        for widget in app.slider
        if widget.label == "目标套装概率"
        and getattr(widget, "key", "") == "prob_target_set_zzz_zzz_default_base"
    )
    initial_three_probability = next(
        widget
        for widget in app.slider
        if widget.label == "初始 3 词条概率"
        and getattr(widget, "key", "") == "prob_initial_3_zzz_zzz_default_base"
    )
    assert target_set_probability.value == 0.25
    assert initial_three_probability.value == 0.8
    assert any(
        (
            "规则" in getattr(dataframe.value, "columns", [])
            and "值" in getattr(dataframe.value, "columns", [])
            and any(
                row["规则"] == "目标套装概率" and row["值"] == "25.0%"
                for row in dataframe.value.to_dict("records")
            )
        )
        for dataframe in app.dataframe
    )


def test_probability_model_parameter_controls_override_rules_overview():
    app = AppTest.from_file("app.py")
    app.run(timeout=30)

    assert not app.exception

    target_set_probability = next(
        widget
        for widget in app.slider
        if widget.label == "目标套装概率"
    )
    target_set_probability.set_value(0.3)
    app.run(timeout=30)

    assert not app.exception
    assert any(
        (
            "规则" in getattr(dataframe.value, "columns", [])
            and "值" in getattr(dataframe.value, "columns", [])
            and any(
                row["规则"] == "目标套装概率" and row["值"] == "30.0%"
                for row in dataframe.value.to_dict("records")
            )
        )
        for dataframe in app.dataframe
    )
