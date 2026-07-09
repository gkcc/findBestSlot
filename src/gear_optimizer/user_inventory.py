from __future__ import annotations

from pathlib import Path

import yaml

from gear_optimizer.exporting import current_gear_export_data
from gear_optimizer.models import GearPiece
from gear_optimizer.paths import app_data_root
from gear_optimizer.presets import current_gear_data_to_pieces

SHARED_INVENTORY_ID = "_shared"
LEGACY_GLOBAL_INVENTORY_ID = "global"


def user_inventory_store_path(
    game_id: str,
    character_id: str = SHARED_INVENTORY_ID,
    root: Path | None = None,
) -> Path:
    base = root or app_data_root()
    return base / "inventory" / game_id / f"{SHARED_INVENTORY_ID}.yaml"


def legacy_user_inventory_store_path(
    game_id: str,
    character_id: str,
    root: Path | None = None,
) -> Path:
    base = root or app_data_root()
    return base / "inventory" / game_id / f"{character_id}.yaml"


def legacy_user_inventory_store_paths(
    game_id: str,
    root: Path | None = None,
) -> list[Path]:
    base = root or app_data_root()
    folder = base / "inventory" / game_id
    if not folder.exists():
        return []
    ignored = {SHARED_INVENTORY_ID, LEGACY_GLOBAL_INVENTORY_ID}
    return sorted(path for path in folder.glob("*.yaml") if path.stem not in ignored)


def _load_inventory_file(path: Path, game_id: str) -> list[GearPiece]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return current_gear_data_to_pieces(data, game_id=game_id)


def _ordered_legacy_inventory_paths(
    game_id: str,
    character_id: str,
    root: Path | None = None,
) -> list[Path]:
    preferred = legacy_user_inventory_store_path(game_id, character_id, root) if character_id else None
    paths = legacy_user_inventory_store_paths(game_id, root)
    if preferred is None or preferred not in paths:
        return paths
    return [preferred, *(path for path in paths if path != preferred)]


def load_legacy_user_inventory(
    game_id: str,
    character_id: str,
    root: Path | None = None,
) -> list[GearPiece]:
    path = legacy_user_inventory_store_path(game_id, character_id, root)
    if not path.exists():
        return []
    return _load_inventory_file(path, game_id)


def load_user_inventory(
    game_id: str,
    character_id: str = SHARED_INVENTORY_ID,
    root: Path | None = None,
) -> list[GearPiece]:
    path = user_inventory_store_path(game_id, character_id, root)
    if path.exists():
        return _load_inventory_file(path, game_id)
    pieces: list[GearPiece] = []
    for legacy_path in _ordered_legacy_inventory_paths(game_id, character_id, root):
        pieces.extend(_load_inventory_file(legacy_path, game_id))
    return pieces


def load_user_inventory_with_source(
    game_id: str,
    character_id: str = SHARED_INVENTORY_ID,
    root: Path | None = None,
) -> tuple[list[GearPiece], str]:
    path = user_inventory_store_path(game_id, character_id, root)
    if path.exists():
        return _load_inventory_file(path, game_id), SHARED_INVENTORY_ID
    legacy_paths = _ordered_legacy_inventory_paths(game_id, character_id, root)
    pieces: list[GearPiece] = []
    for legacy_path in legacy_paths:
        pieces.extend(_load_inventory_file(legacy_path, game_id))
    if legacy_paths:
        return pieces, "legacy_merged"
    return [], SHARED_INVENTORY_ID


def save_user_inventory(
    game_id: str,
    character_id: str,
    pieces: list[GearPiece],
    root: Path | None = None,
) -> Path:
    path = user_inventory_store_path(game_id, character_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = current_gear_export_data(
        game_id,
        SHARED_INVENTORY_ID,
        pieces,
        label=f"{game_id} shared inventory",
    )
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    return path


def save_legacy_user_inventory(
    game_id: str,
    character_id: str,
    pieces: list[GearPiece],
    root: Path | None = None,
) -> Path:
    path = legacy_user_inventory_store_path(game_id, character_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = current_gear_export_data(
        game_id,
        character_id,
        pieces,
        label=f"{character_id} inventory",
    )
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    return path
