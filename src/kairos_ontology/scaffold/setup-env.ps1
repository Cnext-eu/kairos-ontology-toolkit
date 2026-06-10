# Setup script for Kairos ontology hub development environment.
# Uses uv to create an isolated .venv and install the toolkit + dev dependencies.
# Also installs Node dev dependencies (Mermaid CLI) when package.json is present.
#
# Usage:
#   .\setup-env.ps1            # Create/sync the virtual environment
#   .\setup-env.ps1 -Force     # Recreate from scratch (deletes existing .venv)
#
# Requires: uv (https://docs.astral.sh/uv/)
#   Install: irm https://astral.sh/uv/install.ps1 | iex

param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# --- Check uv is installed ---
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: 'uv' is not installed." -ForegroundColor Red
    Write-Host ""
    Write-Host "Install uv with:" -ForegroundColor Yellow
    Write-Host "  irm https://astral.sh/uv/install.ps1 | iex" -ForegroundColor White
    Write-Host ""
    Write-Host "More info: https://docs.astral.sh/uv/getting-started/installation/" -ForegroundColor Gray
    exit 1
}

# --- Recreate if -Force ---
$venvDir = Join-Path $PSScriptRoot ".venv"
if ($Force -and (Test-Path $venvDir)) {
    Write-Host "Removing existing .venv ..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $venvDir
}

# --- Sync environment ---
Write-Host "Syncing environment with uv ..." -ForegroundColor Cyan
Push-Location $PSScriptRoot
try {
    uv sync
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
} finally {
    Pop-Location
}

# --- Install Node dependencies (optional, for Mermaid SVG rendering) ---
if (Test-Path (Join-Path $PSScriptRoot "package.json")) {
    Write-Host "Installing Node dependencies with npm (Mermaid CLI) ..." -ForegroundColor Cyan
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "package.json found but 'npm' is not installed. Install Node.js, then re-run setup-env.ps1."
    }
    Push-Location $PSScriptRoot
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    } finally {
        Pop-Location
    }
}

# --- Validate ---
Write-Host ""
$toolkitVersion = uv run python -c "from kairos_ontology import __version__; print(__version__)"
$toolkitPath = uv run python -c "import kairos_ontology; print(kairos_ontology.__file__)"
Write-Host "Toolkit version : $toolkitVersion" -ForegroundColor Green
Write-Host "Toolkit location: $toolkitPath" -ForegroundColor Green
Write-Host ""
Write-Host "Environment ready. Run commands with:" -ForegroundColor Cyan
Write-Host "  uv run kairos-ontology <command>" -ForegroundColor White
Write-Host ""
Write-Host "Or activate the venv manually:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor White
