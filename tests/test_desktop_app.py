import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import desktop_app
from gear_optimizer import launcher
from streamlit.web import bootstrap


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_url_uses_loopback():
    assert desktop_app.streamlit_url(8765) == "http://127.0.0.1:8765/"


def test_build_streamlit_command_uses_headless_loopback():
    command = desktop_app.build_streamlit_command(8765)

    assert command[:4] == [sys.executable, "-m", "streamlit", "run"]
    assert str(desktop_app.APP_PATH) in command
    assert "--server.address" in command
    assert "127.0.0.1" in command
    assert "--server.port" in command
    assert "8765" in command
    assert "--server.headless" in command
    assert "true" in command


def test_build_streamlit_command_uses_packaged_server_entry_when_frozen(monkeypatch):
    monkeypatch.setattr(launcher, "is_frozen_app", lambda: True)

    command = launcher.build_streamlit_command(8765)

    assert command == [sys.executable, "--serve-streamlit", "8765"]


def test_build_web_command_runs_repo_app():
    command = launcher.build_web_command(["--server.port", "8505"])

    assert command[:4] == [sys.executable, "-m", "streamlit", "run"]
    assert str(launcher.APP_PATH) in command
    assert "--server.address" in command
    assert "127.0.0.1" in command
    assert "--browser.gatherUsageStats" in command
    assert "false" in command
    assert command[-2:] == ["--server.port", "8505"]


def test_build_web_command_allows_later_cli_args_to_override_defaults():
    command = launcher.build_web_command(["--server.address", "0.0.0.0"])

    assert command.count("--server.address") == 2
    assert command[-2:] == ["--server.address", "0.0.0.0"]


def test_parse_args_defaults_to_free_port_marker():
    args = desktop_app.parse_args([])

    assert args.port == 0
    assert args.width >= 1100
    assert args.height >= 720
    assert not args.check
    assert not args.app_check
    assert args.app_check_json == ""
    assert not args.strict_runtime


def test_parse_args_supports_desktop_runtime_check():
    args = desktop_app.parse_args(["--check"])

    assert args.check


def test_parse_args_supports_app_smoke_check():
    args = desktop_app.parse_args(["--app-check"])

    assert args.app_check


def test_parse_args_supports_app_smoke_check_json():
    args = desktop_app.parse_args(["--app-check-json", "reports/source_app_smoke_checks.json"])

    assert args.app_check_json == "reports/source_app_smoke_checks.json"


def test_app_smoke_checks_pass_requires_all_rows_ok():
    assert launcher.app_smoke_checks_pass(
        [{"item": "streamlit app", "status": "ok", "detail": "rendered"}]
    )
    assert not launcher.app_smoke_checks_pass(
        [{"item": "streamlit app", "status": "error", "detail": "failed"}]
    )


def test_build_browser_app_command_uses_app_mode(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: f"C:/bin/{name}.exe" if name == "msedge" else None)
    monkeypatch.setattr(launcher, "app_data_root", lambda: Path("C:/data"))

    command = launcher.build_browser_app_command("http://127.0.0.1:8501/")
    normalized_command = [part.replace("\\", "/") for part in command]

    assert normalized_command == [
        "C:/bin/msedge.exe",
        "--app=http://127.0.0.1:8501/",
        "--new-window",
        "--user-data-dir=C:/data/browser_app_profile",
        "--no-first-run",
    ]


def test_streamlit_log_paths_use_app_data_logs(monkeypatch):
    monkeypatch.setattr(launcher, "app_data_root", lambda: Path("C:/data"))

    paths = launcher.streamlit_log_paths(8765)

    assert str(paths.stdout).replace("\\", "/") == "C:/data/logs/streamlit-8765.out.log"
    assert str(paths.stderr).replace("\\", "/") == "C:/data/logs/streamlit-8765.err.log"
    assert "streamlit-8765.out.log" in launcher.streamlit_log_path_text(8765)


def test_packaged_server_log_path_uses_app_data_logs(monkeypatch):
    monkeypatch.setattr(launcher, "app_data_root", lambda: Path("C:/data"))

    path = launcher.packaged_server_log_path(8765)

    assert str(path).replace("\\", "/") == "C:/data/logs/packaged-server-8765.log"


def test_append_packaged_server_log_writes_timestamped_lines(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "app_data_root", lambda: tmp_path)

    launcher.append_packaged_server_log(8765, "hello")

    text = (tmp_path / "logs" / "packaged-server-8765.log").read_text(encoding="utf-8")
    assert "hello" in text
    assert text.startswith("[")


def test_append_packaged_server_log_ignores_unwritable_log_dir(monkeypatch, tmp_path):
    blocked_file = tmp_path / "blocked"
    blocked_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        launcher,
        "packaged_server_log_path",
        lambda port: blocked_file / f"packaged-server-{port}.log",
    )

    launcher.append_packaged_server_log(8765, "hello")


def test_browser_app_candidates_include_windows_install_locations(monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", "C:/Program Files")
    monkeypatch.setenv("ProgramFiles(x86)", "C:/Program Files (x86)")
    monkeypatch.setenv("LocalAppData", "C:/Users/example/AppData/Local")

    candidates = launcher._browser_app_candidates()
    normalised = {candidate.replace("\\", "/") for candidate in candidates}

    assert "C:/Program Files/Microsoft/Edge/Application/msedge.exe" in normalised
    assert "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" in normalised
    assert "C:/Program Files/Google/Chrome/Application/chrome.exe" in normalised


def test_desktop_support_rows_report_runtime_status(monkeypatch):
    monkeypatch.setattr(
        launcher.importlib.util,
        "find_spec",
        lambda name: object() if name == "webview" else None,
    )

    rows = launcher.desktop_support_rows()
    formatted = launcher.format_desktop_support(rows)

    assert {"item": "pywebview", "status": "ok", "detail": "desktop window runtime"} in rows
    assert any(row["item"] == "browser app window" for row in rows)
    assert "pywebview" in formatted
    assert "ok" in formatted


def test_desktop_main_check_prints_status_without_starting_server(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "desktop_support_rows", lambda: [{"item": "pywebview", "status": "missing", "detail": "install"}])

    def fail_start(_port):
        raise AssertionError("desktop --check must not start Streamlit")

    monkeypatch.setattr(launcher, "start_streamlit", fail_start)

    assert launcher.desktop_main(["--check"]) == 0
    assert "pywebview" in capsys.readouterr().out


def test_desktop_main_app_check_prints_status_without_starting_server(monkeypatch, capsys):
    rows = [{"item": "streamlit app", "status": "ok", "detail": "rendered"}]

    def fail_start(_port):
        raise AssertionError("desktop --app-check must not start Streamlit server")

    monkeypatch.setattr(launcher, "app_smoke_rows", lambda: rows)
    monkeypatch.setattr(launcher, "start_streamlit", fail_start)

    assert launcher.desktop_main(["--app-check"]) == 0
    output = capsys.readouterr().out
    assert "streamlit app" in output
    assert "rendered" in output


def test_desktop_main_app_check_can_write_json(monkeypatch, tmp_path, capsys):
    rows = [{"item": "streamlit app", "status": "ok", "detail": "rendered"}]
    output = tmp_path / "source_app_smoke_checks.json"

    monkeypatch.setattr(launcher, "app_smoke_rows", lambda: rows)

    assert launcher.desktop_main(["--app-check-json", str(output)]) == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == rows
    assert "Wrote app smoke checks:" in capsys.readouterr().out


def test_desktop_main_app_check_returns_nonzero_for_app_errors(monkeypatch, capsys):
    rows = [{"item": "streamlit app", "status": "error", "detail": "failed"}]

    monkeypatch.setattr(launcher, "app_smoke_rows", lambda: rows)

    assert launcher.desktop_main(["--app-check"]) == 1
    assert "failed" in capsys.readouterr().out


def test_desktop_main_strict_missing_runtime_does_not_start_server(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "has_desktop_runtime", lambda: False)
    monkeypatch.setattr(
        launcher,
        "desktop_support_rows",
        lambda: [{"item": "pywebview", "status": "missing", "detail": 'install with: pip install -e ".[desktop]"'}],
    )

    def fail_start(_port):
        raise AssertionError("desktop launch without pywebview must not start Streamlit")

    monkeypatch.setattr(launcher, "start_streamlit", fail_start)

    assert launcher.desktop_main(["--port", "8765", "--strict-runtime"]) == 2
    output = capsys.readouterr().out
    assert 'pip install -e ".[desktop]"' in output
    assert "browser app window fallback" in output


def test_desktop_main_missing_runtime_uses_browser_app_fallback(monkeypatch, capsys):
    calls = []

    class FakeProcess:
        pass

    class FakeBrowserProcess:
        pass

    launch = launcher.BrowserAppLaunch("browser-app", FakeBrowserProcess())

    monkeypatch.setattr(launcher, "has_desktop_runtime", lambda: False)
    monkeypatch.setattr(launcher, "find_free_port", lambda: 8765)
    monkeypatch.setattr(launcher, "start_streamlit", lambda port: calls.append(("start", port)) or FakeProcess())
    monkeypatch.setattr(launcher, "wait_for_streamlit", lambda url: calls.append(("wait", url)))
    monkeypatch.setattr(launcher, "open_browser_app_window", lambda url: calls.append(("open", url)) or launch)
    monkeypatch.setattr(
        launcher,
        "wait_for_browser_app_exit",
        lambda url, app_launch: calls.append(("hold", url, app_launch.process.__class__.__name__)) or 0,
    )
    monkeypatch.setattr(launcher, "stop_process", lambda process: calls.append(("stop", process.__class__.__name__)))
    monkeypatch.setattr(
        launcher,
        "desktop_support_rows",
        lambda: [
            {"item": "pywebview", "status": "missing", "detail": "install"},
            {"item": "browser app window", "status": "ok", "detail": "available"},
        ],
    )

    assert launcher.desktop_main([]) == 0

    assert calls == [
        ("start", 8765),
        ("wait", "http://127.0.0.1:8765/"),
        ("open", "http://127.0.0.1:8765/"),
        ("hold", "http://127.0.0.1:8765/", "FakeBrowserProcess"),
        ("stop", "FakeProcess"),
    ]
    output = capsys.readouterr().out
    assert "browser app window fallback" in output
    assert "Opened an Edge/Chrome app-mode window." in output


def test_desktop_main_reports_streamlit_logs_when_server_fails(monkeypatch):
    calls = []

    class FakeProcess:
        pass

    monkeypatch.setattr(launcher, "find_free_port", lambda: 8765)
    monkeypatch.setattr(launcher, "start_streamlit", lambda port: calls.append(("start", port)) or FakeProcess())
    monkeypatch.setattr(
        launcher,
        "wait_for_streamlit",
        lambda url: (_ for _ in ()).throw(RuntimeError(f"failed at {url}")),
    )
    monkeypatch.setattr(launcher, "streamlit_log_path_text", lambda port: f"logs for {port}")
    monkeypatch.setattr(launcher, "stop_process", lambda process: calls.append(("stop", process.__class__.__name__)))

    try:
        launcher.desktop_main([])
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("desktop_main should raise when Streamlit fails to start")

    assert "failed at http://127.0.0.1:8765/" in message
    assert "Streamlit logs: logs for 8765" in message
    assert calls == [("start", 8765), ("stop", "FakeProcess")]


def test_wait_for_browser_app_exit_stops_when_browser_process_closes(capsys):
    calls = []

    class FakeBrowserProcess:
        def wait(self):
            calls.append("wait")
            return 0

    launch = launcher.BrowserAppLaunch("browser-app", FakeBrowserProcess())

    assert launcher.wait_for_browser_app_exit("http://127.0.0.1:8765/", launch) == 0
    assert calls == ["wait"]
    output = capsys.readouterr().out
    assert "Close the app window to stop the local service automatically." in output
    assert "App window closed. Stopping gacha-gear-optimizer." in output


def test_wait_for_browser_app_exit_tracks_profile_after_launcher_process_exits(monkeypatch, capsys):
    calls = []
    profile_states = iter([True, True, False])

    class FakeBrowserProcess:
        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return 0

    monkeypatch.setattr(launcher, "browser_app_profile_dir", lambda: Path("C:/data/browser_app_profile"))
    monkeypatch.setattr(
        launcher,
        "browser_app_profile_process_is_running",
        lambda profile_dir=None: calls.append(("profile", str(profile_dir))) or next(profile_states),
    )
    monkeypatch.setattr(launcher.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))

    launch = launcher.BrowserAppLaunch("browser-app", FakeBrowserProcess())

    assert launcher.wait_for_browser_app_exit("http://127.0.0.1:8765/", launch) == 0
    normalized_calls = [
        (kind, value.replace("\\", "/") if isinstance(value, str) else value)
        for kind, value in calls
    ]
    assert normalized_calls == [
        ("profile", "C:/data/browser_app_profile"),
        ("sleep", 1),
        ("profile", "C:/data/browser_app_profile"),
        ("sleep", 1),
        ("profile", "C:/data/browser_app_profile"),
    ]
    assert "App window closed. Stopping gacha-gear-optimizer." in capsys.readouterr().out


def test_module_main_defaults_to_web_launcher(monkeypatch):
    calls = []

    def fake_streamlit_main(args):
        calls.append(("web", args))
        return 0

    monkeypatch.setattr(launcher, "streamlit_main", fake_streamlit_main)

    assert launcher.module_main(["--server.port", "8506"]) == 0
    assert calls == [("web", ["--server.port", "8506"])]


def test_module_main_can_dispatch_to_desktop(monkeypatch):
    calls = []

    def fake_desktop_main(args):
        calls.append(("desktop", args))
        return 0

    monkeypatch.setattr(launcher, "desktop_main", fake_desktop_main)

    assert launcher.module_main(["--desktop", "--width", "1400"]) == 0
    assert calls == [("desktop", ["--width", "1400"])]


def test_module_main_can_dispatch_to_packaged_streamlit_server(monkeypatch):
    calls = []

    def fake_serve(args):
        calls.append(args)
        return 0

    monkeypatch.setattr(launcher, "serve_streamlit_main", fake_serve)

    assert launcher.module_main(["--serve-streamlit", "8765"]) == 0
    assert calls == [["8765"]]


def test_serve_streamlit_main_loads_config_options_before_bootstrap_run(monkeypatch):
    calls = []

    def fake_load_config_options(flag_options):
        calls.append(("load", flag_options.copy()))

    def fake_run(main_script_path, is_hello, args, flag_options):
        calls.append(("run", main_script_path, is_hello, args, flag_options.copy()))

    monkeypatch.setattr(launcher, "append_packaged_server_log", lambda port, message: None)
    monkeypatch.setattr(bootstrap, "load_config_options", fake_load_config_options)
    monkeypatch.setattr(bootstrap, "run", fake_run)

    assert launcher.serve_streamlit_main(["8765"]) == 0

    assert calls[0] == (
        "load",
        {
            "global.developmentMode": False,
            "server.address": "127.0.0.1",
            "server.port": 8765,
            "server.headless": True,
            "browser.gatherUsageStats": False,
        },
    )
    assert calls[1][0] == "run"
    assert calls[1][1] == str(launcher.APP_PATH)
    assert calls[1][4]["server.port"] == 8765


def test_desktop_app_main_wraps_desktop_args(monkeypatch):
    calls = []

    def fake_module_main(args):
        calls.append(args)
        return 0

    monkeypatch.setattr(desktop_app.launcher, "module_main", fake_module_main)

    assert desktop_app.main(["--width", "1400"]) == 0
    assert calls == [["--desktop", "--width", "1400"]]


def test_desktop_app_main_passes_packaged_server_args(monkeypatch):
    calls = []

    def fake_module_main(args):
        calls.append(args)
        return 0

    monkeypatch.setattr(desktop_app.launcher, "module_main", fake_module_main)

    assert desktop_app.main(["--serve-streamlit", "8765"]) == 0
    assert calls == [["--serve-streamlit", "8765"]]


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
    assert "app.py" in result.stdout


def test_pyproject_declares_app_console_scripts():
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    pytest_options = data["tool"]["pytest"]["ini_options"]

    assert scripts["gacha-gear-optimizer"] == "gear_optimizer.launcher:streamlit_main"
    assert scripts["gacha-gear-optimizer-desktop"] == "gear_optimizer.launcher:desktop_main"
    assert scripts["gacha-gear-optimizer-doctor"] == "gear_optimizer.diagnostics:main"
    assert scripts["gacha-gear-optimizer-acceptance"] == "gear_optimizer.acceptance:main"
    assert (
        scripts["gacha-gear-optimizer-verify-release"]
        == "gear_optimizer.release_manifest:main"
    )
    assert scripts["gacha-gear-optimizer-readiness"] == "gear_optimizer.readiness:main"
    assert "packaging" in data["project"]["optional-dependencies"]
    assert any(
        dependency.startswith("pyinstaller")
        for dependency in data["project"]["optional-dependencies"]["packaging"]
    )
    assert pytest_options["addopts"] == "-m 'not streamlit_ui'"
    assert any("streamlit_ui:" in marker for marker in pytest_options["markers"])


def test_windows_packaging_scripts_exist_and_bundle_resources():
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
    assert "--collect-data" in script
    assert "--collect-all" in script
    assert '"numpy"' in script
    assert '"--collect-all", "numpy"' in script
    assert '"pandas"' in script
    assert '"--collect-data", "pandas"' in script
    assert '"--collect-all", "pandas"' not in script
    assert '"plotly"' in script
    assert "$Root\\desktop_app.py" in script
