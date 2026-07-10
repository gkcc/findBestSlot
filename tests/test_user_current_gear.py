import yaml

from gear_optimizer.models import GearPiece, SubstatLine
from gear_optimizer.user_current_gear import (
    current_gear_store_path,
    delete_user_current_gear,
    load_user_current_gears,
    save_user_current_gear,
)
from gear_optimizer.user_inventory import (
    legacy_user_inventory_store_path,
    load_user_inventory,
    save_legacy_user_inventory,
    save_user_inventory,
    user_inventory_store_path,
)


def _pieces() -> list[GearPiece]:
    return [
        GearPiece(
            position=1,
            set_name="云岿如我",
            main_stat="生命值",
            level=15,
            substats=[
                SubstatLine(stat="暴击率", rolls=1),
                SubstatLine(stat="暴击伤害", rolls=1),
            ],
        )
    ]


def test_user_current_gear_save_load_and_delete_round_trip(tmp_path):
    saved = save_user_current_gear(
        "zzz",
        "zzz_starlight_billy",
        _pieces(),
        "比利测试盘面",
        root=tmp_path,
    )

    assert saved["id"] == "user_比利测试盘面"
    assert current_gear_store_path("zzz", "zzz_starlight_billy", tmp_path).exists()

    loaded = load_user_current_gears("zzz", "zzz_starlight_billy", tmp_path)
    assert len(loaded) == 1
    assert loaded[0]["label"] == "比利测试盘面"
    assert loaded[0]["pieces"] == _pieces()

    overwritten = save_user_current_gear(
        "zzz",
        "zzz_starlight_billy",
        _pieces(),
        "比利测试盘面",
        root=tmp_path,
    )
    assert overwritten["id"] == saved["id"]
    assert len(load_user_current_gears("zzz", "zzz_starlight_billy", tmp_path)) == 1

    assert delete_user_current_gear("zzz", "zzz_starlight_billy", saved["id"], tmp_path)
    assert load_user_current_gears("zzz", "zzz_starlight_billy", tmp_path) == []
    path = current_gear_store_path("zzz", "zzz_starlight_billy", tmp_path)
    assert not path.exists()
    assert path.with_name(f"{path.name}.bak").exists()


def test_user_current_gear_delete_missing_returns_false(tmp_path):
    assert not delete_user_current_gear(
        "zzz",
        "zzz_starlight_billy",
        "missing",
        tmp_path,
    )


def test_unsupported_revealed_next_substat_is_stripped_from_legacy_user_storage(tmp_path):
    piece_payload = {
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
        "revealed_next_substat": "暴击率",
    }
    inventory_path = user_inventory_store_path("zzz", "zzz_starlight_billy", tmp_path)
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(
        yaml.safe_dump({"pieces": [piece_payload]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    current_path = current_gear_store_path("zzz", "zzz_starlight_billy", tmp_path)
    current_path.parent.mkdir(parents=True, exist_ok=True)
    current_path.write_text(
        yaml.safe_dump(
            {
                "templates": [
                    {
                        "id": "legacy",
                        "label": "旧数据",
                        "pieces": [piece_payload],
                    }
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    inventory = load_user_inventory("zzz", "zzz_starlight_billy", tmp_path)
    current = load_user_current_gears("zzz", "zzz_starlight_billy", tmp_path)

    assert inventory[0].revealed_next_substat is None
    assert current[0]["pieces"][0].revealed_next_substat is None


def test_hsr_revealed_next_substat_roundtrips_in_user_inventory_and_current_gear(tmp_path):
    piece = GearPiece(
        position="body",
        set_name="识海迷坠的学者",
        main_stat="暴击率",
        initial_substat_count=3,
        level=0,
        substats=[
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="攻击力百分比", rolls=0),
            SubstatLine(stat="生命值百分比", rolls=0),
        ],
        revealed_next_substat="速度",
    )

    save_user_inventory("hsr", "hsr_placeholder", [piece], tmp_path)
    save_user_current_gear("hsr", "hsr_placeholder", [piece], "预告词条盘面", tmp_path)

    inventory = load_user_inventory("hsr", "hsr_placeholder", tmp_path)
    current = load_user_current_gears("hsr", "hsr_placeholder", tmp_path)

    assert inventory[0].revealed_next_substat == "速度"
    assert current[0]["pieces"][0].revealed_next_substat == "速度"


def test_user_inventory_is_game_shared_across_agents(tmp_path):
    piece = _pieces()[0]

    billy_path = save_user_inventory("zzz", "zzz_starlight_billy", [piece], tmp_path)
    ye_path = user_inventory_store_path("zzz", "zzz_ye_shunguang", tmp_path)

    assert billy_path == ye_path
    assert billy_path.name == "_shared.yaml"
    assert load_user_inventory("zzz", "zzz_starlight_billy", tmp_path) == [piece]
    assert load_user_inventory("zzz", "zzz_ye_shunguang", tmp_path) == [piece]


def test_user_inventory_merges_legacy_agent_files_until_shared_save_exists(tmp_path):
    first = _pieces()[0]
    second = first.model_copy(update={"position": 2})
    save_legacy_user_inventory("zzz", "zzz_starlight_billy", [first], tmp_path)
    save_legacy_user_inventory("zzz", "zzz_ye_shunguang", [second], tmp_path)

    assert user_inventory_store_path("zzz", "zzz_starlight_billy", tmp_path).name == "_shared.yaml"
    assert legacy_user_inventory_store_path("zzz", "zzz_starlight_billy", tmp_path).name == "zzz_starlight_billy.yaml"
    assert load_user_inventory("zzz", "zzz_starlight_billy", tmp_path) == [first, second]
    assert load_user_inventory("zzz", "zzz_ye_shunguang", tmp_path) == [second, first]

    save_user_inventory("zzz", "zzz_starlight_billy", [first], tmp_path)

    assert load_user_inventory("zzz", "zzz_ye_shunguang", tmp_path) == [first]


def test_invalid_hsr_revealed_next_substat_is_stripped_from_legacy_user_storage(tmp_path):
    repeated_existing_payload = {
        "position": "body",
        "set_name": "识海迷坠的学者",
        "main_stat": "暴击率",
        "initial_substat_count": 3,
        "level": 0,
        "substats": [
            {"stat": "暴击伤害", "rolls": 0},
            {"stat": "攻击力百分比", "rolls": 0},
            {"stat": "生命值百分比", "rolls": 0},
        ],
        "revealed_next_substat": "暴击伤害",
    }
    repeated_main_payload = {
        **repeated_existing_payload,
        "revealed_next_substat": "暴击率",
    }
    inventory_path = user_inventory_store_path("hsr", "hsr_placeholder", tmp_path)
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(
        yaml.safe_dump({"pieces": [repeated_existing_payload]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    current_path = current_gear_store_path("hsr", "hsr_placeholder", tmp_path)
    current_path.parent.mkdir(parents=True, exist_ok=True)
    current_path.write_text(
        yaml.safe_dump(
            {
                "templates": [
                    {
                        "id": "legacy",
                        "label": "旧数据",
                        "pieces": [repeated_main_payload],
                    }
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    inventory = load_user_inventory("hsr", "hsr_placeholder", tmp_path)
    current = load_user_current_gears("hsr", "hsr_placeholder", tmp_path)

    assert inventory[0].revealed_next_substat is None
    assert current[0]["pieces"][0].revealed_next_substat is None

