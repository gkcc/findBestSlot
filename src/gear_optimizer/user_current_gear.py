from __future__ import annotations

from pathlib import Path
from typing import Any

from gear_optimizer.exporting import current_gear_export_data
from gear_optimizer.models import GearPiece
from gear_optimizer.paths import app_data_root
from gear_optimizer.presets import current_gear_data_to_pieces
from gear_optimizer.storage_io import (
    USER_STORE_SCHEMA_VERSION,
    read_yaml_mapping,
    safe_storage_id,
    update_yaml_mapping_locked,
    validate_store_schema_version,
)


def current_gear_store_path(game_id: str, character_id: str, root: Path | None = None) -> Path:
    base = root or app_data_root()
    return base / "current_gear" / game_id / f"{character_id}.yaml"


def load_user_current_gears(
    game_id: str,
    character_id: str,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    path = current_gear_store_path(game_id, character_id, root)
    data = read_yaml_mapping(path)
    validate_store_schema_version(data, path)
    return _current_gear_rows(data, game_id, path)


def _current_gear_rows(
    data: dict[str, Any],
    game_id: str,
    path: Path,
) -> list[dict[str, Any]]:
    templates = data.get("templates", [])
    if not isinstance(templates, list):
        raise ValueError(f"templates must be a list in {path}")
    values = []
    for item in templates:
        if not isinstance(item, dict):
            raise ValueError(f"template item must be a mapping in {path}")
        values.append(
            {
                "id": str(
                    item.get("id")
                    or safe_storage_id(
                        str(item.get("label") or "current_gear"),
                        fallback="current_gear",
                    )
                ),
                "label": str(item.get("label") or item.get("id") or "未命名盘面"),
                "pieces": current_gear_data_to_pieces(item, game_id=game_id),
            }
        )
    return values


def save_user_current_gear(
    game_id: str,
    character_id: str,
    pieces: list[GearPiece],
    label: str,
    root: Path | None = None,
) -> dict[str, Any]:
    saved_label = label.strip() or "未命名盘面"
    saved_id = f"user_{safe_storage_id(saved_label, fallback='current_gear')}"
    path = current_gear_store_path(game_id, character_id, root)

    def update(data: dict[str, Any]) -> dict[str, Any]:
        validate_store_schema_version(data, path)
        existing = [
            item
            for item in _current_gear_rows(data, game_id, path)
            if item["id"] != saved_id
        ]
        existing.append({"id": saved_id, "label": saved_label, "pieces": pieces})
        return {
            "schema_version": USER_STORE_SCHEMA_VERSION,
            "game": game_id,
            "character": character_id,
            "templates": [
                {
                    "id": item["id"],
                    **current_gear_export_data(
                        game_id,
                        character_id,
                        item["pieces"],
                        label=item["label"],
                    ),
                }
                for item in existing
            ],
        }

    update_yaml_mapping_locked(path, update, backup_existing=True)
    return {"id": saved_id, "label": saved_label, "pieces": pieces}


def delete_user_current_gear(
    game_id: str,
    character_id: str,
    template_id: str,
    root: Path | None = None,
) -> bool:
    path = current_gear_store_path(game_id, character_id, root)
    deleted = False

    def update(data: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal deleted
        validate_store_schema_version(data, path)
        existing = _current_gear_rows(data, game_id, path)
        remaining = [item for item in existing if item["id"] != template_id]
        if len(remaining) == len(existing):
            return data
        deleted = True
        if not remaining:
            return None
        return {
            "schema_version": USER_STORE_SCHEMA_VERSION,
            "game": game_id,
            "character": character_id,
            "templates": [
                {
                    "id": item["id"],
                    **current_gear_export_data(
                        game_id,
                        character_id,
                        item["pieces"],
                        label=item["label"],
                    ),
                }
                for item in remaining
            ],
        }

    update_yaml_mapping_locked(path, update, backup_existing=True)
    return deleted
