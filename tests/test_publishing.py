"""Publishing: OAuth plumbing, Shorts validation, metadata, and the queue API."""

from __future__ import annotations

import asyncio
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from autoclip import app as app_module
from autoclip import config
from autoclip.api import publishing as publishing_api
from autoclip.app import create_app
from autoclip.db import store
from autoclip.db.models import Export, PublishJob, new_id
from autoclip.pipeline import ffmpeg
from autoclip.publishing import credentials, metadata, oauth, youtube
from autoclip.publishing.credentials import OAuthClient, StoredToken
from autoclip.publishing.metadata import ClipContext
from autoclip.publishing.validation import validate_export
from fastapi.testclient import TestClient


@pytest.fixture
def client(autoclip_home, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(app_module.ENV_NO_WORKER, "1")
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def export_file(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    # Not a real MP4: the publish endpoint checks existence, not contents. The
    # queue re-validates before it ever uploads anything.
    path.write_bytes(b"\x00" * 4096)
    return path


@pytest.fixture
def clip(initialised_db: int):
    from autoclip.db.models import Clip, Job, Source

    source = store.create_source(
        Source(
            id=new_id(),
            type="upload",
            path="/tmp/source.mp4",
            title="Publishing source",
            duration_s=600.0,
        )
    )
    job = store.create_job(Job(id=new_id(), source_id=source.id, status="done"))
    return store.replace_clips(
        job.id,
        [
            Clip(
                id=new_id(),
                job_id=job.id,
                rank=1,
                start_s=0.0,
                end_s=40.0,
                start_word=0,
                end_word=80,
                title="A real moment",
                hook="The bit everyone quotes.",
                reason="A complete story.",
                score=93,
            )
        ],
    )[0]


@pytest.fixture
def export_record(export_file: Path, clip) -> Export:
    record = Export(
        id=new_id(),
        clip_id=clip.id,
        path=str(export_file),
        ratio="9:16",
        style="bold_pop",
        size_bytes=export_file.stat().st_size,
    )
    return store.create_export(record)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch, autoclip_home: Path) -> OAuthClient:
    path = autoclip_home / "client_secret_test.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "test-client.apps.googleusercontent.com",
                    "client_secret": "not-a-real-secret",
                    "project_id": "test-project",
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(credentials, "_candidate_paths", lambda: [path])
    return credentials.discover_client()


class TestCredentials:
    def test_discovers_installed_client_without_leaking_the_secret(
        self, fake_client: OAuthClient
    ) -> None:
        assert fake_client.project_id == "test-project"
        summary = json.dumps(credentials.client_summary())
        assert "not-a-real-secret" not in summary
        assert summary.count("configured") == 1

    def test_missing_client_explains_where_it_looked(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(credentials, "_candidate_paths", lambda: [tmp_path / "nope.json"])
        with pytest.raises(credentials.CredentialsError) as caught:
            credentials.discover_client()
        assert "client_secret" in caught.value.hint

    def test_tokens_are_owner_only_and_never_summarised(
        self, autoclip_home: Path
    ) -> None:
        credentials.save_token(
            StoredToken(
                access_token="access-value",
                refresh_token="refresh-value",
                expires_at=9_999_999_999,
                scope=credentials.UPLOAD_SCOPE,
            )
        )
        path = credentials.token_path()
        assert path.exists()
        if sys.platform != "win32":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600

        summary = json.dumps(credentials.token_summary())
        assert "access-value" not in summary
        assert "refresh-value" not in summary
        assert '"connected": true' in summary

        credentials.delete_token()
        assert credentials.token_summary() == {"connected": False}

    def test_redirect_defaults_to_the_registered_loopback_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(credentials.REDIRECT_ENV, raising=False)
        assert credentials.default_redirect_uri(8000) == "http://localhost:8000"
        monkeypatch.setenv(credentials.REDIRECT_ENV, "http://localhost:9000/callback")
        assert credentials.default_redirect_uri(8000) == "http://localhost:9000/callback"


class TestOAuth:
    def test_authorisation_url_asks_only_for_upload_scope(
        self, fake_client: OAuthClient
    ) -> None:
        url, state = oauth.begin("http://localhost:8000")
        assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube.upload" in url
        assert "code_challenge_method=S256" in url
        assert "access_type=offline" in url
        assert f"state={state}" in url

    def test_pkce_challenge_matches_the_verifier(self) -> None:
        import base64
        import hashlib

        verifier, challenge = oauth._pkce_pair()
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert challenge == expected
        assert 43 <= len(verifier) <= 128

    def test_expired_code_is_rejected_with_a_usable_hint(self) -> None:
        with pytest.raises(oauth.OAuthError) as caught:
            oauth.complete("code", "unknown-state")
        assert "expired" in str(caught.value)


class TestYouTubeHelpers:
    def test_acknowledged_offset_trusts_googles_range_header(self) -> None:
        import httpx

        response = httpx.Response(308, headers={"range": "bytes=0-1048575"})
        assert youtube._acknowledged_offset(response, 0, 1048576) == 1048576
        assert youtube.watch_url("abc123").endswith("/shorts/abc123")


class TestPublishApi:
    def payload(self, **overrides):
        body = {
            "title": "A real moment",
            "description": "From the transcript.",
            "hashtags": ["#clip"],
            "tags": ["clip"],
            "privacy": "private",
            "confirm": True,
            "confirm_public": False,
        }
        body.update(overrides)
        return body

    def test_unconfirmed_publish_is_refused(
        self, client: TestClient, export_record: Export
    ) -> None:
        response = client.post(
            f"/api/exports/{export_record.id}/publish",
            json=self.payload(confirm=False),
        )
        assert response.status_code == 400
        assert "confirmation" in response.json()["detail"]["message"]
        assert store.get_publish_job_for_export(export_record.id) is None

    def test_public_needs_a_second_confirmation(
        self, client: TestClient, export_record: Export
    ) -> None:
        response = client.post(
            f"/api/exports/{export_record.id}/publish",
            json=self.payload(privacy="public"),
        )
        assert response.status_code == 400
        assert "public" in response.json()["detail"]["message"].lower()

    def test_private_publish_queues_exactly_one_upload(
        self, client: TestClient, export_record: Export
    ) -> None:
        response = client.post(
            f"/api/exports/{export_record.id}/publish", json=self.payload()
        )
        assert response.status_code == 201
        job = response.json()
        assert job["status"] == "pending"
        assert job["privacy"] == "private"
        assert job["hashtags"] == ["#clip"]

        duplicate = client.post(
            f"/api/exports/{export_record.id}/publish", json=self.payload()
        )
        assert duplicate.status_code == 409
        assert len(store.list_publish_jobs()) == 1

        queue = client.get("/api/publishing/queue").json()
        assert [item["id"] for item in queue] == [job["id"]]

    def test_retry_is_only_for_failed_jobs(
        self, client: TestClient, export_record: Export
    ) -> None:
        created = client.post(
            f"/api/exports/{export_record.id}/publish", json=self.payload()
        ).json()

        pending_retry = client.post(f"/api/publishing/queue/{created['id']}/retry")
        assert pending_retry.status_code == 409

        store.update_publish_job(created["id"], status="failed", error="network died")
        retried = client.post(f"/api/publishing/queue/{created['id']}/retry")
        assert retried.status_code == 200
        assert retried.json()["status"] == "pending"
        assert retried.json()["error"] is None

    def test_pending_jobs_are_picked_oldest_first(self, initialised_db: int) -> None:
        first = store.create_publish_job(
            PublishJob(
                id="first",
                export_id="export-a",
                title="First",
                created_at="2024-01-01T00:00:00+00:00",
            )
        )
        store.create_publish_job(
            PublishJob(
                id="second",
                export_id="export-b",
                title="Second",
                created_at="2024-01-02T00:00:00+00:00",
            )
        )

        picked = store.next_pending_publish_job()
        assert picked is not None
        assert picked.id == first.id

    def test_one_row_per_export_is_enforced_by_the_database(
        self, initialised_db: int
    ) -> None:
        import sqlite3

        store.create_publish_job(PublishJob(id="one", export_id="export-a"))
        with pytest.raises(sqlite3.IntegrityError):
            store.create_publish_job(PublishJob(id="two", export_id="export-a"))

    def test_export_history_reports_missing_files_truthfully(
        self, client: TestClient, export_record: Export, export_file: Path
    ) -> None:
        listed = client.get("/api/exports").json()
        assert listed[0]["id"] == export_record.id
        assert listed[0]["preview_url"].endswith("inline=1")

        export_file.unlink()
        missing = client.get(f"/api/exports/{export_record.id}")
        assert missing.status_code == 200
        report = missing.json()["validation"]
        assert report["ok"] is False
        assert any(check["key"] == "file" for check in report["errors"])

    def test_delete_export_removes_only_the_local_file(
        self, client: TestClient, export_record: Export, export_file: Path
    ) -> None:
        assert export_file.exists()

        response = client.delete(f"/api/exports/{export_record.id}")

        assert response.status_code == 204
        assert not export_file.exists()
        assert client.get("/api/exports").json() == []


class TestMetadata:
    def context(self) -> ClipContext:
        return ClipContext(
            title="The 4am trick that fixed my sleep",
            hook="I stopped waking up at 4am.",
            reason="A complete story with a clear before and after.",
            transcript="I stopped waking up at 4am after changing one thing.",
            duration_s=42.0,
            source_title="Sleep podcast",
        )

    def test_provider_failure_falls_back_to_a_local_draft(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode():
            raise RuntimeError("no provider reachable")

        monkeypatch.setattr(metadata, "build_provider", explode)
        draft = asyncio.run(metadata.generate(self.context()))

        assert draft.generated_by == "local-draft"
        assert draft.warning
        assert len(draft.titles) == 3
        assert draft.recommended_title == draft.titles[0]
        assert draft.description
        assert 3 <= len(draft.hashtags) <= 5
        # Only words from the clip itself — no invented events or numbers.
        assert "4am" in draft.description.lower()

    def test_hashtags_are_normalised_and_deduplicated(self) -> None:
        tags = metadata._clean_hashtags(["#One", "one", "two words", ""], ["#Three"])
        assert tags == ["#One", "#two", "#three"]


class TestShortsValidation:
    def test_missing_file_is_a_blocking_error(self, tmp_path: Path) -> None:
        report = validate_export(tmp_path / "absent.mp4")
        assert report.ok is False
        assert report.errors[0].key == "file"

    @pytest.mark.slow
    def test_vertical_two_second_file_is_ready(self, tmp_path: Path) -> None:
        path = tmp_path / "vertical.mp4"
        subprocess.run(
            [
                ffmpeg.ffmpeg_path(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=1080x1920:rate=30:duration=2",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(path),
            ],
            check=True,
        )

        report = validate_export(path)

        assert report.ok is True
        assert report.errors == []
        assert report.width == 1080
        assert report.height == 1920
        assert report.has_audio is True
        assert any(check.key == "decode" and check.ok for check in report.checks)

    @pytest.mark.slow
    def test_horizontal_file_is_refused_with_an_explanation(self, tmp_path: Path) -> None:
        path = tmp_path / "horizontal.mp4"
        subprocess.run(
            [
                ffmpeg.ffmpeg_path(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=1280x720:rate=30:duration=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
        )

        report = validate_export(path)

        assert report.ok is False
        ratio = next(check for check in report.errors if check.key == "ratio")
        assert "9:16" in ratio.detail


class TestEngineApi:
    @pytest.fixture(autouse=True)
    def clean_engine(self, monkeypatch: pytest.MonkeyPatch):
        from autoclip import engine as engine_module
        from types import SimpleNamespace

        monkeypatch.setattr(
            engine_module.system,
            "refresh",
            lambda: SimpleNamespace(ffmpeg=SimpleNamespace(usable=True, missing_filters=[])),
        )
        monkeypatch.setattr(engine_module.engine, "_load_model", lambda: None)
        yield
        if engine_module.engine.is_running():
            engine_module.engine.stop(force=True)

    def test_lifecycle_start_refuses_duplicates_and_restarts(self, client: TestClient) -> None:
        assert client.get("/api/engine").json()["state"] == "stopped"

        started = client.post("/api/engine/start")
        assert started.status_code == 200
        assert started.json()["state"] == "running"

        duplicate = client.post("/api/engine/start")
        assert duplicate.status_code == 409
        assert "already running" in duplicate.json()["detail"]["message"]

        stopped = client.post("/api/engine/stop", json={"force": False})
        assert stopped.status_code == 200
        assert stopped.json()["state"] == "stopped"

        assert client.post("/api/engine/stop").status_code == 409
        assert client.post("/api/engine/start").json()["state"] == "running"

    def test_publish_defaults_round_trip_through_settings(self, client: TestClient) -> None:
        settings = client.get("/api/settings").json()
        assert settings["publish"]["default_privacy"] == "private"

        updated = client.put(
            "/api/settings",
            json={
                "publish": {
                    **settings["publish"],
                    "default_privacy": "unlisted",
                    "description_style": "story",
                }
            },
        )
        assert updated.status_code == 200
        assert config.load().publish.default_privacy == "unlisted"
        assert config.load().publish.description_style == "story"


def test_callback_redirects_back_to_the_studio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        publishing_api.oauth,
        "complete",
        lambda code, state: StoredToken(access_token="a", refresh_token="r"),
    )
    response = asyncio.run(publishing_api.complete_callback(code="c", state="s", error=""))
    assert response.status_code == 303
    assert response.headers["location"] == "/publishing?connected=1"


def test_callback_error_is_escaped_into_the_redirect() -> None:
    response = asyncio.run(
        publishing_api.complete_callback(code="", state="", error="access denied")
    )
    assert response.status_code == 303
    assert "access%20denied" in response.headers["location"]
