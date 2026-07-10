import hashlib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import gear_optimizer.agents as agents
from gear_optimizer.agents import (
    AgentCatalog,
    AgentLoadout,
    AgentLoadoutStore,
    AgentMetadata,
    AgentUserState,
    AgentUserStateStore,
    GlobalInventoryStore,
    InventoryItem,
    agent_loadout_store_path,
    agent_metadata_with_fallbacks,
    agent_user_state_store_path,
    apply_multi_agent_migration,
    dry_run_multi_agent_migration,
    expand_agent_loadout,
    global_inventory_store_path,
    load_agent_loadout_store,
    load_agent_user_state_store,
    load_global_inventory_store,
    load_inventory_items_compatible,
    loadout_reference_issues,
    migration_report_json,
    migration_report_markdown,
    missing_agent_asset_issues,
    new_inventory_item,
    save_agent_loadout_store,
    save_agent_user_state_store,
    save_global_inventory_store,
    split_current_and_inventory_for_agent,
    filter_agent_metadata,
    sort_agent_metadata,
)
from gear_optimizer.models import CharacterPreset, GearPiece, SubstatLine, SubstatPriority
from gear_optimizer.storage_io import StoreRevisionConflictError
from gear_optimizer.user_current_gear import current_gear_store_path, save_user_current_gear
from gear_optimizer.user_inventory import save_legacy_user_inventory, save_user_inventory


GAME_ID = "test_game"
CHARACTER_ID = "test_char"


def _character() -> CharacterPreset:
    return CharacterPreset(
        id=CHARACTER_ID,
        game=GAME_ID,
        name="测试代理人",
        target_set="A",
        substat_priority=SubstatPriority(core=["crit"], usable=["dmg"]),
    )


def _piece(
    position: int = 1,
    *,
    set_name: str = "A",
    main_stat: str = "hp",
    substats: list[SubstatLine] | None = None,
    level: int = 0,
) -> GearPiece:
    return GearPiece(
        position=position,
        set_name=set_name,
        main_stat=main_stat,
        level=level,
        substats=substats
        if substats is not None
        else [SubstatLine(stat="crit", rolls=0), SubstatLine(stat="dmg", rolls=0)],
        initial_substat_count=4,
    )


def _patch_migration_configs(monkeypatch):
    monkeypatch.setattr(agents, "load_characters", lambda game_id: [_character()])
    monkeypatch.setattr(
        agents,
        "load_agent_catalog",
        lambda game_id, project_root=agents.PROJECT_ROOT: AgentCatalog(game=game_id, agents=[]),
    )


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_agent_schemas_save_load_and_fallbacks(tmp_path):
    character = _character()
    fallback = AgentMetadata.fallback_for_character(character)

    assert fallback.agent_id == "fallback_test_char"
    assert fallback.name == "测试代理人"
    assert fallback.rarity == "未知"
    assert fallback.portrait_path is None
    assert agent_metadata_with_fallbacks(
        GAME_ID,
        [character],
        AgentCatalog(game=GAME_ID, agents=[]),
    ) == [fallback]

    with pytest.raises(ValidationError):
        AgentMetadata(
            agent_id="remote",
            name="Remote",
            character_preset_id=CHARACTER_ID,
            portrait_path="https://example.com/portrait.png",
        )
    missing_asset_agent = AgentMetadata(
        agent_id="missing_asset",
        name="Missing",
        character_preset_id=CHARACTER_ID,
        portrait_path="assets/missing.png",
    )
    assert missing_agent_asset_issues([missing_asset_agent], tmp_path)[0].code == "agent_asset_missing"

    user_state = AgentUserStateStore(
        game=GAME_ID,
        agents={"agent": AgentUserState(owned=True, level=60, favorite=True)},
    )
    save_agent_user_state_store(user_state, tmp_path)
    assert agent_user_state_store_path(GAME_ID, tmp_path).exists()
    assert load_agent_user_state_store(GAME_ID, tmp_path) == user_state

    assert load_agent_user_state_store("missing", tmp_path) == AgentUserStateStore(game="missing")


def test_unknown_legacy_character_uses_safe_fallback_agent_id():
    agent = agents._agent_for_character("Missing Character!", {}, {})

    assert agent.agent_id == "fallback_missing_character"
    assert agent.character_preset_id == "Missing Character!"


def test_project_agent_catalogs_match_character_presets():
    for game_id in ["hsr", "zzz"]:
        catalog = agents.load_agent_catalog(game_id)
        characters = agents.load_characters(game_id)
        character_ids = {character.id for character in characters}

        assert catalog.game == game_id
        assert catalog.agents
        assert {
            agent.character_preset_id
            for agent in catalog.agents
            if agent.character_preset_id
        }.issubset(character_ids)
        assert len(agent_metadata_with_fallbacks(game_id, characters, catalog)) >= len(characters)

    hsr_catalog = agents.load_agent_catalog("hsr")
    assert len(hsr_catalog.agents) >= 80
    assert hsr_catalog.agents == sort_agent_metadata(hsr_catalog.agents)
    assert hsr_catalog.agents[0].release_order >= hsr_catalog.agents[-1].release_order
    assert {agent.attribute for agent in hsr_catalog.agents}.issuperset({"火", "冰", "雷", "量子", "虚数"})
    assert {agent.specialty for agent in hsr_catalog.agents}.issuperset({"毁灭", "巡猎", "智识", "同谐", "虚无", "存护", "丰饶", "记忆"})
    assert not any(agent.name == "崩铁通用暴击模板" for agent in hsr_catalog.agents)
    assert all(agent.portrait_path for agent in hsr_catalog.agents)
    assert all(agent.card_path for agent in hsr_catalog.agents)
    for agent in hsr_catalog.agents[:8]:
        assert (agents.PROJECT_ROOT / agent.portrait_path).exists()
        assert (agents.PROJECT_ROOT / agent.card_path).exists()

    zzz_catalog = agents.load_agent_catalog("zzz")
    assert len(zzz_catalog.agents) >= 50
    assert zzz_catalog.agents == sort_agent_metadata(zzz_catalog.agents)
    assert zzz_catalog.agents[0].release_order >= zzz_catalog.agents[-1].release_order
    assert {agent.attribute for agent in zzz_catalog.agents}.issuperset({"火", "冰", "电", "物理", "以太", "风"})
    assert {agent.specialty for agent in zzz_catalog.agents}.issuperset({"强攻", "击破", "支援", "异常", "防护", "命破"})
    assert not any(agent.name == "异常代理人模板" for agent in zzz_catalog.agents)
    assert any(agent.agent_id == "zzz_starlight_billy" and agent.name == "星徽·比利" for agent in zzz_catalog.agents)
    assert next(agent for agent in zzz_catalog.agents if agent.agent_id == "zzz_ye_shunguang").character_preset_id == ""
    assert not any(agent.character_preset_id == "zzz_template_anomaly" for agent in zzz_catalog.agents)
    assert all(agent.portrait_path for agent in zzz_catalog.agents)
    assert all(agent.card_path for agent in zzz_catalog.agents)
    for agent in zzz_catalog.agents[:8]:
        assert (agents.PROJECT_ROOT / agent.portrait_path).exists()
        assert (agents.PROJECT_ROOT / agent.card_path).exists()


def test_agent_catalog_filtering_uses_real_agent_fields():
    hsr_agents = agents.load_agent_catalog("hsr").agents
    zzz_agents = agents.load_agent_catalog("zzz").agents

    fire_agents = filter_agent_metadata(hsr_agents, attribute="火")
    nihility_agents = filter_agent_metadata(hsr_agents, specialty="虚无")
    blade_agents = filter_agent_metadata(hsr_agents, text="刃")
    physical_agents = filter_agent_metadata(zzz_agents, attribute="物理")
    rupture_agents = filter_agent_metadata(zzz_agents, specialty="命破")
    billy_agents = filter_agent_metadata(zzz_agents, text="比利")

    assert fire_agents
    assert all(agent.attribute == "火" for agent in fire_agents)
    assert nihility_agents
    assert all(agent.specialty == "虚无" for agent in nihility_agents)
    assert any("刃" in agent.name for agent in blade_agents)
    assert fire_agents == sort_agent_metadata(fire_agents)
    assert physical_agents
    assert all(agent.attribute == "物理" for agent in physical_agents)
    assert rupture_agents
    assert all(agent.specialty == "命破" for agent in rupture_agents)
    assert {agent.name for agent in billy_agents}.issuperset({"星徽·比利", "比利"})
    assert physical_agents == sort_agent_metadata(physical_agents)


def test_inventory_item_id_is_stable_after_round_trip(tmp_path):
    item = new_inventory_item(_piece(), now="2026-07-04T00:00:00+08:00")
    store = GlobalInventoryStore(game=GAME_ID, items=[item])

    save_global_inventory_store(store, tmp_path)
    loaded = load_global_inventory_store(GAME_ID, tmp_path)

    assert item.item_id.startswith("inv_")
    assert loaded.items[0].item_id == item.item_id
    assert loaded.items[0].piece == item.piece


def test_global_inventory_store_rejects_stale_model_save(tmp_path):
    store = GlobalInventoryStore(game=GAME_ID)
    save_global_inventory_store(store, tmp_path)
    first_writer = load_global_inventory_store(GAME_ID, tmp_path)
    stale_writer = load_global_inventory_store(GAME_ID, tmp_path)
    first_writer.items.append(new_inventory_item(_piece(position=1), item_id="first"))
    stale_writer.items.append(new_inventory_item(_piece(position=2), item_id="stale"))

    save_global_inventory_store(first_writer, tmp_path)
    with pytest.raises(StoreRevisionConflictError, match="重新载入"):
        save_global_inventory_store(stale_writer, tmp_path)

    loaded = load_global_inventory_store(GAME_ID, tmp_path)
    assert loaded.revision == 2
    assert [item.item_id for item in loaded.items] == ["first"]


def test_agent_loadout_stores_only_item_ids_and_expands_from_global_inventory(tmp_path):
    item1 = new_inventory_item(_piece(position=1), item_id="inv_one", now="2026-07-04T00:00:00+08:00")
    item2 = new_inventory_item(_piece(position=2), item_id="inv_two", now="2026-07-04T00:00:00+08:00")
    inventory = GlobalInventoryStore(game=GAME_ID, items=[item1, item2])
    loadout = AgentLoadoutStore(
        game=GAME_ID,
        agent_id="agent_a",
        loadouts=[
            AgentLoadout(
                loadout_id="default",
                slot_items={"1": item1.item_id, "2": None},
                updated_at="2026-07-04T00:00:00+08:00",
            )
        ],
    )

    save_global_inventory_store(inventory, tmp_path)
    save_agent_loadout_store(loadout, tmp_path)

    raw_loadout = yaml.safe_load(agent_loadout_store_path(GAME_ID, "agent_a", tmp_path).read_text(encoding="utf-8"))
    assert raw_loadout["loadouts"][0]["slot_items"] == {"1": "inv_one", "2": None}
    assert "piece" not in yaml.safe_dump(raw_loadout["loadouts"][0], allow_unicode=True)
    assert load_agent_loadout_store(GAME_ID, "agent_a", tmp_path) == loadout
    assert expand_agent_loadout(inventory, loadout) == [item1.piece]
    current, backpack = split_current_and_inventory_for_agent(inventory, loadout)
    assert current == [item1.piece]
    assert backpack == [item2.piece]

    broken = AgentLoadoutStore(
        game=GAME_ID,
        agent_id="agent_a",
        loadouts=[
            AgentLoadout(
                slot_items={"1": "missing"},
                updated_at="2026-07-04T00:00:00+08:00",
            )
        ],
    )
    with pytest.raises(ValueError, match="missing inventory item_id"):
        expand_agent_loadout(inventory, broken)


def test_legacy_inventory_compatible_view_switches_to_global_when_present(tmp_path):
    legacy_piece = _piece(position=1)
    global_piece = _piece(position=2)
    save_user_inventory(GAME_ID, CHARACTER_ID, [legacy_piece], tmp_path)

    legacy_items = load_inventory_items_compatible(GAME_ID, CHARACTER_ID, tmp_path)
    assert len(legacy_items) == 1
    assert legacy_items[0].piece == legacy_piece
    assert legacy_items[0].item_id.startswith("mig_")

    global_item = new_inventory_item(
        global_piece,
        item_id="inv_global",
        now="2026-07-04T00:00:00+08:00",
    )
    save_global_inventory_store(GlobalInventoryStore(game=GAME_ID, items=[global_item]), tmp_path)

    assert load_inventory_items_compatible(GAME_ID, CHARACTER_ID, tmp_path) == [global_item]


def test_shared_inventory_compatible_ids_do_not_depend_on_selected_agent(tmp_path):
    piece = _piece(position=1)
    save_user_inventory(GAME_ID, "agent_a", [piece], tmp_path)

    agent_a_items = load_inventory_items_compatible(GAME_ID, "agent_a", tmp_path)
    agent_b_items = load_inventory_items_compatible(GAME_ID, "agent_b", tmp_path)

    assert [item.piece for item in agent_a_items] == [piece]
    assert [item.item_id for item in agent_a_items] == [item.item_id for item in agent_b_items]


def test_dry_run_migration_includes_shared_inventory(monkeypatch, tmp_path):
    _patch_migration_configs(monkeypatch)
    shared_piece = _piece(position=1)
    current_piece = _piece(position=2)
    save_user_inventory(GAME_ID, CHARACTER_ID, [shared_piece], tmp_path)
    save_user_current_gear(GAME_ID, CHARACTER_ID, [current_piece], "当前装备", tmp_path)

    report = dry_run_multi_agent_migration(
        GAME_ID,
        root=tmp_path,
        now="2026-07-04T00:00:00+08:00",
    )

    assert len(report.inventory_items) == 2
    assert f"inventory/{GAME_ID}/_shared.yaml" in report.legacy_inventory_files
    assert any(
        item.migrated_from and item.migrated_from.get("kind") == "shared_inventory"
        for item in report.inventory_items
    )


def test_shared_inventory_shadows_legacy_agent_files_during_migration(monkeypatch, tmp_path):
    _patch_migration_configs(monkeypatch)
    shared_piece = _piece(position=1)
    stale_legacy_piece = _piece(position=2)
    save_user_inventory(GAME_ID, CHARACTER_ID, [shared_piece], tmp_path)
    save_legacy_user_inventory(
        GAME_ID,
        CHARACTER_ID,
        [stale_legacy_piece],
        tmp_path,
    )

    report = dry_run_multi_agent_migration(GAME_ID, root=tmp_path)

    assert [item.piece for item in report.inventory_items] == [shared_piece]
    assert "legacy_agent_inventory_shadowed_by_shared" in {
        issue.code for issue in report.issues
    }
    assert f"inventory/{GAME_ID}/_shared.yaml" in report.legacy_inventory_files
    assert f"inventory/{GAME_ID}/{CHARACTER_ID}.yaml" in report.legacy_inventory_files


def test_migration_resolves_current_gear_owner_by_agent_id(monkeypatch, tmp_path):
    metadata = AgentMetadata(
        agent_id="agent_owner",
        name="正式代理人",
        character_preset_id="",
    )
    monkeypatch.setattr(agents, "load_characters", lambda _game_id: [])
    monkeypatch.setattr(
        agents,
        "load_agent_catalog",
        lambda game_id, project_root=agents.PROJECT_ROOT: AgentCatalog(
            game=game_id,
            agents=[metadata],
        ),
    )
    save_user_current_gear(GAME_ID, "agent_owner", [_piece(position=1)], "当前装备", tmp_path)

    report = dry_run_multi_agent_migration(
        GAME_ID,
        root=tmp_path,
        now="2026-07-10T00:00:00+08:00",
    )

    assert [store.agent_id for store in report.loadout_stores] == ["agent_owner"]
    assert "agent_metadata_missing" not in {issue.code for issue in report.issues}
    assert "character_preset_missing" not in {issue.code for issue in report.issues}


def test_dry_run_migration_reports_duplicates_and_does_not_modify_files(monkeypatch, tmp_path):
    _patch_migration_configs(monkeypatch)
    exact_piece = _piece(position=1)
    reversed_substats_piece = _piece(
        position=1,
        substats=[SubstatLine(stat="dmg", rolls=0), SubstatLine(stat="crit", rolls=0)],
    )
    save_legacy_user_inventory(
        GAME_ID,
        CHARACTER_ID,
        [exact_piece, exact_piece, reversed_substats_piece],
        tmp_path,
    )
    save_user_current_gear(GAME_ID, CHARACTER_ID, [exact_piece], "当前装备", tmp_path)
    inventory_path = tmp_path / "inventory" / GAME_ID / f"{CHARACTER_ID}.yaml"
    current_path = current_gear_store_path(GAME_ID, CHARACTER_ID, tmp_path)
    before = {inventory_path: _hash_file(inventory_path), current_path: _hash_file(current_path)}

    report = dry_run_multi_agent_migration(
        GAME_ID,
        root=tmp_path,
        now="2026-07-04T00:00:00+08:00",
    )

    assert report.dry_run
    assert len(report.inventory_items) == 3
    assert sum(len(store.loadouts) for store in report.loadout_stores) == 1
    assert {path: _hash_file(path) for path in before} == before
    assert any(group.count == 2 for group in report.exact_duplicate_groups)
    assert any(group.count == 3 for group in report.unordered_duplicate_groups)
    assert "agent_metadata_missing" in {issue.code for issue in report.issues}
    assert "dry-run" in migration_report_markdown(report)
    assert '"dry_run": true' in migration_report_json(report)


def test_apply_migration_creates_global_inventory_loadouts_and_backup(monkeypatch, tmp_path):
    _patch_migration_configs(monkeypatch)
    inventory_piece = _piece(position=1)
    current_piece = _piece(position=2)
    save_legacy_user_inventory(GAME_ID, CHARACTER_ID, [inventory_piece], tmp_path)
    save_user_current_gear(GAME_ID, CHARACTER_ID, [current_piece], "当前装备", tmp_path)
    legacy_inventory_path = tmp_path / "inventory" / GAME_ID / f"{CHARACTER_ID}.yaml"
    legacy_current_path = current_gear_store_path(GAME_ID, CHARACTER_ID, tmp_path)

    report = apply_multi_agent_migration(
        GAME_ID,
        root=tmp_path,
        now="2026-07-04T00:00:00+08:00",
    )

    assert not report.dry_run
    assert report.backup_path
    assert global_inventory_store_path(GAME_ID, tmp_path).exists()
    assert agent_loadout_store_path(GAME_ID, "fallback_test_char", tmp_path).exists()
    assert legacy_inventory_path.exists()
    assert legacy_current_path.exists()
    assert (tmp_path / report.backup_path / "inventory" / GAME_ID / f"{CHARACTER_ID}.yaml").exists()
    assert (tmp_path / report.backup_path / "current_gear" / GAME_ID / f"{CHARACTER_ID}.yaml").exists()

    loaded_inventory = load_global_inventory_store(GAME_ID, tmp_path)
    loaded_loadout = load_agent_loadout_store(GAME_ID, "fallback_test_char", tmp_path)
    assert len(loaded_inventory.items) == 2
    assert len(loaded_loadout.loadouts) == 1
    assert expand_agent_loadout(loaded_inventory, loaded_loadout) == [current_piece]


def test_migration_preserves_existing_global_inventory_and_is_idempotent(monkeypatch, tmp_path):
    _patch_migration_configs(monkeypatch)
    existing_item = new_inventory_item(
        _piece(position=1),
        item_id="inv_existing",
        now="2026-07-04T00:00:00+08:00",
    )
    save_global_inventory_store(
        GlobalInventoryStore(game=GAME_ID, items=[existing_item]),
        tmp_path,
    )
    save_user_inventory(GAME_ID, CHARACTER_ID, [_piece(position=3)], tmp_path)
    save_user_current_gear(
        GAME_ID,
        CHARACTER_ID,
        [_piece(position=2)],
        "当前装备",
        tmp_path,
    )

    first = apply_multi_agent_migration(
        GAME_ID,
        root=tmp_path,
        now="2026-07-04T00:00:00+08:00",
    )
    first_ids = [item.item_id for item in load_global_inventory_store(GAME_ID, tmp_path).items]
    second = apply_multi_agent_migration(
        GAME_ID,
        root=tmp_path,
        now="2026-07-05T00:00:00+08:00",
    )
    second_ids = [item.item_id for item in load_global_inventory_store(GAME_ID, tmp_path).items]

    assert first_ids == second_ids
    assert first_ids[0] == "inv_existing"
    assert len(first_ids) == 2
    assert "legacy_inventory_shadowed_by_global" in {issue.code for issue in first.issues}
    assert "legacy_inventory_shadowed_by_global" in {issue.code for issue in second.issues}


def test_loadout_conflict_reporting_allows_shared_item_but_blocks_missing_reference():
    item = InventoryItem(
        item_id="inv_shared",
        piece=_piece(position=1),
        created_at="2026-07-04T00:00:00+08:00",
        updated_at="2026-07-04T00:00:00+08:00",
    )
    inventory = GlobalInventoryStore(game=GAME_ID, items=[item])
    store_a = AgentLoadoutStore(
        game=GAME_ID,
        agent_id="agent_a",
        loadouts=[
            AgentLoadout(
                slot_items={"1": item.item_id},
                updated_at="2026-07-04T00:00:00+08:00",
            )
        ],
    )
    store_b = AgentLoadoutStore(
        game=GAME_ID,
        agent_id="agent_b",
        loadouts=[
            AgentLoadout(
                slot_items={"1": item.item_id, "2": "missing"},
                updated_at="2026-07-04T00:00:00+08:00",
            )
        ],
    )

    issues = loadout_reference_issues(inventory, [store_a, store_b])

    by_code = {issue.code: issue for issue in issues}
    assert by_code["shared_equipment_conflict"].severity == "warning"
    assert by_code["loadout_item_missing"].severity == "error"


def test_migration_reports_loadout_slot_conflicts(monkeypatch, tmp_path):
    _patch_migration_configs(monkeypatch)
    path = current_gear_store_path(GAME_ID, CHARACTER_ID, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "game": GAME_ID,
                "character": CHARACTER_ID,
                "templates": [
                    {
                        "id": "default",
                        "label": "冲突盘面",
                        "pieces": [
                            _piece(position=1).model_dump(mode="json"),
                            _piece(position=1, set_name="B").model_dump(mode="json"),
                        ],
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = dry_run_multi_agent_migration(
        GAME_ID,
        root=tmp_path,
        now="2026-07-04T00:00:00+08:00",
    )

    assert "loadout_slot_conflict" in {issue.code for issue in report.issues}
    assert report.blocking_issues


def test_migration_current_gear_loader_strips_unsupported_revealed_next_substat(tmp_path):
    path = current_gear_store_path("zzz", "zzz_starlight_billy", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "templates": [
                    {
                        "id": "legacy",
                        "label": "旧盘面",
                        "pieces": [
                            {
                                "position": 5,
                                "set_name": "云岿如我",
                                "main_stat": "物理伤害",
                                "initial_substat_count": 3,
                                "level": 0,
                                "substats": [
                                    {"stat": "暴击率", "rolls": 0},
                                    {"stat": "暴击伤害", "rolls": 0},
                                    {"stat": "攻击力百分比", "rolls": 0},
                                ],
                                "revealed_next_substat": "生命值百分比",
                            }
                        ],
                    }
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    templates = agents._load_current_file_templates(path, "zzz")

    assert templates[0]["pieces"][0].revealed_next_substat is None


def test_migration_piece_signature_and_item_id_include_revealed_next_substat():
    base = GearPiece(
        position=1,
        set_name="A",
        main_stat="hp",
        level=0,
        initial_substat_count=3,
        substats=[
            SubstatLine(stat="crit", rolls=0),
            SubstatLine(stat="dmg", rolls=0),
            SubstatLine(stat="atk", rolls=0),
        ],
    )
    speed_reveal = base.model_copy(update={"revealed_next_substat": "spd"})
    break_reveal = base.model_copy(update={"revealed_next_substat": "break"})

    assert agents._piece_signature(speed_reveal) != agents._piece_signature(break_reveal)
    assert agents._piece_signature(speed_reveal, unordered_substats=True) != agents._piece_signature(
        break_reveal,
        unordered_substats=True,
    )
    assert agents._stable_migration_item_id("legacy.yaml", "1", speed_reveal) != agents._stable_migration_item_id(
        "legacy.yaml",
        "1",
        break_reveal,
    )


def test_duplicate_item_id_is_rejected():
    item = new_inventory_item(
        _piece(),
        item_id="duplicate",
        now="2026-07-04T00:00:00+08:00",
    )

    with pytest.raises(ValidationError, match="duplicate item_id"):
        GlobalInventoryStore(game=GAME_ID, items=[item, item])
