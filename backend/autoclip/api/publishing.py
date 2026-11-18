"""Export history and the YouTube publishing studio endpoints."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from .. import config
from ..db import store
from ..db.models import PublishJob, new_id
from ..pipeline.runner import JobWorkspace
from ..pipeline.transcript import Transcript
from ..publishing import oauth, thumbnail
from ..publishing.credentials import (
    UPLOAD_SCOPE,
    CredentialsError,
    client_summary,
    default_redirect_uri,
    token_summary,
)
from ..publishing.metadata import ClipContext, generate
from ..publishing.queue import publish_queue
from ..publishing.validation import validate_export
from .schemas import (
    ExportDetailOut,
    MetadataIn,
    MetadataOut,
    OAuthStartOut,
    PublishIn,
    PublishingStatusOut,
    PublishOut,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["publishing"])


# --------------------------------------------------------------------------
# Export history / detail
# --------------------------------------------------------------------------


@router.get("/exports", response_model=list[ExportDetailOut])
async def list_exports(limit: int = 100) -> list[ExportDetailOut]:
    records = await asyncio.to_thread(store.list_all_exports, limit)
    out: list[ExportDetailOut] = []
    for record in records:
        out.append(await asyncio.to_thread(_export_out, record, validate=False))
    return out


@router.get("/exports/{export_id}", response_model=ExportDetailOut)
async def export_detail(export_id: str, validate: bool = True) -> ExportDetailOut:
    record = await asyncio.to_thread(store.get_export, export_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Export not found.")
    return await asyncio.to_thread(_export_out, record, validate=validate)


@router.get("/exports/{export_id}/thumbnail")
async def export_thumbnail(export_id: str) -> FileResponse:
    record = await asyncio.to_thread(store.get_export, export_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Export not found.")
    path = Path(record.path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="The exported file has been moved or deleted.")
    thumb = await asyncio.to_thread(thumbnail.thumbnail_for, export_id, path)
    if thumb is None:
        raise HTTPException(status_code=404, detail="Could not generate a thumbnail.")
    return FileResponse(thumb, media_type="image/jpeg")


# --------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------


@router.post("/exports/{export_id}/metadata", response_model=MetadataOut)
async def generate_metadata(export_id: str, payload: MetadataIn | None = None) -> MetadataOut:
    record = await asyncio.to_thread(store.get_export, export_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Export not found.")

    context = await asyncio.to_thread(_clip_context, record)
    settings = config.load().publish
    if payload is not None and payload.style:
        settings = settings.model_copy(update={"description_style": payload.style})
    if payload is not None and payload.extra_context:
        context.transcript = (
            f"{context.transcript}\n\nExtra context from the user: {payload.extra_context}"
        )

    try:
        draft = await generate(context, settings)
    except Exception as exc:  # noqa: BLE001 - generator already falls back, this is a hard stop
        log.exception("Could not generate metadata for %s.", export_id)
        raise HTTPException(
            status_code=502,
            detail={"message": "Could not generate metadata.", "hint": str(exc)},
        ) from exc

    return MetadataOut(
        titles=draft.titles,
        recommended_title=draft.recommended_title,
        description=draft.description,
        hashtags=draft.hashtags,
        tags=draft.tags,
        generated_by=draft.generated_by,
        warning=draft.warning,
        notes=draft.notes,
    )


# --------------------------------------------------------------------------
# Publishing
# --------------------------------------------------------------------------


@router.post("/exports/{export_id}/publish", response_model=PublishOut, status_code=201)
async def publish_export(export_id: str, payload: PublishIn) -> PublishOut:
    record = await asyncio.to_thread(store.get_export, export_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Export not found.")

    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Publishing needs explicit confirmation.",
                "hint": (
                    "Review the file, title, description, and privacy, then confirm the upload."
                ),
            },
        )

    if payload.privacy == "public" and not payload.confirm_public:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "A public upload needs a second confirmation.",
                "hint": "Tick the public confirmation box. Private is the default for a reason.",
            },
        )

    path = Path(record.path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="The exported file has been moved or deleted.")

    existing = await asyncio.to_thread(store.get_publish_job_for_export, export_id)
    if existing is not None and existing.status in (
        "pending",
        "uploading",
        "processing",
        "published",
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"This export is already {existing.status}.",
                "hint": (
                    "Open the queue to follow it. Published videos are never uploaded twice."
                    if existing.status == "published"
                    else "Wait for the current upload to finish, or retry it from the queue."
                ),
            },
        )

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="A title is required.")

    hashtags = _normalise_hashtags(payload.hashtags)
    tags = _normalise_tags(payload.tags)
    thumb = await asyncio.to_thread(thumbnail.thumbnail_for, export_id, path)

    if existing is not None:
        # A failed job is resumed in place. Keeping the row is what enforces one
        # upload per export.
        await asyncio.to_thread(
            store.update_publish_job,
            existing.id,
            title=title,
            description=payload.description,
            hashtags=hashtags,
            tags=tags,
            privacy=payload.privacy,
            status="pending",
            progress=0.0,
            error=None,
            published_at=None,
            thumbnail_path=str(thumb) if thumb else None,
        )
        job_id = existing.id
    else:
        job = PublishJob(
            id=new_id(),
            export_id=export_id,
            title=title,
            description=payload.description,
            hashtags=hashtags,
            tags=tags,
            privacy=payload.privacy,
            status="pending",
            thumbnail_path=str(thumb) if thumb else None,
        )
        await asyncio.to_thread(store.create_publish_job, job)
        job_id = job.id

    publish_queue.notify()
    updated = await asyncio.to_thread(store.get_publish_job, job_id)
    return PublishOut.of(updated or job)


@router.get("/publishing/queue", response_model=list[PublishOut])
async def publishing_queue(limit: int = 100) -> list[PublishOut]:
    jobs = await asyncio.to_thread(store.list_publish_jobs, limit)
    return [PublishOut.of(job) for job in jobs]


@router.post("/publishing/queue/{job_id}/retry", response_model=PublishOut)
async def retry_publish(job_id: str) -> PublishOut:
    job = await asyncio.to_thread(store.get_publish_job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if job.status != "failed":
        raise HTTPException(
            status_code=409,
            detail=f"Only failed uploads can be retried (this one is {job.status}).",
        )

    await asyncio.to_thread(
        store.update_publish_job,
        job_id,
        status="processing" if job.video_id else "pending",
        progress=1.0 if job.video_id else 0.0,
        error=None,
        published_at=None,
    )
    publish_queue.notify()
    updated = await asyncio.to_thread(store.get_publish_job, job_id)
    return PublishOut.of(updated or job)


# --------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------


def redirect_uri_for(request: Request) -> str:
    return default_redirect_uri(request.url.port)


def _status_for(request: Request) -> PublishingStatusOut:
    summary = client_summary()
    token = token_summary()
    redirect_uri = redirect_uri_for(request)

    warnings: list[str] = []
    registered = summary.get("redirect_uris") or []
    if summary.get("configured") and registered:
        hosts = {uri.split("/")[2].split(":")[0] for uri in registered if "://" in uri}
        if hosts and not hosts & {"localhost", "127.0.0.1"}:
            warnings.append(
                "The OAuth client has no loopback redirect URI. Add "
                f"{redirect_uri} to its authorized redirect URIs in Google Cloud Console."
            )
    if token.get("connected") and not token.get("has_refresh_token"):
        warnings.append(
            "Google did not return a refresh token. The connection will last about an hour; "
            "disconnect and reconnect to grant offline access."
        )

    return PublishingStatusOut(
        configured=bool(summary.get("configured")),
        connected=bool(token.get("connected")),
        redirect_uri=redirect_uri,
        client_project=summary.get("project", ""),
        client_source=summary.get("source", ""),
        configured_redirect_uris=registered,
        scopes=token.get("scopes") or [UPLOAD_SCOPE],
        expires_at=token.get("expires_at"),
        has_refresh_token=bool(token.get("has_refresh_token")),
        warnings=warnings,
        detail=summary.get("detail", ""),
        hint=summary.get("hint", ""),
    )


@router.get("/publishing/status", response_model=PublishingStatusOut)
async def publishing_status(request: Request) -> PublishingStatusOut:
    return _status_for(request)


@router.post("/publishing/auth/start", response_model=OAuthStartOut)
async def oauth_start(request: Request) -> OAuthStartOut:
    redirect_uri = redirect_uri_for(request)
    try:
        auth_url, state = await asyncio.to_thread(oauth.begin, redirect_uri)
    except CredentialsError as exc:
        raise HTTPException(
            status_code=400,
            detail={"message": str(exc), "hint": exc.hint},
        ) from exc
    except oauth.OAuthError as exc:
        raise HTTPException(
            status_code=400,
            detail={"message": str(exc), "hint": exc.hint},
        ) from exc
    return OAuthStartOut(auth_url=auth_url, redirect_uri=redirect_uri, state=state)


@router.get("/publishing/oauth/callback", response_model=None)
async def oauth_callback(code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    return await complete_callback(code=code, state=state, error=error)


async def complete_callback(*, code: str, state: str, error: str) -> RedirectResponse:
    """Finish the OAuth flow and send the browser back to the studio."""
    if error:
        return RedirectResponse(url=f"/publishing?error={quote(error)}", status_code=303)
    if not code or not state:
        return RedirectResponse(
            url=f"/publishing?error={quote('Google did not return an authorization code.')}",
            status_code=303,
        )

    try:
        await asyncio.to_thread(oauth.complete, code, state)
    except (oauth.OAuthError, CredentialsError) as exc:
        message = str(exc) + (f" {exc.hint}" if exc.hint else "")
        return RedirectResponse(url=f"/publishing?error={quote(message)}", status_code=303)
    return RedirectResponse(url="/publishing?connected=1", status_code=303)


@router.post("/publishing/auth/disconnect", status_code=204)
async def oauth_disconnect() -> None:
    await asyncio.to_thread(oauth.disconnect)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _export_out(record, *, validate: bool) -> ExportDetailOut:
    clip = store.get_clip(record.clip_id)
    job = store.get_job(clip.job_id) if clip else None
    publish = store.get_publish_job_for_export(record.id)

    report = None
    path = Path(record.path)
    if validate:
        try:
            # validate_export reports a missing or empty file as a blocking
            # finding, which is the honest answer for history: the row exists but
            # the MP4 does not.
            report = validate_export(path, cache_key=record.id).to_dict()
        except Exception:  # noqa: BLE001 - validation must not break history
            log.exception("Validation failed for %s.", record.id)

    return ExportDetailOut(
        id=record.id,
        clip_id=record.clip_id,
        job_id=job.id if job else None,
        title=(clip.title if clip else "") or path.stem,
        hook=clip.hook if clip else "",
        filename=path.name,
        duration_s=clip.duration_s if clip else 0.0,
        ratio=record.ratio,
        style=record.style,
        size_bytes=record.size_bytes,
        created_at=record.created_at,
        download_url=f"/api/exports/{record.id}/download",
        thumbnail_url=f"/api/exports/{record.id}/thumbnail",
        preview_url=f"/api/exports/{record.id}/download?inline=1",
        publish=PublishOut.of(publish) if publish else None,
        validation=report,
    )


def _clip_context(record) -> ClipContext:
    clip = store.get_clip(record.clip_id)
    if clip is None:
        return ClipContext(
            title=Path(record.path).stem,
            hook="",
            reason="",
            transcript="",
            duration_s=0.0,
        )

    job = store.get_job(clip.job_id)
    source_title = ""
    if job is not None:
        source = store.get_source(job.source_id)
        source_title = source.title if source else ""

    transcript = ""
    edit = store.get_clip_edit(clip.id)
    if edit is not None and edit.edited_words:
        transcript = " ".join(str(word.get("text", "")) for word in edit.edited_words)
    else:
        workspace = JobWorkspace(clip.job_id)
        if workspace.transcript.exists():
            try:
                loaded = Transcript.load(workspace.transcript)
                transcript = " ".join(
                    word.text for word in loaded.slice(clip.start_word, clip.end_word)
                )
            except Exception:  # noqa: BLE001 - missing/broken transcript is not fatal
                log.debug("Could not read transcript for %s.", clip.id, exc_info=True)

    return ClipContext(
        title=clip.title,
        hook=clip.hook,
        reason=clip.reason,
        transcript=transcript,
        duration_s=clip.duration_s,
        source_title=source_title,
    )


def _normalise_hashtags(values: list[str]) -> list[str]:
    result: list[str] = []
    for raw in values:
        for piece in re.split(r"[\s,]+", raw or ""):
            tag = re.sub(r"[^\w]", "", piece.lstrip("#"), flags=re.UNICODE)
            if tag:
                candidate = f"#{tag}"
                if candidate.lower() not in {item.lower() for item in result}:
                    result.append(candidate)
    return result[:5]


def _normalise_tags(values: list[str]) -> list[str]:
    tags: list[str] = []
    total = 0
    for raw in values:
        for piece in re.split(r"[,\n]+", raw or ""):
            tag = re.sub(r"\s+", " ", piece).strip().lstrip("#")
            if not tag or tag.lower() in {item.lower() for item in tags}:
                continue
            if total + len(tag) + 1 > 480:
                return tags
            tags.append(tag)
            total += len(tag) + 1
    return tags
