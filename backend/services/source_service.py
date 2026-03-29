from __future__ import annotations

import logging
from typing import Any, Optional

from backend.repositories.repository_errors import RepositoryError
from backend.repositories.sources_repository import SourcesRepository


logger = logging.getLogger(__name__)


class SourceService:
    def __init__(self, repository: Optional[SourcesRepository] = None) -> None:
        self._repository = repository or SourcesRepository()
        self._allowed_statuses = {"active", "deactivated"}

    async def ensure_default_source(self) -> dict[str, Any]:
        sources = await self._repository.list_sources()
        if not sources:
            logger.info("sources.default.create")
            created = await self._repository.create_source(
                source_name="default",
                status="deactivated",
            )
            await self._repository.deactivate_all_sources()
            activated = await self._repository.activate_source(created["id"])
            if not activated:
                raise RepositoryError("Failed to activate default source")
            return activated

        active_source = await self._repository.get_active_source()
        if active_source:
            return active_source

        default_source = await self._repository.get_source_by_name("default")
        if default_source:
            activated = await self.activate_source_by_id(default_source["id"])
            if not activated:
                raise RepositoryError("Failed to activate default source")
            return activated

        logger.info("sources.default.create")
        created = await self._repository.create_source(source_name="default", status="deactivated")
        await self._repository.deactivate_all_sources()
        activated = await self._repository.activate_source(created["id"])
        if not activated:
            raise RepositoryError("Failed to activate default source")
        return activated

    async def create_source_and_optionally_activate(
        self,
        source_name: str,
        author: Optional[str] = None,
        comment: Optional[str] = None,
        activate: bool = False,
    ) -> dict[str, Any]:
        created = await self._repository.create_source(
            source_name=source_name,
            author=author,
            comment=comment,
            status="deactivated",
        )
        if activate:
            await self._repository.deactivate_all_sources()
            return await self._repository.activate_source(created["id"]) or created
        return created

    async def activate_source_by_id(self, source_id: str) -> Optional[dict[str, Any]]:
        source = await self._repository.get_source(source_id)
        if not source:
            return None
        await self._repository.deactivate_all_sources()
        return await self._repository.activate_source(source_id)

    async def activate_source_by_name(self, source_name: str) -> dict[str, Any]:
        source = await self._repository.get_source_by_name(source_name)
        if not source:
            source = await self._repository.create_source(source_name=source_name, status="deactivated")
        await self._repository.deactivate_all_sources()
        activated = await self._repository.activate_source(source["id"])
        return activated or source

    async def list_sources(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        if status and status not in self._allowed_statuses:
            raise ValueError("Invalid status. Use 'active' or 'deactivated'.")
        return await self._repository.list_sources(status=status)

    async def get_active_source(self) -> Optional[dict[str, Any]]:
        return await self._repository.get_active_source()
