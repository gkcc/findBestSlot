from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import RLock
import time
from typing import Any
import uuid

from gear_optimizer.action_ev_protocol import (
    ActionEvWorkerRequest,
    parse_action_ev_progress_event,
    parse_action_ev_worker_error,
    parse_action_ev_worker_result,
    parse_action_ev_worker_summary,
    protocol_json_data,
)
from gear_optimizer.desktop_protocol import DesktopActionJob
from gear_optimizer.paths import app_data_root
from gear_optimizer.project_paths import PROJECT_ROOT
from gear_optimizer.runtime_logging import append_runtime_event


@dataclass
class _ActionJobRuntime:
    job_id: str
    game_id: str
    agent_id: str
    request: ActionEvWorkerRequest
    process: subprocess.Popen[Any]
    run_dir: Path
    started_at: str
    started_monotonic: float
    cancelled: bool = False
    finished_elapsed: float | None = None
    cached_result: dict[str, Any] | None = None
    cached_error: dict[str, Any] | None = None


class DesktopActionJobManager:
    def __init__(self, root: Path | None = None):
        self.root = root or app_data_root()
        self._jobs: dict[str, _ActionJobRuntime] = {}
        self._lock = RLock()

    @property
    def log_path(self) -> Path:
        return self.root / "logs" / "desktop-backend.jsonl"

    def start(
        self,
        request: ActionEvWorkerRequest,
        *,
        agent_id: str,
    ) -> DesktopActionJob:
        with self._lock:
            running = [
                job
                for job in self._jobs.values()
                if job.process.poll() is None and not job.cancelled
            ]
            if running:
                raise ValueError(
                    f"已有 Action EV 任务正在运行：{running[0].job_id}。请先等待或取消。"
                )
            job_id = request.run_id or f"action-{uuid.uuid4().hex}"
            run_dir = self.root / "runs" / "desktop" / job_id
            run_dir.mkdir(parents=True, exist_ok=False)
            input_path = run_dir / "input.json"
            output_path = run_dir / "result.json"
            progress_path = run_dir / "progress.jsonl"
            error_path = run_dir / "error.json"
            summary_path = run_dir / "summary.json"
            input_path.write_text(
                json.dumps(protocol_json_data(request), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            command = self._worker_command(
                input_path,
                output_path,
                progress_path,
                error_path,
                summary_path,
            )
            env = os.environ.copy()
            env["GEAR_OPTIMIZER_USER_DATA_DIR"] = str(self.root)
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            )
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            started_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            runtime = _ActionJobRuntime(
                job_id=job_id,
                game_id=request.game_id,
                agent_id=agent_id,
                request=request,
                process=process,
                run_dir=run_dir,
                started_at=started_at,
                started_monotonic=time.monotonic(),
            )
            self._jobs[job_id] = runtime
            append_runtime_event(
                self.log_path,
                "action_job_started",
                source="desktop_backend",
                job_id=job_id,
                run_id=request.run_id,
                game_id=request.game_id,
                agent_id=agent_id,
                horizon=request.horizon,
                engine=request.engine,
                action_mode=request.action_mode,
                pid=process.pid,
            )
            return self._snapshot(runtime)

    def status(self, job_id: str) -> DesktopActionJob:
        with self._lock:
            runtime = self._jobs.get(job_id)
            if runtime is None:
                raise KeyError(f"unknown Action EV job_id: {job_id}")
            return self._snapshot(runtime)

    def list(self) -> list[DesktopActionJob]:
        with self._lock:
            return [
                self._snapshot(runtime)
                for runtime in sorted(
                    self._jobs.values(),
                    key=lambda item: item.started_at,
                    reverse=True,
                )
            ]

    def cancel(self, job_id: str) -> DesktopActionJob:
        with self._lock:
            runtime = self._jobs.get(job_id)
            if runtime is None:
                raise KeyError(f"unknown Action EV job_id: {job_id}")
            if runtime.process.poll() is None:
                runtime.cancelled = True
                runtime.process.terminate()
                try:
                    runtime.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    runtime.process.kill()
                    runtime.process.wait(timeout=5)
                append_runtime_event(
                    self.log_path,
                    "action_job_cancelled",
                    source="desktop_backend",
                    job_id=job_id,
                    run_id=runtime.request.run_id,
                    game_id=runtime.game_id,
                    agent_id=runtime.agent_id,
                    elapsed_seconds=round(time.monotonic() - runtime.started_monotonic, 6),
                )
            return self._snapshot(runtime)

    def shutdown(self) -> None:
        with self._lock:
            for runtime in self._jobs.values():
                if runtime.process.poll() is None:
                    runtime.cancelled = True
                    runtime.process.terminate()

    def _snapshot(self, runtime: _ActionJobRuntime) -> DesktopActionJob:
        return_code = runtime.process.poll()
        latest_event = self._latest_progress_event(runtime.run_dir / "progress.jsonl")
        completed = float(latest_event.get("completed") or 0.0)
        total = float(latest_event.get("total") or 0.0)
        progress_fraction = min(max(completed / total, 0.0), 1.0) if total > 0 else 0.0
        status = "running"
        if runtime.cancelled:
            status = "cancelled"
        elif return_code is not None:
            self._load_finished_artifacts(runtime)
            status = "completed" if return_code == 0 and runtime.cached_result else "failed"
            if status == "completed":
                completed = total or completed
                progress_fraction = 1.0
        elapsed = time.monotonic() - runtime.started_monotonic
        if return_code is not None:
            if runtime.finished_elapsed is None:
                runtime.finished_elapsed = elapsed
            elapsed = runtime.finished_elapsed
        summary_path = runtime.run_dir / "summary.json"
        if summary_path.exists():
            try:
                summary = parse_action_ev_worker_summary(
                    json.loads(summary_path.read_text(encoding="utf-8-sig")),
                    fallback_run_id=runtime.request.run_id,
                )
                elapsed = max(elapsed, summary.elapsed_seconds)
                if return_code is not None:
                    runtime.finished_elapsed = elapsed
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return DesktopActionJob(
            job_id=runtime.job_id,
            status=status,
            game_id=runtime.game_id,
            agent_id=runtime.agent_id,
            horizon=runtime.request.horizon,
            engine=str(runtime.request.engine),
            action_mode=str(runtime.request.action_mode),
            started_at=runtime.started_at,
            elapsed_seconds=elapsed,
            completed_units=completed,
            total_units=total,
            progress_fraction=progress_fraction,
            latest_event=latest_event,
            result=runtime.cached_result,
            error=runtime.cached_error,
        )

    def _load_finished_artifacts(self, runtime: _ActionJobRuntime) -> None:
        if runtime.cached_result is not None or runtime.cached_error is not None:
            return
        result_path = runtime.run_dir / "result.json"
        error_path = runtime.run_dir / "error.json"
        if result_path.exists():
            try:
                result = parse_action_ev_worker_result(
                    json.loads(result_path.read_text(encoding="utf-8-sig")),
                    fallback_run_id=runtime.request.run_id,
                )
                runtime.cached_result = result.model_dump(mode="json")
                append_runtime_event(
                    self.log_path,
                    "action_job_completed",
                    source="desktop_backend",
                    job_id=runtime.job_id,
                    run_id=runtime.request.run_id,
                    game_id=runtime.game_id,
                    agent_id=runtime.agent_id,
                    rows=len(result.rows),
                    total_seconds=result.performance_audit.total_seconds,
                )
                return
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                runtime.cached_error = {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
                return
        if error_path.exists():
            try:
                error = parse_action_ev_worker_error(
                    json.loads(error_path.read_text(encoding="utf-8-sig")),
                    fallback_run_id=runtime.request.run_id,
                )
                runtime.cached_error = error.model_dump(mode="json")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                runtime.cached_error = {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
        else:
            runtime.cached_error = {
                "error_type": "WorkerExitError",
                "message": f"Action EV worker exited with code {runtime.process.returncode}",
            }
        append_runtime_event(
            self.log_path,
            "action_job_failed",
            source="desktop_backend",
            job_id=runtime.job_id,
            run_id=runtime.request.run_id,
            game_id=runtime.game_id,
            agent_id=runtime.agent_id,
            error=runtime.cached_error,
        )

    @staticmethod
    def _latest_progress_event(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            return {}
        latest: dict[str, Any] | None = None
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                event = parse_action_ev_progress_event(json.loads(line)).to_flat_dict()
            except (ValueError, json.JSONDecodeError):
                continue
            if latest is None:
                latest = event
            if float(event.get("total") or 0.0) > 0:
                latest.setdefault("completed", event.get("completed"))
                latest.setdefault("total", event.get("total"))
                latest.setdefault("label", event.get("label"))
                return latest
        return latest or {}

    @staticmethod
    def _worker_command(
        input_path: Path,
        output_path: Path,
        progress_path: Path,
        error_path: Path,
        summary_path: Path,
    ) -> list[str]:
        worker_executable = os.environ.get("GEAR_OPTIMIZER_ACTION_WORKER", "").strip()
        command = [worker_executable] if worker_executable else [
            sys.executable,
            "-m",
            "gear_optimizer.action_ev_worker",
        ]
        return [
            *command,
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--progress",
            str(progress_path),
            "--error",
            str(error_path),
            "--summary",
            str(summary_path),
        ]
