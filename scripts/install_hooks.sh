#!/usr/bin/env bash
# Install the repo's fail-safe git hooks by pointing git at .githooks/.
# Run once per clone:  bash scripts/install_hooks.sh
set -euo pipefail
cd "$(dirname "$0")/.."

chmod +x .githooks/* 2>/dev/null || true
git config core.hooksPath .githooks
echo "✓ git hooks installed (core.hooksPath=.githooks)."
echo "  Active hooks: $(ls .githooks | tr '\n' ' ')"
echo "  Bypass once with: git commit --no-verify"
