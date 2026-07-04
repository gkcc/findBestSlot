from collections import defaultdict
from itertools import product
import json

import pytest

import gear_optimizer.position_ev as position_ev
from gear_optimizer.game_rules import load_characters, load_game, load_probability_models
from gear_optimizer.position_ev import (
    ActionSpec,
    action_gain_for_spec,
    best_loadout_rows,
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
    _positive_gain,
    _row_sort_vector,
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

    assert character.substat_priority.core == ["暴击率", "暴击伤害", "生命值百分比"]
    assert character.substat_priority.usable == []
    assert substat_quality_vector(piece, character) == (6.0, 2.0, 1.0, 3.0, 0.0)


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


def _tiny_six_exact_context():
    positions = [
        PositionRule(id=index, name=f"{index}号位", main_stats=[f"main{index}"])
        for index in range(1, 7)
    ]
    game = GameRules(
        id="tiny_six",
        name="Tiny Six",
        gear_name="Disk",
        sets=["A"],
        positions=positions,
        sub_stats=["a", "b", "c", "d"],
        main_stat_probabilities={
            str(index): {f"main{index}": 1.0}
            for index in range(1, 7)
        },
        sub_stat_probabilities={"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0},
        enhancement=EnhancementRule(max_level=0, step=3, initial_add_level=3),
    )
    character = CharacterPreset(
        id="tiny_six_char",
        game="tiny_six",
        name="Tiny Six Char",
        target_set="A",
        substat_priority=SubstatPriority(core=["a", "b", "c", "d"], usable=[]),
        preferred_main_stats={
            str(index): [f"main{index}"]
            for index in range(1, 7)
        },
        set_plans=[
            SetPlan(
                id="a6",
                name="A 6",
                requirements=[SetRequirement(set_name="A", pieces=6)],
            )
        ],
        default_set_plan="a6",
    )
    probability_model = ProbabilityModel(
        id="tiny_six_prob",
        game="tiny_six",
        name="Tiny six deterministic",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 0.0, "4": 1.0},
        resource_costs={
            "mother_disk_random_position_attempt": 1.0,
            "mother_disk_fixed_position_attempt": 1.0,
        },
    )
    inventory = [
        GearPiece(position=index, set_name="A", main_stat=f"main{index}", level=0, substats=[])
        for index in range(1, 7)
    ]
    return game, character, probability_model, inventory


def _tiny_lock_context():
    game = GameRules(
        id="tiny_lock",
        name="Tiny Lock",
        gear_name="Disk",
        sets=["A"],
        positions=[
            PositionRule(id=1, name="1号位", main_stats=["main_good", "main_bad"]),
            PositionRule(id=2, name="2号位", main_stats=["main2"]),
        ],
        sub_stats=["good", "ok", "bad", "worse"],
        main_stat_probabilities={
            "1": {"main_good": 0.5, "main_bad": 0.5},
            "2": {"main2": 1.0},
        },
        sub_stat_probabilities={"good": 0.25, "ok": 0.25, "bad": 0.25, "worse": 0.25},
        enhancement=EnhancementRule(max_level=0, step=3, initial_add_level=3),
    )
    character = CharacterPreset(
        id="tiny_lock_char",
        game="tiny_lock",
        name="Tiny Lock Char",
        target_set="A",
        substat_priority=SubstatPriority(core=["good"], usable=["ok"]),
        preferred_main_stats={"1": ["main_good"], "2": ["main2"]},
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
        id="tiny_lock_prob",
        game="tiny_lock",
        name="Tiny lock deterministic",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 0.0, "4": 1.0},
        resource_costs={
            "mother_disk_random_position_attempt": 1.0,
            "mother_disk_fixed_position_attempt": 1.0,
        },
    )
    inventory = [
        GearPiece(
            position=1,
            set_name="A",
            main_stat="main_good",
            level=0,
            substats=[SubstatLine(stat="bad", rolls=0)],
        ),
        GearPiece(
            position=2,
            set_name="A",
            main_stat="main2",
            level=0,
            substats=[SubstatLine(stat="worse", rolls=0)],
        ),
    ]
    analysis = analyse_current_gear(inventory, game, character)
    return game, character, probability_model, analysis, inventory


def _position_rows_with_fake_action_values(monkeypatch, increments: dict[str, float]):
    game, character, probability_model, analysis, inventory = _tiny_lock_context()
    current_value = best_loadout_value(
        inventory,
        game,
        character,
        current_count=len(inventory),
    )
    calls = []

    def fake_expected_action_value(
        _inventory_rows,
        _game,
        _character,
        _probability_model,
        spec,
        *_args,
        **_kwargs,
    ):
        calls.append(spec.strategy)
        positioned_key = f"{spec.strategy}:{position_key(spec.target_position)}"
        delta = increments.get(positioned_key, increments.get(spec.strategy, 0.0))
        return (*current_value[:-1], current_value[-1] + delta)

    position_ev._ACTION_EV_ROWS_CACHE.clear()
    monkeypatch.setattr(position_ev, "_expected_action_value", fake_expected_action_value)
    rows = position_strategy_efficiency_rows(game, character, probability_model, analysis)
    position_ev._ACTION_EV_ROWS_CACHE.clear()
    return rows, calls


def _tiny_upgrade_expectation_context():
    game = GameRules(
        id="tiny_upgrade",
        name="Tiny Upgrade",
        gear_name="Disk",
        sets=["A"],
        positions=[PositionRule(id=1, name="1号位", main_stats=["main"])],
        sub_stats=["good", "bad"],
        main_stat_probabilities={"1": {"main": 1.0}},
        sub_stat_probabilities={"good": 1.0, "bad": 1.0},
        enhancement=EnhancementRule(max_level=3, step=3, initial_add_level=3),
    )
    character = CharacterPreset(
        id="tiny_upgrade_char",
        game="tiny_upgrade",
        name="Tiny Upgrade Char",
        target_set="A",
        substat_priority=SubstatPriority(core=["good"], usable=[]),
        preferred_main_stats={"1": ["main"]},
        set_plans=[
            SetPlan(
                id="a1",
                name="A 1",
                requirements=[SetRequirement(set_name="A", pieces=1)],
            )
        ],
        default_set_plan="a1",
    )
    current = GearPiece(
        position=1,
        set_name="A",
        main_stat="main",
        level=3,
        substats=[SubstatLine(stat="good", rolls=0)],
        initial_substat_count=4,
    )
    embryo = GearPiece(
        position=1,
        set_name="A",
        main_stat="main",
        level=0,
        substats=[SubstatLine(stat="good", rolls=0)],
        initial_substat_count=4,
    )
    return game, character, current, embryo


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
    random_row = next(row for row in rows if row["策略"] == "随机位置")
    fixed_rows = [row for row in rows if row["策略"] == "固定位置"]

    assert random_row["策略"] == "随机位置"
    assert random_row["位置"] == "1-6 随机"
    assert {"云岿如我", "折枝剑歌"}.issubset({row["目标套装"] for row in rows})
    assert "排序向量/母盘" in random_row
    assert any(row["位置"] == "6号位" and row["有效/母盘"] > 0 for row in fixed_rows)
    branch_slot6 = next(
        row
        for row in rows
        if row["策略"] == "固定位置"
        and row["目标套装"] == "折枝剑歌"
        and row["位置"] == "6号位"
    )
    assert "云岿如我5 + 折枝剑歌1" in branch_slot6["预期搭配"]
    assert "6号位折枝剑歌" in branch_slot6["代表路径"]
    assert branch_slot6["套装约束"] == "未满足云岿如我 4 + 折枝剑歌 2硬约束"
    assert branch_slot6["相对随机"] == "未满足套装硬约束，不作为当前 horizon 推荐"
    assert "代表新盘未进入" not in branch_slot6["互补位"]


def test_horizon_two_random_action_row_is_marked_as_mixed_not_representative():
    game, character, probability_model, inventory = _tiny_six_exact_context()
    analysis = analyse_current_gear(inventory, game, character)

    rows = position_strategy_efficiency_rows(
        game,
        character,
        probability_model,
        analysis,
        horizon=2,
    )
    random_row = next(row for row in rows if row["策略"] == "随机位置")

    assert "概率混合" in random_row["代表路径"]
    assert "条件策略" in random_row["代表路径"]
    assert random_row["方案类型"] == "条件策略"
    assert random_row["预期搭配"] == "混合结果，不存在唯一典型搭配"
    assert random_row["代表分支搭配"] == "混合结果，不存在唯一典型搭配"
    assert random_row["互补位"] == "请查看 H=2 方案条件分支；固定位置行可辅助审计"
    assert random_row["_representative_loadout_rows"] == []
    assert random_row["套装约束"] == "混合动作：每个条件分支分别验算套装硬约束"
    assert random_row["比较口径"] == "随机混合：1-6 固定位置按概率加权；不是单一代表搭配"
    branches = random_row["条件分支"]
    assert len(branches) == 6
    assert {branch["条件"] for branch in branches} == {f"第1步命中 {index}号位" for index in range(1, 7)}
    assert all(branch["条件概率"] == pytest.approx(1 / 6) for branch in branches)
    for branch in branches:
        assert {
            "条件",
            "条件概率",
            "代表新盘",
            "第二步 action",
            "第二步原因",
            "代表最终搭配",
            "套装约束",
        }.issubset(branch)
        assert "exact horizon=1 lookahead" in branch["第二步原因"] or "未找到正提升" in branch["第二步原因"]

    fixed_row = next(row for row in rows if row["策略"] == "固定位置")
    assert fixed_row["方案类型"] == "代表路径"
    assert fixed_row["代表路径说明"] == "代表路径仅用于审计；真实 H=2 EV 已对所有 outcome 加权。"
    assert fixed_row["_representative_loadout_rows"]
    assert "第1步" in fixed_row["代表路径"]


def test_horizon_one_action_rows_are_single_step_explanations():
    game, character, probability_model, inventory = _tiny_exact_context()
    analysis = analyse_current_gear(inventory, game, character)

    rows = position_strategy_efficiency_rows(
        game,
        character,
        probability_model,
        analysis,
        horizon=1,
    )

    assert rows
    assert {row["方案类型"] for row in rows} == {"单步"}
    assert all(row["第二步策略摘要"] == "-" for row in rows)
    assert all(row["条件分支"] == [] for row in rows)


def test_random_horizon_two_condition_followup_uses_exact_helper(monkeypatch):
    game, character, probability_model, inventory = _tiny_six_exact_context()
    inventory_rows = inventory_rows_from_pieces(
        inventory,
        game,
        character,
        current_count=len(inventory),
    )
    sentinel = ActionSpec("固定位置", "A", ("A",), 6)
    calls = []

    def fake_best_followup_spec(
        _inventory,
        _game,
        _character,
        _probability_model,
        horizon,
        _memo,
        _quality_cache,
    ):
        calls.append(horizon)
        return sentinel

    monkeypatch.setattr(position_ev, "_best_followup_spec", fake_best_followup_spec)

    branches = position_ev._random_position_condition_branches(
        inventory_rows,
        game,
        character,
        probability_model,
        ActionSpec("随机位置", "A", ("A",), None),
        2,
        {},
        {},
    )

    assert calls == [1] * 6
    assert len(branches) == 6
    assert all(branch["第二步 action"] == "固定位置 / A / 6号位" for branch in branches)
    assert all("exact horizon=1 lookahead" in branch["第二步原因"] for branch in branches)


def test_single_action_plan_status_uses_inventory_complement_for_four_plus_two():
    game, character, probability_model, analysis = _billy_context()
    current = load_current_example("examples/zzz_billy_current.yaml")
    inventory = [
        GearPiece(
            position=5,
            set_name="折枝剑歌",
            main_stat="物理伤害",
            level=15,
            substats=[
                SubstatLine(stat="暴击率", rolls=2),
                SubstatLine(stat="暴击伤害", rolls=2),
                SubstatLine(stat="生命值百分比", rolls=2),
            ],
            initial_substat_count=4,
        )
    ]

    rows = position_strategy_efficiency_rows(
        game,
        character,
        probability_model,
        analysis,
        inventory_pieces=[*current, *inventory],
    )
    branch_slot6 = next(
        row
        for row in rows
        if row["策略"] == "固定位置"
        and row["目标套装"] == "折枝剑歌"
        and row["位置"] == "6号位"
    )

    assert branch_slot6["套装约束"] == "满足云岿如我 4 + 折枝剑歌 2"
    assert "云岿如我4 + 折枝剑歌2" in branch_slot6["预期搭配"]
    assert "5号位折枝剑歌" in branch_slot6["互补位"]
    assert "6号位折枝剑歌" in branch_slot6["代表路径"]
    representative_rows = branch_slot6["_representative_loadout_rows"]
    assert len(representative_rows) == 6
    assert any(row["set_name"] == "折枝剑歌" and row["position"] == 5 for row in representative_rows)
    assert any(row["set_name"] == "折枝剑歌" and row["position"] == 6 for row in representative_rows)


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


def test_best_loadout_can_explicitly_rank_unfinished_inventory_by_upgrade_expectation():
    game, character, current, embryo = _tiny_upgrade_expectation_context()

    static_rows = best_loadout_rows([current, embryo], game, character, current_count=1)
    expected_rows = best_loadout_rows(
        [current, embryo],
        game,
        character,
        current_count=1,
        include_upgrade_expectation=True,
    )

    assert static_rows[0]["source"] == "current"
    assert expected_rows[0]["source"] == "inventory"
    assert expected_rows[0]["_expected_upgrade"] is True
    assert expected_rows[0]["_current_quality_score"] == 1.0
    assert expected_rows[0]["quality_score"] == 2.0
    assert best_loadout_value(
        [current, embryo],
        game,
        character,
        current_count=1,
        include_upgrade_expectation=True,
    ) > best_loadout_value([current, embryo], game, character, current_count=1)


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


def test_core_global_caches_enforce_lru_capacity_limits():
    cache_specs = [
        (position_ev._ACTION_EV_ROWS_CACHE, position_ev.ACTION_EV_ROWS_CACHE_MAX_SIZE, "action"),
        (
            position_ev._RESOURCE_MARGINAL_EV_ROWS_CACHE,
            position_ev.RESOURCE_MARGINAL_EV_ROWS_CACHE_MAX_SIZE,
            "resource",
        ),
        (position_ev._BEST_COMBO_VALUE_CACHE, position_ev.BEST_COMBO_VALUE_CACHE_MAX_SIZE, "best"),
        (
            position_ev._AGGREGATED_ACTION_OUTCOME_CACHE,
            position_ev.AGGREGATED_ACTION_OUTCOME_CACHE_MAX_SIZE,
            "outcome",
        ),
        (position_ev._STATE_TRANSITION_CACHE, position_ev.STATE_TRANSITION_CACHE_MAX_SIZE, "state"),
    ]

    try:
        for cache, max_size, prefix in cache_specs:
            cache.clear()
            for index in range(max_size):
                position_ev._lru_set(cache, (prefix, index), index, max_size)
            assert len(cache) == max_size

            assert position_ev._lru_get(cache, (prefix, 0)) == 0
            position_ev._lru_set(cache, (prefix, "new"), "new", max_size)

            assert len(cache) == max_size
            assert (prefix, 0) in cache
            assert (prefix, 1) not in cache
            assert (prefix, "new") in cache
    finally:
        for cache, _max_size, _prefix in cache_specs:
            cache.clear()


def test_action_ev_cache_key_includes_engine_and_config_fingerprints():
    game, character, probability_model, analysis = _billy_context()
    inventory_rows = position_ev._current_inventory_rows(analysis, character)

    inventory_key = json.loads(
        position_ev._action_ev_cache_key(
            game,
            character,
            probability_model,
            analysis,
            inventory_rows=inventory_rows,
            horizon=1,
            use_state_dp=False,
        )
    )
    state_key = json.loads(
        position_ev._action_ev_cache_key(
            game,
            character,
            probability_model,
            analysis,
            inventory_rows=inventory_rows,
            horizon=1,
            use_state_dp=True,
        )
    )

    assert inventory_key["engine"] == "inventory_recursive"
    assert state_key["engine"] == "state_dp"
    assert inventory_key["fingerprints"]["game"][0] == game.id
    assert inventory_key["fingerprints"]["character"][0] == character.id
    assert inventory_key["fingerprints"]["probability_model"][0] == probability_model.id


def test_exact_horizon_two_value_follows_dynamic_programming_formula():
    game, character, probability_model, inventory = _tiny_exact_context()

    horizon_zero = lookahead_inventory_value(inventory, game, character, probability_model, horizon=0)
    horizon_one = lookahead_inventory_value(inventory, game, character, probability_model, horizon=1)
    horizon_two = lookahead_inventory_value(inventory, game, character, probability_model, horizon=2)

    assert horizon_zero[-1] == 0
    assert horizon_one[-1] == 4
    assert horizon_two[-1] == 8


def test_action_ev_progress_calculates_fixed_positions_before_random(monkeypatch):
    game, character, probability_model, analysis, inventory = _tiny_lock_context()
    current_value = best_loadout_value(
        inventory,
        game,
        character,
        current_count=len(inventory),
    )
    events = []

    def fake_expected_action_value(
        _inventory_rows,
        _game,
        _character,
        _probability_model,
        spec,
        *_args,
        **_kwargs,
    ):
        return (*current_value[:-1], current_value[-1] + (1.0 if spec.target_position == 1 else 0.5))

    position_ev._ACTION_EV_ROWS_CACHE.clear()
    monkeypatch.setattr(position_ev, "_expected_action_value", fake_expected_action_value)
    position_strategy_efficiency_rows(
        game,
        character,
        probability_model,
        analysis,
        progress_callback=events.append,
    )
    position_ev._ACTION_EV_ROWS_CACHE.clear()

    first_unit = next(event for event in events if event.get("event") == "unit_start")
    assert first_unit["action_strategy"] == "固定位置"


def test_random_position_ev_is_weighted_average_of_fixed_positions(monkeypatch):
    rows, calls = _position_rows_with_fake_action_values(
        monkeypatch,
        {
            "固定位置:1": 1.0,
            "固定位置:2": 5.0,
        },
    )

    random_row = next(row for row in rows if row["策略"] == "随机位置")
    slot_1 = next(row for row in rows if row["策略"] == "固定位置" and row["位置"] == "1号位")
    slot_2 = next(row for row in rows if row["策略"] == "固定位置" and row["位置"] == "2号位")

    assert random_row["质量提升"] == pytest.approx((slot_1["质量提升"] + slot_2["质量提升"]) / 2)
    assert random_row["有效提升"] == pytest.approx((slot_1["有效提升"] + slot_2["有效提升"]) / 2)
    assert calls.count("随机位置") == 0


def test_fixed_main_rows_wait_until_fixed_position_beats_random(monkeypatch):
    rows, calls = _position_rows_with_fake_action_values(
        monkeypatch,
        {
            "固定位置": 1.0,
            "固定位置 + 固定主属性": 99.0,
            "固定位置 + 固定主属性 + 固定副属性": 99.0,
        },
    )

    assert not any(row["策略"] == "固定位置 + 固定主属性" for row in rows)
    assert not any(row["策略"] == "固定位置 + 固定主属性 + 固定副属性" for row in rows)
    assert "固定位置 + 固定主属性" not in calls
    assert "固定位置 + 固定主属性 + 固定副属性" not in calls


def test_fixed_substat_rows_wait_until_fixed_main_beats_fixed_position(monkeypatch):
    rows, calls = _position_rows_with_fake_action_values(
        monkeypatch,
        {
            "固定位置:1": 3.0,
            "固定位置:2": 0.0,
            "固定位置 + 固定主属性": 2.0,
            "固定位置 + 固定主属性 + 固定副属性": 99.0,
        },
    )

    assert any(row["策略"] == "固定位置 + 固定主属性" for row in rows)
    assert not any(row["策略"] == "固定位置 + 固定主属性 + 固定副属性" for row in rows)
    assert "固定位置 + 固定主属性" in calls
    assert "固定位置 + 固定主属性 + 固定副属性" not in calls


def test_fixed_substat_rows_expand_after_fixed_main_beats_fixed_position(monkeypatch):
    rows, calls = _position_rows_with_fake_action_values(
        monkeypatch,
        {
            "固定位置:1": 2.0,
            "固定位置:2": 0.0,
            "固定位置 + 固定主属性": 3.0,
            "固定位置 + 固定主属性 + 固定副属性": 4.0,
        },
    )

    assert any(
        row["策略"] == "固定位置 + 固定主属性"
        and row["相对随机"] == "固定位置已优于随机；优于固定位置，才建议锁主属性"
        for row in rows
    )
    assert any(
        row["策略"] == "固定位置 + 固定主属性 + 固定副属性"
        and row["相对随机"] == "锁主属性已优于固定位置；优于锁主属性，才建议锁副属性"
        for row in rows
    )
    assert "固定位置 + 固定主属性 + 固定副属性" in calls


def test_lookahead_action_space_includes_fixed_main_and_fixed_substats(monkeypatch):
    rows, _calls = _position_rows_with_fake_action_values(
        monkeypatch,
        {
            "固定位置:1": 2.0,
            "固定位置:2": 0.0,
            "固定位置 + 固定主属性": 3.0,
            "固定位置 + 固定主属性 + 固定副属性": 4.0,
        },
    )

    assert any(row["策略"] == "固定位置 + 固定主属性" for row in rows)
    assert any(row["策略"] == "固定位置 + 固定主属性 + 固定副属性" for row in rows)
    fixed_main = next(
        row
        for row in rows
        if row["策略"] == "固定位置 + 固定主属性"
    )
    fixed_substat = next(
        row
        for row in rows
        if row["策略"] == "固定位置 + 固定主属性 + 固定副属性"
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
    assert upgrade_rows[0]["相对随机"] == "未满足套装硬约束，不作为当前 horizon 推荐"
    assert upgrade_rows[0]["套装约束"].startswith("未满足")
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

    rows[1]["套装约束"] = "未满足A 2硬约束"

    assert recommended_action_ev_row(rows)["策略"] == "随机位置"

    rows[1]["套装约束"] = "满足A 2"

    assert recommended_action_ev_row(rows)["策略"] == "固定位置"

    rows.append(
        {
            "策略": "固定位置 + 固定主属性",
            "目标套装": "A",
            "位置": "6号位",
            "质量/母盘": 0.05,
            "有效/母盘": 0.05,
            "相对随机": "固定位置已优于随机；不如固定位置，不建议锁主属性",
        }
    )

    assert recommended_action_ev_row(rows)["策略"] == "固定位置"

    rows[-1]["相对随机"] = "固定位置已优于随机；优于固定位置，才建议锁主属性"

    assert recommended_action_ev_row(rows)["策略"] == "固定位置 + 固定主属性"

    rows.append(
        {
            "策略": "固定位置 + 固定主属性 + 固定副属性",
            "目标套装": "A",
            "位置": "6号位",
            "质量/母盘": 0.06,
            "有效/母盘": 0.06,
            "相对随机": "锁主属性已优于固定位置；不如锁主属性，不建议锁副属性",
        }
    )

    assert recommended_action_ev_row(rows)["策略"] == "固定位置 + 固定主属性"

    rows[-1]["相对随机"] = "锁主属性已优于固定位置；优于锁主属性，才建议锁副属性"

    assert recommended_action_ev_row(rows)["策略"] == "固定位置 + 固定主属性 + 固定副属性"


def test_action_plan_explain_fields_do_not_affect_recommendation_sorting():
    rows = [
        {
            "策略": "随机位置",
            "目标套装": "A",
            "位置": "1-6 随机",
            "质量/母盘": 0.01,
            "有效/母盘": 0.01,
            "_sort_vector": (0.01, 0.01),
            "相对随机": "基准",
            "套装约束": "满足A 6",
            "方案类型": "条件策略",
            "第二步策略摘要": "旧摘要",
            "条件分支": [],
        },
        {
            "策略": "固定位置",
            "目标套装": "A",
            "位置": "6号位",
            "质量/母盘": 0.02,
            "有效/母盘": 0.02,
            "_sort_vector": (0.02, 0.02),
            "相对随机": "优于随机，才建议固定",
            "套装约束": "满足A 6",
            "方案类型": "代表路径",
            "第二步策略摘要": "旧摘要",
            "条件分支": [],
        },
    ]

    assert recommended_action_ev_row(rows) is rows[1]

    rows[0]["方案类型"] = "看起来很强"
    rows[0]["第二步策略摘要"] = "不应影响排序"
    rows[0]["条件分支"] = [{"第二步 action": "伪造高收益"}]

    assert recommended_action_ev_row(rows) is rows[1]


def test_recommended_action_ev_ignores_float_noise_before_real_gain():
    rows = [
        {
            "策略": "随机位置",
            "目标套装": "A",
            "位置": "1-6 随机",
            "质量/母盘": 0.0025,
            "有效/母盘": 0.0025,
            "_sort_vector": (1e-10, 0.0025, 0.0),
            "相对随机": "基准",
            "套装约束": "满足A 6",
        },
        {
            "策略": "随机位置",
            "目标套装": "B",
            "位置": "1-6 随机",
            "质量/母盘": 0.04,
            "有效/母盘": 0.04,
            "_sort_vector": (0.0, 0.04, 0.0),
            "相对随机": "基准",
            "套装约束": "满足B 6",
        },
    ]

    assert _row_sort_vector(rows[0])[0] == 0.0
    assert recommended_action_ev_row(rows) is rows[1]
    assert _positive_gain((1e-10, 1.0), (0.0, 1.0)) == (0.0, 0.0)


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
