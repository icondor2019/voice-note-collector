from unittest.mock import AsyncMock

import pytest

from backend.repositories.repository_errors import RepositoryError
from backend.services.chat_mode_service import ChatModeService
from backend.services.telegram_command_handler import (
    LABEL_DUPLICATE,
    LABEL_INVALID,
    LABEL_SUCCESS,
    TelegramCommandHandler,
)


@pytest.fixture
def handler_mocks() -> tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]:
    source_service = AsyncMock()
    bot_client = AsyncMock()
    labels_repository = AsyncMock()
    handler = TelegramCommandHandler(
        source_service=source_service,
        bot_client=bot_client,
        labels_repository=labels_repository,
        chat_mode_service=ChatModeService(),
    )
    return handler, source_service, bot_client, labels_repository


@pytest.mark.anyio
async def test_label_success(handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]) -> None:
    handler, _, bot_client, labels_repository = handler_mocks
    labels_repository.get_label_by_name = AsyncMock(return_value=None)
    labels_repository.create_label = AsyncMock(return_value={"id": 1})

    reply = await handler.handle_text("/label ideas", chat_id=123)

    assert reply == LABEL_SUCCESS.format(name="ideas")
    labels_repository.get_label_by_name.assert_awaited_once_with("ideas")
    labels_repository.create_label.assert_awaited_once_with("ideas")
    bot_client.send_message.assert_awaited_once_with(123, reply)


@pytest.mark.anyio
async def test_label_success_normalizes_case(
    handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]
) -> None:
    handler, _, _, labels_repository = handler_mocks
    labels_repository.get_label_by_name = AsyncMock(return_value=None)
    labels_repository.create_label = AsyncMock(return_value={"id": 1})

    reply = await handler.handle_text("/label Ideas", chat_id=123)

    assert reply == LABEL_SUCCESS.format(name="ideas")
    labels_repository.get_label_by_name.assert_awaited_once_with("ideas")


@pytest.mark.anyio
async def test_label_success_strips_whitespace(
    handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]
) -> None:
    handler, _, _, labels_repository = handler_mocks
    labels_repository.get_label_by_name = AsyncMock(return_value=None)
    labels_repository.create_label = AsyncMock(return_value={"id": 1})

    reply = await handler.handle_text("/label   ideas  ", chat_id=123)

    assert reply == LABEL_SUCCESS.format(name="ideas")
    labels_repository.get_label_by_name.assert_awaited_once_with("ideas")


@pytest.mark.anyio
async def test_label_duplicate_via_get(
    handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]
) -> None:
    handler, _, _, labels_repository = handler_mocks
    labels_repository.get_label_by_name = AsyncMock(return_value={"id": 1})

    reply = await handler.handle_text("/label ideas", chat_id=123)

    assert reply == LABEL_DUPLICATE.format(name="ideas")
    labels_repository.create_label.assert_not_awaited()


@pytest.mark.anyio
async def test_label_duplicate_via_repository_error(
    handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]
) -> None:
    handler, _, _, labels_repository = handler_mocks
    labels_repository.get_label_by_name = AsyncMock(return_value=None)
    labels_repository.create_label = AsyncMock(
        side_effect=RepositoryError("unique constraint")
    )

    reply = await handler.handle_text("/label ideas", chat_id=123)

    assert reply == LABEL_DUPLICATE.format(name="ideas")


@pytest.mark.anyio
async def test_label_non_unique_repository_error_reraises(
    handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]
) -> None:
    handler, _, _, labels_repository = handler_mocks
    labels_repository.get_label_by_name = AsyncMock(return_value=None)
    labels_repository.create_label = AsyncMock(
        side_effect=RepositoryError("connection failed")
    )

    with pytest.raises(RepositoryError):
        await handler.handle_text("/label ideas", chat_id=123)


@pytest.mark.anyio
async def test_label_empty_argument(
    handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]
) -> None:
    handler, _, _, labels_repository = handler_mocks

    reply = await handler.handle_text("/label", chat_id=123)

    assert reply == LABEL_INVALID
    labels_repository.get_label_by_name.assert_not_awaited()


@pytest.mark.anyio
async def test_label_whitespace_only_argument(
    handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]
) -> None:
    handler, _, _, labels_repository = handler_mocks

    reply = await handler.handle_text("/label    ", chat_id=123)

    assert reply == LABEL_INVALID
    labels_repository.get_label_by_name.assert_not_awaited()


@pytest.mark.anyio
async def test_label_too_long(
    handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]
) -> None:
    handler, _, _, labels_repository = handler_mocks
    long_name = "a" * 65

    reply = await handler.handle_text(f"/label {long_name}", chat_id=123)

    assert reply == LABEL_INVALID
    labels_repository.get_label_by_name.assert_not_awaited()


@pytest.mark.anyio
async def test_label_invalid_chars(
    handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]
) -> None:
    handler, _, _, labels_repository = handler_mocks

    reply = await handler.handle_text("/label hello world!", chat_id=123)

    assert reply == LABEL_INVALID
    labels_repository.get_label_by_name.assert_not_awaited()


@pytest.mark.anyio
async def test_label_valid_with_spaces(
    handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]
) -> None:
    handler, _, _, labels_repository = handler_mocks
    labels_repository.get_label_by_name = AsyncMock(return_value=None)
    labels_repository.create_label = AsyncMock(return_value={"id": 1})

    reply = await handler.handle_text("/label my ideas", chat_id=123)

    assert reply == LABEL_SUCCESS.format(name="my ideas")
    labels_repository.get_label_by_name.assert_awaited_once_with("my ideas")


@pytest.mark.anyio
async def test_label_valid_with_hyphens(
    handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]
) -> None:
    handler, _, _, labels_repository = handler_mocks
    labels_repository.get_label_by_name = AsyncMock(return_value=None)
    labels_repository.create_label = AsyncMock(return_value={"id": 1})

    reply = await handler.handle_text("/label my-ideas", chat_id=123)

    assert reply == LABEL_SUCCESS.format(name="my-ideas")
    labels_repository.get_label_by_name.assert_awaited_once_with("my-ideas")


@pytest.mark.anyio
async def test_existing_source_command_unaffected(
    handler_mocks: tuple[TelegramCommandHandler, AsyncMock, AsyncMock, AsyncMock]
) -> None:
    handler, source_service, _, labels_repository = handler_mocks
    source_service.list_sources = AsyncMock(return_value=[])

    reply = await handler.handle_text("/sources", chat_id=123)

    assert "📂" in reply
    labels_repository.get_label_by_name.assert_not_awaited()
