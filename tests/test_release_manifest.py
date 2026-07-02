import hashlib
import json
from pathlib import Path

from gear_optimizer.release_manifest import (
    format_manifest_checks,
    main as release_manifest_main,
    manifest_checks_pass,
    verify_manifest,
)


def _write_manifest(tmp_path, exe_bytes: bytes = b"release") -> tuple:
    exe = tmp_path / "dist" / "gacha-gear-optimizer.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(exe_bytes)
    manifest = tmp_path / "reports" / "release_artifact_manifest.json"
    manifest.parent.mkdir(parents=True)
    relative_exe_path = Path("dist") / "gacha-gear-optimizer.exe"
    manifest.write_text(
        json.dumps(
            {
                "app": "gacha-gear-optimizer",
                "version": "0.1.0",
                "generated_at": "2026-07-01T07:29:55.0298782Z",
                "exe_path": str(exe),
                "relative_exe_path": str(relative_exe_path),
                "exe_size_bytes": len(exe_bytes),
                "exe_sha256": hashlib.sha256(exe_bytes).hexdigest(),
                "exe_last_write_time": "2026-07-01T07:29:51.3134423Z",
                "one_file": False,
                "preflight_skipped": True,
                "smoke_check_requested": True,
                "smoke_check_passed": True,
                "smoke_timeout_seconds": 45,
                "pyinstaller_args": [],
            },
        ),
        encoding="utf-8",
    )
    return manifest, exe


def _update_manifest(manifest, mutator):
    data = json.loads(manifest.read_text(encoding="utf-8"))
    mutator(data)
    manifest.write_text(json.dumps(data), encoding="utf-8")


def test_verify_manifest_passes_for_matching_exe(tmp_path):
    manifest, _exe = _write_manifest(tmp_path)

    rows = verify_manifest(manifest)

    assert manifest_checks_pass(rows)
    assert "exe sha256" in format_manifest_checks(rows)


def test_verify_manifest_resolves_relative_exe_path_from_project_root(tmp_path):
    manifest, _exe = _write_manifest(tmp_path)

    def remove_absolute_path(data):
        data.pop("exe_path")

    _update_manifest(manifest, remove_absolute_path)

    rows = verify_manifest(manifest)
    by_item = {row["item"]: row for row in rows}

    assert manifest_checks_pass(rows)
    assert by_item["exe file"]["status"] == "ok"


def test_verify_manifest_detects_metadata_errors(tmp_path):
    manifest, _exe = _write_manifest(tmp_path)

    def break_metadata(data):
        data["app"] = "wrong-app"
        data["version"] = "9.9.9"
        data["generated_at"] = "not-a-date"
        data["one_file"] = "false"
        data["smoke_check_passed"] = False
        data["smoke_timeout_seconds"] = 0
        data["pyinstaller_args"] = ["--log-level", 1]

    _update_manifest(manifest, break_metadata)

    rows = verify_manifest(manifest)
    by_item = {row["item"]: row for row in rows}

    assert not manifest_checks_pass(rows)
    assert by_item["manifest app"]["status"] == "error"
    assert by_item["manifest version"]["status"] == "error"
    assert by_item["generated at"]["status"] == "error"
    assert by_item["release flags"]["status"] == "error"
    assert by_item["smoke status"]["status"] == "error"
    assert by_item["smoke timeout"]["status"] == "error"
    assert by_item["pyinstaller args"]["status"] == "error"


def test_verify_manifest_detects_sha_mismatch(tmp_path):
    manifest, exe = _write_manifest(tmp_path)
    exe.write_bytes(b"changed bytes")

    rows = verify_manifest(manifest)
    by_item = {row["item"]: row for row in rows}

    assert not manifest_checks_pass(rows)
    assert by_item["exe size"]["status"] == "error"
    assert by_item["exe sha256"]["status"] == "error"


def test_verify_manifest_reports_missing_exe(tmp_path):
    manifest, exe = _write_manifest(tmp_path)
    exe.unlink()

    rows = verify_manifest(manifest)
    by_item = {row["item"]: row for row in rows}

    assert not manifest_checks_pass(rows)
    assert by_item["exe file"]["status"] == "missing"


def test_release_manifest_cli_returns_nonzero_for_bad_manifest(tmp_path, capsys):
    missing = tmp_path / "missing.json"

    assert release_manifest_main(["--manifest", str(missing)]) == 1

    output = capsys.readouterr().out
    assert "manifest" in output
    assert "missing" in output
