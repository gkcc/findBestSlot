from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from gear_optimizer.game_rules import PROJECT_ROOT
from gear_optimizer.release_manifest import _manifest_exe_path, manifest_checks_pass, verify_manifest

DEFAULT_ACCEPTANCE_CHECKS = PROJECT_ROOT / "reports" / "first_version_acceptance_checks.json"
DEFAULT_APP_SMOKE_CHECKS = PROJECT_ROOT / "reports" / "source_app_smoke_checks.json"
DEFAULT_PYTEST_REPORT = PROJECT_ROOT / "reports" / "pytest.xml"
DEFAULT_RELEASE_MANIFEST = PROJECT_ROOT / "reports" / "release_artifact_manifest.json"
EVIDENCE_FRESHNESS_INPUTS = [
    PROJECT_ROOT / "app.py",
    PROJECT_ROOT / "desktop_app.py",
    PROJECT_ROOT / "pyproject.toml",
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "configs",
    PROJECT_ROOT / "examples",
    PROJECT_ROOT / "assets",
]
EVIDENCE_FRESHNESS_SUFFIXES = {".png", ".py", ".toml", ".yaml", ".yml"}
PYTEST_FRESHNESS_INPUTS = [
    PROJECT_ROOT / "app.py",
    PROJECT_ROOT / "desktop_app.py",
    PROJECT_ROOT / "pyproject.toml",
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "scripts",
    PROJECT_ROOT / "configs",
    PROJECT_ROOT / "examples",
]
PYTEST_FRESHNESS_SUFFIXES = {".cmd", ".ps1", ".py", ".toml", ".yaml", ".yml"}
FRESHNESS_TOLERANCE_SECONDS = 1.0


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _utc_timestamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _summarize_bad_rows(rows: list[dict[str, Any]], status_key: str) -> str:
    bad_rows = [row for row in rows if row.get(status_key) != "ok"]
    if not bad_rows:
        return "all checks ok"
    names = [
        str(row.get("检查项") or row.get("item") or row.get("id") or "unknown")
        for row in bad_rows[:5]
    ]
    suffix = "" if len(bad_rows) <= 5 else f"; +{len(bad_rows) - 5} more"
    return f"{len(bad_rows)} failing check(s): {', '.join(names)}{suffix}"


def _acceptance_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return [
            {
                "item": "acceptance checks",
                "status": "missing",
                "detail": str(path),
            }
        ]

    try:
        data = _read_json(path)
    except Exception as exc:
        return [
            {
                "item": "acceptance checks",
                "status": "error",
                "detail": str(exc),
            }
        ]

    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        return [
            {
                "item": "acceptance checks",
                "status": "error",
                "detail": "expected a list of check rows",
            }
        ]

    ok_count = sum(1 for row in data if row.get("状态") == "ok")
    all_ok = ok_count == len(data) and len(data) > 0
    return [
        {
            "item": "acceptance checks",
            "status": "ok" if all_ok else "error",
            "detail": f"{ok_count}/{len(data)} checks ok; {path}",
        },
        {
            "item": "acceptance evidence",
            "status": "ok" if all_ok else "error",
            "detail": _summarize_bad_rows(data, "状态"),
        },
        _freshness_row(
            "acceptance freshness",
            path,
            EVIDENCE_FRESHNESS_INPUTS,
            EVIDENCE_FRESHNESS_SUFFIXES,
        ),
    ]


def _source_app_smoke_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return [
            {
                "item": "source app smoke",
                "status": "missing",
                "detail": str(path),
            }
        ]

    try:
        data = _read_json(path)
    except Exception as exc:
        return [
            {
                "item": "source app smoke",
                "status": "error",
                "detail": str(exc),
            }
        ]

    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        return [
            {
                "item": "source app smoke",
                "status": "error",
                "detail": "expected a list of check rows",
            }
        ]

    ok_count = sum(1 for row in data if row.get("status") == "ok")
    all_ok = ok_count == len(data) and len(data) > 0
    return [
        {
            "item": "source app smoke",
            "status": "ok" if all_ok else "error",
            "detail": f"{ok_count}/{len(data)} checks ok; {path}",
        },
        {
            "item": "source app evidence",
            "status": "ok" if all_ok else "error",
            "detail": _summarize_bad_rows(data, "status"),
        },
        _freshness_row(
            "source app freshness",
            path,
            EVIDENCE_FRESHNESS_INPUTS,
            EVIDENCE_FRESHNESS_SUFFIXES,
        ),
    ]


def _int_xml_attr(element: ET.Element, name: str) -> int:
    raw_value = element.attrib.get(name, "0")
    try:
        return int(float(raw_value))
    except ValueError:
        return 0


def _iter_freshness_inputs(inputs: list[Path], suffixes: set[str]) -> list[Path]:
    files: list[Path] = []
    for root in inputs:
        if root.is_file() and root.suffix.lower() in suffixes:
            files.append(root)
        elif root.is_dir():
            files.extend(
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.suffix.lower() in suffixes
                and "__pycache__" not in path.parts
            )
    return files


def _newest_freshness_input(inputs: list[Path], suffixes: set[str]) -> tuple[Path, float] | None:
    newest: tuple[Path, float] | None = None
    for path in _iter_freshness_inputs(inputs, suffixes):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if newest is None or mtime > newest[1]:
            newest = (path, mtime)
    return newest


def _freshness_row(
    item: str,
    report_path: Path,
    inputs: list[Path],
    suffixes: set[str],
) -> dict[str, str]:
    newest = _newest_freshness_input(inputs, suffixes)
    if newest is None:
        return {
            "item": item,
            "status": "error",
            "detail": "no source inputs found for freshness check",
        }

    newest_path, newest_mtime = newest
    report_mtime = report_path.stat().st_mtime
    fresh = report_mtime + FRESHNESS_TOLERANCE_SECONDS >= newest_mtime
    return {
        "item": item,
        "status": "ok" if fresh else "error",
        "detail": (
            f"report={_utc_timestamp(report_mtime)}; "
            f"newest_input={_utc_timestamp(newest_mtime)} {newest_path}"
        ),
    }


def _pytest_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return [
            {
                "item": "pytest report",
                "status": "missing",
                "detail": str(path),
            }
        ]

    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        return [
            {
                "item": "pytest report",
                "status": "error",
                "detail": str(exc),
            }
        ]

    if root.tag == "testsuite":
        suites = [root]
    else:
        suites = list(root.findall(".//testsuite"))
    if not suites:
        return [
            {
                "item": "pytest report",
                "status": "error",
                "detail": "no testsuite entries found",
            }
        ]

    tests = sum(_int_xml_attr(suite, "tests") for suite in suites)
    failures = sum(_int_xml_attr(suite, "failures") for suite in suites)
    errors = sum(_int_xml_attr(suite, "errors") for suite in suites)
    skipped = sum(_int_xml_attr(suite, "skipped") for suite in suites)
    passed = tests - failures - errors - skipped
    passed = max(passed, 0)
    ok = tests > 0 and failures == 0 and errors == 0
    rows = [
        {
            "item": "pytest report",
            "status": "ok" if ok else "error",
            "detail": (
                f"{tests} tests; {passed} passed; {failures} failures; "
                f"{errors} errors; {skipped} skipped; {path}"
            ),
        }
    ]
    rows.append(
        _freshness_row(
            "pytest freshness",
            path,
            PYTEST_FRESHNESS_INPUTS,
            PYTEST_FRESHNESS_SUFFIXES,
        )
    )
    return rows


def _manifest_rows(path: Path) -> list[dict[str, str]]:
    manifest_rows = verify_manifest(path)
    manifest_ok = manifest_checks_pass(manifest_rows)
    rows = [
        {
            "item": "release manifest",
            "status": "ok" if manifest_ok else "error",
            "detail": _summarize_bad_rows(manifest_rows, "status"),
        }
    ]
    if not manifest_ok:
        return rows

    data = _read_json(path)
    one_file = data.get("one_file")
    rows.append(
        {
            "item": "release artifact shape",
            "status": "ok" if one_file is False else "error",
            "detail": (
                "default onedir artifact recorded"
                if one_file is False
                else "current first-version release record is not the default onedir artifact"
            ),
        }
    )
    rows.append(
        {
            "item": "package smoke",
            "status": "ok"
            if data.get("smoke_check_requested") is True and data.get("smoke_check_passed") is True
            else "error",
            "detail": (
                f"requested={data.get('smoke_check_requested')!r}; "
                f"passed={data.get('smoke_check_passed')!r}"
            ),
        }
    )
    rows.append(
        {
            "item": "smoke timeout",
            "status": "ok",
            "detail": f"{data.get('smoke_timeout_seconds')} second(s)",
        }
    )
    exe_path = _manifest_exe_path(path, data)
    rows.append(
        _freshness_row(
            "package freshness",
            exe_path,
            EVIDENCE_FRESHNESS_INPUTS,
            EVIDENCE_FRESHNESS_SUFFIXES,
        )
    )
    return rows


def _readiness_metadata_rows(
    acceptance_path: Path,
    app_smoke_path: Path,
    manifest_path: Path,
    pytest_path: Path | None,
) -> list[dict[str, str]]:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if generated_at.endswith("+00:00"):
        generated_at = f"{generated_at[:-6]}Z"
    pytest_detail = str(pytest_path) if pytest_path else "<not requested>"
    return [
        {
            "item": "readiness generated at",
            "status": "ok",
            "detail": generated_at,
        },
        {
            "item": "readiness inputs",
            "status": "ok",
            "detail": (
                f"acceptance={acceptance_path}; "
                f"app_smoke={app_smoke_path}; "
                f"pytest={pytest_detail}; "
                f"manifest={manifest_path}"
            ),
        },
    ]


def readiness_rows(
    acceptance_checks: str | Path = DEFAULT_ACCEPTANCE_CHECKS,
    app_smoke_checks: str | Path = DEFAULT_APP_SMOKE_CHECKS,
    manifest: str | Path = DEFAULT_RELEASE_MANIFEST,
    pytest_report: str | Path | None = None,
) -> list[dict[str, str]]:
    acceptance_path = Path(acceptance_checks)
    app_smoke_path = Path(app_smoke_checks)
    manifest_path = Path(manifest)
    pytest_path = Path(pytest_report) if pytest_report else None
    rows = [
        *_readiness_metadata_rows(acceptance_path, app_smoke_path, manifest_path, pytest_path),
        *_acceptance_rows(acceptance_path),
        *_source_app_smoke_rows(app_smoke_path),
    ]
    if pytest_path:
        rows.extend(_pytest_rows(pytest_path))
    rows.extend(_manifest_rows(manifest_path))
    return rows


def readiness_checks_pass(rows: list[dict[str, str]]) -> bool:
    return all(row["status"] == "ok" for row in rows)


def format_readiness_rows(rows: list[dict[str, str]]) -> str:
    width = max(len(row["item"]) for row in rows)
    return "\n".join(
        f"{row['item']:<{width}}  {row['status']:<7}  {row['detail']}"
        for row in rows
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify first-version release readiness for gacha-gear-optimizer.",
    )
    parser.add_argument(
        "--acceptance-checks",
        default=str(DEFAULT_ACCEPTANCE_CHECKS),
        help="Path to first_version_acceptance_checks.json.",
    )
    parser.add_argument(
        "--app-smoke-checks",
        default=str(DEFAULT_APP_SMOKE_CHECKS),
        help="Path to source_app_smoke_checks.json.",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_RELEASE_MANIFEST),
        help="Path to release_artifact_manifest.json.",
    )
    parser.add_argument(
        "--pytest-report",
        default=str(DEFAULT_PYTEST_REPORT),
        help="Path to a pytest JUnit XML report.",
    )
    parser.add_argument(
        "--skip-pytest-report",
        action="store_true",
        help="Do not include pytest JUnit XML evidence in readiness checks.",
    )
    parser.add_argument(
        "--json",
        default="",
        help="Optional path to write machine-readable readiness rows.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = readiness_rows(
        args.acceptance_checks,
        args.app_smoke_checks,
        args.manifest,
        None if args.skip_pytest_report else args.pytest_report,
    )
    print(format_readiness_rows(rows))
    if args.json:
        output_path = Path(args.json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote readiness checks: {output_path}")
    return 0 if readiness_checks_pass(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
