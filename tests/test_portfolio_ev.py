import pytest

import gear_optimizer.portfolio_ev as portfolio_ev
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
from gear_optimizer.portfolio_ev import (
    PortfolioAuditCancelled,
    _portfolio_delta_scalar,
    portfolio_action_rows,
    portfolio_piece_check_rows,
)
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


def _build_progress_game() -> GameRules:
    return GameRules(
        id="portfolio",
        name="Portfolio",
        gear_name="Disk",
        sets=["X", "Y"],
        positions=[
            PositionRule(id=1, name="1号位", main_stats=["main"]),
            PositionRule(id=2, name="2号位", main_stats=["main"]),
            PositionRule(id=3, name="3号位", main_stats=["main"]),
            PositionRule(id=4, name="4号位", main_stats=["atk", "hp", "def"]),
        ],
        sub_stats=["good", "bad1", "bad2", "bad3"],
        main_stat_probabilities={
            "1": {"main": 1.0},
            "2": {"main": 1.0},
            "3": {"main": 1.0},
            "4": {"atk": 1.0, "hp": 0.0, "def": 0.0},
        },
        sub_stat_probabilities={"good": 1.0, "bad1": 1.0, "bad2": 1.0, "bad3": 1.0},
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


def _build_character() -> CharacterPreset:
    return CharacterPreset(
        id="build_template",
        game="portfolio",
        name="建设代理",
        target_set="X",
        substat_priority=SubstatPriority(core=["good"], usable=[]),
        preferred_main_stats={
            "1": ["main"],
            "2": ["main"],
            "3": ["main"],
            "4": ["atk"],
        },
        set_plans=[
            SetPlan(
                id="x4",
                name="X4",
                requirements=[SetRequirement(set_name="X", pieces=4)],
            )
        ],
        default_set_plan="x4",
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


def _build_piece(
    position: int,
    *,
    set_name: str = "X",
    main_stat: str = "main",
    good_rolls: int = 0,
    include_good: bool = True,
) -> GearPiece:
    substats = (
        [
            SubstatLine(stat="good", rolls=good_rolls),
            SubstatLine(stat="bad1", rolls=0),
            SubstatLine(stat="bad2", rolls=0),
        ]
        if include_good
        else [
            SubstatLine(stat="bad1", rolls=0),
            SubstatLine(stat="bad2", rolls=0),
            SubstatLine(stat="bad3", rolls=0),
        ]
    )
    return GearPiece(
        position=position,
        set_name=set_name,
        main_stat=main_stat,
        level=0,
        substats=substats,
        initial_substat_count=3,
    )


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


def _fixed_position_row(rows, position: int):
    return next(
        row
        for row in rows
        if row.action_spec.strategy == "固定位置"
        and row.action_spec.target_position == position
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
    assert "建设审计单独展示" in display["模式说明"]
    assert display["至少一人成型收益概率"] == "100.0%"
    assert "建设方向推进概率" in display
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


def test_portfolio_audit_can_be_cancelled_cooperatively():
    game = _portfolio_game()
    probability = ProbabilityModel(id="p", game="portfolio", name="P")
    character = _portfolio_character("agent_template", "代理", "atk", "good")
    target = PortfolioTarget(agent_id="agent", name="代理", character=character)

    with pytest.raises(PortfolioAuditCancelled):
        portfolio_action_rows(
            game,
            probability,
            [target],
            _current_pieces(),
            [],
            should_cancel=lambda: True,
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


def test_portfolio_default_scope_excludes_inventory_upgrades_and_fixed_substats():
    game = _upgrade_portfolio_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )
    unfinished = GearPiece(
        position=2,
        set_name="A",
        main_stat="atk",
        level=0,
        substats=[
            SubstatLine(stat="good_a", rolls=0),
            SubstatLine(stat="bad1", rolls=0),
            SubstatLine(stat="bad2", rolls=0),
        ],
        initial_substat_count=3,
    )

    rows = portfolio_action_rows(
        game,
        probability,
        [_targets()[0]],
        _current_pieces(),
        [unfinished],
        mode=PortfolioMode.ANY_USEFUL,
    )

    strategies = {row.action_spec.strategy for row in rows}
    assert "强化库存胚子" not in strategies
    assert "固定位置 + 固定主属性" in strategies
    assert "固定位置 + 固定主属性 + 固定副属性" not in strategies

    upgrade_rows = portfolio_action_rows(
        game,
        probability,
        [_targets()[0]],
        _current_pieces(),
        [unfinished],
        mode=PortfolioMode.ANY_USEFUL,
        action_scope="upgrade",
    )
    assert upgrade_rows
    assert {row.action_spec.strategy for row in upgrade_rows} == {"强化库存胚子"}


def test_portfolio_does_not_recount_main_match_when_better_same_slot_exists():
    game = _build_progress_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )
    character = _build_character()
    target = PortfolioTarget(agent_id="agent", name="建设代理", character=character)
    complete_pool = [
        _build_piece(1),
        _build_piece(2),
        _build_piece(3),
        _build_piece(4, main_stat="atk", good_rolls=3),
    ]

    row = _fixed_position_row(
        portfolio_action_rows(
            game,
            probability,
            [target],
            complete_pool,
            mode=PortfolioMode.ANY_USEFUL,
        ),
        4,
    )

    assert row.portfolio_ev == pytest.approx(0.0)
    assert row.useful_probability == pytest.approx(0.0)
    assert row.target_gains[0].immediate_gain == pytest.approx(0.0)
    assert row.build_progress_gain == pytest.approx(0.0)
    assert "已有更优或等价" in row.set_progress_detail


def test_portfolio_zero_current_uses_global_pool_for_immediate_best_loadout_gain():
    game = _build_progress_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )
    character = _build_character()
    target = PortfolioTarget(
        agent_id="agent",
        name="建设代理",
        character=character,
        current_pieces=[],
    )
    inventory = [
        _build_piece(1),
        _build_piece(2),
        _build_piece(3),
        _build_piece(4, main_stat="atk", include_good=False),
    ]

    row = _fixed_position_row(
        portfolio_action_rows(
            game,
            probability,
            [target],
            [],
            inventory,
            mode=PortfolioMode.ANY_USEFUL,
        ),
        4,
    )

    assert row.portfolio_ev > 0
    assert row.target_gains[0].immediate_gain > 0
    assert row.build_progress_gain == pytest.approx(0.0)


def test_portfolio_zero_current_incomplete_pool_reports_build_progress_only():
    game = _build_progress_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )
    character = _build_character()
    target = PortfolioTarget(
        agent_id="agent",
        name="建设代理",
        character=character,
        current_pieces=[],
    )

    row = _fixed_position_row(
        portfolio_action_rows(
            game,
            probability,
            [target],
            [],
            [_build_piece(1)],
            mode=PortfolioMode.ANY_USEFUL,
        ),
        2,
    )

    assert row.portfolio_ev == pytest.approx(0.0)
    assert row.useful_probability == pytest.approx(0.0)
    assert row.build_progress_probability > 0
    assert row.build_progress_gain > 0
    assert "覆盖缺失位置" in row.position_coverage_detail
    assert "命中目标主属性" in row.main_stat_hit_detail
    assert "当前可行1件，加入后可行2件" in row.set_progress_detail


def test_portfolio_incomplete_pool_outcome_that_completes_loadout_counts_as_main_ev():
    game = _build_progress_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )
    character = _build_character()
    target = PortfolioTarget(
        agent_id="agent",
        name="成型代理",
        character=character,
        current_pieces=[],
    )

    row = _fixed_position_row(
        portfolio_action_rows(
            game,
            probability,
            [target],
            [],
            [_build_piece(1), _build_piece(2), _build_piece(3)],
            mode=PortfolioMode.ANY_USEFUL,
        ),
        4,
    )

    assert row.portfolio_ev > 0
    assert row.useful_probability == pytest.approx(1.0)
    assert row.target_gains[0].immediate_gain > 0
    assert row.target_gains[0].entered_best_loadout_probability == pytest.approx(1.0)
    assert row.build_progress_gain == pytest.approx(0.0)
    assert row.to_recommendation_row()["建设提示"] == "-"
    assert "best_loadout 有正提升" in row.to_recommendation_row()["说明"]


def test_portfolio_unfinished_pieces_count_toward_box_loadout_frontier():
    game = _build_progress_game().model_copy(
        update={"enhancement": EnhancementRule(max_level=3, step=3, initial_add_level=3)}
    )
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )
    character = _build_character()
    target = PortfolioTarget(
        agent_id="agent",
        name="胚子代理",
        character=character,
        current_pieces=[],
    )

    row = _fixed_position_row(
        portfolio_action_rows(
            game,
            probability,
            [target],
            [],
            [
                _build_piece(1, good_rolls=0),
                _build_piece(2, good_rolls=0),
                _build_piece(3, good_rolls=0),
            ],
            mode=PortfolioMode.ANY_USEFUL,
        ),
        4,
    )

    assert row.portfolio_ev > 0
    assert row.useful_probability == pytest.approx(1.0)
    assert row.target_gains[0].immediate_gain > 0
    assert row.build_progress_gain == pytest.approx(0.0)


def test_portfolio_missing_slot_that_completes_four_plus_two_outranks_other_positions():
    game = GameRules(
        id="portfolio",
        name="Portfolio",
        gear_name="Disk",
        sets=["X", "Y", "OffPlan"],
        positions=[
            PositionRule(id=position, name=f"{position}号位", main_stats=["main"])
            for position in range(1, 7)
        ],
        sub_stats=["good", "bad1", "bad2", "bad3"],
        main_stat_probabilities={
            str(position): {"main": 1.0}
            for position in range(1, 7)
        },
        sub_stat_probabilities={"good": 1.0, "bad1": 1.0, "bad2": 1.0, "bad3": 1.0},
        enhancement=EnhancementRule(max_level=3, step=3, initial_add_level=3),
    )
    character = CharacterPreset(
        id="four_plus_two",
        game="portfolio",
        name="缺五号位代理",
        target_set="X",
        substat_priority=SubstatPriority(core=["good"], usable=[]),
        preferred_main_stats={str(position): ["main"] for position in range(1, 7)},
        set_plans=[
            SetPlan(
                id="x4_y2",
                name="X4 + Y2",
                requirements=[
                    SetRequirement(set_name="X", pieces=4),
                    SetRequirement(set_name="Y", pieces=2),
                ],
            )
        ],
        default_set_plan="x4_y2",
    )
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )

    def piece(position: int, set_name: str) -> GearPiece:
        return GearPiece(
            position=position,
            set_name=set_name,
            main_stat="main",
            level=0,
            substats=[
                SubstatLine(stat="good", rolls=0),
                SubstatLine(stat="bad1", rolls=0),
                SubstatLine(stat="bad2", rolls=0),
            ],
            initial_substat_count=3,
        )

    current = [
        piece(1, "Y"),
        piece(2, "X"),
        piece(3, "Y"),
        piece(4, "X"),
        piece(6, "X"),
    ]
    inventory = [
        piece(1, "X"),
        piece(5, "OffPlan"),
    ]
    target = PortfolioTarget(
        agent_id="agent",
        name="缺五号位代理",
        character=character,
        current_pieces=current,
    )

    rows = portfolio_action_rows(
        game,
        probability,
        [target],
        current,
        inventory,
        mode=PortfolioMode.ANY_USEFUL,
    )
    x_slot_3 = next(
        row
        for row in rows
        if row.action_spec.strategy == "固定位置"
        and row.action_spec.set_options == ("X",)
        and row.action_spec.target_position == 3
    )
    x_slot_5 = next(
        row
        for row in rows
        if row.action_spec.strategy == "固定位置"
        and row.action_spec.set_options == ("X",)
        and row.action_spec.target_position == 5
    )
    y_slot_5 = next(
        row
        for row in rows
        if row.action_spec.strategy == "固定位置"
        and row.action_spec.set_options == ("Y",)
        and row.action_spec.target_position == 5
    )

    assert x_slot_3.portfolio_ev == pytest.approx(0.0)
    assert x_slot_3.completion_probability == pytest.approx(0.0)
    assert x_slot_5.portfolio_ev > 0
    assert x_slot_5.useful_probability == pytest.approx(1.0)
    assert x_slot_5.completion_probability == pytest.approx(1.0)
    assert x_slot_5.direct_completion_probability == pytest.approx(1.0)
    assert x_slot_5.target_gains[0].baseline_complete is False
    assert x_slot_5.target_gains[0].completion_probability == pytest.approx(1.0)
    assert x_slot_5.target_gains[0].direct_completion_probability == pytest.approx(1.0)
    assert "当前装备 5/6（缺5号位）" in x_slot_5.baseline_summary
    assert "可直接补齐当前盘面" in x_slot_5.to_recommendation_row()["说明"]
    assert "可直接补当前盘面成型" in x_slot_5.completion_path_detail
    assert y_slot_5.portfolio_ev == pytest.approx(x_slot_5.portfolio_ev)
    assert y_slot_5.completion_probability == pytest.approx(1.0)
    assert y_slot_5.direct_completion_probability == pytest.approx(0.0)
    assert "不能直接接入当前盘面" in y_slot_5.completion_path_detail
    assert "需调用背包候选重配" in y_slot_5.to_recommendation_row()["说明"]
    assert rows.index(x_slot_5) < rows.index(y_slot_5)
    assert rows[0].action_spec.target_position == 5


def test_portfolio_missing_slot_only_counts_target_main_outcomes_as_completed_gain():
    game = _build_progress_game().model_copy(
        update={
            "main_stat_probabilities": {
                "1": {"main": 1.0},
                "2": {"main": 1.0},
                "3": {"main": 1.0},
                "4": {"atk": 0.5, "hp": 0.5, "def": 0.0},
            }
        }
    )
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )
    character = _build_character()
    current = [_build_piece(1), _build_piece(2), _build_piece(3)]
    target = PortfolioTarget(
        agent_id="agent",
        name="缺四号位代理",
        character=character,
        current_pieces=current,
    )

    rows = portfolio_action_rows(
        game,
        probability,
        [target],
        current,
        [],
        mode=PortfolioMode.ANY_USEFUL,
    )
    random_main = next(
        row
        for row in rows
        if row.action_spec.strategy == "固定位置"
        and row.action_spec.target_position == 4
    )
    fixed_main = next(
        row
        for row in rows
        if row.action_spec.strategy == "固定位置 + 固定主属性"
        and row.action_spec.target_position == 4
        and row.action_spec.fixed_main_stat == "atk"
    )

    assert random_main.useful_probability == pytest.approx(0.5)
    assert random_main.completion_probability == pytest.approx(0.5)
    assert random_main.direct_completion_probability == pytest.approx(0.5)
    assert random_main.portfolio_ev == pytest.approx(fixed_main.portfolio_ev * 0.5)
    assert random_main.conditional_gain == pytest.approx(fixed_main.conditional_gain)
    assert fixed_main.useful_probability == pytest.approx(1.0)
    assert fixed_main.completion_probability == pytest.approx(1.0)
    assert fixed_main.direct_completion_probability == pytest.approx(1.0)
    assert random_main.to_recommendation_row()["命中后增益"] > 0
    assert random_main.to_recommendation_row()["资源成本"] == "母盘 6"
    assert fixed_main.to_recommendation_row()["资源成本"] == "母盘 6 + 调律器 1"


def test_portfolio_full_fallback_without_target_plan_is_not_main_ev_baseline():
    game = _build_progress_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )
    character = _build_character()
    target = PortfolioTarget(agent_id="agent", name="目标套装代理", character=character)

    row = _fixed_position_row(
        portfolio_action_rows(
            game,
            probability,
            [target],
            [],
            [
                _build_piece(1),
                _build_piece(2),
                _build_piece(3, set_name="Y"),
                _build_piece(4),
            ],
            mode=PortfolioMode.ANY_USEFUL,
        ),
        3,
    )

    assert row.portfolio_ev > 0
    assert row.useful_probability == pytest.approx(1.0)
    assert row.build_progress_gain == pytest.approx(0.0)
    assert row.to_recommendation_row()["建设提示"] == "-"


def test_portfolio_incomplete_pool_does_not_expand_full_substat_outcomes(monkeypatch):
    game = _build_progress_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )
    character = _build_character()
    target = PortfolioTarget(
        agent_id="agent",
        name="建设代理",
        character=character,
        current_pieces=[],
    )

    def fail_raw_distribution(*_args, **_kwargs):
        raise AssertionError("incomplete BOX build audit should not expand full substat outcomes")

    monkeypatch.setattr(portfolio_ev, "_raw_outcome_piece_distribution", fail_raw_distribution)

    row = _fixed_position_row(
        portfolio_ev.portfolio_action_rows(
            game,
            probability,
            [target],
            [],
            [_build_piece(1)],
            mode=PortfolioMode.ANY_USEFUL,
        ),
        2,
    )

    assert row.portfolio_ev == pytest.approx(0.0)
    assert row.build_progress_gain > 0
    assert "当前可行1件，加入后可行2件" in row.set_progress_detail


def test_portfolio_set_frontier_progress_does_not_affect_main_sort_value():
    game = _build_progress_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )
    character = _build_character()
    target = PortfolioTarget(agent_id="agent", name="建设代理", character=character)

    row = _fixed_position_row(
        portfolio_action_rows(
            game,
            probability,
            [target],
            [_build_piece(1)],
            [],
            mode=PortfolioMode.ANY_USEFUL,
        ),
        2,
    )

    assert row.portfolio_ev == pytest.approx(0.0)
    assert row.ev_per_mother == pytest.approx(0.0)
    assert row.build_progress_probability > 0
    assert "当前可行1件，加入后可行2件" in row.set_progress_detail


def test_portfolio_zero_main_ev_tie_prefers_lower_mother_cost():
    game = _build_progress_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
        resource_costs={
            "mother_disk_random_position_attempt": 3.0,
            "mother_disk_fixed_position_attempt": 6.0,
        },
    )
    character = _build_character()
    target = PortfolioTarget(agent_id="agent", name="建设代理", character=character)

    rows = portfolio_action_rows(
        game,
        probability,
        [target],
        [_build_piece(1)],
        [],
        mode=PortfolioMode.ANY_USEFUL,
    )

    assert rows[0].portfolio_ev == pytest.approx(0.0)
    assert rows[0].action_spec.strategy == "随机位置"
    assert rows[0].mother_cost == pytest.approx(3.0)
    assert any(
        row.action_spec.strategy == "固定位置" and row.mother_cost == pytest.approx(6.0)
        for row in rows
    )


def test_portfolio_fake_set_progress_is_not_counted():
    game = _build_progress_game()
    probability = ProbabilityModel(
        id="p",
        game="portfolio",
        name="P",
        target_set_probability=1.0,
        initial_substat_count_probabilities={"3": 1.0, "4": 0.0},
    )
    character = _build_character()
    target = PortfolioTarget(
        agent_id="agent",
        name="建设代理",
        character=character,
        current_pieces=[],
    )

    row = _fixed_position_row(
        portfolio_action_rows(
            game,
            probability,
            [target],
            [],
            [_build_piece(1), _build_piece(2, good_rolls=3)],
            mode=PortfolioMode.ANY_USEFUL,
        ),
        2,
    )

    assert row.portfolio_ev == pytest.approx(0.0)
    assert row.build_progress_gain == pytest.approx(0.0)
    assert "已有更优或等价" in row.set_progress_detail


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


def test_portfolio_piece_check_separates_unfinished_piece_immediate_and_upgrade_value():
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
