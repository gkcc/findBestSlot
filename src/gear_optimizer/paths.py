from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

from gear_optimizer.project_paths import PROJECT_ROOT

APP_DIR_NAME = "gacha-gear-optimizer"


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def _temp_app_data_root() -> Path:
    return Path(tempfile.gettempdir()) / APP_DIR_NAME / "user_data"


def _ensure_or_fallback(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        fallback = _temp_app_data_root()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def app_data_root() -> Path:
    override = os.environ.get("GEAR_OPTIMIZER_USER_DATA_DIR") or os.environ.get(
        "GEAR_OPTIMIZER_USER_DATA"
    )
    if override:
        return Path(override).expanduser().resolve()

    if not is_frozen_app():
        return PROJECT_ROOT / "user_data"

    if sys.platform.startswith("win"):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return _ensure_or_fallback(Path(local_app_data) / APP_DIR_NAME / "user_data")

    if sys.platform == "darwin":
        return _ensure_or_fallback(
            Path.home() / "Library" / "Application Support" / APP_DIR_NAME / "user_data"
        )

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return _ensure_or_fallback(Path(xdg_data_home) / APP_DIR_NAME / "user_data")
    return _ensure_or_fallback(Path.home() / f".{APP_DIR_NAME}" / "user_data")
