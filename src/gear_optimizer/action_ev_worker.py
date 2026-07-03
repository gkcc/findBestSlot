from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import traceback
from typing import Any

from gear_optimizer.game_rules import load_characters, load_game, load_probability_models
from gear_optimizer.models import GearPiece
from gear_optimizer.position_ev import position_strategy_efficiency_rows
from gear_optimizer.scoring import analyse_current_gear

ProgressCallback = Callable[[dict[str, object]], None]
ACTION_EV_ENGINE_ENV = "GEAR_OPTIMIZER_ACTION_EV_ENGINE"
DEFAULT_ACTION_EV_ENGINE = "inventory_recursive"
ACTION_EV_ENGINES = {"inventory_recursive", "state_dp"}
WORKER_EXECUTION_MODE = "worker_process"
IMMEDIATE_PROGRESS_EVENTS = {
    "start",
    "cache_hit",
    "unit_start",
    "unit_done",
    "refinement_start",
    "complete",
    "failed",
    "cancelled",
}


def normalize_action_ev_engine(value: object | None) -> str:
    engine = str(value or DEFAULT_ACTION_EV_ENGINE).strip().lower()
    if not engine:
        engine = DEFAULT_ACTION_EV_ENGINE
    if engine not in ACTION_EV_ENGINES:
        allowed = ", ".join(sorted(ACTION_EV_ENGINES))
        raise ValueError(f"Unknown Action EV engine: {engine}. Available: {allowed}")
    return engine


def action_ev_engine_from_payload(payload: dict[str, Any]) -> str:
    override = os.environ.get(ACTION_EV_ENGINE_ENV)
    return normalize_action_ev_engine(override if override not in (None, "") else payload.get("engine"))


def action_ev_uses_state_dp(engine: str) -> bool:
    return normalize_action_ev_engine(engine) == "state_dp"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _write_json(path: str | Path, payload: Any) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _pick_by_id(items: list[Any], item_id: str, label: str) -> Any:
    for item in items:
        if item.id == item_id:
            return item
    available = ", ".join(item.id for item in items) or "-"
    raise ValueError(f"Unknown {label}: {item_id}. Available: {available}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, GearPiece):
        return {"__gear_piece__": value.model_dump(mode="json")}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class ProgressJsonlWriter:
    def __init__(
        self,
        path: str | Path,
        run_id: str,
        min_interval_seconds: float = 0.2,
    ) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self.min_interval_seconds = min_interval_seconds
        self.started_at = time.monotonic()
        self._last_write_at = 0.0
        self._file = None

    def __enter__(self) -> "ProgressJsonlWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8")
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def emit(self, payload: dict[str, object], force: bool = False) -> None:
        now = time.monotonic()
        event = str(payload.get("event") or "")
        immediate = force or event in IMMEDIATE_PROGRESS_EVENTS
        if not immediate and now - self._last_write_at < self.min_interval_seconds:
            return
        enriched = {
            "run_id": self.run_id,
            "elapsed_seconds": round(now - self.started_at, 3),
            "wall_time": _utc_now(),
            **payload,
        }
        if self._file is None:
            raise RuntimeError("progress writer is not open")
        self._file.write(json.dumps(_jsonable(enriched), ensure_ascii=False) + "\n")
        self._file.flush()
        self._last_write_at = now


def build_action_ev_rows_from_payload(
    payload: dict[str, Any],
    progress_callback: ProgressCallback | None = None,
    engine: str | None = None,
) -> list[dict[str, Any]]:
    resolved_engine = normalize_action_ev_engine(engine) if engine else action_ev_engine_from_payload(payload)
    game = load_game(str(payload["game_id"]))
    character = _pick_by_id(
        load_characters(game.id),
        str(payload["character_id"]),
        "character",
    )
    probability_model = _pick_by_id(
        load_probability_models(game.id),
        str(payload["probability_model_id"]),
        "probability model",
    )
    current_pieces = [
        GearPiece.model_validate(item)
        for item in payload.get("current_pieces", [])
    ]
    inventory_pieces = [
        GearPiece.model_validate(item)
        for item in payload.get("inventory_pieces", [])
    ]
    horizon = int(payload.get("horizon") or 1)
    analysis = analyse_current_gear(current_pieces, game, character)
    return position_strategy_efficiency_rows(
        game,
        character,
        probability_model,
        analysis,
        inventory_pieces=[*current_pieces, *inventory_pieces],
        horizon=horizon,
        progress_callback=progress_callback,
        use_state_dp=action_ev_uses_state_dp(resolved_engine),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run exact Action EV in a worker process.")
    parser.add_argument("--input", required=True, help="Input JSON path.")
    parser.add_argument("--output", required=True, help="Output rows JSON path.")
    parser.add_argument("--progress", required=True, help="Progress JSONL path.")
    parser.add_argument("--error", required=True, help="Error JSON path.")
    parser.add_argument("--summary", required=True, help="Run summary JSON path.")
    parser.add_argument(
        "--progress-interval-ms",
        type=int,
        default=200,
        help="Minimum interval for non-critical progress events.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started_wall = _utc_now()
    started_monotonic = time.monotonic()
    payload = _read_json(args.input)
    run_id = str(payload.get("run_id") or Path(args.input).stem)
    raw_engine = os.environ.get(ACTION_EV_ENGINE_ENV) or payload.get("engine") or DEFAULT_ACTION_EV_ENGINE
    summary_base = {
        "run_id": run_id,
        "input": str(args.input),
        "output": str(args.output),
        "progress": str(args.progress),
        "error": str(args.error),
        "engine": str(raw_engine),
        "execution_mode": WORKER_EXECUTION_MODE,
        "started_at": started_wall,
        "horizon": int(payload.get("horizon") or 1),
    }

    try:
        engine = action_ev_engine_from_payload(payload)
        summary_base["engine"] = engine
        with ProgressJsonlWriter(
            args.progress,
            run_id,
            min_interval_seconds=max(args.progress_interval_ms, 0) / 1000.0,
        ) as progress:
            progress.emit(
                {
                    "event": "worker_start",
                    "label": "Action EV worker started",
                    "engine": engine,
                    "execution_mode": WORKER_EXECUTION_MODE,
                },
                force=True,
            )
            rows = build_action_ev_rows_from_payload(payload, progress_callback=progress.emit, engine=engine)
            serialised_rows = _jsonable(rows)
            _write_json(
                args.output,
                {
                    "run_id": run_id,
                    "engine": engine,
                    "execution_mode": WORKER_EXECUTION_MODE,
                    "rows": serialised_rows,
                },
            )
            progress.emit(
                {
                    "event": "worker_done",
                    "label": "Action EV worker complete",
                    "engine": engine,
                    "execution_mode": WORKER_EXECUTION_MODE,
                    "rows": len(rows),
                },
                force=True,
            )
        _write_json(
            args.summary,
            {
                **summary_base,
                "status": "ok",
                "finished_at": _utc_now(),
                "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
                "rows": len(rows),
            },
        )
        return 0
    except BaseException as exc:
        tb = traceback.format_exc()
        _write_json(
            args.error,
            {
                "run_id": run_id,
                "status": "error",
                "engine": summary_base["engine"],
                "execution_mode": WORKER_EXECUTION_MODE,
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": tb,
                "finished_at": _utc_now(),
            },
        )
        _write_json(
            args.summary,
            {
                **summary_base,
                "status": "error",
                "finished_at": _utc_now(),
                "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
            },
        )
        try:
            with ProgressJsonlWriter(args.progress, run_id, min_interval_seconds=0.0) as progress:
                progress.emit({"event": "failed", "label": "Action EV worker failed"}, force=True)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
