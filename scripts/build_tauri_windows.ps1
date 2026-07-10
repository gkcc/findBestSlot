param(
    [switch]$SkipChecks,
    [switch]$SidecarsOnly,
    [switch]$NoBundle
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DesktopRoot = Join-Path $Root "desktop"
$BuildRoot = Join-Path $Root "build"
$SidecarDir = Join-Path $BuildRoot "tauri-sidecars"
$PyInstallerWork = Join-Path $BuildRoot "pyinstaller-tauri"
$SmokeRoot = Join-Path $BuildRoot "tauri-sidecar-smoke"

function Reset-WorkspaceDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    $ResolvedRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $ResolvedPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $ResolvedPath.StartsWith($ResolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to reset a directory outside the workspace: $ResolvedPath"
    }
    if (Test-Path -LiteralPath $ResolvedPath) {
        Remove-Item -LiteralPath $ResolvedPath -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $ResolvedPath | Out-Null
}

function Assert-CommandSucceeded {
    param([Parameter(Mandatory = $true)][string]$Label)

    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

$PythonArgs = @()
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
    $PythonArgs = @("-3")
}
if (-not $Python) {
    throw "python or py was not found. Install Python 3.11+ and run again."
}

& $Python.Source @PythonArgs -c "import PyInstaller" 2>$null
Assert-CommandSucceeded "PyInstaller availability check"

if (-not $SkipChecks) {
    & $Python.Source @PythonArgs -m pytest -q `
        (Join-Path $Root "tests\test_desktop_backend.py") `
        (Join-Path $Root "tests\test_desktop_protocol.py") `
        (Join-Path $Root "tests\test_desktop_jobs.py") `
        (Join-Path $Root "tests\test_desktop_service.py") `
        (Join-Path $Root "tests\test_tauri_packaging.py")
    Assert-CommandSucceeded "Desktop backend and packaging tests"
}

Reset-WorkspaceDirectory $SidecarDir
Reset-WorkspaceDirectory $PyInstallerWork

function Build-PythonSidecar {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$EntryPoint
    )

    $WorkPath = Join-Path $PyInstallerWork $Name
    $SpecPath = Join-Path $WorkPath "spec"
    New-Item -ItemType Directory -Force -Path $WorkPath, $SpecPath | Out-Null
    Write-Host "Building Python sidecar: $Name"
    & $Python.Source @PythonArgs -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --console `
        --name $Name `
        --paths (Join-Path $Root "src") `
        --distpath $SidecarDir `
        --workpath $WorkPath `
        --specpath $SpecPath `
        (Join-Path $Root $EntryPoint)
    Assert-CommandSucceeded "PyInstaller build for $Name"
}

Build-PythonSidecar `
    -Name "gear-optimizer-backend" `
    -EntryPoint "src\gear_optimizer\desktop_backend.py"
Build-PythonSidecar `
    -Name "gear-optimizer-action-worker" `
    -EntryPoint "src\gear_optimizer\action_ev_worker.py"

$BackendExe = Join-Path $SidecarDir "gear-optimizer-backend.exe"
$WorkerExe = Join-Path $SidecarDir "gear-optimizer-action-worker.exe"
if (-not (Test-Path -LiteralPath $BackendExe) -or -not (Test-Path -LiteralPath $WorkerExe)) {
    throw "Expected sidecar executables were not produced in $SidecarDir."
}

Write-Host "Running packaged sidecar smoke checks..."
& $BackendExe --schema | Out-Null
Assert-CommandSucceeded "Packaged desktop backend schema check"
& $WorkerExe --help | Out-Null
Assert-CommandSucceeded "Packaged Action EV worker import check"

Reset-WorkspaceDirectory $SmokeRoot
$RequestPath = Join-Path $SmokeRoot "workspace-request.json"
$ResponsePath = Join-Path $SmokeRoot "workspace-response.json"
@{
    schema_version = 1
    request_id = "tauri-package-smoke"
    method = "workspace.get"
    params = @{
        game_id = "zzz"
        agent_id = ""
    }
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $RequestPath -Encoding UTF8

$PreviousProjectRoot = $env:GEAR_OPTIMIZER_PROJECT_ROOT
$PreviousUserData = $env:GEAR_OPTIMIZER_USER_DATA_DIR
$PreviousWorker = $env:GEAR_OPTIMIZER_ACTION_WORKER
try {
    $env:GEAR_OPTIMIZER_PROJECT_ROOT = $Root
    $env:GEAR_OPTIMIZER_USER_DATA_DIR = Join-Path $SmokeRoot "user-data"
    $env:GEAR_OPTIMIZER_ACTION_WORKER = $WorkerExe
    & $BackendExe --request-file $RequestPath --response-file $ResponsePath
    Assert-CommandSucceeded "Packaged desktop backend workspace check"
    $StreamRequestText = Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 |
        ConvertFrom-Json |
        ConvertTo-Json -Depth 6 -Compress
    $StreamResponseText = $StreamRequestText | & $BackendExe
    Assert-CommandSucceeded "Packaged desktop backend NDJSON stream check"
    $StreamResponse = $StreamResponseText | ConvertFrom-Json
    if (-not $StreamResponse.ok -or -not $StreamResponse.data.workspace) {
        throw "Packaged desktop backend returned an invalid NDJSON workspace response."
    }
}
finally {
    $env:GEAR_OPTIMIZER_PROJECT_ROOT = $PreviousProjectRoot
    $env:GEAR_OPTIMIZER_USER_DATA_DIR = $PreviousUserData
    $env:GEAR_OPTIMIZER_ACTION_WORKER = $PreviousWorker
}
$SmokeResponse = Get-Content -LiteralPath $ResponsePath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $SmokeResponse.ok -or -not $SmokeResponse.data.workspace) {
    throw "Packaged desktop backend returned an invalid workspace response."
}

if ($SidecarsOnly) {
    Write-Host "Sidecars are ready: $SidecarDir"
    exit 0
}

$Node = Get-Command node -ErrorAction SilentlyContinue
if (-not $Node) {
    $ProgramFilesNode = Join-Path $env:ProgramFiles "nodejs\node.exe"
    if (Test-Path -LiteralPath $ProgramFilesNode) {
        $Node = Get-Item -LiteralPath $ProgramFilesNode
        $NodeDir = Split-Path -Parent $ProgramFilesNode
        $env:PATH = "$NodeDir;$env:PATH"
    }
}
if (-not $Node) {
    throw "node was not found. Install Node.js 20+ and run again."
}
$Pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if (-not $Pnpm) {
    $UserPnpm = Join-Path $env:APPDATA "npm\pnpm.cmd"
    if (Test-Path -LiteralPath $UserPnpm) {
        $Pnpm = Get-Item -LiteralPath $UserPnpm
        $PnpmDir = Split-Path -Parent $UserPnpm
        $env:PATH = "$PnpmDir;$env:PATH"
    }
}
if (-not $Pnpm) {
    throw "pnpm was not found. Install Node.js and pnpm 11.7.0, then run again."
}
$PnpmExecutable = if ($Pnpm.Source) { $Pnpm.Source } else { $Pnpm.FullName }
$Cargo = Get-Command cargo -ErrorAction SilentlyContinue
if (-not $Cargo) {
    $RustupCargo = Join-Path $env:USERPROFILE ".cargo\bin\cargo.exe"
    if (Test-Path -LiteralPath $RustupCargo) {
        $Cargo = Get-Item -LiteralPath $RustupCargo
        $CargoDir = Split-Path -Parent $RustupCargo
        $env:PATH = "$CargoDir;$env:PATH"
    }
}
if (-not $Cargo) {
    throw "cargo was not found. Install the Rust toolchain, then run again."
}

Push-Location $DesktopRoot
try {
    & $PnpmExecutable install --frozen-lockfile
    Assert-CommandSucceeded "pnpm install"
    if (-not $SkipChecks) {
        & $PnpmExecutable test
        Assert-CommandSucceeded "Tauri frontend tests"
    }
    $TauriArgs = @(
        "tauri",
        "build",
        "--config",
        "src-tauri/tauri.bundle.conf.json"
    )
    if ($NoBundle) {
        $TauriArgs += "--no-bundle"
    }
    & $PnpmExecutable @TauriArgs
    Assert-CommandSucceeded "Tauri desktop build"
}
finally {
    Pop-Location
}

if ($NoBundle) {
    Write-Host "Tauri executable build completed without an installer bundle."
} else {
    Write-Host "Tauri NSIS bundle completed. PySide6 remains the default release until parity gates pass."
}
