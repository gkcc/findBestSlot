import json
import os
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest
from gear_optimizer import launcher


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
    assert not any(dependency.startswith("streamlit") for dependency in data["project"]["dependencies"])
    assert "PySide6-Essentials==6.11.1" in optional["desktop"]
    assert "PySide6-Essentials==6.11.1" in optional["packaging"]


def test_optimizer_window_constructs_key_pyside6_components(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("GEAR_OPTIMIZER_USER_DATA_DIR", str(tmp_path / "user_data"))
    pytest.importorskip("PySide6")

    from PySide6.QtWidgets import QApplication
    from gear_optimizer.pyside6_app import ACTION_DETAIL_DISPLAY_LIMIT, OptimizerWindow, PieceCard

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
        assert window.overview_game_label.text()
        assert window.overview_confirm_label.text() in {"未确认", "已确认"}
        assert len(window.current_cards) == 6
        assert all(isinstance(card, PieceCard) for card in window.current_cards)
        assert window.current_cards[0].icon_label.toolTip()
        assert window._current_action_ev_engine() == "inventory_recursive"
        assert window.inventory_summary_table.isHidden()
        assert window.inventory_card_scroll.widget() is window.inventory_card_host
        assert "库存" in window.inventory_card_status_label.text()
        assert window.target_set_filter.text() == "只看目标套装"
        assert window.weak_position_filter.text() == "只看当前弱位"
        assert window.unfinished_filter.text() == "只看未满级胚子"
        assert window.replaceable_filter.text() == "只看可替换当前"
        game = window.selected_game()
        character = window.selected_character()
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
        assert window.current_confirmed_digest is None
        assert window.result_tabs.tabText(0) == "Action EV 明细"
        assert window.result_tabs.tabText(1) == "H=2 方案"
        assert window.result_tabs.tabText(2) == "代表搭配"
        assert window.result_tabs.tabText(3) == "运行日志"
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
            "质量/母盘": 0.25,
            "有效/母盘": 0.15,
            "排序向量/母盘": "internal-ish",
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
        assert "比较口径" in headers
        assert "代表分支搭配" in headers
        assert "质量/母盘" not in headers
        assert "预期搭配" not in headers
        assert "相对随机" not in headers
        assert "排序向量/母盘" not in headers
        assert "_sort_vector" not in headers
        assert window.show_all_actions_button.isEnabled()
        assert "显示全部" in window.show_all_actions_button.text()
        window.toggle_action_rows()
        assert window.action_table.rowCount() == ACTION_DETAIL_DISPLAY_LIMIT + 5
        assert "收起" in window.show_all_actions_button.text()
        card_text = window._recommended_action_card_text(sample_action_row)
        assert "推荐动作：固定位置" in card_text
        assert "方案类型：代表路径" in card_text
        assert "第二步策略摘要：固定位置 / 云岿如我 / 2号位" in card_text
        assert "质量/母盘" not in card_text
        assert "排序口径" in card_text
        assert "计算口径：精确" in card_text
        assert "计算引擎：inventory_recursive" in card_text
        assert "执行方式" in card_text
        assert "比较口径：优于随机，才建议固定" in card_text
        assert "固定位置是基础 action" in card_text
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
        ]:
            assert callable(getattr(window, method))
    finally:
        window.close()
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
            assert dialog.level_spin.minimumHeight() >= 38
            assert dialog.substat_cards[0].roll_spin.minimumHeight() >= 38
            assert dialog.check_button.isEnabled()
            dialog._select_set(game.sets[-1])
            assert dialog._selected_set == game.sets[-1]
            dialog._move_substat_card(0, 1)
            assert dialog.substat_cards[0].index == 0
            dialog._run_optimal_check()
            assert "checked" in dialog.check_result_label.text()
        finally:
            dialog.close()
    finally:
        window.close()
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
        assert "已添加一件库存" in window.progress_label.text()
    finally:
        window.close()
        app.processEvents()


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
                "质量提升": 0,
                "_sort_vector": (0.0, 0.0),
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

        assert "当前可用调律 action 均无正期望提升" in window._action_gain_summary_text(no_gain_rows)
        assert "1/1 个有正期望提升" in window._action_gain_summary_text(gain_rows)
        upgrade_summary = window._action_gain_summary_text([*gain_rows, *upgrade_rows])
        assert "调律有效/母盘最高为 0.2" in upgrade_summary
        assert "库存强化：1/1 个胚子有正期望" in upgrade_summary
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
