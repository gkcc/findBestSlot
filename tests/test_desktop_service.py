import io
import json
from pathlib import Path

from gear_optimizer.agents import GlobalInventoryStore, save_global_inventory_store
from gear_optimizer.desktop_backend import serve_stream
from gear_optimizer.desktop_protocol import DesktopRequest
from gear_optimizer.desktop_service import DesktopService, load_desktop_workspace
from gear_optimizer.game_rules import load_game
from gear_optimizer.inventory_service import add_inventory_piece
from gear_optimizer.models import GearPiece


BILLY_AGENT_ID = "zzz_starlight_billy"
EMPTY_AGENT_ID = "zzz_ye_shunguang"


def _piece(position_index: int) -> GearPiece:
    game = load_game("zzz")
    position = game.positions[position_index]
    return GearPiece(
        position=position.id,
        set_name=game.sets_for_position(position.id)[0],
        main_stat=position.main_stats[0],
    )


def _canonical_inventory(tmp_path: Path) -> list[str]:
    save_global_inventory_store(GlobalInventoryStore(game="zzz"), tmp_path)
    return [
        add_inventory_piece("zzz", _piece(0), tmp_path).item_id,
        add_inventory_piece("zzz", _piece(1), tmp_path).item_id,
    ]


def _request(method: str, **params) -> DesktopRequest:
    return DesktopRequest(request_id=f"request-{method}", method=method, params=params)


def test_workspace_inventory_is_game_global_when_switching_agents(tmp_path: Path):
    expected_ids = set(_canonical_inventory(tmp_path))

    billy = load_desktop_workspace("zzz", BILLY_AGENT_ID, tmp_path)
    ye = load_desktop_workspace("zzz", EMPTY_AGENT_ID, tmp_path)

    assert {item.item_id for item in billy.inventory} == expected_ids
    assert {item.item_id for item in ye.inventory} == expected_ids
    assert all(item.status == "backpack" for item in billy.inventory)
    assert billy.agent_id != ye.agent_id


def test_equip_and_unequip_keep_one_global_inventory_item(tmp_path: Path):
    item_id = _canonical_inventory(tmp_path)[0]
    service = DesktopService(tmp_path)

    equipped = service.execute(
        _request(
            "loadout.equip",
            game_id="zzz",
            agent_id=BILLY_AGENT_ID,
            item_id=item_id,
        )
    )

    assert equipped.ok
    workspace = equipped.data["workspace"]
    assert len(workspace["inventory"]) == 2
    row = next(item for item in workspace["inventory"] if item["item_id"] == item_id)
    assert row["status"] == "equipped"
    assert row["equipped_by"]["agent_id"] == BILLY_AGENT_ID
    slot = next(
        slot
        for slot in workspace["current_loadout"]["slots"]
        if slot["item_id"] == item_id
    )

    other_agent = load_desktop_workspace("zzz", EMPTY_AGENT_ID, tmp_path)
    other_row = next(item for item in other_agent.inventory if item.item_id == item_id)
    assert other_row.equipped_by is not None
    assert other_row.equipped_by.agent_id == BILLY_AGENT_ID

    unequipped = service.execute(
        _request(
            "loadout.unequip",
            game_id="zzz",
            agent_id=BILLY_AGENT_ID,
            position=slot["position"],
        )
    )

    assert unequipped.ok
    refreshed = unequipped.data["workspace"]
    assert len(refreshed["inventory"]) == 2
    row = next(item for item in refreshed["inventory"] if item["item_id"] == item_id)
    assert row["status"] == "backpack"
    assert row["equipped_by"] is None


def test_workspace_reports_executable_capability_reasons(tmp_path: Path):
    _canonical_inventory(tmp_path)

    billy = load_desktop_workspace("zzz", BILLY_AGENT_ID, tmp_path)
    empty = load_desktop_workspace("zzz", EMPTY_AGENT_ID, tmp_path)

    assert not billy.capabilities["action_ev"].available
    assert "0/6" in billy.capabilities["action_ev"].reason
    assert not empty.capabilities["action_ev"].available
    assert "没有目标模板" in empty.capabilities["action_ev"].reason
    assert empty.capabilities["inventory_write"].available


def test_target_template_selection_is_scoped_to_selected_agent(tmp_path: Path):
    _canonical_inventory(tmp_path)
    service = DesktopService(tmp_path)
    initial = load_desktop_workspace("zzz", BILLY_AGENT_ID, tmp_path)
    template_id = initial.target_templates[0].id

    selected = service.execute(
        _request(
            "target_template.select",
            game_id="zzz",
            agent_id=BILLY_AGENT_ID,
            template_id=template_id,
        )
    )

    assert selected.ok
    assert selected.data["workspace"]["active_target_template_id"] == template_id
    assert load_desktop_workspace(
        "zzz", EMPTY_AGENT_ID, tmp_path
    ).active_target_template_id is None


def test_cross_agent_equip_conflict_is_structured(tmp_path: Path):
    item_id = _canonical_inventory(tmp_path)[0]
    service = DesktopService(tmp_path)
    first = service.execute(
        _request(
            "loadout.equip",
            game_id="zzz",
            agent_id=BILLY_AGENT_ID,
            item_id=item_id,
        )
    )
    assert first.ok

    conflict = service.execute(
        _request(
            "loadout.equip",
            game_id="zzz",
            agent_id=EMPTY_AGENT_ID,
            item_id=item_id,
        )
    )

    assert not conflict.ok
    assert conflict.error is not None
    assert conflict.error.code == "invalid_operation"
    assert BILLY_AGENT_ID in conflict.error.message


def test_desktop_backend_serves_ndjson_and_survives_invalid_json(tmp_path: Path):
    input_stream = io.StringIO(
        "not-json\n"
        + json.dumps(
            {
                "schema_version": 1,
                "request_id": "ping-1",
                "method": "system.ping",
            }
        )
        + "\n"
        + json.dumps(
            {
                "schema_version": 1,
                "request_id": "shutdown-1",
                "method": "system.shutdown",
            }
        )
        + "\n"
    )
    output_stream = io.StringIO()

    assert serve_stream(input_stream, output_stream, root=tmp_path) == 0
    responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]

    assert responses[0]["error"]["code"] == "invalid_json"
    assert responses[1]["data"]["protocol_version"] == 1
    assert responses[2]["data"]["shutdown"] is True
    log_lines = (tmp_path / "logs" / "desktop-backend.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert any('"method": "system.ping"' in line for line in log_lines)
