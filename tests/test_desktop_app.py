import json
import os
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import desktop_app
from gear_optimizer import launcher


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_parse_args_defaults_to_native_desktop_size():
    args = desktop_app.parse_args([])

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


def test_desktop_app_main_wraps_desktop_args(monkeypatch):
    calls = []

    def fake_module_main(args):
        calls.append(args)
        return 0

    monkeypatch.setattr(desktop_app.launcher, "module_main", fake_module_main)

    assert desktop_app.main(["--width", "1400"]) == 0
    assert calls == [["--desktop", "--width", "1400"]]


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
    assert not any(dependency.startswith("pandas") for dependency in data["project"]["dependencies"])
    assert not any(dependency.startswith("plotly") for dependency in data["project"]["dependencies"])
    assert "PySide6-Essentials==6.11.1" in optional["desktop"]
    assert "PySide6-Essentials==6.11.1" in optional["packaging"]
    assert not any(dependency.startswith("pywebview") for dependency in optional["desktop"])
    assert not any(dependency.startswith("pywebview") for dependency in optional["packaging"])


def test_native_desktop_source_uses_tabs_with_inventory_first():
    source = (PROJECT_ROOT / "src" / "gear_optimizer" / "pyside6_app.py").read_text(encoding="utf-8")

    assert "QTabWidget" in source
    assert 'self.tabs.addTab(inventory_page, "库存")' in source
    assert 'self.tabs.addTab(current_page, "当前装备")' in source
    assert 'self.tabs.addTab(result_page, "计算结果")' in source
    assert 'self.action_loadout_table = QTableWidget()' in source
    assert 'QLabel("推荐调律后代表搭配")' in source
    assert 'self._fill_table(self.action_loadout_table, loadout_rows)' in source
    assert source.index('inventory_group = QGroupBox("背包库存（未装备盘）")') < source.index(
        'current_group = QGroupBox("当前装备（身上 6 件）")'
    )
    assert "include_upgrade_expectation=True" in source
    assert 'row_label_prefix="库存"' in source
    assert '"来源行": _loadout_source_ref(row, current_count)' in source
    assert "_loadout_display_rows(rows, game, len(current_pieces))" in source
    assert '"副词条": _loadout_substat_label(row)' in source
    assert "GEAR_COLUMN_WIDTHS" in source
    assert "setStretchLastSection(False)" in source
    assert "QHeaderView.ResizeMode.Fixed" in source
    assert "QAbstractItemView.ScrollMode.ScrollPerPixel" in source
    assert "self.progress_bar.setMinimumHeight(30)" in source
    assert "QProgressBar::chunk" in source
    assert "self.progress_detail_label = QLabel" in source
    assert "_action_progress_percent" in source
    assert "max(self._action_progress_percent, raw_percent)" in source
    assert "计划已扩展，进度条保持不回退" in source
    assert "预计剩余约" in source
    assert "LEVEL_COMBO_MIN_WIDTH = 82" in source
    assert "level_combo.setMinimumWidth(LEVEL_COMBO_MIN_WIDTH)" in source
    assert "ROLL_SPINBOX_MIN_WIDTH = 72" in source
    assert "spin.setMinimumWidth(ROLL_SPINBOX_MIN_WIDTH)" in source


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
