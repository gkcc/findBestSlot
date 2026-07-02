import hashlib
import json
import os
from pathlib import Path
from datetime import datetime

from gear_optimizer.readiness import (
    format_readiness_rows,
    main as readiness_main,
    readiness_checks_pass,
    readiness_rows,
)


def _write_acceptance_checks(path: Path, status: str = "ok") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "id": "six_core_questions",
                    "检查项": "六个核心问题",
                    "状态": status,
                    "证据": "## 六个核心问题",
                    "缺失": "" if status == "ok" else "## 六个核心问题",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_app_smoke_checks(path: Path, status: str = "ok") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "item": "PySide6 app",
                    "status": status,
                    "detail": "native UI module importable" if status == "ok" else "failed",
                }
            ]
        ),
        encoding="utf-8",
    )


def _write_pytest_report(path: Path, failures: int = 0, errors: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tests = 5
    skipped = 1
    path.write_text(
        (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<testsuites>'
            f'<testsuite name="pytest" tests="{tests}" failures="{failures}" '
            f'errors="{errors}" skipped="{skipped}">'
            '<testcase classname="tests.test_example" name="test_ok" />'
            "</testsuite>"
            "</testsuites>"
        ),
        encoding="utf-8",
    )


def _write_manifest(path: Path, one_file: bool = False, smoke_passed: bool = True) -> None:
    exe = path.parent.parent / "dist" / "gacha-gear-optimizer.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    payload = b"release"
    exe.write_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "app": "gacha-gear-optimizer",
                "version": "0.1.0",
                "generated_at": "2026-07-01T07:29:55Z",
                "exe_path": str(exe),
                "relative_exe_path": str(Path("dist") / "gacha-gear-optimizer.exe"),
                "exe_size_bytes": len(payload),
                "exe_sha256": hashlib.sha256(payload).hexdigest(),
                "exe_last_write_time": "2026-07-01T07:29:51Z",
                "one_file": one_file,
                "preflight_skipped": True,
                "smoke_check_requested": True,
                "smoke_check_passed": smoke_passed,
                "smoke_timeout_seconds": 45,
                "pyinstaller_args": [],
            }
        ),
        encoding="utf-8",
    )


def test_readiness_passes_for_acceptance_and_default_onedir_manifest(tmp_path):
    acceptance = tmp_path / "reports" / "first_version_acceptance_checks.json"
    app_smoke = tmp_path / "reports" / "source_app_smoke_checks.json"
    pytest_report = tmp_path / "reports" / "pytest.xml"
    manifest = tmp_path / "reports" / "release_artifact_manifest.json"
    _write_acceptance_checks(acceptance)
    _write_app_smoke_checks(app_smoke)
    _write_pytest_report(pytest_report)
    _write_manifest(manifest)

    rows = readiness_rows(acceptance, app_smoke, manifest, pytest_report)
    by_item = {row["item"]: row for row in rows}

    assert readiness_checks_pass(rows)
    assert by_item["readiness generated at"]["status"] == "ok"
    assert by_item["readiness generated at"]["detail"].endswith("Z")
    datetime.fromisoformat(by_item["readiness generated at"]["detail"].replace("Z", "+00:00"))
    assert by_item["readiness inputs"]["status"] == "ok"
    assert str(acceptance) in by_item["readiness inputs"]["detail"]
    assert str(app_smoke) in by_item["readiness inputs"]["detail"]
    assert str(pytest_report) in by_item["readiness inputs"]["detail"]
    assert str(manifest) in by_item["readiness inputs"]["detail"]
    assert by_item["acceptance checks"]["status"] == "ok"
    assert by_item["acceptance freshness"]["status"] == "ok"
    assert by_item["source app smoke"]["status"] == "ok"
    assert by_item["source app freshness"]["status"] == "ok"
    assert by_item["pytest report"]["status"] == "ok"
    assert by_item["pytest freshness"]["status"] == "ok"
    assert by_item["release manifest"]["status"] == "ok"
    assert by_item["release artifact shape"]["detail"] == "default onedir artifact recorded"
    assert by_item["package freshness"]["status"] == "ok"
    assert "package smoke" in format_readiness_rows(rows)


def test_readiness_detects_acceptance_failure(tmp_path):
    acceptance = tmp_path / "reports" / "first_version_acceptance_checks.json"
    app_smoke = tmp_path / "reports" / "source_app_smoke_checks.json"
    manifest = tmp_path / "reports" / "release_artifact_manifest.json"
    _write_acceptance_checks(acceptance, status="missing")
    _write_app_smoke_checks(app_smoke)
    _write_manifest(manifest)

    rows = readiness_rows(acceptance, app_smoke, manifest)
    by_item = {row["item"]: row for row in rows}

    assert not readiness_checks_pass(rows)
    assert by_item["acceptance checks"]["status"] == "error"
    assert by_item["acceptance evidence"]["status"] == "error"


def test_readiness_detects_source_app_smoke_failure(tmp_path):
    acceptance = tmp_path / "reports" / "first_version_acceptance_checks.json"
    app_smoke = tmp_path / "reports" / "source_app_smoke_checks.json"
    manifest = tmp_path / "reports" / "release_artifact_manifest.json"
    _write_acceptance_checks(acceptance)
    _write_app_smoke_checks(app_smoke, status="error")
    _write_manifest(manifest)

    rows = readiness_rows(acceptance, app_smoke, manifest)
    by_item = {row["item"]: row for row in rows}

    assert not readiness_checks_pass(rows)
    assert by_item["source app smoke"]["status"] == "error"
    assert by_item["source app evidence"]["status"] == "error"


def test_readiness_detects_stale_acceptance_checks(tmp_path):
    acceptance = tmp_path / "reports" / "first_version_acceptance_checks.json"
    app_smoke = tmp_path / "reports" / "source_app_smoke_checks.json"
    manifest = tmp_path / "reports" / "release_artifact_manifest.json"
    _write_acceptance_checks(acceptance)
    _write_app_smoke_checks(app_smoke)
    _write_manifest(manifest)
    os.utime(acceptance, (1, 1))

    rows = readiness_rows(acceptance, app_smoke, manifest)
    by_item = {row["item"]: row for row in rows}

    assert not readiness_checks_pass(rows)
    assert by_item["acceptance checks"]["status"] == "ok"
    assert by_item["acceptance freshness"]["status"] == "error"


def test_readiness_detects_stale_source_app_smoke(tmp_path):
    acceptance = tmp_path / "reports" / "first_version_acceptance_checks.json"
    app_smoke = tmp_path / "reports" / "source_app_smoke_checks.json"
    manifest = tmp_path / "reports" / "release_artifact_manifest.json"
    _write_acceptance_checks(acceptance)
    _write_app_smoke_checks(app_smoke)
    _write_manifest(manifest)
    os.utime(app_smoke, (1, 1))

    rows = readiness_rows(acceptance, app_smoke, manifest)
    by_item = {row["item"]: row for row in rows}

    assert not readiness_checks_pass(rows)
    assert by_item["source app smoke"]["status"] == "ok"
    assert by_item["source app freshness"]["status"] == "error"


def test_readiness_detects_pytest_failure_report(tmp_path):
    acceptance = tmp_path / "reports" / "first_version_acceptance_checks.json"
    app_smoke = tmp_path / "reports" / "source_app_smoke_checks.json"
    pytest_report = tmp_path / "reports" / "pytest.xml"
    manifest = tmp_path / "reports" / "release_artifact_manifest.json"
    _write_acceptance_checks(acceptance)
    _write_app_smoke_checks(app_smoke)
    _write_pytest_report(pytest_report, failures=1)
    _write_manifest(manifest)

    rows = readiness_rows(acceptance, app_smoke, manifest, pytest_report)
    by_item = {row["item"]: row for row in rows}

    assert not readiness_checks_pass(rows)
    assert by_item["pytest report"]["status"] == "error"
    assert "1 failures" in by_item["pytest report"]["detail"]


def test_readiness_detects_stale_pytest_report(tmp_path):
    acceptance = tmp_path / "reports" / "first_version_acceptance_checks.json"
    app_smoke = tmp_path / "reports" / "source_app_smoke_checks.json"
    pytest_report = tmp_path / "reports" / "pytest.xml"
    manifest = tmp_path / "reports" / "release_artifact_manifest.json"
    _write_acceptance_checks(acceptance)
    _write_app_smoke_checks(app_smoke)
    _write_pytest_report(pytest_report)
    _write_manifest(manifest)
    os.utime(pytest_report, (1, 1))

    rows = readiness_rows(acceptance, app_smoke, manifest, pytest_report)
    by_item = {row["item"]: row for row in rows}

    assert not readiness_checks_pass(rows)
    assert by_item["pytest report"]["status"] == "ok"
    assert by_item["pytest freshness"]["status"] == "error"


def test_readiness_requires_default_onedir_release_record(tmp_path):
    acceptance = tmp_path / "reports" / "first_version_acceptance_checks.json"
    app_smoke = tmp_path / "reports" / "source_app_smoke_checks.json"
    manifest = tmp_path / "reports" / "release_artifact_manifest.json"
    _write_acceptance_checks(acceptance)
    _write_app_smoke_checks(app_smoke)
    _write_manifest(manifest, one_file=True)

    rows = readiness_rows(acceptance, app_smoke, manifest)
    by_item = {row["item"]: row for row in rows}

    assert not readiness_checks_pass(rows)
    assert by_item["release artifact shape"]["status"] == "error"


def test_readiness_detects_stale_package_artifact(tmp_path):
    acceptance = tmp_path / "reports" / "first_version_acceptance_checks.json"
    app_smoke = tmp_path / "reports" / "source_app_smoke_checks.json"
    manifest_path = tmp_path / "reports" / "release_artifact_manifest.json"
    _write_acceptance_checks(acceptance)
    _write_app_smoke_checks(app_smoke)
    _write_manifest(manifest_path)
    manifest = manifest_path
    exe = tmp_path / "dist" / "gacha-gear-optimizer.exe"
    os.utime(exe, (1, 1))

    rows = readiness_rows(acceptance, app_smoke, manifest)
    by_item = {row["item"]: row for row in rows}

    assert not readiness_checks_pass(rows)
    assert by_item["release manifest"]["status"] == "ok"
    assert by_item["package freshness"]["status"] == "error"


def test_readiness_cli_can_write_json(tmp_path, capsys):
    acceptance = tmp_path / "reports" / "first_version_acceptance_checks.json"
    app_smoke = tmp_path / "reports" / "source_app_smoke_checks.json"
    pytest_report = tmp_path / "reports" / "pytest.xml"
    manifest = tmp_path / "reports" / "release_artifact_manifest.json"
    output = tmp_path / "reports" / "first_version_readiness_checks.json"
    _write_acceptance_checks(acceptance)
    _write_app_smoke_checks(app_smoke)
    _write_pytest_report(pytest_report)
    _write_manifest(manifest)

    assert (
        readiness_main(
            [
                "--acceptance-checks",
                str(acceptance),
                "--app-smoke-checks",
                str(app_smoke),
                "--pytest-report",
                str(pytest_report),
                "--manifest",
                str(manifest),
                "--json",
                str(output),
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert "Wrote readiness checks:" in captured.out
    assert output.exists()
    rows = json.loads(output.read_text(encoding="utf-8"))
    assert all(row["status"] == "ok" for row in rows)
    assert any(row["item"] == "pytest report" for row in rows)


def test_readiness_cli_can_skip_pytest_report(tmp_path, capsys):
    acceptance = tmp_path / "reports" / "first_version_acceptance_checks.json"
    app_smoke = tmp_path / "reports" / "source_app_smoke_checks.json"
    manifest = tmp_path / "reports" / "release_artifact_manifest.json"
    output = tmp_path / "reports" / "first_version_readiness_checks.json"
    _write_acceptance_checks(acceptance)
    _write_app_smoke_checks(app_smoke)
    _write_manifest(manifest)

    assert (
        readiness_main(
            [
                "--acceptance-checks",
                str(acceptance),
                "--app-smoke-checks",
                str(app_smoke),
                "--manifest",
                str(manifest),
                "--skip-pytest-report",
                "--json",
                str(output),
            ]
        )
        == 0
    )

    rows = json.loads(output.read_text(encoding="utf-8"))
    assert not any(row["item"] == "pytest report" for row in rows)
    assert any("pytest=<not requested>" in row["detail"] for row in rows if row["item"] == "readiness inputs")
