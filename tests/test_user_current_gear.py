from gear_optimizer.models import GearPiece, SubstatLine
from gear_optimizer.user_current_gear import (
    current_gear_store_path,
    delete_user_current_gear,
    load_user_current_gears,
    save_user_current_gear,
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


def test_user_current_gear_delete_missing_returns_false(tmp_path):
    assert not delete_user_current_gear(
        "zzz",
        "zzz_starlight_billy",
        "missing",
        tmp_path,
    )

