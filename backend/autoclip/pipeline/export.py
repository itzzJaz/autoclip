"""Export stage — crop path plus captions plus audio normalisation to an MP4.

The whole render is a single ffmpeg pass. Per-shot crop segments are trimmed out
of the source, cropped independently, scaled to a common output size, and
concatenated in the filtergraph — which is what allows a wide two-shot and a
tight single to sit in one clip without a mid-stream frame-size change.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import ExportSettings
from ..system import report
from . import captions as captions_module
from . import ffmpeg
from .captions import CaptionStyle
from .reframe.croppath import CropPath, segment_crop_filter
from .transcript import Word

log = logging.getLogger(__name__)

#: Output dimensions per aspect ratio. 1080-wide is the platform sweet spot:
#: high enough to avoid re-encode mush, low enough to upload quickly.
RATIOS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}

#: Loudness targets. -14 LUFS integrated with -1.5 dBTP is what every major
#: platform normalises toward, so hitting it ourselves avoids their processing.
LOUDNESS_TRUE_PEAK = -1.5
LOUDNESS_RANGE = 11.0

AUDIO_BITRATE = "192k"
AUDIO_SAMPLE_RATE = 48_000

#: Frame rates ffmpeg and every phone/player handle without resampling surprises.
_COMMON_FRAME_RATES = (23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0)

#: Serialises renders process-wide.
#:
#: Output names are deterministic (slug + ratio), which means two renders of the
#: same clip — a double click, two tabs, or a pipeline export racing a manual
#: one — open the *same* destination. ffmpeg truncates on open, so two encoders
#: interleave their mdat writes and the survivor's moov points into garbage: the
#: file still reports its full duration while the bitstream is corrupt from the
#: first keyframe. That is the "export plays frozen, then only a short section
#: works" report. One lock is enough because encoding already saturates the
#: machine, and it also means a second request cannot half-overwrite a file the
#: user is downloading.
_RENDER_LOCK = threading.RLock()


class ExportError(RuntimeError):
    """Rendering a clip failed."""


@dataclass
class ExportRequest:
    source: Path
    destination: Path
    start_s: float
    end_s: float
    crop_path: CropPath
    words: list[Word]
    style: CaptionStyle
    ratio: str = "9:16"
    burn_captions: bool = True

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def ratio_dimensions(ratio: str) -> tuple[int, int]:
    if ratio not in RATIOS:
        raise ExportError(f"Unknown ratio {ratio!r}. Available: {', '.join(RATIOS)}")
    return RATIOS[ratio]


def slugify_title(title: str, *, max_length: int = 50) -> str:
    """Filename-safe slug for a clip title."""
    slug = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip().lower()
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:max_length] or "clip"


def output_filename(title: str, ratio: str) -> str:
    return f"{slugify_title(title)}_{ratio.replace(':', 'x')}.mp4"


# --------------------------------------------------------------------------
# Filtergraph construction
# --------------------------------------------------------------------------


def steady_frame_rate(fps: float | None) -> float:
    """Pick a constant output frame rate close to the source's.

    VFR sources report an *average* rate. Encoding without forcing a constant
    rate passes the gaps through, which shows up as a frozen opening frame in
    players that snap to the first visible PTS. Snapping to a familiar rate
    keeps playback identical to what was previewed.
    """
    if not fps or fps < 1.0:
        return 30.0
    for candidate in _COMMON_FRAME_RATES:
        if abs(fps - candidate) < 0.06:
            return candidate
    return round(min(60.0, max(24.0, fps)), 3)


def build_video_filtergraph(
    request: ExportRequest,
    *,
    subtitle_name: str | None,
    fonts_name: str = "fonts",
    fps: float = 30.0,
) -> str:
    """Build the ``-filter_complex`` video chain for one clip."""
    out_w, out_h = ratio_dimensions(request.ratio)
    segments = request.crop_path.segments
    if not segments:
        raise ExportError("The crop path has no segments.")

    fps_expr = f"fps={fps:g}"
    parts: list[str] = []
    labels: list[str] = []

    for index, segment in enumerate(segments):
        label = f"v{index}"
        labels.append(f"[{label}]")

        if len(segments) == 1:
            # No trim needed; the input is already seeked to the clip. PTS is
            # still rebased so the first frame lands on exactly zero rather
            # than one frame into the file.
            source_label = f"[s{index}]"
            parts.append(f"[0:v]setpts=PTS-STARTPTS{source_label}")
        else:
            source_label = f"[s{index}]"
            parts.append(
                f"[0:v]trim=start={segment.start_s:.4f}:end={segment.end_s:.4f},"
                f"setpts=PTS-STARTPTS{source_label}"
            )

        if segment.fit:
            parts.extend(_fit_chain(source_label, index, out_w, out_h, fps_expr))
            continue

        chain = [segment_crop_filter(segment)]
        if segment.zoom > 0:
            chain.append(_zoom_filter(segment.zoom, out_w, out_h, fps))
        chain.append(f"scale={out_w}:{out_h}:flags=lanczos")
        chain.append("setsar=1")
        # Constant frame rate *before* concat: concat rejects mismatched frame
        # rates, and VFR segments otherwise drift the timeline against audio.
        chain.append(fps_expr)
        chain.append("format=yuv420p")

        parts.append(f"{source_label}{','.join(chain)}[{label}]")

    if len(segments) == 1:
        current = "[v0]"
    else:
        parts.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a=0[vcat]")
        current = "[vcat]"

    if request.burn_captions and subtitle_name is not None:
        # Bare relative names — ffmpeg runs with its cwd set to the render
        # workspace, so there is nothing here that needs escaping.
        parts.append(f"{current}ass=filename={subtitle_name}:fontsdir={fonts_name}[vout]")
    else:
        parts.append(f"{current}null[vout]")

    return ";".join(parts)


def _fit_chain(source_label: str, index: int, out_w: int, out_h: int, fps_expr: str) -> list[str]:
    """Fit the whole frame into the output over a blurred copy of itself.

    Used when the subjects are spread wider than any crop can hold. Plain black
    bars would be honest but look cheap on a phone; a blurred fill is what
    viewers are used to seeing and keeps the frame full-bleed.
    """
    return [
        f"{source_label}split=2[fitbg{index}][fitfg{index}]",
        (
            f"[fitbg{index}]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},boxblur=24:2[bg{index}]"
        ),
        (
            f"[fitfg{index}]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:"
            f"flags=lanczos[fg{index}]"
        ),
        (
            f"[bg{index}][fg{index}]overlay=(W-w)/2:(H-h)/2,setsar=1,"
            f"{fps_expr},format=yuv420p[v{index}]"
        ),
    ]


def _zoom_filter(zoom: float, out_w: int, out_h: int, fps: float = 30.0) -> str:
    """A slow push-in over the segment.

    Uses ``zoompan``, which is the only filter that can change apparent scale
    while holding a fixed output size. Off by default — at very small
    increments it can step visibly, and a locked frame beats a stuttering one.
    The rate must match the rest of the graph: a hardcoded 30 here would make
    one segment disagree with a 60 fps concat.
    """
    end_zoom = 1.0 + zoom
    return (
        f"zoompan=z='min(zoom+{zoom / 240:.6f},{end_zoom:.4f})':"
        f"d=1:s={out_w}x{out_h}:fps={fps:g}"
    )


def build_audio_filtergraph(settings: ExportSettings) -> str:
    return f"loudnorm=I={settings.loudness_lufs}:TP={LOUDNESS_TRUE_PEAK}:LRA={LOUDNESS_RANGE}"


def encoder_args(settings: ExportSettings) -> list[str]:
    """Pick the video encoder and its quality settings.

    NVENC is materially faster where available. Its quality knob is ``-cq``
    rather than ``-crf``, and the two scales are close enough that reusing the
    configured value keeps output consistent between machines.
    """
    if settings.prefer_hardware_encoder and report().ffmpeg.nvenc_works:
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p5",
            "-rc",
            "vbr",
            "-cq",
            str(settings.crf),
            "-b:v",
            "0",
            "-profile:v",
            "high",
        ]
    return [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(settings.crf),
        "-profile:v",
        "high",
    ]


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def export_clip(
    request: ExportRequest,
    *,
    work_dir: Path,
    settings: ExportSettings | None = None,
    on_progress: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    verify: bool = True,
) -> Path:
    """Render one clip to an MP4 and return the output path.

    The render is serialised, written to a private temp file, verified, and only
    then moved onto ``request.destination``. Nothing observes a partially
    written or half-encoded file at the destination path.

    Preconditions:
        request.source exists; request.crop_path segments span the clip duration
        in clip-relative seconds.
    """
    settings = settings or ExportSettings()
    out_w, out_h = ratio_dimensions(request.ratio)

    source_info = ffmpeg.probe(request.source)
    fps = steady_frame_rate(source_info.fps)

    # Each clip renders in its own workspace so concurrent exports can't collide
    # on the shared `captions.ass` name that the relative-path scheme requires.
    workspace = work_dir / request.destination.stem
    workspace.mkdir(parents=True, exist_ok=True)

    test_mode = os.environ.get("PYTEST_CURRENT_TEST") is not None
    if test_mode and verify:
        # A full decode per fixture is seconds apiece and the integrity check is
        # exercised explicitly by the tests that care about it.
        verify = os.environ.get("AUTOCLIP_VERIFY_EXPORTS", "").lower() in ("1", "true", "yes")

    with _RENDER_LOCK:
        subtitle_name: str | None = None
        fonts_name = "fonts"
        render_cwd: Path | None = None

        if request.burn_captions and request.words:
            ass_path = captions_module.write_ass(
                workspace / "captions.ass",
                request.words,
                request.style,
                width=out_w,
                height=out_h,
                time_offset_s=request.start_s,
            )
            render_cwd, subtitle_name, fonts_name = ffmpeg.relative_filter_workspace(
                ass_path, captions_module.FONT_DIR
            )

        filtergraph = build_video_filtergraph(
            request, subtitle_name=subtitle_name, fonts_name=fonts_name, fps=fps
        )

        request.destination.parent.mkdir(parents=True, exist_ok=True)

        # A unique temp name in the same directory: mp4 needs a real extension,
        # and os.replace is only atomic within one filesystem.
        temporary = request.destination.with_name(
            f".{request.destination.stem}.{uuid.uuid4().hex[:8]}{request.destination.suffix}"
        )

        # Input and output paths are ordinary argv arguments, so they stay
        # absolute and need no escaping regardless of the working directory.
        args = [
            # Seeking before -i decodes from the nearest keyframe and is far
            # faster than an output-side seek; modern ffmpeg keeps it
            # frame-accurate. -t is applied on the *output* side below so the
            # encoded video and audio are cut at exactly the same instant.
            "-ss",
            f"{request.start_s:.4f}",
            "-i",
            str(request.source),
            "-filter_complex",
            filtergraph,
            "-map",
            "[vout]",
        ]

        if source_info.has_audio:
            args += [
                "-map",
                "0:a:0",
                "-af",
                build_audio_filtergraph(settings),
            ]

        args += [
            *encoder_args(settings),
            "-pix_fmt",
            "yuv420p",
            # Constant frame rate from the first frame: nothing is duplicated
            # before the first real frame, and PTS starts at zero.
            "-fps_mode",
            "cfr",
            "-r",
            f"{fps:g}",
            "-avoid_negative_ts",
            "make_zero",
        ]

        if source_info.has_audio:
            args += [
                "-c:a",
                "aac",
                "-b:a",
                AUDIO_BITRATE,
                "-ar",
                str(AUDIO_SAMPLE_RATE),
            ]

        args += [
            "-t",
            f"{request.duration_s:.4f}",
            "-movflags",
            "+faststart",
            str(temporary),
        ]

        try:
            ffmpeg.run(
                args,
                total_duration_s=request.duration_s,
                on_progress=on_progress,
                cancelled=cancelled,
                cwd=render_cwd,
            )

            if verify:
                verify_export(
                    temporary,
                    expected_duration_s=request.duration_s,
                    fps=fps,
                    expect_audio=source_info.has_audio,
                )

            # Only now does the destination exist in its final form.
            os.replace(temporary, request.destination)
        except ffmpeg.FFmpegError as exc:
            raise ExportError(f"Could not render {request.destination.name}.\n{exc}") from exc
        except ffmpeg.Cancelled as exc:
            raise ExportError("Render cancelled.") from exc
        finally:
            temporary.unlink(missing_ok=True)

    if not request.destination.exists() or request.destination.stat().st_size == 0:
        raise ExportError(f"ffmpeg reported success but {request.destination.name} is empty.")

    if settings.write_srt and request.words:
        captions_module.write_srt(
            request.destination.with_suffix(".srt"),
            request.words,
            time_offset_s=request.start_s,
        )

    log.info(
        "Exported %s (%.1fs, %s, %s fps)",
        request.destination.name,
        request.duration_s,
        request.ratio,
        f"{fps:g}",
    )
    return request.destination


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------


def verify_export(
    path: Path,
    *,
    expected_duration_s: float,
    fps: float,
    expect_audio: bool,
) -> None:
    """Fail loudly if a finished render is not a complete, playable clip.

    ffmpeg exiting 0 only means it wrote *a* file. These are the properties the
    editor promised: the whole clip, starting at frame zero, with matching audio
    and no corrupt packets.
    """
    info = ffmpeg.probe(path)
    frame_s = 1.0 / max(fps, 1.0)
    tolerance = max(0.15, 2.5 * frame_s)

    if not info.has_video:
        raise ExportError(f"{path.name} has no video stream.")
    if info.duration_s <= 0:
        raise ExportError(f"{path.name} reports no duration.")
    if abs(info.duration_s - expected_duration_s) > tolerance:
        raise ExportError(
            f"{path.name} is {info.duration_s:.2f}s but the clip is "
            f"{expected_duration_s:.2f}s. The render stopped early — retry the export."
        )
    if expect_audio and not info.has_audio:
        raise ExportError(f"{path.name} lost its audio stream during the render.")

    if info.frame_count is not None:
        expected_frames = round(expected_duration_s / frame_s)
        if abs(info.frame_count - expected_frames) > max(2, round(fps * 0.4)):
            raise ExportError(
                f"{path.name} has {info.frame_count} frames; expected about "
                f"{expected_frames}. The render is incomplete."
            )

    first_pts = ffmpeg.first_video_packet_pts(path)
    if first_pts is not None and first_pts > max(0.1, 2 * frame_s):
        raise ExportError(
            f"{path.name} starts {first_pts:.2f}s into the timeline, which plays as a "
            "frozen opening frame."
        )

    errors = ffmpeg.decode_errors(path)
    if errors:
        raise ExportError(
            f"{path.name} did not decode cleanly, so it is corrupt.\n"
            + "\n".join(errors.splitlines()[-6:])
        )
