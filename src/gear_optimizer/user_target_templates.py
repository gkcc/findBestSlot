from __future__ import annotations

from pathlib import Path
from typing import Any

from gear_optimizer.models import CharacterPreset
from gear_optimizer.paths import app_data_root
from gear_optimizer.storage_io import (
    USER_STORE_SCHEMA_VERSION,
    read_yaml_mapping,
    safe_storage_id,
    update_yaml_mapping_locked,
    validate_store_schema_version,
)

HIDDEN_BUILTIN_TEMPLATE_IDS_KEY = "hidden_builtin_template_ids"


def target_template_store_path(game_id: str, root: Path | None = None) -> Path:
    base = root or app_data_root()
    return base / "target_templates" / f"{game_id}.yaml"


def _template_records(
    game_id: str,
    root: Path | None = None,
) -> list[tuple[CharacterPreset, str, str]]:
    path = target_template_store_path(game_id, root)
    data = read_yaml_mapping(path)
    validate_store_schema_version(data, path)
    return _template_records_from_data(data, path)


def _template_records_from_data(
    data: dict[str, Any],
    path: Path,
) -> list[tuple[CharacterPreset, str, str]]:
    templates = data.get("templates", [])
    if not isinstance(templates, list):
        raise ValueError(f"templates must be a list in {path}")
    records: list[tuple[CharacterPreset, str, str]] = []
    for item in templates:
        if not isinstance(item, dict):
            raise ValueError(f"template item must be a mapping in {path}")
        source_character_id = str(
            item.get("source_character_id")
            or item.get("base_character_id")
            or ""
        )
        source_agent_id = str(item.get("source_agent_id") or "")
        records.append((CharacterPreset.model_validate(item), source_character_id, source_agent_id))
    return records


def load_user_target_templates(
    game_id: str,
    root: Path | None = None,
) -> list[CharacterPreset]:
    return [preset for preset, _source, _agent in _template_records(game_id, root)]


def load_user_target_template_sources(
    game_id: str,
    root: Path | None = None,
) -> dict[str, str]:
    return {
        preset.id: source
        for preset, source, _agent in _template_records(game_id, root)
        if source
    }


def load_user_target_template_source_agents(
    game_id: str,
    root: Path | None = None,
) -> dict[str, str]:
    return {
        preset.id: source_agent_id
        for preset, _source, source_agent_id in _template_records(game_id, root)
        if source_agent_id
    }


def _template_payload(
    preset: CharacterPreset,
    source_character_id: str = "",
    source_agent_id: str = "",
) -> dict[str, Any]:
    payload = preset.model_dump(mode="json", exclude_none=True)
    if source_character_id:
        payload["source_character_id"] = source_character_id
    if source_agent_id:
        payload["source_agent_id"] = source_agent_id
    return payload


def _store_payload(
    game_id: str,
    records: list[tuple[CharacterPreset, str, str]],
    hidden_builtin_template_ids: set[str] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"game": game_id}
    data["schema_version"] = USER_STORE_SCHEMA_VERSION
    hidden_ids = sorted(hidden_builtin_template_ids or set())
    if hidden_ids:
        data[HIDDEN_BUILTIN_TEMPLATE_IDS_KEY] = hidden_ids
    if records:
        data["templates"] = [
            _template_payload(item, source, agent)
            for item, source, agent in records
        ]
    return data


def load_hidden_builtin_target_template_ids(
    game_id: str,
    root: Path | None = None,
) -> set[str]:
    path = target_template_store_path(game_id, root)
    data = read_yaml_mapping(path)
    validate_store_schema_version(data, path)
    return _hidden_ids_from_data(data, path)


def _hidden_ids_from_data(data: dict[str, Any], path: Path) -> set[str]:
    raw_ids = data.get(HIDDEN_BUILTIN_TEMPLATE_IDS_KEY, [])
    if raw_ids is None:
        return set()
    if not isinstance(raw_ids, list):
        raise ValueError(f"{HIDDEN_BUILTIN_TEMPLATE_IDS_KEY} must be a list in {path}")
    return {str(item) for item in raw_ids if str(item)}


def hide_builtin_target_template(
    game_id: str,
    preset_id: str,
    root: Path | None = None,
) -> bool:
    if preset_id.startswith("user_"):
        return False
    path = target_template_store_path(game_id, root)
    changed = False

    def update(data: dict[str, Any]) -> dict[str, Any]:
        nonlocal changed
        validate_store_schema_version(data, path)
        records = _template_records_from_data(data, path)
        hidden_ids = _hidden_ids_from_data(data, path)
        if preset_id in hidden_ids:
            return data
        hidden_ids.add(preset_id)
        changed = True
        return _store_payload(game_id, records, hidden_ids)

    update_yaml_mapping_locked(path, update, backup_existing=True)
    return changed


def unhide_builtin_target_template(
    game_id: str,
    preset_id: str,
    root: Path | None = None,
) -> bool:
    path = target_template_store_path(game_id, root)
    changed = False

    def update(data: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal changed
        validate_store_schema_version(data, path)
        records = _template_records_from_data(data, path)
        hidden_ids = _hidden_ids_from_data(data, path)
        if preset_id not in hidden_ids:
            return data
        hidden_ids.remove(preset_id)
        changed = True
        if records or hidden_ids:
            return _store_payload(game_id, records, hidden_ids)
        return None

    update_yaml_mapping_locked(path, update, backup_existing=True)
    return changed


def _new_template_id(
    preset: CharacterPreset,
    label: str,
    source_character_id: str | None = None,
    source_agent_id: str | None = None,
) -> str:
    if preset.id.startswith("user_"):
        return preset.id
    source = source_agent_id or source_character_id or preset.id
    return (
        f"user_{safe_storage_id(source, fallback='target_template')}_"
        f"{safe_storage_id(label, fallback='target_template')}"
    )


def save_user_target_template(
    game_id: str,
    preset: CharacterPreset,
    label: str,
    root: Path | None = None,
    *,
    source_character_id: str | None = None,
    source_agent_id: str | None = None,
) -> CharacterPreset:
    saved_label = label.strip() or preset.name or "目标模板"
    saved_id = _new_template_id(preset, saved_label, source_character_id, source_agent_id)
    saved = preset.model_copy(update={"id": saved_id, "name": saved_label, "game": game_id})
    path = target_template_store_path(game_id, root)

    def update(data: dict[str, Any]) -> dict[str, Any]:
        validate_store_schema_version(data, path)
        previous_records = _template_records_from_data(data, path)
        previous_source = next(
            (source for item, source, _agent in previous_records if item.id == saved.id and source),
            "",
        )
        previous_agent_source = next(
            (agent for item, _source, agent in previous_records if item.id == saved.id and agent),
            "",
        )
        if source_character_id is None:
            resolved_source = previous_source or (
                preset.id if not preset.id.startswith("user_") else ""
            )
        else:
            resolved_source = source_character_id
        resolved_agent_source = (
            source_agent_id if source_agent_id is not None else previous_agent_source
        )
        hidden_ids = _hidden_ids_from_data(data, path)
        existing = [
            (item, source, agent)
            for item, source, agent in previous_records
            if item.id != saved.id
        ]
        existing.append((saved, resolved_source, resolved_agent_source))
        return _store_payload(game_id, existing, hidden_ids)

    update_yaml_mapping_locked(path, update, backup_existing=True)
    return saved


def delete_user_target_template(
    game_id: str,
    preset_id: str,
    root: Path | None = None,
) -> bool:
    path = target_template_store_path(game_id, root)
    deleted = False

    def update(data: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal deleted
        validate_store_schema_version(data, path)
        existing = _template_records_from_data(data, path)
        hidden_ids = _hidden_ids_from_data(data, path)
        remaining = [
            (item, source, agent)
            for item, source, agent in existing
            if item.id != preset_id
        ]
        if len(remaining) == len(existing):
            return data
        deleted = True
        if remaining or hidden_ids:
            return _store_payload(game_id, remaining, hidden_ids)
        return None

    update_yaml_mapping_locked(path, update, backup_existing=True)
    return deleted
