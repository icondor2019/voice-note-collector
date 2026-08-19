"""Tests for SourceCreateAgent singleton dependency injection.

Verifies the fix for the critical DI scoping bug:
- SourceCreateAgent must be a module-level singleton (like ChatModeService)
- The same instance must be returned across multiple HTTP requests
- Pending context set in request 1 must be retrievable in request 2
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import backend.controllers.telegram_controller as controller_module
from backend.controllers.telegram_controller import (
    _source_create_agent,
    get_source_create_agent,
)
from backend.services.source_create_agent import SourceCreateAgent


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the module-level singleton before and after each test."""
    controller_module._source_create_agent = None
    yield
    controller_module._source_create_agent = None


class TestSourceCreateAgentSingleton:
    """Verify get_source_create_agent() returns the same instance."""

    def test_returns_same_instance_on_multiple_calls(self) -> None:
        """The singleton pattern: same instance across calls."""
        mock_source_service = AsyncMock()

        agent1 = get_source_create_agent(source_service=mock_source_service)
        agent2 = get_source_create_agent(source_service=mock_source_service)

        assert agent1 is agent2

    def test_returns_source_create_agent_instance(self) -> None:
        """The returned object is a SourceCreateAgent."""
        mock_source_service = AsyncMock()
        agent = get_source_create_agent(source_service=mock_source_service)
        assert isinstance(agent, SourceCreateAgent)

    def test_first_call_creates_instance(self) -> None:
        """First call creates the singleton and caches it."""
        mock_source_service = AsyncMock()
        assert controller_module._source_create_agent is None

        agent = get_source_create_agent(source_service=mock_source_service)

        assert controller_module._source_create_agent is agent
        assert agent is not None

    def test_second_call_does_not_create_new_instance(self) -> None:
        """Second call returns the cached instance, ignoring new source_service."""
        mock_source_service_1 = AsyncMock()
        mock_source_service_2 = AsyncMock()

        agent1 = get_source_create_agent(source_service=mock_source_service_1)
        agent2 = get_source_create_agent(source_service=mock_source_service_2)

        assert agent1 is agent2
        # The source_service from the first call is the one used
        assert agent1._source_service is mock_source_service_1

    def test_different_source_service_ignored_after_first_call(self) -> None:
        """After first call, different source_service args don't create a new agent."""
        svc_a = AsyncMock()
        svc_b = AsyncMock()

        agent_a = get_source_create_agent(source_service=svc_a)
        agent_b = get_source_create_agent(source_service=svc_b)

        assert agent_a is agent_b
        assert agent_a._source_service is svc_a


class TestSingletonPreservesPendingContext:
    """Simulate the multi-request flow that was broken before the fix."""

    def test_pending_context_survives_across_dependency_calls(self) -> None:
        """Request 1 sets pending context; request 2 retrieves it (same instance)."""
        mock_source_service = AsyncMock()

        # Simulate request 1: get the agent and set pending context
        agent_request_1 = get_source_create_agent(source_service=mock_source_service)
        user_id = 12345
        agent_request_1._pending[user_id] = {
            "source_id": "src-abc",
            "step": "AWAITING_NAME_CONFIRM",
            "source_name": "yt-test-video",
            "type": "youtube",
            "url": "https://youtube.com/watch?v=test",
        }

        # Simulate request 2: get the agent again (should be same instance)
        agent_request_2 = get_source_create_agent(source_service=mock_source_service)

        # The pending context from request 1 is available in request 2
        ctx = agent_request_2.get_pending_context(user_id)
        assert ctx is not None
        assert ctx["source_id"] == "src-abc"
        assert ctx["step"] == "AWAITING_NAME_CONFIRM"

    def test_clear_pending_works_on_singleton(self) -> None:
        """clear_pending on one reference affects the singleton."""
        mock_source_service = AsyncMock()

        agent1 = get_source_create_agent(source_service=mock_source_service)
        user_id = 99
        agent1._pending[user_id] = {"source_id": "src-x", "step": "DONE"}

        agent2 = get_source_create_agent(source_service=mock_source_service)
        agent2.clear_pending(user_id)

        # Both references see the cleared state
        assert agent1.get_pending_context(user_id) is None
        assert agent2.get_pending_context(user_id) is None

    def test_multiple_users_pending_context(self) -> None:
        """Singleton correctly tracks pending context for multiple users."""
        mock_source_service = AsyncMock()

        agent = get_source_create_agent(source_service=mock_source_service)
        agent._pending[1] = {"source_id": "src-1", "step": "AWAITING_NAME_CONFIRM"}
        agent._pending[2] = {"source_id": "src-2", "step": "AWAITING_AUTHOR"}

        # Get a fresh reference (same instance)
        agent2 = get_source_create_agent(source_service=mock_source_service)
        assert agent2.get_pending_context(1) is not None
        assert agent2.get_pending_context(2) is not None
        assert agent2.get_pending_context(1)["source_id"] == "src-1"
        assert agent2.get_pending_context(2)["source_id"] == "src-2"

        # Clear one, other remains
        agent2.clear_pending(1)
        assert agent2.get_pending_context(1) is None
        assert agent2.get_pending_context(2) is not None
