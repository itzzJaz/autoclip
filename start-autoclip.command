#!/usr/bin/env bash
#
# Double-click this file in Finder, or run ./start-autoclip.command, to start
# AutoClip and its local model server (Ollama).
#
# Everything stays on this Mac. Nothing is uploaded anywhere.
#
# Extra arguments are passed through, e.g.:
#   ./start-autoclip.command --no-open
#   ./start-autoclip.command --port 8010
#
set -euo pipefail

cd "$(dirname "$0")"

OLLAMA_URL="http://localhost:11434"

# --- Ollama ---------------------------------------------------------------
# AutoClip's highlight picking needs Ollama. Start it if it is not up yet and
# give it a few seconds to answer before handing over to the launcher.
if ! curl -sf --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo "Starting Ollama..."
  brew services start ollama >/dev/null 2>&1 || open -a Ollama >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    curl -sf --max-time 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1 && break
    sleep 1
  done
  if ! curl -sf --max-time 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    echo "NOTE: Ollama did not come up. Highlight picking will be unavailable."
    echo "      Start it manually with: brew services start ollama"
  fi
fi

# --- AutoClip -------------------------------------------------------------
# start-autoclip.sh handles ffmpeg, the venv, the model check and the port.
# exec replaces this shell, so Ctrl+C here stops the server.
exec ./start-autoclip.sh "$@"
