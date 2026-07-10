from __future__ import annotations

import os
from pathlib import Path
import sys


def _looks_like_project_root(path: Path) -> bool:
    return (
        (path / "pyproject.toml").exists()
        and (path / "desktop_app.py").exists()
        and (path / "configs" / "games").exists()
        and (path / "examples").exists()
    )


def project_root() -> Path:
    override = os.environ.get("GEAR_OPTIMIZER_PROJECT_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    package_source_root = Path(__file__).resolve().parents[2]
    bundle_root = getattr(sys, "_MEIPASS", None)
    candidates: list[Path] = []
    if bundle_root:
        candidates.append(Path(bundle_root).resolve())
    candidates.extend([Path.cwd().resolve(), package_source_root])
    candidates.extend(Path.cwd().resolve().parents)

    for candidate in candidates:
        if _looks_like_project_root(candidate):
            return candidate
    return package_source_root


PROJECT_ROOT = project_root()
