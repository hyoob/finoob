#!/usr/bin/env bash
# Git pre-push hook: verifies that live BigQuery views/routines/tables match sql/ before pushing.
# Bypass when needed with: git push --no-verify

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"

if [ ! -x "${PYTHON_BIN}" ]; then
    PYTHON_BIN="python3"
fi

echo "🔍 Checking if BigQuery DDL matches local sql/ folder..."
if ! "${PYTHON_BIN}" "${REPO_ROOT}/scripts/bq_schema_sync.py" status 2>/dev/null; then
    echo ""
    echo "⚠️  Push paused: Live BigQuery schemas/views/procedures differ from local sql/ files."
    echo "   👉 Run:  .venv/bin/python scripts/bq_schema_sync.py pull"
    echo "   👉 Then commit the updated sql/ files (or bypass with 'git push --no-verify')."
    exit 1
fi
echo "✅ BigQuery DDL is in sync with sql/."
