import multiprocessing
from pathlib import Path

import pytest

from gear_optimizer.agents import (
    AgentLoadout,
    AgentLoadoutStore,
    GlobalInventoryStore,
    load_agent_loadout_store,
    new_inventory_item,
    save_agent_loadout_store,
    save_global_inventory_store,
)
from gear_optimizer.inventory_service import (
    CanonicalInventoryUnavailableError,
    activate_agent_loadout,
    add_inventory_piece,
    delete_agent_loadout_snapshot,
    delete_inventory_item,
    equip_inventory_item,
    load_agent_loadout_snapshots,
    load_agent_inventory_view,
    rename_agent_loadout_snapshot,
    save_agent_loadout_snapshot,
    unequip_inventory_position,
    update_inventory_piece,
)
from gear_optimizer.models import GearPiece, SubstatLine


GAME_ID = "test_game"
NOW = "2026-07-10T00:00:00+08:00"


def _piece(position: int, *, rolls: int = 0) -> GearPiece:
    return GearPiece(
        position=position,
        set_name="A",
        main_stat="main",
        level=0,
        substats=[SubstatLine(stat="good", rolls=rolls)],
        initial_substat_count=3,
    )


def _equip_from_process(root_text: str, agent_id: str, start, results) -> None:
    if not start.wait(5.0):
        results.put((agent_id, "TimeoutError", "start event timed out"))
        return
    try:
        equip_inventory_item(GAME_ID, agent_id, "inv_3", Path(root_text), now=NOW)
    except Exception as exc:
        results.put((agent_id, type(exc).__name__, str(exc)))
    else:
        results.put((agent_id, "ok", ""))


def _seed_two_agents(tmp_path):
    items = [
        new_inventory_item(_piece(position), item_id=f"inv_{position}", now=NOW)
        for position in (1, 2, 3)
    ]
    save_global_inventory_store(GlobalInventoryStore(game=GAME_ID, items=items), tmp_path)
    save_agent_loadout_store(
        AgentLoadoutStore(
            game=GAME_ID,
            agent_id="agent_a",
            loadouts=[
                AgentLoadout(
                    slot_items={"1": "inv_1"},
                    updated_at=NOW,
                )
            ],
        ),
        tmp_path,
    )
    save_agent_loadout_store(
        AgentLoadoutStore(
            game=GAME_ID,
            agent_id="agent_b",
            loadouts=[
                AgentLoadout(
                    slot_items={"2": "inv_2"},
                    updated_at=NOW,
                )
            ],
        ),
        tmp_path,
    )
    return items


def test_global_backpack_is_invariant_when_switching_agents(tmp_path):
    _seed_two_agents(tmp_path)

    view_a = load_agent_inventory_view(GAME_ID, "agent_a", tmp_path)
    view_b = load_agent_inventory_view(GAME_ID, "agent_b", tmp_path)

    assert [item.item_id for item in view_a.current_items] == ["inv_1"]
    assert [item.item_id for item in view_b.current_items] == ["inv_2"]
    assert [item.item_id for item in view_a.backpack_items] == ["inv_3"]
    assert [item.item_id for item in view_b.backpack_items] == ["inv_3"]


def test_equip_and_unequip_move_item_refs_without_changing_global_inventory(tmp_path):
    items = _seed_two_agents(tmp_path)

    assert equip_inventory_item(GAME_ID, "agent_a", "inv_3", tmp_path, now=NOW) is None
    with pytest.raises(ValueError, match="equipped by agent_a"):
        equip_inventory_item(GAME_ID, "agent_b", "inv_3", tmp_path, now=NOW)

    view_a = load_agent_inventory_view(GAME_ID, "agent_a", tmp_path)
    view_b = load_agent_inventory_view(GAME_ID, "agent_b", tmp_path)
    assert [item.item_id for item in view_a.current_items] == ["inv_1", "inv_3"]
    assert [item.item_id for item in view_b.current_items] == ["inv_2"]
    assert view_a.backpack_items == view_b.backpack_items == tuple()

    assert unequip_inventory_position(GAME_ID, "agent_a", 1, tmp_path, now=NOW) == "inv_1"
    assert [item.item_id for item in load_agent_inventory_view(
        GAME_ID, "agent_b", tmp_path
    ).backpack_items] == ["inv_1"]
    assert [item.item_id for item in items] == ["inv_1", "inv_2", "inv_3"]


def test_two_processes_cannot_equip_the_same_inventory_item(tmp_path):
    _seed_two_agents(tmp_path)
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_equip_from_process,
            args=(str(tmp_path), agent_id, start, results),
        )
        for agent_id in ("agent_a", "agent_b")
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(8.0)
        if process.is_alive():
            process.terminate()
            process.join(5.0)

    assert [process.exitcode for process in processes] == [0, 0]
    outcomes = [results.get(timeout=1.0) for _process in processes]
    assert [outcome[1] for outcome in outcomes].count("ok") == 1
    rejected = next(outcome for outcome in outcomes if outcome[1] != "ok")
    assert rejected[1] == "ValueError"
    assert "equipped by" in rejected[2]
    references = [
        (agent_id, item_id)
        for agent_id in ("agent_a", "agent_b")
        for loadout in load_agent_loadout_store(GAME_ID, agent_id, tmp_path).loadouts
        for item_id in loadout.slot_items.values()
        if item_id == "inv_3"
    ]
    assert len(references) == 1


def test_inventory_mutations_preserve_ids_and_block_referenced_deletion(tmp_path):
    _seed_two_agents(tmp_path)

    with pytest.raises(ValueError, match="referenced by agent_b/default/2"):
        delete_inventory_item(GAME_ID, "inv_2", tmp_path)

    updated = update_inventory_piece(
        GAME_ID,
        "inv_3",
        _piece(3, rolls=2),
        tmp_path,
        now="2026-07-11T00:00:00+08:00",
    )
    added = add_inventory_piece(GAME_ID, _piece(4), tmp_path, now=NOW)
    deleted = delete_inventory_item(GAME_ID, "inv_3", tmp_path)

    assert updated.item_id == "inv_3"
    assert updated.created_at == NOW
    assert updated.piece.substats[0].rolls == 2
    assert added.item_id.startswith("inv_")
    assert deleted.item_id == "inv_3"


def test_canonical_inventory_view_requires_migration(tmp_path):
    with pytest.raises(CanonicalInventoryUnavailableError, match="global inventory does not exist"):
        load_agent_inventory_view(GAME_ID, "agent_a", tmp_path)


def test_loadout_snapshots_store_item_refs_and_switch_active_loadout(tmp_path):
    items = _seed_two_agents(tmp_path)

    saved = save_agent_loadout_snapshot(
        GAME_ID,
        "agent_a",
        "第二套",
        {"1": "inv_1", "3": "inv_3"},
        tmp_path,
        loadout_id="second",
        activate=False,
        now=NOW,
    )
    snapshots = load_agent_loadout_snapshots(GAME_ID, "agent_a", tmp_path)

    assert saved.slot_items == {"1": "inv_1", "3": "inv_3"}
    assert [(snapshot.loadout_id, snapshot.active) for snapshot in snapshots] == [
        ("default", True),
        ("second", False),
    ]
    assert snapshots[1].item_ids == ["inv_1", "inv_3"]

    activate_agent_loadout(GAME_ID, "agent_a", "second", tmp_path)
    view = load_agent_inventory_view(GAME_ID, "agent_a", tmp_path)
    assert [item.item_id for item in view.current_items] == ["inv_1", "inv_3"]
    assert view.backpack_items == tuple()

    renamed = rename_agent_loadout_snapshot(
        GAME_ID,
        "agent_a",
        "second",
        "第二套·改名",
        tmp_path,
        now=NOW,
    )
    assert renamed.loadout_id == "second"
    assert renamed.label == "第二套·改名"

    deleted = delete_agent_loadout_snapshot(
        GAME_ID,
        "agent_a",
        "second",
        tmp_path,
    )
    assert deleted.loadout_id == "second"
    assert [item.item_id for item in load_agent_inventory_view(
        GAME_ID, "agent_a", tmp_path
    ).current_items] == ["inv_1"]
    assert [item.item_id for item in items] == ["inv_1", "inv_2", "inv_3"]


def test_loadout_snapshot_rejects_missing_or_wrong_position_item_refs(tmp_path):
    _seed_two_agents(tmp_path)

    with pytest.raises(ValueError, match="missing inventory item_id"):
        save_agent_loadout_snapshot(
            GAME_ID,
            "agent_a",
            "损坏快照",
            {"3": "missing"},
            tmp_path,
        )
    with pytest.raises(ValueError, match="position does not match"):
        save_agent_loadout_snapshot(
            GAME_ID,
            "agent_a",
            "错位快照",
            {"2": "inv_1"},
            tmp_path,
        )


def test_inactive_snapshot_reference_still_blocks_inventory_deletion(tmp_path):
    _seed_two_agents(tmp_path)
    save_agent_loadout_snapshot(
        GAME_ID,
        "agent_a",
        "备用",
        {"3": "inv_3"},
        tmp_path,
        loadout_id="spare",
        activate=False,
        now=NOW,
    )

    with pytest.raises(ValueError, match="agent_a/spare/3"):
        delete_inventory_item(GAME_ID, "inv_3", tmp_path)


def test_deleting_only_active_snapshot_leaves_empty_agent_without_fake_pieces(tmp_path):
    _seed_two_agents(tmp_path)

    delete_agent_loadout_snapshot(GAME_ID, "agent_a", "default", tmp_path)

    assert load_agent_loadout_snapshots(GAME_ID, "agent_a", tmp_path) == []
    view = load_agent_inventory_view(GAME_ID, "agent_a", tmp_path)
    assert view.current_items == tuple()
    assert [item.item_id for item in view.backpack_items] == ["inv_1", "inv_3"]
