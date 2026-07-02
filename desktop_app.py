from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gear_optimizer import launcher
from gear_optimizer.launcher import (
    APP_PATH,
    PACKAGED_SERVER_ARG,
    app_smoke_checks_pass,
    app_smoke_rows,
    build_browser_app_command,
    build_streamlit_command,
    desktop_main,
    desktop_support_rows,
    find_free_port,
    format_app_smoke,
    format_desktop_support,
    has_browser_app_fallback,
    has_desktop_runtime,
    open_browser_app_window,
    open_desktop_window,
    parse_desktop_args,
    serve_streamlit_main,
    start_streamlit,
    stop_process,
    streamlit_url,
    wait_for_streamlit,
)


parse_args = parse_desktop_args


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == PACKAGED_SERVER_ARG:
        return launcher.module_main(args)
    return launcher.module_main(["--desktop", *args])


if __name__ == "__main__":
    raise SystemExit(main())
