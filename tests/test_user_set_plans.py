from gear_optimizer.models import SetPlan, SetRequirement
from gear_optimizer.user_set_plans import (
    delete_user_set_plan,
    load_user_set_plans,
    save_user_set_plan,
    set_plan_store_path,
)


def _plan(name: str = "云岿如我 4 + 折枝剑歌 2") -> SetPlan:
    return SetPlan(
        id="ui_custom_4_2",
        name=name,
        requirements=[
            SetRequirement(role="core4", set_name="云岿如我", pieces=4),
            SetRequirement(role="pair2", set_name="折枝剑歌", pieces=2),
        ],
    )


def test_user_set_plan_save_load_and_delete_round_trip(tmp_path):
    saved = save_user_set_plan(
        "zzz",
        "zzz_starlight_billy",
        _plan(),
        root=tmp_path,
    )

    assert saved.id == "user_云岿如我_4_折枝剑歌_2"
    assert set_plan_store_path("zzz", "zzz_starlight_billy", tmp_path).exists()
    assert load_user_set_plans("zzz", "zzz_starlight_billy", tmp_path) == [saved]

    renamed = save_user_set_plan(
        "zzz",
        "zzz_starlight_billy",
        saved,
        name="云岿如我 4 + 折枝剑歌 2 保存版",
        root=tmp_path,
    )
    loaded = load_user_set_plans("zzz", "zzz_starlight_billy", tmp_path)

    assert len(loaded) == 1
    assert loaded[0].id == saved.id
    assert loaded[0].name == renamed.name

    assert delete_user_set_plan("zzz", "zzz_starlight_billy", saved.id, tmp_path)
    assert load_user_set_plans("zzz", "zzz_starlight_billy", tmp_path) == []


def test_user_set_plan_delete_missing_returns_false(tmp_path):
    assert not delete_user_set_plan("zzz", "zzz_starlight_billy", "missing", tmp_path)


def test_user_set_plan_copy_from_saved_plan_uses_new_name_id(tmp_path):
    saved = save_user_set_plan(
        "zzz",
        "zzz_starlight_billy",
        _plan(),
        name="方案 A",
        root=tmp_path,
    )
    copied = save_user_set_plan(
        "zzz",
        "zzz_starlight_billy",
        saved.model_copy(update={"id": f"ui_copy_{saved.id}"}),
        name="方案 B",
        root=tmp_path,
    )

    loaded = load_user_set_plans("zzz", "zzz_starlight_billy", tmp_path)

    assert saved.id == "user_方案_a"
    assert copied.id == "user_方案_b"
    assert {plan.name for plan in loaded} == {"方案 A", "方案 B"}
