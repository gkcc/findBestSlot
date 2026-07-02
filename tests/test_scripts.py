from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"


def _read(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def test_cmd_wrappers_forward_cli_arguments_to_powershell_scripts():
    for name in [
        "start_desktop.cmd",
        "acceptance_report.cmd",
        "build_windows_app.cmd",
        "release_gate.cmd",
    ]:
        assert "%*" in _read(name)


def test_powershell_entrypoints_forward_remaining_arguments_to_python():
    start_desktop = _read("start_desktop.ps1")
    acceptance = _read("acceptance_report.ps1")
    release_gate = _read("release_gate.ps1")

    assert "ValueFromRemainingArguments" in start_desktop
    assert "@LauncherArgs" in start_desktop
    assert "ValueFromRemainingArguments" in acceptance
    assert "@AcceptanceArgs" in acceptance
    assert "--check-json $CheckJson" in acceptance
    assert "ValueFromRemainingArguments" in release_gate
    assert "@PytestArgs" in release_gate


def test_build_windows_app_runs_preflight_before_pyinstaller():
    build = _read("build_windows_app.ps1")

    assert "[switch]$SkipPreflight" in build
    assert "[switch]$RunPytest" in build
    assert "Running build preflight checks" in build
    assert "-m gear_optimizer.diagnostics" in build
    assert "-m gear_optimizer.acceptance" in build
    assert "--check-json $AcceptanceChecks" in build
    assert 'Join-Path $Root "reports\\source_app_smoke_checks.json"' in build
    assert 'Join-Path $Root "reports\\pytest.xml"' in build
    assert "if ($SmokeCheck)" in build
    assert "$DesktopApp = Join-Path $Root \"desktop_app.py\"" in build
    assert "& $Python.Source @PythonArgs $DesktopApp --app-check --app-check-json $AppSmokeChecks" in build
    assert 'Write-Error "Preflight app smoke failed."' in build
    assert "Skipping source app smoke. Run with -SmokeCheck when you want it." in build
    assert "if ($RunPytest)" in build
    assert "-m pytest --junitxml $PytestReport" in build
    assert 'Write-Error "Preflight pytest failed."' in build
    assert "$PytestEvidenceAvailable = $true" in build
    assert "Skipping build preflight checks" in build
    assert "Ignoring -RunPytest because -SkipPreflight was provided" in build


def test_build_windows_app_can_smoke_check_and_verify_packaged_exe():
    build = _read("build_windows_app.ps1")

    assert "[switch]$SmokeCheck" in build
    assert "[ValidateRange(1, 600)]" in build
    assert "[int]$SmokeTimeoutSeconds = 45" in build
    assert "function Get-FreeLoopbackPort" not in build
    assert "function Test-PackagedStreamlitServer" not in build
    assert "function Invoke-PackagedExeCheck" in build
    assert "function Write-ReleaseManifest" in build
    assert "function Get-ProjectVersion" in build
    assert 'Write-Error "PyInstaller build failed."' in build
    assert 'Join-Path $Root "dist\\gacha-gear-optimizer.exe"' in build
    assert 'Join-Path $Root "dist\\gacha-gear-optimizer\\gacha-gear-optimizer.exe"' in build
    assert 'Write-Error "Expected build output was not found: $ExePath"' in build
    assert "Running packaged native PySide6 app smoke check" in build
    assert '-Name "Packaged PySide6 runtime check"' in build
    assert '-Arguments @("--check")' in build
    assert '-Name "Packaged native app import check"' in build
    assert '-Arguments @("--app-check")' in build
    assert '-ErrorPatterns @("PySide6 app\\s+error", "Traceback")' in build
    assert "--serve-streamlit" not in build
    assert "Invoke-WebRequest -Uri $Url" not in build
    assert 'Join-Path $Root "reports\\release_artifact_manifest.json"' in build
    assert 'Join-Path $Root "reports\\first_version_readiness_checks.json"' in build
    assert "exe_size_bytes" in build
    assert "exe_sha256" in build
    assert "function Get-Sha256Hex" in build
    assert "Get-Command Get-FileHash -ErrorAction SilentlyContinue" in build
    assert "Get-Sha256Hex $ExeItem.FullName" in build
    assert "smoke_check_passed" in build
    assert "smoke_timeout_seconds" in build
    assert "pyinstaller_args" in build
    assert "$ExtraPyInstallerArgs = @()" in build
    assert "pyinstaller_args = $ExtraPyInstallerArgs" in build
    assert "Wrote release artifact manifest" in build
    assert "$ReleaseManifest = Join-Path $Root \"reports\\release_artifact_manifest.json\"" in build
    assert "Verifying release artifact manifest" in build
    assert "-m gear_optimizer.release_manifest --manifest $ReleaseManifest" in build
    assert 'Write-Error "Release artifact manifest verification failed."' in build
    assert "Verifying first-version readiness" in build
    assert '"--pytest-report", $PytestReport' in build
    assert '"--skip-pytest-report"' in build
    assert "& $Python.Source @PythonArgs @ReadinessArgs" in build
    assert 'Write-Error "First-version readiness verification failed."' in build
    assert "Skipping first-version readiness because preflight evidence is missing" in build


def test_release_gate_runs_doctor_acceptance_pytest_and_optional_package_smoke():
    release_gate = _read("release_gate.ps1")

    assert "[switch]$BuildPackage" in release_gate
    assert "[switch]$OneFile" in release_gate
    assert "[switch]$SkipPytest" in release_gate
    assert "[switch]$SmokeCheck" in release_gate
    assert "[switch]$VerifyManifest" in release_gate
    assert "[int]$SmokeTimeoutSeconds = 45" in release_gate
    assert "function Invoke-GateStep" in release_gate
    assert "-m gear_optimizer.diagnostics" in release_gate
    assert "-m gear_optimizer.acceptance" in release_gate
    assert "--check-json $AcceptanceChecks" in release_gate
    assert 'Join-Path $Root "reports\\source_app_smoke_checks.json"' in release_gate
    assert 'Join-Path $Root "reports\\pytest.xml"' in release_gate
    assert 'Invoke-GateStep "native app smoke"' in release_gate
    assert "Skipping smoke check. Run with -SmokeCheck when you want it." in release_gate
    assert "$DesktopApp = Join-Path $Root \"desktop_app.py\"" in release_gate
    assert "& $Python.Source @PythonArgs $DesktopApp --app-check --app-check-json $AppSmokeChecks" in release_gate
    assert "-m pytest @PytestArgs" in release_gate
    assert "--junitxml $PytestReport" in release_gate
    assert '"Skipping pytest."' in release_gate
    assert '$BuildArgs = @("-SkipPreflight", "-SmokeTimeoutSeconds", $SmokeTimeoutSeconds)' in release_gate
    assert '$BuildArgs += "-SmokeCheck"' in release_gate
    assert '$BuildArgs += "-OneFile"' in release_gate
    assert "& $BuildScript @BuildArgs" in release_gate
    assert 'Join-Path $Root "reports\\release_artifact_manifest.json"' in release_gate
    assert 'Join-Path $Root "reports\\first_version_readiness_checks.json"' in release_gate
    assert "$BuildPackage -or $VerifyManifest" in release_gate
    assert "-m gear_optimizer.release_manifest --manifest $ReleaseManifest" in release_gate
    assert '"--pytest-report", $PytestReport' in release_gate
    assert '"--skip-pytest-report"' in release_gate
    assert "& $Python.Source @PythonArgs @ReadinessArgs" in release_gate
    assert "Skipping readiness because smoke evidence was not requested." in release_gate
    assert "build_windows_app.ps1" in release_gate
    assert "Release gate passed." in release_gate


def test_powershell_scripts_use_ascii_text_for_windows_powershell_parser():
    for name in [
        "start_desktop.ps1",
        "acceptance_report.ps1",
        "build_windows_app.ps1",
        "release_gate.ps1",
    ]:
        text = _read(name)
        assert text.isascii()


def test_powershell_entrypoints_force_utf8_python_output():
    for name in [
        "start_desktop.ps1",
        "acceptance_report.ps1",
        "build_windows_app.ps1",
        "release_gate.ps1",
    ]:
        text = _read(name)
        assert "[Console]::OutputEncoding = $Utf8NoBom" in text
        assert "$OutputEncoding = $Utf8NoBom" in text
        assert '$env:PYTHONIOENCODING = "utf-8"' in text
