import pytest

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
from gear_optimizer.portfolio_ev import _portfolio_delta_scalar, portfolio_action_rows, portfolio_piece_check_rows
from gear_optimizer.portfolio_models import PortfolioMode, PortfolioTarget
from gear_optimizer.position_ev import ActionSpec, action_gain_for_spec


def _portfolio_game() -> GameRules:
    return GameRules(
        id="portfolio",
        name="Portfolio",
        gear_name="Disk",
        sets=["A"],
        positions=[
            PositionRule(id=1, name="1号位", main_stats=["main1"]),
            PositionRule(id=2, name="2号位", main_stats=["atk", "hp", "def"]),
        ],
        sub_stats=["bad1", "bad2", "bad3"],
        main_stat_probabilities={
            "1": {"main1": 1.0},
            "2": {"atk": 0.5, "hp": 0.5, "def": 0.0},
        },
        sub_stat_probabilities={"bad1": 1.0, "bad2": 1.0, "bad3": 1.0},
        enhancement=EnhancementRule(max_level=0, step=3, initial_add_level=3),
    )


def _upgrade_portfolio_game() -> GameRules:
    return GameRules(
        id="portfolio",
        name="Portfolio",
        gear_name="Disk",
        sets=["A"],
        positions=[
            PositionRule(id=1, name="1号位", main_stats=["main1"]),
            PositionRule(id=2, name="2号位", main_stats=["atk", "hp", "def"]),
        ],
        sub_stats=["good_a", "good_b", "bad1", "bad2", "bad3"],
        main_stat_probabilities={
            "1": {"main1": 1.0},
            "2": {"atk": 0.5, "hp": 0.5, "def": 0.0},
        },
        sub_stat_probabilities={
            "good_a": 1.0,
            "good_b": 1.0,
            "bad1": 1.0,
            "bad2": 1.0,
            "bad3": 1.0,
        },
        enhancement=EnhancementRule(max_level=3, step=3, initial_add_level=3),
    )


def _portfolio_character(character_id: str, name: str, main2: str, good_stat: str) -> CharacterPreset:
    return CharacterPreset(
        id=character_id,
        game="portfolio",
        name=name,
        target_set="A",
        substat_priority=SubstatPriority(core=[good_stat], usable=[]),
        preferred_main_stats={"1": ["main1"], "2": [main2]},
        set_plans=[
            SetPlan(
                id="a2",
                name="A2",
                requirements=[SetRequirement(set_name="A", pieces=2)],
            )
        ],
        default_set_plan="a2",
    )


def _current_pieces() -> list[GearPiece]:
    return [
        GearPiece(
            position=1,
            set_name="A",
            main_stat="main1",
            level=0,
            substats=[SubstatLine(stat="bad1", rolls=0)],
            initial_substat_count=3,
        ),
        GearPiece(
            position=2,
            set_name="A",
            main_stat="def",
            level=0,
            substats=[SubstatLine(stat="bad1", rolls=0)],
            initial_substat_count=3,
        ),
    ]


def _targets(weight_a: float = 1.0, weight_b: float = 1.0) -> list[PortfolioTarget]:
    char_a = _portfolio_character("agent_a_template", "攻百代理", "atk", "good_a")
    char_b = _portfolio_character("agent_b_template", "生百代理", "hp", "good_b")
    return [
        PortfolioTarget(agent_id="agent_a", name="攻百代理", character=char_a, weight=weight_a),
        PortfolioTarget(agent_id="agent_b", name="生百代理", character=char_b, weight=weight_b),
    ]


def _fixed_position_2_row(rows):
    return next(
        row
        for row in rows
        if row.action_spec.strategy == "固定位置"
        and row.action_spec.target_position == 2
    )


def test_portfolio_any_useful_counts_complementary_main_stat_outcomes():
    game = _portfolio_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )

    row = _fixed_position_2_row(
        portfolio_action_rows(
            game,
            probability,
            _targets(),
            _current_pieces(),
            mode=PortfolioMode.ANY_USEFUL,
        )
    )

    assert row.mode == PortfolioMode.ANY_USEFUL
    assert row.portfolio_ev == pytest.approx(1.0)
    assert row.ev_per_mother == pytest.approx(1.0 / 6.0, abs=1e-6)
    assert row.useful_probability == pytest.approx(1.0)
    assert row.beneficiary_count == 2
    assert {gain.name: gain.expected_gain for gain in row.target_gains} == {
        "攻百代理": pytest.approx(0.5),
        "生百代理": pytest.approx(0.5),
    }
    display = row.to_display_row()
    assert display["模式"] == "任一代理人有用"
    assert "best_loadout_value 的正 delta" in display["模式说明"]
    assert "不按主属性/副词条粗判" in display["模式说明"]
    assert row.entered_best_loadout_summary == "攻百代理 50.0%；生百代理 50.0%"
    assert display["outcome 入选更优搭配"] == row.entered_best_loadout_summary
    assert {gain.name: gain.entered_best_loadout_probability for gain in row.target_gains} == {
        "攻百代理": pytest.approx(0.5),
        "生百代理": pytest.approx(0.5),
    }


def test_portfolio_weighted_sum_applies_target_weights_per_outcome():
    game = _portfolio_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )

    row = _fixed_position_2_row(
        portfolio_action_rows(
            game,
            probability,
            _targets(weight_a=2.0, weight_b=1.0),
            _current_pieces(),
            mode=PortfolioMode.WEIGHTED_SUM,
        )
    )

    assert row.portfolio_ev == pytest.approx(1.5)
    assert row.ev_per_mother == pytest.approx(1.5 / 6.0, abs=1e-6)
    assert row.useful_probability == pytest.approx(1.0)
    assert row.mode_note.startswith("WEIGHTED_SUM")


def test_portfolio_useful_probability_is_not_suppressed_by_zero_weight():
    game = _portfolio_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )

    row = _fixed_position_2_row(
        portfolio_action_rows(
            game,
            probability,
            _targets(weight_a=0.0, weight_b=0.0),
            _current_pieces(),
            mode=PortfolioMode.WEIGHTED_SUM,
        )
    )

    assert row.portfolio_ev == pytest.approx(0.0)
    assert row.useful_probability == pytest.approx(1.0)
    assert row.beneficiary_count == 2


def test_portfolio_rejects_horizon_two_in_phase_one():
    with pytest.raises(ValueError, match="only supports horizon=1"):
        portfolio_action_rows(
            _portfolio_game(),
            ProbabilityModel(id="p", game="portfolio", name="P"),
            _targets(),
            _current_pieces(),
            horizon=2,
        )


def test_single_target_portfolio_matches_existing_horizon_one_scalar_for_same_action():
    game = _portfolio_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )
    target = _targets()[0]
    spec = ActionSpec("固定位置", "A", ("A",), 2)

    row = _fixed_position_2_row(
        portfolio_action_rows(
            game,
            probability,
            [target],
            _current_pieces(),
            mode=PortfolioMode.ANY_USEFUL,
        )
    )
    gain = action_gain_for_spec(
        _current_pieces(),
        game,
        target.character,
        probability,
        spec,
        horizon=1,
    )
    expected_scalar = _portfolio_delta_scalar(gain)

    assert row.portfolio_ev == pytest.approx(expected_scalar)
    assert row.target_gains[0].expected_gain == pytest.approx(expected_scalar)


def test_portfolio_piece_check_reports_immediate_gain_for_actual_drop():
    game = _portfolio_game()
    probability = ProbabilityModel(id="p", game="portfolio", name="P")
    piece = GearPiece(
        position=2,
        set_name="A",
        main_stat="atk",
        level=0,
        substats=[SubstatLine(stat="bad1", rolls=0)],
        initial_substat_count=3,
    )

    rows = portfolio_piece_check_rows(
        game,
        probability,
        _targets(),
        _current_pieces(),
        [],
        piece,
    )

    by_name = {row.name: row for row in rows}
    assert by_name["攻百代理"].immediate_gain > 0
    assert by_name["攻百代理"].upgrade_expected_gain == by_name["攻百代理"].immediate_gain
    assert by_name["攻百代理"].worth_observing is True
    assert by_name["生百代理"].immediate_gain == pytest.approx(0.0)


def test_portfolio_piece_check_keeps_unfinished_piece_out_of_loadout_but_values_upgrade():
    game = _upgrade_portfolio_game()
    probability = ProbabilityModel(id="p", game="portfolio", name="P")
    piece = GearPiece(
        position=2,
        set_name="A",
        main_stat="def",
        level=0,
        substats=[
            SubstatLine(stat="bad1", rolls=0),
            SubstatLine(stat="bad2", rolls=0),
            SubstatLine(stat="bad3", rolls=0),
        ],
        initial_substat_count=3,
    )
    current_pieces = [
        piece.model_copy(update={"level": game.enhancement.max_level})
        for piece in _current_pieces()
    ]

    rows = portfolio_piece_check_rows(
        game,
        probability,
        _targets(),
        current_pieces,
        [],
        piece,
    )

    by_name = {row.name: row for row in rows}
    assert by_name["攻百代理"].immediate_gain == pytest.approx(0.0)
    assert by_name["攻百代理"].upgrade_expected_gain > 0
    assert by_name["攻百代理"].upgrade_observation_gain > 0
    assert by_name["攻百代理"].worth_observing is True
    assert by_name["生百代理"].immediate_gain == pytest.approx(0.0)
    assert by_name["生百代理"].upgrade_expected_gain > 0
