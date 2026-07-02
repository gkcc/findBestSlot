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

function Get-LauncherArgValue {
    param(
        [string[]]$Args,
        [string]$Name,
        [string]$Default
    )

    $Value = $Default
    for ($Index = 0; $Index -lt $Args.Count; $Index++) {
        $Arg = $Args[$Index]
        if (($Arg -eq $Name) -and (($Index + 1) -lt $Args.Count)) {
            $Value = $Args[$Index + 1]
        } elseif ($Arg.StartsWith("$Name=")) {
            $Value = $Arg.Substring($Name.Length + 1)
        }
    }
    return $Value
}

$DisplayAddress = Get-LauncherArgValue -Args $LauncherArgs -Name "--server.address" -Default "127.0.0.1"
$DisplayPort = Get-LauncherArgValue -Args $LauncherArgs -Name "--server.port" -Default "8501"
$PageHost = $DisplayAddress
if ($PageHost -eq "0.0.0.0") {
    $PageHost = "127.0.0.1"
}

Write-Host "Starting gacha-gear-optimizer..."
Write-Host "Working directory: $Root"
Write-Host "Page URL: http://${PageHost}:$DisplayPort/"
Write-Host "Stop service: press Ctrl+C in this window."

& $Python.Source @PythonArgs -m gear_optimizer.launcher @LauncherArgs
