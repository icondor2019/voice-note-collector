from __future__ import annotations

from loguru import logger

from backend.services.source_service import SourceService
from backend.services.telegram_bot_client import TelegramBotClient
from backend.utils.slug import slugify, validate_slug_input

CREATE_SUCCESS = '✅ Source "{slug}" created and activated.'
CREATE_DUPLICATE = '❌ Source "{slug}" already exists. Use /switch to activate it.'
SWITCH_SUCCESS = '✅ Active source is now "{slug}".'
SWITCH_NOT_FOUND = '❌ Source "{slug}" not found. Use /sources to see available sources.'
DEFAULT_SUCCESS = '✅ Active source is now "default".'
CURRENT_ACTIVE = '📍 Active source: "{name}"'
CURRENT_NONE = '⚠️ No active source. Use /default to reset.'
SOURCES_HEADER = "📂 Your sources:\n"
SOURCES_EMPTY = "📂 No sources found. Use /create <name> to get started."
INVALID_NAME = "❌ Source name must be 2–4 words, no special characters."
UNKNOWN_TEXT = "🤖 Send voice notes to capture ideas. Use /sources to manage sources."


class TelegramCommandHandler:
    def __init__(self, source_service: SourceService, bot_client: TelegramBotClient) -> None:
        self._source_service = source_service
        self._bot_client = bot_client

    def _parse_command(self, text: str) -> tuple[str, str]:
        normalized = text.strip()
        if not normalized.startswith("/"):
            return "text", text

        parts = normalized.split(maxsplit=1)
        command = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""
        return command, argument

    async def handle_text(self, text: str, chat_id: int | str) -> str:
        command, argument = self._parse_command(text)
        if command == "/create":
            reply = await self._handle_create(argument)
        elif command == "/switch":
            reply = await self._handle_switch(argument)
        elif command == "/default":
            reply = await self._handle_default()
        elif command == "/current":
            reply = await self._handle_current()
        elif command == "/sources":
            reply = await self._handle_sources()
        else:
            reply = self._handle_unknown_text()

        await self._bot_client.send_message(chat_id, reply)
        return reply

    async def _handle_create(self, argument: str) -> str:
        if not argument or not validate_slug_input(argument):
            return INVALID_NAME

        slug = slugify(argument)
        existing = await self._source_service._repository.get_source_by_name(slug)
        if existing:
            return CREATE_DUPLICATE.format(slug=slug)

        await self._source_service.create_source_and_optionally_activate(
            slug, author=None, comment=None, activate=True
        )
        logger.info("telegram.command.create", extra={"slug": slug})
        return CREATE_SUCCESS.format(slug=slug)

    async def _handle_switch(self, argument: str) -> str:
        if not argument or not validate_slug_input(argument):
            return INVALID_NAME

        slug = slugify(argument)
        existing = await self._source_service._repository.get_source_by_name(slug)
        if not existing:
            return SWITCH_NOT_FOUND.format(slug=slug)

        await self._source_service.activate_source_by_id(existing["id"])
        logger.info("telegram.command.switch", extra={"slug": slug})
        return SWITCH_SUCCESS.format(slug=slug)

    async def _handle_default(self) -> str:
        default_source = await self._source_service._repository.get_source_by_name("default")
        if not default_source:
            default_source = await self._source_service.ensure_default_source()
        else:
            await self._source_service.activate_source_by_id(default_source["id"])

        logger.info("telegram.command.default")
        return DEFAULT_SUCCESS

    async def _handle_current(self) -> str:
        active = await self._source_service.get_active_source()
        if not active:
            return CURRENT_NONE

        return CURRENT_ACTIVE.format(name=active["source_name"])

    async def _handle_sources(self) -> str:
        sources = await self._source_service.list_sources()
        if not sources:
            return SOURCES_EMPTY

        lines: list[str] = []
        for source in sources:
            marker = "●" if source.get("status") == "active" else "○"
            lines.append(f"{marker} {source.get('source_name')}")
        return SOURCES_HEADER + "\n".join(lines)

    def _handle_unknown_text(self) -> str:
        return UNKNOWN_TEXT
