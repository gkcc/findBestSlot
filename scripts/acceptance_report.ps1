param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AcceptanceArgs
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

$Output = Join-Path $Root "reports\first_version_acceptance.md"
$CheckJson = Join-Path $Root "reports\first_version_acceptance_checks.json"

Write-Host "Generating first-version acceptance report..."
Write-Host "Output file: $Output"
Write-Host "Check JSON: $CheckJson"

& $Python.Source @PythonArgs -m gear_optimizer.acceptance --output $Output --check --check-json $CheckJson @AcceptanceArgs
