from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.controllers.web_controller import (
    get_dashboard_service,
    get_labels_repository,
    get_session_builder_service,
    get_session_document_service,
    get_sources_repository,
    get_voice_note_service,
    get_web_auth_service,
)
from backend.services.web_auth_service import WebAuthError, WebSession
from backend.services.session_builder_service import EnrichmentIncompleteError, NoValidNotesError
from backend.services.web_library_filters import label_ranking_cache
from main import app


class StubAuth:
    def __init__(self, *, valid: bool = True, refreshed: bool = False) -> None:
        self.valid = valid
        self.refreshed = refreshed

    async def validate_session(self, access_token: str | None, refresh_token: str | None) -> WebSession:
        if not self.valid:
            raise WebAuthError("required")
        return WebSession("owner@example.com", "new-access", "new-refresh", self.refreshed)

    async def sign_in(self, email: str, password: str) -> WebSession:
        if password == "wrong":
            raise WebAuthError("invalid")
        return WebSession(email, "access", "refresh")

    async def sign_out(self, access_token: str | None, refresh_token: str | None) -> None:
        return None


class StubDashboard:
    async def get_summary(self) -> dict[str, Any]:
        return {
            "sources": {"total": 3, "active": 2, "archived": 1},
            "notes": 14,
            "documents": 4,
            "days_since_last_note": 2,
            "total_recording_time": "12 h 34 min",
            "pending_notes": 6,
        }


class StubSources:
    async def list_sources(self) -> list[dict[str, Any]]:
        return [{
            "id": "s1", "source_name": "A source", "type": "video",
            "author": "Miguel Anxo Bastos", "usage_status": "active",
        }]


class StubLabels:
    async def list_labels(self) -> list[dict[str, Any]]:
        return [
            {"id": index, "label": "architecture" if index == 1 else f"label-{index}", "count": 13 - index}
            for index in range(1, 13)
        ]


class StubNotes:
    async def list_web_notes(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": "n1", "source": {"id": "s1", "source_name": "A source", "author": "Note Author"}, "source_id": "s1", "created_at": "2026-09-10T10:00:00Z", "display_title": "A note", "preview": "Raw idea", "details": {"status": "enriched"}, "labels": [{"id": 1, "label": "architecture"}], "build_eligible": True, "build_block_reason": None}]

    async def get_web_note(self, note_id: str) -> dict[str, Any] | None:
        if note_id == "missing":
            return None
        return {"id": note_id, "source": {"id": "s1", "source_name": "A source", "author": "Note Author"}, "source_id": "s1", "created_at": "2026-09-10T10:00:00Z", "display_title": "A note", "raw_text": "Raw transcription", "clean_text": None, "details": {"status": "created"}, "labels": [], "message_id": 1, "duration_seconds": 12, "build_eligible": True, "build_block_reason": None}


class StubDocuments:
    async def list_documents(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": "d1", "source": {"source_name": "A source", "author": "Document Author"}, "created_at": "2026-09-10T10:00:00Z", "title": "A document", "preview": "Structured ideas", "status": "ready", "labels": [{"id": 1, "label": "architecture", "count": 3}]}]

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        if document_id == "missing":
            return None
        return {"id": document_id, "source": {"source_name": "A source", "author": "Document Author"}, "created_at": "2026-09-10T10:00:00Z", "title": "A document", "status": "ready", "labels": [{"id": 1, "label": "architecture", "count": 3}], "rendered_content": "<h2>Summary</h2><p>Safe content</p>"}


class StubBuilder:
    def __init__(self) -> None:
        from unittest.mock import AsyncMock

        self.build = AsyncMock(return_value={"id": "doc-123"})


class PaginatedNotes(StubNotes):
    async def list_web_notes(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": f"n{index}", "source": {"source_name": "A source"},
                "created_at": "2026-09-10T10:00:00Z", "display_title": f"Note {index}",
                "preview": "Raw idea", "details": {"status": "enriched"}, "labels": [],
            }
            for index in range(25)
        ]


@pytest.fixture(autouse=True)
def web_overrides() -> Any:
    label_ranking_cache.clear()
    app.dependency_overrides[get_web_auth_service] = lambda: StubAuth()
    app.dependency_overrides[get_dashboard_service] = lambda: StubDashboard()
    app.dependency_overrides[get_sources_repository] = lambda: StubSources()
    app.dependency_overrides[get_labels_repository] = lambda: StubLabels()
    app.dependency_overrides[get_voice_note_service] = lambda: StubNotes()
    app.dependency_overrides[get_session_document_service] = lambda: StubDocuments()
    app.dependency_overrides[get_session_builder_service] = lambda: StubBuilder()
    yield
    app.dependency_overrides.clear()
    label_ranking_cache.clear()


def authenticated_client() -> TestClient:
    client = TestClient(app)
    client.cookies.set("vnc_access_token", "access")
    client.cookies.set("vnc_refresh_token", "refresh")
    return client


def test_get_voice_note_service_uses_client_backed_dependencies() -> None:
    client = object()

    service = get_voice_note_service(client)

    assert service._repository._client is client
    assert service._source_service._repository._client is client


class TestWebAuthentication:
    def test_login_page_sets_csrf_and_renders_token(self) -> None:
        client = TestClient(app)
        response = client.get("/login")
        assert response.status_code == 200
        token = response.cookies["vnc_csrf_token"]
        assert token in response.text

    def test_login_requires_matching_csrf(self) -> None:
        response = TestClient(app).post("/login", data={"email": "owner@example.com", "password": "secret", "csrf_token": "wrong"})
        assert response.status_code == 403

    def test_login_sets_http_only_auth_cookies(self) -> None:
        client = TestClient(app)
        csrf = client.get("/login").cookies["vnc_csrf_token"]
        response = client.post("/login", data={"email": "owner@example.com", "password": "secret", "csrf_token": csrf}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert "HttpOnly" in response.headers.get_list("set-cookie")[0]

    def test_protected_page_redirects_when_session_invalid(self) -> None:
        app.dependency_overrides[get_web_auth_service] = lambda: StubAuth(valid=False)
        response = TestClient(app).get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


class TestWebPages:
    def test_dashboard_renders_metrics_and_security_headers(self) -> None:
        response = authenticated_client().get("/")
        assert response.status_code == 200
        assert "14" in response.text and "4" in response.text
        assert "Recording time" in response.text
        assert "12 h 34 min" in response.text
        assert "Pending" in response.text and ">6<" in response.text
        assert 'href="/notes?status=created"' in response.text
        assert "default-src 'self'" in response.headers["content-security-policy"]
        assert response.cookies.get("vnc_csrf_token") in response.text

    def test_refreshed_session_replaces_auth_cookies(self) -> None:
        app.dependency_overrides[get_web_auth_service] = lambda: StubAuth(refreshed=True)
        response = authenticated_client().get("/")
        assert response.cookies["vnc_access_token"] == "new-access"
        assert response.cookies["vnc_refresh_token"] == "new-refresh"

    def test_notes_page_renders_note_and_label(self) -> None:
        response = authenticated_client().get("/notes")
        assert response.status_code == 200
        assert "A note" in response.text
        assert "data-note-selection" in response.text
        assert 'data-selectable="true"' in response.text
        assert "Build from selected notes" in response.text
        assert "architecture" in response.text
        assert "A source · Note Author" in response.text
        assert 'class="status-chip">enriched</span>' in response.text
        assert 'class="chip">architecture</span>' in response.text

    def test_notes_filters_are_unified_and_explicit(self) -> None:
        response = authenticated_client().get(
            "/notes?source_id=s1&source_type=video&source_author=Miguel%20Anxo%20Bastos"
            "&source_usage_status=active&status=enriched&label_id=12"
        )

        assert response.status_code == 200
        assert 'data-library-filters' in response.text
        assert 'data-more-labels-region hidden' in response.text
        assert 'data-has-hidden-selection="true"' in response.text
        assert 'type="submit">Apply filters' in response.text
        assert 'name="source_author"' not in response.text
        assert "filter-panel" not in response.text
        assert "filter-backdrop" not in response.text
        assert "See more labels" in response.text

    def test_documents_use_the_same_unified_filter_interface(self) -> None:
        response = authenticated_client().get("/documents?status=ready")

        assert response.status_code == 200
        assert 'type="submit">Apply filters' in response.text
        assert "Document status" in response.text
        assert 'name="source_author"' not in response.text

    def test_load_more_preserves_every_active_filter(self) -> None:
        app.dependency_overrides[get_voice_note_service] = lambda: PaginatedNotes()
        response = authenticated_client().get(
            "/notes?source_id=s1&source_type=video&source_author=Miguel%20Anxo%20Bastos"
            "&source_usage_status=active&status=enriched&label_id=1&label_id=2"
        )

        markup = html.unescape(response.text)
        assert "offset=24" in markup
        assert "source_id=s1" in markup
        assert "source_type=video" in markup
        assert "source_author=Miguel+Anxo+Bastos" in markup
        assert "source_usage_status=active" in markup
        assert "status=enriched" in markup
        assert "label_id=1&label_id=2" in markup

    def test_note_detail_404(self) -> None:
        assert authenticated_client().get("/notes/missing").status_code == 404

    def test_notes_build_requires_csrf_and_delegates_to_builder(self) -> None:
        client = authenticated_client()
        notes_response = client.get("/notes")
        csrf_token = notes_response.cookies["vnc_csrf_token"]
        builder = StubBuilder()
        app.dependency_overrides[get_session_builder_service] = lambda: builder

        response = client.post(
            "/notes/build",
            json={"source_id": "a0dcea10-ca65-4314-af78-ce096824aff1", "note_ids": ["b0dcea10-ca65-4314-af78-ce096824aff1"]},
            headers={"X-CSRF-Token": csrf_token},
        )

        assert response.status_code == 201
        assert response.json() == {"document_id": "doc-123", "redirect_url": "/documents/doc-123"}
        builder.build.assert_awaited_once_with(
            source_id="a0dcea10-ca65-4314-af78-ce096824aff1",
            note_ids=["b0dcea10-ca65-4314-af78-ce096824aff1"],
        )

    def test_notes_build_rejects_invalid_csrf(self) -> None:
        response = authenticated_client().post(
            "/notes/build",
            json={"source_id": "a0dcea10-ca65-4314-af78-ce096824aff1", "note_ids": ["b0dcea10-ca65-4314-af78-ce096824aff1"]},
            headers={"X-CSRF-Token": "wrong"},
        )
        assert response.status_code == 403

    def test_notes_build_requires_web_session(self) -> None:
        app.dependency_overrides[get_web_auth_service] = lambda: StubAuth(valid=False)
        response = TestClient(app).post(
            "/notes/build",
            json={"source_id": "a0dcea10-ca65-4314-af78-ce096824aff1", "note_ids": ["b0dcea10-ca65-4314-af78-ce096824aff1"]},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    @pytest.mark.parametrize(
        ("failure", "status_code"),
        [
            (NoValidNotesError("No valid notes"), 400),
            (EnrichmentIncompleteError("Enrichment incomplete"), 503),
        ],
    )
    def test_notes_build_translates_builder_failures(self, failure: Exception, status_code: int) -> None:
        from unittest.mock import AsyncMock

        builder = StubBuilder()
        builder.build = AsyncMock(side_effect=failure)
        app.dependency_overrides[get_session_builder_service] = lambda: builder
        client = authenticated_client()
        csrf_token = client.get("/notes").cookies["vnc_csrf_token"]
        response = client.post(
            "/notes/build",
            json={"source_id": "a0dcea10-ca65-4314-af78-ce096824aff1", "note_ids": ["b0dcea10-ca65-4314-af78-ce096824aff1"]},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert response.status_code == status_code

    def test_note_detail_aligns_status_after_date_and_uses_large_labels(self) -> None:
        response = authenticated_client().get("/notes/n1")
        assert response.status_code == 200
        assert "A source · Note Author" in response.text
        assert 'class="detail-meta"><span>2026-09-10</span><span class="status-chip">created</span>' in response.text
        assert 'class="chips large"' in response.text

    def test_note_detail_falls_back_when_source_author_is_missing(self) -> None:
        class MissingAuthorNotes(StubNotes):
            async def get_web_note(self, note_id: str) -> dict[str, Any] | None:
                note = await super().get_web_note(note_id)
                if note:
                    note["source"]["author"] = ""
                return note

        app.dependency_overrides[get_voice_note_service] = lambda: MissingAuthorNotes()
        response = authenticated_client().get("/notes/n1")
        assert response.status_code == 200
        assert "A source · Unknown author" in response.text

    def test_documents_are_separate_and_show_frequency(self) -> None:
        response = authenticated_client().get("/documents")
        assert response.status_code == 200
        assert "A document" in response.text
        assert "architecture · 3" in response.text
        assert "A source · Document Author" in response.text
        assert 'class="status-chip">ready</span>' in response.text

    def test_library_cards_fall_back_when_source_author_is_missing(self) -> None:
        class MissingAuthorNotes(StubNotes):
            async def list_web_notes(self, **kwargs: Any) -> list[dict[str, Any]]:
                notes = await super().list_web_notes(**kwargs)
                notes[0]["source"]["author"] = ""
                return notes

        class MissingAuthorDocuments(StubDocuments):
            async def list_documents(self, **kwargs: Any) -> list[dict[str, Any]]:
                documents = await super().list_documents(**kwargs)
                documents[0]["source"]["author"] = None
                return documents

        app.dependency_overrides[get_voice_note_service] = lambda: MissingAuthorNotes()
        notes_response = authenticated_client().get("/notes")
        app.dependency_overrides[get_session_document_service] = lambda: MissingAuthorDocuments()
        documents_response = authenticated_client().get("/documents")

        assert "A source · Unknown author" in notes_response.text
        assert "A source · Unknown author" in documents_response.text

    def test_document_detail_has_safe_content_and_audio_placeholder(self) -> None:
        response = authenticated_client().get("/documents/d1")
        assert response.status_code == 200
        assert "A source · Document Author" in response.text
        assert "Safe content" in response.text
        assert "Coming soon" in response.text
        assert 'class="detail-meta"><span>2026-09-10</span><span class="status-chip">ready</span>' in response.text
        assert 'class="chips large"' in response.text

    def test_document_detail_falls_back_when_source_author_is_missing(self) -> None:
        class MissingAuthorDocuments(StubDocuments):
            async def get_document(self, document_id: str) -> dict[str, Any] | None:
                document = await super().get_document(document_id)
                if document:
                    document["source"]["author"] = None
                return document

        app.dependency_overrides[get_session_document_service] = lambda: MissingAuthorDocuments()
        response = authenticated_client().get("/documents/d1")
        assert response.status_code == 200
        assert "A source · Unknown author" in response.text


def test_filter_javascript_only_controls_label_visibility() -> None:
    javascript = (
        Path(__file__).resolve().parents[2] / "frontend" / "static" / "js" / "app.js"
    ).read_text(encoding="utf-8")

    assert 'Show less labels' in javascript
    assert 'See more labels' in javascript
    assert 'moreToggle.dataset.hasHiddenSelection' in javascript
    assert "sessionStorage" not in javascript
    assert "form.requestSubmit()" not in javascript
    assert "data-note-checkbox" in javascript
