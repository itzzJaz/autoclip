# AutoClip — local setup on this Mac

AutoClip turns one long recording into short, vertical, caption-burned clips.
This copy runs **entirely on this machine**: no accounts, no API keys, no
credits, no watermark, and no footage leaves the laptop.

- Project: `/Users/jazlaanjamsheer/Desktop/AutoClip`
- Dashboard: `http://127.0.0.1:8000` (local only, no auth exposed to the network)
- Data (media, jobs, exports, settings): `/Users/jazlaanjamsheer/.autoclip/`

Upstream project: <https://github.com/artbyjazi/autoclip> (MIT licence).

---

## 1. Start it

```bash
cd /Users/jazlaanjamsheer/Desktop/AutoClip
./start-autoclip.sh
```

That opens `http://127.0.0.1:8000` in the browser. Options:

```bash
./start-autoclip.sh --no-open        # don't launch a browser
./start-autoclip.sh --port 8010      # different port
```

Stop it with **Ctrl+C** in the terminal that is running it.

The script does the fiddly parts for you:

- puts the full ffmpeg build on `PATH` (the plain Homebrew `ffmpeg` has no
  libass and cannot burn captions)
- clears the macOS hidden flag on the editable-install `.pth` files
- warns if Ollama is down or the configured model is not pulled
- refuses to start if the port is already taken

## 2. Make a clip

1. Open the dashboard.
2. Either **paste a link** (YouTube etc.) or **drop a video file**:
   `mp4 · mov · mkv · webm · mp3 · wav · m4a`.
3. Leave the defaults, or open **Options** to change clip length, count,
   aspect ratio, caption style and whether to use YouTube's own captions.
4. Wait. Stages: Prepare → Transcribe → Highlights → Reframe → Captions →
   Export, with live progress in the browser.
5. On the review page you get a ranked list of candidate clips with a 9:16
   preview. `keep` / `drop` each one, trim if needed, then **Export kept**.
6. Finished files land in `~/.autoclip/exports/<job_id>/` as
   `<title>_9x16.mp4` plus a `.srt` sidecar, and are downloadable from the UI.

Settings (provider, model, Whisper size, clip bounds, caption style, ratio)
live in the **Settings** page and are stored in `~/.autoclip/config.json`.

## 3. What is installed

| Piece | Version / choice | Notes |
|---|---|---|
| Python | 3.11.18 via `uv` | venv at `.venv`; MediaPipe has no 3.13 wheels |
| Node | existing system Node | frontend built into `backend/autoclip/static` |
| ffmpeg | `ffmpeg-full 9.0.2` | keg-only, used via `PATH`; libass + libx264 verified |
| Whisper | `faster-whisper`, `small`, CPU int8 | English, diarisation off |
| LLM | Ollama + `llama3.1:8b` | free, local; picks the highlight moments |
| Reframe | MediaPipe face tracking | keeps the speaker centred in 9:16 |
| Encoder | libx264, CRF 20 | hardware encoding deliberately off |

Measured on this M5 / 16 GB machine: a 2:49 1080p source transcribes in ~19 s
and produces a finished 90 s clip in about 4 minutes total, most of it the 8B
model thinking. Memory stays comfortably inside 16 GB.

## 4. Configuration

Active settings in `~/.autoclip/config.json`:

```json
{
  "active_provider": "ollama",
  "providers": { "ollama": { "model": "llama3.1:8b", "base_url": "http://localhost:11434" } },
  "whisper": { "model": "small", "compute_type": "", "language": "en", "diarization": false },
  "clips": { "min_duration_s": 20.0, "max_duration_s": 90.0, "max_clips": 3 },
  "export": { "ratio": "9:16", "caption_style": "bold_pop", "crf": 20, "write_srt": true }
}
```

Useful changes:

- **Longer/shorter clips** — raise `clips.min_duration_s` if highlights feel
  thin; a 20 s floor on a 46 s source leaves almost no room to work.
- **Different look** — `export.caption_style` (`bold_pop`, `clean`, …) and
  `export.ratio` (`9:16`, `1:1`, `16:9`).
- **Smaller model** — `qwen2.5:3b` is faster but was unreliable here: on a
  169 s transcript it returned zero valid highlights. `llama3.1:8b` is the
  right trade-off for 16 GB.
- **Accuracy** — `whisper.model` can go to `medium` (slower, better on accents
  and noisy audio).

Edit the file with the server stopped, or use the Settings page.

## 5. What actually works (tested)

| Feature | Status |
|---|---|
| Local transcription with word-level timestamps | ✅ |
| Local highlight selection via Ollama | ✅ 3 valid candidates in ~97 s |
| Face-tracked 9:16 reframe, speaker centred | ✅ verified frame-by-frame |
| Animated `bold_pop` captions burned in | ✅ verified in exported frames |
| SRT sidecar export | ✅ |
| Browser upload → job → review → export | ✅ end-to-end |
| Review page preview, keep/drop, trim, export | ✅ |
| Settings page, provider status, system panel | ✅ |
| Runs with no API keys / no paid services | ✅ |
| Watermark | none — the app adds none |
| YouTube link ingest | implemented via `yt-dlp`; may hit YouTube's bot check, in which case use `ingest.cookies_from_browser` or upload the file instead |
| Speaker diarisation | not installed (needs a HuggingFace token + gated models); off by default |
| Copy/copyright | you must own or have rights to the footage you process |

Test exports live in `test_output/`:

- `why-most-habits-fail-at-the-start_9x16.mp4` — 90.0 s, 1080×1920, H.264
  yuv420p, AAC 48 kHz mono, captions burned, plus `.srt`
- `becoming-consistent-requires-less-discipline_9x16.mp4` — 21.4 s, same
  specs, produced through the browser upload flow

Both were made from a NASA public-domain portrait plus narration generated
with macOS `say`, so no third-party footage was used.

## 6. Troubleshooting

**"Doctor says CUDA for Whisper FAIL"** — harmless on Apple Silicon. There is
no CUDA; the pipeline uses MPS/CPU int8. `ffmpeg -hide_banner -filters | grep subtitles`
and the `/api/system` panel are the checks that matter.

**Captions missing from exports** — you are running the plain `ffmpeg`
formula. Use `start-autoclip.sh`, or export
`PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"` yourself.

**`No module named autoclip`** — macOS re-applied the hidden flag to the
editable `.pth`. The launcher fixes it; manually:
`find .venv -name '*.pth' -exec chflags nohidden {} +`

**Highlights come back empty** — the model returned nothing usable. Try a
longer source, `llama3.1:8b`, or lower `min_duration_s`. Very short sources
give the model too little to choose from.

**Ollama not reachable** — `open -a Ollama`, then `ollama pull llama3.1:8b`.
Check with `curl -s localhost:11434/api/tags`.

**A YouTube download fails with a bot/sign-in error** — expected for some
videos. Set `ingest.cookies_from_browser` to your browser (e.g. `"chrome"`) or
download the file yourself and upload it.

## 7. Manual commands

For scripting or debugging, with the environment set up:

```bash
cd /Users/jazlaanjamsheer/Desktop/AutoClip
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
export PYTHONPATH="$PWD/backend"

.venv/bin/autoclip doctor                                  # environment checks
.venv/bin/autoclip clip samples/test_long.mp4 --max-clips 2 --style bold_pop
.venv/bin/autoclip serve --no-open --port 8000             # same as the launcher
```

## 8. Privacy and cost

- Transcription, reframing, captioning and encoding are local.
- Highlight selection talks only to `http://localhost:11434` (Ollama).
- No telemetry, no accounts, no subscriptions, no per-clip cost.
- The dashboard binds to `127.0.0.1` only. Do not change it to `0.0.0.0`:
  there is no authentication, so that would expose your media to the network.
