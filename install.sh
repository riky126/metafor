#!/bin/bash
set -e

# Define paths
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ENV="$ROOT_DIR/build_env"

# Determine pip command
if [[ -z "$VIRTUAL_ENV" ]] && [[ -d "$BUILD_ENV" ]]; then
    PIP="$BUILD_ENV/bin/pip"
    echo "Using build_env pip: $PIP"
else
    PIP="pip"
    echo "Using active pip: $(which pip)"
fi

echo "Installing Metafor Framework..."
"$PIP" install "$ROOT_DIR"

echo "Installing Metafor CLI..."
"$PIP" install "$ROOT_DIR/metafor_cli"

echo "✅ Done! Metafor is installed."
echo "Run 'metafor new <project_name>' to create a new project."
