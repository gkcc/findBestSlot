from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

from gear_optimizer.game_rules import PROJECT_ROOT
from gear_optimizer.models import GameRules

_PIXMAP_CACHE: dict[tuple[str, int], QPixmap | None] = {}
_ICON_CACHE: dict[tuple[str, int], QIcon | None] = {}


def _asset_path(relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    path = Path(relative_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def set_icon_pixmap(game: GameRules, set_name: str, size: int = 32) -> QPixmap | None:
    relative_path = game.set_icon_path(set_name)
    path = _asset_path(relative_path)
    cache_key = (str(path) if path else "", size)
    if cache_key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[cache_key]
    if path is None or not path.exists():
        _PIXMAP_CACHE[cache_key] = None
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        _PIXMAP_CACHE[cache_key] = None
        return None
    scaled = pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    _PIXMAP_CACHE[cache_key] = scaled
    return scaled


def set_icon(game: GameRules, set_name: str, size: int = 32) -> QIcon | None:
    relative_path = game.set_icon_path(set_name)
    path = _asset_path(relative_path)
    cache_key = (str(path) if path else "", size)
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]
    pixmap = set_icon_pixmap(game, set_name, size)
    if pixmap is None:
        _ICON_CACHE[cache_key] = None
        return None
    icon = QIcon(pixmap)
    _ICON_CACHE[cache_key] = icon
    return icon


def set_effect_tooltip(game: GameRules, set_name: str) -> str:
    effect = game.set_effect(set_name)
    if effect is None:
        return set_name
    parts = [set_name]
    if effect.two_piece:
        parts.append(f"2件套：{effect.two_piece}")
    if effect.four_piece:
        parts.append(f"4件套：{effect.four_piece}")
    return "\n".join(parts)
