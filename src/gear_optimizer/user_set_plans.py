from __future__ import annotations

from pathlib import Path

import yaml

from gear_optimizer.models import SetPlan
from gear_optimizer.paths import app_data_root


def _safe_id(value: str) -> str:
    text = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in text.split("_") if part) or "set_plan"


def user_data_root() -> Path:
    return app_data_root()


def set_plan_store_path(game_id: str, character_id: str, root: Path | None = None) -> Path:
    base = root or user_data_root()
    return base / "set_plans" / game_id / f"{character_id}.yaml"


def _read_store(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return data


def load_user_set_plans(
    game_id: str,
    character_id: str,
    root: Path | None = None,
) -> list[SetPlan]:
    path = set_plan_store_path(game_id, character_id, root)
    data = _read_store(path)
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
    saved_id = plan.id if plan.id.startswith("user_") else f"user_{_safe_id(saved_name)}"
    saved_plan = plan.model_copy(update={"id": saved_id, "name": saved_name})
    path = set_plan_store_path(game_id, character_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = [
        item
        for item in load_user_set_plans(game_id, character_id, root)
        if item.id != saved_plan.id
    ]
    existing.append(saved_plan)
    data = {
        "game": game_id,
        "character": character_id,
        "set_plans": [
            item.model_dump(mode="json", exclude_none=True)
            for item in existing
        ],
    }
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    return saved_plan


def delete_user_set_plan(
    game_id: str,
    character_id: str,
    plan_id: str,
    root: Path | None = None,
) -> bool:
    path = set_plan_store_path(game_id, character_id, root)
    existing = load_user_set_plans(game_id, character_id, root)
    remaining = [item for item in existing if item.id != plan_id]
    if len(remaining) == len(existing):
        return False
    if remaining:
        data = {
            "game": game_id,
            "character": character_id,
            "set_plans": [
                item.model_dump(mode="json", exclude_none=True)
                for item in remaining
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    elif path.exists():
        path.unlink()
    return True
