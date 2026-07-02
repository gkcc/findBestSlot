from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from gear_optimizer.exporting import current_gear_export_data
from gear_optimizer.models import GearPiece
from gear_optimizer.paths import app_data_root
from gear_optimizer.presets import current_gear_data_to_pieces


def _safe_id(value: str) -> str:
    text = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in text.split("_") if part) or "current_gear"


def user_data_root() -> Path:
    return app_data_root()


def current_gear_store_path(game_id: str, character_id: str, root: Path | None = None) -> Path:
    base = root or user_data_root()
    return base / "current_gear" / game_id / f"{character_id}.yaml"


def _read_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return data


def load_user_current_gears(
    game_id: str,
    character_id: str,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    path = current_gear_store_path(game_id, character_id, root)
    data = _read_store(path)
    templates = data.get("templates", [])
    if not isinstance(templates, list):
        raise ValueError(f"templates must be a list in {path}")
    values = []
    for item in templates:
        if not isinstance(item, dict):
            raise ValueError(f"template item must be a mapping in {path}")
        values.append(
            {
                "id": str(item.get("id") or _safe_id(str(item.get("label") or "current_gear"))),
                "label": str(item.get("label") or item.get("id") or "未命名盘面"),
                "pieces": current_gear_data_to_pieces(item),
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
    saved_id = f"user_{_safe_id(saved_label)}"
    path = current_gear_store_path(game_id, character_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = [
        item
        for item in load_user_current_gears(game_id, character_id, root)
        if item["id"] != saved_id
    ]
    existing.append({"id": saved_id, "label": saved_label, "pieces": pieces})
    data = {
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
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    return {"id": saved_id, "label": saved_label, "pieces": pieces}


def delete_user_current_gear(
    game_id: str,
    character_id: str,
    template_id: str,
    root: Path | None = None,
) -> bool:
    path = current_gear_store_path(game_id, character_id, root)
    existing = load_user_current_gears(game_id, character_id, root)
    remaining = [item for item in existing if item["id"] != template_id]
    if len(remaining) == len(existing):
        return False
    if remaining:
        data = {
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
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    elif path.exists():
        path.unlink()
    return True
