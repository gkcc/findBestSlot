from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import multiprocessing
import os
from pathlib import Path
import queue
import tempfile
import time
from typing import Any

from gear_optimizer.action_ev_protocol import ActionEvWorkerRequest
from gear_optimizer.action_ev_worker import build_action_ev_models_from_payload
from gear_optimizer.models import CharacterPreset
from gear_optimizer.position_ev import (
    _ACTION_EV_ROWS_CACHE,
    _AGGREGATED_ACTION_OUTCOME_CACHE,
    _BEST_COMBO_VALUE_CACHE,
    _STATE_TRANSITION_CACHE,
)
from gear_optimizer.user_target_templates import save_user_target_template


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = PROJECT_ROOT / "reports" / "h2_benchmark.json"
DEFAULT_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "zzz_ye_shunguang_h2_benchmark.json"


def load_benchmark_fixture(
    path: Path = DEFAULT_FIXTURE,
) -> tuple[ActionEvWorkerRequest, CharacterPreset]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported benchmark fixture schema: {data.get('schema_version')}")
    request = ActionEvWorkerRequest.model_validate(data["request"])
    target = CharacterPreset.model_validate(data["target_template"])
    if request.character_id != target.id:
        raise ValueError("benchmark request and target template IDs do not match")
    return request, target


def build_default_request() -> ActionEvWorkerRequest:
    request, _target = load_benchmark_fixture()
    return request


def _clear_action_caches() -> None:
    _ACTION_EV_ROWS_CACHE.clear()
    _AGGREGATED_ACTION_OUTCOME_CACHE.clear()
    _BEST_COMBO_VALUE_CACHE.clear()
    _STATE_TRANSITION_CACHE.clear()


def _one_run(request: ActionEvWorkerRequest) -> dict[str, Any]:
    latest_audit: dict[str, Any] = {}

    def progress(event: dict[str, object]) -> None:
        nonlocal latest_audit
        audit = event.get("performance_audit")
        if isinstance(audit, dict):
            latest_audit = dict(audit)

    started = time.perf_counter()
    rows = build_action_ev_models_from_payload(request, progress_callback=progress)
    elapsed = time.perf_counter() - started
    return {
        "elapsed_seconds": round(elapsed, 6),
        "rows": len(rows),
        "performance_audit": latest_audit,
    }


def _benchmark_worker(
    request_data: dict[str, Any],
    target_data: dict[str, Any],
    output: multiprocessing.Queue,
) -> None:
    try:
        request = ActionEvWorkerRequest.model_validate(request_data)
        target = CharacterPreset.model_validate(target_data)
        with tempfile.TemporaryDirectory(prefix="gear-optimizer-h2-benchmark-") as temp_dir:
            benchmark_user_data = Path(temp_dir)
            save_user_target_template(
                request.game_id,
                target,
                target.name,
                benchmark_user_data,
            )
            os.environ["GEAR_OPTIMIZER_USER_DATA_DIR"] = str(benchmark_user_data)
            _clear_action_caches()
            cold = _one_run(request)
            warm = _one_run(request)
            output.put({"ok": True, "cold": cold, "warm": warm})
    except Exception as exc:
        output.put(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        )


def run_isolated_benchmark(
    request: ActionEvWorkerRequest,
    *,
    target_template: CharacterPreset,
    timeout_seconds: float,
) -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    output: multiprocessing.Queue = context.Queue()
    process = context.Process(
        target=_benchmark_worker,
        args=(
            request.model_dump(mode="json"),
            target_template.model_dump(mode="json"),
            output,
        ),
    )
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(10)
        raise TimeoutError(f"H=2 benchmark exceeded {timeout_seconds:.1f} seconds")
    try:
        result = output.get(timeout=5)
    except queue.Empty as exc:
        raise RuntimeError(
            f"H=2 benchmark process exited with code {process.exitcode} without a report"
        ) from exc
    if not result.get("ok"):
        raise RuntimeError(
            f"{result.get('error_type', 'BenchmarkError')}: {result.get('message', '')}"
        )
    return result


def build_report(
    result: dict[str, Any],
    *,
    threshold_seconds: float,
) -> dict[str, Any]:
    cold_seconds = float(result["cold"]["elapsed_seconds"])
    warm_seconds = float(result["warm"]["elapsed_seconds"])
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "fixture": "zzz_ye_shunguang_complete_plus_33_inventory_h2_fast",
        "threshold_seconds": threshold_seconds,
        "cold": result["cold"],
        "warm": result["warm"],
        "cold_pass": cold_seconds <= threshold_seconds,
        "warm_pass": warm_seconds <= threshold_seconds,
        "passed": max(cold_seconds, warm_seconds) <= threshold_seconds,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the fixed exact H=2 performance gate.")
    parser.add_argument("--threshold", type=float, default=60.0)
    parser.add_argument("--timeout", type=float, default=150.0)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        request, target_template = load_benchmark_fixture()
        result = run_isolated_benchmark(
            request,
            target_template=target_template,
            timeout_seconds=args.timeout,
        )
        report = build_report(result, threshold_seconds=args.threshold)
    except Exception as exc:
        report = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "fixture": "zzz_ye_shunguang_complete_plus_33_inventory_h2_fast",
            "threshold_seconds": args.threshold,
            "passed": False,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
