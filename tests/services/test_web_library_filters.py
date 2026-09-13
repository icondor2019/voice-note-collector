from __future__ import annotations

import asyncio

import pytest

from backend.services.web_library_filters import LabelRankingCache


@pytest.mark.anyio
async def test_label_ranking_cache_loads_once_for_concurrent_callers() -> None:
    cache = LabelRankingCache()
    calls = 0

    async def loader() -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return [{"id": 1, "label": "common", "count": 101}]

    results = await asyncio.gather(cache.get(loader), cache.get(loader))

    assert calls == 1
    assert results[0] == results[1]
    assert results[0][0]["count"] == 101
