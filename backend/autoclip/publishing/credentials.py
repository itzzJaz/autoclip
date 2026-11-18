"""OAuth client discovery and token storage for YouTube.

The client secret JSON is read from disk and never copied into settings, logged,
or returned by an endpoint. Tokens live outside the repository under
``~/.autoclip`` with owner-only permissions, and only their presence and expiry
are ever reported to the UI.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import paths

log = logging.getLogger(__name__)

#: Scope is deliberately the narrow upload scope only. Reading the channel,
#: managing playlists, and listing videos all need broader scopes that a clipper
#: has no business asking for.
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"

CLIENT_ENV = "AUTOCLIP_YOUTUBE_CLIENT_SECRET"
REDIRECT_ENV = "AUTOCLIP_OAUTH_REDIRECT_URI"

TOKEN_FILENAME = "youtube_token.json"


class CredentialsError(RuntimeError):
    """The OAuth client or stored token is missing or unusable."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    client_secret: str
    project_id: str
    auth_uri: str
    token_uri: str
    redirect_uris: tuple[str, ...]
    source: str


@dataclass
class StoredToken:
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    scope: str = ""
    token_type: str = "Bearer"

    @property
    def fresh(self) -> bool:
        return bool(self.access_token) and self.expires_at > time.time() + 60

    @property
    def connected(self) -> bool:
        return bool(self.refresh_token or self.access_token)

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
            "token_type": self.token_type,
        }

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], *, previous: StoredToken | None = None
    ) -> StoredToken:
        expires_in = payload.get("expires_in")
        expires_at = time.time() + float(expires_in) if expires_in else 0.0
        return cls(
            access_token=str(payload.get("access_token") or ""),
            # Google omits the refresh token on repeat grants unless consent is
            # prompted again. Keeping the previous one is what stops a reconnect
            # from silently breaking the next day.
            refresh_token=str(
                payload.get("refresh_token") or (previous.refresh_token if previous else "")
            ),
            expires_at=expires_at,
            scope=str(payload.get("scope") or (previous.scope if previous else UPLOAD_SCOPE)),
            token_type=str(payload.get("token_type") or "Bearer"),
        )


# --------------------------------------------------------------------------
# Client discovery
# --------------------------------------------------------------------------


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    if env := os.environ.get(CLIENT_ENV):
        candidates.append(Path(env).expanduser())

    # Repo root and the runtime home are both reasonable places for a desktop
    # install. Globbing rather than a fixed filename means the timestamped name
    # Google's console downloads keeps working.
    root = Path(__file__).resolve().parents[3]
    for directory in (root, paths.root(), Path.cwd()):
        candidates.extend(sorted(directory.glob("client_secret*.json")))

    candidates.append(paths.root() / "client_secret.json")
    return candidates


def discover_client() -> OAuthClient:
    """Find and parse the OAuth client JSON.

    Raises :class:`CredentialsError` with a hint rather than returning None: the
    caller needs to show *where* the file was looked for.
    """
    seen: list[str] = []
    for path in _candidate_paths():
        if not path.is_file():
            continue
        seen.append(str(path))
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialsError(
                f"Could not read the YouTube client file at {path.name}.",
                hint=str(exc),
            ) from exc

        section = payload.get("installed") or payload.get("web")
        if not isinstance(section, dict):
            continue
        client_id = str(section.get("client_id") or "")
        client_secret = str(section.get("client_secret") or "")
        if not client_id or not client_secret:
            continue

        return OAuthClient(
            client_id=client_id,
            client_secret=client_secret,
            project_id=str(section.get("project_id") or ""),
            auth_uri=str(section.get("auth_uri") or "https://accounts.google.com/o/oauth2/v2/auth"),
            token_uri=str(section.get("token_uri") or "https://oauth2.googleapis.com/token"),
            redirect_uris=tuple(section.get("redirect_uris") or []),
            source=path.name,
        )

    raise CredentialsError(
        "No YouTube OAuth client secret was found.",
        hint=(
            "Put the `client_secret_*.json` downloaded from Google Cloud Console in the "
            "AutoClip project folder, or set AUTOCLIP_YOUTUBE_CLIENT_SECRET to its path. "
            f"Looked in: {', '.join(seen) or 'the project folder and ~/.autoclip'}."
        ),
    )


def client_summary() -> dict[str, Any]:
    """Non-secret description of the configured OAuth client."""
    try:
        client = discover_client()
    except CredentialsError as exc:
        return {"configured": False, "detail": str(exc), "hint": exc.hint}
    return {
        "configured": True,
        "project": client.project_id,
        "source": client.source,
        "redirect_uris": list(client.redirect_uris),
    }


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


def token_path() -> Path:
    return paths.root() / TOKEN_FILENAME


def load_token() -> StoredToken | None:
    path = token_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Ignoring unreadable YouTube token file: %s", exc)
        return None
    return StoredToken(
        access_token=str(payload.get("access_token") or ""),
        refresh_token=str(payload.get("refresh_token") or ""),
        expires_at=float(payload.get("expires_at") or 0.0),
        scope=str(payload.get("scope") or ""),
        token_type=str(payload.get("token_type") or "Bearer"),
    )


def save_token(token: StoredToken) -> None:
    paths.ensure_layout()
    path = token_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(token.to_dict(), indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):
        tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)
    with contextlib.suppress(OSError):
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def delete_token() -> None:
    token_path().unlink(missing_ok=True)


def token_summary() -> dict[str, Any]:
    token = load_token()
    if token is None or not token.connected:
        return {"connected": False}
    return {
        "connected": True,
        "scopes": token.scope.split() if token.scope else [UPLOAD_SCOPE],
        "expires_at": token.expires_at,
        "has_refresh_token": bool(token.refresh_token),
    }


def default_redirect_uri(port: int | None = None) -> str:
    """Return the loopback redirect URI handed to Google.

    The supplied installed-app client registers ``http://localhost`` with no
    path. Google's loopback flow treats that as a host, not a fixed address, so
    the running port can be appended at runtime. The root path is used for the
    same reason: it is the one path the registered URI actually contains.
    """
    if env := os.environ.get(REDIRECT_ENV):
        return env
    suffix = f":{port}" if port else ":8000"
    return f"http://localhost{suffix}"
