#!/usr/bin/env bash
#
# Start the AutoClip dashboard locally.
#
# Everything runs on this Mac: Whisper for transcription, MediaPipe for
# reframing, ffmpeg for encoding, and Ollama for highlight selection.
# Nothing is uploaded anywhere.
#
# Usage:
#   ./start-autoclip.sh              # start and open the browser
#   ./start-autoclip.sh --no-open    # start without opening a browser
#   ./start-autoclip.sh --port 8000  # pick a different port
#
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

HOST="127.0.0.1"
PORT="8000"
OPEN_BROWSER=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-open) OPEN_BROWSER=0; shift ;;
    --port) PORT="${2:?--port needs a value}"; shift 2 ;;
    -h|--help)
      sed -n '3,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

# --- ffmpeg -----------------------------------------------------------------
# The plain `ffmpeg` formula is a reduced build with no libass, which means it
# installs fine and then cannot burn a single caption. ffmpeg-full is keg-only,
# so its bin directory has to be prepended to PATH. The existing symlink is
# never touched, so other projects keep the ffmpeg they expect.
FFMPEG_BIN="/opt/homebrew/opt/ffmpeg-full/bin"
if [[ -d "$FFMPEG_BIN" ]]; then
  export PATH="$FFMPEG_BIN:$PATH"
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is not installed. Run: brew install ffmpeg-full" >&2
  exit 1
fi
# Buffer the list instead of piping into `grep -q`: under `pipefail`, grep
# exiting early gives ffmpeg SIGPIPE and the whole pipeline looks like a failure.
FFMPEG_FILTERS="$(ffmpeg -hide_banner -filters 2>/dev/null || true)"
if ! grep -q ' subtitles ' <<<"$FFMPEG_FILTERS"; then
  echo "WARNING: this ffmpeg has no libass filter, so captions cannot be burned in." >&2
  echo "         Install the full build: brew install ffmpeg-full" >&2
fi

# --- Python environment -----------------------------------------------------
if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "Python environment missing. Create it with:" >&2
  echo "  uv venv --python 3.11 && uv pip install -e \".[dev]\"" >&2
  exit 1
fi

# macOS sometimes re-applies the hidden flag to files inside site-packages,
# which makes Python silently skip the editable-install .pth and report
# "No module named autoclip". Clearing the flag is enough; PYTHONPATH is a
# belt-and-braces fallback for the same problem.
find "$PROJECT_DIR/.venv" -name '*.pth' -exec chflags nohidden {} + 2>/dev/null || true
export PYTHONPATH="$PROJECT_DIR/backend${PYTHONPATH:+:$PYTHONPATH}"

# --- Ollama -----------------------------------------------------------------
OLLAMA_URL="http://localhost:11434"
if curl -sf --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  MODEL="$(python3 - <<'PY' 2>/dev/null || echo ""
import json, pathlib
p = pathlib.Path.home() / ".autoclip" / "config.json"
try:
    print(json.loads(p.read_text())["providers"]["ollama"]["model"])
except Exception:
    print("")
PY
)"
  TAGS="$(curl -sf --max-time 3 "$OLLAMA_URL/api/tags" || true)"
  if [[ -n "$MODEL" ]] && ! grep -q "\"$MODEL\"" <<<"$TAGS"; then
    echo "NOTE: Ollama is running but '$MODEL' is not pulled yet."
    echo "      Run: ollama pull $MODEL"
  else
    echo "Ollama: reachable${MODEL:+ ($MODEL)}"
  fi
else
  echo "NOTE: Ollama is not running. Highlight picking needs it:"
  echo "      open -a Ollama     # or: ollama serve"
  echo "      Continuing — the dashboard will still start."
fi

# --- Start ------------------------------------------------------------------
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use. AutoClip may already be running:"
  echo "  http://$HOST:$PORT"
  exit 1
fi

echo "AutoClip: http://$HOST:$PORT"
echo "Press Ctrl+C to stop."

ARGS=(serve --host "$HOST" --port "$PORT")
if [[ "$OPEN_BROWSER" == "1" ]]; then
  ARGS+=(--open)
else
  ARGS+=(--no-open)
fi

exec "$PROJECT_DIR/.venv/bin/autoclip" "${ARGS[@]}"
