"""Meta Graph API helpers for Instagram Reels publishing."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

GRAPH_VERSION = "v22.0"
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"


class InstagramError(RuntimeError):
    pass


def configuration() -> dict[str, str]:
    return {
        "app_id": os.environ.get("AUTOCLIP_META_APP_ID", "").strip(),
        "app_secret": os.environ.get("AUTOCLIP_META_APP_SECRET", "").strip(),
        "access_token": os.environ.get("AUTOCLIP_META_ACCESS_TOKEN", "").strip(),
        "account_id": os.environ.get("AUTOCLIP_INSTAGRAM_ACCOUNT_ID", "").strip(),
        "public_base_url": os.environ.get("AUTOCLIP_PUBLIC_BASE_URL", "").strip().rstrip("/"),
    }


def status() -> dict[str, Any]:
    config = configuration()
    required = ("app_id", "app_secret", "access_token", "account_id", "public_base_url")
    missing = [key for key in required if not config[key]]
    public_ok = config["public_base_url"].startswith("https://")
    account: dict[str, Any] = {}
    if not missing and public_ok:
        try:
            account = account_stats(config)
        except InstagramError:
            pass
    return {
        "configured": not missing and public_ok,
        "missing": missing,
        "public_url_ok": public_ok,
        "account_id": config["account_id"],
        "public_base_url": config["public_base_url"],
        "account": account,
    }


def account_stats(config: dict[str, str] | None = None) -> dict[str, Any]:
    config = config or configuration()
    token = config["access_token"]
    account_id = config["account_id"]
    if not token or not account_id:
        raise InstagramError("Instagram access token or Business account ID is missing.")
    response = httpx.get(
        f"{GRAPH_URL}/{account_id}",
        params={
            "fields": "username,name,followers_count,media_count",
            "access_token": token,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise InstagramError(_graph_error(response))
    payload = response.json()
    return {
        "username": payload.get("username") or "",
        "name": payload.get("name") or "",
        "followers": int(payload.get("followers_count") or 0),
        "media": int(payload.get("media_count") or 0),
    }


def publish_reel(*, video_url: str, caption: str) -> dict[str, Any]:
    config = configuration()
    missing = [
        key
        for key in ("access_token", "account_id", "public_base_url")
        if not config[key]
    ]
    if missing:
        raise InstagramError(
            f"Instagram publishing is missing: {', '.join(missing)}."
        )
    if not config["public_base_url"].startswith("https://"):
        raise InstagramError("M-CLIP_PUBLIC_BASE_URL must be a public HTTPS URL.")

    token = config["access_token"]
    account_id = config["account_id"]
    response = httpx.post(
        f"{GRAPH_URL}/{account_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": token,
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise InstagramError(_graph_error(response))
    container_id = str(response.json().get("id") or "")
    if not container_id:
        raise InstagramError("Instagram returned no Reel container ID.")

    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        state = httpx.get(
            f"{GRAPH_URL}/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=30,
        )
        if state.status_code >= 400:
            raise InstagramError(_graph_error(state))
        status_code = str((state.json().get("status_code") or "")).upper()
        if status_code == "FINISHED":
            break
        if status_code == "ERROR":
            raise InstagramError("Instagram failed to process the Reel.")
        time.sleep(5)
    else:
        raise InstagramError("Instagram is still processing the Reel.")

    published = httpx.post(
        f"{GRAPH_URL}/{account_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=60,
    )
    if published.status_code >= 400:
        raise InstagramError(_graph_error(published))
    media_id = str(published.json().get("id") or "")
    permalink = ""
    if media_id:
        detail = httpx.get(
            f"{GRAPH_URL}/{media_id}",
            params={"fields": "permalink", "access_token": token},
            timeout=30,
        )
        if detail.status_code < 400:
            permalink = str(detail.json().get("permalink") or "")
    return {"container_id": container_id, "media_id": media_id, "url": permalink}


def _graph_error(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
        message = error.get("message") or ""
        code = error.get("code") or response.status_code
        return f"Meta API {code}: {message}"
    except Exception:
        return f"Meta API returned HTTP {response.status_code}"
