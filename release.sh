#!/bin/bash
#
# Create and publish a new release of kairos-ontology-toolkit
#
# This script automates the release process:
# - Prompts for release type (major/minor/patch)
# - Updates version in pyproject.toml and __init__.py
# - Updates poetry.lock
# - Builds the package
# - Commits changes
# - Creates and pushes git tag
#

set -e

echo ""
echo "========================================"
echo "  Kairos Ontology Toolkit - Release"
echo "========================================"
echo ""

# Check for uncommitted changes
if [[ -n $(git status --porcelain) ]]; then
    echo "❌ Error: You have uncommitted changes. Please commit or stash them first."
    git status --short
    exit 1
fi

# Get current version from pyproject.toml
if grep -q 'version = "[0-9]\+\.[0-9]\+\.[0-9]\+"' pyproject.toml; then
    current_version=$(grep 'version = ' pyproject.toml | head -1 | sed 's/.*"\([0-9.]*\)".*/\1/')
    major=$(echo $current_version | cut -d. -f1)
    minor=$(echo $current_version | cut -d. -f2)
    patch=$(echo $current_version | cut -d. -f3)
else
    echo "❌ Error: Could not parse version from pyproject.toml"
    exit 1
fi

echo "📦 Current version: $current_version"
echo ""

# Prompt for release type
echo "Select release type:"
echo "  [1] Patch (bug fixes)         $major.$minor.$patch -> $major.$minor.$((patch+1))"
echo "  [2] Minor (new features)      $major.$minor.$patch -> $major.$((minor+1)).0"
echo "  [3] Major (breaking changes)  $major.$minor.$patch -> $((major+1)).0.0"
echo ""
read -p "Enter choice (1-3): " choice

# Calculate new version
case $choice in
    1)
        new_version="$major.$minor.$((patch+1))"
        release_type="Patch"
        ;;
    2)
        new_version="$major.$((minor+1)).0"
        release_type="Minor"
        ;;
    3)
        new_version="$((major+1)).0.0"
        release_type="Major"
        ;;
    *)
        echo "❌ Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "🚀 Preparing $release_type release: $current_version -> $new_version"
echo ""

# Confirm
read -p "Continue? (y/n): " confirm
if [[ "$confirm" != "y" ]]; then
    echo "❌ Release cancelled"
    exit 0
fi

echo ""
echo "📝 Updating version numbers..."

# Update pyproject.toml
sed -i.bak "s/version = \"[0-9.]*\"/version = \"$new_version\"/" pyproject.toml && rm pyproject.toml.bak

# Update __init__.py
sed -i.bak "s/__version__ = \"[0-9.]*\"/__version__ = \"$new_version\"/" src/kairos_ontology/__init__.py && rm src/kairos_ontology/__init__.py.bak

echo "  ✓ Updated pyproject.toml"
echo "  ✓ Updated __init__.py"

# Update poetry lock
echo ""
echo "🔒 Updating poetry.lock..."
poetry lock
echo "  ✓ Lock file updated"

# Build package
echo ""
echo "🏗️  Building package..."
poetry build
echo "  ✓ Package built"

# Get release notes
echo ""
echo "📝 Enter release notes (press Ctrl+D when done):"
release_notes=$(cat)

if [[ -z "$release_notes" ]]; then
    release_notes="Release v$new_version"
fi

commit_message="Release v$new_version"
tag_message="Release v$new_version - $release_type release

$release_notes"

# Commit changes
echo ""
echo "💾 Committing changes..."
git add pyproject.toml poetry.lock src/kairos_ontology/__init__.py
git commit -m "$commit_message"
echo "  ✓ Changes committed"

# Create tag
echo ""
echo "🏷️  Creating tag v$new_version..."
git tag -a "v$new_version" -m "$tag_message"
echo "  ✓ Tag created"

# Push to GitHub
echo ""
echo "📤 Pushing to GitHub..."
git push
git push --tags
echo "  ✓ Pushed to GitHub"

echo ""
echo "========================================"
echo "  ✅ Release v$new_version completed!"
echo "========================================"
echo ""
echo "📦 Package files created in dist/:"
ls -1 dist/*$new_version* 2>/dev/null | sed 's/^/  - /'
echo ""
echo "🔗 GitHub: https://github.com/Cnext-eu/kairos-ontology-toolkit/releases/tag/v$new_version"
echo ""
echo "📦 Install with:"
echo "  pip install git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git@v$new_version"
echo ""
