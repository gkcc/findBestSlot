from gear_optimizer.models import CharacterPreset, SetPlan, SetRequirement, SubstatPriority
from gear_optimizer.user_target_templates import (
    delete_user_target_template,
    hide_builtin_target_template,
    load_hidden_builtin_target_template_ids,
    load_user_target_template_source_agents,
    load_user_target_template_sources,
    load_user_target_templates,
    save_user_target_template,
    target_template_store_path,
    unhide_builtin_target_template,
)


def _preset() -> CharacterPreset:
    return CharacterPreset(
        id="base",
        game="zzz",
        name="基础目标",
        target_set="A",
        substat_priority=SubstatPriority(core=[["crit", "cdmg"], "atk"], usable=[]),
        preferred_main_stats={"4": ["crit", "cdmg"], "5": ["dmg"]},
        set_plans=[
            SetPlan(
                id="a4_b2",
                name="A4+B2",
                requirements=[
                    SetRequirement(set_name="A", pieces=4),
                    SetRequirement(set_name="B", pieces=2),
                ],
            )
        ],
        default_set_plan="a4_b2",
    )


def test_user_target_templates_roundtrip_and_delete(tmp_path):
    saved = save_user_target_template(
        "zzz",
        _preset(),
        "暴击目标",
        source_character_id="base",
        source_agent_id="agent_base",
        root=tmp_path,
    )

    assert saved.id.startswith("user_")
    assert target_template_store_path("zzz", tmp_path).exists()

    loaded = load_user_target_templates("zzz", tmp_path)

    assert [item.id for item in loaded] == [saved.id]
    assert loaded[0].preferred_mains_for("4") == ["crit", "cdmg"]
    assert loaded[0].active_set_plan().requirements[0].pieces == 4
    assert loaded[0].priority_tiers() == [["crit", "cdmg"], ["atk"]]
    assert load_user_target_template_sources("zzz", tmp_path) == {saved.id: "base"}
    assert load_user_target_template_source_agents("zzz", tmp_path) == {saved.id: "agent_base"}

    assert delete_user_target_template("zzz", saved.id, tmp_path)
    assert load_user_target_templates("zzz", tmp_path) == []
    assert load_user_target_template_source_agents("zzz", tmp_path) == {}


def test_user_target_template_id_includes_source_to_avoid_same_label_collision(tmp_path):
    saved_a = save_user_target_template(
        "zzz",
        _preset(),
        "同名目标",
        source_character_id="base",
        source_agent_id="agent_a",
        root=tmp_path,
    )
    saved_b = save_user_target_template(
        "zzz",
        _preset(),
        "同名目标",
        source_character_id="base",
        source_agent_id="agent_b",
        root=tmp_path,
    )
    renamed_a = save_user_target_template(
        "zzz",
        saved_a,
        "同名目标",
        root=tmp_path,
    )

    loaded = load_user_target_templates("zzz", tmp_path)

    assert saved_a.id == renamed_a.id
    assert saved_a.id != saved_b.id
    assert saved_a.id.startswith("user_agent_a_")
    assert saved_b.id.startswith("user_agent_b_")
    assert sorted(item.id for item in loaded) == sorted([saved_a.id, saved_b.id])
    assert load_user_target_template_source_agents("zzz", tmp_path) == {
        saved_a.id: "agent_a",
        saved_b.id: "agent_b",
    }


def test_user_target_template_can_clear_stale_source_character(tmp_path):
    saved = save_user_target_template(
        "zzz",
        _preset(),
        "旧来源目标",
        source_character_id="removed_builtin",
        source_agent_id="agent_a",
        root=tmp_path,
    )

    resaved = save_user_target_template(
        "zzz",
        saved.model_copy(update={"name": "旧来源目标"}),
        "旧来源目标",
        source_character_id="",
        source_agent_id="agent_a",
        root=tmp_path,
    )

    assert resaved.id == saved.id
    assert load_user_target_template_sources("zzz", tmp_path) == {}
    assert load_user_target_template_source_agents("zzz", tmp_path) == {saved.id: "agent_a"}


def test_hidden_builtin_target_templates_survive_user_template_changes(tmp_path):
    hidden_id = "zzz_removed_builtin_for_test"
    assert hide_builtin_target_template("zzz", hidden_id, tmp_path)
    assert load_hidden_builtin_target_template_ids("zzz", tmp_path) == {hidden_id}

    saved = save_user_target_template(
        "zzz",
        _preset(),
        "隐藏后新增目标",
        source_character_id="base",
        root=tmp_path,
    )
    assert load_hidden_builtin_target_template_ids("zzz", tmp_path) == {hidden_id}

    assert delete_user_target_template("zzz", saved.id, tmp_path)
    assert load_user_target_templates("zzz", tmp_path) == []
    assert load_hidden_builtin_target_template_ids("zzz", tmp_path) == {hidden_id}

    assert unhide_builtin_target_template("zzz", hidden_id, tmp_path)
    assert load_hidden_builtin_target_template_ids("zzz", tmp_path) == set()
