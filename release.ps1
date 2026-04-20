#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Create and publish a new release of kairos-ontology-toolkit

.DESCRIPTION
    This script automates the release process:
    - Prompts for release type (major/minor/patch)
    - Updates version in pyproject.toml and __init__.py
    - Updates poetry.lock
    - Builds the package
    - Commits changes
    - Creates and pushes git tag
    - Rebuilds package with new version

.EXAMPLE
    .\release.ps1
#>

# Exit on error
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Kairos Ontology Toolkit - Release" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check for uncommitted changes
$gitStatus = git status --porcelain
if ($gitStatus) {
    Write-Host "❌ Error: You have uncommitted changes. Please commit or stash them first." -ForegroundColor Red
    git status --short
    exit 1
}

# Get current version from pyproject.toml
$pyprojectContent = Get-Content "pyproject.toml" -Raw
if ($pyprojectContent -match 'version\s*=\s*"([0-9]+)\.([0-9]+)\.([0-9]+)"') {
    $major = [int]$matches[1]
    $minor = [int]$matches[2]
    $patch = [int]$matches[3]
} else {
    Write-Host "❌ Error: Could not parse version from pyproject.toml" -ForegroundColor Red
    exit 1
}

$currentVersion = "$major.$minor.$patch"
Write-Host "📦 Current version: $currentVersion" -ForegroundColor Yellow
Write-Host ""

# Prompt for release type
Write-Host "Select release type:" -ForegroundColor Cyan
$patchTarget = "$major.$minor.$($patch + 1)"
$minorTarget = "$major.$($minor + 1).0"
$majorTarget = "$($major + 1).0.0"
Write-Host "  [1] Patch `(bug fixes`)         $currentVersion -> $patchTarget" -ForegroundColor White
Write-Host "  [2] Minor `(new features`)      $currentVersion -> $minorTarget" -ForegroundColor White
Write-Host "  [3] Major `(breaking changes`)  $currentVersion -> $majorTarget" -ForegroundColor White
Write-Host ""

do {
    $choice = Read-Host "Enter choice `(1-3`)"
} while ($choice -notmatch '^[1-3]$')

# Calculate new version
switch ($choice) {
    "1" {
        $newMajor = $major
        $newMinor = $minor
        $newPatch = $patch + 1
        $releaseType = "Patch"
    }
    "2" {
        $newMajor = $major
        $newMinor = $minor + 1
        $newPatch = 0
        $releaseType = "Minor"
    }
    "3" {
        $newMajor = $major + 1
        $newMinor = 0
        $newPatch = 0
        $releaseType = "Major"
    }
}

$newVersion = "$newMajor.$newMinor.$newPatch"
Write-Host ""
Write-Host "🚀 Preparing $releaseType release: $currentVersion -> $newVersion" -ForegroundColor Green
Write-Host ""

# Confirm
$confirm = Read-Host "Continue? `(y/n`)"
if ($confirm -ne 'y') {
    Write-Host "❌ Release cancelled" -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "📝 Updating version numbers..." -ForegroundColor Cyan

# Update pyproject.toml
$pyprojectContent = $pyprojectContent -replace 'version\s*=\s*"[0-9]+\.[0-9]+\.[0-9]+"', "version = `"$newVersion`""
Set-Content "pyproject.toml" -Value $pyprojectContent -NoNewline

# Update __init__.py
$initPath = "src\kairos_ontology\__init__.py"
$initContent = Get-Content $initPath -Raw
$initContent = $initContent -replace '__version__\s*=\s*"[0-9]+\.[0-9]+\.[0-9]+"', "__version__ = `"$newVersion`""
Set-Content $initPath -Value $initContent -NoNewline

Write-Host "  ✓ Updated pyproject.toml" -ForegroundColor Green
Write-Host "  ✓ Updated __init__.py" -ForegroundColor Green

# Resolve poetry executable — prefer a local .venv, fall back to PATH
function Invoke-Poetry {
    param([string[]]$Arguments)
    $venvPython = Join-Path $PSScriptRoot ".venv" "Scripts" "python.exe"
    if (Test-Path $venvPython) {
        & $venvPython -m poetry @Arguments
    } elseif (Get-Command poetry -ErrorAction SilentlyContinue) {
        poetry @Arguments
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        py -m poetry @Arguments
    } else {
        python -m poetry @Arguments
    }
    if ($LASTEXITCODE -ne 0) { throw "poetry $($Arguments -join ' ') failed (exit $LASTEXITCODE)" }
}

# Update poetry lock
Write-Host ""
Write-Host "🔒 Updating poetry.lock..." -ForegroundColor Cyan
Invoke-Poetry "lock"
Write-Host "  ✓ Lock file updated" -ForegroundColor Green

# Build package
Write-Host ""
Write-Host "🏗️  Building package..." -ForegroundColor Cyan
Invoke-Poetry "build"
Write-Host "  ✓ Package built" -ForegroundColor Green

# Get release notes (single line)
Write-Host ""
$releaseNote = Read-Host "Enter release notes `(one line`)"

if ([string]::IsNullOrWhiteSpace($releaseNote)) {
    $releaseNote = "Release v$newVersion"
}

$commitMessage = "Release v$newVersion"
$tagMessage = "Release v$newVersion - $releaseType release`n`n$releaseNote"

# Commit changes
Write-Host ""
Write-Host "💾 Committing changes..." -ForegroundColor Cyan
git add pyproject.toml poetry.lock src/kairos_ontology/__init__.py
git commit -m $commitMessage
Write-Host "  ✓ Changes committed" -ForegroundColor Green

# Create tag
Write-Host ""
Write-Host "🏷️  Creating tag v$newVersion..." -ForegroundColor Cyan
git tag -a "v$newVersion" -m $tagMessage
Write-Host "  ✓ Tag created" -ForegroundColor Green

# Push to GitHub
Write-Host ""
Write-Host "📤 Pushing to GitHub..." -ForegroundColor Cyan
git push
git push --tags
Write-Host "  ✓ Pushed to GitHub" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  ✅ Release v$newVersion completed!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "📦 Package files created in dist/:" -ForegroundColor Cyan
Get-ChildItem dist | Where-Object { $_.Name -like "*$newVersion*" } | ForEach-Object {
    Write-Host "  - $($_.Name)" -ForegroundColor White
}
Write-Host ""
Write-Host "🔗 GitHub: https://github.com/Cnext-eu/kairos-ontology-toolkit/releases/tag/v$newVersion" -ForegroundColor Cyan
Write-Host ""
Write-Host "📦 Install with:" -ForegroundColor Cyan
Write-Host "  pip install git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git@v$newVersion" -ForegroundColor White
Write-Host ""
