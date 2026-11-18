"""Engine lifecycle — the Start / Stop switch in the header.

"Engine" means the local processing service: ffmpeg is present, the Whisper
model is loaded, and the job worker is allowed to pull work. It deliberately
does *not* mean the web server — the UI stays up while the engine is stopped so
the user can still review, export history, and manage uploads.

The state machine is small on purpose. A transition that cannot be honoured
(stopping while a render is running without an explicit force) is refused rather
than faked, because a header that says "Stopped" while a job is still encoding
is worse than one that says "Still running".
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from . import model_cache, system
from .config import load as load_settings

log = logging.getLogger(__name__)


class EngineState:
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class EngineError(RuntimeError):
    """The engine could not make the requested transition."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


class EngineBusy(EngineError):
    """A competing request, or active work that would be interrupted."""


@dataclass
class EngineStatus:
    state: str
    error: str | None = None
    model: str = ""
    model_loaded: str | None = None
    started_at: str | None = None
    active_job_id: str | None = None
    queued: int = 0
    ffmpeg_version: str | None = None
    ready: bool = False


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Engine:
    """Thread-safe owner of the engine state and its loaded models."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = EngineState.STOPPED
        self._error: str | None = None
        self._started_at: str | None = None

    # -- introspection -----------------------------------------------------

    def is_running(self) -> bool:
        with self._lock:
            return self._state == EngineState.RUNNING

    def status(self) -> EngineStatus:
        with self._lock:
            state = self._state
            error = self._error
            started_at = self._started_at

        settings = load_settings()
        report = system.report()
        active_job_id: str | None = None
        queued = 0
        try:
            # Imported here: the queue imports the pipeline, which is heavy and
            # would make this module part of the app-import cycle.
            from .jobs.queue import queue

            status = queue.status()
            active_job_id = status.running_job_id
            queued = status.queued
        except Exception:  # pragma: no cover - queue is always importable in app
            pass

        return EngineStatus(
            state=state,
            error=error,
            model=settings.whisper.model,
            model_loaded=model_cache.loaded_whisper(),
            started_at=started_at,
            active_job_id=active_job_id,
            queued=queued,
            ffmpeg_version=report.ffmpeg.version,
            ready=report.ffmpeg.usable,
        )

    # -- transitions -------------------------------------------------------

    def start(self, *, preload: bool = True) -> EngineStatus:
        """Start the engine, optionally loading the configured Whisper model.

        ``preload=False`` is used on boot: the app should be usable immediately,
        and a model download has no business blocking startup. An explicit Start
        from the UI preloads, which is what makes the button's "Starting" state
        and the Stop button's unloading real rather than cosmetic.
        """
        with self._lock:
            if self._state in (EngineState.STARTING, EngineState.STOPPING):
                raise EngineBusy(
                    f"The engine is already {self._state}.",
                    hint="Wait for the current transition to finish.",
                )
            if self._state == EngineState.RUNNING:
                raise EngineBusy(
                    "The engine is already running.",
                    hint="Stop it first if you want to reload the model.",
                )
            self._state = EngineState.STARTING
            self._error = None

        try:
            report = system.refresh()
            if not report.ffmpeg.usable:
                missing = ", ".join(report.ffmpeg.missing_filters) or "libass/libx264"
                raise EngineError(
                    "ffmpeg cannot render captioned video on this machine.",
                    hint=(
                        f"Missing: {missing}. On macOS install `ffmpeg-full` with "
                        "`brew install ffmpeg-full`; on Linux install a build with libass."
                    ),
                )

            if preload:
                self._load_model()
        except EngineError as exc:
            with self._lock:
                self._state = EngineState.ERROR
                self._error = str(exc)
            log.error("Engine failed to start: %s", exc)
            raise
        except Exception as exc:
            with self._lock:
                self._state = EngineState.ERROR
                self._error = f"Could not start the engine: {exc}"
            log.exception("Engine failed to start.")
            raise EngineError(f"Could not start the engine: {exc}") from exc

        with self._lock:
            self._state = EngineState.RUNNING
            self._started_at = _now()
            self._error = None
        log.info("Engine running.")
        self._wake_worker()
        return self.status()

    def stop(self, *, force: bool = False) -> EngineStatus:
        """Stop the engine and unload its models.

        A running job is only cancelled when ``force`` is set. Without it the
        request is refused so a stray click cannot destroy a render that is
        nearly finished.
        """
        with self._lock:
            if self._state in (EngineState.STARTING, EngineState.STOPPING):
                raise EngineBusy(
                    f"The engine is already {self._state}.",
                    hint="Wait for the current transition to finish.",
                )
            if self._state == EngineState.STOPPED and model_cache.loaded_whisper() is None:
                raise EngineBusy(
                    "The engine is already stopped.",
                    hint="Start it to process another video.",
                )

            active_job_id: str | None = None
            try:
                from .jobs.queue import queue

                active_job_id = queue.status().running_job_id
            except Exception:  # pragma: no cover
                pass

            if active_job_id and not force:
                raise EngineBusy(
                    "A video is being processed right now.",
                    hint=(
                        "Stopping would cancel it. Let it finish, or stop the engine "
                        "with force to cancel the job."
                    ),
                )

            self._state = EngineState.STOPPING

        try:
            if active_job_id and force:
                from .jobs.queue import queue

                queue.cancel(active_job_id)
                log.info("Cancelling job %s so the engine can stop.", active_job_id)

            freed = model_cache.clear()
            with self._lock:
                self._state = EngineState.STOPPED
                self._started_at = None
                self._error = None
            log.info("Engine stopped%s.", f" (unloaded {', '.join(freed)})" if freed else "")
            return self.status()
        except Exception as exc:
            with self._lock:
                self._state = EngineState.ERROR
                self._error = f"Could not stop the engine cleanly: {exc}"
            raise EngineError(f"Could not stop the engine cleanly: {exc}") from exc

    # -- helpers -----------------------------------------------------------

    def _load_model(self) -> None:
        settings = load_settings()

        # Imported late: transcribe imports faster-whisper, which is slow to
        # import and pulls in CTranslate2's CUDA discovery.
        from .pipeline.transcribe import _model_load_error, resolve_compute

        device, compute_type = resolve_compute(settings.whisper)
        try:
            model_cache.get_whisper_model(settings.whisper.model, device, compute_type)
        except Exception as exc:
            raise _model_load_error(exc, device, compute_type) from exc

    def _wake_worker(self) -> None:
        try:
            from .jobs.queue import queue

            queue.notify()
        except Exception:  # pragma: no cover
            pass


#: Process-wide engine.
engine = Engine()
