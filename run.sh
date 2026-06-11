#!/usr/bin/env bash
# cc-tracker launcher: collector server (:8765) + desktop float.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "[1/3] creating venv ..."
  python3 -m venv .venv
fi
echo "[2/3] installing python deps ..."
./.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt

echo "[3/3] launching desktop float ..."
if [ ! -d desktop/node_modules ]; then
  echo "  [first run] installing electron ..."
  ( cd desktop && npm install )
fi
( cd desktop && npm start >/dev/null 2>&1 & )

echo "==============================================="
echo " cc-tracker collector at http://127.0.0.1:8765"
echo " Next: run  ./install-hooks.sh  once to wire Claude Code."
echo "==============================================="
# Kill any old collector on :8765 first, so we start clean (drop stale in-memory state) and load latest code.
( lsof -ti tcp:8765 2>/dev/null | xargs -r kill 2>/dev/null ) || true
exec ./.venv/bin/python -m server
