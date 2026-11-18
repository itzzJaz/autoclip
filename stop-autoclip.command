#!/usr/bin/env bash
#
# Double-click this file in Finder, or run ./stop-autoclip.command, to stop
# AutoClip and free the AI model's memory.
#
# Stops the dashboard on port 8000, unloads any model Ollama has in RAM, quits
# the Ollama app and stops its background service. Files on disk are untouched.
#
set -uo pipefail

PORT="${AUTOCLIP_PORT:-8000}"

# --- AutoClip dashboard ---------------------------------------------------
PIDS="$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$PIDS" ]]; then
  echo "Stopping AutoClip on port $PORT (PID $(echo "$PIDS" | tr '\n' ' '))..."
  # shellcheck disable=SC2086
  kill $PIDS 2>/dev/null || true
  sleep 2
  # Anything still hanging on is force-stopped.
  PIDS="$(lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$PIDS" ]]; then
    # shellcheck disable=SC2086
    kill -9 $PIDS 2>/dev/null || true
  fi
else
  echo "AutoClip was not running on port $PORT."
fi

# --- Ollama model ---------------------------------------------------------
if command -v ollama >/dev/null 2>&1; then
  while read -r model _; do
    [[ -z "$model" || "$model" == "NAME" ]] && continue
    echo "Unloading $model from memory..."
    ollama stop "$model" >/dev/null 2>&1 || true
  done < <(ollama ps 2>/dev/null || true)
else
  echo "ollama command not found; skipping model unload."
fi

osascript -e 'quit app "Ollama"' >/dev/null 2>&1 || true
brew services stop ollama >/dev/null 2>&1 || true

echo "Done. Port $PORT is free and no model is loaded."
