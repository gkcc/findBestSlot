import pytest

import gear_optimizer.position_ev as position_ev
from gear_optimizer.models import (
    CharacterPreset,
    EnhancementRule,
    GameRules,
    GearPiece,
    PositionRule,
    SetPlan,
    SetRequirement,
    SubstatLine,
    SubstatPriority,
)
from gear_optimizer.position_ev import EvState, best_loadout_rows, best_loadout_value


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
        sub_stats=["good", "bad"],
        main_stat_probabilities={"1": {"main1": 1.0}, "2": {"main2": 1.0}},
        sub_stat_probabilities={"good": 1.0, "bad": 1.0},
        enhancement=EnhancementRule(max_level=max_level, step=3, initial_add_level=3),
    )


def _two_slot_character():
    return CharacterPreset(
        id="two_char",
        game="two",
        name="Two Char",
        target_set="A",
        substat_priority=SubstatPriority(core=["good"], usable=[]),
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
