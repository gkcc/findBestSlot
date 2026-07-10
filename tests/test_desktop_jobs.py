import json
from pathlib import Path

from gear_optimizer.action_ev_protocol import ActionEvWorkerRequest
from gear_optimizer.desktop_jobs import DesktopActionJobManager


class FakeProcess:
    def __init__(self):
        self.pid = 4321
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def _request(run_id="job-test"):
    return ActionEvWorkerRequest(
        run_id=run_id,
        game_id="zzz",
        character_id="zzz_starlight_billy",
        probability_model_id="zzz_default",
        current_pieces=[],
        inventory_pieces=[],
        horizon=2,
    )


def test_action_job_manager_reports_progress_and_result(monkeypatch, tmp_path: Path):
    process = FakeProcess()
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return process

    monkeypatch.setattr("gear_optimizer.desktop_jobs.subprocess.Popen", fake_popen)
    manager = DesktopActionJobManager(tmp_path)

    started = manager.start(_request(), agent_id="zzz_starlight_billy")

    assert started.status == "running"
    assert started.horizon == 2
    assert captured["kwargs"]["env"]["GEAR_OPTIMIZER_USER_DATA_DIR"] == str(tmp_path)
    run_dir = tmp_path / "runs" / "desktop" / started.job_id
    (run_dir / "progress.jsonl").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "job-test",
                "event": "unit_progress",
                "payload": {"completed": 3, "total": 12, "label": "测试动作"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    progress = manager.status(started.job_id)
    assert progress.progress_fraction == 0.25
    assert progress.latest_event["label"] == "测试动作"

    (run_dir / "result.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "job-test",
                "engine": "inventory_recursive",
                "action_mode": "fast",
                "rows": [],
                "performance_audit": {"total_seconds": 12.5},
            }
        ),
        encoding="utf-8",
    )
    process.returncode = 0
    completed = manager.status(started.job_id)
    assert completed.status == "completed"
    assert completed.progress_fraction == 1.0
    assert completed.result["performance_audit"]["total_seconds"] == 12.5
    frozen_elapsed = completed.elapsed_seconds
    assert manager.status(started.job_id).elapsed_seconds == frozen_elapsed


def test_action_job_manager_cancels_running_worker(monkeypatch, tmp_path: Path):
    process = FakeProcess()
    monkeypatch.setattr(
        "gear_optimizer.desktop_jobs.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    manager = DesktopActionJobManager(tmp_path)
    started = manager.start(_request("cancel-test"), agent_id="agent")

    cancelled = manager.cancel(started.job_id)

    assert process.terminated
    assert cancelled.status == "cancelled"
