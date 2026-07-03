import json
from pathlib import Path

from gear_optimizer import position_ev
from gear_optimizer.action_ev_worker import ProgressJsonlWriter, main as worker_main
from gear_optimizer.presets import load_current_example


def _write_worker_input(path: Path, game_id: str = "zzz") -> None:
    pieces = load_current_example("examples/zzz_billy_current.yaml")
    path.write_text(
        json.dumps(
            {
                "run_id": "test-run",
                "game_id": game_id,
                "character_id": "zzz_starlight_billy",
                "probability_model_id": "zzz_default",
                "current_pieces": [piece.model_dump(mode="json") for piece in pieces],
                "inventory_pieces": [],
                "horizon": 1,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_action_ev_worker_writes_result_progress_and_summary(tmp_path):
    position_ev._ACTION_EV_ROWS_CACHE.clear()
    position_ev._AGGREGATED_ACTION_OUTCOME_CACHE.clear()
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "result.json"
    progress_path = tmp_path / "progress.jsonl"
    error_path = tmp_path / "error.json"
    summary_path = tmp_path / "summary.json"
    _write_worker_input(input_path)

    assert (
        worker_main(
            [
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
                "--progress-interval-ms",
                "0",
            ]
        )
        == 0
    )

    result = json.loads(output_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    progress_events = [
        json.loads(line)
        for line in progress_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result["run_id"] == "test-run"
    assert result["rows"]
    assert summary["status"] == "ok"
    assert summary["rows"] == len(result["rows"])
    assert any(event["event"] == "worker_start" for event in progress_events)
    assert any(event["event"] == "worker_done" for event in progress_events)
    assert any(
        event.get("inner_event") == "candidate_generation_step_done"
        for event in progress_events
    )
    assert any("aggregated_outcome_cache_misses" in event for event in progress_events)
    assert not error_path.exists()


def test_action_ev_worker_writes_error_json_for_bad_input(tmp_path):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "result.json"
    progress_path = tmp_path / "progress.jsonl"
    error_path = tmp_path / "error.json"
    summary_path = tmp_path / "summary.json"
    _write_worker_input(input_path, game_id="missing-game")

    assert (
        worker_main(
            [
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
        )
        == 1
    )

    error = json.loads(error_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert error["status"] == "error"
    assert "missing-game" in error["message"]
    assert "traceback" in error
    assert summary["status"] == "error"
    assert not output_path.exists()


def test_progress_jsonl_writer_throttles_non_critical_events(tmp_path):
    progress_path = tmp_path / "progress.jsonl"
    with ProgressJsonlWriter(progress_path, "test-run", min_interval_seconds=60.0) as writer:
        writer.emit({"event": "unit_progress", "label": "first"})
        writer.emit({"event": "unit_progress", "label": "skipped"})
        writer.emit({"event": "complete", "label": "done"})

    events = [
        json.loads(line)
        for line in progress_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["label"] for event in events] == ["first", "done"]
