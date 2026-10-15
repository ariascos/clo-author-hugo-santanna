#!/usr/bin/env bash
# clo-author: infrastructure
#
# Point git at the version-controlled hooks in .githooks/ (pre-commit gate,
# post-merge reminder). Run once per clone:  scripts/install-hooks.sh
# Undo with:  git config --unset core.hooksPath

set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
chmod +x .githooks/*
git config core.hooksPath .githooks
echo "git hooks installed: core.hooksPath -> .githooks ($(ls .githooks | tr '\n' ' '))"
