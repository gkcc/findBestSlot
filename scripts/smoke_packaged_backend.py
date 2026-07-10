from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from typing import Any


def _request() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": "tauri-package-smoke-\u2022",
        "method": "workspace.get",
        "params": {"game_id": "zzz", "agent_id": ""},
    }


def _parse_response(stdout: str, request_id: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError(f"expected one NDJSON response line, received {len(lines)}")
    response = json.loads(lines[0])
    if response.get("request_id") != request_id:
        raise ValueError("NDJSON response request_id does not match the request")
    if not response.get("ok"):
        raise ValueError(f"NDJSON backend error: {response.get('error')!r}")
    if not (response.get("data") or {}).get("workspace"):
        raise ValueError("NDJSON response does not contain data.workspace")
    return response


def run_smoke(
    backend: Path,
    project_root: Path,
    user_data: Path,
    worker: Path,
    timeout: float,
) -> dict[str, Any]:
    request = _request()
    environment = os.environ.copy()
    environment.update(
        {
            "GEAR_OPTIMIZER_PROJECT_ROOT": str(project_root),
            "GEAR_OPTIMIZER_USER_DATA_DIR": str(user_data),
            "GEAR_OPTIMIZER_ACTION_WORKER": str(worker),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    completed = subprocess.run(
        [str(backend)],
        input=json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=timeout,
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"backend exited with {completed.returncode}; stderr={completed.stderr!r}"
        )
    try:
        return _parse_response(completed.stdout, request["request_id"])
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"invalid backend response: {exc}; stdout={completed.stdout!r}; "
            f"stderr={completed.stderr!r}"
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test a packaged desktop NDJSON backend.")
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--user-data", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_smoke(
        args.backend.resolve(),
        args.project_root.resolve(),
        args.user_data.resolve(),
        args.worker.resolve(),
        args.timeout,
    )
    print("Packaged desktop backend NDJSON stream check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
