from __future__ import annotations

from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from backend.controllers.sources_controller import get_source_service
from backend.repositories.repository_errors import RepositoryError
from main import app


class StubSourceService:
    def __init__(
        self,
        *,
        create_result: Optional[dict[str, Any]] = None,
        list_result: Optional[list[dict[str, Any]]] = None,
        active_result: Optional[dict[str, Any]] = None,
        activate_id_result: Optional[dict[str, Any]] = None,
        activate_name_result: Optional[dict[str, Any]] = None,
        raise_on_create: Optional[Exception] = None,
        raise_on_list: Optional[Exception] = None,
    ) -> None:
        self.create_result = create_result or {}
        self.list_result = list_result or []
        self.active_result = active_result
        self.activate_id_result = activate_id_result
        self.activate_name_result = activate_name_result or {}
        self.raise_on_create = raise_on_create
        self.raise_on_list = raise_on_list
        self.list_status: Optional[str] = None
        self.created_payload: Optional[dict[str, Any]] = None
        self.activated_id: Optional[str] = None
        self.activated_name: Optional[str] = None

    async def create_source_and_optionally_activate(
        self,
        *,
        source_name: str,
        author: Optional[str] = None,
        comment: Optional[str] = None,
        activate: bool = False,
    ) -> dict[str, Any]:
        if self.raise_on_create:
            raise self.raise_on_create
        self.created_payload = {
            "source_name": source_name,
            "author": author,
            "comment": comment,
            "activate": activate,
        }
        return self.create_result

    async def list_sources(self, *, status: Optional[str] = None) -> list[dict[str, Any]]:
        if self.raise_on_list:
            raise self.raise_on_list
        self.list_status = status
        return self.list_result

    async def get_active_source(self) -> Optional[dict[str, Any]]:
        return self.active_result

    async def activate_source_by_id(self, source_id: str) -> Optional[dict[str, Any]]:
        self.activated_id = source_id
        return self.activate_id_result

    async def activate_source_by_name(self, source_name: str) -> dict[str, Any]:
        self.activated_name = source_name
        return self.activate_name_result


@pytest.fixture
def source_service_override():
    stub = StubSourceService()

    def override_service() -> StubSourceService:
        return stub

    app.dependency_overrides[get_source_service] = override_service
    yield stub
    app.dependency_overrides.clear()


class TestSourcesEndpoints:
    def test_create_source_returns_created_payload(self, source_service_override: StubSourceService) -> None:
        source_service_override.create_result = {
            "id": "source-1",
            "source_name": "Daily",
            "status": "deactivated",
        }
        client = TestClient(app)

        response = client.post(
            "/api/sources",
            json={
                "source_name": "Daily",
                "author": "Alex",
                "comment": "Morning",
                "activate": False,
            },
        )

        assert response.status_code == 201
        assert response.json() == source_service_override.create_result
        assert source_service_override.created_payload == {
            "source_name": "Daily",
            "author": "Alex",
            "comment": "Morning",
            "activate": False,
        }

    def test_create_source_returns_503_on_repository_error(self, source_service_override: StubSourceService) -> None:
        source_service_override.raise_on_create = RepositoryError("down")
        client = TestClient(app)

        response = client.post(
            "/api/sources",
            json={"source_name": "Daily", "activate": False},
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "Supabase unavailable"

    def test_list_sources_uses_status_filter(self, source_service_override: StubSourceService) -> None:
        source_service_override.list_result = [
            {"id": "source-1", "status": "active"},
        ]
        client = TestClient(app)

        response = client.get("/api/sources", params={"status": "active"})

        assert response.status_code == 200
        assert response.json() == source_service_override.list_result
        assert source_service_override.list_status == "active"

    def test_get_active_source_returns_404_when_missing(self, source_service_override: StubSourceService) -> None:
        source_service_override.active_result = None
        client = TestClient(app)

        response = client.get("/api/sources/active")

        assert response.status_code == 404
        assert response.json()["detail"] == "Active source not found"

    def test_activate_source_returns_404_when_missing(self, source_service_override: StubSourceService) -> None:
        source_service_override.activate_id_result = None
        client = TestClient(app)

        response = client.post("/api/sources/source-404/activate")

        assert response.status_code == 404
        assert response.json()["detail"] == "Source not found"
        assert source_service_override.activated_id == "source-404"

    def test_activate_source_by_name_returns_payload(self, source_service_override: StubSourceService) -> None:
        source_service_override.activate_name_result = {
            "id": "source-2",
            "source_name": "Ideas",
            "status": "active",
        }
        client = TestClient(app)

        response = client.post(
            "/api/sources/activate-by-name",
            json={"source_name": "Ideas"},
        )

        assert response.status_code == 200
        assert response.json() == source_service_override.activate_name_result
        assert source_service_override.activated_name == "Ideas"
