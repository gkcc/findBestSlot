import pytest

from gear_optimizer.action_types import (
    ActionEvEngine,
    ActionEvLookaheadScope,
    ActionEvMode,
    PortfolioActionScope,
    normalize_action_ev_engine,
    normalize_action_ev_lookahead_scope,
    normalize_action_ev_mode,
    normalize_portfolio_action_scope,
)


def test_action_protocol_enums_keep_stable_string_values():
    assert ActionEvMode.FAST == "fast"
    assert ActionEvEngine.STATE_DP == "state_dp"
    assert ActionEvLookaheadScope.TUNING_STATIC == "tuning_static"
    assert PortfolioActionScope.TUNING == "tuning"


def test_action_protocol_normalizers_handle_aliases_and_reject_unknown_values():
    assert normalize_action_ev_mode("quick") is ActionEvMode.FAST
    assert normalize_action_ev_mode("full") is ActionEvMode.EXACT
    assert normalize_action_ev_engine("STATE_DP") is ActionEvEngine.STATE_DP
    assert (
        normalize_action_ev_lookahead_scope("TUNING_STATIC")
        is ActionEvLookaheadScope.TUNING_STATIC
    )
    assert normalize_portfolio_action_scope("upgrade") is PortfolioActionScope.UPGRADE

    with pytest.raises(ValueError, match="Unknown Action EV mode"):
        normalize_action_ev_mode("mystery")
    with pytest.raises(ValueError, match="Unknown Action EV engine"):
        normalize_action_ev_engine("mystery")
    with pytest.raises(ValueError, match="Unknown Action EV lookahead scope"):
        normalize_action_ev_lookahead_scope("mystery")
    with pytest.raises(ValueError, match="Unknown portfolio action scope"):
        normalize_portfolio_action_scope("mystery")
