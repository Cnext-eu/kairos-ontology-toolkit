#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Fetch the ontology-reference-models folder from the remote reference repo.

.DESCRIPTION
    Performs a sparse shallow clone of the upstream repo into a temp directory,
    copies just the ontology-reference-models/ subfolder into this workspace,
    then discards the clone. No git submodule, no history, no git objects left
    behind in this repo.

.PARAMETER Ref
    The branch, tag, or SHA to fetch. Defaults to 'main'.

.EXAMPLE
    .\update-referencemodels.ps1
    # Fetches latest from main

.EXAMPLE
    .\update-referencemodels.ps1 -Ref v1.2.1
    # Fetches the v1.2.1 tag
#>

param(
    [string]$Ref = "main"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REMOTE_URL = "https://github.com/Cnext-eu/kairos-ontology-referencemodels.git"
$DEST       = Join-Path $PSScriptRoot "ontology-reference-models"
$REMOTE_DIR = "ontology-reference-models"    # subfolder inside the remote repo

function Write-Info    { Write-Host "  $args" -ForegroundColor Cyan }
function Write-Success { Write-Host "  $args" -ForegroundColor Green }
function Write-Err     { Write-Host "  $args" -ForegroundColor Red; exit 1 }

# ── Sparse shallow clone into a temp folder ───────────────────────────────────
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) "kairos-refmodels-$([System.IO.Path]::GetRandomFileName())"

try {
    Write-Info "Fetching ref '$Ref' from remote..."
    git clone --depth 1 --filter=blob:none --sparse --branch $Ref $REMOTE_URL $tmp --quiet 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Err "git clone failed" }

    git -C $tmp sparse-checkout set $REMOTE_DIR 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Err "git sparse-checkout failed" }

    $src = Join-Path $tmp $REMOTE_DIR
    if (-not (Test-Path $src)) { Write-Err "Expected folder '$REMOTE_DIR' not found in cloned repo" }

    # ── Copy into workspace, replacing previous content ───────────────────────
    if (Test-Path $DEST) {
        Remove-Item $DEST -Recurse -Force
    }
    Copy-Item $src $DEST -Recurse -Force

    # ── Report ─────────────────────────────────────────────────────────────────
    $sha = (git -C $tmp rev-parse HEAD).Trim()
    $version = $null
    $versionFile = Join-Path $DEST "VERSION"
    if (Test-Path $versionFile) { $version = (Get-Content $versionFile -Raw).Trim() }

    Write-Success "Done. ontology-reference-models/ is up to date."
    Write-Info   "  Ref     : $Ref"
    Write-Info   "  Commit  : $sha"
    if ($version) { Write-Info "  Version : $version" }

} finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
}
