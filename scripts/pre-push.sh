#!/usr/bin/env bash
# Git pre-push safety hook: verifies no database files, keys, or secrets are tracked before pushing.
# Bypass when needed with: git push --no-verify

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

echo "🔍 Running pre-push safety check..."
FORBIDDEN=$(git -C "${REPO_ROOT}" ls-files | grep -E '\.(duckdb|pem)$|secrets\.toml$' || true)
if [ -n "${FORBIDDEN}" ]; then
    echo "🚨 Push blocked: Sensitive or database files are tracked in Git:"
    echo "${FORBIDDEN}"
    exit 1
fi
echo "✅ Pre-push check passed."
