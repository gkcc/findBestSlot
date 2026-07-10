from __future__ import annotations

from enum import StrEnum


class ActionEvMode(StrEnum):
    FAST = "fast"
    EXACT = "exact"


class ActionEvEngine(StrEnum):
    INVENTORY_RECURSIVE = "inventory_recursive"
    STATE_DP = "state_dp"


class ActionEvLookaheadScope(StrEnum):
    EXACT = "exact"
    TUNING_STATIC = "tuning_static"


class PortfolioActionScope(StrEnum):
    TUNING = "tuning"
    UPGRADE = "upgrade"
    ALL = "all"


ACTION_EV_FAST_MODE = ActionEvMode.FAST
ACTION_EV_EXACT_MODE = ActionEvMode.EXACT
DEFAULT_ACTION_EV_MODE = ActionEvMode.FAST
ACTION_EV_MODES = frozenset(ActionEvMode)
DEFAULT_ACTION_EV_ENGINE = ActionEvEngine.INVENTORY_RECURSIVE
ACTION_EV_ENGINES = frozenset(ActionEvEngine)
LOOKAHEAD_SCOPE_EXACT = ActionEvLookaheadScope.EXACT
LOOKAHEAD_SCOPE_TUNING_STATIC = ActionEvLookaheadScope.TUNING_STATIC


def normalize_action_ev_mode(value: object | None) -> ActionEvMode:
    raw = str(value or DEFAULT_ACTION_EV_MODE).strip().lower()
    aliases = {
        "quick": ActionEvMode.FAST,
        "default": ActionEvMode.FAST,
        "deep": ActionEvMode.EXACT,
        "full": ActionEvMode.EXACT,
    }
    raw = str(aliases.get(raw, raw))
    try:
        return ActionEvMode(raw)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in ActionEvMode)
        raise ValueError(f"Unknown Action EV mode: {raw}. Available: {allowed}") from exc


def normalize_action_ev_engine(value: object | None) -> ActionEvEngine:
    raw = str(value or DEFAULT_ACTION_EV_ENGINE).strip().lower()
    try:
        return ActionEvEngine(raw)
    except ValueError as exc:
        allowed = ", ".join(engine.value for engine in ActionEvEngine)
        raise ValueError(f"Unknown Action EV engine: {raw}. Available: {allowed}") from exc


def normalize_action_ev_lookahead_scope(value: object | None) -> ActionEvLookaheadScope:
    raw = str(value or ActionEvLookaheadScope.EXACT).strip().lower()
    try:
        return ActionEvLookaheadScope(raw)
    except ValueError as exc:
        allowed = ", ".join(scope.value for scope in ActionEvLookaheadScope)
        raise ValueError(f"Unknown Action EV lookahead scope: {raw}. Available: {allowed}") from exc


def normalize_portfolio_action_scope(value: object | None) -> PortfolioActionScope:
    raw = str(value or PortfolioActionScope.TUNING).strip().lower()
    try:
        return PortfolioActionScope(raw)
    except ValueError as exc:
        allowed = ", ".join(scope.value for scope in PortfolioActionScope)
        raise ValueError(f"Unknown portfolio action scope: {raw}. Available: {allowed}") from exc
