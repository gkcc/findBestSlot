from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib
import importlib.util
import json
from pathlib import Path
import sys

from gear_optimizer.project_paths import PROJECT_ROOT

PYSIDE6_APP_MODULE = "gear_optimizer.pyside6_app"
PYSIDE6_APP_PATH = PROJECT_ROOT / "src" / "gear_optimizer" / "pyside6_app.py"


@dataclass(frozen=True)
class DesktopRuntimeCheck:
    item: str
    status: str
    detail: str

    def as_row(self) -> dict[str, str]:
        return {"item": self.item, "status": self.status, "detail": self.detail}


def has_desktop_runtime() -> bool:
    return importlib.util.find_spec("PySide6") is not None


def desktop_support_rows() -> list[dict[str, str]]:
    pyside_ok = has_desktop_runtime()
    rows = [
        DesktopRuntimeCheck(
            "project root",
            "ok" if PROJECT_ROOT.exists() else "error",
            str(PROJECT_ROOT),
        ),
        DesktopRuntimeCheck(
            "desktop app entry",
            "ok" if (PROJECT_ROOT / "desktop_app.py").exists() else "error",
            str(PROJECT_ROOT / "desktop_app.py"),
        ),
        DesktopRuntimeCheck(
            "PySide6",
            "ok" if pyside_ok else "missing",
            "native desktop runtime"
            if pyside_ok
            else 'install with: pip install -e ".[desktop]"',
        ),
        DesktopRuntimeCheck(
            "native UI module",
            "ok" if PYSIDE6_APP_PATH.exists() else "error",
            str(PYSIDE6_APP_PATH),
        ),
    ]
    return [row.as_row() for row in rows]


def format_desktop_support(rows: list[dict[str, str]] | None = None) -> str:
    rows = rows if rows is not None else desktop_support_rows()
    width = max(len(row["item"]) for row in rows)
    return "\n".join(
        f"{row['item']:<{width}}  {row['status']:<7}  {row['detail']}"
        for row in rows
    )


def desktop_smoke_rows() -> list[dict[str, str]]:
    rows = desktop_support_rows()
    if not has_desktop_runtime():
        rows.append(
            {
                "item": "PySide6 app",
                "status": "missing",
                "detail": 'cannot instantiate native UI until PySide6 is installed',
            }
        )
        return rows
    try:
        pyside6_app = importlib.import_module(PYSIDE6_APP_MODULE)

        # Constructing the full QApplication is intentionally avoided here so
        # the check remains safe in headless CI. Importing the module catches
        # missing PySide6 bindings and syntax/import errors in the native UI layer.
        if not callable(getattr(pyside6_app, "main", None)):
            raise TypeError(f"{PYSIDE6_APP_MODULE}.main is not callable")
    except Exception as exc:
        rows.append({"item": "PySide6 app", "status": "error", "detail": str(exc)})
    else:
        rows.append({"item": "PySide6 app", "status": "ok", "detail": "native UI module importable"})
    return rows


def app_smoke_rows() -> list[dict[str, str]]:
    return desktop_smoke_rows()


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


def parse_desktop_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch gacha-gear-optimizer as a native PySide6 app.")
    parser.add_argument("--width", type=int, default=1500, help="Desktop window width.")
    parser.add_argument("--height", type=int, default=950, help="Desktop window height.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether the PySide6 desktop runtime is available.",
    )
    parser.add_argument(
        "--app-check",
        action="store_true",
        help="Check whether the native PySide6 app module can be imported.",
    )
    parser.add_argument(
        "--app-check-json",
        default="",
        help="Optional path to write machine-readable native app check rows.",
    )
    return parser.parse_args(argv)


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
    if not has_desktop_runtime():
        print(format_desktop_support())
        print("")
        print('PySide6 is required for the native desktop app. Install it with: pip install -e ".[desktop]"')
        return 2
    pyside6_app = importlib.import_module(PYSIDE6_APP_MODULE)

    return pyside6_app.main(["--width", str(args.width), "--height", str(args.height)])


def module_main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == "--desktop":
        return desktop_main(args[1:])
    return desktop_main(args)


if __name__ == "__main__":
    raise SystemExit(module_main())
