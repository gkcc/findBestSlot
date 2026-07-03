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

State-DP progress events and transition cache diagnostics have been added. The path now emits state/action/outcome progress plus transition cache hit/miss counters.

Reason it is not yet the default: the latest small example profile does not show a material speedup over the inventory-recursive path. The exact state engine is available for profiling and parallelism work, but the production default should change only after profiling shows a clear benefit or after the parallel state engine is selected explicitly.

## Profile Snapshot

Latest local state-DP profile command:

```powershell
python -m gear_optimizer.profile_action_ev --horizon 1 --state-dp --output reports\action_ev_profile_state_dp.json --summary reports\action_ev_profile_state_dp_summary.md
```

Result:

- engine: state_dp
- horizon: 1
- total_seconds: 2.2917
- action_count: 14
- outcome_count: 2886
- state_transition_cache_misses: 14

On this small example, state DP is not yet materially faster than the inventory-recursive path. It is therefore kept as an explicit engine switch while transition profiling and parallelism work continue.

## Next Work

- Add state-DP progress events and transition cache hit/miss diagnostics.
- Re-run profile with `use_state_dp=True`.
- Decide whether to make state DP the default for worker runs after progress parity is in place.
