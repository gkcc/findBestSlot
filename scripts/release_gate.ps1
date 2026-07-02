param(
    [switch]$BuildPackage,
    [switch]$OneFile,
    [switch]$SkipPytest,
    [switch]$SmokeCheck,
    [switch]$VerifyManifest,
    [ValidateRange(1, 600)]
    [int]$SmokeTimeoutSeconds = 45,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$env:PYTHONPATH = "$Root\src;$env:PYTHONPATH"
$env:PYTHONIOENCODING = "utf-8"

$PythonArgs = @()
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
    $PythonArgs = @("-3")
}

if (-not $Python) {
    Write-Error "python or py was not found. Install Python 3.11+ and run again."
    exit 1
}

function Invoke-GateStep {
    param(
        [string]$Name,
        [scriptblock]$Step
    )

    Write-Host ""
    Write-Host "== $Name =="
    & $Step
    if ($LASTEXITCODE -ne 0) {
        Write-Error "$Name failed."
        exit $LASTEXITCODE
    }
}

$AcceptanceOutput = Join-Path $Root "reports\acceptance_report.md"
$AcceptanceChecks = Join-Path $Root "reports\acceptance_checks.json"
$AppSmokeChecks = Join-Path $Root "reports\source_app_smoke_checks.json"
$PytestReport = Join-Path $Root "reports\pytest.xml"
$ReleaseManifest = Join-Path $Root "reports\release_artifact_manifest.json"
$ReadinessChecks = Join-Path $Root "reports\readiness_checks.json"

Invoke-GateStep "doctor" {
    & $Python.Source @PythonArgs -m gear_optimizer.diagnostics
}

Invoke-GateStep "acceptance" {
    & $Python.Source @PythonArgs -m gear_optimizer.acceptance --output $AcceptanceOutput --check --check-json $AcceptanceChecks
}

if ($SmokeCheck) {
    Invoke-GateStep "native app smoke" {
        $DesktopApp = Join-Path $Root "desktop_app.py"
        & $Python.Source @PythonArgs $DesktopApp --app-check --app-check-json $AppSmokeChecks
    }
} else {
    Write-Host ""
    Write-Host "== native app smoke =="
    Write-Host "Skipping smoke check. Run with -SmokeCheck when you want it."
}

if ($SkipPytest) {
    Write-Host ""
    Write-Host "== pytest =="
    Write-Host "Skipping pytest."
} else {
    Invoke-GateStep "pytest" {
        Remove-Item $PytestReport -ErrorAction SilentlyContinue
        & $Python.Source @PythonArgs -m pytest @PytestArgs --junitxml $PytestReport
    }
}

if ($BuildPackage) {
    Invoke-GateStep "package build" {
        $BuildScript = Join-Path $PSScriptRoot "build_windows_app.ps1"
        $BuildArgs = @("-SkipPreflight", "-SmokeTimeoutSeconds", $SmokeTimeoutSeconds)
        if ($SmokeCheck) {
            $BuildArgs += "-SmokeCheck"
        }
        if ($OneFile) {
            $BuildArgs += "-OneFile"
        }
        & $BuildScript @BuildArgs
    }
}

if ($BuildPackage -or $VerifyManifest) {
    Invoke-GateStep "release manifest" {
        & $Python.Source @PythonArgs -m gear_optimizer.release_manifest --manifest $ReleaseManifest
    }

    if ($SmokeCheck) {
        Invoke-GateStep "release readiness" {
            $ReadinessArgs = @(
                "-m", "gear_optimizer.readiness",
                "--acceptance-checks", $AcceptanceChecks,
                "--app-smoke-checks", $AppSmokeChecks,
                "--manifest", $ReleaseManifest,
                "--json", $ReadinessChecks
            )
            if (-not $SkipPytest) {
                $ReadinessArgs += @("--pytest-report", $PytestReport)
            } else {
                $ReadinessArgs += @("--skip-pytest-report")
            }
            & $Python.Source @PythonArgs @ReadinessArgs
        }
    } else {
        Write-Host ""
        Write-Host "== release readiness =="
        Write-Host "Skipping readiness because smoke evidence was not requested."
    }
}

Write-Host ""
Write-Host "Release gate passed."
