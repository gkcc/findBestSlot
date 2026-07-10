import json

from gear_optimizer.runtime_logging import append_runtime_event


def _events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_runtime_event_includes_process_context(tmp_path):
    path = tmp_path / "runtime.log"

    append_runtime_event(
        path,
        "test_event",
        source="test",
        session_id="session-1",
        game_id="zzz",
        run_id="run-1",
    )

    event = _events(path)[0]
    assert event["event"] == "test_event"
    assert event["source"] == "test"
    assert event["session_id"] == "session-1"
    assert event["game_id"] == "zzz"
    assert event["run_id"] == "run-1"
    assert event["pid"] > 0
    assert event["ts"]


def test_runtime_event_log_rotates_by_size(tmp_path):
    path = tmp_path / "runtime.log"
    path.write_text("x" * 100, encoding="utf-8")

    append_runtime_event(
        path,
        "after_rotate",
        source="test",
        session_id="session-2",
        max_bytes=50,
        backup_count=2,
    )

    assert (tmp_path / "runtime.log.1").read_text(encoding="utf-8") == "x" * 100
    assert _events(path)[0]["event"] == "after_rotate"
