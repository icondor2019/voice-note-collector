"""Tests for URL source capture feature."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from backend.models.source import SourceCreateByAgentRequest, VALID_PREFIXES, VALID_SOURCE_TYPES
from backend.services.source_create_agent import (
    SourceCreateAgent,
    SourceCreateContext,
    SourceCreateStep,
    _suggest_source_name,
)
from backend.services.source_type_resolver import SourceTypeResolver
from backend.services.url_detector_service import UrlDetectorService


# ── UrlDetectorService ────────────────────────────────────────────────────────


class TestUrlDetectorService:
    def test_is_url_https(self) -> None:
        assert UrlDetectorService.is_url("https://www.youtube.com/watch?v=abc123") is True

    def test_is_url_http(self) -> None:
        assert UrlDetectorService.is_url("http://example.com/page") is True

    def test_is_url_www(self) -> None:
        assert UrlDetectorService.is_url("www.youtube.com/watch?v=abc") is True

    def test_is_url_bare_domain(self) -> None:
        assert UrlDetectorService.is_url("youtube.com/watch?v=abc") is True

    def test_is_url_with_whitespace(self) -> None:
        assert UrlDetectorService.is_url("  https://youtube.com  ") is True

    def test_is_url_instagram(self) -> None:
        assert UrlDetectorService.is_url("https://instagram.com/p/xyz") is True

    def test_is_url_returns_false_for_url_plus_text(self) -> None:
        assert UrlDetectorService.is_url("check this https://youtube.com/watch?v=abc") is False

    def test_is_url_returns_false_for_text_before_url(self) -> None:
        assert UrlDetectorService.is_url("look at https://example.com") is False

    def test_is_url_returns_false_for_plain_text(self) -> None:
        assert UrlDetectorService.is_url("hello world") is False

    def test_is_url_returns_false_for_command(self) -> None:
        assert UrlDetectorService.is_url("/create my source") is False

    def test_is_url_returns_false_for_empty_string(self) -> None:
        assert UrlDetectorService.is_url("") is False

    def test_is_url_returns_false_for_whitespace_only(self) -> None:
        assert UrlDetectorService.is_url("   ") is False

    def test_extract_url_returns_url(self) -> None:
        url = "https://youtube.com/watch?v=abc"
        assert UrlDetectorService.extract_url(url) == url

    def test_extract_url_strips_whitespace(self) -> None:
        assert UrlDetectorService.extract_url("  https://youtube.com  ") == "https://youtube.com"

    def test_extract_url_returns_empty_for_non_url(self) -> None:
        assert UrlDetectorService.extract_url("not a url") == ""


# ── SourceTypeResolver ────────────────────────────────────────────────────────


class TestSourceTypeResolver:
    def test_youtube_com(self) -> None:
        assert SourceTypeResolver.resolve_type("https://www.youtube.com/watch?v=abc") == "youtube"

    def test_youtu_be(self) -> None:
        assert SourceTypeResolver.resolve_type("https://youtu.be/abc") == "youtube"

    def test_instagram(self) -> None:
        assert SourceTypeResolver.resolve_type("https://instagram.com/p/xyz") == "instagram"

    def test_facebook(self) -> None:
        assert SourceTypeResolver.resolve_type("https://facebook.com/post/123") == "facebook"

    def test_fb_com(self) -> None:
        assert SourceTypeResolver.resolve_type("https://fb.com/post/123") == "facebook"

    def test_linkedin(self) -> None:
        assert SourceTypeResolver.resolve_type("https://linkedin.com/in/user") == "linkedin"

    def test_generic_web(self) -> None:
        assert SourceTypeResolver.resolve_type("https://example.com/page") == "web"

    def test_bare_domain(self) -> None:
        assert SourceTypeResolver.resolve_type("youtube.com/watch?v=abc") == "youtube"

    def test_m_youtube(self) -> None:
        assert SourceTypeResolver.resolve_type("https://m.youtube.com/watch?v=abc") == "youtube"


# ── SourceCreateByAgentRequest ────────────────────────────────────────────────


class TestSourceCreateByAgentRequest:
    def test_valid_youtube_prefix(self) -> None:
        req = SourceCreateByAgentRequest(
            source_name="yt-cool-video",
            type="youtube",
            url="https://youtube.com/watch?v=abc",
        )
        assert req.source_name == "yt-cool-video"
        assert req.type == "youtube"

    def test_valid_all_types(self) -> None:
        prefix_map = {
            "youtube": "yt",
            "instagram": "ig",
            "facebook": "fb",
            "linkedin": "lkn",
            "web": "wb",
            "book": "bk",
            "course": "cr",
            "thought": "th",
        }
        for source_type, prefix in prefix_map.items():
            req = SourceCreateByAgentRequest(
                source_name=f"{prefix}-test-item",
                type=source_type,
            )
            assert req.type == source_type

    def test_invalid_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="must start with"):
            SourceCreateByAgentRequest(
                source_name="invalid-name",
                type="youtube",
            )

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid source type"):
            SourceCreateByAgentRequest(
                source_name="yt-cool-video",
                type="invalid_type",
            )

    def test_optional_fields_default_none(self) -> None:
        req = SourceCreateByAgentRequest(
            source_name="yt-cool-video",
            type="youtube",
        )
        assert req.url is None
        assert req.author is None
        assert req.comment is None


# ── Source Name Suggestion ────────────────────────────────────────────────────


class TestSourceNameSuggestion:
    def test_youtube_url_suggestion(self) -> None:
        name = _suggest_source_name("youtube", "https://youtube.com/watch?v=abc")
        assert name.startswith("yt-")
        parts = name.split("-")
        assert len(parts) == 3

    def test_instagram_url_suggestion(self) -> None:
        name = _suggest_source_name("instagram", "https://instagram.com/p/xyz")
        assert name.startswith("ig-")
        parts = name.split("-")
        assert len(parts) == 3

    def test_no_url_suggestion(self) -> None:
        name = _suggest_source_name("thought")
        assert name.startswith("th-")
        parts = name.split("-")
        assert len(parts) == 3

    def test_web_url_with_path(self) -> None:
        name = _suggest_source_name("web", "https://example.com/blog/my-article")
        assert name.startswith("wb-")
        parts = name.split("-")
        assert len(parts) == 3

    def test_bare_domain(self) -> None:
        name = _suggest_source_name("youtube", "youtube.com/watch?v=test")
        assert name.startswith("yt-")


# ── SourceCreateAgent ─────────────────────────────────────────────────────────


class TestSourceCreateAgent:
    def _make_agent(self, source_service: AsyncMock | None = None) -> SourceCreateAgent:
        svc = source_service or AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={"id": "1", "source_name": "yt-test-video", "type": "youtube"}
        )
        return SourceCreateAgent(source_service=svc)

    @pytest.mark.anyio
    async def test_create_source_from_url_returns_confirmation(self) -> None:
        agent = self._make_agent()
        reply = await agent.create_source_from_url("https://youtube.com/watch?v=abc", user_id=1)
        assert "youtube" in reply
        assert "https://youtube.com/watch?v=abc" in reply
        assert "✅ Source created" in reply
        # No pending context after deterministic creation
        assert agent.get_pending_context(1) is None

    @pytest.mark.anyio
    async def test_create_source_from_url_duplicate_url(self) -> None:
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(
            return_value={"source_name": "existing-source"}
        )
        agent = SourceCreateAgent(source_service=svc)
        reply = await agent.create_source_from_url("https://youtube.com/watch?v=abc", user_id=1)
        assert "already exists" in reply
        assert agent.get_pending_context(1) is None

    @pytest.mark.anyio
    async def test_start_create_flow_no_args(self) -> None:
        agent = self._make_agent()
        reply = await agent.start_create_flow(user_id=1)
        assert "type" in reply.lower() or "What type" in reply
        assert agent.get_pending_context(1) is not None

    @pytest.mark.anyio
    async def test_start_create_flow_with_url(self) -> None:
        agent = self._make_agent()
        reply = await agent.start_create_flow(user_id=1, name_or_url="https://youtube.com/watch?v=abc")
        assert "youtube" in reply
        # Deterministic creation: no pending context
        assert agent.get_pending_context(1) is None

    @pytest.mark.anyio
    async def test_start_create_flow_with_prefixed_name(self) -> None:
        agent = self._make_agent()
        reply = await agent.start_create_flow(user_id=1, name_or_url="yt-my-video")
        assert "yt-my-video" in reply
        ctx = agent.get_pending_context(1)
        assert ctx is not None
        assert ctx.source_name == "yt-my-video"

    @pytest.mark.anyio
    async def test_start_create_flow_with_invalid_name(self) -> None:
        agent = self._make_agent()
        reply = await agent.start_create_flow(user_id=1, name_or_url="no-prefix")
        assert "prefix" in reply.lower()

    @pytest.mark.anyio
    async def test_handle_response_no_pending(self) -> None:
        agent = self._make_agent()
        reply = await agent.handle_response("hello", user_id=999)
        assert "No pending" in reply

    @pytest.mark.anyio
    async def test_full_flow_url_create_then_enrich(self) -> None:
        """Test the decoupled flow: URL create → /update → name → author → comment → confirm → update."""
        agent = self._make_agent()

        # Step 1: Deterministic URL creation — no pending context
        reply = await agent.create_source_from_url("https://youtube.com/watch?v=abc", user_id=1)
        assert "✅ Source created" in reply
        assert agent.get_pending_context(1) is None

        # Step 2: /update starts enrichment for the active source
        active_source = {
            "id": "1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
            "author": None,
            "comment": None,
        }
        reply = await agent.start_enrich_flow(1, active_source)
        assert "yt-test-video" in reply
        ctx = agent.get_pending_context(1)
        assert ctx is not None
        assert ctx.source_id == "1"

        # Step 3: Accept suggested name
        reply = await agent.handle_response("yes", user_id=1)
        assert "author" in reply.lower()

        # Step 4: Provide author
        reply = await agent.handle_response("John Doe", user_id=1)
        assert "comment" in reply.lower()

        # Step 5: Provide comment — shows confirmation summary (no auto-apply)
        reply = await agent.handle_response("Great tutorial", user_id=1)
        assert "Here's what I'll update" in reply
        assert "yt-test-video" in reply
        assert "John Doe" in reply
        assert "Great tutorial" in reply
        assert "Anything else to add" in reply

        # Context should still be pending (awaiting confirmation)
        assert agent.get_pending_context(1) is not None

        # update_source should NOT have been called yet
        agent._source_service.update_source.assert_not_awaited()

        # Step 6: Confirm — applies changes
        reply = await agent.handle_response("confirm", user_id=1)
        assert "✅ Source updated" in reply
        assert "We are now in note mode" in reply

        # Context should be cleared
        assert agent.get_pending_context(1) is None

        # Verify update_source was called
        agent._source_service.update_source.assert_awaited_once()

    @pytest.mark.anyio
    async def test_always_ask_rule_author(self) -> None:
        """Verify the agent asks for author even though it's optional."""
        agent = self._make_agent()
        active_source = {
            "id": "1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, active_source)
        # Accept name → should ask for author
        reply = await agent.handle_response("yes", user_id=1)
        # After name step, agent MUST ask for author
        assert "author" in reply.lower()

    @pytest.mark.anyio
    async def test_always_ask_rule_comment(self) -> None:
        """Verify the agent asks for comment even though it's optional."""
        agent = self._make_agent()
        active_source = {
            "id": "1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, active_source)
        await agent.handle_response("yes", user_id=1)  # accept name → asks author
        reply = await agent.handle_response("skip", user_id=1)  # skip author → asks comment
        # After author step, agent MUST ask for comment
        assert "comment" in reply.lower()

    @pytest.mark.anyio
    async def test_skip_author_and_comment(self) -> None:
        """User can skip optional fields."""
        agent = self._make_agent()
        active_source = {
            "id": "1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, active_source)
        await agent.handle_response("yes", user_id=1)  # accept name
        await agent.handle_response("skip", user_id=1)  # skip author
        reply = await agent.handle_response("skip", user_id=1)  # skip comment → confirmation
        assert "Here's what I'll update" in reply
        assert "(empty)" in reply  # empty fields shown
        # Confirm to apply
        reply = await agent.handle_response("apply", user_id=1)
        assert "✅ Source updated" in reply

    @pytest.mark.anyio
    async def test_clear_pending(self) -> None:
        agent = self._make_agent()
        active_source = {
            "id": "1",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, active_source)
        assert agent.get_pending_context(1) is not None
        agent.clear_pending(1)
        assert agent.get_pending_context(1) is None


# ── SourceCreateContext ───────────────────────────────────────────────────────


class TestSourceCreateContext:
    def test_to_dict_and_back(self) -> None:
        ctx = SourceCreateContext(
            source_type="youtube",
            url="https://youtube.com/watch?v=abc",
            suggested_name="yt-cool-video",
            source_id="abc-123",
            step=SourceCreateStep.AWAITING_AUTHOR,
        )
        d = ctx.to_dict()
        restored = SourceCreateContext.from_dict(d)
        assert restored.source_type == "youtube"
        assert restored.url == "https://youtube.com/watch?v=abc"
        assert restored.source_id == "abc-123"
        assert restored.step == SourceCreateStep.AWAITING_AUTHOR
