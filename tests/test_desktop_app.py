import json
import os
import subprocess
import sys
import threading
import time
import tomllib
import types
from pathlib import Path

import pytest
from gear_optimizer import launcher


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _process_events_until(app, predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    app.processEvents()
    assert predicate()


def test_parse_desktop_args_defaults_to_native_desktop_size():
    args = launcher.parse_desktop_args([])

    assert args.width >= 1100
    assert args.height >= 720
    assert not args.check
    assert not args.app_check
    assert args.app_check_json == ""
    assert not hasattr(args, "port")
    assert not hasattr(args, "strict_runtime")


def test_desktop_support_rows_report_pyside6_runtime(monkeypatch):
    monkeypatch.setattr(
        launcher.importlib.util,
        "find_spec",
        lambda name: object() if name == "PySide6" else None,
    )

    rows = launcher.desktop_support_rows()
    formatted = launcher.format_desktop_support(rows)

    assert {"item": "PySide6", "status": "ok", "detail": "native desktop runtime"} in rows
    assert any(row["item"] == "native UI module" for row in rows)
    assert "PySide6" in formatted
    assert "native UI module" in formatted


def test_desktop_main_check_prints_status_without_launching(monkeypatch, capsys):
    monkeypatch.setattr(
        launcher,
        "desktop_support_rows",
        lambda: [{"item": "PySide6", "status": "missing", "detail": "install"}],
    )

    assert launcher.desktop_main(["--check"]) == 0
    assert "PySide6" in capsys.readouterr().out


def test_desktop_main_app_check_can_write_json(monkeypatch, tmp_path, capsys):
    rows = [{"item": "PySide6 app", "status": "ok", "detail": "importable"}]
    output = tmp_path / "native_app_checks.json"

    monkeypatch.setattr(launcher, "app_smoke_rows", lambda: rows)

    assert launcher.desktop_main(["--app-check-json", str(output)]) == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == rows
    assert "Wrote app smoke checks:" in capsys.readouterr().out


def test_desktop_main_app_check_returns_nonzero_for_errors(monkeypatch):
    rows = [{"item": "PySide6 app", "status": "error", "detail": "failed"}]

    monkeypatch.setattr(launcher, "app_smoke_rows", lambda: rows)

    assert launcher.desktop_main(["--app-check"]) == 1


def test_desktop_main_missing_pyside6_does_not_launch(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "has_desktop_runtime", lambda: False)
    monkeypatch.setattr(
        launcher,
        "desktop_support_rows",
        lambda: [{"item": "PySide6", "status": "missing", "detail": 'install with: pip install -e ".[desktop]"'}],
    )

    assert launcher.desktop_main([]) == 2
    output = capsys.readouterr().out
    assert "PySide6 is required" in output
    assert 'pip install -e ".[desktop]"' in output


def test_desktop_main_launches_pyside6_app_when_runtime_available(monkeypatch):
    calls = []
    fake_pyside6_app = types.ModuleType("gear_optimizer.pyside6_app")
    fake_pyside6_app.main = lambda args: calls.append(args) or 0

    monkeypatch.setattr(launcher, "has_desktop_runtime", lambda: True)
    monkeypatch.setattr(launcher.importlib, "import_module", lambda name: fake_pyside6_app)

    assert launcher.desktop_main(["--width", "1400", "--height", "900"]) == 0
    assert calls == [["--width", "1400", "--height", "900"]]


def test_module_main_dispatches_to_native_desktop(monkeypatch):
    calls = []

    def fake_desktop_main(args):
        calls.append(args)
        return 0

    monkeypatch.setattr(launcher, "desktop_main", fake_desktop_main)

    assert launcher.module_main(["--desktop", "--width", "1400"]) == 0
    assert calls == [["--width", "1400"]]


def test_module_main_defaults_to_native_desktop(monkeypatch):
    calls = []

    def fake_desktop_main(args):
        calls.append(args)
        return 0

    monkeypatch.setattr(launcher, "desktop_main", fake_desktop_main)

    assert launcher.module_main(["--width", "1400"]) == 0
    assert calls == [["--width", "1400"]]


def test_desktop_app_script_can_run_check_without_pythonpath(tmp_path):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "desktop_app.py"), "--check"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "project root" in result.stdout
    assert "PySide6" in result.stdout


def test_pyproject_declares_native_desktop_scripts_and_dependencies():
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    optional = data["project"]["optional-dependencies"]

    assert scripts["gacha-gear-optimizer"] == "gear_optimizer.launcher:desktop_main"
    assert scripts["gacha-gear-optimizer-desktop"] == "gear_optimizer.launcher:desktop_main"
    assert scripts["gacha-gear-optimizer-ui-smoke"] == "gear_optimizer.desktop_ui_smoke:main"
    assert not any(dependency.startswith("streamlit") for dependency in data["project"]["dependencies"])
    assert "PySide6-Essentials==6.11.1" in optional["desktop"]
    assert "PySide6-Essentials==6.11.1" in optional["packaging"]


def test_desktop_ui_smoke_main_reports_script_result(monkeypatch, capsys, tmp_path):
    from gear_optimizer import desktop_ui_smoke

    calls = []

    def fake_run_smoke(*, visible, timeout_seconds, user_data_dir):
        calls.append((visible, timeout_seconds, user_data_dir))
        return ["fake smoke ok"]

    monkeypatch.setattr(desktop_ui_smoke, "run_smoke", fake_run_smoke)

    assert desktop_ui_smoke.main(
        ["--offscreen", "--timeout", "7", "--user-data-dir", str(tmp_path / "data")]
    ) == 0
    assert calls == [(False, 7.0, (tmp_path / "data").resolve())]
    output = capsys.readouterr().out
    assert "fake smoke ok" in output
    assert "UI_SMOKE_OK" in output


def test_optimizer_window_constructs_key_pyside6_components(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QLabel, QGroupBox, QInputDialog, QMessageBox
    from gear_optimizer.pyside6_app import (
        ACTION_DETAIL_DISPLAY_LIMIT,
        OptimizerWindow,
        PieceCard,
        _default_inventory_piece,
    )

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        assert window.tabs.tabText(0) == "总览"
        assert window.tabs.currentIndex() == 0
        assert {window.tabs.tabText(index) for index in range(window.tabs.count())} == {
            "总览",
            "库存",
            "当前装备",
            "计算结果",
        }
        visible_labels = [label.text() for label in window.findChildren(QLabel)]
        group_titles = [group.title() for group in window.findChildren(QGroupBox)]
        assert window.overview_game_label.text()
        assert "代理人 / 目标模板" in visible_labels
        assert "计算输入审计" in group_titles
        assert "本次输入口径" in group_titles
        assert "目标模板：" in window.input_audit_label.text()
        assert "数据归属：" in window.input_audit_label.text()
        assert ("库存归属：" in window.input_audit_label.text()) or ("库存来源：" in window.input_audit_label.text())
        assert "游戏/概率模型：" in window.input_audit_label.text()
        assert "当前装备：" in window.input_audit_label.text()
        assert "库存：" in window.input_audit_label.text()
        assert "输入指纹：" in window.input_audit_label.text()
        assert "当前装备指纹：" in window.input_audit_label.text()
        assert "库存指纹：" in window.input_audit_label.text()
        assert window.result_input_audit_label.text() == window.input_audit_label.text()
        assert window.copy_input_audit_button.text() == "复制输入审计"
        assert window.copy_result_input_audit_button.text() == "复制本次输入口径"
        window.copy_input_audit()
        assert app.clipboard().text() == window.input_audit_label.text()
        assert "已复制本次输入口径" in window.progress_label.text()
        assert "计算 Action EV" in window.result_recommend_detail.text()
        assert "库存升级机会" in window.result_recommend_detail.text()
        assert window.agent_button.text() == "切换代理人"
        assert window.selected_agent() is not None
        assert window.selected_agent().character_preset_id == window.selected_character().id
        assert window.selected_character().id in window.agent_summary_label.text()
        assert window.edit_target_template_button.text() == "编辑目标模板"
        assert not window.delete_target_template_button.isEnabled()
        assert "目标模板=计算目标，不保存装备" in window.target_template_summary_label.text()
        assert "期望套装结构" in window.target_template_summary_label.text()
        assert "每位置期望主属性" in window.target_template_summary_label.text()
        assert "副属性有效排序" in window.target_template_summary_label.text()
        hsr_index = window.game_combo.findData("hsr")
        assert hsr_index >= 0
        window.game_combo.setCurrentIndex(hsr_index)
        assert "horizon=1" in window.input_audit_label.text()
        assert window.result_input_audit_label.text() == window.input_audit_label.text()
        empty_inventory_audit = window.input_audit_label.text()
        assert len(window.agents) >= 80
        assert window.agents[0].release_order >= window.agents[-1].release_order
        assert window.selected_agent().name != "崩铁通用暴击模板"
        assert window.selected_agent().card_path
        assert window.selected_agent().name in window.agent_summary_label.text()
        if window.selected_agent().faction != "未知":
            assert window.selected_agent().faction in window.agent_summary_label.text()
        assert window.selected_character().id in window.agent_summary_label.text()
        assert window.overview_confirm_label.text() in {"未确认", "已确认"}
        assert window.current_template_combo.currentData() == ""
        assert not window.load_current_template_button.isEnabled()
        assert window.current_table.rowCount() == 0
        assert not window.confirm_button.isEnabled()
        assert not window.save_current_button.isEnabled()
        assert len(window.current_cards) == 6
        assert all(isinstance(card, PieceCard) for card in window.current_cards)
        assert "空槽" in window.current_cards[0].position_label.text()
        assert window.current_cards[0].icon_label.toolTip()
        assert window._current_action_ev_engine() == "inventory_recursive"
        assert window.inventory_summary_table.isHidden()
        assert window.inventory_card_scroll.widget() is window.inventory_card_host
        assert "库存" in window.inventory_card_status_label.text()
        assert window.target_set_filter.text() == "只看目标套装"
        assert window.weak_position_filter.text() == "只看当前弱位"
        assert window.unfinished_filter.text() == "只看未满级胚子"
        assert window.replaceable_filter.text() == "只看可替换当前"
        assert window.duplicate_filter.text() == "只看重复库存"
        assert window.clear_inventory_filters_button.text() == "清除筛选"
        assert window.best_button.text() == "计算当前最优搭配（含强化期望）"
        assert window.portfolio_button.text() == "多代理人调律建议"
        assert "多代理人调律" in {
            window.result_tabs.tabText(index)
            for index in range(window.result_tabs.count())
        }
        assert "当前最优/Action EV 需要确认当前装备" in window.overview_guide_label.text()
        assert "多代理人调律可直接使用空或部分当前盘面" in window.overview_guide_label.text()
        assert not window.clear_inventory_filters_button.isEnabled()
        assert not window.copy_inventory_button.isEnabled()
        assert not window.clear_substats_button.isEnabled()
        assert not window.delete_inventory_button.isEnabled()
        assert not window.export_inventory_button.isEnabled()
        window.copy_selected_inventory()
        assert window.progress_label.text() == "请先选中一件库存。"
        window.export_inventory_details()
        assert window.progress_label.text() == "库存为空，暂无可导出的完整明细。"
        game = window.selected_game()
        character = window.selected_character()
        empty_slot_piece = _default_inventory_piece(game, character, game.positions[0].id)
        window.inventory_table.set_context(game, character, [empty_slot_piece])
        window._inventory_changed()
        assert "库存：1 件" in window.input_audit_label.text()
        assert window.input_audit_label.text() != empty_inventory_audit
        assert window.result_input_audit_label.text() == window.input_audit_label.text()
        assert window.copy_inventory_button.isEnabled()
        assert window.clear_substats_button.isEnabled()
        assert window.delete_inventory_button.isEnabled()
        assert window.export_inventory_button.isEnabled()
        window.equip_inventory_piece(0)
        assert window.current_table.rowCount() == 1
        assert window.inventory_table.rowCount() == 0
        assert "该槽位之前为空" in window.progress_label.text()
        assert window.confirm_button.isEnabled()
        assert window.save_current_button.isEnabled()
        assert not window.copy_inventory_button.isEnabled()
        assert not window.clear_substats_button.isEnabled()
        assert not window.delete_inventory_button.isEnabled()
        assert not window.export_inventory_button.isEnabled()
        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("半成品快照", True))
        window.save_current()
        assert window.current_template_combo.currentData()
        assert "半成品快照" in window.current_template_combo.currentText()
        assert "1/6" in window.current_template_combo.currentText()
        window.current_table.set_context(game, character, [])
        window.load_current_template()
        assert window.current_table.rowCount() == 1
        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("重命名快照", True))
        window.rename_current_template()
        assert "重命名快照" in window.current_template_combo.currentText()
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
        window.delete_current_template()
        assert window.current_template_combo.currentData() == ""
        assert not window.load_current_template_button.isEnabled()
        window.load_example_current()
        current_before = window._hidden_table_pieces(window.current_table)
        inventory_piece = current_before[0].model_copy(
            update={
                "level": 0,
                "locked": False,
                "substats": [],
            }
        )
        window.inventory_table.set_context(game, character, [inventory_piece])
        window._inventory_changed()
        assert len(window.inventory_cards) == 1
        assert "库存 #1" in window.inventory_detail_label.text()
        assert "有效" in window.inventory_detail_label.text()
        assert "质量" not in window.inventory_detail_label.text()
        assert window.inventory_cards[0].position_label.text()
        assert window.inventory_cards[0].index_badge.text() == "库存 #1"
        assert "质量" not in window.inventory_cards[0].metric_badge.text()
        window.equip_inventory_piece(0)
        current_after = window._hidden_table_pieces(window.current_table)
        inventory_after = window._hidden_table_pieces(window.inventory_table)
        assert current_after[0].level == 0
        assert inventory_after[0].position == current_before[0].position
        assert inventory_after[0].level == current_before[0].level
        assert window._selected_inventory_source_row() == 0
        assert window.inventory_cards[0].is_selected
        assert "库存 #1 现在是换下来的旧当前件" in window.progress_label.text()
        assert window.current_confirmed_digest is None
        assert window.result_tabs.tabText(0) == "Action EV 明细"
        assert window.result_tabs.tabText(1) == "H=2 方案"
        assert window.result_tabs.tabText(2) == "搭配结果"
        assert window.result_tabs.tabText(3) == "多代理人调律"
        assert window.result_tabs.tabText(4) == "运行日志"
        assert not window.log.isVisible()
        assert not window.show_all_actions_button.isEnabled()
        assert not window.cancel_action_button.isEnabled()
        window.horizon_combo.setCurrentIndex(1)
        assert "完整概率分布精确计算" in window.horizon_note_label.text()
        assert "可取消" in window.horizon_note_label.text()
        assert window.progress_bar.objectName() == "ActionProgressBar"
        window._on_action_progress({"event": "unit_progress", "completed": 50, "total": 100})
        assert window.progress_bar.value() == 0
        window._render_action_progress(window._last_action_progress_payload)
        assert window.progress_bar.value() == 50
        assert "总进度 50%" in window.progress_meter_label.text()
        window._render_action_progress(
            {"event": "refinement_start", "completed": 10, "total": 200, "label": "追加精确任务"}
        )
        assert window.progress_bar.value() == 50
        assert "计划已扩展" in window.progress_meter_label.text()
        window._render_action_progress(
            {
                "event": "unit_progress",
                "completed": 10,
                "total": 200,
                "label": "随机位置",
                "inner_event": "candidate_generation_step_done",
                "inner_completed": 3,
                "inner_total": 10,
                "inner_action_position": "2",
                "inner_action_main_stat": "暴击率",
                "dp_steps": 23,
                "dp_states": 5,
            }
        )
        assert "候选组完成" in window.progress_detail_label.text()
        assert "内部步数 23" in window.progress_detail_label.text()
        assert "DP状态 5（诊断）" in window.progress_detail_label.text()
        window._render_action_progress(
            {
                "event": "unit_done",
                "completed": 11,
                "total": 200,
                "label": "随机混合：1-6 固定位置按概率加权",
                "derived_from_fixed_positions": True,
                "spec_index": 7,
                "spec_total": 10,
                "unit_label": "horizon=1",
            }
        )
        assert "汇总固定位置分支" in window.progress_label.text()
        assert "随机=固定分支加权汇总" in window.progress_meter_label.text()
        assert "不是单独随机枚举" in window.progress_detail_label.text()
        sample_action_row = {
            "策略": "固定位置",
            "目标套装": "云岿如我",
            "位置": "1号位",
            "主属性": "生命值",
            "固定副属性": "不固定",
            "horizon": 2,
            "期望提升": "质量 +1",
            "方案类型": "代表路径",
            "第一步 action": "固定位置 / 云岿如我 / 1号位",
            "第二步策略摘要": "固定位置 / 云岿如我 / 2号位",
            "代表路径": "-",
            "预期搭配": "-",
            "代表分支搭配": "-",
            "互补位": "-",
            "套装约束": "满足4+2",
            "条件分支": [],
            "代表路径说明": "代表路径仅用于审计；真实 H=2 EV 已对所有 outcome 加权。",
            "有效提升": 0.3,
            "质量/母盘": 0.25,
            "有效/母盘": 0.15,
            "排序向量/母盘": "internal-ish",
            "比较口径": "固定位置基础行；优于随机混合，才建议固定",
            "相对随机": "优于随机，才建议固定",
            "_sort_vector": (1.0,),
            "_representative_loadout_rows": [],
        }
        window._action_result_rows = [dict(sample_action_row) for _index in range(ACTION_DETAIL_DISPLAY_LIMIT + 5)]
        window._render_action_table()
        assert window.action_table.rowCount() == ACTION_DETAIL_DISPLAY_LIMIT
        headers = [
            window.action_table.horizontalHeaderItem(index).text()
            for index in range(window.action_table.columnCount())
        ]
        assert "动作类型" in headers
        assert "调律策略/动作" in headers
        assert "有效期望" in headers
        assert "比较口径" in headers
        assert "代表分支搭配" in headers
        assert "策略" not in headers
        assert "期望提升" not in headers
        assert "质量/母盘" not in headers
        assert "预期搭配" not in headers
        assert "相对随机" not in headers
        assert "排序向量/母盘" not in headers
        assert "_sort_vector" not in headers
        assert headers.index("套装约束") < headers.index("有效期望")
        assert headers.index("比较口径") < headers.index("有效期望")
        assert headers.index("有效/母盘") > headers.index("有效期望")
        effective_col = headers.index("有效期望")
        assert window.action_table.item(0, effective_col).text() == "有效提升 +0.3"
        assert "质量 +1" not in window.action_table.item(0, effective_col).text()
        assert window.show_all_actions_button.isEnabled()
        assert "显示全部" in window.show_all_actions_button.text()
        window.toggle_action_rows()
        assert window.action_table.rowCount() == ACTION_DETAIL_DISPLAY_LIMIT + 5
        assert "收起" in window.show_all_actions_button.text()
        card_text = window._recommended_action_card_text(sample_action_row)
        assert "动作类型：调律母盘" in card_text
        assert "推荐动作：固定位置" in card_text
        assert "方案类型：代表路径" in card_text
        assert "第二步策略摘要：固定位置 / 云岿如我 / 2号位" in card_text
        assert "有效期望：有效提升 +0.3" in card_text
        assert "期望提升：质量 +1" not in card_text
        assert "质量 +1" not in card_text
        assert "质量/母盘" not in card_text
        assert "排序口径" in card_text
        assert "先要求有效提升为正" in card_text
        assert "按有效/母盘、有效提升排序" in card_text
        assert "审计排序向量仅作 tie-break" in card_text
        assert "沿用引擎排序向量" not in card_text
        assert "按排序向量/母盘推荐" not in card_text
        assert "计算口径：精确" in card_text
        assert "计算引擎：inventory_recursive" in card_text
        assert "执行方式" in card_text
        assert "比较口径：固定位置基础行；优于随机混合，才建议固定" in card_text
        assert "固定位置是基础 action" in card_text
        assert "固定位置基础行；优于随机混合，才建议固定" in card_text
        assert "H=2 方案页展示审计用代表路径或条件分支" in card_text
        first_position = window.selected_game().positions[0].id
        window._render_action_plan(
            {
                **sample_action_row,
                "_representative_loadout_rows": [
                    {
                        "position": first_position,
                        "set_name": "云岿如我",
                        "source": "outcome",
                        "main_stat": "生命值",
                        "effective_rolls": 1.0,
                        "quality_score": 2.0,
                        "quality_vector": (2.0,),
                    }
                ],
            }
        )
        assert "方案类型：代表路径" in window.action_plan_summary_label.text()
        assert window.action_plan_branch_table.rowCount() == 0
        assert window.action_plan_loadout_table.rowCount() == 1
        window._render_action_plan(
            {
                **sample_action_row,
                "策略": "随机位置",
                "位置": "1-6 随机",
                "方案类型": "条件策略",
                "第二步策略摘要": "按命中位置分 6 个条件分支；第二步来自 exact lookahead",
                "代表分支搭配": "混合结果，不存在唯一典型搭配",
                "条件分支": [
                    {
                        "条件": "第1步命中 1号位",
                        "条件概率": 1 / 6,
                        "代表新盘": "1号位云岿如我（代表命中 100.0%）",
                        "第二步 action": "固定位置 / 云岿如我 / 2号位",
                        "第二步原因": "来自该 outcome state 的 exact horizon=1 lookahead",
                        "代表最终搭配": "A6",
                        "套装约束": "满足A 6",
                    }
                ],
                "_representative_loadout_rows": [
                    {
                        "position": first_position,
                        "set_name": "云岿如我",
                        "source": "outcome",
                        "main_stat": "生命值",
                    }
                ],
            }
        )
        assert "混合结果，不存在唯一典型搭配" in window.action_plan_summary_label.text()
        assert window.action_plan_branch_table.rowCount() == 1
        assert window.action_plan_loadout_table.rowCount() == 0
        upgrade_text = window._recommended_action_card_text(
            {
                **sample_action_row,
                "策略": "强化库存胚子",
                "相对随机": "库存动作",
                "_upgrade_inventory_id": f"piece:{window.current_table.rowCount()}",
            }
        )
        assert "动作类型：库存升级机会" in upgrade_text
        assert "机会动作：非调律：升级已有库存" in upgrade_text
        assert "库存升级机会不参与主调律推荐" in upgrade_text
        assert "没有有效提升为正的调律 action" in upgrade_text
        assert "不消耗母盘" in upgrade_text
        assert "库存编号：库存 #1" in upgrade_text
        assert "不等于这件胚子当前已经比已装备件更好" in upgrade_text
        for method in [
            "confirm_current",
            "run_best_loadout",
            "run_action_ev",
            "cancel_action_ev",
            "toggle_action_rows",
            "edit_current_piece",
            "edit_inventory_piece",
            "copy_selected_inventory",
            "clear_selected_inventory_substats",
            "export_inventory_details",
            "load_current_template",
            "rename_current_template",
            "delete_current_template",
            "edit_target_template",
            "delete_target_template",
        ]:
            assert callable(getattr(window, method))
        zzz_index = window.game_combo.findData("zzz")
        if zzz_index >= 0:
            window.game_combo.setCurrentIndex(zzz_index)
            app.processEvents()
            assert len(window.agents) >= 50
            assert window.selected_agent().agent_id == "zzz_starlight_billy"
            assert window.selected_agent().name == "星徽·比利"
            assert window.selected_agent().card_path
            target_agent = next(agent for agent in window.agents if agent.name == "维琳娜")
            window._select_agent(target_agent)
            app.processEvents()
            assert window.selected_character().id == target_agent.character_preset_id
            assert target_agent.name in window.agent_summary_label.text()
            assert target_agent.faction in window.agent_summary_label.text()
            assert target_agent.character_preset_id in window.agent_summary_label.text()
            unselected_card = window._agent_card_widget(target_agent, selected=False)
            card_texts = {
                label.objectName(): label.text()
                for label in unselected_card.findChildren(QLabel)
            }
            assert card_texts["AgentCardName"] == target_agent.name
            assert target_agent.faction in card_texts["AgentCardFaction"]
            assert target_agent.character_preset_id in card_texts["AgentCardTemplate"]
    finally:
        window.close()
        app.processEvents()


def test_action_detail_sort_prioritizes_effective_metric_over_audit_vector(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from gear_optimizer.pyside6_app import _desktop_recommended_action_row, _sorted_action_rows

    high_audit_low_effective = {
        "策略": "固定位置",
        "目标套装": "A",
        "位置": "1号位",
        "相对随机": "优于随机，才建议固定",
        "套装约束": "满足A 6",
        "有效提升": 0.1,
        "有效/母盘": 0.1,
        "质量/母盘": 99.0,
        "_sort_vector": (99.0, 0.1),
    }
    low_audit_high_effective = {
        "策略": "固定位置",
        "目标套装": "A",
        "位置": "2号位",
        "相对随机": "优于随机，才建议固定",
        "套装约束": "满足A 6",
        "有效提升": 0.2,
        "有效/母盘": 0.2,
        "质量/母盘": 1.0,
        "_sort_vector": (1.0, 0.2),
    }

    rows = _sorted_action_rows([high_audit_low_effective, low_audit_high_effective])

    assert rows[0]["位置"] == "2号位"
    assert _desktop_recommended_action_row(rows)["位置"] == "2号位"

    gated_fixed = {
        **low_audit_high_effective,
        "位置": "3号位",
        "有效提升": 9.0,
        "有效/母盘": 9.0,
        "相对随机": "不如随机，不建议固定",
    }
    random_baseline = {
        **high_audit_low_effective,
        "策略": "随机位置",
        "位置": "1-6 随机",
        "相对随机": "基准",
    }

    assert _desktop_recommended_action_row([gated_fixed, random_baseline])["位置"] == "1-6 随机"


def test_transient_popup_guard_suppresses_popup_show_during_ui_rebuild(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication, QComboBox, QWidget
    import gear_optimizer.pyside6_app as pyside6_app

    app = QApplication.instance() or QApplication([])
    guard = pyside6_app._TransientPopupGuard()
    popup = QWidget()
    popup.setWindowFlag(Qt.WindowType.Popup, True)
    tooltip_popup = QWidget(None, Qt.WindowType.ToolTip)
    combo = QComboBox()
    normal = QWidget()
    try:
        pyside6_app._suppress_transient_popups(1000)

        assert guard.eventFilter(popup, QEvent(QEvent.Type.Show))
        assert guard.eventFilter(tooltip_popup, QEvent(QEvent.Type.Show))
        assert not guard.eventFilter(combo, QEvent(QEvent.Type.Show))
        assert not guard.eventFilter(normal, QEvent(QEvent.Type.Show))
    finally:
        pyside6_app._TRANSIENT_POPUP_SUPPRESS_UNTIL = 0
        popup.close()
        tooltip_popup.close()
        combo.close()
        normal.close()
        app.processEvents()


def test_multi_agent_tuning_button_renders_recommendation_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    import gear_optimizer.pyside6_app as pyside6_app
    from gear_optimizer.portfolio_models import PortfolioMode, PortfolioTarget
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_piece

    class FakePortfolioRow:
        action_label = "固定位置 / A / 2号位"
        target_set = "A"
        portfolio_ev = 1.0
        useful_probability = 1.0
        best_beneficiary_agent = "测试代理"

        def to_recommendation_row(self):
            return {
                "调律动作": self.action_label,
                "目标套装": self.target_set,
                "位置": "2号位",
                "主属性": "不固定",
                "主EV": self.portfolio_ev,
                "EV/母盘": 0.1667,
                "成型收益概率": "100.0%",
                "主要受益人": self.best_beneficiary_agent,
                "受益人数": 1,
                "受益明细": "测试代理 +1.000 (100.0%)",
                "建设提示": "-",
                "说明": "测试代理 的 best_loadout 有正提升",
            }

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        current_pieces = [_default_piece(game, character, game.positions[0].id)]
        window.current_table.set_context(game, character, current_pieces)
        target = PortfolioTarget(
            agent_id="test_agent",
            name="测试代理",
            character=character,
            weight=1.0,
        )
        monkeypatch.setattr(
            window,
            "_select_portfolio_targets_dialog",
            lambda: ([target], PortfolioMode.ANY_USEFUL),
        )

        calls = []

        def fake_portfolio_action_rows(*args, **kwargs):
            calls.append((args, kwargs))
            assert len(args[3]) == 1
            assert args[3][0].position == game.positions[0].id
            assert kwargs["mode"] == PortfolioMode.ANY_USEFUL
            assert kwargs["horizon"] == 1
            assert kwargs["action_scope"] == "tuning"
            return [FakePortfolioRow()]

        monkeypatch.setattr(pyside6_app, "portfolio_action_rows", fake_portfolio_action_rows)

        window.run_portfolio_audit()
        _process_events_until(
            app,
            lambda: window.portfolio_table.rowCount() == 1 and not window._action_busy(),
        )

        assert calls
        assert window.portfolio_table.rowCount() == 1
        headers = [
            window.portfolio_table.horizontalHeaderItem(index).text()
            for index in range(window.portfolio_table.columnCount())
        ]
        assert "主EV" in headers
        assert "成型收益概率" in headers
        assert "主要受益人" in headers
        assert "建设提示" in headers
        assert "固定副属性" not in headers
        assert "多代理人调律完成" in window.portfolio_status_label.text()
        assert "本表只比较随机位置、固定位置、固定主属性" in window.portfolio_status_label.text()
        assert window.result_tabs.tabText(window.result_tabs.currentIndex()) == "多代理人调律"
        assert window.progress_label.text() == "多代理人调律建议已计算完成。"
        assert "多代理人调律推荐" in window.result_recommend_title.text()
        log_path = pyside6_app.ui_runtime_log_path()
        log_text = log_path.read_text(encoding="utf-8")
        assert "portfolio_compute_start" in log_text
        assert "portfolio_compute_finished" in log_text
    finally:
        window.close()
        app.processEvents()


def test_multi_agent_tuning_button_does_not_require_confirmed_full_current(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        window.current_table.set_context(
            game,
            character,
            [_default_piece(game, character, game.positions[0].id)],
        )
        window.current_confirmed_digest = None

        window._update_action_buttons()

        assert not window.best_button.isEnabled()
        assert not window.action_button.isEnabled()
        assert window.portfolio_button.isEnabled()
        assert "需要先确认当前装备" in window.best_button.toolTip()
        assert "需要先确认当前装备" in window.action_button.toolTip()
        assert "不要求确认完整当前装备" in window.portfolio_button.toolTip()

        window._update_action_buttons(busy=True)

        assert not window.best_button.isEnabled()
        assert not window.action_button.isEnabled()
        assert not window.portfolio_button.isEnabled()
        assert window.portfolio_button.toolTip() == "正在计算中。"
    finally:
        window.close()
        app.processEvents()


def test_current_piece_card_can_unequip_to_inventory(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QPushButton
    import gear_optimizer.pyside6_app as pyside6_app
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        current_piece = _default_piece(game, character, game.positions[0].id)
        window.current_table.set_context(game, character, [current_piece])
        window.inventory_table.set_context(game, character, [])
        window._current_changed()

        assert window.current_table.rowCount() == 1
        assert window.inventory_table.rowCount() == 0
        assert any(
            button.text() == "卸下"
            for button in window.current_cards[0].findChildren(QPushButton)
        )

        window.unequip_current_piece(0)

        current_pieces = window._hidden_table_pieces(window.current_table)
        inventory_pieces = window._hidden_table_pieces(window.inventory_table)
        assert current_pieces == []
        assert len(inventory_pieces) == 1
        assert inventory_pieces[0].position == current_piece.position
        assert window.current_confirmed_digest is None
        assert "已卸下" in window.progress_label.text()
        assert window._selected_inventory_source_row() == 0
        assert not window.confirm_button.isEnabled()
        assert window.portfolio_button.isEnabled()
        assert "current_piece_unequipped" in pyside6_app.ui_runtime_log_path().read_text(encoding="utf-8")
    finally:
        window.close()
        app.processEvents()


def test_portfolio_audit_runs_in_background_and_records_operations(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    import gear_optimizer.pyside6_app as pyside6_app
    from gear_optimizer.portfolio_models import PortfolioMode, PortfolioTarget
    from gear_optimizer.pyside6_app import OptimizerWindow

    class FakePortfolioRow:
        action_label = "固定位置 / A / 2号位"
        target_set = "A"
        portfolio_ev = 0.0
        useful_probability = 0.0
        best_beneficiary_agent = ""

        def to_recommendation_row(self):
            return {"主EV": 0.0, "建设提示": "暂不成型"}

    entered = threading.Event()
    release = threading.Event()
    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        target = PortfolioTarget(
            agent_id="test_agent",
            name="测试代理",
            character=character,
            weight=1.0,
        )
        monkeypatch.setattr(
            window,
            "_select_portfolio_targets_dialog",
            lambda: ([target], PortfolioMode.ANY_USEFUL),
        )

        def slow_portfolio_action_rows(*args, **kwargs):
            entered.set()
            assert release.wait(timeout=3.0)
            return [FakePortfolioRow()]

        monkeypatch.setattr(pyside6_app, "portfolio_action_rows", slow_portfolio_action_rows)

        window.current_confirmed_digest = None
        window.run_portfolio_audit()
        _process_events_until(app, entered.is_set)

        assert window._action_busy()
        assert not window.portfolio_button.isEnabled()
        assert window.progress_bar.maximum() == 0
        assert "后台计算" in window.progress_label.text()

        log_text = pyside6_app.ui_runtime_log_path().read_text(encoding="utf-8")
        assert "portfolio_audit_clicked" in log_text
        assert "portfolio_compute_start" in log_text
        assert '"current_confirmed": false' in log_text

        release.set()
        _process_events_until(
            app,
            lambda: window.portfolio_table.rowCount() == 1 and not window._action_busy(),
        )

        assert window.progress_label.text() == "多代理人调律建议已计算完成。"
        log_text = pyside6_app.ui_runtime_log_path().read_text(encoding="utf-8")
        assert "portfolio_compute_finished" in log_text
    finally:
        release.set()
        if window._portfolio_worker_thread is not None:
            window._portfolio_worker_thread.quit()
            window._portfolio_worker_thread.wait(1000)
        window.close()
        app.processEvents()


def test_game_selector_is_native_combo_and_contains_zzz(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QComboBox
    from gear_optimizer.pyside6_app import OptimizerWindow

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        assert type(window.game_combo) is QComboBox
        zzz_index = window.game_combo.findData("zzz")
        assert zzz_index >= 0

        window.game_combo.setCurrentIndex(zzz_index)
        app.processEvents()
        assert window.game_combo.currentData() == "zzz"
        assert "绝区零" in window.game_combo.currentText()
        assert "多代理人调律可直接使用空或部分当前盘面" in window.progress_label.text()
        assert "请先确认当前装备" not in window.progress_label.text()
    finally:
        window.close()
        app.processEvents()


def test_action_visible_summary_uses_user_facing_upgrade_label():
    pytest.importorskip("PySide6")

    from gear_optimizer.pyside6_app import _action_row_explanation, _action_visible_summary

    summary = _action_visible_summary(
        {
            "策略": "强化库存胚子",
            "目标套装": "云岿如我",
            "位置": "5号位",
            "主属性": "电属性伤害",
            "_upgrade_inventory_id": "piece:6",
        },
        current_count=6,
    )

    assert summary == "非调律：升级已有库存 / 库存 #1 / 云岿如我 / 5号位 / 电属性伤害"
    assert "强化库存胚子" not in summary

    random_explanation = _action_row_explanation(
        {
            "策略": "随机位置",
            "目标套装": "云岿如我",
            "位置": "1-6 随机",
            "horizon": 1,
            "套装约束": "满足",
        }
    )
    assert "action value 按位置概率加权平均" in random_explanation
    assert "不存在唯一典型搭配" in random_explanation

    fixed_explanation = _action_row_explanation(
        {
            "策略": "固定位置",
            "相对随机": "优于随机，才建议固定",
            "比较口径": "固定位置基础行；优于随机混合，才建议固定",
            "horizon": 1,
            "套装约束": "满足",
        }
    )
    assert "固定位置基础行；优于随机混合，才建议固定" in fixed_explanation
    assert "固定位置是基础 action；优于随机，才建议固定" not in fixed_explanation


def test_inventory_highlight_summary_lists_visible_inventory_numbers():
    pytest.importorskip("PySide6")

    from gear_optimizer.pyside6_app import (
        _inventory_hidden_highlight_summary,
        _inventory_highlight_count_summary,
        _inventory_highlight_summary,
    )

    assert _inventory_highlight_count_summary(set(), has_results=False) == ""
    assert _inventory_highlight_count_summary(set(), has_results=True) == "当前结果未高亮库存；"
    assert _inventory_highlight_count_summary({0, 2}, has_results=True) == "高亮 2 件；"
    assert _inventory_highlight_summary(set(), "最优") == ""
    assert _inventory_highlight_summary({2, 0}, "最优") == "最优：库存 #1、库存 #3；"
    assert _inventory_highlight_summary({0, 1, 2, 3, 4, 5}, "推荐") == (
        "推荐：库存 #1、库存 #2、库存 #3、库存 #4、另 2 件；"
    )
    assert _inventory_hidden_highlight_summary({0, 2}, {0}) == "其中 1 件高亮被当前筛选隐藏，点“清除筛选”可查看；"
    assert _inventory_hidden_highlight_summary({0, 2}, {0, 2}) == ""


def test_loadout_inventory_usage_summary_lists_inventory_sources():
    pytest.importorskip("PySide6")

    from gear_optimizer.game_rules import load_game
    from gear_optimizer.pyside6_app import (
        _loadout_display_rows,
        _loadout_inventory_usage_summary,
        _loadout_result_summary,
        _loadout_valuation_summary,
        _loadout_vs_upgrade_opportunity_summary,
    )

    assert _loadout_inventory_usage_summary([{"_inventory_id": "piece:0"}], current_count=2) == (
        "仅使用当前装备。"
    )
    assert _loadout_inventory_usage_summary(
        [{"_inventory_id": "piece:2"}, {"_inventory_id": "piece:4"}],
        current_count=2,
    ) == "使用库存：库存 #1、库存 #3。"
    assert _loadout_inventory_usage_summary(
        [
            {"_inventory_id": "piece:2"},
            {"_inventory_id": "piece:3"},
            {"_inventory_id": "piece:4"},
            {"_inventory_id": "piece:5"},
            {"_inventory_id": "piece:6"},
        ],
        current_count=2,
    ) == "使用库存：库存 #1、库存 #2、库存 #3、库存 #4、另 1 件。"
    assert _loadout_valuation_summary([{}]) == "估值口径：均按当前值/代表结果。"
    assert _loadout_valuation_summary([{"_expected_upgrade": True}, {}]) == (
        "估值口径：含 1 件未满级装备按满级强化期望估值，不折算强化材料消耗。"
    )
    assert _loadout_vs_upgrade_opportunity_summary() == (
        "口径区别：当前最优是在当前装备+库存中选搭配；"
        "库存升级机会只评估某件未满级继续升级的未来分支，正期望不等于当前已入选最优。"
    )
    display_rows = _loadout_display_rows(
        [
            {
                "position": "1",
                "set_name": "A",
                "source": "inventory",
                "_inventory_id": "piece:2",
                "_expected_upgrade": True,
                "effective_rolls": 1.5,
            }
        ],
        load_game("zzz"),
        current_count=2,
    )
    assert display_rows[0]["估值口径"] == "满级强化期望（不折算强化材料）"
    assert _loadout_result_summary(
        [{"_inventory_id": "piece:2", "_expected_upgrade": True}],
        current_count=2,
        total_count=4,
    ) == (
        "当前最优搭配 1 件；库存合计 4 件。\n"
        "使用库存：库存 #1。\n"
        "估值口径：含 1 件未满级装备按满级强化期望估值，不折算强化材料消耗。\n"
        "口径区别：当前最优是在当前装备+库存中选搭配；"
        "库存升级机会只评估某件未满级继续升级的未来分支，正期望不等于当前已入选最优。"
    )


def test_target_template_switch_preserves_editing_tables(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QInputDialog
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece
    from gear_optimizer.user_current_gear import load_user_current_gears, save_user_current_gear
    from gear_optimizer.user_target_templates import save_user_target_template

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1000, height=720)
    try:
        zzz_index = window.game_combo.findData("zzz")
        if zzz_index >= 0:
            window.game_combo.setCurrentIndex(zzz_index)
        game = window.selected_game()
        base = window.selected_character()
        current_piece = _default_inventory_piece(game, base, game.positions[0].id)
        inventory_piece = _default_inventory_piece(game, base, game.positions[-1].id)
        window.current_table.set_context(game, base, [current_piece])
        window.inventory_table.set_context(game, base, [inventory_piece])
        source_agent = next(agent for agent in window.agents if agent.name == "维琳娜")
        source_template = next(
            character
            for character in window.characters
            if character.id == source_agent.character_preset_id
        )
        source_snapshot_piece = _default_inventory_piece(game, source_template, game.positions[1].id)
        save_user_current_gear(game.id, source_agent.agent_id, [source_snapshot_piece], "维琳娜快照")

        saved = save_user_target_template(
            game.id,
            source_template.model_copy(update={"name": "UI 目标模板"}),
            "UI 目标模板",
            source_character_id=source_agent.character_preset_id,
            source_agent_id=source_agent.agent_id,
        )
        window._reload_target_template_options(saved.id)
        window._target_template_changed()

        assert window.selected_character().id == saved.id
        assert window.selected_storage_character_id() == source_agent.agent_id
        assert window.current_table.rowCount() == 1
        assert window.inventory_table.rowCount() == 1
        assert window._hidden_table_pieces(window.current_table)[0].position == current_piece.position
        assert window._hidden_table_pieces(window.inventory_table)[0].position == inventory_piece.position
        assert window.current_table.character.id == saved.id
        assert window.inventory_table.character.id == saved.id
        assert window.current_template_combo.currentData() == ""
        assert "未载入快照" in window.current_template_combo.currentText()
        assert not window.load_current_template_button.isEnabled()
        assert any(
            "维琳娜快照" in window.current_template_combo.itemText(index)
            for index in range(window.current_template_combo.count())
        )
        def select_current_snapshot(label: str) -> None:
            snapshot_index = next(
                index
                for index in range(window.current_template_combo.count())
                if label in window.current_template_combo.itemText(index)
            )
            window.current_template_combo.setCurrentIndex(snapshot_index)

        select_current_snapshot("维琳娜快照")
        assert window.current_template_combo.currentData()
        assert window.load_current_template_button.isEnabled()
        assert f"库存归属：{source_agent.agent_id}" in window.inventory_card_status_label.text()
        assert window.current_confirmed_digest is None
        assert "目标模板已变化" in window.progress_label.text()

        default_labels = []
        monkeypatch.setattr(
            QInputDialog,
            "getText",
            lambda *args, **kwargs: (
                default_labels.append(kwargs.get("text")) or "切换后保存",
                True,
            ),
        )
        window.save_current()
        saved_labels = [
            item["label"]
            for item in load_user_current_gears(game.id, source_agent.agent_id)
        ]
        assert default_labels == ["当前装备"]
        assert saved_labels == ["维琳娜快照", "切换后保存"]

        select_current_snapshot("维琳娜快照")
        window.load_current_template()
        loaded_default_labels = []
        monkeypatch.setattr(
            QInputDialog,
            "getText",
            lambda *args, **kwargs: (
                loaded_default_labels.append(kwargs.get("text")) or "载入后另存",
                True,
            ),
        )
        window.save_current()
        saved_labels = [
            item["label"]
            for item in load_user_current_gears(game.id, source_agent.agent_id)
        ]
        assert loaded_default_labels == ["维琳娜快照"]
        assert saved_labels == ["维琳娜快照", "切换后保存", "载入后另存"]

        select_current_snapshot("维琳娜快照")
        window.current_table.set_context(game, saved, [current_piece])
        window._current_changed()
        edited_default_labels = []
        monkeypatch.setattr(
            QInputDialog,
            "getText",
            lambda *args, **kwargs: (
                edited_default_labels.append(kwargs.get("text")) or "手动编辑后保存",
                True,
            ),
        )
        window.save_current()
        saved_labels = [
            item["label"]
            for item in load_user_current_gears(game.id, source_agent.agent_id)
        ]
        assert edited_default_labels == ["当前装备"]
        assert saved_labels == ["维琳娜快照", "切换后保存", "载入后另存", "手动编辑后保存"]
    finally:
        window.close()
        app.processEvents()


def test_edit_target_template_success_message_includes_saved_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QDialog
    from gear_optimizer import pyside6_app
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1000, height=720)
    try:
        game = window.selected_game()
        character = window.selected_character()
        current_piece = _default_inventory_piece(game, character, game.positions[0].id)
        inventory_piece = _default_inventory_piece(game, character, game.positions[-1].id)
        window.current_table.set_context(game, character, [current_piece])
        window.inventory_table.set_context(game, character, [inventory_piece])
        saved_template = character.model_copy(update={"name": "保存反馈目标"})

        class FakeTargetTemplateDialog:
            def __init__(self, *_args, **_kwargs):
                self.template = saved_template

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(pyside6_app, "TargetTemplateEditDialog", FakeTargetTemplateDialog)
        window.edit_target_template()

        progress = window.progress_label.text()
        assert window.progress_label.wordWrap()
        assert "已保存目标模板：保存反馈目标" in progress
        assert "它只影响目标规则，不改库存或当前装备快照" in progress
        assert "期望套装结构：" in progress
        assert "每位置期望主属性：" in progress
        assert "副属性有效排序：" in progress
        assert "保存反馈目标" in window.character_combo.currentText()
        assert window.current_table.rowCount() == 1
        assert window.inventory_table.rowCount() == 1
    finally:
        window.close()
        app.processEvents()


def test_edit_target_template_cancel_reports_no_rule_change(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QDialog
    from gear_optimizer import pyside6_app
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1000, height=720)
    try:
        game = window.selected_game()
        character = window.selected_character()
        current_piece = _default_inventory_piece(game, character, game.positions[0].id)
        inventory_piece = _default_inventory_piece(game, character, game.positions[-1].id)
        window.current_table.set_context(game, character, [current_piece])
        window.inventory_table.set_context(game, character, [inventory_piece])
        selected_template_id = window.selected_character().id

        class CancelTargetTemplateDialog:
            template = None

            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return QDialog.DialogCode.Rejected

        monkeypatch.setattr(pyside6_app, "TargetTemplateEditDialog", CancelTargetTemplateDialog)
        window.edit_target_template()

        assert window.progress_label.text() == "已取消编辑目标模板；目标规则未变化。"
        assert window.selected_character().id == selected_template_id
        assert window.current_table.rowCount() == 1
        assert window.inventory_table.rowCount() == 1
    finally:
        window.close()
        app.processEvents()


def test_delete_target_template_cancel_reports_no_rule_change(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.pyside6_app import OptimizerWindow
    from gear_optimizer.user_target_templates import save_user_target_template

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1000, height=720)
    try:
        base = window.selected_character()
        saved = save_user_target_template(
            window.selected_game().id,
            base.model_copy(update={"name": "待取消删除目标"}),
            "待取消删除目标",
            source_character_id=base.id,
        )
        window._reload_target_template_options(saved.id)

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **_kwargs: QMessageBox.StandardButton.No,
        )
        window.delete_target_template()

        assert window.progress_label.text() == "已取消删除目标模板；目标规则未变化。"
        assert window.selected_character().id == saved.id
        assert "待取消删除目标" in window.character_combo.currentText()
    finally:
        window.close()
        app.processEvents()


def test_delete_target_template_success_message_includes_fallback_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.pyside6_app import OptimizerWindow
    from gear_optimizer.user_target_templates import load_user_target_templates, save_user_target_template

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1000, height=720)
    try:
        base = window.selected_character()
        saved = save_user_target_template(
            window.selected_game().id,
            base.model_copy(update={"name": "待删除目标"}),
            "待删除目标",
            source_character_id=base.id,
        )
        window._reload_target_template_options(saved.id)

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        window.delete_target_template()

        progress = window.progress_label.text()
        assert "已删除自定义目标模板：待删除目标" in progress
        assert f"已切回目标模板：{base.name}" in progress
        assert "期望套装结构：" in progress
        assert "每位置期望主属性：" in progress
        assert "副属性有效排序：" in progress
        assert window.selected_character().id == base.id
        assert all(item.id != saved.id for item in load_user_target_templates(window.selected_game().id))
    finally:
        window.close()
        app.processEvents()


def test_user_target_template_source_restores_agent_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QGroupBox, QLabel
    from gear_optimizer.pyside6_app import OptimizerWindow
    from gear_optimizer.user_target_templates import save_user_target_template

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1000, height=720)
    try:
        zzz_index = window.game_combo.findData("zzz")
        if zzz_index >= 0:
            window.game_combo.setCurrentIndex(zzz_index)
        source_agent = next(agent for agent in window.agents if agent.name == "维琳娜")
        source_template = next(
            character
            for character in window.characters
            if character.id == source_agent.character_preset_id
        )
        saved = save_user_target_template(
            window.selected_game().id,
            source_template.model_copy(update={"name": "维琳娜自定义目标"}),
            "维琳娜自定义目标",
            source_character_id=source_agent.character_preset_id,
            source_agent_id=source_agent.agent_id,
        )

        stale_agent = next(
            agent
            for agent in window.agents
            if agent.character_preset_id != source_agent.character_preset_id
        )
        window._selected_agent_id_by_game[window.selected_game().id] = stale_agent.agent_id
        window._reload_target_template_options(saved.id)

        assert window.selected_character().id == saved.id
        assert window.selected_agent().agent_id == source_agent.agent_id
        assert window.selected_storage_character_id() == source_agent.agent_id
        assert window.selected_legacy_storage_character_id() == source_agent.character_preset_id
        window._refresh_agent_selector_summary()
        assert f"数据归属：{source_agent.agent_id}" in window.agent_summary_label.text()
        assert f"目标模板来源：{source_agent.character_preset_id}" in window.agent_summary_label.text()
    finally:
        window.close()
        app.processEvents()


def test_agent_storage_keeps_legacy_current_snapshot_unloaded_until_explicit_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QPushButton
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece
    from gear_optimizer.user_current_gear import load_user_current_gears, save_user_current_gear
    from gear_optimizer.user_inventory import load_user_inventory, save_user_inventory
    from gear_optimizer.user_target_templates import save_user_target_template

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1000, height=720)
    try:
        zzz_index = window.game_combo.findData("zzz")
        if zzz_index >= 0:
            window.game_combo.setCurrentIndex(zzz_index)
        source_agent = next(agent for agent in window.agents if agent.name == "维琳娜")
        source_template = next(
            character
            for character in window.characters
            if character.id == source_agent.character_preset_id
        )
        current_piece = _default_inventory_piece(
            window.selected_game(),
            source_template,
            window.selected_game().positions[0].id,
        )
        inventory_piece = _default_inventory_piece(
            window.selected_game(),
            source_template,
            window.selected_game().positions[-1].id,
        )
        save_user_current_gear(
            window.selected_game().id,
            source_agent.character_preset_id,
            [current_piece],
            "旧模板存储",
        )
        save_user_inventory(
            window.selected_game().id,
            source_agent.character_preset_id,
            [inventory_piece],
        )
        saved = save_user_target_template(
            window.selected_game().id,
            source_template.model_copy(update={"name": "维琳娜代理人目标"}),
            "维琳娜代理人目标",
            source_character_id=source_agent.character_preset_id,
            source_agent_id=source_agent.agent_id,
        )

        window._reload_target_template_options(saved.id)
        window._reload_character_context()

        assert window.selected_agent().agent_id == source_agent.agent_id
        assert window.selected_storage_character_id() == source_agent.agent_id
        assert window.selected_legacy_storage_character_id() == source_agent.character_preset_id
        assert f"数据归属：{source_agent.agent_id}" in window.agent_summary_label.text()
        assert f"目标模板来源：{source_agent.character_preset_id}" in window.overview_character_label.text()
        assert window._hidden_table_pieces(window.current_table) == []
        assert not any(
            button.text() == "卸下"
            for card in window.current_cards
            for button in card.findChildren(QPushButton)
        )
        assert [piece.position for piece in window._hidden_table_pieces(window.inventory_table)] == [inventory_piece.position]
        assert window.current_template_combo.currentData() == ""
        assert "未载入快照" in window.current_template_combo.currentText()
        assert not window.load_current_template_button.isEnabled()
        legacy_snapshot_index = next(
            index
            for index in range(window.current_template_combo.count())
            if "旧来源" in window.current_template_combo.itemText(index)
        )
        assert f"库存来源：旧来源 {source_agent.character_preset_id}" in window.inventory_card_status_label.text()
        assert f"保存会写入 {source_agent.agent_id}" in window.inventory_card_status_label.text()

        window.save_inventory()
        assert [piece.position for piece in load_user_inventory(window.selected_game().id, source_agent.agent_id)] == [inventory_piece.position]
        assert f"库存归属：{source_agent.agent_id}" in window.inventory_card_status_label.text()
        window.export_inventory_details()
        exported = json.loads((PROJECT_ROOT / "reports" / "inventory_export.json").read_text(encoding="utf-8"))
        assert exported["storage_id"] == source_agent.agent_id
        assert exported["legacy_storage_id"] == source_agent.character_preset_id
        assert exported["target_template_id"] == saved.id
        assert exported["agent_id"] == source_agent.agent_id
        assert exported["duplicate_summary"]["flagged_piece_count"] == 0
        assert exported["pieces"][0]["inventory_index"] == 1
        assert exported["character_id"] == source_agent.agent_id

        window.current_template_combo.setCurrentIndex(legacy_snapshot_index)
        assert window.load_current_template_button.isEnabled()
        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("旧模板改名", True))
        window.rename_current_template()
        legacy_items = load_user_current_gears(window.selected_game().id, source_agent.character_preset_id)
        agent_items = load_user_current_gears(window.selected_game().id, source_agent.agent_id)
        assert [item["label"] for item in legacy_items] == ["旧模板改名"]
        assert agent_items == []

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )
        window.delete_current_template()
        assert load_user_current_gears(window.selected_game().id, source_agent.character_preset_id) == []
        assert not window.load_current_template_button.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_target_template_editor_preserves_flexible_set_options(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QCheckBox, QGroupBox, QLabel
    from gear_optimizer.game_rules import load_characters, load_game
    from gear_optimizer.models import SubstatPriority
    from gear_optimizer.pyside6_app import OptimizerWindow, TargetSetOptionCard, TargetTemplateEditDialog

    app = QApplication.instance() or QApplication([])
    game = load_game("zzz")
    character = next(item for item in load_characters("zzz") if item.id == "zzz_starlight_billy")
    tiered_priority = SubstatPriority.model_validate(
        {"core": [game.sub_stats[:2], [game.sub_stats[2]]], "usable": []}
    )
    flex_character = character.model_copy(
        update={
            "default_set_plan": "cloud_4_flex_2",
            "substat_priority": tiered_priority,
        }
    )
    dialog = TargetTemplateEditDialog(game, flex_character)
    set_card = TargetSetOptionCard(game, game.sets[0], selected=True)
    window = OptimizerWindow(width=1000, height=720)
    try:
        zzz_index = window.game_combo.findData("zzz")
        if zzz_index >= 0:
            window.game_combo.setCurrentIndex(zzz_index)
        plan = dialog._set_plan()
        summary = window._target_template_summary_text(flex_character)

        choose_buttons = [
            button.text()
            for button in dialog.findChildren(type(window.edit_target_template_button))
            if button.text() == "选择"
        ]
        parsed = dialog._set_names_from_text("啄木鸟电音 / 河豚电音，激素朋克, 啄木鸟电音")
        dialog_labels = [label.text() for label in dialog.findChildren(QLabel)]
        group_titles = [group.title() for group in dialog.findChildren(QGroupBox)]
        set_card_labels = [label.text() for label in set_card.findChildren(QLabel)]

        assert len(choose_buttons) >= 3
        assert set_card.is_selected()
        assert set_card.findChild(QCheckBox).isChecked()
        assert game.sets[0] in set_card_labels
        assert any(text.startswith("2件套：") for text in set_card_labels)
        assert any(text.startswith("4件套：") for text in set_card_labels)
        assert any("目标模板不是装备模板，也不会生成或保存任何装备" in text for text in dialog_labels)
        assert any("这里仅定义计算目标规则" in text for text in dialog_labels)
        assert any("当前装备和库存请在对应区域维护" in text for text in dialog_labels)
        assert any("当前副属性有效排序：" in text and " = " in text for text in dialog_labels)
        assert "主属性目标（按位置）" in group_titles
        assert "目标套装结构（4+2 / 2+2+2）" in group_titles
        assert "副属性目标排序（支持并列）" in group_titles
        assert parsed == ["啄木鸟电音", "河豚电音", "激素朋克"]
        assert plan.requirements[1].set_names == ["啄木鸟电音", "河豚电音", "激素朋克"]
        assert "期望套装结构" in summary
        assert "每位置期望主属性" in summary
        assert "副属性有效排序" in summary
        assert " = " in summary
        assert "啄木鸟电音 / 河豚电音 / 激素朋克 2" in summary
    finally:
        set_card.close()
        dialog.close()
        window.close()
        app.processEvents()


def test_target_template_editor_preserves_full_substat_rank_range(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.game_rules import load_characters, load_game
    from gear_optimizer.models import SubstatPriority
    from gear_optimizer.pyside6_app import TargetTemplateEditDialog

    app = QApplication.instance() or QApplication([])
    game = load_game("hsr")
    character = next(item for item in load_characters("hsr") if item.id == "hsr_placeholder")
    priority = SubstatPriority.model_validate(
        {"core": [[stat] for stat in game.sub_stats], "usable": []}
    )
    ranked_character = character.model_copy(update={"substat_priority": priority})
    dialog = TargetTemplateEditDialog(game, ranked_character)
    try:
        last_stat = game.sub_stats[-1]
        last_spin = dialog.substat_rank_spins[last_stat]
        rebuilt_priority = dialog._substat_priority()

        assert len(game.sub_stats) > 9
        assert last_spin.maximum() >= len(game.sub_stats)
        assert last_spin.value() == len(game.sub_stats)
        assert last_spin.minimumHeight() >= 44
        assert last_spin.isAccelerated()
        assert rebuilt_priority.core_tiers == [[stat] for stat in game.sub_stats]
    finally:
        dialog.close()
        app.processEvents()


def test_target_template_editor_warns_when_main_target_is_missing(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.game_rules import load_characters, load_game
    from gear_optimizer.pyside6_app import TargetTemplateEditDialog

    app = QApplication.instance() or QApplication([])
    game = load_game("zzz")
    character = load_characters("zzz")[0]
    dialog = TargetTemplateEditDialog(game, character)
    try:
        first_rule = game.positions[0]
        first_key = str(first_rule.id)
        for check in dialog.main_stat_checks[first_key]:
            check.setChecked(False)

        questions = []

        def deny_missing_main(*args, **_kwargs):
            questions.append((args[1], args[2]))
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(QMessageBox, "question", deny_missing_main)
        dialog.accept()

        assert questions
        assert questions[0][0] == "主属性目标未完整配置"
        assert game.position_name(first_rule.id) in questions[0][1]
        assert "不限制主属性" in questions[0][1]
        assert dialog.template is None

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        dialog.accept()

        assert dialog.template is not None
        assert first_key not in dialog.template.preferred_main_stats
    finally:
        dialog.close()
        app.processEvents()


def test_target_template_summary_names_unrestricted_main_positions(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.game_rules import load_characters
    from gear_optimizer.pyside6_app import OptimizerWindow

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1000, height=720)
    try:
        game = window.selected_game()
        character = load_characters(game.id)[0]
        first_rule = game.positions[0]
        second_rule = game.positions[1]
        partial = character.model_copy(
            update={
                "preferred_main_stats": {
                    str(first_rule.id): [first_rule.main_stats[0]],
                }
            }
        )
        unrestricted = character.model_copy(update={"preferred_main_stats": {}})

        partial_summary = window._target_template_summary_text(partial)
        unrestricted_summary = window._target_template_summary_text(unrestricted)

        assert f"{game.position_name(first_rule.id)}:{first_rule.main_stats[0]}" in partial_summary
        assert "未限制：" in partial_summary
        assert game.position_name(second_rule.id) in partial_summary
        assert "全部位置不限制主属性" in unrestricted_summary
    finally:
        window.close()
        app.processEvents()


def test_target_template_editor_warns_when_set_plan_is_unrestricted(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.game_rules import load_characters, load_game
    from gear_optimizer.pyside6_app import TargetTemplateEditDialog

    app = QApplication.instance() or QApplication([])
    game = load_game("zzz")
    character = load_characters("zzz")[0]
    dialog = TargetTemplateEditDialog(game, character)
    try:
        for _set_edit, count_combo in dialog.set_requirement_rows:
            count_combo.setCurrentIndex(count_combo.findData(0))

        questions = []

        def deny_unrestricted_sets(*args, **_kwargs):
            questions.append((args[1], args[2]))
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(QMessageBox, "question", deny_unrestricted_sets)
        dialog.accept()

        assert questions
        assert questions[0][0] == "套装目标为空"
        assert "不限套装" in questions[0][1]
        assert "不会强制 4+2 或 2+2+2" in questions[0][1]
        assert dialog.template is None

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        dialog.accept()

        assert dialog.template is not None
        assert dialog.template.active_set_plan().is_unrestricted
    finally:
        dialog.close()
        app.processEvents()


def test_target_template_editor_warns_when_set_row_text_is_not_enabled(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.game_rules import load_characters, load_game
    from gear_optimizer.pyside6_app import TargetTemplateEditDialog

    app = QApplication.instance() or QApplication([])
    game = load_game("zzz")
    character = load_characters("zzz")[0]
    dialog = TargetTemplateEditDialog(game, character)
    try:
        ignored_set_name = game.sets[-1]
        ignored_edit, ignored_count = dialog.set_requirement_rows[-1]
        ignored_edit.setText(ignored_set_name)
        ignored_count.setCurrentIndex(ignored_count.findData(0))

        questions = []

        def deny_ignored_set_row(*args, **_kwargs):
            questions.append((args[1], args[2]))
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(QMessageBox, "question", deny_ignored_set_row)
        dialog.accept()

        assert questions
        assert questions[0][0] == "套装目标行未启用"
        assert ignored_set_name in questions[0][1]
        assert "保存时会被忽略" in questions[0][1]
        assert dialog.template is None

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        dialog.accept()

        assert dialog.template is not None
        assert ignored_set_name not in dialog.template.active_set_plan().target_sets
    finally:
        dialog.close()
        app.processEvents()


def test_action_process_input_payload_includes_input_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    import gear_optimizer.pyside6_app as pyside6_app
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    class FakeSignal:
        def __init__(self) -> None:
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

    class FakeProcess:
        instances = []

        def __init__(self, *_args, **_kwargs) -> None:
            self.readyReadStandardError = FakeSignal()
            self.readyReadStandardOutput = FakeSignal()
            self.finished = FakeSignal()
            self.errorOccurred = FakeSignal()
            self.started = False
            FakeProcess.instances.append(self)

        def setProgram(self, program):
            self.program = program

        def setArguments(self, arguments):
            self.arguments = arguments

        def setProcessEnvironment(self, environment):
            self.environment = environment

        def setWorkingDirectory(self, working_directory):
            self.working_directory = working_directory

        def start(self):
            self.started = True

    monkeypatch.setattr(pyside6_app, "QProcess", FakeProcess)

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1000, height=720)
    try:
        game = window.selected_game()
        character = window.selected_character()
        inventory_piece = _default_inventory_piece(game, character, game.positions[0].id)
        window.inventory_table.set_context(game, character, [inventory_piece])
        window._inventory_changed()
        audit_text = window.input_audit_label.text()

        window._start_action_ev_process([], [inventory_piece], 2, "inventory_recursive")

        payload = json.loads(Path(window._action_input_path).read_text(encoding="utf-8"))
        assert FakeProcess.instances[-1].started
        assert payload["action_mode"] == "fast"
        assert payload["input_audit"] == audit_text
        assert payload["input_audit_lines"] == audit_text.splitlines()
        assert "输入指纹：" in payload["input_audit"]
    finally:
        window._progress_timer.stop()
        window._clear_action_process_state()
        window.close()
        app.processEvents()


def test_transient_popup_suppression_hides_combo_popups(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QComboBox
    import gear_optimizer.pyside6_app as pyside6_app

    class TrackingCombo(QComboBox):
        def __init__(self) -> None:
            super().__init__()
            self.hide_popup_called = False

        def hidePopup(self) -> None:  # noqa: N802 - Qt override name
            self.hide_popup_called = True
            super().hidePopup()

    app = QApplication.instance() or QApplication([])
    combo = TrackingCombo()
    try:
        combo.addItems(["A", "B"])
        combo.show()
        app.processEvents()
        combo.showPopup()
        app.processEvents()

        pyside6_app._suppress_transient_popups(0)

        assert combo.hide_popup_called
        assert not combo.view().isVisible()
        assert not combo.view().isHidden()

        pyside6_app._TRANSIENT_POPUP_SUPPRESS_UNTIL = 0
        combo.showPopup()
        app.processEvents()
        assert combo.view().isVisible()
    finally:
        pyside6_app._TRANSIENT_POPUP_SUPPRESS_UNTIL = 0
        combo.close()
        app.processEvents()


def test_transient_popup_guard_blocks_delayed_combo_popups(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QComboBox
    import gear_optimizer.pyside6_app as pyside6_app

    class TrackingCombo(QComboBox):
        def __init__(self) -> None:
            super().__init__()
            self.hide_popup_called = False

        def hidePopup(self) -> None:  # noqa: N802 - Qt override name
            self.hide_popup_called = True
            super().hidePopup()

    app = QApplication.instance() or QApplication([])
    pyside6_app._install_transient_popup_guard()
    combo = TrackingCombo()
    try:
        combo.addItems(["A", "B"])
        combo.show()
        app.processEvents()

        pyside6_app._suppress_transient_popups(2000)
        app.processEvents()
        combo.hide_popup_called = False

        combo.showPopup()
        app.processEvents()

        assert combo.hide_popup_called
        assert not combo.view().isVisible()
        assert not combo.view().isHidden()
    finally:
        pyside6_app._TRANSIENT_POPUP_SUPPRESS_UNTIL = 0
        combo.close()
        app.processEvents()


def test_user_combo_press_clears_transient_popup_suppression(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QComboBox
    import gear_optimizer.pyside6_app as pyside6_app

    app = QApplication.instance() or QApplication([])
    pyside6_app._install_transient_popup_guard()
    combo = QComboBox()
    try:
        combo.addItems(["A", "B"])
        combo.show()
        app.processEvents()

        pyside6_app._suppress_transient_popups(2000)
        assert pyside6_app._transient_popups_suppressed()

        assert pyside6_app._TRANSIENT_POPUP_GUARD is not None
        pyside6_app._TRANSIENT_POPUP_GUARD.eventFilter(
            combo,
            QEvent(QEvent.Type.MouseButtonPress),
        )

        assert not pyside6_app._transient_popups_suppressed()
    finally:
        combo.close()
        app.processEvents()


def test_delayed_popup_cleanup_does_not_hide_user_opened_combo(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QComboBox
    import gear_optimizer.pyside6_app as pyside6_app

    class TrackingCombo(QComboBox):
        def __init__(self) -> None:
            super().__init__()
            self.hide_popup_called = False

        def hidePopup(self) -> None:  # noqa: N802 - Qt override name
            self.hide_popup_called = True
            super().hidePopup()

    app = QApplication.instance() or QApplication([])
    pyside6_app._install_transient_popup_guard()
    combo = TrackingCombo()
    try:
        combo.addItems(["A", "B"])
        combo.show()
        app.processEvents()

        pyside6_app._suppress_transient_popups(2000)
        combo.hide_popup_called = False

        assert pyside6_app._TRANSIENT_POPUP_GUARD is not None
        pyside6_app._TRANSIENT_POPUP_GUARD.eventFilter(
            combo,
            QEvent(QEvent.Type.MouseButtonPress),
        )
        pyside6_app._hide_transient_popups_if_suppressed()

        assert not combo.hide_popup_called
    finally:
        combo.close()
        app.processEvents()


def test_cleanup_successful_action_run_dirs_keeps_failures_and_recent_successes(tmp_path):
    pytest.importorskip("PySide6")

    from gear_optimizer.pyside6_app import cleanup_successful_action_run_dirs

    success_dirs = []
    for index in range(5):
        run_dir = tmp_path / f"gear-action-ev-success-{index}"
        run_dir.mkdir()
        summary_path = run_dir / "summary.json"
        summary_path.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        timestamp = 1_700_000_000 + index
        os.utime(summary_path, (timestamp, timestamp))
        success_dirs.append(run_dir)

    failed_dir = tmp_path / "gear-action-ev-failed"
    failed_dir.mkdir()
    (failed_dir / "summary.json").write_text(json.dumps({"status": "error"}), encoding="utf-8")
    cancelled_dir = tmp_path / "gear-action-ev-cancelled"
    cancelled_dir.mkdir()

    removed = cleanup_successful_action_run_dirs(tmp_path, keep=3)

    assert {path.name for path in removed} == {"gear-action-ev-success-0", "gear-action-ev-success-1"}
    assert not success_dirs[0].exists()
    assert not success_dirs[1].exists()
    assert all(path.exists() for path in success_dirs[2:])
    assert failed_dir.exists()
    assert cancelled_dir.exists()


def test_piece_editor_uses_card_controls_and_can_check_best_loadout(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.pyside6_app import GearPieceEditDialog, OptimizerWindow, _default_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_piece(game, character, game.positions[0].id).model_copy(update={"locked": False})
        dialog = GearPieceEditDialog(
            game,
            character,
            piece,
            editable_position=True,
            title="测试编辑装备",
            parent=window,
            optimal_check_callback=lambda candidate: f"checked {candidate.set_name}",
        )
        try:
            assert not hasattr(dialog, "table")
            assert dialog.set_card_scroll.widget() is dialog.set_card_host
            assert dialog.main_stat_card_host is not None
            assert len(dialog.substat_cards) == 4
            assert dialog.level_spin.minimumHeight() >= 44
            assert dialog.level_spin.isAccelerated()
            assert dialog.substat_cards[0].roll_spin.minimumHeight() >= 44
            assert dialog.substat_cards[0].roll_spin.isAccelerated()
            assert dialog.check_button.isEnabled()
            assert "未满级会按满级强化期望估值" in dialog.check_result_label.text()
            valid_set = game.sets_for_position(piece.position)[-1]
            dialog._select_set(valid_set)
            assert dialog._selected_set == valid_set
            dialog._move_substat_card(0, 1)
            assert dialog.substat_cards[0].index == 0
            dialog._run_optimal_check()
            assert "checked" in dialog.check_result_label.text()
        finally:
            dialog.close()
    finally:
        window.close()
        app.processEvents()


def test_piece_editor_and_cards_show_revealed_next_substat(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.game_rules import load_characters, load_game
    from gear_optimizer.models import GearPiece, SubstatLine
    from gear_optimizer.pyside6_app import GearPieceEditDialog, GearTable, PieceCard

    app = QApplication.instance() or QApplication([])
    game = load_game("hsr")
    character = next(item for item in load_characters("hsr") if item.id == "hsr_placeholder")
    zzz_game = load_game("zzz")
    zzz_character = next(item for item in load_characters("zzz") if item.id == "zzz_starlight_billy")
    piece = GearPiece(
        position="body",
        set_name="识海迷坠的学者",
        main_stat="暴击率",
        level=0,
        initial_substat_count=3,
        substats=[
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="攻击力百分比", rolls=0),
            SubstatLine(stat="生命值百分比", rolls=0),
        ],
        revealed_next_substat="速度",
    )
    dialog = GearPieceEditDialog(
        game,
        character,
        piece,
        editable_position=True,
        title="测试预告副属性",
    )
    table = GearTable(editable_positions=True, row_label_prefix="库存")
    card = PieceCard(0, show_actions=True)
    zzz_piece = GearPiece(
        position=6,
        set_name="云岿如我",
        main_stat="生命值百分比",
        level=0,
        initial_substat_count=3,
        substats=[
            SubstatLine(stat="暴击率", rolls=0),
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="攻击力百分比", rolls=0),
        ],
        revealed_next_substat="穿透值",
    )
    zzz_dialog = GearPieceEditDialog(
        zzz_game,
        zzz_character,
        zzz_piece,
        editable_position=True,
        title="测试不支持预告副属性",
    )
    stale_revealed_piece = GearPiece(
        position="body",
        set_name="识海迷坠的学者",
        main_stat="暴击率",
        level=game.enhancement.initial_add_level,
        initial_substat_count=3,
        substats=[
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="攻击力百分比", rolls=0),
            SubstatLine(stat="生命值百分比", rolls=0),
            SubstatLine(stat="防御力百分比", rolls=0),
        ],
        revealed_next_substat="速度",
    )
    try:
        assert dialog.revealed_next_combo.isEnabled()
        assert dialog.revealed_next_combo.currentData() == "速度"
        assert dialog._build_piece().revealed_next_substat == "速度"

        dialog.level_spin.setValue(game.enhancement.initial_add_level)

        assert not dialog.revealed_next_combo.isEnabled()
        assert dialog._build_piece().revealed_next_substat is None

        card.update_piece(piece, game, character)
        assert "预告第4副属性：速度" in card.substat_label.text()
        assert "预告第4副属性：速度" in card.toolTip()

        table.set_context(game, character, [piece])
        roundtrip_pieces, warnings = table.collect_pieces()
        assert warnings == []
        assert roundtrip_pieces[0].revealed_next_substat == "速度"

        assert not zzz_dialog.revealed_next_combo.isEnabled()
        assert "不支持记录预告第 4 副属性" in zzz_dialog.revealed_next_hint.text()
        assert zzz_dialog._build_piece().revealed_next_substat is None

        card.update_piece(zzz_piece, zzz_game, zzz_character)
        assert "预告第4副属性：穿透值（当前游戏不支持，计算会忽略）" in card.substat_label.text()
        assert "当前游戏不支持，计算会忽略" in card.toolTip()

        card.update_piece(stale_revealed_piece, game, character)
        assert "预告第4副属性：速度（当前状态不适用，计算会忽略）" in card.substat_label.text()
        assert "当前状态不适用，计算会忽略" in card.toolTip()

        table.set_context(zzz_game, zzz_character, [zzz_piece])
        zzz_roundtrip, zzz_warnings = table.collect_pieces()
        assert zzz_warnings == []
        assert zzz_roundtrip[0].revealed_next_substat is None
    finally:
        zzz_dialog.close()
        dialog.close()
        table.close()
        card.close()
        app.processEvents()


def test_add_inventory_opens_editor_before_adding(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QDialog
    import gear_optimizer.pyside6_app as pyside6_app
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece, _default_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        default_inventory = _default_inventory_piece(game, character, game.positions[0].id)
        assert default_inventory.level == 0
        assert default_inventory.initial_substat_count == 3
        assert len(default_inventory.substats) == 3
        created_piece = _default_piece(game, character, game.positions[-1].id).model_copy(update={"locked": False})
        calls = []

        class FakeDialog:
            def __init__(self, *_args, **_kwargs):
                calls.append(_kwargs.get("title"))
                self.piece = created_piece

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(pyside6_app, "GearPieceEditDialog", FakeDialog)

        window.add_inventory()

        pieces = window._hidden_table_pieces(window.inventory_table)
        assert calls == ["新增库存件"]
        assert len(pieces) == 1
        assert pieces[0].position == created_piece.position
        assert window._selected_inventory_source_row() == 0
        assert len(window.inventory_cards) == 1
        assert window.inventory_cards[0].row_index == 0
        assert window.inventory_cards[0].is_selected
        assert "库存 #1" in window.inventory_detail_label.text()
        assert "已添加一件库存" in window.progress_label.text()
    finally:
        window.close()
        app.processEvents()


def test_add_inventory_cancel_reports_no_change(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QDialog
    import gear_optimizer.pyside6_app as pyside6_app
    from gear_optimizer.pyside6_app import OptimizerWindow

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        class FakeDialog:
            piece = None

            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return QDialog.DialogCode.Rejected

        monkeypatch.setattr(pyside6_app, "GearPieceEditDialog", FakeDialog)

        window.add_inventory()

        assert window.inventory_table.rowCount() == 0
        assert "已取消新增库存" in window.progress_label.text()
        assert "库存未变化" in window.progress_label.text()
    finally:
        window.close()
        app.processEvents()


def test_add_inventory_mentions_when_filters_hide_new_piece(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QDialog
    import gear_optimizer.pyside6_app as pyside6_app
    from gear_optimizer.models import position_key
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        created_piece = _default_inventory_piece(game, character, game.positions[0].id)
        hidden_by_position = str(position_key(game.positions[-1].id))
        hidden_index = window.position_filter.findData(hidden_by_position)
        assert hidden_index >= 0
        window.position_filter.setCurrentIndex(hidden_index)

        class FakeDialog:
            def __init__(self, *_args, **_kwargs):
                self.piece = created_piece

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(pyside6_app, "GearPieceEditDialog", FakeDialog)

        window.add_inventory()

        assert len(window._hidden_table_pieces(window.inventory_table)) == 1
        assert len(window.inventory_cards) == 0
        assert "当前筛选隐藏了这件" in window.progress_label.text()
        assert window.clear_inventory_filters_button.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_edit_inventory_mentions_when_filters_hide_updated_piece(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QDialog
    import gear_optimizer.pyside6_app as pyside6_app
    from gear_optimizer.models import position_key
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        visible_piece = _default_inventory_piece(game, character, game.positions[0].id)
        hidden_piece = _default_inventory_piece(game, character, game.positions[-1].id)
        window.inventory_table.set_context(game, character, [visible_piece])
        window._inventory_changed()
        visible_position = str(position_key(visible_piece.position))
        position_index = window.position_filter.findData(visible_position)
        assert position_index >= 0
        window.position_filter.setCurrentIndex(position_index)
        assert len(window.inventory_cards) == 1

        class FakeDialog:
            def __init__(self, *_args, **_kwargs):
                self.piece = hidden_piece

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(pyside6_app, "GearPieceEditDialog", FakeDialog)

        window.edit_inventory_piece(0)

        assert len(window.inventory_cards) == 0
        assert "已更新库存 #1" in window.progress_label.text()
        assert "当前筛选隐藏了这件" in window.progress_label.text()
    finally:
        window.close()
        app.processEvents()


def test_save_inventory_warns_before_persisting_duplicate_pieces(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece
    from gear_optimizer.user_inventory import load_user_inventory, user_inventory_store_path

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        duplicate = piece.model_copy(deep=True)
        window.inventory_table.set_context(game, character, [piece, duplicate])
        window._inventory_changed()
        path = user_inventory_store_path(game.id, window.selected_storage_character_id())

        questions = []

        def deny_save(*args, **_kwargs):
            questions.append(args[2])
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(QMessageBox, "question", deny_save)
        window.save_inventory()

        assert questions
        assert "完全重复" in questions[0]
        assert "#1、#2" in questions[0]
        assert not path.exists()
        assert "已取消保存库存" in window.progress_label.text()

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        window.save_inventory()

        assert path.exists()
        assert len(load_user_inventory(game.id, window.selected_storage_character_id())) == 2
    finally:
        window.close()
        app.processEvents()


def test_save_empty_inventory_requires_confirmation_before_clearing_saved_file(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece
    from gear_optimizer.user_inventory import load_user_inventory, save_user_inventory

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        storage_id = window.selected_storage_character_id()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        save_user_inventory(game.id, storage_id, [piece])
        window.inventory_table.set_context(game, character, [])
        window._inventory_changed()

        questions = []

        def deny_empty_save(*args, **_kwargs):
            questions.append((args[1], args[2]))
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(QMessageBox, "question", deny_empty_save)
        window.save_inventory()

        assert questions
        assert questions[0][0] == "保存空库存？"
        assert "覆盖为空列表" in questions[0][1]
        assert len(load_user_inventory(game.id, storage_id)) == 1
        assert window.progress_label.text() == "已取消保存空库存；本机库存未变化。"

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        window.save_inventory()

        assert load_user_inventory(game.id, storage_id) == []
        assert "已保存 0 件库存" in window.progress_label.text()
    finally:
        window.close()
        app.processEvents()


def test_save_empty_inventory_requires_confirmation_before_masking_legacy_source(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece
    from gear_optimizer.user_inventory import (
        load_user_inventory,
        save_user_inventory,
        user_inventory_store_path,
    )
    from gear_optimizer.user_target_templates import save_user_target_template

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        source_agent = next(agent for agent in window.agents if agent.agent_id != agent.character_preset_id)
        source_template = next(
            character
            for character in window.characters
            if character.id == source_agent.character_preset_id
        )
        legacy_piece = _default_inventory_piece(game, source_template, game.positions[0].id)
        save_user_inventory(game.id, source_agent.character_preset_id, [legacy_piece])
        saved = save_user_target_template(
            game.id,
            source_template.model_copy(update={"name": "回退库存目标"}),
            "回退库存目标",
            source_character_id=source_agent.character_preset_id,
            source_agent_id=source_agent.agent_id,
        )

        window._reload_target_template_options(saved.id)
        window._reload_character_context()
        target_path = user_inventory_store_path(game.id, source_agent.agent_id)

        assert not target_path.exists()
        assert window._inventory_loaded_storage_id == source_agent.character_preset_id
        assert len(window._hidden_table_pieces(window.inventory_table)) == 1

        window.inventory_table.set_context(game, window.selected_character(), [])
        window._inventory_changed()
        questions = []

        def deny_empty_save(*args, **_kwargs):
            questions.append((args[1], args[2]))
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(QMessageBox, "question", deny_empty_save)
        window.save_inventory()

        assert questions
        assert questions[0][0] == "保存空库存？"
        assert "旧来源库存会被遮住" in questions[0][1]
        assert not target_path.exists()
        assert len(load_user_inventory(game.id, source_agent.character_preset_id)) == 1
        assert window.progress_label.text() == "已取消保存空库存；本机库存未变化。"

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        window.save_inventory()

        assert target_path.exists()
        assert load_user_inventory(game.id, source_agent.agent_id) == []
        assert len(load_user_inventory(game.id, source_agent.character_preset_id)) == 1
        assert "已保存 0 件库存" in window.progress_label.text()
    finally:
        window.close()
        app.processEvents()


def test_inventory_cards_show_duplicate_warnings(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.models import position_key
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        duplicate = piece.model_copy(deep=True)
        distinct = _default_inventory_piece(game, character, game.positions[-1].id)
        window.inventory_table.set_context(game, character, [piece, duplicate, distinct])
        window._inventory_changed()

        assert "重复提示 2 件" in window.inventory_card_status_label.text()
        assert len(window.inventory_cards) == 3
        duplicate_cards = [
            card for card in window.inventory_cards if not card.duplicate_badge.isHidden()
        ]
        assert len(duplicate_cards) == 2
        assert all(card.duplicate_badge.text() == "重复" for card in duplicate_cards)
        assert "完全重复：#1、#2" in window.inventory_cards[0].duplicate_badge.toolTip()
        assert "重复提示：完全重复：#1、#2" in window.inventory_detail_label.text()

        window.select_inventory_piece(1)
        assert "库存 #2" in window.inventory_detail_label.text()
        assert "重复提示：完全重复：#1、#2" in window.inventory_detail_label.text()

        window.duplicate_filter.setChecked(True)

        assert len(window.inventory_cards) == 2
        assert {card.index_badge.text() for card in window.inventory_cards} == {"库存 #1", "库存 #2"}
        assert "显示 2 / 3 件库存" in window.inventory_card_status_label.text()
        assert "筛选：重复库存" in window.inventory_card_status_label.text()
    finally:
        window.close()
        app.processEvents()


def test_inventory_status_lists_highlighted_inventory_numbers(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        pieces = [
            _default_inventory_piece(game, character, game.positions[index % len(game.positions)].id)
            for index in range(3)
        ]
        alternate_sets = [
            set_name for set_name in game.sets_for_position(pieces[2].position)
            if set_name != pieces[0].set_name
        ]
        assert alternate_sets
        pieces[2] = pieces[2].model_copy(update={"set_name": alternate_sets[0]})
        window.inventory_table.set_context(game, character, pieces)
        window._highlighted_inventory_source_rows = {0, 2}
        window._highlighted_inventory_label = "最优"
        window._refresh_inventory_view()

        status_text = window.inventory_card_status_label.text()
        assert "高亮 2 件" in status_text
        assert "最优：库存 #1、库存 #3" in status_text
        assert not window.inventory_cards[0].highlight_badge.isHidden()
        assert window.inventory_cards[0].highlight_badge.text() == "最优"
        assert not window.inventory_cards[2].highlight_badge.isHidden()

        set_index = window.set_filter.findData(pieces[0].set_name)
        assert set_index >= 0
        window.set_filter.setCurrentIndex(set_index)

        filtered_status_text = window.inventory_card_status_label.text()
        assert "最优：库存 #1、库存 #3" in filtered_status_text
        assert "其中 1 件高亮被当前筛选隐藏，点“清除筛选”可查看" in filtered_status_text

        window.clear_inventory_filters()
        window._highlighted_inventory_source_rows = set()
        window._fill_table(window.best_table, [{"状态": "已有结果"}])
        window._refresh_inventory_view()

        no_highlight_status = window.inventory_card_status_label.text()
        assert "当前结果未高亮库存" in no_highlight_status
        assert "高亮 0 件" not in no_highlight_status
    finally:
        window.close()
        app.processEvents()


def test_copy_inventory_marks_duplicate_immediately(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.models import position_key
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        window.inventory_table.set_context(game, character, [piece])
        window._inventory_changed()

        window.copy_inventory_piece(0)

        assert "新副本会标记为重复" in window.progress_label.text()
        assert "重复提示 2 件" in window.inventory_card_status_label.text()
        assert len(window.inventory_cards) == 2
        assert window._selected_inventory_source_row() == 1
        assert all(card.duplicate_badge.text() == "重复" for card in window.inventory_cards)
        assert all("完全重复：#1、#2" in card.duplicate_badge.toolTip() for card in window.inventory_cards)
    finally:
        window.close()
        app.processEvents()


def test_clear_inventory_substats_mentions_when_filters_hide_piece(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        duplicate = piece.model_copy(deep=True)
        window.inventory_table.set_context(game, character, [piece, duplicate])
        window._inventory_changed()
        window.duplicate_filter.setChecked(True)
        assert len(window.inventory_cards) == 2
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )

        window.clear_inventory_piece_substats(1)

        assert len(window.inventory_cards) == 0
        assert "已清空选中库存副词条" in window.progress_label.text()
        assert "当前筛选隐藏了这件" in window.progress_label.text()
    finally:
        window.close()
        app.processEvents()


def test_clear_inventory_substats_requires_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        window.inventory_table.set_context(game, character, [piece])
        window._inventory_changed()

        prompts = []

        def reject_clear(_parent, title, text, *_args, **_kwargs):
            prompts.append((title, text))
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(QMessageBox, "question", reject_clear)
        window.clear_inventory_piece_substats(0)

        pieces = window._hidden_table_pieces(window.inventory_table)
        assert len(pieces[0].substats) == len(piece.substats)
        assert prompts and prompts[0][0] == "清空副词条？"
        assert "库存 #1" in prompts[0][1]
        assert "仍需点击“保存库存到本机”" in prompts[0][1]
        assert "已取消清空副词条" in window.progress_label.text()
    finally:
        window.close()
        app.processEvents()


def test_clear_inventory_substats_also_clears_revealed_next_substat(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.game_rules import load_characters, load_game
    from gear_optimizer.models import GearPiece, SubstatLine
    from gear_optimizer.pyside6_app import OptimizerWindow

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = load_game("hsr")
        character = next(item for item in load_characters("hsr") if item.id == "hsr_placeholder")
        hsr_index = window.game_combo.findData("hsr")
        assert hsr_index >= 0
        window.game_combo.setCurrentIndex(hsr_index)
        piece = GearPiece(
            position="body",
            set_name="识海迷坠的学者",
            main_stat="暴击率",
            level=0,
            initial_substat_count=3,
            substats=[
                SubstatLine(stat="暴击伤害", rolls=0),
                SubstatLine(stat="攻击力百分比", rolls=0),
                SubstatLine(stat="生命值百分比", rolls=0),
            ],
            revealed_next_substat="速度",
        )
        window.inventory_table.set_context(game, character, [piece])
        window._inventory_changed()
        assert "预告第4副属性：速度" in window.inventory_cards[0].substat_label.text()
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )

        window.clear_inventory_piece_substats(0)

        pieces = window._hidden_table_pieces(window.inventory_table)
        assert pieces[0].substats == []
        assert pieces[0].revealed_next_substat is None
        assert "预告第4副属性" not in window.inventory_cards[0].substat_label.text()
        assert "已清空选中库存副词条" in window.progress_label.text()
    finally:
        window.close()
        app.processEvents()


def test_equip_inventory_mentions_when_returned_current_is_hidden_by_filters(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        position = game.positions[0].id
        set_names = game.sets_for_position(position)
        assert len(set_names) >= 2
        old_set, visible_set = set_names[0], set_names[1]
        current_piece = _default_inventory_piece(game, character, position).model_copy(
            update={"set_name": old_set}
        )
        inventory_piece = _default_inventory_piece(game, character, position).model_copy(
            update={"set_name": visible_set}
        )
        window.current_table.set_context(game, character, [current_piece])
        window.inventory_table.set_context(game, character, [inventory_piece])
        window._inventory_changed()
        set_index = window.set_filter.findData(visible_set)
        assert set_index >= 0
        window.set_filter.setCurrentIndex(set_index)
        assert len(window.inventory_cards) == 1

        window.equip_inventory_piece(0)

        inventory_pieces = window._hidden_table_pieces(window.inventory_table)
        current_pieces = window._hidden_table_pieces(window.current_table)
        assert [piece.set_name for piece in current_pieces] == [visible_set]
        assert [piece.set_name for piece in inventory_pieces] == [old_set]
        assert len(window.inventory_cards) == 0
        assert "原当前件已放回库存" in window.progress_label.text()
        assert "当前筛选隐藏了换回库存的旧当前件" in window.progress_label.text()
        assert window.clear_inventory_filters_button.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_duplicate_filter_empty_state_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        window.inventory_table.set_context(game, character, [piece])
        window._inventory_changed()

        window.duplicate_filter.setChecked(True)

        assert len(window.inventory_cards) == 0
        assert "当前没有重复库存" in window.inventory_card_status_label.text()
        assert "筛选：重复库存" in window.inventory_card_status_label.text()
        assert window.inventory_detail_label.text() == "当前没有重复库存。"
    finally:
        window.close()
        app.processEvents()


def test_delete_inventory_requires_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        window.inventory_table.set_context(game, character, [piece])
        window._inventory_changed()

        prompts = []

        def reject_delete(_parent, title, text, *_args, **_kwargs):
            prompts.append((title, text))
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(QMessageBox, "question", reject_delete)
        window.delete_inventory_piece(0)

        assert window.inventory_table.rowCount() == 1
        assert prompts and prompts[0][0] == "删除库存件？"
        assert "库存 #1" in prompts[0][1]
        assert "仍需点击“保存库存到本机”" in prompts[0][1]
        assert "已取消删除库存" in window.progress_label.text()

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        window.delete_inventory_piece(0)

        assert window.inventory_table.rowCount() == 0
        assert "已删除选中库存" in window.progress_label.text()
    finally:
        window.close()
        app.processEvents()


def test_inventory_actions_report_stale_source_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.pyside6_app import OptimizerWindow

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        for action in [
            window.copy_inventory_piece,
            window.clear_inventory_piece_substats,
            window.delete_inventory_piece,
            window.equip_inventory_piece,
        ]:
            window.progress_label.setText("")
            action(99)
            assert window.progress_label.text() == "库存行已不存在，请重新选择。"
    finally:
        window.close()
        app.processEvents()


def test_clear_inventory_filters_restores_full_inventory_view(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.models import position_key
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        first = _default_inventory_piece(game, character, game.positions[0].id)
        second = _default_inventory_piece(game, character, game.positions[-1].id)
        window.inventory_table.set_context(game, character, [first, second])
        window._inventory_changed()

        second_position = str(position_key(second.position))
        position_index = window.position_filter.findData(second_position)
        assert position_index >= 0
        window.position_filter.setCurrentIndex(position_index)
        window.unfinished_filter.setChecked(True)
        window.duplicate_filter.setChecked(True)
        assert len(window.inventory_cards) == 0
        assert window.clear_inventory_filters_button.isEnabled()
        assert "筛选：位置=" in window.inventory_card_status_label.text()
        assert "未满级" in window.inventory_card_status_label.text()
        assert "重复库存" in window.inventory_card_status_label.text()

        window.clear_inventory_filters()

        assert window.position_filter.currentData() == ""
        assert window.set_filter.currentData() == ""
        assert window.main_filter.currentData() == ""
        assert not window.unfinished_filter.isChecked()
        assert not window.duplicate_filter.isChecked()
        assert not window.clear_inventory_filters_button.isEnabled()
        assert len(window.inventory_cards) == 2
        assert "已清除库存筛选" in window.progress_label.text()
        assert "显示 2 / 2 件库存" in window.inventory_card_status_label.text()
        assert "筛选：" not in window.inventory_card_status_label.text()
    finally:
        window.close()
        app.processEvents()


def test_inventory_export_includes_duplicate_notes(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        duplicate = piece.model_copy(deep=True)
        distinct = _default_inventory_piece(game, character, game.positions[-1].id)
        window.inventory_table.set_context(game, character, [piece, duplicate, distinct])
        window._inventory_changed()

        window.export_inventory_details()

        exported = json.loads((PROJECT_ROOT / "reports" / "inventory_export.json").read_text(encoding="utf-8"))
        assert exported["input_audit"] == window.input_audit_label.text()
        assert exported["input_audit_lines"] == window.input_audit_label.text().splitlines()
        assert "输入指纹：" in exported["input_audit"]
        assert exported["duplicate_summary"] == {
            "exact_groups": [[1, 2]],
            "similar_groups": [],
            "exact_group_count": 1,
            "similar_group_count": 0,
            "flagged_piece_count": 2,
        }
        assert [item["inventory_index"] for item in exported["pieces"]] == [1, 2, 3]
        assert exported["pieces"][0]["duplicate_note"] == "完全重复：#1、#2"
        assert exported["pieces"][1]["duplicate_note"] == "完全重复：#1、#2"
        assert "duplicate_note" not in exported["pieces"][2]
    finally:
        window.close()
        app.processEvents()


def test_save_inventory_warns_on_unordered_duplicate_pieces(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        reordered = piece.model_copy(
            update={"substats": list(reversed(piece.substats))},
            deep=True,
        )
        window.inventory_table.set_context(game, character, [piece, reordered])
        window._inventory_changed()

        questions = []
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **_kwargs: (
                questions.append(args[2]) or QMessageBox.StandardButton.No
            ),
        )
        window.save_inventory()

        assert questions
        assert "疑似重复" in questions[0]
        assert "完全重复" not in questions[0]
        assert "已取消保存库存" in window.progress_label.text()
    finally:
        window.close()
        app.processEvents()


def test_gear_piece_entry_consistency_flags_substat_and_roll_mismatches():
    pytest.importorskip("PySide6")

    from gear_optimizer.game_rules import load_game
    from gear_optimizer.models import GearPiece, SubstatLine
    from gear_optimizer.pyside6_app import gear_piece_entry_consistency_issues

    game = load_game("zzz")
    position = game.positions[0]
    main_stat = position.main_stats[0]
    set_name = game.sets[0]
    substat_names = game.available_substats(main_stat)[:4]

    def make_piece(
        *,
        initial_substat_count: int,
        level: int,
        substat_count: int,
        rolls: list[int] | None = None,
    ) -> GearPiece:
        roll_values = rolls or [0] * substat_count
        return GearPiece(
            position=position.id,
            set_name=set_name,
            main_stat=main_stat,
            level=level,
            initial_substat_count=initial_substat_count,
            substats=[
                SubstatLine(
                    stat=substat_names[index],
                    rolls=roll_values[index] if index < len(roll_values) else 0,
                )
                for index in range(substat_count)
            ],
        )

    errors, warnings = gear_piece_entry_consistency_issues(
        make_piece(initial_substat_count=4, level=0, substat_count=3),
        game,
    )
    assert errors == []
    assert any("通常应显示 4 条副属性" in warning for warning in warnings)

    errors, warnings = gear_piece_entry_consistency_issues(
        make_piece(initial_substat_count=3, level=0, substat_count=4),
        game,
    )
    assert warnings == []
    assert any("最多应显示 3 条副属性" in error for error in errors)

    errors, warnings = gear_piece_entry_consistency_issues(
        make_piece(initial_substat_count=3, level=3, substat_count=3),
        game,
    )
    assert errors == []
    assert any("通常应显示 4 条副属性" in warning for warning in warnings)

    errors, warnings = gear_piece_entry_consistency_issues(
        make_piece(initial_substat_count=4, level=3, substat_count=4),
        game,
    )
    assert errors == []
    assert any("通常应有 1 次副属性强化" in warning for warning in warnings)

    errors, warnings = gear_piece_entry_consistency_issues(
        make_piece(initial_substat_count=3, level=3, substat_count=4, rolls=[1, 0, 0, 0]),
        game,
    )
    assert warnings == []
    assert any("最多应有 0 次副属性强化" in error for error in errors)

    unsupported_reveal = make_piece(initial_substat_count=3, level=0, substat_count=3).model_copy(
        update={"revealed_next_substat": game.available_substats(main_stat)[3]}
    )
    errors, warnings = gear_piece_entry_consistency_issues(unsupported_reveal, game)
    assert warnings == []
    assert any("当前不支持记录预告第 4 副属性" in error for error in errors)

    hsr = load_game("hsr")
    revealed_after_add_event = GearPiece(
        position="body",
        set_name="识海迷坠的学者",
        main_stat="暴击率",
        initial_substat_count=3,
        level=3,
        substats=[
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="攻击力百分比", rolls=0),
            SubstatLine(stat="生命值百分比", rolls=0),
            SubstatLine(stat="速度", rolls=0),
        ],
        revealed_next_substat="击破特攻",
    )
    errors, warnings = gear_piece_entry_consistency_issues(revealed_after_add_event, hsr)
    assert warnings == []
    assert any("不能记录预告第 4 副属性" in error for error in errors)

    unknown_revealed = GearPiece(
        position="body",
        set_name="识海迷坠的学者",
        main_stat="暴击率",
        initial_substat_count=3,
        level=0,
        substats=[
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="攻击力百分比", rolls=0),
            SubstatLine(stat="生命值百分比", rolls=0),
        ],
        revealed_next_substat="不存在副属性",
    )
    errors, warnings = gear_piece_entry_consistency_issues(unknown_revealed, hsr)
    assert warnings == []
    assert any("不是 崩坏：星穹铁道 的合法副属性" in error for error in errors)


def test_hsr_default_pieces_use_position_legal_sets():
    pytest.importorskip("PySide6")

    from gear_optimizer.game_rules import load_characters, load_game, validate_gear_piece_against_game
    from gear_optimizer.pyside6_app import _default_inventory_piece, _default_piece

    game = load_game("hsr")
    character = next(item for item in load_characters("hsr") if item.id == "hsr_placeholder")

    for position in game.positions:
        default_piece = _default_piece(game, character, position.id)
        default_inventory = _default_inventory_piece(game, character, position.id)
        validate_gear_piece_against_game(default_piece, game)
        validate_gear_piece_against_game(default_inventory, game)
        assert default_piece.set_name in game.sets_for_position(position.id)
        assert default_inventory.set_name in game.sets_for_position(position.id)


def test_horizon_one_gain_summary_marks_no_positive_gain(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.pyside6_app import OptimizerWindow

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        no_gain_rows = [
            {
                "horizon": 1,
                "套装约束": "满足",
                "有效提升": 0,
                "质量提升": 1.0,
                "_sort_vector": (1.0, 1.0),
            }
        ]
        gain_rows = [
            {
                "策略": "固定位置",
                "horizon": 1,
                "套装约束": "满足",
                "有效提升": 0.2,
                "质量提升": 0.2,
                "有效/母盘": 0.2,
                "_sort_vector": (0.2, 0.2),
            }
        ]
        upgrade_rows = [
            {
                "策略": "强化库存胚子",
                "horizon": 1,
                "套装约束": "满足",
                "有效提升": 0.4,
                "质量提升": 0.4,
                "有效/母盘": 0.4,
                "_sort_vector": (0.4, 0.4),
            }
        ]

        assert "当前可用调律 action 均无有效提升" in window._action_gain_summary_text(no_gain_rows)
        assert "1/1 个有效提升为正" in window._action_gain_summary_text(gain_rows)
        upgrade_summary = window._action_gain_summary_text([*gain_rows, *upgrade_rows])
        assert "调律有效/母盘最高为 0.2" in upgrade_summary
        assert "库存升级机会：1/1 个升级机会有效提升为正" in upgrade_summary
        assert "非调律，仅提示，不参与主调律推荐" in upgrade_summary
        assert "个胚子有效提升为正" not in upgrade_summary
    finally:
        window.close()
        app.processEvents()


def test_action_finished_shows_upgrade_opportunity_without_tuning_recommendation(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        window.inventory_table.set_context(game, character, [piece])
        window._refresh_inventory_view()

        window._on_action_finished(
            [
                {
                    "策略": "强化库存胚子",
                    "动作类型": "库存升级机会",
                    "目标套装": piece.set_name,
                    "位置": game.position_name(piece.position),
                    "主属性": piece.main_stat,
                    "固定副属性": "不固定",
                    "horizon": 1,
                    "套装约束": "满足",
                    "有效提升": 0.4,
                    "质量提升": 0.4,
                    "有效/母盘": 0.0,
                    "期望提升": "有效 +0.4",
                    "_upgrade_inventory_id": "piece:0",
                    "_sort_vector": (0.4, 0.4),
                }
            ]
        )

        assert window.result_recommend_title.text() == "暂无可推荐调律 action；有库存升级机会"
        assert "机会动作：非调律：升级已有库存" in window.result_recommend_detail.text()
        assert "库存编号：库存 #1" in window.result_recommend_detail.text()
        assert window._highlighted_inventory_label == "机会"
        assert window._highlighted_inventory_source_rows == {0}
        assert window.progress_label.text() == "Action EV 结果已计算完成。"
        assert "结果已更新" in window.progress_meter_label.text()
        assert "推荐已更新" not in window.progress_meter_label.text()
        assert not window.inventory_cards[0].highlight_badge.isHidden()
        assert window.inventory_cards[0].highlight_badge.text() == "机会"
    finally:
        window.close()
        app.processEvents()


def test_action_finished_without_recommendation_keeps_default_highlight_label(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        window.inventory_table.set_context(game, character, [piece])
        window._refresh_inventory_view()

        window._on_action_finished(
            [
                {
                    "策略": "固定位置",
                    "目标套装": piece.set_name,
                    "位置": game.position_name(piece.position),
                    "主属性": piece.main_stat,
                    "固定副属性": "不固定",
                    "horizon": 1,
                    "套装约束": "满足",
                    "相对随机": "不如随机，不建议固定",
                    "有效提升": 0.0,
                    "质量提升": 0.0,
                    "有效/母盘": 0.0,
                    "质量/母盘": 0.0,
                    "期望提升": "无提升",
                    "_sort_vector": (0.0, 0.0),
                }
            ]
        )

        assert window.result_recommend_title.text() == "暂无可推荐 action"
        assert window._highlighted_inventory_label == "入选"
        assert window._highlighted_inventory_source_rows == set()
        assert "当前结果未高亮库存" in window.inventory_card_status_label.text()
    finally:
        window.close()
        app.processEvents()


def test_action_finished_hides_quality_only_recommendation_from_main_card(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.pyside6_app import OptimizerWindow, _default_inventory_piece

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        game = window.selected_game()
        character = window.selected_character()
        piece = _default_inventory_piece(game, character, game.positions[0].id)
        window.inventory_table.set_context(game, character, [piece])
        window._refresh_inventory_view()

        window._on_action_finished(
            [
                {
                    "策略": "随机位置",
                    "目标套装": piece.set_name,
                    "位置": "1-6 随机",
                    "主属性": "不固定",
                    "固定副属性": "不固定",
                    "horizon": 1,
                    "套装约束": "满足",
                    "相对随机": "随机位置是基础 action",
                    "有效提升": 0.0,
                    "质量提升": 1.0,
                    "有效/母盘": 0.0,
                    "质量/母盘": 1.0,
                    "期望提升": "质量 +1",
                    "_sort_vector": (1.0, 0.0),
                }
            ]
        )

        assert window.result_recommend_title.text() == "暂无有效提升 action"
        assert "当前桌面主口径不作为推荐" in window.result_recommend_detail.text()
        assert "推荐调律 action" not in window.result_recommend_title.text()
        assert window._highlighted_inventory_label == "入选"
        assert window._highlighted_inventory_source_rows == set()
        assert window.action_plan_summary_label.text() == "尚无 H=2 方案。"
        assert "排序最高 action 没有有效提升" in window.log.toPlainText()
    finally:
        window.close()
        app.processEvents()


def test_action_failed_uses_action_ev_wording(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication, QMessageBox
    from gear_optimizer.pyside6_app import OptimizerWindow

    app = QApplication.instance() or QApplication([])
    window = OptimizerWindow(width=1200, height=760)
    try:
        monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)

        window._on_action_failed("boom")

        assert window.progress_label.text() == "Action EV 计算失败。"
        assert window.result_recommend_title.text() == "Action EV 计算失败"
    finally:
        window.close()
        app.processEvents()


def test_windows_packaging_scripts_bundle_native_pyside6_resources():
    ps1 = PROJECT_ROOT / "scripts" / "build_windows_app.ps1"
    cmd = PROJECT_ROOT / "scripts" / "build_windows_app.cmd"

    script = ps1.read_text(encoding="utf-8")

    assert ps1.exists()
    assert cmd.exists()
    assert "--paths" in script
    assert "$Root\\src" in script
    assert "--add-data" in script
    assert "$Root\\src\\gear_optimizer;src\\gear_optimizer" in script
    assert "$Root\\configs;configs" in script
    assert "$Root\\assets;assets" in script
    assert "--collect-all" in script
    assert '"PySide6"' in script
    assert '"streamlit"' not in script
    assert '"webview"' not in script
    assert "--serve-streamlit" not in script
    assert "$Root\\desktop_app.py" in script
