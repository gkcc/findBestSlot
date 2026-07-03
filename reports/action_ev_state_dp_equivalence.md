# Action EV State DP Equivalence

Generated: 2026-07-03

## Scope

This report covers the first state-transition DP implementation behind the explicit `use_state_dp=True` switch in `position_strategy_efficiency_rows`.

The old exact inventory-recursive path remains available as the reference path. The state DP path uses:

- `EvState` compressed inventory signatures.
- `state_transition_for_action` over compressed states.
- `expected_state_action_value` and `lookahead_state_value`.
- Existing exact action space: `dominant_generation ∪ set_plan_frontier ∪ upgrade_sources`.

No Monte Carlo, quick preview, top-N approximation, partial recommendation, or time-budget early return was introduced.

## Equivalence Evidence

Automated tests compare the new state DP path against the existing inventory-recursive exact path:

- Fresh/full generation actions:
  - random position
  - fixed position
  - fixed position + fixed main stat
  - fixed position + fixed main stat + fixed substat
- Inventory upgrade action source.
- `horizon=2` lookahead value.
- Action EV rows for `horizon=1` and `horizon=2` on a tiny exact deterministic fixture.
- Best loadout semantics under 4+2 and 2+2+2 set plans.
- Current locked-position semantics.
- Inventory locked piece does not lock a position.
- Unfinished pieces remain upgrade sources only by default.
- Non-improving candidate outcomes merge to `same_state`; improving outcomes replace the compressed `(position, set)` entry.

## Verification

Latest local verification:

```powershell
python -m pytest tests\test_ev_state.py -q
python -m pytest tests\test_position_ev.py -q
python -m pytest -q
```

Results:

- `tests\test_ev_state.py`: 10 passed.
- `tests\test_position_ev.py`: 26 passed.
- Full suite: 233 passed.

## Current Default

The state DP path is implemented and tested but remains behind the explicit `use_state_dp=True` switch for now.

Reason: the existing inventory-recursive path emits richer nested progress events. Before making state DP the UI default, the state DP path should emit equivalent progress diagnostics so long-running `horizon=2` still looks alive and remains easy to cancel/debug.

## Next Work

- Add state-DP progress events and transition cache hit/miss diagnostics.
- Re-run profile with `use_state_dp=True`.
- Decide whether to make state DP the default for worker runs after progress parity is in place.
