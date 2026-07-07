import pytest

import gear_optimizer.position_ev as position_ev
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
)
from gear_optimizer.scoring import analyse_current_gear
from gear_optimizer.position_ev import (
    ActionSpec,
    EvState,
    best_loadout_rows,
    best_loadout_value,
    compare_action_ev_engines,
    configured_action_ev_workers,
    expected_state_action_value,
    inventory_rows_from_pieces,
    lookahead_inventory_value,
    lookahead_inventory_value_state_dp,
    parallel_expected_state_action_values,
    position_strategy_efficiency_rows,
)


def _gear_piece(position, set_name, rolls=0, *, locked=False, level=0, main_stat=None):
    return GearPiece(
        position=position,
        set_name=set_name,
        main_stat=main_stat or f"main{position}",
        level=level,
        locked=locked,
        substats=[SubstatLine(stat="good", rolls=rolls)],
        initial_substat_count=4,
    )


def _six_slot_game():
    return GameRules(
        id="six",
        name="Six",
        gear_name="Disk",
        sets=["A", "B", "C"],
        positions=[
            PositionRule(id=index, name=f"{index}号位", main_stats=[f"main{index}"])
            for index in range(1, 7)
        ],
        sub_stats=["good", "bad"],
        main_stat_probabilities={
            str(index): {f"main{index}": 1.0}
            for index in range(1, 7)
        },
        sub_stat_probabilities={"good": 1.0, "bad": 1.0},
        enhancement=EnhancementRule(max_level=0, step=3, initial_add_level=3),
    )


def _six_slot_character(requirements, plan_id):
    return CharacterPreset(
        id=f"six_{plan_id}",
        game="six",
        name="Six Char",
        target_set="A",
        substat_priority=SubstatPriority(core=["good"], usable=[]),
        preferred_main_stats={
            str(index): [f"main{index}"]
            for index in range(1, 7)
        },
        set_plans=[
            SetPlan(
                id=plan_id,
                name=plan_id,
                requirements=requirements,
            )
        ],
        default_set_plan=plan_id,
    )


def _two_slot_game(max_level=0):
    return GameRules(
        id=f"two_{max_level}",
        name="Two",
        gear_name="Disk",
        sets=["A"],
        positions=[
            PositionRule(id=1, name="1号位", main_stats=["main1"]),
            PositionRule(id=2, name="2号位", main_stats=["main2"]),
        ],
        sub_stats=["good", "ok", "bad", "worse"],
        main_stat_probabilities={"1": {"main1": 1.0}, "2": {"main2": 1.0}},
        sub_stat_probabilities={"good": 1.0, "ok": 1.0, "bad": 1.0, "worse": 1.0},
        enhancement=EnhancementRule(max_level=max_level, step=3, initial_add_level=3),
    )


def _two_slot_character():
    return CharacterPreset(
        id="two_char",
        game="two",
        name="Two Char",
        target_set="A",
        substat_priority=SubstatPriority(core=["good"], usable=["ok"]),
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


def _two_slot_probability(game_id="two"):
    return ProbabilityModel(
        id=f"{game_id}_prob",
        game=game_id,
        name="Two deterministic",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 0.0, "4": 1.0},
        resource_costs={
            "mother_disk_random_position_attempt": 1.0,
            "mother_disk_fixed_position_attempt": 1.0,
        },
    )


def test_ev_state_best_loadout_matches_inventory_for_4_plus_2():
    game = _six_slot_game()
    character = _six_slot_character(
        [
            SetRequirement(set_name="A", pieces=4),
            SetRequirement(set_name="B", pieces=2),
        ],
        "a4b2",
    )
    inventory = [
        *[_gear_piece(index, "A", rolls=1) for index in range(1, 5)],
        _gear_piece(5, "B", rolls=1),
        _gear_piece(6, "B", rolls=1),
        _gear_piece(6, "C", rolls=9),
    ]

    state = EvState.from_inventory(inventory, game, character, current_count=6)

    assert state.best_loadout_value(game, character) == best_loadout_value(
        inventory,
        game,
        character,
        current_count=6,
    )
    assert [row["set_name"] for row in state.best_loadout_rows(game, character)].count("A") == 4
    assert [row["set_name"] for row in state.best_loadout_rows(game, character)].count("B") == 2


def test_ev_state_best_loadout_matches_inventory_for_2_plus_2_plus_2():
    game = _six_slot_game()
    character = _six_slot_character(
        [
            SetRequirement(set_name="A", pieces=2),
            SetRequirement(set_name="B", pieces=2),
            SetRequirement(set_name="C", pieces=2),
        ],
        "a2b2c2",
    )
    inventory = [
        _gear_piece(1, "A", rolls=1),
        _gear_piece(2, "A", rolls=1),
        _gear_piece(3, "B", rolls=1),
        _gear_piece(4, "B", rolls=1),
        _gear_piece(5, "C", rolls=1),
        _gear_piece(6, "C", rolls=1),
        _gear_piece(6, "A", rolls=9),
    ]

    state = EvState.from_inventory(inventory, game, character, current_count=6)

    assert state.best_loadout_value(game, character) == best_loadout_value(
        inventory,
        game,
        character,
        current_count=6,
    )
    counts = {}
    for row in state.best_loadout_rows(game, character):
        counts[row["set_name"]] = counts.get(row["set_name"], 0) + 1
    assert counts == {"A": 2, "B": 2, "C": 2}


def test_ev_state_preserves_current_locked_position():
    game = _two_slot_game()
    character = _two_slot_character()
    current = [
        _gear_piece(1, "A", rolls=0, locked=True),
        _gear_piece(2, "A", rolls=0),
    ]
    inventory = [
        _gear_piece(1, "A", rolls=9),
    ]

    state = EvState.from_inventory([*current, *inventory], game, character, current_count=2)
    rows = state.best_loadout_rows(game, character)

    assert state.locked_positions == ("1",)
    assert next(row for row in rows if row["position"] == 1)["locked"] is True
    assert state.best_loadout_value(game, character) == best_loadout_value(
        [*current, *inventory],
        game,
        character,
        current_count=2,
    )
    candidate_row = position_ev._candidate_inventory_row(
        _gear_piece(1, "A", rolls=20, main_stat="main1"),
        game,
        character,
        source="outcome",
    )
    assert state.with_candidate_row(candidate_row, game, character) is state


def test_ev_state_does_not_treat_inventory_locked_as_position_lock():
    game = _two_slot_game()
    character = _two_slot_character()
    current = [
        _gear_piece(1, "A", rolls=0),
        _gear_piece(2, "A", rolls=0),
    ]
    inventory = [
        _gear_piece(1, "A", rolls=9, locked=True),
    ]

    state = EvState.from_inventory([*current, *inventory], game, character, current_count=2)
    rows = state.best_loadout_rows(game, character)

    assert state.locked_positions == ()
    assert next(row for row in rows if row["position"] == 1)["quality_score"] > 1
    assert state.best_loadout_value(game, character) == best_loadout_value(
        [*current, *inventory],
        game,
        character,
        current_count=2,
    )


def test_ev_state_keeps_unfinished_piece_as_upgrade_source_only_by_default():
    game = _two_slot_game(max_level=3)
    character = _two_slot_character()
    current = [
        _gear_piece(1, "A", rolls=0, level=3),
        _gear_piece(2, "A", rolls=0, level=3),
    ]
    embryo = _gear_piece(1, "A", rolls=9, level=0)

    state = EvState.from_inventory([*current, embryo], game, character, current_count=2)

    assert state.upgrade_source_ids == ("piece:2",)
    assert state.best_loadout_value(game, character) == best_loadout_value(
        current,
        game,
        character,
        current_count=2,
    )


def test_ev_state_candidate_transition_merges_non_improving_rows():
    game = _two_slot_game()
    character = _two_slot_character()
    inventory = [
        _gear_piece(1, "A", rolls=3),
        _gear_piece(2, "A", rolls=0),
    ]
    state = EvState.from_inventory(inventory, game, character, current_count=2)

    weak_candidate = position_ev._candidate_inventory_row(
        _gear_piece(1, "A", rolls=0, main_stat="main1"),
        game,
        character,
        source="outcome",
    )
    strong_candidate = position_ev._candidate_inventory_row(
        _gear_piece(1, "A", rolls=9, main_stat="main1"),
        game,
        character,
        source="outcome",
    )

    assert state.with_candidate_row(weak_candidate, game, character) is state
    next_state = state.with_candidate_row(strong_candidate, game, character)
    assert next_state is not state
    assert next_state.signature != state.signature
    assert next_state.best_loadout_value(game, character) > state.best_loadout_value(game, character)


def _assert_vector_close(left, right):
    assert len(left) == len(right)
    for left_value, right_value in zip(left, right):
        assert left_value == pytest.approx(right_value)


def test_state_action_value_matches_inventory_recursion_for_generation_specs():
    game = _two_slot_game()
    character = _two_slot_character()
    probability_model = _two_slot_probability(game.id)
    inventory = [
        _gear_piece(1, "A", rolls=0),
        _gear_piece(2, "A", rolls=0),
    ]
    rows = inventory_rows_from_pieces(inventory, game, character, current_count=2)
    state = EvState.from_rows(rows, game, character)
    specs = [
        ActionSpec("随机位置", "A", ("A",), None),
        ActionSpec("固定位置", "A", ("A",), 1),
        ActionSpec("固定位置 + 固定主属性", "A", ("A",), 1, fixed_main_stat="main1"),
        ActionSpec(
            "固定位置 + 固定主属性 + 固定副属性",
            "A",
            ("A",),
            1,
            fixed_main_stat="main1",
            required_substats=("good",),
        ),
    ]

    for spec in specs:
        old_value = position_ev._expected_action_value(
            rows,
            game,
            character,
            probability_model,
            spec,
            1,
            memo={},
            quality_cache={},
        )
        new_value = expected_state_action_value(
            state,
            game,
            character,
            probability_model,
            spec,
            1,
            memo={},
            quality_cache={},
        )
        _assert_vector_close(new_value, old_value)


def test_state_action_value_matches_inventory_recursion_for_upgrade_source():
    game = _two_slot_game(max_level=3)
    character = _two_slot_character()
    probability_model = _two_slot_probability(game.id)
    current = [
        _gear_piece(1, "A", rolls=0, level=3),
        _gear_piece(2, "A", rolls=0, level=3),
    ]
    embryo = _gear_piece(1, "A", rolls=1, level=0)
    rows = inventory_rows_from_pieces([*current, embryo], game, character, current_count=2)
    state = EvState.from_rows(rows, game, character)
    spec = ActionSpec(
        "强化库存胚子",
        "A",
        upgrade_inventory_id="piece:2",
    )

    old_value = position_ev._expected_action_value(
        rows,
        game,
        character,
        probability_model,
        spec,
        1,
        memo={},
        quality_cache={},
    )
    new_value = expected_state_action_value(
        state,
        game,
        character,
        probability_model,
        spec,
        1,
        memo={},
        quality_cache={},
    )

    _assert_vector_close(new_value, old_value)


def test_lookahead_state_value_matches_inventory_recursion_for_horizon_two():
    game = _two_slot_game()
    character = _two_slot_character()
    probability_model = _two_slot_probability(game.id)
    inventory = [
        _gear_piece(1, "A", rolls=0),
        _gear_piece(2, "A", rolls=0),
    ]
    rows = inventory_rows_from_pieces(inventory, game, character, current_count=2)

    old_value = lookahead_inventory_value(
        rows,
        game,
        character,
        probability_model,
        horizon=2,
        memo={},
        quality_cache={},
    )
    new_value = lookahead_inventory_value_state_dp(
        rows,
        game,
        character,
        probability_model,
        horizon=2,
        memo={},
    )

    _assert_vector_close(new_value, old_value)


def test_position_strategy_rows_match_with_state_dp_for_horizon_one_and_two():
    game = _two_slot_game()
    character = _two_slot_character()
    probability_model = _two_slot_probability(game.id)
    inventory = [
        _gear_piece(1, "A", rolls=0),
        _gear_piece(2, "A", rolls=0),
    ]
    analysis = analyse_current_gear(inventory, game, character)
    compare_columns = [
        "策略",
        "目标套装",
        "位置",
        "主属性",
        "固定副属性",
        "horizon",
        "期望提升",
        "质量/母盘",
        "有效/母盘",
        "相对随机",
        "套装约束",
    ]

    for horizon in (1, 2):
        position_ev._ACTION_EV_ROWS_CACHE.clear()
        position_ev._STATE_TRANSITION_CACHE.clear()
        old_rows = position_strategy_efficiency_rows(
            game,
            character,
            probability_model,
            analysis,
            inventory_pieces=inventory,
            horizon=horizon,
        )
        position_ev._ACTION_EV_ROWS_CACHE.clear()
        position_ev._STATE_TRANSITION_CACHE.clear()
        new_rows = position_strategy_efficiency_rows(
            game,
            character,
            probability_model,
            analysis,
            inventory_pieces=inventory,
            horizon=horizon,
            use_state_dp=True,
        )
        assert len(new_rows) == len(old_rows)
        for old_row, new_row in zip(old_rows, new_rows):
            assert {column: new_row[column] for column in compare_columns} == {
                column: old_row[column] for column in compare_columns
            }


def test_action_ev_engine_compare_report_matches_golden_case():
    game = _two_slot_game()
    character = _two_slot_character()
    probability_model = _two_slot_probability(game.id)
    inventory = [
        _gear_piece(1, "A", rolls=0),
        _gear_piece(2, "A", rolls=0),
    ]
    analysis = analyse_current_gear(inventory, game, character)

    position_ev._ACTION_EV_ROWS_CACHE.clear()
    position_ev._STATE_TRANSITION_CACHE.clear()
    report = compare_action_ev_engines(
        game,
        character,
        probability_model,
        analysis,
        inventory_pieces=inventory,
        horizon=1,
    )

    assert report["consistent"] is True
    assert report["recommendation_consistent"] is True
    assert report["top_10_order_consistent"] is True
    assert report["core_ev_consistent"] is True
    assert report["row_counts"]["inventory_recursive"] == report["row_counts"]["state_dp"]
    assert report["elapsed_seconds"]["inventory_recursive"] >= 0
    assert report["elapsed_seconds"]["state_dp"] >= 0
    assert report["top_10"]["inventory_recursive"] == report["top_10"]["state_dp"]
    assert "core EV values match" in report["diff_report"]


def test_state_dp_action_rows_emit_transition_progress():
    game = _two_slot_game()
    character = _two_slot_character()
    probability_model = _two_slot_probability(game.id)
    inventory = [
        _gear_piece(1, "A", rolls=0),
        _gear_piece(2, "A", rolls=0),
    ]
    analysis = analyse_current_gear(inventory, game, character)
    events = []

    position_ev._ACTION_EV_ROWS_CACHE.clear()
    position_ev._STATE_TRANSITION_CACHE.clear()
    position_strategy_efficiency_rows(
        game,
        character,
        probability_model,
        analysis,
        inventory_pieces=inventory,
        horizon=1,
        progress_callback=events.append,
        use_state_dp=True,
    )

    assert any(
        event.get("event") == "unit_progress"
        and event.get("inner_event") == "state_transition_cache_miss"
        for event in events
    )
    assert any("state_transition_cache_misses" in event for event in events)


def test_parallel_state_action_values_match_single_worker(monkeypatch):
    game = _two_slot_game()
    character = _two_slot_character()
    probability_model = _two_slot_probability(game.id)
    inventory = [
        _gear_piece(1, "A", rolls=0),
        _gear_piece(2, "A", rolls=0),
    ]
    rows = inventory_rows_from_pieces(inventory, game, character, current_count=2)
    state = EvState.from_rows(rows, game, character)
    specs = [
        ActionSpec("随机位置", "A", ("A",), None),
        ActionSpec("固定位置", "A", ("A",), 1),
    ]

    single = parallel_expected_state_action_values(
        state,
        game,
        character,
        probability_model,
        specs,
        horizon=1,
        workers=1,
    )
    parallel = parallel_expected_state_action_values(
        state,
        game,
        character,
        probability_model,
        specs,
        horizon=1,
        workers=2,
    )

    assert [result.error for result in single] == [None, None]
    assert [result.error for result in parallel] == [None, None]
    for left, right in zip(single, parallel):
        assert left.spec == right.spec
        _assert_vector_close(left.value, right.value)

    monkeypatch.setenv("GEAR_OPTIMIZER_WORKERS", "2")
    assert configured_action_ev_workers() == 2


def test_parallel_state_action_worker_error_does_not_return_value():
    game = _two_slot_game()
    character = _two_slot_character()
    probability_model = _two_slot_probability(game.id)
    rows = inventory_rows_from_pieces(
        [_gear_piece(1, "A", rolls=0), _gear_piece(2, "A", rolls=0)],
        game,
        character,
        current_count=2,
    )
    state = EvState.from_rows(rows, game, character)
    bad_spec = ActionSpec(
        "固定位置",
        "A",
        ("A",),
        target_position=999,
    )

    [result] = parallel_expected_state_action_values(
        state,
        game,
        character,
        probability_model,
        [bad_spec],
        horizon=1,
        workers=2,
    )

    assert result.spec == bad_spec
    assert result.value == ()
    assert result.error
