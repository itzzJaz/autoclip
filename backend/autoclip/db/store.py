"""CRUD operations over the AutoClip database.

Every function opens its own transaction via :func:`autoclip.db.connection`,
so callers don't manage commits. Functions are synchronous; async callers should
wrap them in ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
from typing import Any

from . import connection
from .models import (
    Clip,
    ClipEdit,
    ClipStatus,
    Export,
    Job,
    JobStatus,
    Privacy,
    PublishJob,
    PublishStatus,
    Source,
    Transcript,
    utcnow,
)

# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------


def create_source(source: Source) -> Source:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO sources (id, type, url, filename, path, title, channel,
                                 duration_s, width, height, fps, has_audio,
                                 has_video, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.id,
                source.type,
                source.url,
                source.filename,
                source.path,
                source.title,
                source.channel,
                source.duration_s,
                source.width,
                source.height,
                source.fps,
                int(source.has_audio),
                int(source.has_video),
                source.created_at,
            ),
        )
    return source


def get_source(source_id: str) -> Source | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return Source.from_row(row) if row else None


def list_sources(limit: int = 50) -> list[Source]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM sources ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [Source.from_row(r) for r in rows]


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------


def create_job(job: Job) -> Job:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, source_id, status, current_stage, progress, error,
                              provider, settings_json, created_at, updated_at,
                              started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.source_id,
                job.status,
                job.current_stage,
                job.progress,
                job.error,
                job.provider,
                json.dumps(job.settings),
                job.created_at,
                job.updated_at,
                job.started_at,
                job.finished_at,
            ),
        )
    return job


def get_job(job_id: str) -> Job | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return Job.from_row(row) if row else None


def list_jobs(limit: int = 50, status: JobStatus | None = None) -> list[Job]:
    query = "SELECT * FROM jobs"
    params: list[Any] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [Job.from_row(r) for r in rows]


class _Unset:
    """Sentinel distinguishing "leave this alone" from "set this to NULL".

    Without it, nullable columns can only ever be written, never cleared — a
    retried job would keep displaying the error message from its failed run.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNSET"


UNSET = _Unset()


def update_job(
    job_id: str,
    *,
    status: JobStatus | None = None,
    current_stage: str | None = None,
    progress: float | None = None,
    error: str | None | _Unset = UNSET,
    started_at: str | None | _Unset = UNSET,
    finished_at: str | None | _Unset = UNSET,
) -> None:
    """Patch the supplied fields. Omitted fields are left untouched.

    Nullable fields take :data:`UNSET` as their default, so passing ``None``
    explicitly clears them.

    ``updated_at`` is always refreshed so the UI can detect staleness.
    """
    fields: dict[str, Any] = {"updated_at": utcnow()}
    for name, value in (
        ("status", status),
        ("current_stage", current_stage),
        ("progress", progress),
    ):
        if value is not None:
            fields[name] = value

    for name, value in (
        ("error", error),
        ("started_at", started_at),
        ("finished_at", finished_at),
    ):
        if not isinstance(value, _Unset):
            fields[name] = value

    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connection() as conn:
        conn.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?",
            (*fields.values(), job_id),
        )


def next_queued_job() -> Job | None:
    """Return the oldest queued job — the FIFO the worker pulls from."""
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
    return Job.from_row(row) if row else None


# --------------------------------------------------------------------------
# Transcripts
# --------------------------------------------------------------------------


def upsert_transcript(transcript: Transcript) -> Transcript:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO transcripts (job_id, json_path, language, model,
                                     has_diarization, word_count, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                json_path = excluded.json_path,
                language = excluded.language,
                model = excluded.model,
                has_diarization = excluded.has_diarization,
                word_count = excluded.word_count,
                source = excluded.source
            """,
            (
                transcript.job_id,
                transcript.json_path,
                transcript.language,
                transcript.model,
                int(transcript.has_diarization),
                transcript.word_count,
                transcript.source,
                transcript.created_at,
            ),
        )
    return transcript


def get_transcript(job_id: str) -> Transcript | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM transcripts WHERE job_id = ?", (job_id,)).fetchone()
    return Transcript.from_row(row) if row else None


# --------------------------------------------------------------------------
# Clips
# --------------------------------------------------------------------------


def replace_clips(job_id: str, clips: list[Clip]) -> list[Clip]:
    """Swap in a fresh set of clips for a job.

    Used when highlight detection reruns — a retry should not leave the previous
    run's candidates behind.
    """
    with connection() as conn:
        conn.execute("DELETE FROM clips WHERE job_id = ?", (job_id,))
        conn.executemany(
            """
            INSERT INTO clips (id, job_id, rank, start_s, end_s, start_word, end_word,
                               title, hook, score, reason, status, user_trimmed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    c.id,
                    c.job_id,
                    c.rank,
                    c.start_s,
                    c.end_s,
                    c.start_word,
                    c.end_word,
                    c.title,
                    c.hook,
                    c.score,
                    c.reason,
                    c.status,
                    int(c.user_trimmed),
                    c.created_at,
                )
                for c in clips
            ],
        )
    return clips


def create_clip(clip: Clip) -> Clip:
    """Persist one user-created clip."""
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO clips (id, job_id, rank, start_s, end_s, start_word, end_word,
                               title, hook, score, reason, status, user_trimmed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip.id,
                clip.job_id,
                clip.rank,
                clip.start_s,
                clip.end_s,
                clip.start_word,
                clip.end_word,
                clip.title,
                clip.hook,
                clip.score,
                clip.reason,
                clip.status,
                int(clip.user_trimmed),
                clip.created_at,
            ),
        )
    return clip


def get_clip(clip_id: str) -> Clip | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return Clip.from_row(row) if row else None


def list_clips(job_id: str) -> list[Clip]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM clips WHERE job_id = ? ORDER BY rank ASC", (job_id,)
        ).fetchall()
    return [Clip.from_row(r) for r in rows]


def update_clip(
    clip_id: str,
    *,
    start_s: float | None = None,
    end_s: float | None = None,
    start_word: int | None = None,
    end_word: int | None = None,
    title: str | None = None,
    status: ClipStatus | None = None,
    user_trimmed: bool | None = None,
) -> None:
    fields: dict[str, Any] = {}
    for name, value in (
        ("start_s", start_s),
        ("end_s", end_s),
        ("start_word", start_word),
        ("end_word", end_word),
        ("title", title),
        ("status", status),
    ):
        if value is not None:
            fields[name] = value
    if user_trimmed is not None:
        fields["user_trimmed"] = int(user_trimmed)

    if not fields:
        return

    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connection() as conn:
        conn.execute(
            f"UPDATE clips SET {assignments} WHERE id = ?",
            (*fields.values(), clip_id),
        )


# --------------------------------------------------------------------------
# Clip edits
# --------------------------------------------------------------------------


def upsert_clip_edit(edit: ClipEdit) -> ClipEdit:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO clip_edits (clip_id, edited_words_json, caption_style, ratio,
                                    caption_scale, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(clip_id) DO UPDATE SET
                edited_words_json = excluded.edited_words_json,
                caption_style = excluded.caption_style,
                ratio = excluded.ratio,
                caption_scale = excluded.caption_scale,
                updated_at = excluded.updated_at
            """,
            (
                edit.clip_id,
                json.dumps(edit.edited_words) if edit.edited_words is not None else None,
                edit.caption_style,
                edit.ratio,
                edit.caption_scale,
                utcnow(),
            ),
        )
    return edit


def get_clip_edit(clip_id: str) -> ClipEdit | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM clip_edits WHERE clip_id = ?", (clip_id,)).fetchone()
    return ClipEdit.from_row(row) if row else None


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------


def create_export(export: Export) -> Export:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO exports (id, clip_id, path, ratio, style, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                export.id,
                export.clip_id,
                export.path,
                export.ratio,
                export.style,
                export.size_bytes,
                export.created_at,
            ),
        )
    return export


def get_export(export_id: str) -> Export | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM exports WHERE id = ?", (export_id,)).fetchone()
    return Export.from_row(row) if row else None


def list_exports(clip_id: str) -> list[Export]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM exports WHERE clip_id = ? AND size_bytes > 0 "
            "ORDER BY created_at DESC",
            (clip_id,),
        ).fetchall()
    return [Export.from_row(r) for r in rows]


def list_all_exports(limit: int = 100) -> list[Export]:
    """Every export, newest first — the export-history feed."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM exports WHERE size_bytes > 0 ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [Export.from_row(r) for r in rows]


def update_export_size(export_id: str, size_bytes: int) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE exports SET size_bytes = ? WHERE id = ?",
            (size_bytes, export_id),
        )


# --------------------------------------------------------------------------
# Publishing
# --------------------------------------------------------------------------


def create_publish_job(job: PublishJob) -> PublishJob:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO publish_jobs (id, export_id, title, description,
                                      hashtags_json, tags_json, privacy, status,
                                      progress, video_id, url, error, attempts,
                                      thumbnail_path, created_at, updated_at,
                                      published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.export_id,
                job.title,
                job.description,
                json.dumps(job.hashtags),
                json.dumps(job.tags),
                job.privacy,
                job.status,
                job.progress,
                job.video_id,
                job.url,
                job.error,
                job.attempts,
                job.thumbnail_path,
                job.created_at,
                job.updated_at,
                job.published_at,
            ),
        )
    return job


def get_publish_job(job_id: str) -> PublishJob | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM publish_jobs WHERE id = ?", (job_id,)).fetchone()
    return PublishJob.from_row(row) if row else None


def get_publish_job_for_export(export_id: str) -> PublishJob | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM publish_jobs WHERE export_id = ?", (export_id,)
        ).fetchone()
    return PublishJob.from_row(row) if row else None


def list_publish_jobs(limit: int = 100) -> list[PublishJob]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM publish_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [PublishJob.from_row(r) for r in rows]


def next_pending_publish_job() -> PublishJob | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM publish_jobs "
            "WHERE status = 'pending' OR (status = 'processing' AND video_id IS NOT NULL) "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
    return PublishJob.from_row(row) if row else None


def update_publish_job(
    job_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    hashtags: list[str] | None = None,
    tags: list[str] | None = None,
    privacy: Privacy | None = None,
    status: PublishStatus | None = None,
    progress: float | None = None,
    video_id: str | None = None,
    url: str | None = None,
    error: str | None | _Unset = UNSET,
    attempts: int | None = None,
    thumbnail_path: str | None = None,
    published_at: str | None | _Unset = UNSET,
) -> None:
    fields: dict[str, Any] = {"updated_at": utcnow()}
    for name, value in (
        ("title", title),
        ("description", description),
        ("privacy", privacy),
        ("status", status),
        ("progress", progress),
        ("video_id", video_id),
        ("url", url),
        ("attempts", attempts),
        ("thumbnail_path", thumbnail_path),
    ):
        if value is not None:
            fields[name] = value
    if hashtags is not None:
        fields["hashtags_json"] = json.dumps(hashtags)
    if tags is not None:
        fields["tags_json"] = json.dumps(tags)
    for name, value in (("error", error), ("published_at", published_at)):
        if not isinstance(value, _Unset):
            fields[name] = value

    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connection() as conn:
        conn.execute(
            f"UPDATE publish_jobs SET {assignments} WHERE id = ?",
            (*fields.values(), job_id),
        )


def delete_publish_job(job_id: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM publish_jobs WHERE id = ?", (job_id,))


# Instagram jobs

def create_instagram_job(job: Any) -> Any:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO instagram_jobs (
                id, export_id, caption, status, container_id, media_id, url, error,
                created_at, updated_at, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.export_id,
                job.caption,
                job.status,
                job.container_id,
                job.media_id,
                job.url,
                job.error,
                job.created_at,
                job.updated_at,
                job.published_at,
            ),
        )
    return job


def get_instagram_job_for_export(export_id: str) -> Any | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM instagram_jobs WHERE export_id = ?", (export_id,)
        ).fetchone()
    if not row:
        return None
    from .models import InstagramJob
    return InstagramJob.from_row(row)


def get_instagram_job(job_id: str) -> Any | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM instagram_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    if not row:
        return None
    from .models import InstagramJob
    return InstagramJob.from_row(row)


def list_instagram_jobs(limit: int = 100) -> list[Any]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM instagram_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    from .models import InstagramJob
    return [InstagramJob.from_row(row) for row in rows]


def update_instagram_job(
    job_id: str,
    *,
    caption: str | None = None,
    status: str | None = None,
    container_id: str | None = None,
    media_id: str | None = None,
    url: str | None = None,
    error: str | None | _Unset = UNSET,
    published_at: str | None | _Unset = UNSET,
) -> None:
    fields: dict[str, Any] = {"updated_at": utcnow()}
    for name, value in (
        ("caption", caption),
        ("status", status),
        ("container_id", container_id),
        ("media_id", media_id),
        ("url", url),
    ):
        if value is not None:
            fields[name] = value
    for name, value in (("error", error), ("published_at", published_at)):
        if not isinstance(value, _Unset):
            fields[name] = value
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connection() as conn:
        conn.execute(
            f"UPDATE instagram_jobs SET {assignments} WHERE id = ?",
            (*fields.values(), job_id),
        )
