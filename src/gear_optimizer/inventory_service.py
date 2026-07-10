from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
import inspect
from pathlib import Path
from typing import ParamSpec, TypeVar

from gear_optimizer.agents import (
    DEFAULT_LOADOUT_ID,
    AgentLoadout,
    AgentLoadoutStore,
    AgentUserState,
    AgentUserStateStore,
    GlobalInventoryStore,
    InventoryItem,
    global_inventory_store_path,
    load_agent_loadout_store,
    load_agent_user_state_store,
    load_global_inventory_store,
    new_inventory_item,
    save_agent_loadout_store,
    save_agent_user_state_store,
    save_global_inventory_store,
)
from gear_optimizer.models import GearPiece, position_key
from gear_optimizer.paths import app_data_root
from gear_optimizer.storage_io import safe_storage_id, store_file_lock


P = ParamSpec("P")
R = TypeVar("R")


class CanonicalInventoryUnavailableError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class AgentInventoryView:
    game: str
    agent_id: str
    active_loadout_id: str | None
    current_items: tuple[InventoryItem, ...]
    backpack_items: tuple[InventoryItem, ...]

    @property
    def current_pieces(self) -> list[GearPiece]:
        return [item.piece for item in self.current_items]

    @property
    def backpack_pieces(self) -> list[GearPiece]:
        return [item.piece for item in self.backpack_items]


@dataclass(frozen=True)
class AgentLoadoutSnapshot:
    game: str
    agent_id: str
    loadout_id: str
    label: str
    items: tuple[InventoryItem, ...]
    active: bool

    @property
    def item_ids(self) -> list[str]:
        return [item.item_id for item in self.items]

    @property
    def pieces(self) -> list[GearPiece]:
        return [item.piece for item in self.items]


def _base_root(root: Path | None) -> Path:
    return root or app_data_root()


def _now_text() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _inventory_transaction_path(game_id: str, root: Path | None) -> Path:
    return _base_root(root) / "inventory" / game_id / "transaction"


def _serialized_inventory_operation(operation: Callable[P, R]) -> Callable[P, R]:
    operation_signature = inspect.signature(operation)

    @wraps(operation)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        arguments = operation_signature.bind(*args, **kwargs).arguments
        game_id = str(arguments["game_id"])
        root = arguments.get("root")
        with store_file_lock(_inventory_transaction_path(game_id, root)):
            return operation(*args, **kwargs)

    return wrapped


def canonical_inventory_available(game_id: str, root: Path | None = None) -> bool:
    return global_inventory_store_path(game_id, root).exists()


def load_agent_loadout_stores(
    game_id: str,
    root: Path | None = None,
) -> list[AgentLoadoutStore]:
    folder = _base_root(root) / "loadouts" / game_id
    if not folder.exists():
        return []
    return [
        load_agent_loadout_store(game_id, path.stem, root)
        for path in sorted(folder.glob("*.yaml"))
    ]


def _active_loadout(
    store: AgentLoadoutStore,
    user_states: AgentUserStateStore,
) -> AgentLoadout | None:
    state = user_states.agents.get(store.agent_id)
    requested_id = state.active_loadout_id if state is not None else DEFAULT_LOADOUT_ID
    requested = next(
        (loadout for loadout in store.loadouts if loadout.loadout_id == requested_id),
        None,
    )
    if requested is not None:
        return requested
    default = next(
        (loadout for loadout in store.loadouts if loadout.loadout_id == DEFAULT_LOADOUT_ID),
        None,
    )
    return default or (store.loadouts[0] if store.loadouts else None)


def _active_loadouts_by_agent(
    game_id: str,
    root: Path | None = None,
) -> tuple[dict[str, AgentLoadoutStore], dict[str, AgentLoadout | None]]:
    stores = {store.agent_id: store for store in load_agent_loadout_stores(game_id, root)}
    user_states = load_agent_user_state_store(game_id, root)
    active = {
        agent_id: _active_loadout(store, user_states)
        for agent_id, store in stores.items()
    }
    return stores, active


def _items_for_loadout(
    inventory: GlobalInventoryStore,
    loadout: AgentLoadout | None,
) -> tuple[InventoryItem, ...]:
    if loadout is None:
        return tuple()
    items_by_id = {item.item_id: item for item in inventory.items}
    missing = [
        item_id
        for item_id in loadout.slot_items.values()
        if item_id and item_id not in items_by_id
    ]
    if missing:
        raise ValueError(f"loadout references missing inventory item_id: {missing}")
    return tuple(
        items_by_id[item_id]
        for _position, item_id in sorted(loadout.slot_items.items())
        if item_id
    )


@_serialized_inventory_operation
def load_agent_inventory_view(
    game_id: str,
    agent_id: str,
    root: Path | None = None,
) -> AgentInventoryView:
    if not canonical_inventory_available(game_id, root):
        raise CanonicalInventoryUnavailableError(
            f"canonical global inventory does not exist: {global_inventory_store_path(game_id, root)}"
        )
    inventory = load_global_inventory_store(game_id, root)
    stores, active_loadouts = _active_loadouts_by_agent(game_id, root)
    selected_loadout = active_loadouts.get(agent_id)
    current_items = _items_for_loadout(inventory, selected_loadout)
    equipped_ids = {
        item_id
        for loadout in active_loadouts.values()
        if loadout is not None
        for item_id in loadout.slot_items.values()
        if item_id
    }
    backpack_items = tuple(
        item for item in inventory.items if item.item_id not in equipped_ids
    )
    return AgentInventoryView(
        game=game_id,
        agent_id=agent_id,
        active_loadout_id=selected_loadout.loadout_id if selected_loadout is not None else None,
        current_items=current_items,
        backpack_items=backpack_items,
    )


@_serialized_inventory_operation
def load_agent_loadout_snapshots(
    game_id: str,
    agent_id: str,
    root: Path | None = None,
) -> list[AgentLoadoutSnapshot]:
    if not canonical_inventory_available(game_id, root):
        raise CanonicalInventoryUnavailableError(
            f"canonical global inventory does not exist: {global_inventory_store_path(game_id, root)}"
        )
    inventory = load_global_inventory_store(game_id, root)
    store = load_agent_loadout_store(game_id, agent_id, root)
    user_states = load_agent_user_state_store(game_id, root)
    active = _active_loadout(store, user_states)
    active_id = active.loadout_id if active is not None else None
    return [
        AgentLoadoutSnapshot(
            game=game_id,
            agent_id=agent_id,
            loadout_id=loadout.loadout_id,
            label=loadout.label,
            items=_items_for_loadout(inventory, loadout),
            active=loadout.loadout_id == active_id,
        )
        for loadout in store.loadouts
    ]


def _validate_snapshot_slot_items(
    inventory: GlobalInventoryStore,
    slot_items: dict[str, str | None],
) -> dict[str, str | None]:
    normalized = {position_key(position): item_id for position, item_id in slot_items.items()}
    item_ids = [item_id for item_id in normalized.values() if item_id]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("loadout snapshot cannot reference the same item_id in multiple positions")
    items_by_id = {item.item_id: item for item in inventory.items}
    missing = [item_id for item_id in item_ids if item_id not in items_by_id]
    if missing:
        raise ValueError(f"loadout snapshot references missing inventory item_id: {missing}")
    mismatched = [
        f"{position}:{item_id}"
        for position, item_id in normalized.items()
        if item_id and position_key(items_by_id[item_id].piece.position) != position
    ]
    if mismatched:
        raise ValueError(f"loadout snapshot position does not match inventory item: {mismatched}")
    return normalized


def _conflicting_active_owners(
    game_id: str,
    agent_id: str,
    item_ids: set[str],
    root: Path | None,
) -> list[str]:
    _stores, active_loadouts = _active_loadouts_by_agent(game_id, root)
    return [
        f"{owner_agent_id}/{owner_loadout.loadout_id}/{position}"
        for owner_agent_id, owner_loadout in active_loadouts.items()
        if owner_agent_id != agent_id and owner_loadout is not None
        for position, equipped_id in owner_loadout.slot_items.items()
        if equipped_id in item_ids
    ]


def _set_active_loadout_id(
    game_id: str,
    agent_id: str,
    loadout_id: str,
    root: Path | None,
) -> None:
    user_states = load_agent_user_state_store(game_id, root)
    state = user_states.agents.get(agent_id) or AgentUserState()
    state.active_loadout_id = loadout_id
    user_states.agents[agent_id] = state
    save_agent_user_state_store(user_states, root)


@_serialized_inventory_operation
def activate_agent_loadout(
    game_id: str,
    agent_id: str,
    loadout_id: str,
    root: Path | None = None,
) -> AgentLoadout:
    inventory = load_global_inventory_store(game_id, root)
    store = load_agent_loadout_store(game_id, agent_id, root)
    loadout = next(
        (candidate for candidate in store.loadouts if candidate.loadout_id == loadout_id),
        None,
    )
    if loadout is None:
        raise ValueError(f"unknown agent loadout: {agent_id}/{loadout_id}")
    normalized = _validate_snapshot_slot_items(inventory, loadout.slot_items)
    conflicts = _conflicting_active_owners(
        game_id,
        agent_id,
        {item_id for item_id in normalized.values() if item_id},
        root,
    )
    if conflicts:
        raise ValueError(f"loadout items are equipped by another agent: {', '.join(conflicts)}")
    _set_active_loadout_id(game_id, agent_id, loadout_id, root)
    return loadout


@_serialized_inventory_operation
def save_agent_loadout_snapshot(
    game_id: str,
    agent_id: str,
    label: str,
    slot_items: dict[str, str | None],
    root: Path | None = None,
    *,
    loadout_id: str | None = None,
    activate: bool = True,
    now: str | None = None,
) -> AgentLoadout:
    inventory = load_global_inventory_store(game_id, root)
    normalized = _validate_snapshot_slot_items(inventory, slot_items)
    store = load_agent_loadout_store(game_id, agent_id, root)
    saved_label = label.strip() or "当前装备"
    resolved_id = loadout_id or f"loadout_{safe_storage_id(saved_label, fallback='current')}"
    existing = next(
        (candidate for candidate in store.loadouts if candidate.loadout_id == resolved_id),
        None,
    )
    snapshot = AgentLoadout(
        loadout_id=resolved_id,
        label=saved_label,
        slot_items=normalized,
        updated_at=now or _now_text(),
    )
    if activate:
        conflicts = _conflicting_active_owners(
            game_id,
            agent_id,
            {item_id for item_id in normalized.values() if item_id},
            root,
        )
        if conflicts:
            raise ValueError(f"loadout items are equipped by another agent: {', '.join(conflicts)}")
    if existing is None:
        store.loadouts.append(snapshot)
    else:
        store.loadouts[store.loadouts.index(existing)] = snapshot
    save_agent_loadout_store(store, root)
    if activate:
        _set_active_loadout_id(game_id, agent_id, resolved_id, root)
    return snapshot


@_serialized_inventory_operation
def rename_agent_loadout_snapshot(
    game_id: str,
    agent_id: str,
    loadout_id: str,
    label: str,
    root: Path | None = None,
    *,
    now: str | None = None,
) -> AgentLoadout:
    store = load_agent_loadout_store(game_id, agent_id, root)
    loadout = next(
        (candidate for candidate in store.loadouts if candidate.loadout_id == loadout_id),
        None,
    )
    if loadout is None:
        raise ValueError(f"unknown agent loadout: {agent_id}/{loadout_id}")
    loadout.label = label.strip() or loadout.label
    loadout.updated_at = now or _now_text()
    save_agent_loadout_store(store, root)
    return loadout


@_serialized_inventory_operation
def delete_agent_loadout_snapshot(
    game_id: str,
    agent_id: str,
    loadout_id: str,
    root: Path | None = None,
) -> AgentLoadout:
    store = load_agent_loadout_store(game_id, agent_id, root)
    deleted = next(
        (candidate for candidate in store.loadouts if candidate.loadout_id == loadout_id),
        None,
    )
    if deleted is None:
        raise ValueError(f"unknown agent loadout: {agent_id}/{loadout_id}")
    user_states = load_agent_user_state_store(game_id, root)
    active = _active_loadout(store, user_states)
    store.loadouts = [candidate for candidate in store.loadouts if candidate.loadout_id != loadout_id]
    replacement_id: str | None = None
    if active is not None and active.loadout_id == loadout_id:
        replacement = store.loadouts[0] if store.loadouts else None
        replacement_id = replacement.loadout_id if replacement is not None else DEFAULT_LOADOUT_ID
    save_agent_loadout_store(store, root)
    if replacement_id is not None:
        _set_active_loadout_id(game_id, agent_id, replacement_id, root)
    return deleted


def _store_and_active_loadout_for_update(
    game_id: str,
    agent_id: str,
    root: Path | None,
    now: str,
) -> tuple[AgentLoadoutStore, AgentLoadout, dict[str, AgentLoadout | None]]:
    stores, active_loadouts = _active_loadouts_by_agent(game_id, root)
    store = stores.get(agent_id)
    if store is None:
        store = AgentLoadoutStore(game=game_id, agent_id=agent_id)
        stores[agent_id] = store
    loadout = active_loadouts.get(agent_id)
    if loadout is None:
        user_states = load_agent_user_state_store(game_id, root)
        state = user_states.agents.get(agent_id)
        loadout_id = state.active_loadout_id if state is not None else DEFAULT_LOADOUT_ID
        loadout = AgentLoadout(loadout_id=loadout_id, updated_at=now)
        store.loadouts.append(loadout)
        active_loadouts[agent_id] = loadout
    return store, loadout, active_loadouts


@_serialized_inventory_operation
def equip_inventory_item(
    game_id: str,
    agent_id: str,
    item_id: str,
    root: Path | None = None,
    *,
    now: str | None = None,
) -> str | None:
    inventory = load_global_inventory_store(game_id, root)
    item = next((candidate for candidate in inventory.items if candidate.item_id == item_id), None)
    if item is None:
        raise ValueError(f"unknown inventory item_id: {item_id}")
    timestamp = now or _now_text()
    store, loadout, active_loadouts = _store_and_active_loadout_for_update(
        game_id,
        agent_id,
        root,
        timestamp,
    )
    for owner_agent_id, owner_loadout in active_loadouts.items():
        if owner_agent_id == agent_id or owner_loadout is None:
            continue
        if item_id in owner_loadout.slot_items.values():
            raise ValueError(f"inventory item_id {item_id} is equipped by {owner_agent_id}")

    position = position_key(item.piece.position)
    slots = dict(loadout.slot_items)
    for slot, equipped_id in list(slots.items()):
        if equipped_id == item_id:
            slots[slot] = None
    previous_item_id = slots.get(position)
    slots[position] = item_id
    loadout.slot_items = slots
    loadout.updated_at = timestamp
    save_agent_loadout_store(store, root)
    return previous_item_id


@_serialized_inventory_operation
def unequip_inventory_position(
    game_id: str,
    agent_id: str,
    position: str | int,
    root: Path | None = None,
    *,
    now: str | None = None,
) -> str | None:
    timestamp = now or _now_text()
    store, loadout, _active_loadouts = _store_and_active_loadout_for_update(
        game_id,
        agent_id,
        root,
        timestamp,
    )
    key = position_key(position)
    previous_item_id = loadout.slot_items.get(key)
    loadout.slot_items = {**loadout.slot_items, key: None}
    loadout.updated_at = timestamp
    save_agent_loadout_store(store, root)
    return previous_item_id


@_serialized_inventory_operation
def add_inventory_piece(
    game_id: str,
    piece: GearPiece,
    root: Path | None = None,
    *,
    now: str | None = None,
) -> InventoryItem:
    inventory = load_global_inventory_store(game_id, root)
    item = new_inventory_item(piece, now=now)
    inventory.items.append(item)
    save_global_inventory_store(inventory, root)
    return item


@_serialized_inventory_operation
def update_inventory_piece(
    game_id: str,
    item_id: str,
    piece: GearPiece,
    root: Path | None = None,
    *,
    now: str | None = None,
) -> InventoryItem:
    inventory = load_global_inventory_store(game_id, root)
    index = next(
        (index for index, item in enumerate(inventory.items) if item.item_id == item_id),
        None,
    )
    if index is None:
        raise ValueError(f"unknown inventory item_id: {item_id}")
    existing = inventory.items[index]
    updated = existing.model_copy(
        update={
            "piece": piece,
            "locked": piece.locked,
            "updated_at": now or _now_text(),
        }
    )
    inventory.items[index] = updated
    save_global_inventory_store(inventory, root)
    return updated


@_serialized_inventory_operation
def delete_inventory_item(
    game_id: str,
    item_id: str,
    root: Path | None = None,
) -> InventoryItem:
    inventory = load_global_inventory_store(game_id, root)
    item = next((candidate for candidate in inventory.items if candidate.item_id == item_id), None)
    if item is None:
        raise ValueError(f"unknown inventory item_id: {item_id}")
    references = [
        f"{store.agent_id}/{loadout.loadout_id}/{position}"
        for store in load_agent_loadout_stores(game_id, root)
        for loadout in store.loadouts
        for position, equipped_id in loadout.slot_items.items()
        if equipped_id == item_id
    ]
    if references:
        raise ValueError(
            f"cannot delete inventory item_id {item_id}; referenced by {', '.join(references)}"
        )
    inventory.items = [candidate for candidate in inventory.items if candidate.item_id != item_id]
    save_global_inventory_store(inventory, root)
    return item
