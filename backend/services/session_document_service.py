from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import bleach
import markdown

from backend.repositories.session_documents_repository import SessionDocumentsRepository


ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4",
    "hr", "li", "ol", "p", "pre", "strong", "table", "tbody", "td", "th",
    "thead", "tr", "ul",
}


def render_safe_markdown(content: str) -> str:
    rendered = markdown.markdown(
        content or "",
        extensions=["extra", "sane_lists"],
        output_format="html",
    )
    cleaned = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes={"a": ["href", "title"]},
        protocols={"http", "https", "mailto"},
        strip=True,
    )
    return bleach.linkify(cleaned, skip_tags={"pre", "code"})


class SessionDocumentService:
    def __init__(self, repository: SessionDocumentsRepository) -> None:
        self._repository = repository

    async def list_documents(
        self,
        *,
        source_id: Optional[str] = None,
        source_type: Optional[str] = None,
        source_author: Optional[str] = None,
        source_usage_status: Optional[str] = None,
        status: Optional[str] = None,
        label_ids: Optional[list[int]] = None,
        offset: int = 0,
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        return await self._repository.list_web_documents(
            source_id=source_id,
            source_type=source_type,
            source_author=source_author,
            source_usage_status=source_usage_status,
            status=status,
            label_ids=label_ids,
            offset=offset,
            limit=limit,
        )

    async def get_document(self, document_id: str) -> Optional[dict[str, Any]]:
        document = await self._repository.get_web_document(document_id)
        if document:
            document["rendered_content"] = render_safe_markdown(document.get("content") or "")
        return document
