from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
from contextlib import contextmanager
from collections.abc import Callable, Iterator, Mapping
from typing import Any

import yaml

USER_STORE_SCHEMA_VERSION = 1
STORE_REVISION_KEY = "revision"


class UnsupportedStoreVersionError(ValueError):
    pass


class StoreConcurrencyError(RuntimeError):
    pass


class StoreRevisionConflictError(StoreConcurrencyError):
    pass


class StoreLockTimeoutError(StoreConcurrencyError, TimeoutError):
    pass


def safe_storage_id(value: str, *, fallback: str) -> str:
    text = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in text.split("_") if part) or fallback


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return data


def validate_store_schema_version(
    data: dict[str, Any],
    path: Path,
    *,
    supported_version: int = USER_STORE_SCHEMA_VERSION,
) -> int:
    raw_version = data.get("schema_version", 0)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version < 0:
        raise ValueError(f"schema_version must be a non-negative integer in {path}")
    if raw_version > supported_version:
        raise UnsupportedStoreVersionError(
            f"Unsupported schema_version {raw_version} in {path}; "
            f"this app supports up to {supported_version}"
        )
    return raw_version


def store_revision(data: Mapping[str, Any], path: Path | None = None) -> int:
    raw_revision = data.get(STORE_REVISION_KEY, 0)
    location = f" in {path}" if path is not None else ""
    if (
        isinstance(raw_revision, bool)
        or not isinstance(raw_revision, int)
        or raw_revision < 0
    ):
        raise ValueError(f"{STORE_REVISION_KEY} must be a non-negative integer{location}")
    return raw_revision


@contextmanager
def store_file_lock(
    path: Path,
    *,
    timeout_seconds: float = 5.0,
) -> Iterator[None]:
    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be non-negative")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    deadline = time.monotonic() + timeout_seconds
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()

        while True:
            try:
                _acquire_file_lock(handle)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise StoreLockTimeoutError(
                        f"另一个窗口正在保存用户数据，等待文件锁超时：{lock_path}"
                    ) from exc
                time.sleep(0.02)

        try:
            yield
        finally:
            _release_file_lock(handle)


def _acquire_file_lock(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_file_lock(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def update_yaml_mapping_locked(
    path: Path,
    updater: Callable[[dict[str, Any]], Mapping[str, Any] | None],
    *,
    backup_existing: bool = False,
    timeout_seconds: float = 5.0,
) -> dict[str, Any] | None:
    with store_file_lock(path, timeout_seconds=timeout_seconds):
        current = read_yaml_mapping(path)
        current_revision = store_revision(current, path)
        updated = updater(dict(current))
        if updated is None:
            if path.exists():
                if backup_existing:
                    backup_existing_file(path)
                path.unlink()
            return None
        payload = dict(updated)
        comparable_current = dict(current)
        comparable_current.pop(STORE_REVISION_KEY, None)
        comparable_payload = dict(payload)
        comparable_payload.pop(STORE_REVISION_KEY, None)
        if comparable_payload == comparable_current:
            return current
        payload[STORE_REVISION_KEY] = current_revision + 1
        atomic_write_yaml(path, payload, backup_existing=backup_existing)
        return payload


def backup_existing_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup_path = path.with_name(f"{path.name}.bak")
    atomic_write_text(backup_path, path.read_text(encoding="utf-8"))
    return backup_path


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    backup_existing: bool = False,
) -> None:
    if backup_existing:
        backup_existing_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def atomic_write_yaml(path: Path, data: Any, *, backup_existing: bool = False) -> None:
    payload = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    atomic_write_text(path, payload, backup_existing=backup_existing)


def atomic_compare_and_swap_yaml(
    path: Path,
    data: Mapping[str, Any],
    *,
    expected_revision: int,
    backup_existing: bool = False,
) -> int:
    if isinstance(expected_revision, bool) or expected_revision < 0:
        raise ValueError("expected_revision must be non-negative")
    with store_file_lock(path):
        current = read_yaml_mapping(path)
        actual_revision = store_revision(current, path)
        if actual_revision != expected_revision:
            raise StoreRevisionConflictError(
                f"用户数据已被另一个窗口修改：{path} "
                f"（当前副本 revision={expected_revision}，磁盘 revision={actual_revision}）。"
                "请重新载入后再保存。"
            )
        next_revision = expected_revision + 1
        payload = dict(data)
        payload[STORE_REVISION_KEY] = next_revision
        atomic_write_yaml(path, payload, backup_existing=backup_existing)
        return next_revision
