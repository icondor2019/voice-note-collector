from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from backend.services.dashboard_service import DashboardService
from backend.services.session_document_service import render_safe_markdown


def test_render_safe_markdown_removes_scripts_and_keeps_structure() -> None:
    rendered = render_safe_markdown("## Summary\n\nSafe.\n\n<script>alert(1)</script>")
    assert "<h2>Summary</h2>" in rendered
    assert "<script" not in rendered
    assert "alert(1)" in rendered


@pytest.mark.parametrize(
    ("total_seconds", "expected"),
    [
        (0, "0 h 0 min"),
        (3_599, "0 h 59 min"),
        (3_600, "1 h 0 min"),
        (45_240, "12 h 34 min"),
    ],
)
def test_format_recording_duration(total_seconds: int, expected: str) -> None:
    assert DashboardService.format_recording_duration(total_seconds) == expected


@pytest.mark.anyio
async def test_dashboard_summary_combines_existing_repositories() -> None:
    sources = AsyncMock()
    sources.get_web_statistics.return_value = {"total": 5, "active": 4, "archived": 1}
    notes = AsyncMock()
    notes.count_voice_notes.return_value = 12
    notes.get_latest_note_created_at.return_value = datetime.now().astimezone().isoformat()
    notes.get_dashboard_recording_statistics.return_value = {
        "total_duration_seconds": 45_240,
        "pending_notes": 4,
    }
    documents = AsyncMock()
    documents.count_documents.return_value = 3
    service = DashboardService(sources, notes, documents)

    result = await service.get_summary()

    assert result["sources"]["archived"] == 1
    assert result["notes"] == 12
    assert result["documents"] == 3
    assert result["days_since_last_note"] in {0, 1}
    assert result["total_recording_time"] == "12 h 34 min"
    assert result["pending_notes"] == 4


@pytest.mark.anyio
async def test_dashboard_summary_handles_no_notes() -> None:
    sources = AsyncMock()
    sources.get_web_statistics.return_value = {"total": 0, "active": 0, "archived": 0}
    notes = AsyncMock()
    notes.count_voice_notes.return_value = 0
    notes.get_latest_note_created_at.return_value = None
    notes.get_dashboard_recording_statistics.return_value = {
        "total_duration_seconds": 0,
        "pending_notes": 0,
    }
    documents = AsyncMock()
    documents.count_documents.return_value = 0

    result = await DashboardService(sources, notes, documents).get_summary()

    assert result["days_since_last_note"] is None
    assert result["total_recording_time"] == "0 h 0 min"
    assert result["pending_notes"] == 0
