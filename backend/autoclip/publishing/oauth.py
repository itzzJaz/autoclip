"""Google OAuth 2.0 for installed apps, with PKCE.

Implemented directly against Google's token endpoint instead of adding
``google-auth-oauthlib``: the flow is four HTTP requests, the dependency would be
another package to audit, and the upload path already needs raw HTTP for
resumable PUTs.

Nothing here writes the client secret or a token to a log. Errors are reported by
their Google error code and description.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .credentials import (
    UPLOAD_SCOPE,
    CredentialsError,
    OAuthClient,
    StoredToken,
    delete_token,
    discover_client,
    load_token,
    save_token,
)

log = logging.getLogger(__name__)


class OAuthError(RuntimeError):
    """Authorization or token refresh failed."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass
class _Pending:
    verifier: str
    redirect_uri: str
    created_at: float


_pending: dict[str, _Pending] = {}
_pending_lock = threading.Lock()
_PENDING_TTL_S = 15 * 60


def _prune() -> None:
    cutoff = time.time() - _PENDING_TTL_S
    for state in [key for key, value in _pending.items() if value.created_at < cutoff]:
        _pending.pop(state, None)


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def begin(redirect_uri: str) -> tuple[str, str]:
    """Create an authorization URL. Returns ``(url, state)``."""
    client = discover_client()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)

    with _pending_lock:
        _prune()
        _pending[state] = _Pending(
            verifier=verifier, redirect_uri=redirect_uri, created_at=time.time()
        )

    query = urlencode(
        {
            "client_id": client.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": UPLOAD_SCOPE,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{client.auth_uri}?{query}", state


def _token_request(client: OAuthClient, data: dict[str, str]) -> dict:
    try:
        response = httpx.post(client.token_uri, data=data, timeout=30.0)
    except httpx.HTTPError as exc:
        raise OAuthError(
            "Could not reach Google's token endpoint.",
            hint=f"{exc}\n\nCheck your internet connection and retry.",
        ) from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code >= 400 or payload.get("error"):
        code = payload.get("error") or response.status_code
        detail = payload.get("error_description") or "Google rejected the token request."
        raise OAuthError(f"Google authorization failed ({code}).", hint=str(detail))
    return payload


def complete(code: str, state: str) -> StoredToken:
    """Exchange the callback code for tokens and persist them."""
    with _pending_lock:
        _prune()
        pending = _pending.pop(state, None)
    if pending is None:
        raise OAuthError(
            "This sign-in link has expired or was already used.",
            hint="Start the YouTube connection again from the Publishing screen.",
        )

    client = discover_client()
    payload = _token_request(
        client,
        {
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "code": code,
            "code_verifier": pending.verifier,
            "grant_type": "authorization_code",
            "redirect_uri": pending.redirect_uri,
        },
    )

    token = StoredToken.from_payload(payload)
    if not token.refresh_token:
        # Google only returns one on the first consent (or with prompt=consent).
        # We do ask for consent, but a missing refresh token still deserves a
        # warning rather than a silent one-hour session.
        log.warning("Google did not return a refresh token; the connection will expire.")
    save_token(token)
    log.info("YouTube account connected.")
    return token


def refresh(client: OAuthClient, token: StoredToken) -> StoredToken:
    if not token.refresh_token:
        raise OAuthError(
            "The YouTube connection has expired and cannot be renewed.",
            hint="Reconnect the account from the Publishing screen.",
        )

    payload = _token_request(
        client,
        {
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "refresh_token": token.refresh_token,
            "grant_type": "refresh_token",
        },
    )
    updated = StoredToken.from_payload(payload, previous=token)
    save_token(updated)
    return updated


def access_token(*, force_refresh: bool = False) -> str:
    """Return a usable access token, refreshing it when necessary."""
    token = load_token()
    if token is None or not token.connected:
        raise OAuthError(
            "YouTube is not connected.",
            hint="Open Publishing Studio and connect your Google account first.",
        )
    if token.fresh and not force_refresh:
        return token.access_token

    if not token.refresh_token:
        raise OAuthError(
            "The YouTube access token has expired.",
            hint="Reconnect the account from the Publishing screen.",
        )

    try:
        client = discover_client()
    except CredentialsError as exc:
        raise OAuthError(str(exc), hint=exc.hint) from exc
    return refresh(client, token).access_token


def disconnect() -> None:
    delete_token()
    log.info("YouTube account disconnected.")
