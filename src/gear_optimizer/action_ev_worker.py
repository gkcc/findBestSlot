from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Any

from gear_optimizer.action_ev_protocol import (
    ACTION_EV_WORKER_EXECUTION_MODE,
    ActionEvPerformanceAuditPayload,
    ActionEvProgressEvent,
    ActionEvRowPayload,
    ActionEvWorkerError,
    ActionEvWorkerRequest,
    ActionEvWorkerResult,
    ActionEvWorkerSummary,
    encode_protocol_value,
    parse_action_ev_worker_request,
    protocol_json_data,
)
from gear_optimizer.action_types import (
    ACTION_EV_ENGINES as ACTION_EV_ENGINES,
    DEFAULT_ACTION_EV_ENGINE,
    DEFAULT_ACTION_EV_MODE,
    ActionEvEngine,
    ActionEvMode,
    normalize_action_ev_engine,
    normalize_action_ev_mode,
)
from gear_optimizer.game_rules import load_characters, load_game, load_probability_models
from gear_optimizer.models import GearPiece
from gear_optimizer.position_ev import (
    position_strategy_efficiency_models,
)
from gear_optimizer.presets import sanitize_piece_data_for_game
from gear_optimizer.scoring import analyse_current_gear
from gear_optimizer.user_target_templates import load_user_target_templates

ProgressCallback = Callable[[dict[str, object]], None]
ACTION_EV_ENGINE_ENV = "GEAR_OPTIMIZER_ACTION_EV_ENGINE"
ACTION_EV_MODE_ENV = "GEAR_OPTIMIZER_ACTION_EV_MODE"
WORKER_EXECUTION_MODE = ACTION_EV_WORKER_EXECUTION_MODE
IMMEDIATE_PROGRESS_EVENTS = {
    "start",
    "cache_hit",
    "unit_start",
    "unit_done",
    "action_perf",
    "refinement_start",
    "complete",
    "failed",
    "cancelled",
}


def action_ev_engine_from_payload(
    payload: ActionEvWorkerRequest | dict[str, Any],
) -> ActionEvEngine:
    override = os.environ.get(ACTION_EV_ENGINE_ENV)
    payload_engine = payload.engine if isinstance(payload, ActionEvWorkerRequest) else payload.get("engine")
    return normalize_action_ev_engine(
        override if override not in (None, "") else payload_engine
    )


def action_ev_mode_from_payload(
    payload: ActionEvWorkerRequest | dict[str, Any],
) -> ActionEvMode:
    override = os.environ.get(ACTION_EV_MODE_ENV)
    payload_mode = (
        payload.action_mode if isinstance(payload, ActionEvWorkerRequest) else payload.get("action_mode")
    )
    return normalize_action_ev_mode(
        override if override not in (None, "") else payload_mode
    )


def action_ev_uses_state_dp(engine: object | None) -> bool:
    return normalize_action_ev_engine(engine) is ActionEvEngine.STATE_DP


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


def _pick_character(game_id: str, character_id: str) -> Any:
    builtin_characters = load_characters(game_id)
    for character in builtin_characters:
        if character.id == character_id:
            return character
    return _pick_by_id(
        [*builtin_characters, *load_user_target_templates(game_id)],
        character_id,
        "character",
    )


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
        details = {
            key: encode_protocol_value(value)
            for key, value in payload.items()
            if key != "event"
        }
        event_payload = ActionEvProgressEvent(
            run_id=self.run_id,
            event=event,
            elapsed_seconds=round(now - self.started_at, 3),
            wall_time=_utc_now(),
            payload=details,
        )
        if self._file is None:
            raise RuntimeError("progress writer is not open")
        self._file.write(json.dumps(protocol_json_data(event_payload), ensure_ascii=False) + "\n")
        self._file.flush()
        self._last_write_at = now


def build_action_ev_models_from_payload(
    payload: ActionEvWorkerRequest | dict[str, Any],
    progress_callback: ProgressCallback | None = None,
    engine: str | None = None,
    action_mode: str | None = None,
) -> list[ActionEvRowPayload]:
    request = (
        payload
        if isinstance(payload, ActionEvWorkerRequest)
        else parse_action_ev_worker_request(payload)
    )
    resolved_engine = normalize_action_ev_engine(engine) if engine else action_ev_engine_from_payload(request)
    resolved_mode = normalize_action_ev_mode(action_mode) if action_mode else action_ev_mode_from_payload(request)
    game = load_game(request.game_id)
    character = _pick_character(game.id, request.character_id)
    probability_model = _pick_by_id(
        load_probability_models(game.id),
        request.probability_model_id,
        "probability model",
    )
    current_pieces = [
        GearPiece.model_validate(sanitize_piece_data_for_game(item.model_dump(mode="json"), game.id))
        for item in request.current_pieces
    ]
    inventory_pieces = [
        GearPiece.model_validate(sanitize_piece_data_for_game(item.model_dump(mode="json"), game.id))
        for item in request.inventory_pieces
    ]
    analysis = analyse_current_gear(current_pieces, game, character)
    return position_strategy_efficiency_models(
        game,
        character,
        probability_model,
        analysis,
        inventory_pieces=[*current_pieces, *inventory_pieces],
        horizon=request.horizon,
        progress_callback=progress_callback,
        use_state_dp=action_ev_uses_state_dp(resolved_engine),
        action_mode=resolved_mode,
    )


def build_action_ev_rows_from_payload(
    payload: ActionEvWorkerRequest | dict[str, Any],
    progress_callback: ProgressCallback | None = None,
    engine: str | None = None,
    action_mode: str | None = None,
) -> list[dict[str, Any]]:
    return [
        row.to_display_row()
        for row in build_action_ev_models_from_payload(
            payload,
            progress_callback=progress_callback,
            engine=engine,
            action_mode=action_mode,
        )
    ]


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
    raw_payload: Any = {}
    request: ActionEvWorkerRequest | None = None
    run_id = Path(args.input).stem or "action-ev-worker"
    engine_text = str(os.environ.get(ACTION_EV_ENGINE_ENV) or DEFAULT_ACTION_EV_ENGINE)
    action_mode_text = str(os.environ.get(ACTION_EV_MODE_ENV) or DEFAULT_ACTION_EV_MODE)
    input_audit = ""
    input_audit_lines: list[str] = []
    horizon = 1

    try:
        raw_payload = _read_json(args.input)
        request = parse_action_ev_worker_request(raw_payload)
        run_id = request.run_id
        input_audit = request.input_audit
        input_audit_lines = list(request.input_audit_lines)
        horizon = request.horizon
        engine = action_ev_engine_from_payload(request)
        action_mode = action_ev_mode_from_payload(request)
        engine_text = str(engine)
        action_mode_text = str(action_mode)
        latest_performance_audit: dict[str, Any] = {}
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
                    "action_mode": action_mode,
                    "execution_mode": WORKER_EXECUTION_MODE,
                },
                force=True,
            )

            def emit_progress(event: dict[str, object]) -> None:
                nonlocal latest_performance_audit
                performance = event.get("performance_audit")
                if isinstance(performance, dict):
                    latest_performance_audit = dict(performance)
                progress.emit(event)

            row_payloads = build_action_ev_models_from_payload(
                request,
                progress_callback=emit_progress,
                engine=engine,
                action_mode=action_mode,
            )
            performance_payload = ActionEvPerformanceAuditPayload.model_validate(
                latest_performance_audit
            )
            result_payload = ActionEvWorkerResult(
                run_id=run_id,
                engine=engine,
                action_mode=action_mode,
                input_audit=input_audit,
                input_audit_lines=input_audit_lines,
                performance_audit=performance_payload,
                rows=row_payloads,
            )
            _write_json(
                args.output,
                protocol_json_data(result_payload),
            )
            progress.emit(
                {
                    "event": "worker_done",
                    "label": "Action EV worker complete",
                    "engine": engine,
                    "action_mode": action_mode,
                    "execution_mode": WORKER_EXECUTION_MODE,
                    "rows": len(row_payloads),
                    "performance_audit": latest_performance_audit,
                },
                force=True,
            )
        _write_json(
            args.summary,
            protocol_json_data(
                ActionEvWorkerSummary(
                    run_id=run_id,
                    status="ok",
                    input_path=str(args.input),
                    output_path=str(args.output),
                    progress_path=str(args.progress),
                    error_path=str(args.error),
                    engine=engine_text,
                    action_mode=action_mode_text,
                    started_at=started_wall,
                    finished_at=_utc_now(),
                    horizon=horizon,
                    input_audit=input_audit,
                    input_audit_lines=input_audit_lines,
                    elapsed_seconds=round(time.monotonic() - started_monotonic, 3),
                    rows=len(row_payloads),
                    performance_audit=performance_payload,
                )
            ),
        )
        return 0
    except Exception as exc:
        if isinstance(raw_payload, dict):
            run_id = str(raw_payload.get("run_id") or run_id)
            engine_text = str(
                os.environ.get(ACTION_EV_ENGINE_ENV)
                or raw_payload.get("engine")
                or engine_text
            )
            action_mode_text = str(
                os.environ.get(ACTION_EV_MODE_ENV)
                or raw_payload.get("action_mode")
                or action_mode_text
            )
            input_audit = str(raw_payload.get("input_audit") or input_audit)
            raw_audit_lines = raw_payload.get("input_audit_lines")
            if isinstance(raw_audit_lines, list):
                input_audit_lines = [str(line) for line in raw_audit_lines]
            elif input_audit:
                input_audit_lines = input_audit.splitlines()
            raw_horizon = raw_payload.get("horizon")
            if raw_horizon in {1, 2}:
                horizon = int(raw_horizon)
        tb = traceback.format_exc()
        _write_json(
            args.error,
            protocol_json_data(
                ActionEvWorkerError(
                    run_id=run_id,
                    engine=engine_text,
                    error_type=type(exc).__name__,
                    message=str(exc),
                    traceback=tb,
                    finished_at=_utc_now(),
                    input_audit=input_audit,
                    input_audit_lines=input_audit_lines,
                )
            ),
        )
        _write_json(
            args.summary,
            protocol_json_data(
                ActionEvWorkerSummary(
                    run_id=run_id,
                    status="error",
                    input_path=str(args.input),
                    output_path=str(args.output),
                    progress_path=str(args.progress),
                    error_path=str(args.error),
                    engine=engine_text,
                    action_mode=action_mode_text,
                    started_at=started_wall,
                    finished_at=_utc_now(),
                    horizon=horizon,
                    input_audit=input_audit,
                    input_audit_lines=input_audit_lines,
                    elapsed_seconds=round(time.monotonic() - started_monotonic, 3),
                )
            ),
        )
        try:
            with ProgressJsonlWriter(args.progress, run_id, min_interval_seconds=0.0) as progress:
                progress.emit({"event": "failed", "label": "Action EV worker failed"}, force=True)
        except Exception as progress_exc:
            print(
                f"failed to append worker failure progress: "
                f"{type(progress_exc).__name__}: {progress_exc}",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
