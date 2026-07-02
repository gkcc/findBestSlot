from __future__ import annotations

from pathlib import Path

import yaml

from gear_optimizer.exporting import current_gear_export_data
from gear_optimizer.models import GearPiece
from gear_optimizer.paths import app_data_root
from gear_optimizer.presets import current_gear_data_to_pieces


def user_inventory_store_path(
    game_id: str,
    character_id: str,
    root: Path | None = None,
) -> Path:
    base = root or app_data_root()
    return base / "inventory" / game_id / f"{character_id}.yaml"


def load_user_inventory(
    game_id: str,
    character_id: str,
    root: Path | None = None,
) -> list[GearPiece]:
    path = user_inventory_store_path(game_id, character_id, root)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return current_gear_data_to_pieces(data)


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
        character_id,
        pieces,
        label=f"{character_id} inventory",
    )
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    return path
