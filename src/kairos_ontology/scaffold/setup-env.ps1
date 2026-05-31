# Setup script for Kairos ontology hub development environment.
# Creates an isolated .venv and installs the toolkit + dev dependencies.
#
# Usage:
#   .\setup-env.ps1            # Create/refresh the virtual environment
#   .\setup-env.ps1 -Force     # Recreate from scratch (deletes existing .venv)

param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$venvDir = Join-Path $PSScriptRoot ".venv"

# --- Recreate if -Force ---
if ($Force -and (Test-Path $venvDir)) {
    Write-Host "Removing existing .venv ..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $venvDir
}

# --- Create venv ---
if (-not (Test-Path $venvDir)) {
    Write-Host "Creating virtual environment in .venv ..." -ForegroundColor Cyan
    py -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment" }
}

# --- Activate ---
$activateScript = Join-Path $venvDir "Scripts\Activate.ps1"
if (-not (Test-Path $activateScript)) {
    throw "Activate script not found at $activateScript"
}
& $activateScript

# --- Install dependencies ---
Write-Host "Installing dependencies ..." -ForegroundColor Cyan
pip install --upgrade pip --quiet
pip install -e ".[dev]" --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# --- Validate ---
Write-Host ""
$toolkitPath = py -c "import kairos_ontology; print(kairos_ontology.__file__)"
$toolkitVersion = py -c "from kairos_ontology import __version__; print(__version__)"
Write-Host "Toolkit version : $toolkitVersion" -ForegroundColor Green
Write-Host "Toolkit location: $toolkitPath" -ForegroundColor Green
Write-Host ""
Write-Host "Environment ready. Activate with:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor White
