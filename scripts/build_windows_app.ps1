param(
    [switch]$OneFile,
    [switch]$SkipPreflight,
    [switch]$SmokeCheck,
    [switch]$RunPytest,
    [ValidateRange(1, 600)]
    [int]$SmokeTimeoutSeconds = 45,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PyInstallerArgs
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$env:PYTHONPATH = "$Root\src;$env:PYTHONPATH"
$env:PYTHONIOENCODING = "utf-8"
$AcceptanceOutput = Join-Path $Root "reports\acceptance_report.md"
$AcceptanceChecks = Join-Path $Root "reports\acceptance_checks.json"
$AppSmokeChecks = Join-Path $Root "reports\source_app_smoke_checks.json"
$PytestReport = Join-Path $Root "reports\pytest.xml"
$ReleaseManifest = Join-Path $Root "reports\release_artifact_manifest.json"
$ReadinessChecks = Join-Path $Root "reports\readiness_checks.json"
$PytestEvidenceAvailable = $false

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

function Invoke-PackagedExeCheck {
    param(
        [string]$ExePath,
        [string]$Name,
        [string[]]$Arguments,
        [string]$OutLog,
        [string]$ErrLog,
        [string[]]$ErrorPatterns = @()
    )

    Remove-Item $OutLog, $ErrLog -ErrorAction SilentlyContinue
    $Process = Start-Process `
        -FilePath $ExePath `
        -ArgumentList $Arguments `
        -Wait `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog

    $OutputText = ""
    $ErrorText = ""
    if (Test-Path $OutLog) {
        $OutputText = Get-Content $OutLog -Raw -ErrorAction SilentlyContinue
    }
    if (Test-Path $ErrLog) {
        $ErrorText = Get-Content $ErrLog -Raw -ErrorAction SilentlyContinue
    }

    $MatchedPattern = $null
    foreach ($Pattern in $ErrorPatterns) {
        if (($OutputText -match $Pattern) -or ($ErrorText -match $Pattern)) {
            $MatchedPattern = $Pattern
            break
        }
    }
    if (($Process.ExitCode -ne 0) -or $MatchedPattern) {
        if ($OutputText) {
            Write-Host $OutputText
        }
        if ($ErrorText) {
            Write-Host $ErrorText
        }
        if ($MatchedPattern) {
            Write-Host "$Name matched failure pattern: $MatchedPattern"
        }
        $FailureExitCode = $Process.ExitCode
        if (($null -eq $FailureExitCode) -or ($FailureExitCode -eq 0)) {
            $FailureExitCode = 1
        }
        Write-Error "$Name failed."
        exit $FailureExitCode
    }
    if ($OutputText) {
        Write-Host $OutputText
    }
    if ($ErrorText) {
        Write-Host "$Name stderr log: $ErrLog"
    }
}

function Get-ProjectVersion {
    $Pyproject = Join-Path $Root "pyproject.toml"
    foreach ($Line in Get-Content $Pyproject -ErrorAction Stop) {
        if ($Line -match '^version\s*=\s*"([^"]+)"') {
            return $Matches[1]
        }
    }
    return "unknown"
}

function Get-Sha256Hex {
    param([string]$Path)

    $GetFileHashCommand = Get-Command Get-FileHash -ErrorAction SilentlyContinue
    if ($GetFileHashCommand) {
        return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }

    $Stream = [System.IO.File]::OpenRead($Path)
    try {
        $Sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            return (($Sha256.ComputeHash($Stream) | ForEach-Object { $_.ToString("x2") }) -join "")
        }
        finally {
            $Sha256.Dispose()
        }
    }
    finally {
        $Stream.Dispose()
    }
}

function Write-ReleaseManifest {
    param(
        [string]$ExePath,
        [bool]$OneFileBuild,
        [bool]$SkippedPreflight,
        [bool]$SmokeRequested,
        [object]$SmokePassed,
        [int]$SmokeTimeoutSeconds
    )

    New-Item -ItemType Directory -Force -Path (Split-Path $ReleaseManifest) | Out-Null
    $ExeItem = Get-Item $ExePath
    $ExtraPyInstallerArgs = @()
    if ($PyInstallerArgs) {
        $ExtraPyInstallerArgs = @($PyInstallerArgs)
    }
    $Manifest = [ordered]@{
        app = "gacha-gear-optimizer"
        version = Get-ProjectVersion
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        exe_path = $ExeItem.FullName
        relative_exe_path = Resolve-Path -Path $ExeItem.FullName -Relative
        exe_size_bytes = $ExeItem.Length
        exe_sha256 = Get-Sha256Hex $ExeItem.FullName
        exe_last_write_time = $ExeItem.LastWriteTimeUtc.ToString("o")
        one_file = [bool]$OneFileBuild
        preflight_skipped = [bool]$SkippedPreflight
        smoke_check_requested = [bool]$SmokeRequested
        smoke_check_passed = $SmokePassed
        smoke_timeout_seconds = $SmokeTimeoutSeconds
        pyinstaller_args = $ExtraPyInstallerArgs
    }
    $Manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $ReleaseManifest -Encoding UTF8
    Write-Host "Wrote release artifact manifest: $ReleaseManifest"
}

if (-not $SkipPreflight) {
    Write-Host "Running build preflight checks..."
    & $Python.Source @PythonArgs -m gear_optimizer.diagnostics
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Preflight diagnostics failed."
        exit $LASTEXITCODE
    }

    & $Python.Source @PythonArgs -m gear_optimizer.acceptance --output $AcceptanceOutput --check --check-json $AcceptanceChecks
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Preflight acceptance checks failed."
        exit $LASTEXITCODE
    }

    if ($SmokeCheck) {
        $DesktopApp = Join-Path $Root "desktop_app.py"
        & $Python.Source @PythonArgs $DesktopApp --app-check --app-check-json $AppSmokeChecks
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Preflight app smoke failed."
            exit $LASTEXITCODE
        }
    } else {
        Write-Host "Skipping source app smoke. Run with -SmokeCheck when you want it."
    }

    if ($RunPytest) {
        Remove-Item $PytestReport -ErrorAction SilentlyContinue
        & $Python.Source @PythonArgs -m pytest --junitxml $PytestReport
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Preflight pytest failed."
            exit $LASTEXITCODE
        }
        $PytestEvidenceAvailable = $true
    }
} else {
    Write-Host "Skipping build preflight checks."
    if ($RunPytest) {
        Write-Warning "Ignoring -RunPytest because -SkipPreflight was provided."
    }
}

& $Python.Source @PythonArgs -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error 'PyInstaller is not installed. Run: pip install -e ".[packaging]"'
    exit 1
}

$BuildArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "gacha-gear-optimizer",
    "--paths", "$Root\src",
    "--add-data", "$Root\src\gear_optimizer;src\gear_optimizer",
    "--add-data", "$Root\configs;configs",
    "--add-data", "$Root\examples;examples",
    "--add-data", "$Root\assets;assets",
    "--collect-all", "PySide6",
    "$Root\desktop_app.py"
)

if ($OneFile) {
    $BuildArgs = @("-m", "PyInstaller", "--onefile") + $BuildArgs[2..($BuildArgs.Count - 1)]
}

if ($PyInstallerArgs) {
    $BuildArgs += $PyInstallerArgs
}

Write-Host "Building gacha-gear-optimizer Windows app..."
Write-Host 'Default output: dist\gacha-gear-optimizer\gacha-gear-optimizer.exe'
Write-Host 'With -OneFile: dist\gacha-gear-optimizer.exe'
& $Python.Source @PythonArgs @BuildArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed."
    exit $LASTEXITCODE
}

if ($OneFile) {
    $ExePath = Join-Path $Root "dist\gacha-gear-optimizer.exe"
} else {
    $ExePath = Join-Path $Root "dist\gacha-gear-optimizer\gacha-gear-optimizer.exe"
}

if (-not (Test-Path $ExePath)) {
    Write-Error "Expected build output was not found: $ExePath"
    exit 1
}

if ($SmokeCheck) {
    Write-Host "Running packaged native PySide6 app smoke check..."
    Invoke-PackagedExeCheck `
        -ExePath $ExePath `
        -Name "Packaged PySide6 runtime check" `
        -Arguments @("--check") `
        -OutLog (Join-Path $Root "reports\packaged-check.out.log") `
        -ErrLog (Join-Path $Root "reports\packaged-check.err.log")
    Invoke-PackagedExeCheck `
        -ExePath $ExePath `
        -Name "Packaged native app import check" `
        -Arguments @("--app-check") `
        -OutLog (Join-Path $Root "reports\packaged-app-check.out.log") `
        -ErrLog (Join-Path $Root "reports\packaged-app-check.err.log") `
        -ErrorPatterns @("PySide6 app\s+error", "Traceback")
    $SmokeCheckPassed = $true
} else {
    $SmokeCheckPassed = $null
}

Write-ReleaseManifest `
    -ExePath $ExePath `
    -OneFileBuild ([bool]$OneFile) `
    -SkippedPreflight ([bool]$SkipPreflight) `
    -SmokeRequested ([bool]$SmokeCheck) `
    -SmokePassed $SmokeCheckPassed `
    -SmokeTimeoutSeconds $SmokeTimeoutSeconds

Write-Host "Verifying release artifact manifest..."
& $Python.Source @PythonArgs -m gear_optimizer.release_manifest --manifest $ReleaseManifest
if ($LASTEXITCODE -ne 0) {
    Write-Error "Release artifact manifest verification failed."
    exit $LASTEXITCODE
}

if ($SmokeCheck) {
    if ((Test-Path $AcceptanceChecks) -and (Test-Path $AppSmokeChecks)) {
        Write-Host "Verifying release readiness..."
        $ReadinessArgs = @(
            "-m", "gear_optimizer.readiness",
            "--acceptance-checks", $AcceptanceChecks,
            "--app-smoke-checks", $AppSmokeChecks,
            "--manifest", $ReleaseManifest,
            "--json", $ReadinessChecks
        )
        if ($PytestEvidenceAvailable) {
            $ReadinessArgs += @("--pytest-report", $PytestReport)
        } else {
            $ReadinessArgs += @("--skip-pytest-report")
        }
        & $Python.Source @PythonArgs @ReadinessArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Release readiness verification failed."
            exit $LASTEXITCODE
        }
    } else {
        Write-Warning "Skipping release readiness because preflight evidence is missing. Run without -SkipPreflight or use release_gate.ps1."
    }
}
