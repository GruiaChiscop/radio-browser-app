<#
.SYNOPSIS
    Build radio_browser.exe with Nuitka (produces a compiled, hard-to-reverse binary).

.DESCRIPTION
    Nuitka translates Python to C and compiles it to a native executable.
    This is significantly harder to reverse-engineer than PyInstaller bundles
    (no embedded .pyc files, no simple unpacking tools like pyinstxtractor).

    --onefile   packs everything into a single self-contained .exe
    --standalone alternative: produces a dist/ folder (faster cold start)

.EXAMPLE
    .\build.ps1              # onefile mode (default)
    .\build.ps1 -Standalone  # folder mode
    .\build.ps1 -Debug       # leave console window open for debugging

.REQUIREMENTS
    pip install nuitka zstandard ordered-set
    pip install -r requirements.txt
#>

param(
    [switch]$Standalone,
    [switch]$Debug
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "=== Radio Browser — Nuitka build ===" -ForegroundColor Cyan

# Verify Nuitka is installed
if (-not (python -c "import nuitka" 2>$null; $?)) {
    Write-Host "Installing Nuitka and required build helpers..." -ForegroundColor Yellow
    pip install nuitka zstandard ordered-set
}

$outDir = Join-Path $root "build"
if (Test-Path $outDir) { Remove-Item $outDir -Recurse -Force }
New-Item -ItemType Directory -Path $outDir | Out-Null

$baseArgs = @(
    "-m", "nuitka",
    "--enable-plugin=wx",
    "--include-package=accessible_output2",
    "--include-package=sound_lib",
    "--include-package=libloader",
    "--include-package=platform_utils",
    "--include-package=platformdirs",
    "--output-dir=$outDir",
    "--output-filename=radio_browser.exe"
)

if (-not $Debug) {
    $baseArgs += "--windows-disable-console"
}

if ($Standalone) {
    $baseArgs += "--standalone"
    $baseArgs += "--remove-output"
    Write-Host "Mode: standalone (folder)" -ForegroundColor Yellow
} else {
    $baseArgs += "--onefile"
    Write-Host "Mode: onefile (single exe)" -ForegroundColor Yellow
}

$baseArgs += (Join-Path $root "src\radio_browser.py")

Write-Host "Running: python $($baseArgs -join ' ')" -ForegroundColor Gray
python @baseArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build FAILED." -ForegroundColor Red
    exit $LASTEXITCODE
}

$exePath = Join-Path $outDir "radio_browser.exe"
if (Test-Path $exePath) {
    $sizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 2)
    $hash = (Get-FileHash $exePath -Algorithm SHA256).Hash.ToLower()
    Write-Host ""
    Write-Host "Build successful!" -ForegroundColor Green
    Write-Host "  Output : $exePath"
    Write-Host "  Size   : $sizeMB MB"
    Write-Host "  SHA256 : $hash"
} else {
    Write-Host "Build output not found at expected path." -ForegroundColor Red
    exit 1
}
