"""Thumbnail stills for the publishing queue.

Generated from the exported file itself, not from the source, so the queue shows
what will actually be uploaded — including burned captions and the final crop.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .. import paths
from ..pipeline import ffmpeg

log = logging.getLogger(__name__)


def thumbnail_for(export_id: str, video: Path, *, at_s: float = 0.8) -> Path | None:
    target = paths.work_dir() / "thumbs" / f"{export_id}.jpg"
    try:
        if target.exists() and target.stat().st_mtime >= video.stat().st_mtime:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    command = [
        ffmpeg.ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-v",
        "error",
        "-ss",
        f"{max(0.0, at_s):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-vf",
        "scale=480:-2",
        "-q:v",
        "4",
        str(target),
    ]
    proc = subprocess.run(
        command, capture_output=True, text=True, check=False, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0 or not target.exists():
        log.debug("Could not generate a thumbnail for %s: %s", video.name, proc.stderr)
        return None
    return target
