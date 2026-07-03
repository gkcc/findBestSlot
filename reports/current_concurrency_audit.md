# Current Concurrency Audit

Generated: 2026-07-03

## Desktop Entry State

- Primary app entry is the PySide6 desktop launcher through `gacha-gear-optimizer`, `python desktop_app.py`, and `scripts/start_desktop.ps1`.
- `gacha-gear-optimizer-desktop` is kept as a compatibility alias, not the primary documented entry.
- `desktop_app.py` is a thin bootstrapper that adds `src` to `sys.path` and calls `gear_optimizer.launcher.desktop_main`.
- Search across README, pyproject, scripts, src, tests, and docs found no active Streamlit, pywebview, `start_app`, or `serve-streamlit` entrypoint. Remaining matches are README cleanup statements or tests asserting the old web entrypoints are absent.

## Current Action EV Concurrency

- `horizon=1` still runs in-process on a `QThread`. This keeps the PySide6 UI thread responsive for short exact runs, but it is not CPU multi-core parallelism.
- `horizon=2` runs via `QProcess` using `python -m gear_optimizer.action_ev_worker`. This gives process isolation, cancellability, and prevents the main PySide6 process from being blocked by long exact calculations.
- The worker writes final rows only after exact completion. Progress is JSONL, errors are traceback JSON, and run summary is JSON.
- Cancel terminates/kills the worker process and does not publish partial recommendations.
- A process-pool action-value helper and profiling entrypoint now exist for exact state-DP action evaluation. They are optional and diagnostic-only for now because the current small sample profile shows process startup/serialization overhead exceeding the benefit.
- `GEAR_OPTIMIZER_WORKERS` can override worker count for the process-pool helper/profile path. The PySide6 default recommendation path does not enable that process pool yet.

## Progress Model

- Worker progress output is throttled for non-critical events.
- UI receives progress into a cached payload and renders with a timer, keeping widget updates bounded.
- The visible progress bar is monotonic even when refinement expands the total action plan.
- DP state counters are diagnostic, not the primary progress model.

## Known Next Concurrency Work

- Manually profile a real large `horizon=2` inventory with the state-DP engine before deciding whether to make it the desktop default.
- If large profiles show a win, expose a UI worker-count control and route worker runs through the exact process-pool path.
