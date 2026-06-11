#!/usr/bin/env bash
# Merge cc-tracker hooks into ~/.claude/settings.json (idempotent).
# Run  ./install-hooks.sh --uninstall  to remove them.
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
  ./.venv/bin/python plugin/install_hooks.py "$@"
else
  python3 plugin/install_hooks.py "$@"
fi
