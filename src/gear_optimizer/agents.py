from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
from typing import Any
import uuid

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from gear_optimizer.game_rules import PROJECT_ROOT, load_characters, read_yaml
from gear_optimizer.models import CharacterPreset, GearPiece, position_key
from gear_optimizer.paths import app_data_root
from gear_optimizer.presets import current_gear_data_to_pieces
from gear_optimizer.user_inventory import load_user_inventory

MULTI_AGENT_SCHEMA_VERSION = 1
DEFAULT_LOADOUT_ID = "default"
UNKNOWN_LABEL = "未知"


def _base_root(root: Path | None = None) -> Path:
    return root or app_data_root()


def _now_text() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _safe_id(value: str) -> str:
    text = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in text.split("_") if part) or "agent"


def _safe_timestamp_path(value: str) -> str:
    safe = "".join(char for char in value if char.isalnum() or char in "-_")
    return safe or "migration"


def _relative_text(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _local_asset_issue(path_text: str | None, project_root: Path = PROJECT_ROOT) -> str | None:
    if not path_text:
        return None
    lowered = path_text.lower()
    if lowered.startswith(("http://", "https://")):
        return f"remote asset is not allowed: {path_text}"
    path = Path(path_text)
    full_path = path if path.is_absolute() else project_root / path
    if not full_path.exists():
        return f"missing asset: {path_text}"
    return None


class AgentMetadata(BaseModel):
    agent_id: str
    name: str
    rarity: str = UNKNOWN_LABEL
    attribute: str = UNKNOWN_LABEL
    specialty: str = UNKNOWN_LABEL
    faction: str = UNKNOWN_LABEL
    level_cap: int | None = Field(default=None, ge=1)
    release_version: str | None = None
    release_order: float = 0.0
    portrait_path: str | None = None
    card_path: str | None = None
    character_preset_id: str

    @field_validator("portrait_path", "card_path")
    @classmethod
    def reject_remote_assets(cls, value: str | None) -> str | None:
        if value and value.lower().startswith(("http://", "https://")):
            raise ValueError("agent assets must be local paths")
        return value

    @classmethod
    def fallback_for_character(cls, character: CharacterPreset) -> "AgentMetadata":
        return cls(
            agent_id=f"fallback_{_safe_id(character.id)}",
            name=character.name,
            character_preset_id=character.id,
        )


class AgentCatalog(BaseModel):
    game: str
    agents: list[AgentMetadata] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_agents(self) -> "AgentCatalog":
        ids = [agent.agent_id for agent in self.agents]
        if len(ids) != len(set(ids)):
            raise ValueError("agent catalog contains duplicate agent_id")
        return self


class AgentUserState(BaseModel):
    owned: bool = False
    level: int | None = Field(default=None, ge=1)
    favorite: bool = False
    active_loadout_id: str = DEFAULT_LOADOUT_ID
    notes: str = ""


class AgentUserStateStore(BaseModel):
    game: str
    agents: dict[str, AgentUserState] = Field(default_factory=dict)


class InventoryItem(BaseModel):
    item_id: str
    piece: GearPiece
    locked: bool = False
    created_at: str
    updated_at: str
    migrated_from: dict[str, Any] | None = None

    @field_validator("item_id")
    @classmethod
    def item_id_must_be_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("item_id is required")
        return value


class GlobalInventoryStore(BaseModel):
    game: str
    schema_version: int = MULTI_AGENT_SCHEMA_VERSION
    items: list[InventoryItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_item_ids(self) -> "GlobalInventoryStore":
        ids = [item.item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("global inventory contains duplicate item_id")
        return self


class AgentLoadout(BaseModel):
    loadout_id: str = DEFAULT_LOADOUT_ID
    label: str = "当前装备"
    slot_items: dict[str, str | None] = Field(default_factory=dict)
    updated_at: str

    @field_validator("slot_items")
    @classmethod
    def normalize_slot_keys(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        return {position_key(key): item_id for key, item_id in value.items()}


class AgentLoadoutStore(BaseModel):
    game: str
    agent_id: str
    schema_version: int = MULTI_AGENT_SCHEMA_VERSION
    loadouts: list[AgentLoadout] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_loadouts(self) -> "AgentLoadoutStore":
        ids = [loadout.loadout_id for loadout in self.loadouts]
        if len(ids) != len(set(ids)):
            raise ValueError("agent loadouts contain duplicate loadout_id")
        return self


class MigrationDuplicateGroup(BaseModel):
    signature: str
    rows: list[str]
    count: int


class MigrationIssue(BaseModel):
    severity: str
    code: str
    message: str


class MigrationReport(BaseModel):
    game: str
    dry_run: bool
    inventory_items: list[InventoryItem] = Field(default_factory=list)
    loadout_stores: list[AgentLoadoutStore] = Field(default_factory=list)
    exact_duplicate_groups: list[MigrationDuplicateGroup] = Field(default_factory=list)
    unordered_duplicate_groups: list[MigrationDuplicateGroup] = Field(default_factory=list)
    issues: list[MigrationIssue] = Field(default_factory=list)
    legacy_inventory_files: list[str] = Field(default_factory=list)
    legacy_current_files: list[str] = Field(default_factory=list)
    backup_path: str | None = None

    @property
    def blocking_issues(self) -> list[MigrationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]


def agent_catalog_path(game_id: str, project_root: Path = PROJECT_ROOT) -> Path:
    return project_root / "configs" / "agents" / f"{game_id}.yaml"


def agent_user_state_store_path(game_id: str, root: Path | None = None) -> Path:
    return _base_root(root) / "agents" / f"{game_id}.yaml"


def global_inventory_store_path(game_id: str, root: Path | None = None) -> Path:
    return _base_root(root) / "inventory" / game_id / "global.yaml"


def agent_loadout_store_path(game_id: str, agent_id: str, root: Path | None = None) -> Path:
    return _base_root(root) / "loadouts" / game_id / f"{agent_id}.yaml"


def load_agent_catalog(game_id: str, project_root: Path = PROJECT_ROOT) -> AgentCatalog:
    path = agent_catalog_path(game_id, project_root)
    if not path.exists():
        return AgentCatalog(game=game_id, agents=[])
    data = read_yaml(path)
    return AgentCatalog.model_validate(data)


def agent_metadata_with_fallbacks(
    game_id: str,
    characters: list[CharacterPreset],
    catalog: AgentCatalog | None = None,
) -> list[AgentMetadata]:
    catalog = catalog or load_agent_catalog(game_id)
    by_character = {agent.character_preset_id: agent for agent in catalog.agents}
    agents = list(catalog.agents)
    known_agent_ids = {agent.agent_id for agent in agents}
    for character in characters:
        if character.id in by_character:
            continue
        fallback = AgentMetadata.fallback_for_character(character)
        if fallback.agent_id not in known_agent_ids:
            agents.append(fallback)
            known_agent_ids.add(fallback.agent_id)
    return sort_agent_metadata(agents)


def sort_agent_metadata(agents: list[AgentMetadata]) -> list[AgentMetadata]:
    return sorted(
        agents,
        key=lambda agent: (
            float(agent.release_order or 0.0),
            1 if str(agent.rarity).startswith("5") or str(agent.rarity).upper() == "S" else 0,
            agent.name,
        ),
        reverse=True,
    )


def filter_agent_metadata(
    agents: list[AgentMetadata],
    *,
    attribute: str | None = None,
    specialty: str | None = None,
    text: str | None = None,
) -> list[AgentMetadata]:
    attribute = "" if attribute in {None, "", "全部"} else str(attribute)
    specialty = "" if specialty in {None, "", "全部"} else str(specialty)
    needle = " ".join(str(text or "").split()).lower()
    rows: list[AgentMetadata] = []
    for agent in agents:
        if attribute and agent.attribute != attribute:
            continue
        if specialty and agent.specialty != specialty:
            continue
        haystack = " ".join(
            [
                agent.name,
                agent.agent_id,
                agent.rarity,
                agent.attribute,
                agent.specialty,
                agent.faction,
                agent.character_preset_id,
                agent.release_version or "",
            ]
        ).lower()
        if needle and needle not in haystack:
            continue
        rows.append(agent)
    return sort_agent_metadata(rows)


def agent_filter_values(agents: list[AgentMetadata], field_name: str) -> list[str]:
    values = {
        str(getattr(agent, field_name, "") or "")
        for agent in agents
        if str(getattr(agent, field_name, "") or "") not in {"", UNKNOWN_LABEL}
    }
    return sorted(values)


def missing_agent_asset_issues(
    agents: list[AgentMetadata],
    project_root: Path = PROJECT_ROOT,
) -> list[MigrationIssue]:
    issues: list[MigrationIssue] = []
    for agent in agents:
        for field_name in ["portrait_path", "card_path"]:
            issue = _local_asset_issue(getattr(agent, field_name), project_root)
            if issue:
                issues.append(
                    MigrationIssue(
                        severity="warning",
                        code="agent_asset_missing",
                        message=f"{agent.agent_id} {field_name}: {issue}",
                    )
                )
    return issues


def load_agent_user_state_store(
    game_id: str,
    root: Path | None = None,
) -> AgentUserStateStore:
    path = agent_user_state_store_path(game_id, root)
    if not path.exists():
        return AgentUserStateStore(game=game_id)
    return AgentUserStateStore.model_validate(read_yaml(path))


def save_agent_user_state_store(
    store: AgentUserStateStore,
    root: Path | None = None,
) -> Path:
    path = agent_user_state_store_path(store.game, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(store.model_dump(mode="json"), handle, allow_unicode=True, sort_keys=False)
    return path


def new_inventory_item(
    piece: GearPiece,
    item_id: str | None = None,
    now: str | None = None,
    migrated_from: dict[str, Any] | None = None,
) -> InventoryItem:
    timestamp = now or _now_text()
    return InventoryItem(
        item_id=item_id or f"inv_{uuid.uuid4().hex[:12]}",
        piece=piece,
        locked=piece.locked,
        created_at=timestamp,
        updated_at=timestamp,
        migrated_from=migrated_from,
    )


def load_global_inventory_store(game_id: str, root: Path | None = None) -> GlobalInventoryStore:
    path = global_inventory_store_path(game_id, root)
    if not path.exists():
        return GlobalInventoryStore(game=game_id)
    return GlobalInventoryStore.model_validate(read_yaml(path))


def save_global_inventory_store(
    store: GlobalInventoryStore,
    root: Path | None = None,
) -> Path:
    path = global_inventory_store_path(store.game, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    validated = GlobalInventoryStore.model_validate(store.model_dump(mode="json"))
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(validated.model_dump(mode="json"), handle, allow_unicode=True, sort_keys=False)
    return path


def load_agent_loadout_store(
    game_id: str,
    agent_id: str,
    root: Path | None = None,
) -> AgentLoadoutStore:
    path = agent_loadout_store_path(game_id, agent_id, root)
    if not path.exists():
        return AgentLoadoutStore(game=game_id, agent_id=agent_id)
    return AgentLoadoutStore.model_validate(read_yaml(path))


def save_agent_loadout_store(
    store: AgentLoadoutStore,
    root: Path | None = None,
) -> Path:
    path = agent_loadout_store_path(store.game, store.agent_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    validated = AgentLoadoutStore.model_validate(store.model_dump(mode="json"))
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(validated.model_dump(mode="json"), handle, allow_unicode=True, sort_keys=False)
    return path


def load_inventory_items_compatible(
    game_id: str,
    character_id: str,
    root: Path | None = None,
) -> list[InventoryItem]:
    global_path = global_inventory_store_path(game_id, root)
    if global_path.exists():
        return load_global_inventory_store(game_id, root).items
    pieces = load_user_inventory(game_id, character_id, root)
    return [
        new_inventory_item(
            piece,
            item_id=_stable_migration_item_id(
                "legacy-compatible",
                f"{character_id}:{index}",
                piece,
            ),
            migrated_from={"kind": "legacy_inventory", "character_id": character_id, "row": index},
        )
        for index, piece in enumerate(pieces, start=1)
    ]


def expand_agent_loadout(
    inventory: GlobalInventoryStore,
    loadout_store: AgentLoadoutStore,
    loadout_id: str = DEFAULT_LOADOUT_ID,
) -> list[GearPiece]:
    loadout = next(
        (item for item in loadout_store.loadouts if item.loadout_id == loadout_id),
        None,
    )
    if loadout is None:
        return []
    items_by_id = {item.item_id: item for item in inventory.items}
    pieces: list[GearPiece] = []
    missing: list[str] = []
    for item_id in loadout.slot_items.values():
        if not item_id:
            continue
        item = items_by_id.get(item_id)
        if item is None:
            missing.append(item_id)
            continue
        pieces.append(item.piece)
    if missing:
        raise ValueError(f"loadout references missing inventory item_id: {missing}")
    return pieces


def split_current_and_inventory_for_agent(
    inventory: GlobalInventoryStore,
    loadout_store: AgentLoadoutStore,
    loadout_id: str = DEFAULT_LOADOUT_ID,
) -> tuple[list[GearPiece], list[GearPiece]]:
    current_pieces = expand_agent_loadout(inventory, loadout_store, loadout_id)
    equipped_ids = {
        item_id
        for loadout in loadout_store.loadouts
        if loadout.loadout_id == loadout_id
        for item_id in loadout.slot_items.values()
        if item_id
    }
    inventory_pieces = [
        item.piece
        for item in inventory.items
        if item.item_id not in equipped_ids
    ]
    return current_pieces, inventory_pieces


def loadout_reference_issues(
    inventory: GlobalInventoryStore,
    loadout_stores: list[AgentLoadoutStore],
) -> list[MigrationIssue]:
    issues: list[MigrationIssue] = []
    item_ids = {item.item_id for item in inventory.items}
    usages: defaultdict[str, list[tuple[str, str, str]]] = defaultdict(list)

    for store in loadout_stores:
        try:
            AgentLoadoutStore.model_validate(store.model_dump(mode="json"))
        except ValueError as exc:
            issues.append(
                MigrationIssue(
                    severity="error",
                    code="loadout_id_conflict",
                    message=f"{store.agent_id}: {exc}",
                )
            )

        for loadout in store.loadouts:
            for position, item_id in loadout.slot_items.items():
                if not item_id:
                    continue
                if item_id not in item_ids:
                    issues.append(
                        MigrationIssue(
                            severity="error",
                            code="loadout_item_missing",
                            message=(
                                f"{store.agent_id}/{loadout.loadout_id} slot {position} "
                                f"references missing item_id {item_id}"
                            ),
                        )
                    )
                usages[item_id].append((store.agent_id, loadout.loadout_id, position))

    for item_id, item_usages in sorted(usages.items()):
        agent_ids = {agent_id for agent_id, _loadout_id, _position in item_usages}
        if len(agent_ids) <= 1:
            continue
        details = ", ".join(
            f"{agent_id}/{loadout_id}/{position}"
            for agent_id, loadout_id, position in item_usages
        )
        issues.append(
            MigrationIssue(
                severity="warning",
                code="shared_equipment_conflict",
                message=f"{item_id} is referenced by multiple agents: {details}",
            )
        )

    return issues


def _piece_signature(piece: GearPiece, unordered_substats: bool = False) -> str:
    data = piece.model_dump(mode="json")
    substats = data.get("substats") or []
    if unordered_substats:
        data["substats"] = sorted(
            substats,
            key=lambda item: (str(item.get("stat") or ""), int(item.get("rolls") or 0)),
        )
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=True)


def _stable_migration_item_id(source_path: str, row_key: str, piece: GearPiece) -> str:
    digest = hashlib.sha1(
        f"{source_path}|{row_key}|{_piece_signature(piece)}".encode("utf-8")
    ).hexdigest()
    return f"mig_{digest[:12]}"


def _duplicate_groups(items: list[tuple[str, GearPiece]], unordered: bool = False) -> list[MigrationDuplicateGroup]:
    rows_by_signature: defaultdict[str, list[str]] = defaultdict(list)
    for row_label, piece in items:
        rows_by_signature[_piece_signature(piece, unordered)].append(row_label)
    return [
        MigrationDuplicateGroup(signature=signature, rows=rows, count=len(rows))
        for signature, rows in sorted(rows_by_signature.items())
        if len(rows) > 1
    ]


def _legacy_inventory_files(game_id: str, root: Path) -> list[Path]:
    folder = root / "inventory" / game_id
    if not folder.exists():
        return []
    return sorted(path for path in folder.glob("*.yaml") if path.stem != "global")


def _legacy_current_files(game_id: str, root: Path) -> list[Path]:
    folder = root / "current_gear" / game_id
    if not folder.exists():
        return []
    return sorted(folder.glob("*.yaml"))


def _load_current_file_templates(path: Path, game_id: str) -> list[dict[str, Any]]:
    data = read_yaml(path)
    templates = data.get("templates")
    if isinstance(templates, list):
        values = []
        for index, item in enumerate(templates, start=1):
            values.append(
                {
                    "id": str(item.get("id") or f"template_{index}"),
                    "label": str(item.get("label") or item.get("id") or f"模板 {index}"),
                    "pieces": current_gear_data_to_pieces(item, game_id=game_id),
                }
            )
        return values
    return [
        {
            "id": DEFAULT_LOADOUT_ID,
            "label": str(data.get("label") or "当前装备"),
            "pieces": current_gear_data_to_pieces(data, game_id=game_id),
        }
    ]


def _character_id_from_legacy_path(path: Path) -> str:
    return path.stem


def _agent_for_character(
    character_id: str,
    characters_by_id: dict[str, CharacterPreset],
    metadata_by_character: dict[str, AgentMetadata],
) -> AgentMetadata:
    metadata = metadata_by_character.get(character_id)
    if metadata is not None:
        return metadata
    character = characters_by_id.get(character_id)
    if character is not None:
        return AgentMetadata.fallback_for_character(character)
    return AgentMetadata(
        agent_id=f"fallback_{_safe_id(character_id)}",
        name=character_id,
        character_preset_id=character_id,
    )


def dry_run_multi_agent_migration(
    game_id: str,
    root: Path | None = None,
    project_root: Path = PROJECT_ROOT,
    now: str | None = None,
) -> MigrationReport:
    base = _base_root(root)
    timestamp = now or _now_text()
    characters = load_characters(game_id)
    characters_by_id = {character.id: character for character in characters}
    catalog = load_agent_catalog(game_id, project_root)
    metadata_by_character = {agent.character_preset_id: agent for agent in catalog.agents}
    issues = missing_agent_asset_issues(catalog.agents, project_root)

    inventory_files = _legacy_inventory_files(game_id, base)
    current_files = _legacy_current_files(game_id, base)
    legacy_character_ids = {
        _character_id_from_legacy_path(path)
        for path in [*inventory_files, *current_files]
    }
    for character_id in sorted(legacy_character_ids):
        if character_id not in metadata_by_character:
            issues.append(
                MigrationIssue(
                    severity="warning",
                    code="agent_metadata_missing",
                    message=f"{character_id} has no AgentMetadata; fallback agent will be used",
                )
            )
        if character_id not in characters_by_id:
            issues.append(
                MigrationIssue(
                    severity="warning",
                    code="character_preset_missing",
                    message=f"{character_id} has no CharacterPreset; agent can display but cannot calculate",
                )
            )

    items: list[InventoryItem] = []
    row_items: list[tuple[str, GearPiece]] = []
    signature_to_item_id: dict[str, str] = {}

    def add_item(
        piece: GearPiece,
        source_path: Path,
        row_key: str,
        migrated_from: dict[str, Any],
    ) -> str:
        source_text = _relative_text(source_path, base)
        item_id = _stable_migration_item_id(source_text, row_key, piece)
        item = new_inventory_item(
            piece,
            item_id=item_id,
            now=timestamp,
            migrated_from=migrated_from,
        )
        items.append(item)
        label = f"{source_text}:{row_key}"
        row_items.append((label, piece))
        signature_to_item_id.setdefault(_piece_signature(piece), item_id)
        return item_id

    for path in inventory_files:
        character_id = _character_id_from_legacy_path(path)
        for row_index, piece in enumerate(load_user_inventory(game_id, character_id, base), start=1):
            add_item(
                piece,
                path,
                str(row_index),
                {
                    "kind": "legacy_inventory",
                    "path": _relative_text(path, base),
                    "row": row_index,
                },
            )

    loadout_stores_by_agent: dict[str, AgentLoadoutStore] = {}
    for path in current_files:
        character_id = _character_id_from_legacy_path(path)
        agent = _agent_for_character(character_id, characters_by_id, metadata_by_character)
        store = loadout_stores_by_agent.setdefault(
            agent.agent_id,
            AgentLoadoutStore(game=game_id, agent_id=agent.agent_id),
        )
        templates = _load_current_file_templates(path, game_id)
        for template in templates:
            loadout_id = DEFAULT_LOADOUT_ID if len(templates) == 1 else str(template["id"])
            slot_items: dict[str, str | None] = {}
            seen_positions = Counter(position_key(piece.position) for piece in template["pieces"])
            for position, count in seen_positions.items():
                if count > 1:
                    issues.append(
                        MigrationIssue(
                            severity="error",
                            code="loadout_slot_conflict",
                            message=f"{path.name} {template['id']} has {count} pieces for position {position}",
                        )
                    )
            for row_index, piece in enumerate(template["pieces"], start=1):
                signature = _piece_signature(piece)
                item_id = signature_to_item_id.get(signature)
                if item_id is None:
                    row_key = f"{loadout_id}:{row_index}"
                    item_id = add_item(
                        piece,
                        path,
                        row_key,
                        {
                            "kind": "legacy_current_gear",
                            "path": _relative_text(path, base),
                            "template_id": loadout_id,
                            "row": row_index,
                        },
                    )
                slot_items[position_key(piece.position)] = item_id
            store.loadouts.append(
                AgentLoadout(
                    loadout_id=loadout_id,
                    label=str(template["label"]),
                    slot_items=slot_items,
                    updated_at=timestamp,
                )
            )

    inventory_store: GlobalInventoryStore | None = None
    try:
        inventory_store = GlobalInventoryStore(game=game_id, items=items)
    except ValueError as exc:
        issues.append(
            MigrationIssue(
                severity="error",
                code="inventory_item_id_conflict",
                message=str(exc),
            )
        )
    if inventory_store is not None:
        issues.extend(
            loadout_reference_issues(
                inventory_store,
                list(loadout_stores_by_agent.values()),
            )
        )

    exact_duplicates = _duplicate_groups(row_items, unordered=False)
    unordered_duplicates = _duplicate_groups(row_items, unordered=True)
    return MigrationReport(
        game=game_id,
        dry_run=True,
        inventory_items=items,
        loadout_stores=list(loadout_stores_by_agent.values()),
        exact_duplicate_groups=exact_duplicates,
        unordered_duplicate_groups=unordered_duplicates,
        issues=issues,
        legacy_inventory_files=[_relative_text(path, base) for path in inventory_files],
        legacy_current_files=[_relative_text(path, base) for path in current_files],
    )


def _copy_if_exists(source: Path, backup_root: Path, base: Path) -> None:
    if not source.exists():
        return
    target = backup_root / _relative_text(source, base)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def apply_multi_agent_migration(
    game_id: str,
    root: Path | None = None,
    project_root: Path = PROJECT_ROOT,
    now: str | None = None,
) -> MigrationReport:
    base = _base_root(root)
    timestamp = now or _now_text()
    report = dry_run_multi_agent_migration(game_id, base, project_root, timestamp)
    if report.blocking_issues:
        details = "; ".join(issue.message for issue in report.blocking_issues)
        raise ValueError(f"Cannot apply migration with blocking issues: {details}")

    backup_root = base / "backups" / "multi_agent_migration" / _safe_timestamp_path(timestamp)
    paths_to_backup = [
        *_legacy_inventory_files(game_id, base),
        *_legacy_current_files(game_id, base),
        global_inventory_store_path(game_id, base),
        *(agent_loadout_store_path(game_id, store.agent_id, base) for store in report.loadout_stores),
    ]
    for path in paths_to_backup:
        _copy_if_exists(path, backup_root, base)

    save_global_inventory_store(
        GlobalInventoryStore(game=game_id, items=report.inventory_items),
        base,
    )
    for store in report.loadout_stores:
        save_agent_loadout_store(store, base)

    return report.model_copy(
        update={
            "dry_run": False,
            "backup_path": _relative_text(backup_root, base),
        }
    )


def migration_report_markdown(report: MigrationReport) -> str:
    lines = [
        f"# {report.game} 多代理人库存迁移报告",
        "",
        f"- 模式：{'dry-run' if report.dry_run else 'apply'}",
        f"- 预览 InventoryItem：{len(report.inventory_items)}",
        f"- 预览 AgentLoadout：{sum(len(store.loadouts) for store in report.loadout_stores)}",
        f"- 旧库存文件：{len(report.legacy_inventory_files)}",
        f"- 旧当前装备文件：{len(report.legacy_current_files)}",
        f"- 完全重复组：{len(report.exact_duplicate_groups)}",
        f"- 疑似重复组：{len(report.unordered_duplicate_groups)}",
    ]
    if report.backup_path:
        lines.append(f"- 备份目录：{report.backup_path}")
    lines.extend(["", "## Issues"])
    if report.issues:
        lines.extend(
            f"- [{issue.severity}] {issue.code}: {issue.message}"
            for issue in report.issues
        )
    else:
        lines.append("- 无")
    lines.extend(["", "## Exact Duplicates"])
    if report.exact_duplicate_groups:
        for group in report.exact_duplicate_groups:
            lines.append(f"- x{group.count}: {', '.join(group.rows)}")
    else:
        lines.append("- 无")
    lines.extend(["", "## Unordered Duplicates"])
    if report.unordered_duplicate_groups:
        for group in report.unordered_duplicate_groups:
            lines.append(f"- x{group.count}: {', '.join(group.rows)}")
    else:
        lines.append("- 无")
    return "\n".join(lines) + "\n"


def migration_report_json(report: MigrationReport) -> str:
    return report.model_dump_json(indent=2)
