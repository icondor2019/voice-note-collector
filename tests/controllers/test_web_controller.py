from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.controllers.web_controller import (
    get_dashboard_service,
    get_labels_repository,
    get_session_document_service,
    get_sources_repository,
    get_voice_note_service,
    get_web_auth_service,
)
from backend.services.web_auth_service import WebAuthError, WebSession
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
        return {"sources": {"total": 3, "active": 2, "archived": 1}, "notes": 14, "documents": 4, "days_since_last_note": 2}


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
        return [{"id": "n1", "source": {"source_name": "A source"}, "created_at": "2026-09-10T10:00:00Z", "display_title": "A note", "preview": "Raw idea", "details": {"status": "enriched"}, "labels": [{"id": 1, "label": "architecture"}]}]

    async def get_web_note(self, note_id: str) -> dict[str, Any] | None:
        if note_id == "missing":
            return None
        return {"id": note_id, "source": {"source_name": "A source"}, "created_at": "2026-09-10T10:00:00Z", "display_title": "A note", "raw_text": "Raw transcription", "clean_text": None, "details": {"status": "created"}, "labels": [], "message_id": 1, "duration_seconds": 12}


class StubDocuments:
    async def list_documents(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": "d1", "source": {"source_name": "A source"}, "created_at": "2026-09-10T10:00:00Z", "title": "A document", "preview": "Structured ideas", "status": "ready", "labels": [{"id": 1, "label": "architecture", "count": 3}]}]

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        if document_id == "missing":
            return None
        return {"id": document_id, "source": {"source_name": "A source"}, "created_at": "2026-09-10T10:00:00Z", "title": "A document", "status": "ready", "labels": [{"id": 1, "label": "architecture", "count": 3}], "rendered_content": "<h2>Summary</h2><p>Safe content</p>"}


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
        assert "architecture" in response.text

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

    def test_documents_are_separate_and_show_frequency(self) -> None:
        response = authenticated_client().get("/documents")
        assert response.status_code == 200
        assert "A document" in response.text
        assert "architecture · 3" in response.text

    def test_document_detail_has_safe_content_and_audio_placeholder(self) -> None:
        response = authenticated_client().get("/documents/d1")
        assert response.status_code == 200
        assert "Safe content" in response.text
        assert "Coming soon" in response.text


def test_filter_javascript_only_controls_label_visibility() -> None:
    javascript = (
        Path(__file__).resolve().parents[2] / "frontend" / "static" / "js" / "app.js"
    ).read_text(encoding="utf-8")

    assert 'Show less labels' in javascript
    assert 'See more labels' in javascript
    assert 'moreToggle.dataset.hasHiddenSelection' in javascript
    assert "sessionStorage" not in javascript
    assert "form.requestSubmit()" not in javascript
    assert "addEventListener(\"change\"" not in javascript
