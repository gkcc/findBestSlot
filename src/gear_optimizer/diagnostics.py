from __future__ import annotations

from collections.abc import Callable
import importlib.metadata
import importlib.util
from pathlib import Path
import sys
import tomllib

from gear_optimizer.game_rules import (
    PROJECT_ROOT,
    load_characters,
    load_games,
    load_probability_models,
)
from gear_optimizer.launcher import has_desktop_runtime
from gear_optimizer.presets import list_candidate_examples, list_current_examples

REQUIRED_PYTHON = (3, 11)
REQUIRED_RUNTIME_DEPENDENCIES = [
    ("streamlit", "streamlit", "local web UI server"),
    ("pydantic", "pydantic", "configuration models"),
    ("PyYAML", "yaml", "YAML configuration loading"),
    ("pandas", "pandas", "tables and report data frames"),
    ("plotly", "plotly", "charts"),
]
EXPECTED_CONSOLE_SCRIPTS = {
    "gacha-gear-optimizer": "gear_optimizer.launcher:streamlit_main",
    "gacha-gear-optimizer-desktop": "gear_optimizer.launcher:desktop_main",
    "gacha-gear-optimizer-doctor": "gear_optimizer.diagnostics:main",
    "gacha-gear-optimizer-acceptance": "gear_optimizer.acceptance:main",
    "gacha-gear-optimizer-verify-release": "gear_optimizer.release_manifest:main",
    "gacha-gear-optimizer-readiness": "gear_optimizer.readiness:main",
}
RELEASE_HELPER_MODULES = [
    "gear_optimizer.acceptance",
    "gear_optimizer.release_manifest",
    "gear_optimizer.readiness",
]


def _status(condition: bool) -> str:
    return "ok" if condition else "missing"


def _path_row(name: str, path: Path) -> dict[str, str]:
    return {
        "item": name,
        "status": _status(path.exists()),
        "detail": str(path),
    }


def _load_row(name: str, loader: Callable[[], object]) -> dict[str, str]:
    try:
        value = loader()
    except Exception as exc:
        return {"item": name, "status": "error", "detail": str(exc)}
    try:
        count = len(value)  # type: ignore[arg-type]
    except TypeError:
        count = 1 if value else 0
    return {"item": name, "status": "ok" if count else "empty", "detail": f"{count} loaded"}


def _python_version_row() -> dict[str, str]:
    version = sys.version_info
    required = ".".join(str(part) for part in REQUIRED_PYTHON)
    current = f"{version.major}.{version.minor}.{version.micro}"
    return {
        "item": "python version",
        "status": "ok" if version >= REQUIRED_PYTHON else "error",
        "detail": f"{current}; requires {required}+",
    }


def _dependency_row(package_name: str, module_name: str, purpose: str) -> dict[str, str]:
    if importlib.util.find_spec(module_name) is None:
        return {
            "item": f"dependency {package_name}",
            "status": "missing",
            "detail": f"{purpose}; install with: pip install -e .",
        }
    try:
        version = importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        version = "version unknown"
    return {
        "item": f"dependency {package_name}",
        "status": "ok",
        "detail": f"{version}; {purpose}",
    }


def _runtime_dependency_rows() -> list[dict[str, str]]:
    return [
        _python_version_row(),
        *[
            _dependency_row(package_name, module_name, purpose)
            for package_name, module_name, purpose in REQUIRED_RUNTIME_DEPENDENCIES
        ],
    ]


def _console_scripts_row() -> dict[str, str]:
    pyproject = PROJECT_ROOT / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        scripts = data.get("project", {}).get("scripts", {})
    except Exception as exc:
        return {
            "item": "console scripts",
            "status": "error",
            "detail": f"{pyproject}: {exc}",
        }
    if not isinstance(scripts, dict):
        return {
            "item": "console scripts",
            "status": "error",
            "detail": "[project.scripts] is missing or invalid",
        }

    missing = []
    wrong = []
    for name, expected in EXPECTED_CONSOLE_SCRIPTS.items():
        actual = scripts.get(name)
        if actual is None:
            missing.append(name)
        elif actual != expected:
            wrong.append(f"{name}={actual!r}")

    status = "ok" if not missing and not wrong else "missing"
    details = [f"{len(EXPECTED_CONSOLE_SCRIPTS) - len(missing) - len(wrong)} configured"]
    if missing:
        details.append(f"missing: {', '.join(missing)}")
    if wrong:
        details.append(f"wrong: {'; '.join(wrong)}")
    return {
        "item": "console scripts",
        "status": status,
        "detail": "; ".join(details),
    }


def _release_helper_modules_row() -> dict[str, str]:
    missing = [
        module_name
        for module_name in RELEASE_HELPER_MODULES
        if importlib.util.find_spec(module_name) is None
    ]
    return {
        "item": "release helper modules",
        "status": "ok" if not missing else "missing",
        "detail": (
            f"{len(RELEASE_HELPER_MODULES)} importable"
            if not missing
            else f"missing: {', '.join(missing)}"
        ),
    }


def _set_icon_asset_row(game) -> dict[str, str]:
    if not game.set_icons:
        return {
            "item": f"{game.id} set icon files",
            "status": "ok",
            "detail": "no set icons configured",
        }

    missing_config = sorted(set(game.sets) - set(game.set_icons))
    missing_files: list[str] = []
    empty_files: list[str] = []
    icon_paths = []
    for set_name, relative_path in game.set_icons.items():
        path = PROJECT_ROOT / relative_path
        icon_paths.append(path)
        if not path.exists():
            missing_files.append(f"{set_name}: {relative_path}")
        elif path.stat().st_size <= 0:
            empty_files.append(f"{set_name}: {relative_path}")

    status = "ok" if not missing_config and not missing_files and not empty_files else "missing"
    details = [
        f"{len(game.set_icons)} configured",
        f"{len(game.set_icons) - len(missing_files) - len(empty_files)} files ok",
    ]
    if missing_config:
        details.append(f"missing config for: {', '.join(missing_config)}")
    if missing_files:
        details.append(f"missing files: {'; '.join(missing_files)}")
    if empty_files:
        details.append(f"empty files: {'; '.join(empty_files)}")

    parent_counts: dict[Path, int] = {}
    for path in icon_paths:
        parent_counts[path.parent] = parent_counts.get(path.parent, 0) + 1
    if parent_counts:
        primary_parent = max(parent_counts, key=parent_counts.get)
        if primary_parent.exists():
            referenced_names = {path.name for path in icon_paths if path.parent == primary_parent}
            extra_files = sorted(
                path.name
                for path in primary_parent.glob("*.png")
                if path.name not in referenced_names
            )
            if extra_files:
                details.append(f"extra png files: {', '.join(extra_files)}")

    return {
        "item": f"{game.id} set icon files",
        "status": status,
        "detail": "; ".join(details),
    }


def _set_icon_rows() -> list[dict[str, str]]:
    try:
        games = load_games()
    except Exception as exc:
        return [{"item": "set icon files", "status": "error", "detail": str(exc)}]
    return [_set_icon_asset_row(game) for game in games]


def resource_check_rows() -> list[dict[str, str]]:
    rows = [
        *_runtime_dependency_rows(),
        _path_row("project root", PROJECT_ROOT),
        _path_row("app.py", PROJECT_ROOT / "app.py"),
        _path_row("desktop app entry", PROJECT_ROOT / "desktop_app.py"),
        _path_row("native PySide6 UI", PROJECT_ROOT / "src" / "gear_optimizer" / "pyside6_app.py"),
        _path_row("game configs", PROJECT_ROOT / "configs" / "games"),
        _path_row("character configs", PROJECT_ROOT / "configs" / "characters"),
        _path_row("probability configs", PROJECT_ROOT / "configs" / "probabilities"),
        _path_row("examples", PROJECT_ROOT / "examples"),
        _path_row("zzz drive disc icons", PROJECT_ROOT / "assets" / "zzz" / "drive_discs"),
        _console_scripts_row(),
        _release_helper_modules_row(),
        _path_row("start app script", PROJECT_ROOT / "scripts" / "start_app.ps1"),
        _path_row("start desktop script", PROJECT_ROOT / "scripts" / "start_desktop.ps1"),
        _path_row("acceptance report script", PROJECT_ROOT / "scripts" / "acceptance_report.ps1"),
        _path_row("Windows packaging script", PROJECT_ROOT / "scripts" / "build_windows_app.ps1"),
        _path_row("release gate script", PROJECT_ROOT / "scripts" / "release_gate.ps1"),
        _load_row("games", load_games),
        _load_row("characters", load_characters),
        _load_row("probability models", load_probability_models),
        _load_row("current gear examples", list_current_examples),
        _load_row("candidate examples", list_candidate_examples),
    ]
    rows.extend(_set_icon_rows())
    desktop_runtime_ok = has_desktop_runtime()
    rows.extend(
        [
            {
                "item": "PySide6 desktop runtime",
                "status": "ok" if desktop_runtime_ok else "notice",
                "detail": "native PySide6 runtime available"
                if desktop_runtime_ok
                else 'optional; install with: pip install -e ".[desktop]"',
            },
        ]
    )
    return rows


def has_resource_errors(rows: list[dict[str, str]]) -> bool:
    return any(row["status"] not in {"ok", "notice"} for row in rows)


def format_resource_check(rows: list[dict[str, str]]) -> str:
    width = max(len(row["item"]) for row in rows)
    return "\n".join(
        f"{row['item']:<{width}}  {row['status']:<7}  {row['detail']}"
        for row in rows
    )


def main() -> int:
    rows = resource_check_rows()
    print(format_resource_check(rows))
    return 1 if has_resource_errors(rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
