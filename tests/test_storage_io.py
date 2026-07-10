import multiprocessing
from pathlib import Path
import time

import pytest

import gear_optimizer.storage_io as storage_io
from gear_optimizer.storage_io import (
    StoreLockTimeoutError,
    StoreRevisionConflictError,
    UnsupportedStoreVersionError,
    atomic_compare_and_swap_yaml,
    atomic_write_text,
    atomic_write_yaml,
    read_yaml_mapping,
    store_file_lock,
    update_yaml_mapping_locked,
    validate_store_schema_version,
)


def _temporary_files(path: Path) -> list[Path]:
    return list(path.parent.glob(f".{path.name}.*.tmp"))


def _hold_store_lock(path_text: str, ready, release) -> None:
    with store_file_lock(Path(path_text), timeout_seconds=2.0):
        ready.set()
        if not release.wait(5.0):
            raise TimeoutError("test did not release held store lock")


def _append_yaml_value(path_text: str, value: str, start) -> None:
    if not start.wait(5.0):
        raise TimeoutError("test did not start concurrent YAML update")

    def update(data):
        values = list(data.get("values", []))
        time.sleep(0.05)
        values.append(value)
        return {"values": values}

    update_yaml_mapping_locked(Path(path_text), update)


def test_atomic_write_yaml_replaces_existing_mapping(tmp_path):
    path = tmp_path / "nested" / "store.yaml"
    atomic_write_yaml(path, {"version": 1})
    atomic_write_yaml(path, {"version": 2, "label": "测试"})

    assert read_yaml_mapping(path) == {"version": 2, "label": "测试"}
    assert _temporary_files(path) == []


def test_atomic_write_failure_preserves_previous_file(monkeypatch, tmp_path):
    path = tmp_path / "store.yaml"
    atomic_write_text(path, "version: 1\n")

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(storage_io.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_text(path, "version: 2\n")

    assert path.read_text(encoding="utf-8") == "version: 1\n"
    assert _temporary_files(path) == []


def test_read_yaml_mapping_rejects_non_mapping(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("- list item\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected YAML mapping"):
        read_yaml_mapping(path)


def test_atomic_write_can_keep_previous_file_as_backup(tmp_path):
    path = tmp_path / "store.yaml"
    atomic_write_text(path, "version: 1\n")

    atomic_write_text(path, "version: 2\n", backup_existing=True)

    assert path.read_text(encoding="utf-8") == "version: 2\n"
    assert (tmp_path / "store.yaml.bak").read_text(encoding="utf-8") == "version: 1\n"


def test_store_schema_rejects_future_or_invalid_versions(tmp_path):
    path = tmp_path / "store.yaml"

    assert validate_store_schema_version({}, path) == 0
    assert validate_store_schema_version({"schema_version": 1}, path) == 1
    with pytest.raises(UnsupportedStoreVersionError, match="supports up to 1"):
        validate_store_schema_version({"schema_version": 2}, path)
    with pytest.raises(ValueError, match="non-negative integer"):
        validate_store_schema_version({"schema_version": "1"}, path)


def test_compare_and_swap_rejects_stale_writer_without_losing_latest_data(tmp_path):
    path = tmp_path / "store.yaml"
    assert atomic_compare_and_swap_yaml(path, {"value": "initial"}, expected_revision=0) == 1
    first_reader = read_yaml_mapping(path)
    stale_reader = read_yaml_mapping(path)

    assert atomic_compare_and_swap_yaml(
        path,
        {"value": "first writer"},
        expected_revision=first_reader["revision"],
    ) == 2
    with pytest.raises(StoreRevisionConflictError, match="另一个窗口修改"):
        atomic_compare_and_swap_yaml(
            path,
            {"value": "stale writer"},
            expected_revision=stale_reader["revision"],
        )

    assert read_yaml_mapping(path) == {"value": "first writer", "revision": 2}


def test_store_file_lock_blocks_another_process_and_reports_timeout(tmp_path):
    path = tmp_path / "store.yaml"
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(target=_hold_store_lock, args=(str(path), ready, release))
    process.start()
    try:
        assert ready.wait(5.0)
        with pytest.raises(StoreLockTimeoutError, match="另一个窗口正在保存"):
            with store_file_lock(path, timeout_seconds=0.05):
                pass
    finally:
        release.set()
        process.join(5.0)
        if process.is_alive():
            process.terminate()
            process.join(5.0)
    assert process.exitcode == 0


def test_locked_yaml_updates_from_two_processes_preserve_both_changes(tmp_path):
    path = tmp_path / "store.yaml"
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    processes = [
        context.Process(target=_append_yaml_value, args=(str(path), value, start))
        for value in ("a", "b")
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(5.0)
        if process.is_alive():
            process.terminate()
            process.join(5.0)

    assert [process.exitcode for process in processes] == [0, 0]
    data = read_yaml_mapping(path)
    assert sorted(data["values"]) == ["a", "b"]
    assert data["revision"] == 2
