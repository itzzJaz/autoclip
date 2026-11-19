"""YouTube Data API v3 — resumable upload and processing status.

The upload is chunked rather than a single PUT so progress is real, a dropped
connection can resume at the last acknowledged byte, and a retry never re-sends
a file that Google already has. That last point is why the byte offset is
re-queried from Google on failure instead of tracked locally.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from . import oauth

log = logging.getLogger(__name__)

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API_URL = "https://www.googleapis.com/youtube/v3/videos"

#: Google requires a multiple of 256 KB for non-final chunks. 8 MiB keeps the
#: request count low without holding a whole large clip in memory.
CHUNK_SIZE = 8 * 1024 * 1024
MAX_ATTEMPTS = 4


class YouTubeError(RuntimeError):
    """An upload or status check failed."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


class UploadCancelled(RuntimeError):
    """The user stopped this upload."""


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:400] or f"HTTP {response.status_code}"
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message") or ""
        reason = ""
        errors = error.get("errors") or []
        if errors and isinstance(errors[0], dict):
            reason = errors[0].get("reason") or ""
        return " ".join(part for part in (message, f"[{reason}]" if reason else "") if part)
    return str(payload)[:400]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def upload_video(
    path: Path,
    *,
    title: str,
    description: str,
    tags: list[str],
    privacy: str,
    on_progress: Callable[[float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Upload a file and return the video resource.

    Preconditions:
        ``path`` is a readable MP4; ``privacy`` is one of private/unlisted/public
        and the caller has confirmed a public upload.
    """
    size = path.stat().st_size
    if size <= 0:
        raise YouTubeError("The exported file is empty, so there is nothing to upload.")

    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    token = oauth.access_token()
    session_response, token = _start_session(token, size, metadata)
    location = session_response.headers.get("location")
    if not location:
        raise YouTubeError(
            "YouTube accepted the upload request but returned no upload URL.",
            hint=_error_detail(session_response),
        )

    offset = 0
    attempt = 0
    while offset < size:
        if cancelled is not None and cancelled():
            raise UploadCancelled("Upload cancelled.")

        end = min(offset + CHUNK_SIZE, size)
        chunk = _read_range(path, offset, end)
        headers = {
            **_headers(token),
            "Content-Length": str(len(chunk)),
            "Content-Range": f"bytes {offset}-{end - 1}/{size}",
        }

        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, read=300.0)) as client:
                response = client.put(location, content=chunk, headers=headers)
        except httpx.HTTPError as exc:
            attempt += 1
            if attempt >= MAX_ATTEMPTS:
                raise YouTubeError(
                    "The upload connection kept failing.",
                    hint=(
                        f"{exc}\n\nYour progress is saved on Google's side; "
                        "use Retry in the queue."
                    ),
                ) from exc
            time.sleep(min(2**attempt, 8))
            offset, finished = _resume_offset(location, token, size)
            if finished is not None:
                return finished
            continue

        if response.status_code in (200, 201):
            if on_progress is not None:
                on_progress(1.0)
            payload = response.json()
            log.info("Uploaded video %s.", payload.get("id"))
            return payload

        if response.status_code == 308:
            attempt = 0
            offset = _acknowledged_offset(response, offset, end)
            if on_progress is not None:
                on_progress(min(0.99, offset / size))
            continue

        if response.status_code == 401:
            # Token expired mid-upload. Refresh and re-query rather than
            # resending a chunk Google may already have.
            token = oauth.access_token(force_refresh=True)
            offset, finished = _resume_offset(location, token, size)
            if finished is not None:
                return finished
            continue

        if response.status_code >= 500:
            attempt += 1
            if attempt >= MAX_ATTEMPTS:
                raise YouTubeError(
                    "YouTube kept returning a server error during the upload.",
                    hint=_error_detail(response),
                )
            time.sleep(min(2**attempt, 8))
            offset, finished = _resume_offset(location, token, size)
            if finished is not None:
                return finished
            continue

        raise YouTubeError(
            f"YouTube rejected the upload (HTTP {response.status_code}).",
            hint=_error_detail(response),
        )

    raise YouTubeError("The upload finished without YouTube returning a video id.")


def _start_session(
    token: str, size: int, metadata: dict[str, Any]
) -> tuple[httpx.Response, str]:
    headers = {
        **_headers(token),
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(size),
        "X-Upload-Content-Type": "video/mp4",
    }
    try:
        response = httpx.post(
            f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
            headers=headers,
            content=json.dumps(metadata).encode("utf-8"),
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise YouTubeError(
            "Could not reach YouTube to start the upload.",
            hint=str(exc),
        ) from exc

    if response.status_code == 401:
        token = oauth.access_token(force_refresh=True)
        headers["Authorization"] = f"Bearer {token}"
        response = httpx.post(
            f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
            headers=headers,
            content=json.dumps(metadata).encode("utf-8"),
            timeout=60.0,
        )

    if response.status_code >= 400:
        raise YouTubeError(
            f"YouTube refused to start the upload (HTTP {response.status_code}).",
            hint=_error_detail(response),
        )
    return response, token


def _read_range(path: Path, start: int, end: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(start)
        return handle.read(end - start)


def _acknowledged_offset(response: httpx.Response, start: int, end: int) -> int:
    """Byte offset after a 308, trusting Google's Range header when present."""
    header = response.headers.get("range") or response.headers.get("Range")
    if header and "=" in header:
        try:
            last = int(header.split("=", 1)[1].split("-", 1)[1])
            return last + 1
        except (IndexError, ValueError):
            pass
    return end


def _resume_offset(location: str, token: str, size: int) -> tuple[int, dict[str, Any] | None]:
    """Ask YouTube how many bytes it already has.

    Returns ``(offset, payload)``. A payload means the upload completed while we
    believed it had failed, so the caller can finish without re-sending bytes.
    """
    headers = {
        **_headers(token),
        "Content-Length": "0",
        "Content-Range": f"bytes */{size}",
    }
    try:
        response = httpx.put(location, headers=headers, timeout=60.0)
    except httpx.HTTPError:
        return 0, None

    if response.status_code in (200, 201):
        # The upload actually completed while we thought it failed.
        try:
            return size, response.json()
        except ValueError:
            return size, None
    if response.status_code != 308:
        return 0, None

    header = response.headers.get("range") or response.headers.get("Range")
    if header and "=" in header:
        try:
            return int(header.split("=", 1)[1].split("-", 1)[1]) + 1, None
        except (IndexError, ValueError):
            return 0, None
    return 0, None


def processing_status(video_id: str) -> dict[str, Any]:
    """Return YouTube's processing/privacy state for an uploaded video."""
    token = oauth.access_token()
    params = {"part": "status,processingDetails", "id": video_id}
    response = httpx.get(API_URL, headers=_headers(token), params=params, timeout=30.0)
    if response.status_code == 401:
        token = oauth.access_token(force_refresh=True)
        response = httpx.get(API_URL, headers=_headers(token), params=params, timeout=30.0)
    if response.status_code >= 400:
        raise YouTubeError(
            f"Could not read the upload status (HTTP {response.status_code}).",
            hint=_error_detail(response),
        )

    items = (response.json() or {}).get("items") or []
    if not items:
        raise YouTubeError("YouTube returned no video for that id.")
    item = items[0]
    status = item.get("status") or {}
    processing = item.get("processingDetails") or {}
    return {
        "upload_status": status.get("uploadStatus", ""),
        "privacy": status.get("privacyStatus", ""),
        "failure_reason": status.get("failureReason", ""),
        "rejection_reason": status.get("rejectionReason", ""),
        "processing_status": processing.get("processingStatus", ""),
        "processing_progress": processing.get("processingProgress", {}),
    }


def video_statistics(video_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch public/private video statistics for published uploads."""
    ids = [video_id for video_id in dict.fromkeys(video_ids) if video_id]
    if not ids:
        return {}

    token = oauth.access_token()
    params = {"part": "snippet,statistics,status", "id": ",".join(ids[:50])}
    response = httpx.get(API_URL, headers=_headers(token), params=params, timeout=30.0)
    if response.status_code == 401:
        token = oauth.access_token(force_refresh=True)
        response = httpx.get(API_URL, headers=_headers(token), params=params, timeout=30.0)
    if response.status_code >= 400:
        raise YouTubeError(
            f"Could not read YouTube statistics (HTTP {response.status_code}).",
            hint=_error_detail(response),
        )

    result: dict[str, dict[str, Any]] = {}
    for item in (response.json() or {}).get("items") or []:
        video_id = str(item.get("id") or "")
        snippet = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        status = item.get("status") or {}
        result[video_id] = {
            "title": snippet.get("title") or "",
            "published_at": snippet.get("publishedAt") or "",
            "views": int(stats.get("viewCount") or 0),
            "likes": int(stats.get("likeCount") or 0),
            "comments": int(stats.get("commentCount") or 0),
            "privacy": status.get("privacyStatus") or "",
        }
    return result


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/shorts/{video_id}"
