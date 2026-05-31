#!/usr/bin/env bash
# Setup script for Kairos ontology hub development environment.
# Uses uv to create an isolated .venv and install the toolkit + dev dependencies.
#
# Usage:
#   ./setup-env.sh            # Create/sync the virtual environment
#   ./setup-env.sh --force    # Recreate from scratch (deletes existing .venv)
#
# Requires: uv (https://docs.astral.sh/uv/)
#   Install: curl -LsSf https://astral.sh/uv/install.sh | sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Check uv is installed ---
if ! command -v uv &> /dev/null; then
    echo "ERROR: 'uv' is not installed." >&2
    echo ""
    echo "Install uv with:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo ""
    echo "More info: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

# --- Recreate if --force ---
VENV_DIR="$SCRIPT_DIR/.venv"
if [[ "${1:-}" == "--force" ]] && [[ -d "$VENV_DIR" ]]; then
    echo "Removing existing .venv ..."
    rm -rf "$VENV_DIR"
fi

# --- Sync environment ---
echo "Syncing environment with uv ..."
cd "$SCRIPT_DIR"
uv sync

# --- Validate ---
echo ""
TOOLKIT_VERSION=$(uv run python -c "from kairos_ontology import __version__; print(__version__)")
TOOLKIT_PATH=$(uv run python -c "import kairos_ontology; print(kairos_ontology.__file__)")
echo "Toolkit version : $TOOLKIT_VERSION"
echo "Toolkit location: $TOOLKIT_PATH"
echo ""
echo "Environment ready. Run commands with:"
echo "  uv run kairos-ontology <command>"
echo ""
echo "Or activate the venv manually:"
echo "  source .venv/bin/activate"
