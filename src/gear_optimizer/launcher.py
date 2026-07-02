from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import importlib.util
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
import webbrowser

from gear_optimizer.game_rules import PROJECT_ROOT
from gear_optimizer.paths import app_data_root, is_frozen_app

APP_PATH = PROJECT_ROOT / "app.py"
PACKAGED_SERVER_ARG = "--serve-streamlit"
BROWSER_APP_PROFILE_DIRNAME = "browser_app_profile"
STREAMLIT_LOG_DIRNAME = "logs"
WEB_DEFAULT_STREAMLIT_ARGS = [
    "--server.address",
    "127.0.0.1",
    "--browser.gatherUsageStats",
    "false",
]


@dataclass(frozen=True)
class BrowserAppLaunch:
    mode: str
    process: subprocess.Popen | None = None


@dataclass(frozen=True)
class StreamlitLogPaths:
    stdout: Path
    stderr: Path


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def streamlit_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def build_streamlit_command(port: int) -> list[str]:
    if is_frozen_app():
        return [sys.executable, PACKAGED_SERVER_ARG, str(port)]
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_PATH),
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]


def build_web_command(args: list[str] | None = None) -> list[str]:
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_PATH),
        *WEB_DEFAULT_STREAMLIT_ARGS,
        *(args or []),
    ]


def wait_for_streamlit(url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if 200 <= response.status < 500:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"Streamlit did not start at {url}: {last_error}")


def streamlit_log_paths(port: int) -> StreamlitLogPaths:
    log_dir = app_data_root() / STREAMLIT_LOG_DIRNAME
    return StreamlitLogPaths(
        stdout=log_dir / f"streamlit-{port}.out.log",
        stderr=log_dir / f"streamlit-{port}.err.log",
    )


def streamlit_log_path_text(port: int) -> str:
    paths = streamlit_log_paths(port)
    return f"stdout: {paths.stdout}; stderr: {paths.stderr}"


def packaged_server_log_path(port: int) -> Path:
    return app_data_root() / STREAMLIT_LOG_DIRNAME / f"packaged-server-{port}.log"


def append_packaged_server_log(port: int, message: str) -> None:
    try:
        path = packaged_server_log_path(port)
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")
    except OSError:
        return


def start_streamlit(port: int) -> subprocess.Popen:
    paths = streamlit_log_paths(port)
    paths.stdout.parent.mkdir(parents=True, exist_ok=True)
    with paths.stdout.open("ab") as stdout, paths.stderr.open("ab") as stderr:
        return subprocess.Popen(
            build_streamlit_command(port),
            cwd=PROJECT_ROOT,
            stdout=stdout,
            stderr=stderr,
        )


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def has_desktop_runtime() -> bool:
    return importlib.util.find_spec("webview") is not None


def _browser_app_candidates() -> list[str]:
    candidates = ["msedge", "chrome", "google-chrome", "chromium", "chromium-browser"]
    if sys.platform.startswith("win"):
        program_files = [
            value
            for value in [
                os.environ.get("ProgramFiles"),
                os.environ.get("ProgramFiles(x86)"),
                os.environ.get("LocalAppData"),
            ]
            if value
        ]
        candidates.extend(
            [
                str(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
                for root in program_files
            ]
        )
        candidates.extend(
            [
                str(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
                for root in program_files
            ]
        )
    return candidates


def build_browser_app_command(url: str) -> list[str] | None:
    for candidate in _browser_app_candidates():
        executable = shutil.which(candidate)
        if executable is None and Path(candidate).exists():
            executable = candidate
        if executable:
            return [
                executable,
                f"--app={url}",
                "--new-window",
                f"--user-data-dir={browser_app_profile_dir()}",
                "--no-first-run",
            ]
    return None


def browser_app_profile_dir() -> Path:
    return app_data_root() / BROWSER_APP_PROFILE_DIRNAME


def browser_app_profile_process_is_running(profile_dir: Path | None = None) -> bool:
    profile_text = str(profile_dir or browser_app_profile_dir())
    if sys.platform.startswith("win"):
        script = (
            "$profile = $env:GEAR_OPTIMIZER_BROWSER_PROFILE; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profile) } | "
            "Select-Object -First 1 -ExpandProperty ProcessId"
        )
        env = os.environ.copy()
        env["GEAR_OPTIMIZER_BROWSER_PROFILE"] = profile_text
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                env=env,
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and bool(result.stdout.strip())

    try:
        result = subprocess.run(
            ["ps", "-axo", "command="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return profile_text in result.stdout


def has_browser_app_fallback() -> bool:
    return build_browser_app_command("http://127.0.0.1:0/") is not None


def desktop_support_rows() -> list[dict[str, str]]:
    webview_ok = has_desktop_runtime()
    browser_app_ok = has_browser_app_fallback()
    return [
        {
            "item": "project root",
            "status": "ok" if PROJECT_ROOT.exists() else "error",
            "detail": str(PROJECT_ROOT),
        },
        {
            "item": "app.py",
            "status": "ok" if APP_PATH.exists() else "error",
            "detail": str(APP_PATH),
        },
        {
            "item": "pywebview",
            "status": "ok" if webview_ok else "missing",
            "detail": "desktop window runtime"
            if webview_ok
            else 'install with: pip install -e ".[desktop]"',
        },
        {
            "item": "browser app window",
            "status": "ok" if browser_app_ok else "fallback",
            "detail": "Edge/Chrome --app window available"
            if browser_app_ok
            else "will open the default browser if no app-mode browser is found",
        },
    ]


def format_desktop_support(rows: list[dict[str, str]] | None = None) -> str:
    rows = rows if rows is not None else desktop_support_rows()
    width = max(len(row["item"]) for row in rows)
    return "\n".join(
        f"{row['item']:<{width}}  {row['status']:<7}  {row['detail']}"
        for row in rows
    )


def app_smoke_rows(timeout_seconds: float = 30.0) -> list[dict[str, str]]:
    rows = [
        {
            "item": "project root",
            "status": "ok" if PROJECT_ROOT.exists() else "error",
            "detail": str(PROJECT_ROOT),
        },
        {
            "item": "app.py",
            "status": "ok" if APP_PATH.exists() else "error",
            "detail": str(APP_PATH),
        },
    ]
    if not APP_PATH.exists():
        return rows

    previous_logging_disable_level = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(APP_PATH))
        app.run(timeout=timeout_seconds)
    except Exception as exc:
        rows.append({"item": "streamlit app", "status": "error", "detail": str(exc)})
        return rows
    finally:
        logging.disable(previous_logging_disable_level)

    exceptions = list(app.exception)
    rows.append(
        {
            "item": "streamlit app",
            "status": "ok" if not exceptions else "error",
            "detail": (
                "rendered without exceptions"
                if not exceptions
                else f"{len(exceptions)} Streamlit exception(s)"
            ),
        }
    )
    return rows


def app_smoke_checks_pass(rows: list[dict[str, str]]) -> bool:
    return all(row["status"] == "ok" for row in rows)


def format_app_smoke(rows: list[dict[str, str]] | None = None) -> str:
    rows = rows if rows is not None else app_smoke_rows()
    width = max(len(row["item"]) for row in rows)
    return "\n".join(
        f"{row['item']:<{width}}  {row['status']:<7}  {row['detail']}"
        for row in rows
    )


def write_app_smoke_json(path: str | Path, rows: list[dict[str, str]]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def open_desktop_window(url: str, title: str, width: int, height: int) -> int:
    try:
        import webview
    except ImportError:
        print(
            "pywebview is not installed. Install desktop support with: "
            'pip install -e ".[desktop]"'
        )
        return 2

    webview.create_window(title, url, width=width, height=height, min_size=(1100, 720))
    webview.start()
    return 0


def open_browser_app_window(url: str) -> BrowserAppLaunch:
    command = build_browser_app_command(url)
    if command:
        browser_app_profile_dir().mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(command, cwd=PROJECT_ROOT)
        return BrowserAppLaunch("browser-app", process)
    webbrowser.open(url)
    return BrowserAppLaunch("browser")


def wait_for_browser_app_exit(url: str, launch: BrowserAppLaunch | str) -> int:
    print(f"Local app is running at {url}")
    if isinstance(launch, str):
        launch = BrowserAppLaunch(launch)
    if launch.mode == "browser-app" and launch.process is not None:
        print("Close the app window to stop the local service automatically.")
        profile_dir = browser_app_profile_dir()
        profile_grace_deadline = time.monotonic() + 5
        saw_profile_process = False
        try:
            while True:
                if browser_app_profile_process_is_running(profile_dir):
                    saw_profile_process = True
                    time.sleep(1)
                    continue

                if saw_profile_process:
                    break

                try:
                    launch.process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    continue
                except TypeError:
                    launch.process.wait()
                    break

                if time.monotonic() >= profile_grace_deadline:
                    break
                time.sleep(0.25)
        except KeyboardInterrupt:
            print("Stopping gacha-gear-optimizer.")
            return 0
        print("App window closed. Stopping gacha-gear-optimizer.")
        return 0

    print("Close the browser window when done, then press Ctrl+C here to stop the service.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("Stopping gacha-gear-optimizer.")
        return 0


def parse_desktop_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch gacha-gear-optimizer as a desktop window.")
    parser.add_argument("--port", type=int, default=0, help="Local Streamlit port. 0 picks a free port.")
    parser.add_argument("--width", type=int, default=1500, help="Desktop window width.")
    parser.add_argument("--height", type=int, default=950, help="Desktop window height.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether the desktop window runtime is available.",
    )
    parser.add_argument(
        "--app-check",
        action="store_true",
        help="Run the Streamlit app once and fail if the page raises an exception.",
    )
    parser.add_argument(
        "--app-check-json",
        default="",
        help="Optional path to write machine-readable Streamlit app check rows.",
    )
    parser.add_argument(
        "--strict-runtime",
        action="store_true",
        help="Fail instead of using the browser app fallback when pywebview is missing.",
    )
    return parser.parse_args(argv)


def serve_streamlit_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=argparse.SUPPRESS)
    parser.add_argument("port", type=int)
    args = parser.parse_args(argv)

    try:
        append_packaged_server_log(args.port, f"starting packaged Streamlit server for {APP_PATH}")
        from streamlit.web import bootstrap

        append_packaged_server_log(args.port, "imported streamlit.web.bootstrap")
        flag_options = {
            "global.developmentMode": False,
            "server.address": "127.0.0.1",
            "server.port": args.port,
            "server.headless": True,
            "browser.gatherUsageStats": False,
        }
        bootstrap.load_config_options(flag_options)
        append_packaged_server_log(args.port, "loaded Streamlit config options")
        append_packaged_server_log(args.port, f"calling bootstrap.run with {flag_options}")
        bootstrap.run(str(APP_PATH), False, [], flag_options)
        append_packaged_server_log(args.port, "bootstrap.run returned")
        return 0
    except Exception:
        append_packaged_server_log(args.port, traceback.format_exc())
        raise


def streamlit_main(argv: list[str] | None = None) -> int:
    return subprocess.call(build_web_command(argv), cwd=PROJECT_ROOT)


def desktop_main(argv: list[str] | None = None) -> int:
    args = parse_desktop_args(argv)
    if args.check:
        print(format_desktop_support())
        return 0
    if args.app_check or args.app_check_json:
        rows = app_smoke_rows()
        print(format_app_smoke(rows))
        if args.app_check_json:
            write_app_smoke_json(args.app_check_json, rows)
            print(f"Wrote app smoke checks: {args.app_check_json}")
        return 0 if app_smoke_checks_pass(rows) else 1
    if args.strict_runtime and not has_desktop_runtime():
        print(format_desktop_support())
        print("")
        print('Desktop runtime is missing. Install it with: pip install -e ".[desktop]"')
        print("Or run without --strict-runtime to use the browser app window fallback.")
        return 2
    port = args.port or find_free_port()
    url = streamlit_url(port)
    process = start_streamlit(port)
    try:
        try:
            wait_for_streamlit(url)
        except RuntimeError as exc:
            raise RuntimeError(
                f"{exc}\nStreamlit logs: {streamlit_log_path_text(port)}"
            ) from exc
        if not has_desktop_runtime():
            print(format_desktop_support())
            print("")
            print("pywebview is missing, so using the browser app window fallback.")
            launch = open_browser_app_window(url)
            if launch.mode == "browser-app":
                print("Opened an Edge/Chrome app-mode window.")
            else:
                print("Opened the default browser.")
            return wait_for_browser_app_exit(url, launch)
        return open_desktop_window(
            url,
            "gacha-gear-optimizer",
            width=args.width,
            height=args.height,
        )
    finally:
        stop_process(process)


def module_main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == PACKAGED_SERVER_ARG:
        return serve_streamlit_main(args[1:])
    if args and args[0] == "--desktop":
        return desktop_main(args[1:])
    return streamlit_main(args)


if __name__ == "__main__":
    raise SystemExit(module_main())
