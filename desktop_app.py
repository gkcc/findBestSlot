from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gear_optimizer import launcher
from gear_optimizer.launcher import (
    app_smoke_checks_pass,
    app_smoke_rows,
    desktop_main,
    desktop_smoke_rows,
    desktop_support_rows,
    format_app_smoke,
    format_desktop_support,
    has_desktop_runtime,
    parse_desktop_args,
)


parse_args = parse_desktop_args


def main(argv: list[str] | None = None) -> int:
    return launcher.module_main(["--desktop", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    raise SystemExit(main())
