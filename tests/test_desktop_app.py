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
    from gear_optimizer.pyside6_app import OptimizerWindow, PieceCard

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
        assert window.inventory_summary_table.columnCount() == 8
        assert window.inventory_summary_table.horizontalHeaderItem(0).text() == "位置"
        assert window.result_tabs.tabText(0) == "Action EV 明细"
        assert window.result_tabs.tabText(1) == "代表搭配"
        assert window.result_tabs.tabText(2) == "运行日志"
        assert not window.log.isVisible()
        assert not window.cancel_action_button.isEnabled()
        window.horizon_combo.setCurrentIndex(1)
        assert "完整概率分布精确计算" in window.horizon_note_label.text()
        assert "可取消" in window.horizon_note_label.text()
        window._on_action_progress({"event": "unit_progress", "completed": 50, "total": 100})
        assert window.progress_bar.value() == 0
        window._render_action_progress(window._last_action_progress_payload)
        assert window.progress_bar.value() == 50
        for method in [
            "confirm_current",
            "run_best_loadout",
            "run_action_ev",
            "cancel_action_ev",
            "edit_current_piece",
            "edit_inventory_piece",
        ]:
            assert callable(getattr(window, method))
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
