from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tomllib
from typing import Any

from gear_optimizer.game_rules import PROJECT_ROOT

APP_NAME = "gacha-gear-optimizer"
DEFAULT_MANIFEST = PROJECT_ROOT / "reports" / "release_artifact_manifest.json"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_version() -> str | None:
    try:
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    except Exception:
        return None
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    version = project.get("version")
    if isinstance(version, str) and version:
        return version
    return None


def _manifest_root(manifest_path: Path) -> Path:
    if manifest_path.parent.name.lower() == "reports":
        return manifest_path.parent.parent
    return manifest_path.parent


def _manifest_exe_path(manifest_path: Path, data: dict[str, Any]) -> Path:
    raw_exe_path = data.get("exe_path")
    if isinstance(raw_exe_path, str) and raw_exe_path:
        exe_path = Path(raw_exe_path)
        if exe_path.is_absolute():
            return exe_path
        return (manifest_path.parent / exe_path).resolve()

    raw_relative_path = data.get("relative_exe_path")
    if isinstance(raw_relative_path, str) and raw_relative_path:
        relative_path = Path(raw_relative_path)
        if relative_path.is_absolute():
            return relative_path
        return (_manifest_root(manifest_path) / relative_path).resolve()

    raise ValueError("manifest is missing exe_path")


def _is_iso_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    date_part, separator, suffix = normalized.partition(".")
    if separator:
        digit_count = 0
        for char in suffix:
            if not char.isdigit():
                break
            digit_count += 1
        fraction = suffix[:digit_count]
        remainder = suffix[digit_count:]
        if len(fraction) > 6:
            fraction = fraction[:6]
        normalized = f"{date_part}.{fraction}{remainder}"
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return True


def _manifest_metadata_rows(data: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    app = data.get("app")
    rows.append(
        {
            "item": "manifest app",
            "status": "ok" if app == APP_NAME else "error",
            "detail": f"manifest={app!r}; expected={APP_NAME}",
        }
    )

    version = data.get("version")
    expected_version = _project_version()
    version_ok = isinstance(version, str) and bool(version)
    if expected_version is not None:
        version_ok = version_ok and version == expected_version
    rows.append(
        {
            "item": "manifest version",
            "status": "ok" if version_ok else "error",
            "detail": f"manifest={version!r}; expected={expected_version or 'non-empty'}",
        }
    )

    for key, item in [
        ("generated_at", "generated at"),
        ("exe_last_write_time", "exe timestamp"),
    ]:
        value = data.get(key)
        rows.append(
            {
                "item": item,
                "status": "ok" if _is_iso_timestamp(value) else "error",
                "detail": str(value),
            }
        )

    relative_path = data.get("relative_exe_path")
    rows.append(
        {
            "item": "relative exe path",
            "status": "ok" if isinstance(relative_path, str) and bool(relative_path) else "error",
            "detail": str(relative_path),
        }
    )

    boolean_fields = ["one_file", "preflight_skipped", "smoke_check_requested"]
    invalid_boolean_fields = [
        field for field in boolean_fields if not isinstance(data.get(field), bool)
    ]
    rows.append(
        {
            "item": "release flags",
            "status": "ok" if not invalid_boolean_fields else "error",
            "detail": (
                "all boolean"
                if not invalid_boolean_fields
                else f"non-boolean: {', '.join(invalid_boolean_fields)}"
            ),
        }
    )

    smoke_requested = data.get("smoke_check_requested")
    smoke_passed = data.get("smoke_check_passed")
    if isinstance(smoke_requested, bool):
        if smoke_requested:
            smoke_ok = smoke_passed is True
            smoke_detail = f"requested=True; passed={smoke_passed!r}"
        else:
            smoke_ok = smoke_passed is None
            smoke_detail = f"requested=False; passed={smoke_passed!r}"
    else:
        smoke_ok = False
        smoke_detail = "smoke_check_requested is not boolean"
    rows.append(
        {
            "item": "smoke status",
            "status": "ok" if smoke_ok else "error",
            "detail": smoke_detail,
        }
    )

    smoke_timeout = data.get("smoke_timeout_seconds")
    timeout_ok = (
        isinstance(smoke_timeout, int)
        and not isinstance(smoke_timeout, bool)
        and smoke_timeout > 0
    )
    rows.append(
        {
            "item": "smoke timeout",
            "status": "ok" if timeout_ok else "error",
            "detail": str(smoke_timeout),
        }
    )

    pyinstaller_args = data.get("pyinstaller_args")
    args_ok = isinstance(pyinstaller_args, list) and all(
        isinstance(arg, str) for arg in pyinstaller_args
    )
    rows.append(
        {
            "item": "pyinstaller args",
            "status": "ok" if args_ok else "error",
            "detail": str(pyinstaller_args),
        }
    )

    return rows



def verify_manifest(path: str | Path = DEFAULT_MANIFEST) -> list[dict[str, str]]:
    manifest_path = Path(path)
    rows: list[dict[str, str]] = []
    if not manifest_path.exists():
        return [
            {
                "item": "manifest",
                "status": "missing",
                "detail": str(manifest_path),
            }
        ]

    rows.append({"item": "manifest", "status": "ok", "detail": str(manifest_path)})
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        rows.append({"item": "manifest json", "status": "error", "detail": str(exc)})
        return rows
    if not isinstance(data, dict):
        rows.append({"item": "manifest json", "status": "error", "detail": "expected object"})
        return rows
    rows.append({"item": "manifest json", "status": "ok", "detail": "parsed"})
    rows.extend(_manifest_metadata_rows(data))

    try:
        exe_path = _manifest_exe_path(manifest_path, data)
    except ValueError as exc:
        rows.append({"item": "exe path", "status": "error", "detail": str(exc)})
        return rows

    if not exe_path.exists():
        rows.append({"item": "exe file", "status": "missing", "detail": str(exe_path)})
        return rows
    rows.append({"item": "exe file", "status": "ok", "detail": str(exe_path)})

    expected_size = data.get("exe_size_bytes")
    actual_size = exe_path.stat().st_size
    rows.append(
        {
            "item": "exe size",
            "status": "ok" if expected_size == actual_size else "error",
            "detail": f"manifest={expected_size}; actual={actual_size}",
        }
    )

    expected_sha = data.get("exe_sha256")
    actual_sha = _sha256(exe_path)
    rows.append(
        {
            "item": "exe sha256",
            "status": "ok" if expected_sha == actual_sha else "error",
            "detail": f"manifest={expected_sha}; actual={actual_sha}",
        }
    )
    return rows


def manifest_checks_pass(rows: list[dict[str, str]]) -> bool:
    return all(row["status"] == "ok" for row in rows)


def format_manifest_checks(rows: list[dict[str, str]]) -> str:
    width = max(len(row["item"]) for row in rows)
    return "\n".join(
        f"{row['item']:<{width}}  {row['status']:<7}  {row['detail']}"
        for row in rows
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a gacha-gear-optimizer release artifact manifest.",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to release_artifact_manifest.json.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = verify_manifest(args.manifest)
    print(format_manifest_checks(rows))
    return 0 if manifest_checks_pass(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
