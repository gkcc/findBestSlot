# Unattended Work Summary

Generated: 2026-07-03

## Completed Items

- PySide6 desktop is the primary app surface. Main documented entries are `gacha-gear-optimizer`, `python desktop_app.py`, and `scripts/start_desktop.ps1`; `gacha-gear-optimizer-desktop` remains only as a compatibility alias.
- No active old Web UI, Streamlit, pywebview, `start_app`, or `serve-streamlit` entrypoint remains in the tracked product surface.
- `horizon=1` and `horizon=2` remain exact probability calculations. No Monte Carlo, quick preview, approximate recommendation, top-N approximation, time-budget early return, or partial recommendation mode was introduced.
- `horizon=2` Action EV runs in a worker process with JSON input, JSON result output, JSONL progress, traceback JSON, and summary JSON. Cancel terminates the worker and does not update recommendations with partial results.
- Progress rendering is throttled. The UI separates monotonic outer progress from diagnostic DP counters and keeps the progress bar from moving backward when the plan expands.
- Single-piece outcome distributions are precomputed in `gear_optimizer.piece_distribution`, including 3/4-line starts, main-stat/substat constraints, fixed/mixed main stats, and random-position mixtures.
- `EvState` compresses inventory state for exact state-DP evaluation. It preserves current locked-position semantics, keeps unfinished pieces out of `Best(I)` by default, and can return value-only or representative loadout rows.
- The explicit state-transition DP path is implemented behind `use_state_dp=True`, with transition cache, compressed state signatures, and tests against the old inventory-recursive exact path for horizon=1 and horizon=2.
- Optional process-pool action-value profiling is implemented. `GEAR_OPTIMIZER_WORKERS` can override worker count for that diagnostic path; it is not the desktop default because the current small profile is slower with two workers.
- ZZZ drive disc set icons are loaded through `ui_assets.py`, cached, shown in current gear cards, inventory set cells, and recommendation cards, with text fallback if assets are missing.
- Inventory and current gear UI were reorganized around inventory-first entry, current gear cards, filters, copy/clear/export actions, and current best loadout display.
- Result presentation now shows a complete recommendation card, defaults Action EV detail to the top 20 rows, provides a "show all" audit path, keeps representative loadout in a separate subtab, and keeps logs separate/collapsible.

## Current Concurrency Model

- `horizon=1`: exact in-process computation on a `QThread`; responsive UI, not CPU multi-core.
- `horizon=2`: exact calculation in a separate `QProcess` worker (`python -m gear_optimizer.action_ev_worker`); cancellable and isolated from the PySide6 main process.
- Optional process pool: implemented for state-DP action-value profiling and helper use, but not enabled by default in the desktop app.

## Algorithm State Compression

- `Best(state)` now has an `EvState` value path that uses count-state DP for 4+2 and 2+2+2 set-plan satisfaction.
- The value-only path does not backtrack combinations; the representative-combo path is retained for UI/frontier display.
- Unfinished inventory pieces are upgrade action sources by default and do not pollute `Best(I)`.
- Current locked positions cannot be replaced in best-loadout value. Candidate outcomes on locked positions can still be evaluated as upgrade/fresh outcomes, but they cannot improve that locked loadout slot.

## Profile Summary

Default inventory-recursive `horizon=1` profile:

- total_seconds: 2.2143
- action_count: 14
- outcome_count: 2885
- aggregated outcome cache misses: 14
- top slow action: random-position `云岿如我`

State-DP `horizon=1` profile:

- engine: state_dp
- total_seconds: 2.2917
- action_count: 14
- outcome_count: 2886
- state_transition_cache_misses: 14

Optional process-pool profile:

- workers=1: 2.0151s, errors=0
- workers=2: 2.2838s, errors=0
- Interpretation: Windows-spawn process-pool execution works from a real module entrypoint, but overhead dominates this small workload. Keep it optional until large `horizon=2` profiles prove a win.

## Test Commands And Results

- `python -m pytest tests\test_piece_distribution.py -q`
  Result: passed; distribution precomputation matched legacy enumeration.
- `python -m pytest tests\test_ev_state.py -q`
  Result: passed; compressed state and state-DP equivalence tests passed.
- `python -m gear_optimizer.profile_action_ev --horizon 1 --state-dp --output reports\action_ev_profile_state_dp.json --summary reports\action_ev_profile_state_dp_summary.md`
  Result: passed; wrote state-DP profile JSON and Markdown summary.
- `python -m gear_optimizer.profile_parallel_action_ev --horizon 1 --action-limit 4 --workers 1,2 --output reports\action_ev_parallel_profile.md`
  Result: passed; wrote process-pool comparison report.
- `python -m pytest -q`
  Final result: 238 passed in 16.68s.
- `python -m gear_optimizer.diagnostics`
  Final result: passed; Python, dependencies, PySide6 runtime, configs, examples, scripts, console entries, and 28/28 ZZZ icon files reported ok.
- `python desktop_app.py --app-check`
  Final result: passed; native UI module importable.
- `python -m gear_optimizer.acceptance --output reports/acceptance.md --check`
  Final result: passed; acceptance report written and all required report markers checked ok.

## UI Changes

- Current gear cards show set icon, set name, main stat, substats, effective/quality metrics, and lock state.
- Inventory summary hides substat clutter by default and exposes details in a side panel.
- Result recommendation card includes action, set, position, main stat, fixed substats, horizon, quality/mother disk, effective/mother disk, relative-to-random explanation, and exact calculation basis.
- Action EV detail defaults to top 20 and can expand to all exact rows.
- Internal fields such as `_sort_vector` and `_representative_loadout_rows` are not directly displayed.

## Remaining Risks And Decisions

- A real large `horizon=2` state-DP profile is still needed before switching the desktop default engine.
- Optional process-pool execution is implemented but should remain off by default until large profiles show it beats spawn/serialization overhead.
- Enhancement materials are not converted into mother-disk-equivalent value; that needs a user-approved resource model.

## Files To Review Next

- `src/gear_optimizer/position_ev.py`
- `src/gear_optimizer/piece_distribution.py`
- `src/gear_optimizer/action_ev_worker.py`
- `src/gear_optimizer/profile_action_ev.py`
- `src/gear_optimizer/profile_parallel_action_ev.py`
- `src/gear_optimizer/pyside6_app.py`
- `src/gear_optimizer/ui_assets.py`
- `README.md`
- `docs/next_steps.md`
