"""Pydantic request and response models for the REST API.

Kept separate from the dataclasses in ``db.models``: those mirror SQLite rows,
these are the wire contract. Splitting them means a schema change doesn't
silently reshape the API, and the API can expose derived fields (durations,
export URLs) that don't belong in storage.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..db import models


class SourceOut(BaseModel):
    id: str
    type: str
    title: str
    url: str | None = None
    filename: str | None = None
    channel: str | None = None
    duration_s: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool
    has_video: bool
    created_at: str

    @classmethod
    def of(cls, source: models.Source) -> SourceOut:
        # Built field by field rather than from vars(): the row carries an
        # absolute filesystem path that has no business leaving the process.
        return cls(
            id=source.id,
            type=source.type,
            title=source.title,
            url=source.url,
            filename=source.filename,
            channel=source.channel,
            duration_s=source.duration_s,
            width=source.width,
            height=source.height,
            fps=source.fps,
            has_audio=source.has_audio,
            has_video=source.has_video,
            created_at=source.created_at,
        )


class YouTubeIngestIn(BaseModel):
    url: str
    cookies_from_browser: str | None = None


class JobSettingsIn(BaseModel):
    """Per-job overrides. Anything omitted falls back to saved settings."""

    provider: str | None = None
    whisper_model: str | None = None
    language: str | None = None
    diarization: bool | None = None
    min_duration_s: float | None = Field(default=None, gt=0)
    max_duration_s: float | None = Field(default=None, gt=0)
    max_clips: int | None = Field(default=None, ge=1, le=50)
    caption_style: str | None = None
    ratio: Literal["9:16", "1:1", "16:9"] | None = None


class JobCreateIn(BaseModel):
    source_id: str
    settings: JobSettingsIn = Field(default_factory=JobSettingsIn)


class JobOut(BaseModel):
    id: str
    source_id: str
    status: str
    current_stage: str
    progress: float
    error: str | None = None
    provider: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    source: SourceOut | None = None

    @classmethod
    def of(cls, job: models.Job, source: models.Source | None = None) -> JobOut:
        return cls(
            id=job.id,
            source_id=job.source_id,
            status=job.status,
            current_stage=job.current_stage,
            progress=job.progress,
            error=job.error,
            provider=job.provider,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            source=SourceOut.of(source) if source else None,
        )


class WordOut(BaseModel):
    text: str
    start: float
    end: float
    speaker: str | None = None


class ExportOut(BaseModel):
    id: str
    clip_id: str
    ratio: str
    style: str
    size_bytes: int
    created_at: str
    download_url: str

    @classmethod
    def of(cls, export: models.Export) -> ExportOut:
        return cls(
            id=export.id,
            clip_id=export.clip_id,
            ratio=export.ratio,
            style=export.style,
            size_bytes=export.size_bytes,
            created_at=export.created_at,
            download_url=f"/api/exports/{export.id}/download",
        )


class ClipOut(BaseModel):
    id: str
    job_id: str
    rank: int
    start_s: float
    end_s: float
    duration_s: float
    start_word: int
    end_word: int
    title: str
    hook: str
    score: int
    reason: str
    status: str
    user_trimmed: bool
    caption_style: str = "bold_pop"
    ratio: str = "9:16"
    caption_scale: float = 1.0
    exports: list[ExportOut] = Field(default_factory=list)

    @classmethod
    def of(
        cls,
        clip: models.Clip,
        *,
        edit: models.ClipEdit | None = None,
        exports: list[models.Export] | None = None,
    ) -> ClipOut:
        return cls(
            id=clip.id,
            job_id=clip.job_id,
            rank=clip.rank,
            start_s=clip.start_s,
            end_s=clip.end_s,
            duration_s=clip.duration_s,
            start_word=clip.start_word,
            end_word=clip.end_word,
            title=clip.title,
            hook=clip.hook,
            score=clip.score,
            reason=clip.reason,
            status=clip.status,
            user_trimmed=clip.user_trimmed,
            caption_style=edit.caption_style if edit else "bold_pop",
            ratio=edit.ratio if edit else "9:16",
            caption_scale=edit.caption_scale if edit else 1.0,
            exports=[ExportOut.of(e) for e in (exports or [])],
        )


class ClipPatchIn(BaseModel):
    start_s: float | None = Field(default=None, ge=0)
    end_s: float | None = Field(default=None, gt=0)
    title: str | None = None
    status: Literal["candidate", "kept", "discarded", "exported"] | None = None


class ManualClipIn(BaseModel):
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    title: str = Field(default="Manual clip", max_length=200)


class CaptionPatchIn(BaseModel):
    """Word-level caption edits for one clip."""

    words: list[WordOut] | None = None
    caption_style: str | None = None
    ratio: Literal["9:16", "1:1", "16:9"] | None = None
    caption_scale: float | None = Field(default=None, ge=0.7, le=1.8)


class ExportRequestIn(BaseModel):
    ratio: Literal["9:16", "1:1", "16:9"] = "9:16"
    style: str = "bold_pop"
    caption_scale: float = Field(default=1.0, ge=0.7, le=1.8)
    write_srt: bool = False


class CaptionStyleOut(BaseModel):
    key: str
    label: str
    description: str
    #: Enough for the UI to approximate the look in HTML/CSS before rendering.
    preview: dict[str, Any]


class ProviderStatusOut(BaseModel):
    name: str
    available: bool
    detail: str = ""
    models: list[str] = Field(default_factory=list)
    requires_key: bool = True
    has_key: bool = False


class SettingsOut(BaseModel):
    active_provider: str
    providers: dict[str, dict[str, Any]]
    whisper: dict[str, Any]
    clips: dict[str, Any]
    ingest: dict[str, Any]
    export: dict[str, Any]
    publish: dict[str, Any]
    insecure_secret_storage: bool
    #: Which providers have a key stored. The keys themselves never leave the
    #: keyring, so the UI shows presence, not value.
    keys_present: dict[str, bool] = Field(default_factory=dict)


class SettingsIn(BaseModel):
    active_provider: str | None = None
    providers: dict[str, dict[str, Any]] | None = None
    whisper: dict[str, Any] | None = None
    clips: dict[str, Any] | None = None
    ingest: dict[str, Any] | None = None
    export: dict[str, Any] | None = None
    publish: dict[str, Any] | None = None


class SecretIn(BaseModel):
    key: str
    value: str


class SystemOut(BaseModel):
    ready: bool
    python_version: str
    platform: str
    ffmpeg_version: str | None
    has_libass: bool
    nvenc_works: bool
    videotoolbox_works: bool = False
    accel: str
    gpu_name: str | None
    compute_type: str
    diarization_available: bool


class EngineOut(BaseModel):
    state: str
    error: str | None = None
    model: str = ""
    model_loaded: str | None = None
    started_at: str | None = None
    active_job_id: str | None = None
    queued: int = 0
    ffmpeg_version: str | None = None
    ready: bool = False


class EngineStopIn(BaseModel):
    #: Cancel an in-flight job instead of refusing to stop.
    force: bool = False


class PublishOut(BaseModel):
    id: str
    export_id: str
    title: str
    description: str
    hashtags: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    privacy: str
    status: str
    progress: float
    video_id: str | None = None
    url: str | None = None
    error: str | None = None
    attempts: int = 0
    created_at: str
    updated_at: str
    published_at: str | None = None
    thumbnail_url: str | None = None
    download_url: str | None = None

    @classmethod
    def of(cls, job: models.PublishJob) -> PublishOut:
        return cls(
            id=job.id,
            export_id=job.export_id,
            title=job.title,
            description=job.description,
            hashtags=job.hashtags,
            tags=job.tags,
            privacy=job.privacy,
            status=job.status,
            progress=job.progress,
            video_id=job.video_id,
            url=job.url,
            error=job.error,
            attempts=job.attempts,
            created_at=job.created_at,
            updated_at=job.updated_at,
            published_at=job.published_at,
            thumbnail_url=f"/api/exports/{job.export_id}/thumbnail",
            download_url=f"/api/exports/{job.export_id}/download",
        )


class ExportDetailOut(BaseModel):
    id: str
    clip_id: str
    job_id: str | None = None
    title: str = ""
    hook: str = ""
    filename: str = ""
    duration_s: float = 0.0
    ratio: str
    style: str
    size_bytes: int
    created_at: str
    download_url: str
    thumbnail_url: str
    preview_url: str = ""
    publish: PublishOut | None = None
    validation: dict[str, Any] | None = None


class MetadataIn(BaseModel):
    style: Literal["concise", "story", "educational"] | None = None
    extra_context: str | None = None


class MetadataOut(BaseModel):
    titles: list[str]
    recommended_title: str
    description: str
    hashtags: list[str]
    tags: list[str]
    generated_by: str
    warning: str = ""
    notes: list[str] = Field(default_factory=list)


class PublishIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    hashtags: list[str] = Field(default_factory=list, max_length=5)
    tags: list[str] = Field(default_factory=list)
    privacy: Literal["private", "unlisted", "public"] = "private"
    #: The user has reviewed the file and the metadata.
    confirm: bool = False
    #: A second, explicit acknowledgement for a public upload.
    confirm_public: bool = False


class PublishingStatusOut(BaseModel):
    configured: bool
    connected: bool
    redirect_uri: str
    client_project: str = ""
    client_source: str = ""
    configured_redirect_uris: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    expires_at: float | None = None
    has_refresh_token: bool = False
    warnings: list[str] = Field(default_factory=list)
    detail: str = ""
    hint: str = ""
    export_directory: str = ""
    analytics_scope: bool = False


class PublishedVideoOut(BaseModel):
    job_id: str
    export_id: str
    video_id: str
    title: str
    url: str
    published_at: str | None
    views: int = 0
    likes: int = 0
    comments: int = 0
    privacy: str = ""


class PublishingAnalyticsOut(BaseModel):
    videos: list[PublishedVideoOut] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)


class InstagramStatusOut(BaseModel):
    configured: bool
    missing: list[str] = Field(default_factory=list)
    public_url_ok: bool
    account_id: str = ""
    public_base_url: str = ""
    account: dict[str, Any] = Field(default_factory=dict)


class InstagramPublishIn(BaseModel):
    caption: str = Field(default="", max_length=2200)
    confirm: bool = False


class InstagramPublishOut(BaseModel):
    id: str
    export_id: str
    caption: str
    status: str
    container_id: str | None = None
    media_id: str | None = None
    url: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str
    published_at: str | None = None


class OAuthStartOut(BaseModel):
    auth_url: str
    redirect_uri: str
    state: str


class PublishQueueCountOut(BaseModel):
    pending: int = 0
    uploading: int = 0
    processing: int = 0
    published: int = 0
    failed: int = 0
