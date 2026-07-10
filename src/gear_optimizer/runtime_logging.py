from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
import time
from typing import Any
import uuid

from gear_optimizer.paths import app_data_root

DEFAULT_RUNTIME_LOG_NAME = "ui-runtime.log"
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3
RUNTIME_SESSION_ID = uuid.uuid4().hex
_RUNTIME_LOG_LOCK = RLock()


def runtime_log_path(name: str = DEFAULT_RUNTIME_LOG_NAME) -> Path:
    return app_data_root() / "logs" / name


def _rotated_path(path: Path, index: int) -> Path:
    return path.with_name(f"{path.name}.{index}")


def _rotate_if_needed(path: Path, *, max_bytes: int, backup_count: int) -> None:
    if max_bytes <= 0 or backup_count <= 0 or not path.exists():
        return
    if path.stat().st_size < max_bytes:
        return
    _rotated_path(path, backup_count).unlink(missing_ok=True)
    for index in range(backup_count - 1, 0, -1):
        source = _rotated_path(path, index)
        if source.exists():
            os.replace(source, _rotated_path(path, index + 1))
    os.replace(path, _rotated_path(path, 1))


def append_runtime_event(
    path: Path,
    event: str,
    *,
    source: str,
    session_id: str = RUNTIME_SESSION_ID,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    **fields: Any,
) -> None:
    payload = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S%z"),
        "pid": os.getpid(),
        "session_id": session_id,
        "source": source,
        "event": event,
        **fields,
    }
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    with _RUNTIME_LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(path, max_bytes=max_bytes, backup_count=backup_count)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
