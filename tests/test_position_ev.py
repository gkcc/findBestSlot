from collections import defaultdict
from itertools import product

import pytest

from gear_optimizer.game_rules import load_characters, load_game, load_probability_models
from gear_optimizer.position_ev import (
    ActionSpec,
    action_gain_for_spec,
    best_loadout_value,
    immediate_piece_gain,
    _initial_weight_states,
    fixed_main_gain_ladder_rows,
    fixed_substat_gain_ladder_rows,
    fresh_piece_weighted_score_distribution,
    initial_substat_tier_rows,
    option_piece_gain,
    position_strategy_efficiency_rows,
    recommended_action_ev_row,
    resource_marginal_ev_rows,
    lookahead_inventory_value,
    _lookahead_action_specs,
    _set_plan_frontier_action_specs,
    _dominant_generation_action_specs,
    _aggregated_action_outcomes_for_spec,
    _action_outcome_distribution,
    _aggregate_inventory_outcomes,
    _AGGREGATED_ACTION_OUTCOME_CACHE,
    _combo_value,
    _inventory_signature,
    _set_plan_satisfied,
    inventory_rows_from_pieces,
)
from gear_optimizer.presets import load_current_example
from gear_optimizer.presets import load_candidate_example
from gear_optimizer.scoring import analyse_current_gear, substat_quality_vector
from gear_optimizer.models import (
    CharacterPreset,
    EnhancementRule,
    GameRules,
    GearPiece,
    PositionRule,
    ProbabilityModel,
    SetPlan,
    SetRequirement,
    SubstatLine,
    SubstatPriority,
    position_key,
)


def _billy_context():
    game = load_game("zzz")
    character = next(
        item
        for item in load_characters("zzz")
        if item.id == "zzz_starlight_billy"
    )
    probability_model = load_probability_models("zzz")[0]
    analysis = analyse_current_gear(
        load_current_example("examples/zzz_billy_current.yaml"),
        game,
        character,
    )
    return game, character, probability_model, analysis


def _preferred_main(game, character, position: int) -> str:
    preferred = character.preferred_mains_for(str(position))
    return preferred[0] if preferred else game.main_stats_for(position)[0]


def _piece(game, character, position: int, set_name: str, quality: int) -> GearPiece:
    main_stat = _preferred_main(game, character, position)
    stat = "暴击率" if main_stat != "暴击率" else "暴击伤害"
    return GearPiece(
        position=position,
        set_name=set_name,
        main_stat=main_stat,
        level=15,
        substats=[SubstatLine(stat=stat, rolls=max(quality - 1, 0))],
        initial_substat_count=3,
    )


def _legacy_cartesian_best_value(rows, game, character):
    by_position = defaultdict(list)
    for row in rows:
        by_position[position_key(row["position"])].append(row)
    options = [by_position.get(position_key(rule.id), []) for rule in game.positions]
    if any(not item for item in options):
        return tuple()

    combos = [combo for combo in product(*options) if _set_plan_satisfied(combo, character)]
    if not combos:
        combos = list(product(*options))
    return _combo_value(max(combos, key=lambda combo: _combo_value(combo, character)), character)


def _outcome_signature(outcomes):
    return sorted(
        (_inventory_signature(inventory), round(probability, 12))
        for inventory, probability in outcomes
    )


def test_quality_vector_uses_configured_priority_order_without_scalar_weights():
    _game, character, _probability_model, _analysis = _billy_context()
    piece = GearPiece(
        position=4,
        set_name="云岿如我",
        main_stat="异常精通",
        level=15,
        substats=[
            SubstatLine(stat="暴击率", rolls=1),
            SubstatLine(stat="暴击伤害", rolls=0),
            SubstatLine(stat="生命值百分比", rolls=2),
            SubstatLine(stat="攻击力百分比", rolls=5),
        ],
        initial_substat_count=4,
    )

    assert character.substat_priority.core == ["暴击率", "暴击伤害"]
    assert character.substat_priority.usable == ["生命值百分比"]
    assert substat_quality_vector(piece, character) == (3.0, 2.0, 1.0, 3.0, 3.0)


def _tiny_exact_context():
    game = GameRules(
        id="tiny",
        name="Tiny",
        gear_name="Disk",
        sets=["A"],
        positions=[
            PositionRule(id=1, name="1号位", main_stats=["main1"]),
            PositionRule(id=2, name="2号位", main_stats=["main2"]),
        ],
        sub_stats=["a", "b", "c", "d"],
        main_stat_probabilities={
            "1": {"main1": 1.0},
            "2": {"main2": 1.0},
        },
        sub_stat_probabilities={"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0},
        enhancement=EnhancementRule(max_level=0, step=3, initial_add_level=3),
    )
    character = CharacterPreset(
        id="tiny_char",
        game="tiny",
        name="Tiny Char",
        target_set="A",
        substat_priority=SubstatPriority(core=["a", "b", "c", "d"], usable=[]),
        preferred_main_stats={"1": ["main1"], "2": ["main2"]},
        set_plans=[
            SetPlan(
                id="a2",
                name="A 2",
                requirements=[SetRequirement(set_name="A", pieces=2)],
            )
        ],
        default_set_plan="a2",
    )
    probability_model = ProbabilityModel(
        id="tiny_prob",
        game="tiny",
        name="Tiny deterministic",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 0.0, "4": 1.0},
        resource_costs={
            "mother_disk_random_position_attempt": 1.0,
            "mother_disk_fixed_position_attempt": 1.0,
        },
    )
    inventory = [
        GearPiece(position=1, set_name="A", main_stat="main1", level=0, substats=[]),
        GearPiece(position=2, set_name="A", main_stat="main2", level=0, substats=[]),
    ]
    return game, character, probability_model, inventory


def test_initial_unknown_piece_distribution_preserves_probability_mass():
    game, character, _probability_model, _analysis = _billy_context()

    assert sum(_initial_weight_states(game, character, "生命值", 3).values()) == pytest.approx(1.0)
    assert sum(_initial_weight_states(game, character, "生命值", 4).values()) == pytest.approx(1.0)


def test_fresh_piece_distribution_includes_initial_three_and_four_line_outcomes():
    game, character, probability_model, _analysis = _billy_context()

    distribution = fresh_piece_weighted_score_distribution(
        game,
        character,
        probability_model,
        "生命值",
    )

    assert sum(distribution.values()) == pytest.approx(1.0)
    assert sum(score * probability for score, probability in distribution.items()) > 2.5
    assert any(score >= 6.0 for score in distribution)


def test_random_and_fixed_position_gain_resolve_best_combo_actions():
    game, character, probability_model, analysis = _billy_context()

    rows = position_strategy_efficiency_rows(game, character, probability_model, analysis)
    random_row = rows[0]
    fixed_rows = rows[1:]

    assert random_row["策略"] == "随机位置"
    assert random_row["位置"] == "1-6 随机"
    assert {"云岿如我", "折枝剑歌"}.issubset({row["目标套装"] for row in rows})
    assert "排序向量/母盘" in random_row
    assert any(row["位置"] == "6号位" and row["相对随机"] == "优于随机，才建议固定" for row in fixed_rows)
    assert any(row["位置"] == "6号位" and row["有效/母盘"] > 0 for row in fixed_rows)


def test_best_loadout_uses_full_inventory_and_migrates_four_plus_two_positions():
    game, character, _probability_model, _analysis = _billy_context()
    inventory = [
        _piece(game, character, 1, "折枝剑歌", 2),
        _piece(game, character, 2, "云岿如我", 4),
        _piece(game, character, 3, "折枝剑歌", 4),
        _piece(game, character, 4, "云岿如我", 4),
        _piece(game, character, 5, "云岿如我", 4),
        _piece(game, character, 6, "云岿如我", 0),
    ]
    cloud_slot_1 = _piece(game, character, 1, "云岿如我", 8)
    branch_slot_6 = _piece(game, character, 6, "折枝剑歌", 8)

    current_value = best_loadout_value(inventory, game, character)

    assert best_loadout_value([*inventory, cloud_slot_1], game, character) == current_value
    assert best_loadout_value(
        [*inventory, cloud_slot_1, branch_slot_6],
        game,
        character,
    ) > current_value


def test_dp_best_loadout_matches_legacy_cartesian_reference_on_small_inventory():
    game, character, _probability_model, _analysis = _billy_context()
    inventory = [
        _piece(game, character, 1, "折枝剑歌", 2),
        _piece(game, character, 1, "云岿如我", 5),
        _piece(game, character, 2, "云岿如我", 3),
        _piece(game, character, 2, "折枝剑歌", 1),
        _piece(game, character, 3, "折枝剑歌", 4),
        _piece(game, character, 4, "云岿如我", 4),
        _piece(game, character, 5, "云岿如我", 4),
        _piece(game, character, 6, "云岿如我", 1),
        _piece(game, character, 6, "折枝剑歌", 6),
    ]
    rows = inventory_rows_from_pieces(inventory, game, character)

    assert best_loadout_value(inventory, game, character) == _legacy_cartesian_best_value(
        rows,
        game,
        character,
    )


def test_unfinished_inventory_candidate_is_upgrade_source_not_best_loadout_piece():
    game, character, _probability_model, _analysis = _billy_context()
    inventory = [
        _piece(game, character, 1, "折枝剑歌", 2),
        _piece(game, character, 2, "云岿如我", 4),
        _piece(game, character, 3, "折枝剑歌", 4),
        _piece(game, character, 4, "云岿如我", 4),
        _piece(game, character, 5, "云岿如我", 4),
        _piece(game, character, 6, "云岿如我", 0),
    ]
    unfinished = _piece(game, character, 6, "折枝剑歌", 20).model_copy(update={"level": 0})

    assert best_loadout_value([*inventory, unfinished], game, character) == best_loadout_value(
        inventory,
        game,
        character,
    )

    specs = _lookahead_action_specs(
        game,
        character,
        inventory_rows_from_pieces([*inventory, unfinished], game, character),
    )
    assert any(spec.strategy == "强化库存胚子" for spec in specs)


def test_locked_position_cannot_be_replaced_by_inventory_or_upgraded_candidate():
    game, character, probability_model, analysis = _billy_context()
    inventory = [
        _piece(game, character, 1, "折枝剑歌", 2),
        _piece(game, character, 2, "云岿如我", 4),
        _piece(game, character, 3, "折枝剑歌", 4),
        _piece(game, character, 4, "云岿如我", 4),
        _piece(game, character, 5, "云岿如我", 4),
        _piece(game, character, 6, "云岿如我", 0).model_copy(update={"locked": True}),
    ]
    high_same_position = _piece(game, character, 6, "云岿如我", 20)
    unfinished_same_position = high_same_position.model_copy(update={"level": 0})

    locked_value = best_loadout_value(
        inventory,
        game,
        character,
        current_count=len(inventory),
    )

    assert best_loadout_value(
        [*inventory, high_same_position],
        game,
        character,
        current_count=len(inventory),
    ) == locked_value

    rows = position_strategy_efficiency_rows(
        game,
        character,
        probability_model,
        analysis,
        inventory_pieces=[*inventory, unfinished_same_position],
    )
    upgrade_rows = [row for row in rows if row["策略"] == "强化库存胚子"]
    assert upgrade_rows
    assert all(row["质量提升"] == 0 for row in upgrade_rows)


def test_inventory_locked_piece_does_not_lock_position_unless_source_is_current():
    game, character, _probability_model, _analysis = _billy_context()
    current = [
        _piece(game, character, 1, "折枝剑歌", 2),
        _piece(game, character, 2, "云岿如我", 4),
        _piece(game, character, 3, "折枝剑歌", 4),
        _piece(game, character, 4, "云岿如我", 4),
        _piece(game, character, 5, "云岿如我", 4),
        _piece(game, character, 6, "云岿如我", 0),
    ]
    locked_inventory_piece = _piece(game, character, 6, "云岿如我", 1).model_copy(
        update={"locked": True}
    )
    high_same_position = _piece(game, character, 6, "云岿如我", 20)

    assert best_loadout_value(
        [*current, locked_inventory_piece, high_same_position],
        game,
        character,
        current_count=len(current),
    ) > best_loadout_value(
        [*current, locked_inventory_piece],
        game,
        character,
        current_count=len(current),
    )

    locked_current = [*current[:-1], current[-1].model_copy(update={"locked": True})]
    assert best_loadout_value(
        [*locked_current, locked_inventory_piece, high_same_position],
        game,
        character,
        current_count=len(locked_current),
    ) == best_loadout_value(
        locked_current,
        game,
        character,
        current_count=len(locked_current),
    )


def test_piece_can_have_zero_immediate_gain_but_positive_option_value():
    game, character, probability_model, _analysis = _billy_context()
    inventory = [
        _piece(game, character, 1, "折枝剑歌", 2),
        _piece(game, character, 2, "云岿如我", 4),
        _piece(game, character, 3, "折枝剑歌", 4),
        _piece(game, character, 4, "云岿如我", 4),
        _piece(game, character, 5, "云岿如我", 4),
        _piece(game, character, 6, "云岿如我", 0),
    ]
    cloud_slot_1 = _piece(game, character, 1, "云岿如我", 8)

    assert immediate_piece_gain(inventory, cloud_slot_1, game, character) == tuple(
        0.0 for _ in best_loadout_value(inventory, game, character)
    )
    assert option_piece_gain(
        inventory,
        cloud_slot_1,
        game,
        character,
        probability_model,
        horizon=1,
    ) > tuple(0.0 for _ in best_loadout_value(inventory, game, character))


def test_lookahead_action_space_keeps_frontier_and_dominant_generation_specs():
    game, character, _probability_model, _analysis = _billy_context()
    inventory = [
        _piece(game, character, 1, "折枝剑歌", 2),
        _piece(game, character, 2, "云岿如我", 4),
        _piece(game, character, 3, "折枝剑歌", 4),
        _piece(game, character, 4, "云岿如我", 4),
        _piece(game, character, 5, "云岿如我", 4),
        _piece(game, character, 6, "云岿如我", 0),
        _piece(game, character, 1, "云岿如我", 8),
    ]
    rows = inventory_rows_from_pieces(inventory, game, character)

    frontier = _set_plan_frontier_action_specs(game, character, rows)
    frontier_generated = [spec for spec in frontier if spec.strategy != "强化库存胚子"]
    dominant_generated = _dominant_generation_action_specs(game, character)
    assert {
        position_key(spec.target_position)
        for spec in frontier_generated
        if spec.set_options == ("折枝剑歌",)
    } == {"2", "4", "5", "6"}
    assert not any(spec.set_options == ("云岿如我",) for spec in frontier_generated)
    assert set(frontier_generated).issubset(set(dominant_generated))

    specs = _lookahead_action_specs(game, character, rows)
    generated_specs = [spec for spec in specs if spec.strategy != "强化库存胚子"]

    assert generated_specs
    assert any(
        spec.set_options == ("云岿如我",)
        and position_key(spec.target_position) == "6"
        for spec in generated_specs
    )


def test_aggregated_action_outcomes_cache_matches_manual_distribution(monkeypatch):
    game, character, probability_model, _analysis = _billy_context()
    inventory = [
        _piece(game, character, 1, "折枝剑歌", 2),
        _piece(game, character, 2, "云岿如我", 4),
        _piece(game, character, 3, "折枝剑歌", 4),
        _piece(game, character, 4, "云岿如我", 4),
        _piece(game, character, 5, "云岿如我", 4),
        _piece(game, character, 6, "云岿如我", 0),
    ]
    rows = inventory_rows_from_pieces(inventory, game, character, current_count=len(inventory))
    spec = ActionSpec("固定位置", "折枝剑歌", ("折枝剑歌",), 6)
    quality_cache = {}
    _AGGREGATED_ACTION_OUTCOME_CACHE.clear()

    manual = _aggregate_inventory_outcomes(
        _action_outcome_distribution(
            rows,
            game,
            character,
            probability_model,
            spec,
            quality_cache=quality_cache,
        ),
        game,
        character,
    )
    cached = _aggregated_action_outcomes_for_spec(
        rows,
        game,
        character,
        probability_model,
        spec,
        quality_cache=quality_cache,
    )

    assert _outcome_signature(cached) == _outcome_signature(manual)

    def fail_distribution(*_args, **_kwargs):
        raise AssertionError("cache miss unexpectedly recomputed action outcomes")

    monkeypatch.setattr(
        "gear_optimizer.position_ev._action_outcome_distribution",
        fail_distribution,
    )
    second = _aggregated_action_outcomes_for_spec(
        rows,
        game,
        character,
        probability_model,
        spec,
        quality_cache=quality_cache,
    )
    assert second is cached


def test_exact_horizon_two_value_follows_dynamic_programming_formula():
    game, character, probability_model, inventory = _tiny_exact_context()

    horizon_zero = lookahead_inventory_value(inventory, game, character, probability_model, horizon=0)
    horizon_one = lookahead_inventory_value(inventory, game, character, probability_model, horizon=1)
    horizon_two = lookahead_inventory_value(inventory, game, character, probability_model, horizon=2)

    assert horizon_zero[-1] == 0
    assert horizon_one[-1] == 4
    assert horizon_two[-1] == 8


def test_lookahead_action_space_includes_fixed_main_and_fixed_substats():
    game, character, probability_model, analysis = _billy_context()

    rows = position_strategy_efficiency_rows(game, character, probability_model, analysis)

    assert any(row["策略"] == "固定位置 + 固定主属性" for row in rows)
    assert any(row["策略"] == "固定位置 + 固定主属性 + 固定副属性" for row in rows)
    fixed_main = next(
        row
        for row in rows
        if row["策略"] == "固定位置 + 固定主属性"
        and row["位置"] == "6号位"
        and row["主属性"] == "生命值百分比"
        and row["目标套装"] == "云岿如我"
    )
    fixed_substat = next(
        row
        for row in rows
        if row["策略"] == "固定位置 + 固定主属性 + 固定副属性"
        and row["位置"] == "6号位"
        and row["主属性"] == "生命值百分比"
        and row["固定副属性"] == "暴击率"
        and row["目标套装"] == "云岿如我"
    )

    assert fixed_main["校音器/次"] == 1.0
    assert fixed_main["共鸣核/次"] == 0.0
    assert fixed_substat["校音器/次"] == 1.0
    assert fixed_substat["共鸣核/次"] == 1.0
    assert fixed_substat["_sort_vector"] >= fixed_main["_sort_vector"]


def test_action_rows_include_upgrading_existing_inventory_candidate():
    game, character, probability_model, analysis = _billy_context()
    inventory = [
        *load_current_example("examples/zzz_billy_current.yaml"),
        load_candidate_example("examples/zzz_candidate_slot5.yaml"),
    ]

    rows = position_strategy_efficiency_rows(
        game,
        character,
        probability_model,
        analysis,
        inventory_pieces=inventory,
    )
    upgrade_rows = [row for row in rows if row["策略"] == "强化库存胚子"]

    assert upgrade_rows
    assert upgrade_rows[0]["位置"].startswith("5号位 云岿如我 物理伤害")
    assert upgrade_rows[0]["相对随机"] == "库存动作"
    assert upgrade_rows[0]["母盘/次"] == 0.0


def test_fixed_main_marginal_ev_uses_global_best_loadout_action_difference():
    game, character, probability_model, analysis = _billy_context()

    base_spec = ActionSpec("固定位置", "云岿如我", ("云岿如我",), 6)
    fixed_main_spec = ActionSpec(
        "固定位置 + 固定主属性",
        "云岿如我",
        ("云岿如我",),
        6,
        fixed_main_stat="生命值百分比",
    )
    inventory = load_current_example("examples/zzz_billy_current.yaml")
    base_gain = action_gain_for_spec(
        inventory,
        game,
        character,
        probability_model,
        base_spec,
    )
    fixed_gain = action_gain_for_spec(
        inventory,
        game,
        character,
        probability_model,
        fixed_main_spec,
    )
    rows = resource_marginal_ev_rows(game, character, probability_model, analysis)
    marginal = next(
        row
        for row in rows
        if row["资源"] == "校音器"
        and row["目标套装"] == "云岿如我"
        and row["位置"] == "6号位"
        and row["主属性"] == "生命值百分比"
    )

    assert fixed_gain[-2] > base_gain[-2]
    assert fixed_gain[-1] > base_gain[-1]
    assert marginal["基准action"] == "固定位置，不固定主属性"
    assert marginal["资源action"] == "固定位置 + 固定主属性"
    assert marginal["期望校音器/次"] == 1.0
    assert marginal["期望共鸣核/次"] == 0.0
    assert marginal["同等有效省母盘"] > 0
    assert marginal["同等质量省母盘"] > 0
    assert marginal["边际有效提升"] == pytest.approx(fixed_gain[-2] - base_gain[-2], abs=0.001)


def test_recommended_action_ev_row_only_promotes_fixed_when_it_beats_random():
    rows = [
        {
            "策略": "随机位置",
            "目标套装": "A",
            "位置": "1-6 随机",
            "质量/母盘": 0.02,
            "有效/母盘": 0.02,
            "相对随机": "基准",
        },
        {
            "策略": "固定位置",
            "目标套装": "A",
            "位置": "6号位",
            "质量/母盘": 0.03,
            "有效/母盘": 0.03,
            "相对随机": "不如随机，不建议固定",
        },
    ]

    assert recommended_action_ev_row(rows)["策略"] == "随机位置"

    rows[1]["相对随机"] = "优于随机，才建议固定"

    assert recommended_action_ev_row(rows)["策略"] == "固定位置"


def test_fixed_main_gain_ladder_starts_from_current_weakest_position():
    game, character, probability_model, analysis = _billy_context()

    rows = fixed_main_gain_ladder_rows(game, character, probability_model, analysis)

    assert rows
    assert rows[0]["位置"] == "6号位"
    assert rows[0]["当前补弱顺位"] == 1
    assert rows[0]["提升目标"] == "+1"
    assert rows[0]["推荐主属性"] == "生命值百分比"
    assert rows[0]["固定主属性有效提升"] > rows[0]["不锁主属性有效提升"]
    assert rows[0]["省母盘"] > 0
    assert rows[0]["期望校音器"] > 0


def test_fixed_substat_gain_ladder_counts_cores_without_equivalent_conversion():
    game, character, probability_model, analysis = _billy_context()

    rows = fixed_substat_gain_ladder_rows(game, character, probability_model, analysis)

    assert rows
    first = rows[0]
    second = rows[1]
    assert first["位置"] == "6号位"
    assert first["锁定副属性"] == "暴击率"
    assert first["提升目标"] == "+1"
    assert first["锁副属性有效提升"] > first["固定主属性有效提升"]
    assert first["省母盘"] > 0
    assert first["期望共鸣核"] > 0
    assert second["锁定副属性"] == "暴击率 + 暴击伤害"
    assert second["期望共鸣核"] > first["期望共鸣核"]


def test_initial_substat_tier_rows_explain_three_line_mainstream_and_four_of_three():
    game, character, probability_model, analysis = _billy_context()

    rows = initial_substat_tier_rows(game, character, probability_model, analysis)
    by_slot_and_tier = {(row["位置"], row["胚子挡位"]): row for row in rows}

    assert by_slot_and_tier[("6号位", "3中2")]["总出现概率"] > by_slot_and_tier[("6号位", "4中2")]["总出现概率"]
    assert by_slot_and_tier[("6号位", "3中2")]["满级有效期望"] > 0
    assert ("5号位", "4中3") in by_slot_and_tier
    assert ("6号位", "4中3") not in by_slot_and_tier
    assert by_slot_and_tier[("5号位", "4中3")]["参考主属性"] == "物理伤害"
