Test exports
============

These clips were produced by this local AutoClip install to verify the whole
pipeline. The source media is synthesised, not third-party footage:

  presenter.jpg  NASA astronaut portrait, public domain
  narration      generated locally with macOS `say`
  sources        samples/test_long.mp4 (2:49), samples/test_podcast.mp4 (0:46)

Files
-----

why-most-habits-fail-at-the-start_9x16.mp4 / .srt
  CLI path, 2:49 source -> 90.0 s clip
  1080x1920, H.264 yuv420p, AAC 48 kHz mono, captions burned, no watermark
  Highlight picked by Ollama llama3.1:8b; face tracked at x~1129.5

becoming-consistent-requires-less-discipline_9x16.mp4 / .srt
  Browser upload path, 0:46 source -> 21.4 s clip
  Same output specs, produced end-to-end through the dashboard
  (upload -> transcribe -> highlights -> reframe -> captions -> export)

Both are safe to delete once you have made your own clips.
