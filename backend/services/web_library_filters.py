from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Optional


LabelLoader = Callable[[], Awaitable[list[dict[str, Any]]]]


class LabelRankingCache:
    """Process-local, lazy cache shared by the Notes and Documents pages."""

    def __init__(self) -> None:
        self._labels: Optional[list[dict[str, Any]]] = None
        self._lock = asyncio.Lock()

    async def get(self, loader: LabelLoader) -> list[dict[str, Any]]:
        if self._labels is None:
            async with self._lock:
                if self._labels is None:
                    self._labels = await loader()
        return [dict(label) for label in self._labels]

    def clear(self) -> None:
        """Clear the cache for process-local tests and controlled restarts."""
        self._labels = None


label_ranking_cache = LabelRankingCache()
