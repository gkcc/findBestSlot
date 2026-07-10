from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from gear_optimizer.paths import app_data_root
from gear_optimizer.storage_io import (
    USER_STORE_SCHEMA_VERSION,
    atomic_compare_and_swap_yaml,
    read_yaml_mapping,
    validate_store_schema_version,
)


class TargetTemplateSelectionStore(BaseModel):
    game: str
    schema_version: int = Field(
        default=USER_STORE_SCHEMA_VERSION,
        ge=1,
        le=USER_STORE_SCHEMA_VERSION,
    )
    revision: int = Field(default=0, ge=0, strict=True)
    selections: dict[str, str] = Field(default_factory=dict)


def target_template_selection_store_path(
    game_id: str,
    root: Path | None = None,
) -> Path:
    base = root or app_data_root()
    return base / "target_template_selections" / f"{game_id}.yaml"


def load_target_template_selection_store(
    game_id: str,
    root: Path | None = None,
) -> TargetTemplateSelectionStore:
    path = target_template_selection_store_path(game_id, root)
    if not path.exists():
        return TargetTemplateSelectionStore(game=game_id)
    data = read_yaml_mapping(path)
    validate_store_schema_version(data, path)
    store = TargetTemplateSelectionStore.model_validate(data)
    if store.game != game_id:
        raise ValueError(
            f"target template selection store belongs to {store.game}, not {game_id}"
        )
    return store


def save_target_template_selection_store(
    store: TargetTemplateSelectionStore,
    root: Path | None = None,
) -> Path:
    path = target_template_selection_store_path(store.game, root)
    validated = TargetTemplateSelectionStore.model_validate(store.model_dump(mode="json"))
    store.revision = atomic_compare_and_swap_yaml(
        path,
        validated.model_dump(mode="json"),
        expected_revision=validated.revision,
        backup_existing=True,
    )
    return path


def select_target_template(
    game_id: str,
    agent_id: str,
    template_id: str,
    root: Path | None = None,
) -> TargetTemplateSelectionStore:
    if not agent_id.strip():
        raise ValueError("agent_id is required")
    if not template_id.strip():
        raise ValueError("template_id is required")
    store = load_target_template_selection_store(game_id, root)
    store.selections[agent_id] = template_id
    save_target_template_selection_store(store, root)
    return store


def clear_target_template_selection(
    game_id: str,
    agent_id: str,
    root: Path | None = None,
) -> TargetTemplateSelectionStore:
    store = load_target_template_selection_store(game_id, root)
    if agent_id not in store.selections:
        return store
    del store.selections[agent_id]
    save_target_template_selection_store(store, root)
    return store
