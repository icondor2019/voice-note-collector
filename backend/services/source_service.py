from __future__ import annotations

from loguru import logger
from typing import Any, Optional

from backend.repositories.repository_errors import RepositoryError
from backend.repositories.sources_repository import SourcesRepository

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
        url: Optional[str] = None,
        type: Optional[str] = None,
    ) -> dict[str, Any]:
        # Duplicate URL check
        if url:
            existing = await self._repository.get_source_by_url(url)
            if existing:
                raise ValueError(
                    f"A source with URL '{url}' already exists: "
                    f"'{existing.get('source_name', 'unknown')}'"
                )

        created = await self._repository.create_source(
            source_name=source_name,
            author=author,
            comment=comment,
            status="deactivated",
            url=url,
            type=type,
        )
        if activate:
            await self._repository.deactivate_all_sources()
            return await self._repository.activate_source(created["id"]) or created
        return created

    async def update_source(
        self,
        source_id: str,
        source_name: Optional[str] = None,
        author: Optional[str] = None,
        comment: Optional[str] = None,
        type: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Update a source's mutable fields. Delegates to the repository.

        When type is provided and source_name is not, the name prefix is
        re-derived from the new type's prefix map.
        """
        return await self._repository.update_source(
            source_id=source_id,
            source_name=source_name,
            author=author,
            comment=comment,
            type=type,
        )

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
