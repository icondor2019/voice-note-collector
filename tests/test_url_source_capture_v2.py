"""Tests for url_source_capture v2 fixes.

Covers:
- Create-immediately-then-enrich flow
- Routing fix (source_create_context hydration)
- update_source() repository and service methods
- SourceUpdateRequest model
- LLM-driven agent with detailed system prompt
- Name suggestions are short slugs
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from backend.models.source import SourceUpdateRequest, VALID_PREFIXES
from backend.services.source_create_agent import (
    SOURCE_CREATE_SYSTEM_PROMPT,
    SourceCreateAgent,
    SourceCreateContext,
    SourceCreateStep,
    _extract_json_block,
    _suggest_source_name,
)
from backend.services.multi_agent_service import MultiAgentService
from backend.models.agent import AgentResult, MultiAgentResult


def _make_llm_response(
    reply: str = "",
    fields: dict | None = None,
    intention: str = "capture",
) -> str:
    """Build a JSON string that the LLM would return."""
    if fields is None:
        fields = {}
    return json.dumps({
        "reply": reply,
        "fields": fields,
        "intention": intention,
    })


# ── SourceUpdateRequest ──────────────────────────────────────────────────────


class TestSourceUpdateRequest:
    def test_all_fields_optional(self) -> None:
        req = SourceUpdateRequest()
        assert req.source_name is None
        assert req.author is None
        assert req.comment is None

    def test_with_source_name_valid_prefix(self) -> None:
        req = SourceUpdateRequest(source_name="yt-new-name")
        assert req.source_name == "yt-new-name"

    def test_with_invalid_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="must start with"):
            SourceUpdateRequest(source_name="invalid-name")

    def test_with_author_only(self) -> None:
        req = SourceUpdateRequest(author="John Doe")
        assert req.author == "John Doe"
        assert req.source_name is None

    def test_with_comment_only(self) -> None:
        req = SourceUpdateRequest(comment="Great stuff")
        assert req.comment == "Great stuff"


# ── Create-immediately-then-enrich ──────────────────────────────────────────


class TestCreateImmediatelyThenEnrich:
    """v2: Source is created IMMEDIATELY on URL detection, enrichment via /update."""

    def _make_agent(self) -> SourceCreateAgent:
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(return_value=None)
        svc._repository.get_source_by_name = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={
                "id": "src-123",
                "source_name": "yt-youtube-watch",
                "type": "youtube",
                "status": "active",
            }
        )
        svc.update_source = AsyncMock(
            return_value={
                "id": "src-123",
                "source_name": "yt-fin-aprendizaje",
                "author": "Javier Maza",
                "comment": "Entrevista",
            }
        )
        return SourceCreateAgent(source_service=svc)

    @pytest.mark.anyio
    async def test_url_creates_source_immediately(self) -> None:
        """Source is created in DB BEFORE /update is called."""
        agent = self._make_agent()
        reply = await agent.create_source_from_url("https://youtube.com/watch?v=abc", user_id=1)

        # Verify create_source_and_optionally_activate was called immediately
        agent._source_service.create_source_and_optionally_activate.assert_awaited_once_with(
            source_name="yt-youtube-watch",
            activate=True,
            url="https://youtube.com/watch?v=abc",
            type="youtube",
        )

        # Verify the reply confirms creation
        assert "✅ Source created" in reply
        assert "youtube" in reply

    @pytest.mark.anyio
    async def test_no_pending_context_after_url_creation(self) -> None:
        """After deterministic creation, no pending context is set."""
        agent = self._make_agent()
        await agent.create_source_from_url("https://youtube.com/watch?v=abc", user_id=1)

        ctx = agent.get_pending_context(1)
        assert ctx is None

    @pytest.mark.anyio
    async def test_enrich_via_update_flow(self) -> None:
        """After creation, /update starts enrichment, then LLM-driven apply updates the source."""
        agent = self._make_agent()
        await agent.create_source_from_url("https://youtube.com/watch?v=abc", user_id=1)

        # /update starts enrichment
        active_source = {
            "id": "src-123",
            "source_name": "yt-youtube-watch",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, active_source)

        # LLM-driven: capture then apply
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="Captured: Javier Maza, Entrevista",
            fields={"author": "Javier Maza", "comment": "Entrevista"},
            intention="capture",
        ))
        await agent.handle_response("author Javier Maza, comment Entrevista", user_id=1)

        # Not yet applied
        agent._source_service.update_source.assert_not_awaited()

        # Apply
        agent._call_llm = Mock(return_value=_make_llm_response(
            reply="Saved!",
            fields={"author": "Javier Maza", "comment": "Entrevista"},
            intention="apply",
        ))
        await agent.handle_response("yes", user_id=1)

        # Verify update_source was called
        agent._source_service.update_source.assert_awaited_once()

    @pytest.mark.anyio
    async def test_duplicate_url_no_creation(self) -> None:
        """Duplicate URL does NOT create a new source."""
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(
            return_value={"source_name": "existing-source", "id": "existing-id"}
        )
        svc.create_source_and_optionally_activate = AsyncMock()
        agent = SourceCreateAgent(source_service=svc)

        reply = await agent.create_source_from_url("https://youtube.com/watch?v=abc", user_id=1)

        assert "already exists" in reply
        # Verify create was NOT called
        svc.create_source_and_optionally_activate.assert_not_awaited()
        # Verify no pending context
        assert agent.get_pending_context(1) is None


# ── Routing fix ──────────────────────────────────────────────────────────────


class TestRoutingFix:
    """v2: MultiAgentService.handle() hydrates source_create_context."""

    @pytest.mark.anyio
    async def test_hydrated_context_routes_to_source_create_node(self) -> None:
        """When pending context exists, supervisor routes to source_create_node."""
        # Build a SourceCreateAgent with pending context
        svc = AsyncMock()
        source_create_agent = SourceCreateAgent(source_service=svc)
        # Manually set pending context
        ctx = SourceCreateContext(
            source_type="youtube",
            url="https://youtube.com/watch?v=abc",
            source_id="src-123",
            step=SourceCreateStep.AWAITING_INPUT,
        )
        source_create_agent._pending[123] = ctx

        # Build minimal MultiAgentService
        chat_agent = Mock()
        chat_agent.get_response = AsyncMock(return_value="chat reply")
        reflection_service = Mock()
        reflection_service.get_pending_reflection = AsyncMock(return_value=None)
        reflection_service.reflection_repository = AsyncMock()
        chat_mode_service = Mock()
        chat_mode_service.get_mode = Mock(return_value="agent")
        sources_repo = Mock()
        sources_repo.get_active_source = AsyncMock(return_value=None)

        service = MultiAgentService(
            chat_agent=chat_agent,
            reflection_service=reflection_service,
            question_agent=Mock(),
            scorer_agent=Mock(),
            hint_agent=Mock(),
            chat_mode_service=chat_mode_service,
            sources_repository=sources_repo,
            note_selector_service=Mock(),
            memory_repository=Mock(),
            agent_model=Mock(),
            source_create_agent=source_create_agent,
        )

        result = await service.handle("yes keep the name", telegram_user_id=123)

        # Should route to source_create_node, NOT chat_node
        assert result.outcome == "source_create_reply"
        # chat_agent should NOT have been called
        chat_agent.get_response.assert_not_awaited()

    @pytest.mark.anyio
    async def test_no_context_routes_to_chat_node(self) -> None:
        """When no pending context, supervisor routes to chat_node."""
        source_create_agent = SourceCreateAgent(source_service=AsyncMock())
        # No pending context for user 123

        chat_agent = Mock()
        chat_agent.get_response = AsyncMock(return_value="chat reply")
        reflection_service = Mock()
        reflection_service.get_pending_reflection = AsyncMock(return_value=None)
        reflection_service.reflection_repository = AsyncMock()
        chat_mode_service = Mock()
        chat_mode_service.get_mode = Mock(return_value="agent")
        sources_repo = Mock()
        sources_repo.get_active_source = AsyncMock(return_value=None)

        service = MultiAgentService(
            chat_agent=chat_agent,
            reflection_service=reflection_service,
            question_agent=Mock(),
            scorer_agent=Mock(),
            hint_agent=Mock(),
            chat_mode_service=chat_mode_service,
            sources_repository=sources_repo,
            note_selector_service=Mock(),
            memory_repository=Mock(),
            agent_model=Mock(),
            source_create_agent=source_create_agent,
        )

        result = await service.handle("hello", telegram_user_id=123)

        # Should route to chat_node
        assert result.outcome == "chat_reply"
        assert result.reply == "chat reply"


# ── Name suggestions are short slugs ─────────────────────────────────────────


class TestNameSuggestions:
    """Name suggestions must be short slugs, not full titles."""

    def test_youtube_suggestion_is_slug(self) -> None:
        name = _suggest_source_name("youtube", "https://youtube.com/watch?v=abc")
        assert name.startswith("yt-")
        parts = name.split("-")
        assert len(parts) == 3  # prefix + 2 words
        # No spaces, no uppercase
        assert " " not in name
        assert name == name.lower()

    def test_instagram_suggestion_is_slug(self) -> None:
        name = _suggest_source_name("instagram", "https://instagram.com/p/Cxyz123/")
        assert name.startswith("ig-")
        parts = name.split("-")
        assert len(parts) == 3

    def test_web_suggestion_with_path(self) -> None:
        name = _suggest_source_name("web", "https://medium.com/@user/scaling-apis-fastapi")
        assert name.startswith("wb-")
        parts = name.split("-")
        assert len(parts) == 3

    def test_suggestion_never_full_title(self) -> None:
        """Ensure suggestions are never full titles like 'El Futuro del Aprendizaje'."""
        name = _suggest_source_name("youtube", "https://youtube.com/watch?v=abc")
        # Must not contain spaces (it's a slug)
        assert " " not in name
        # Must be short (prefix + 2 words = 3 parts)
        assert len(name.split("-")) == 3


# ── System prompt ────────────────────────────────────────────────────────────


class TestSystemPrompt:
    """The detailed system prompt must contain examples and rules."""

    def test_prompt_contains_naming_examples(self) -> None:
        assert "yt-fin-aprendizaje" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "yt-youtube-video" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "wb-scaling-apis" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "bk-parasitic-minds" in SOURCE_CREATE_SYSTEM_PROMPT

    def test_prompt_contains_intention_based_instructions(self) -> None:
        assert "intention" in SOURCE_CREATE_SYSTEM_PROMPT.lower()
        assert "capture" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "apply" in SOURCE_CREATE_SYSTEM_PROMPT

    def test_prompt_contains_prefix_table(self) -> None:
        assert "yt-" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "ig-" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "lkn-" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "th-" in SOURCE_CREATE_SYSTEM_PROMPT

    def test_prompt_contains_negative_example(self) -> None:
        """Prompt must explicitly say full titles are WRONG."""
        assert "El Futuro del Aprendizaje" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "WRONG" in SOURCE_CREATE_SYSTEM_PROMPT

    def test_prompt_contains_json_output_format(self) -> None:
        """Prompt must document the JSON output format."""
        assert "intention" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "reply" in SOURCE_CREATE_SYSTEM_PROMPT
        assert "fields" in SOURCE_CREATE_SYSTEM_PROMPT


# ── JSON extraction ──────────────────────────────────────────────────────────


class TestJsonExtraction:
    def test_extract_from_code_block(self) -> None:
        text = """Here is the update:
```json
{
  "reply": "hello",
  "fields": {"source_name": "yt-fin-aprendizaje"},
  "intention": "capture"
}
```
"""
        result = _extract_json_block(text)
        assert result is not None
        assert result["intention"] == "capture"
        assert result["fields"]["source_name"] == "yt-fin-aprendizaje"

    def test_extract_from_bare_json(self) -> None:
        text = '{"reply": "hello", "fields": {}, "intention": "apply"}'
        result = _extract_json_block(text)
        assert result is not None
        assert result["intention"] == "apply"

    def test_no_json_returns_none(self) -> None:
        text = "Just a regular text response without JSON."
        result = _extract_json_block(text)
        assert result is None

    def test_json_without_intention_or_action_returns_none(self) -> None:
        text = '{"source_name": "yt-test"}'
        result = _extract_json_block(text)
        assert result is None


# ── Agent with LLM client ───────────────────────────────────────────────────


class TestAgentWithLLM:
    """Test the agent with a mocked OpenAI client."""

    def _make_agent_with_llm(
        self, llm_response: str = ""
    ) -> SourceCreateAgent:
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={
                "id": "src-123",
                "source_name": "yt-youtube-watch",
                "type": "youtube",
                "status": "active",
            }
        )
        svc.update_source = AsyncMock(
            return_value={
                "id": "src-123",
                "source_name": "yt-fin-aprendizaje",
                "author": "Javier Maza",
                "comment": "Test",
            }
        )

        mock_client = Mock()
        mock_response = Mock()
        mock_choice = Mock()
        mock_choice.message.content = llm_response
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = Mock(return_value=mock_response)

        return SourceCreateAgent(
            source_service=svc,
            openai_client=mock_client,
            model="gpt-5.6-luna",
            reasoning_effort="medium",
        )

    @pytest.mark.anyio
    async def test_llm_called_with_correct_model(self) -> None:
        """Agent uses gpt-5.6-luna with reasoning_effort=medium."""
        agent = self._make_agent_with_llm("Just a text response")
        await agent.create_source_from_url("https://youtube.com/watch?v=abc", user_id=1)
        active_source = {
            "id": "src-123",
            "source_name": "yt-youtube-watch",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, active_source)
        await agent.handle_response("some text", user_id=1)

        # Verify LLM was called with correct model
        agent._openai_client.chat.completions.create.assert_called_once()
        call_kwargs = agent._openai_client.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("model") == "gpt-5.6-luna" or call_kwargs[1].get("model") == "gpt-5.6-luna"
        assert call_kwargs.kwargs.get("reasoning_effort") == "medium" or call_kwargs[1].get("reasoning_effort") == "medium"

    @pytest.mark.anyio
    async def test_llm_json_capture_shows_summary(self) -> None:
        """When LLM returns JSON with intention=capture, summary is shown."""
        json_response = _make_llm_response(
            reply="Here is what I captured: yt-fin-aprendizaje by Javier Maza",
            fields={"source_name": "yt-fin-aprendizaje", "author": "Javier Maza", "comment": "Entrevista"},
            intention="capture",
        )
        agent = self._make_agent_with_llm(json_response)
        await agent.create_source_from_url("https://youtube.com/watch?v=abc", user_id=1)
        active_source = {
            "id": "src-123",
            "source_name": "yt-youtube-watch",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, active_source)

        reply = await agent.handle_response("el video trata sobre el fin del aprendizaje", user_id=1)

        # LLM JSON with intention=capture shows summary (not immediate apply)
        assert "yt-fin-aprendizaje" in reply
        assert "Javier Maza" in reply
        agent._source_service.update_source.assert_not_awaited()

    @pytest.mark.anyio
    async def test_llm_json_apply_triggers_update(self) -> None:
        """When LLM returns JSON with intention=apply, update is triggered."""
        json_response = _make_llm_response(
            reply="Saved! We are now in note mode.",
            fields={"author": "Javier Maza"},
            intention="apply",
        )
        agent = self._make_agent_with_llm(json_response)
        active_source = {
            "id": "src-123",
            "source_name": "yt-youtube-watch",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=abc",
        }
        await agent.start_enrich_flow(1, active_source)

        reply = await agent.handle_response("yes", user_id=1)

        agent._source_service.update_source.assert_awaited_once()
        assert "We are now in note mode" in reply


# ── /create flows ────────────────────────────────────────────────────────────


class TestCreateFlows:
    @pytest.mark.anyio
    async def test_create_no_args_starts_open_ended(self) -> None:
        svc = AsyncMock()
        agent = SourceCreateAgent(source_service=svc)
        reply = await agent.start_create_flow(user_id=1)
        assert "create" in reply.lower()
        ctx = agent.get_pending_context(1)
        assert ctx is not None
        assert ctx.step == SourceCreateStep.AWAITING_INPUT

    @pytest.mark.anyio
    async def test_create_with_url_delegates_to_deterministic_creation(self) -> None:
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={"id": "src-1", "source_name": "yt-test", "type": "youtube"}
        )
        agent = SourceCreateAgent(source_service=svc)
        reply = await agent.start_create_flow(
            user_id=1, name_or_url="https://youtube.com/watch?v=abc"
        )
        assert "✅ Source created" in reply
        # Should have created immediately
        svc.create_source_and_optionally_activate.assert_awaited_once()
        # No pending context after deterministic creation
        assert agent.get_pending_context(1) is None

    @pytest.mark.anyio
    async def test_create_with_prefixed_name(self) -> None:
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_url = AsyncMock(return_value=None)
        svc._repository.get_source_by_name = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={
                "id": "src-123",
                "source_name": "yt-my-video",
                "type": None,
                "status": "active",
            }
        )
        agent = SourceCreateAgent(source_service=svc)
        reply = await agent.start_create_flow(user_id=1, name_or_url="yt-my-video")
        assert "yt-my-video" in reply
        assert "Source created" in reply
        ctx = agent.get_pending_context(1)
        assert ctx is None

    @pytest.mark.anyio
    async def test_create_with_invalid_name(self) -> None:
        """No prefix validation — any non-empty name creates immediately."""
        svc = AsyncMock()
        svc._repository = AsyncMock()
        svc._repository.get_source_by_name = AsyncMock(return_value=None)
        svc.create_source_and_optionally_activate = AsyncMock(
            return_value={
                "id": "src-123",
                "source_name": "no-prefix",
                "type": None,
                "status": "active",
            }
        )
        agent = SourceCreateAgent(source_service=svc)
        reply = await agent.start_create_flow(user_id=1, name_or_url="no-prefix")
        assert "Source created" in reply
        assert "no-prefix" in reply


# ── SourcesRepository.update_source ─────────────────────────────────────────


class TestSourcesRepositoryUpdateSource:
    @pytest.mark.anyio
    async def test_update_source_name(self) -> None:
        from backend.repositories.sources_repository import SourcesRepository

        mock_client = Mock()
        mock_response = Mock()
        mock_response.data = {"id": "src-1", "source_name": "yt-new-name"}
        mock_response.error = None

        update_chain = AsyncMock()
        update_chain.update = Mock(return_value=update_chain)
        update_chain.eq = Mock(return_value=update_chain)
        update_chain.execute = AsyncMock(return_value=mock_response)

        mock_client.table = Mock(return_value=update_chain)

        repo = SourcesRepository(client=mock_client)
        result = await repo.update_source("src-1", source_name="yt-new-name")

        assert result is not None
        assert result["source_name"] == "yt-new-name"
        update_chain.update.assert_called_once_with({"source_name": "yt-new-name"})

    @pytest.mark.anyio
    async def test_update_source_multiple_fields(self) -> None:
        from backend.repositories.sources_repository import SourcesRepository

        mock_client = Mock()
        mock_response = Mock()
        mock_response.data = {
            "id": "src-1",
            "source_name": "yt-new-name",
            "author": "John",
            "comment": "Test",
        }
        mock_response.error = None

        update_chain = AsyncMock()
        update_chain.update = Mock(return_value=update_chain)
        update_chain.eq = Mock(return_value=update_chain)
        update_chain.execute = AsyncMock(return_value=mock_response)

        mock_client.table = Mock(return_value=update_chain)

        repo = SourcesRepository(client=mock_client)
        result = await repo.update_source(
            "src-1",
            source_name="yt-new-name",
            author="John",
            comment="Test",
        )

        assert result is not None
        update_chain.update.assert_called_once_with(
            {"source_name": "yt-new-name", "author": "John", "comment": "Test"}
        )

    @pytest.mark.anyio
    async def test_update_source_no_fields_returns_current(self) -> None:
        from backend.repositories.sources_repository import SourcesRepository

        mock_client = Mock()
        mock_response = Mock()
        mock_response.data = {"id": "src-1", "source_name": "yt-existing"}
        mock_response.error = None

        select_chain = AsyncMock()
        select_chain.select = Mock(return_value=select_chain)
        select_chain.eq = Mock(return_value=select_chain)
        select_chain.maybe_single = Mock(return_value=select_chain)
        select_chain.execute = AsyncMock(return_value=mock_response)

        mock_client.table = Mock(return_value=select_chain)

        repo = SourcesRepository(client=mock_client)
        result = await repo.update_source("src-1")

        # Should fetch and return current record without updating
        assert result is not None
        assert result["source_name"] == "yt-existing"


# ── SourceService.update_source ──────────────────────────────────────────────


class TestSourceServiceUpdateSource:
    @pytest.mark.anyio
    async def test_delegates_to_repository(self) -> None:
        from backend.services.source_service import SourceService

        repo = AsyncMock()
        repo.update_source = AsyncMock(
            return_value={"id": "src-1", "source_name": "yt-new"}
        )
        svc = SourceService(repository=repo)

        result = await svc.update_source("src-1", source_name="yt-new")

        repo.update_source.assert_awaited_once_with(
            source_id="src-1",
            source_name="yt-new",
            author=None,
            comment=None,
            type=None,
        )
        assert result is not None
