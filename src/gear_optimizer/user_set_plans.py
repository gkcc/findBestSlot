from __future__ import annotations

from pathlib import Path
from typing import Any

from gear_optimizer.models import SetPlan
from gear_optimizer.paths import app_data_root
from gear_optimizer.storage_io import (
    USER_STORE_SCHEMA_VERSION,
    read_yaml_mapping,
    safe_storage_id,
    update_yaml_mapping_locked,
    validate_store_schema_version,
)


def set_plan_store_path(game_id: str, character_id: str, root: Path | None = None) -> Path:
    base = root or app_data_root()
    return base / "set_plans" / game_id / f"{character_id}.yaml"


def load_user_set_plans(
    game_id: str,
    character_id: str,
    root: Path | None = None,
) -> list[SetPlan]:
    path = set_plan_store_path(game_id, character_id, root)
    data = read_yaml_mapping(path)
    validate_store_schema_version(data, path)
    return _set_plans_from_data(data, path)


def _set_plans_from_data(data: dict[str, Any], path: Path) -> list[SetPlan]:
    plans = data.get("set_plans", [])
    if not isinstance(plans, list):
        raise ValueError(f"set_plans must be a list in {path}")
    return [SetPlan.model_validate(plan) for plan in plans]


def save_user_set_plan(
    game_id: str,
    character_id: str,
    plan: SetPlan,
    name: str | None = None,
    root: Path | None = None,
) -> SetPlan:
    saved_name = (name or plan.name).strip() or plan.name
    saved_id = (
        plan.id
        if plan.id.startswith("user_")
        else f"user_{safe_storage_id(saved_name, fallback='set_plan')}"
    )
    saved_plan = plan.model_copy(update={"id": saved_id, "name": saved_name})
    path = set_plan_store_path(game_id, character_id, root)

    def update(data: dict[str, Any]) -> dict[str, Any]:
        validate_store_schema_version(data, path)
        existing = [
            item
            for item in _set_plans_from_data(data, path)
            if item.id != saved_plan.id
        ]
        existing.append(saved_plan)
        return {
            "schema_version": USER_STORE_SCHEMA_VERSION,
            "game": game_id,
            "character": character_id,
            "set_plans": [
                item.model_dump(mode="json", exclude_none=True)
                for item in existing
            ],
        }

    update_yaml_mapping_locked(path, update, backup_existing=True)
    return saved_plan


def delete_user_set_plan(
    game_id: str,
    character_id: str,
    plan_id: str,
    root: Path | None = None,
) -> bool:
    path = set_plan_store_path(game_id, character_id, root)
    deleted = False

    def update(data: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal deleted
        validate_store_schema_version(data, path)
        existing = _set_plans_from_data(data, path)
        remaining = [item for item in existing if item.id != plan_id]
        if len(remaining) == len(existing):
            return data
        deleted = True
        if not remaining:
            return None
        return {
            "schema_version": USER_STORE_SCHEMA_VERSION,
            "game": game_id,
            "character": character_id,
            "set_plans": [
                item.model_dump(mode="json", exclude_none=True)
                for item in remaining
            ],
        }

    update_yaml_mapping_locked(path, update, backup_existing=True)
    return deleted
