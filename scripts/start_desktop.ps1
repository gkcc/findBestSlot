param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$LauncherArgs
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

if ($LauncherArgs -contains "--check") {
    Write-Host "Checking gacha-gear-optimizer desktop runtime..."
} else {
    Write-Host "Starting gacha-gear-optimizer desktop window..."
}
Write-Host 'If pywebview is missing, Edge/Chrome app-window fallback will be used.'
Write-Host 'Install full desktop support with: pip install -e ".[desktop]"'
Write-Host "Check desktop support: .\scripts\start_desktop.ps1 --check"
if (-not ($LauncherArgs -contains "--check")) {
    Write-Host "Stop service: close the desktop/app window. If only the default browser opens, press Ctrl+C here."
}

& $Python.Source @PythonArgs -m gear_optimizer.launcher --desktop @LauncherArgs
