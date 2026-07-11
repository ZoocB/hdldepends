#!/usr/bin/env bash
#
# Create an isolated virtual environment for developing/testing hdldepends.
#
# This keeps pytest, mypy and the package itself out of your global / pyenv
# Python so test runs never touch your machine's environment.
#
# Usage:
#   ./scripts/setup_env.sh            # create .venv and install dev deps
#   ./scripts/setup_env.sh --test     # ... then run the test suite
#   ./scripts/setup_env.sh --recreate # delete and rebuild .venv from scratch
#
# Afterwards, activate it in your shell with:
#   source .venv/bin/activate
#
set -euo pipefail

# Resolve repo root (this script lives in <root>/scripts).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="$REPO_ROOT/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

RUN_TESTS=0
for arg in "$@"; do
  case "$arg" in
    --test) RUN_TESTS=1 ;;
    --recreate) echo "Removing existing $VENV_DIR"; rm -rf "$VENV_DIR" ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment in $VENV_DIR (using $("$PYTHON_BIN" --version 2>&1))"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# Use the venv's interpreter directly (no need to 'activate' inside the script).
VENV_PY="$VENV_DIR/bin/python"

echo "Upgrading pip"
"$VENV_PY" -m pip install --upgrade pip >/dev/null

echo "Installing hdldepends (editable) with dev dependencies"
"$VENV_PY" -m pip install -e '.[dev]'

echo
echo "Done. Activate with:  source .venv/bin/activate"

if [ "$RUN_TESTS" -eq 1 ]; then
  echo
  echo "Running test suite"
  "$VENV_PY" -m pytest
fi
