"""Shorts readiness checks.

The point of this module is to tell the truth about a file before it is uploaded,
not to make it pass. Nothing here rewrites, re-encodes, or "fixes" the export.
Every check reports what was measured and why it matters, and the uploader only
blocks on findings that would make the upload broken or invalid.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import paths
from ..pipeline import ffmpeg

log = logging.getLogger(__name__)

#: Shorts accepts up to three minutes. The extra half second avoids rejecting a
#: file whose container rounds 180.0 to 180.02.
MAX_DURATION_S = 180.5

_PASSING_CODECS = {"h264", "hevc", "h265", "av1", "vp9"}


@dataclass
class Check:
    key: str
    label: str
    ok: bool
    severity: str  # "error" | "warn" | "info"
    detail: str


@dataclass
class ValidationReport:
    ok: bool = False
    duration_s: float = 0.0
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool = False
    video_codec: str | None = None
    frozen_opening_s: float = 0.0
    checks: list[Check] = field(default_factory=list)

    @property
    def errors(self) -> list[Check]:
        return [check for check in self.checks if not check.ok and check.severity == "error"]

    @property
    def warnings(self) -> list[Check]:
        return [check for check in self.checks if not check.ok and check.severity == "warn"]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["errors"] = [asdict(check) for check in self.errors]
        payload["warnings"] = [asdict(check) for check in self.warnings]
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> ValidationReport:
        return cls(
            ok=payload.get("ok", False),
            duration_s=payload.get("duration_s", 0.0),
            width=payload.get("width"),
            height=payload.get("height"),
            fps=payload.get("fps"),
            has_audio=payload.get("has_audio", False),
            video_codec=payload.get("video_codec"),
            frozen_opening_s=payload.get("frozen_opening_s", 0.0),
            checks=[Check(**item) for item in payload.get("checks", [])],
        )


def validate_export(path: Path, *, cache_key: str | None = None) -> ValidationReport:
    """Measure an export against the properties a Short needs.

    ``cache_key`` persists the result under ``work/validation`` and is invalidated
    by file mtime and size, so opening the publish screen repeatedly does not
    trigger a full decode each time.
    """
    cache = _cache_path(cache_key) if cache_key else None
    if cache is not None and cache.exists():
        try:
            payload = json.loads(cache.read_text(encoding="utf-8"))
            if (
                payload.get("path") == str(path)
                and payload.get("mtime") == path.stat().st_mtime
                and payload.get("size") == path.stat().st_size
            ):
                return ValidationReport.from_dict(payload["report"])
        except (OSError, ValueError, KeyError):
            pass

    report = _measure(path)

    if cache is not None:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(
                json.dumps(
                    {
                        "path": str(path),
                        "mtime": path.stat().st_mtime,
                        "size": path.stat().st_size,
                        "report": report.to_dict(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            log.debug("Could not cache validation for %s.", path, exc_info=True)

    return report


def _cache_path(key: str) -> Path:
    return paths.work_dir() / "validation" / f"{key}.json"


def _measure(path: Path) -> ValidationReport:
    report = ValidationReport()

    if not path.exists() or path.stat().st_size == 0:
        report.checks.append(
            Check(
                key="file",
                label="File present",
                ok=False,
                severity="error",
                detail="The exported file is missing or empty, so there is nothing to upload.",
            )
        )
        return report

    report.checks.append(
        Check(
            key="file",
            label="File present",
            ok=True,
            severity="info",
            detail="The export exists on disk.",
        )
    )

    try:
        info = ffmpeg.probe(path)
    except ffmpeg.FFmpegError as exc:
        report.checks.append(
            Check(
                key="probe",
                label="Readable media",
                ok=False,
                severity="error",
                detail=f"ffprobe could not read the file: {exc}",
            )
        )
        return report

    report.duration_s = info.duration_s
    report.width = info.width
    report.height = info.height
    report.fps = info.fps
    report.has_audio = info.has_audio
    report.video_codec = info.video_codec

    if not info.has_video:
        report.checks.append(
            Check(
                key="video",
                label="Video stream",
                ok=False,
                severity="error",
                detail="The file has no video stream.",
            )
        )
        return report

    _check_duration(report, info.duration_s)
    _check_ratio(report, info.width, info.height)
    _check_resolution(report, info.width, info.height)
    _check_fps(report, info.fps)
    _check_audio(report, info.has_audio)
    _check_codec(report, info.video_codec)
    _check_completeness(report, path, info)
    _check_opening(report, path, info)

    report.ok = not report.errors
    return report


def _check_duration(report: ValidationReport, duration: float) -> None:
    if duration <= 0:
        report.checks.append(
            Check(
                key="duration",
                label="Duration",
                ok=False,
                severity="error",
                detail=(
                    "The container reports no duration, which usually means the render "
                    "was interrupted."
                ),
            )
        )
        return

    if duration > MAX_DURATION_S:
        report.checks.append(
            Check(
                key="duration",
                label="Duration",
                ok=False,
                severity="error",
                detail=(
                    f"{duration:.1f}s is longer than the 3-minute Shorts limit. "
                    "Trim the clip and export again."
                ),
            )
        )
        return

    report.checks.append(
        Check(
            key="duration",
            label="Duration",
            ok=True,
            severity="info",
            detail=f"{duration:.1f}s — within the 3-minute limit.",
        )
    )


def _check_ratio(report: ValidationReport, width: int | None, height: int | None) -> None:
    if not width or not height:
        report.checks.append(
            Check(
                key="ratio",
                label="Aspect ratio",
                ok=False,
                severity="error",
                detail="The video dimensions are unknown.",
            )
        )
        return

    aspect = width / height
    if abs(aspect - 9 / 16) <= 0.01:
        detail = f"{width}×{height} (9:16) — fills a phone screen."
        report.checks.append(
            Check(key="ratio", label="Aspect ratio", ok=True, severity="info", detail=detail)
        )
    elif abs(aspect - 1.0) <= 0.01:
        report.checks.append(
            Check(
                key="ratio",
                label="Aspect ratio",
                ok=False,
                severity="warn",
                detail=(
                    f"{width}×{height} is square. Shorts accepts it, but vertical 9:16 "
                    "uses the whole screen and is less likely to be letterboxed."
                ),
            )
        )
    else:
        report.checks.append(
            Check(
                key="ratio",
                label="Aspect ratio",
                ok=False,
                severity="error",
                detail=(
                    f"{width}×{height} is {width / height:.2f}:1, not vertical. "
                    "Re-export this clip at 9:16 before publishing it as a Short."
                ),
            )
        )


def _check_resolution(report: ValidationReport, width: int | None, height: int | None) -> None:
    if not width or not height:
        return
    short, long = sorted((width, height))
    if short < 720 or long < 1280:
        report.checks.append(
            Check(
                key="resolution",
                label="Resolution",
                ok=False,
                severity="error",
                detail=(
                    f"{width}×{height} is below 720p on the short side. "
                    "YouTube will either reject it or make it look soft."
                ),
            )
        )
    elif short < 1080:
        report.checks.append(
            Check(
                key="resolution",
                label="Resolution",
                ok=False,
                severity="warn",
                detail=(
                    f"{width}×{height} is below 1080 on the short side. It is allowed, "
                    "but 1080×1920 is the sharpest option for a Short."
                ),
            )
        )
    else:
        report.checks.append(
            Check(
                key="resolution",
                label="Resolution",
                ok=True,
                severity="info",
                detail=f"{width}×{height} — at least 1080 on the short side.",
            )
        )


def _check_fps(report: ValidationReport, fps: float | None) -> None:
    if not fps:
        report.checks.append(
            Check(
                key="fps",
                label="Frame rate",
                ok=False,
                severity="warn",
                detail="The frame rate could not be read. Most players will still handle it.",
            )
        )
        return
    if 24.0 <= fps <= 60.0:
        report.checks.append(
            Check(
                key="fps",
                label="Frame rate",
                ok=True,
                severity="info",
                detail=f"{fps:g} fps — within the 24–60 range Shorts handles natively.",
            )
        )
    else:
        report.checks.append(
            Check(
                key="fps",
                label="Frame rate",
                ok=False,
                severity="warn",
                detail=f"{fps:g} fps is outside 24–60; YouTube may re-encode it.",
            )
        )


def _check_audio(report: ValidationReport, has_audio: bool) -> None:
    if has_audio:
        report.checks.append(
            Check(
                key="audio",
                label="Audio",
                ok=True,
                severity="info",
                detail="An audio track is present.",
            )
        )
    else:
        report.checks.append(
            Check(
                key="audio",
                label="Audio",
                ok=False,
                severity="warn",
                detail=(
                    "There is no audio track. Silent Shorts are allowed, but this is "
                    "often a mistake."
                ),
            )
        )


def _check_codec(report: ValidationReport, codec: str | None) -> None:
    if codec in _PASSING_CODECS:
        report.checks.append(
            Check(
                key="codec",
                label="Video codec",
                ok=True,
                severity="info",
                detail=f"{codec} — accepted by YouTube.",
            )
        )
    else:
        report.checks.append(
            Check(
                key="codec",
                label="Video codec",
                ok=False,
                severity="warn",
                detail=(
                    f"{codec or 'unknown'} may be transcoded on upload. "
                    "H.264 is the safe choice."
                ),
            )
        )


def _check_completeness(report: ValidationReport, path: Path, info: ffmpeg.MediaInfo) -> None:
    errors = ffmpeg.decode_errors(path)
    if errors:
        tail = "\n".join(errors.splitlines()[-4:])
        report.checks.append(
            Check(
                key="decode",
                label="File integrity",
                ok=False,
                severity="error",
                detail=(
                    "The file does not decode cleanly. This is the corrupt-render symptom; "
                    f"export it again.\n{tail}"
                ),
            )
        )
        return

    expected = None
    if info.fps and info.duration_s:
        expected = round(info.duration_s * info.fps)
    if info.frame_count is not None and expected is not None:
        tolerance = max(3, round((info.fps or 30.0) * 0.4))
        if abs(info.frame_count - expected) > tolerance:
            report.checks.append(
                Check(
                    key="frames",
                    label="File integrity",
                    ok=False,
                    severity="error",
                    detail=(
                        f"The container holds {info.frame_count} frames but {expected} were "
                        "expected for its duration. The render stopped short."
                    ),
                )
            )
            return

    report.checks.append(
        Check(
            key="decode",
            label="File integrity",
            ok=True,
            severity="info",
            detail="Every packet decoded cleanly; the container matches its duration.",
        )
    )


def _check_opening(report: ValidationReport, path: Path, info: ffmpeg.MediaInfo) -> None:
    first_pts = ffmpeg.first_video_packet_pts(path)
    frame_s = 1.0 / max(info.fps or 30.0, 1.0)
    if first_pts is not None and first_pts > max(0.1, 2 * frame_s):
        report.checks.append(
            Check(
                key="opening",
                label="Opening frame",
                ok=False,
                severity="error",
                detail=(
                    f"The first frame sits at {first_pts:.2f}s on the timeline, which players "
                    "show as a frozen opening. Export it again."
                ),
            )
        )
        return

    frozen = _frozen_opening_seconds(path)
    report.frozen_opening_s = frozen
    if frozen >= 1.0:
        report.checks.append(
            Check(
                key="opening",
                label="Opening frame",
                ok=False,
                severity="error",
                detail=(
                    f"The first {frozen:.1f}s are a static frame. That is the frozen-opening "
                    "symptom; retry the export."
                ),
            )
        )
    elif frozen >= 0.6:
        report.checks.append(
            Check(
                key="opening",
                label="Opening frame",
                ok=False,
                severity="warn",
                detail=(
                    f"The opening {frozen:.1f}s barely change. Check that the clip starts on "
                    "a moment with movement."
                ),
            )
        )
    else:
        report.checks.append(
            Check(
                key="opening",
                label="Opening frame",
                ok=True,
                severity="info",
                detail="The clip starts at zero and the opening frame is not frozen.",
            )
        )


_FREEZE_START = re.compile(r"freeze_start:\s*([0-9.]+)")
_FREEZE_DURATION = re.compile(r"freeze_duration:\s*([0-9.]+)")


def _frozen_opening_seconds(path: Path) -> float:
    """Length of a freeze that begins at t=0, measured over the first 4s."""
    command = [
        ffmpeg.ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-v",
        "info",
        "-t",
        "4",
        "-i",
        str(path),
        "-an",
        "-vf",
        "freezedetect=n=0.003:d=0.4",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(
        command, capture_output=True, text=True, check=False, encoding="utf-8", errors="replace"
    )
    output = proc.stderr or ""

    started_at = None
    duration = 0.0
    for line in output.splitlines():
        start_match = _FREEZE_START.search(line)
        if start_match:
            started_at = float(start_match.group(1))
        duration_match = _FREEZE_DURATION.search(line)
        if duration_match and started_at is not None and started_at <= 0.06:
            duration = max(duration, float(duration_match.group(1)))
    return duration
