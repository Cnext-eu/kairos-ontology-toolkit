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

# Get current version from pyproject.toml (handles pre-release suffixes like 2.17.0rc1)
$pyprojectContent = Get-Content "pyproject.toml" -Raw
if ($pyprojectContent -match 'version\s*=\s*"([0-9]+)\.([0-9]+)\.([0-9]+)([a-z0-9]*)"') {
    $major = [int]$matches[1]
    $minor = [int]$matches[2]
    $patch = [int]$matches[3]
    $currentPreSuffix = $matches[4]
} else {
    Write-Host "❌ Error: Could not parse version from pyproject.toml" -ForegroundColor Red
    exit 1
}

$currentVersion = "$major.$minor.$patch$currentPreSuffix"
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
Write-Host "  [4] Pre-release `(rc/beta/alpha`)  for testing before GA" -ForegroundColor White
Write-Host ""

do {
    $choice = Read-Host "Enter choice `(1-4`)"
} while ($choice -notmatch '^[1-4]$')

# Calculate new version
$preLabel = ""
$preNum = 0
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
    "4" {
        # Pre-release: bump target version (defaults to next minor)
        Write-Host ""
        Write-Host "Pre-release target version:" -ForegroundColor Cyan
        Write-Host "  [1] Next patch: $patchTarget" -ForegroundColor White
        Write-Host "  [2] Next minor: $minorTarget" -ForegroundColor White
        Write-Host "  [3] Next major: $majorTarget" -ForegroundColor White
        Write-Host ""
        do {
            $targetChoice = Read-Host "Enter target `(1-3, default=2`)"
            if ([string]::IsNullOrWhiteSpace($targetChoice)) { $targetChoice = "2" }
        } while ($targetChoice -notmatch '^[1-3]$')

        switch ($targetChoice) {
            "1" { $newMajor = $major; $newMinor = $minor; $newPatch = $patch + 1 }
            "2" { $newMajor = $major; $newMinor = $minor + 1; $newPatch = 0 }
            "3" { $newMajor = $major + 1; $newMinor = 0; $newPatch = 0 }
        }

        Write-Host ""
        Write-Host "Pre-release label:" -ForegroundColor Cyan
        Write-Host "  [1] rc    `(release candidate — feature-complete, final testing`)" -ForegroundColor White
        Write-Host "  [2] beta  `(feature-complete, may have bugs`)" -ForegroundColor White
        Write-Host "  [3] alpha `(early preview, unstable`)" -ForegroundColor White
        Write-Host ""
        do {
            $labelChoice = Read-Host "Enter label `(1-3, default=1`)"
            if ([string]::IsNullOrWhiteSpace($labelChoice)) { $labelChoice = "1" }
        } while ($labelChoice -notmatch '^[1-3]$')

        switch ($labelChoice) {
            "1" { $preLabel = "rc" }
            "2" { $preLabel = "beta" }
            "3" { $preLabel = "alpha" }
        }

        # Determine pre-release sequence number
        $targetBase = "$newMajor.$newMinor.$newPatch"
        $existingTags = git tag -l "v$targetBase-$preLabel.*" | Sort-Object -Descending
        if ($existingTags) {
            $lastTag = $existingTags[0]
            if ($lastTag -match "\.$preLabel\.(\d+)$") {
                $preNum = [int]$matches[1] + 1
            } else {
                $preNum = 1
            }
        } else {
            $preNum = 1
        }

        $releaseType = "Pre-release"
    }
}

# Build version strings
$baseVersion = "$newMajor.$newMinor.$newPatch"
if ($preLabel) {
    # PEP 440 pre-release suffix (e.g. 2.17.0rc1, 2.17.0b1, 2.17.0a1)
    $pep440Label = switch ($preLabel) {
        "rc"    { "rc" }
        "beta"  { "b" }
        "alpha" { "a" }
    }
    $newVersion = "$baseVersion$pep440Label$preNum"
    $tagVersion = "v$baseVersion-$preLabel.$preNum"
} else {
    $newVersion = $baseVersion
    $tagVersion = "v$newVersion"
}
Write-Host ""
Write-Host "🚀 Preparing $releaseType release: $currentVersion -> $newVersion" -ForegroundColor Green
if ($preLabel) {
    Write-Host "   Git tag: $tagVersion" -ForegroundColor Yellow
}
Write-Host ""

# Confirm
$confirm = Read-Host "Continue? `(y/n`)"
if ($confirm -ne 'y') {
    Write-Host "❌ Release cancelled" -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "📝 Updating version numbers..." -ForegroundColor Cyan

# Update pyproject.toml — only the [tool.poetry] version line (first occurrence)
$pyprojectLines = Get-Content "pyproject.toml"
$replaced = $false
$updatedLines = $pyprojectLines | ForEach-Object {
    if (-not $replaced -and $_ -match '^\s*version\s*=\s*"[^"]+"') {
        $replaced = $true
        $_ -replace 'version\s*=\s*"[^"]+"', "version = `"$newVersion`""
    } else {
        $_
    }
}
Set-Content "pyproject.toml" -Value ($updatedLines -join "`n") -NoNewline

# Update __init__.py
$initPath = "src\kairos_ontology\__init__.py"
$initContent = Get-Content $initPath -Raw
$initContent = $initContent -replace '__version__\s*=\s*"[^"]+"', "__version__ = `"$newVersion`""
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
    $releaseNote = "Release $tagVersion"
}

$commitMessage = if ($preLabel) { "chore: bump version to $newVersion `($tagVersion`)" } else { "chore: bump version to $newVersion" }
$tagMessage = "Release $tagVersion - $releaseType release`n`n$releaseNote"

# Commit changes
Write-Host ""
Write-Host "💾 Committing changes..." -ForegroundColor Cyan
git add pyproject.toml poetry.lock src/kairos_ontology/__init__.py
git commit -m $commitMessage
Write-Host "  ✓ Changes committed" -ForegroundColor Green

# Create tag
Write-Host ""
Write-Host "🏷️  Creating tag $tagVersion..." -ForegroundColor Cyan
git tag -a $tagVersion -m $tagMessage
Write-Host "  ✓ Tag created" -ForegroundColor Green

# Push to GitHub
Write-Host ""
Write-Host "📤 Pushing to GitHub..." -ForegroundColor Cyan
git push
git push --tags
Write-Host "  ✓ Pushed to GitHub" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  ✅ Release $tagVersion completed!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "📦 Package files created in dist/:" -ForegroundColor Cyan
Get-ChildItem dist | Where-Object { $_.Name -like "*$newVersion*" } | ForEach-Object {
    Write-Host "  - $($_.Name)" -ForegroundColor White
}
Write-Host ""
Write-Host "🔗 GitHub: https://github.com/Cnext-eu/kairos-ontology-toolkit/releases/tag/$tagVersion" -ForegroundColor Cyan
Write-Host ""
Write-Host "📦 Install with:" -ForegroundColor Cyan
Write-Host "  pip install git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git@$tagVersion" -ForegroundColor White
Write-Host ""
