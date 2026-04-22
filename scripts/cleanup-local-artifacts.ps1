$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    throw "Uruchom ten skrypt w PowerShell jako administrator, aby wyczyscic zablokowane cache i katalogi tymczasowe."
}

$targets = @(
    (Join-Path $root ".scratch_pytest"),
    (Join-Path $root ".tmp"),
    (Join-Path $root ".tmp_test_runs"),
    (Join-Path $root ".tmp_test_models"),
    (Join-Path $root "__pycache__")
)

$targets += Get-ChildItem -LiteralPath $root -Directory -Force |
    Where-Object { $_.Name -like "pytest-cache-files-*" } |
    ForEach-Object { $_.FullName }

foreach ($subdir in @("Code", "tests")) {
    $path = Join-Path $root $subdir
    if (-not (Test-Path -LiteralPath $path)) {
        continue
    }

    $targets += Get-ChildItem -LiteralPath $path -Recurse -Directory -Filter "__pycache__" -Force -ErrorAction SilentlyContinue |
        ForEach-Object { $_.FullName }
}

$resolved = $targets |
    Sort-Object -Unique |
    Where-Object { Test-Path -LiteralPath $_ }

foreach ($path in $resolved) {
    if (-not $path.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe target outside workspace: $path"
    }
}

foreach ($path in $resolved) {
    Write-Host "Cleaning $path"
    & takeown.exe /F $path /A /R /D Y | Out-Null
    & icacls.exe $path /grant "*S-1-5-32-544:(OI)(CI)F" /T /C | Out-Null
    Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
}

Write-Host ""
Write-Host "Cleanup complete."
