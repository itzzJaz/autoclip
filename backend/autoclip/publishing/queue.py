"""Background YouTube upload queue.

Uploads are sequential and durable. The queue row is the source of truth, so a
crash mid-upload is recoverable: an upload with no video id goes back to
``pending`` and resumes from Google's acknowledged byte offset, while one that
already has a video id goes back to ``processing`` and is polled rather than
uploaded again.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path

from ..db import store
from ..db.models import PublishJob, utcnow
from . import oauth, thumbnail, youtube
from .validation import validate_export

log = logging.getLogger(__name__)

POLL_INTERVAL_S = float(os.environ.get("AUTOCLIP_PUBLISH_POLL_S", "15"))
POLL_ATTEMPTS = int(os.environ.get("AUTOCLIP_PUBLISH_POLL_ATTEMPTS", "20"))


class PublishQueue:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._wakeup: asyncio.Event | None = None
        self._stopping = False

    async def start(self) -> None:
        self._reset_interrupted()
        self._stopping = False
        self._wakeup = asyncio.Event()
        self._task = asyncio.create_task(self._worker(), name="autoclip-publish-queue")
        self.notify()

    async def stop(self) -> None:
        self._stopping = True
        self.notify()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._wakeup = None

    def notify(self) -> None:
        if self._wakeup is not None:
            self._wakeup.set()

    def _reset_interrupted(self) -> None:
        for job in store.list_publish_jobs(limit=200):
            if job.status not in ("uploading", "processing"):
                continue
            if job.video_id:
                store.update_publish_job(
                    job.id,
                    status="processing",
                    error=(
                        "AutoClip restarted while YouTube was still processing this video. "
                        "It is being checked again."
                    ),
                )
            else:
                store.update_publish_job(
                    job.id,
                    status="pending",
                    progress=0.0,
                    error=None,
                )

    async def _worker(self) -> None:
        wakeup = self._wakeup
        assert wakeup is not None

        while not self._stopping:
            job = await asyncio.to_thread(store.next_pending_publish_job)
            if job is None:
                wakeup.clear()
                await wakeup.wait()
                continue
            await self._run_one(job)

    async def _run_one(self, job: PublishJob) -> None:
        export = await asyncio.to_thread(store.get_export, job.export_id)
        if export is None:
            await asyncio.to_thread(
                store.update_publish_job,
                job.id,
                status="failed",
                error="The export record no longer exists.",
            )
            return

        path = Path(export.path)
        report = await asyncio.to_thread(validate_export, path, cache_key=job.export_id)
        if report.errors:
            detail = "\n".join(f"• {check.label}: {check.detail}" for check in report.errors)
            await asyncio.to_thread(
                store.update_publish_job,
                job.id,
                status="failed",
                error=f"This file is not ready to publish:\n{detail}",
            )
            return

        if job.video_id:
            await self._watch_processing(job)
            return

        try:
            await asyncio.to_thread(oauth.access_token)
        except oauth.OAuthError as exc:
            await asyncio.to_thread(
                store.update_publish_job,
                job.id,
                status="failed",
                error=f"{exc}\n\n{exc.hint}",
            )
            return

        await asyncio.to_thread(
            store.update_publish_job,
            job.id,
            status="uploading",
            progress=0.0,
            error=None,
            attempts=job.attempts + 1,
        )

        last_reported = -1.0

        def on_progress(fraction: float) -> None:
            nonlocal last_reported
            if fraction < 1.0 and fraction - last_reported < 0.02:
                return
            last_reported = fraction
            try:
                store.update_publish_job(job.id, progress=max(0.0, min(1.0, fraction)))
            except Exception:  # pragma: no cover - progress must never break upload
                log.debug("Could not persist upload progress.", exc_info=True)

        try:
            payload = await asyncio.to_thread(
                youtube.upload_video,
                path,
                title=job.title,
                description=job.description,
                tags=job.tags,
                privacy=job.privacy,
                on_progress=on_progress,
            )
        except youtube.YouTubeError as exc:
            await asyncio.to_thread(
                store.update_publish_job,
                job.id,
                status="failed",
                error=str(exc) + (f"\n\n{exc.hint}" if exc.hint else ""),
            )
            return
        except Exception as exc:  # noqa: BLE001 - one bad upload must not stop the queue
            log.exception("Upload failed for %s.", job.id)
            await asyncio.to_thread(
                store.update_publish_job,
                job.id,
                status="failed",
                error=f"Upload failed: {exc}",
            )
            return

        video_id = str(payload.get("id") or "")
        if not video_id:
            await asyncio.to_thread(
                store.update_publish_job,
                job.id,
                status="failed",
                error="YouTube accepted the upload but returned no video id.",
            )
            return

        thumb = await asyncio.to_thread(thumbnail.thumbnail_for, job.export_id, path)
        await asyncio.to_thread(
            store.update_publish_job,
            job.id,
            status="processing",
            progress=1.0,
            video_id=video_id,
            url=youtube.watch_url(video_id),
            thumbnail_path=str(thumb) if thumb else None,
        )

        refreshed = await asyncio.to_thread(store.get_publish_job, job.id)
        if refreshed is not None:
            await self._watch_processing(refreshed)

    async def _watch_processing(self, job: PublishJob) -> None:
        if not job.video_id:
            return

        for attempt in range(POLL_ATTEMPTS):
            try:
                state = await asyncio.to_thread(youtube.processing_status, job.video_id)
            except Exception as exc:  # noqa: BLE001 - transient API/network trouble
                log.warning("Could not poll processing state for %s: %s", job.video_id, exc)
                state = {}

            upload_status = (state.get("upload_status") or "").lower()
            processing = (state.get("processing_status") or "").lower()
            failure = state.get("failure_reason") or state.get("rejection_reason") or ""

            if upload_status == "processed" or processing == "succeeded":
                await asyncio.to_thread(
                    store.update_publish_job,
                    job.id,
                    status="published",
                    progress=1.0,
                    error=None,
                    published_at=utcnow(),
                )
                log.info("Published %s.", job.video_id)
                return

            if upload_status in ("failed", "rejected") or processing == "failed":
                await asyncio.to_thread(
                    store.update_publish_job,
                    job.id,
                    status="failed",
                    error=(
                        "YouTube rejected the video"
                        + (f": {failure}" if failure else ".")
                        + " The uploaded video may still appear in YouTube Studio."
                    ),
                )
                return

            if attempt < POLL_ATTEMPTS - 1:
                await asyncio.sleep(POLL_INTERVAL_S)

        await asyncio.to_thread(
            store.update_publish_job,
            job.id,
            error=(
                "YouTube is still processing this video. It will appear in YouTube Studio "
                "when ready; no further upload is needed."
            ),
        )


publish_queue = PublishQueue()
