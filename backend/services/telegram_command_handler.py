from __future__ import annotations

import math
import re

from loguru import logger

from backend.repositories.labels_repository import LabelsRepository
from backend.repositories.repository_errors import RepositoryError
from backend.services.chat_mode_service import (
    AGENT_MODE_ACTIVATED,
    NOTE_MODE_ACTIVATED,
    ChatModeService,
)

REFLECT_MODE_ACTIVATED = "🧠 Reflect mode activated"
from backend.services.reflection_service import (
    AllNotesInternalizedError,
    NoActiveSourceError,
    NoNotesError,
    ReflectionService,
)
from backend.services.source_service import SourceService
from backend.services.telegram_bot_client import TelegramBotClient
from backend.utils.slug import slugify, validate_slug_input

CREATE_SUCCESS = '✅ Source "{slug}" created and activated.'
CREATE_DUPLICATE = '❌ Source "{slug}" already exists. Use /switch to activate it.'
SWITCH_SUCCESS = '✅ Active source is now "{slug}".'
SWITCH_NOT_FOUND = '❌ Source "{slug}" not found. Use /sources to see available sources.'
DEFAULT_SUCCESS = '✅ Active source is now "default".'
CURRENT_ACTIVE = '📍 Active source: "{name}"\n🤖 Mode: {mode}'
CURRENT_NONE = '⚠️ No active source. Use /default to reset.\n🤖 Mode: {mode}'
SOURCES_HEADER = "📂 Your sources:\n"
SOURCES_EMPTY = "📂 No sources found. Use /create <name> to get started."
SOURCES_PAGE_SIZE = 6
INVALID_NAME = "❌ Source name must be 2–4 words, no special characters."
UNKNOWN_TEXT = "🤖 Send voice notes to capture ideas. Use /sources to manage sources."
LABEL_SUCCESS = '✅ Label "{name}" created.'
LABEL_DUPLICATE = '❌ Label "{name}" already exists.'
LABEL_INVALID = "❌ Label name is invalid."
REFLECTION_FEEDBACK_TEMPLATE = "🧠 Rating: {rating}/10\n\n{feedback}"
HELP_MESSAGE = (
    "📋 Available commands:\n\n"
    "🤖 /agent — activate agent mode\n"
    "📝 /note — activate note mode\n"
    "📂 /sources — list your sources\n"
    "✅ /current — show active source and mode\n"
    "⚙️ /default — set default source\n"
    "🧠 /reflect — start a reflection question\n"
    "🔢 /reflect stats — show internalization progress\n"
    "❓ /help — show this message\n\n"
    "⚙️ Commands that require arguments:\n\n"
    "➕ /create <name> — create a new source\n"
    "🔀 /switch <name> — switch to a source by name\n"
    "🏷️ /label <name> — add a label"
)

MODE_DISPLAY_NAMES = {
    "agent": "agent",
    "note": "note",
    "reflect": "reflect",
}


class TelegramCommandHandler:
    def __init__(
        self,
        source_service: SourceService,
        bot_client: TelegramBotClient,
        labels_repository: LabelsRepository,
        chat_mode_service: ChatModeService,
        reflection_service: ReflectionService,
    ) -> None:
        self._source_service = source_service
        self._bot_client = bot_client
        self._labels_repository = labels_repository
        self._chat_mode_service = chat_mode_service
        self._reflection_service = reflection_service

    def _parse_command(self, text: str) -> tuple[str, str]:
        normalized = text.strip()
        if not normalized.startswith("/"):
            return "text", text

        parts = normalized.split(maxsplit=1)
        command = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""
        return command, argument

    async def handle_text(self, text: str, chat_id: int | str, from_user_id: int | None = None) -> str:
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
            return await self._handle_sources(chat_id)
        elif command == "/label":
            reply = await self._handle_label(argument)
        elif command == "/reflect":
            reply = await self._handle_reflect(from_user_id, argument)
        elif command == "/agent":
            reply = self._handle_agent_mode()
        elif command == "/note":
            reply = self._handle_note_mode()
        elif command == "/help":
            reply = self._handle_help()
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

    def _get_mode_display(self) -> str:
        return MODE_DISPLAY_NAMES.get(self._chat_mode_service.get_mode(), "note")

    async def _handle_current(self) -> str:
        active = await self._source_service.get_active_source()
        mode = self._get_mode_display()
        if not active:
            return CURRENT_NONE.format(mode=mode)

        return CURRENT_ACTIVE.format(name=active["source_name"], mode=mode)

    async def _handle_sources(self, chat_id: int | str) -> str:
        sources = await self._source_service.list_sources()
        if not sources:
            await self._bot_client.send_message(chat_id, SOURCES_EMPTY)
            return SOURCES_EMPTY

        keyboard = self.build_sources_keyboard(sources, page=0)
        await self._bot_client.send_message_with_inline_keyboard(
            chat_id, SOURCES_HEADER, keyboard
        )
        return SOURCES_HEADER

    def build_sources_keyboard(self, sources: list[dict], page: int = 0) -> dict:
        total_pages = max(1, math.ceil(len(sources) / SOURCES_PAGE_SIZE))
        page = max(0, min(page, total_pages - 1))
        page_sources = sources[
            page * SOURCES_PAGE_SIZE : (page + 1) * SOURCES_PAGE_SIZE
        ]

        buttons: list[list[dict]] = []
        for source in page_sources:
            source_name = source.get("source_name", "")
            source_id = source.get("id", "")
            is_active = source.get("status") == "active"
            button_text = f"✅ {source_name}" if is_active else source_name
            buttons.append(
                [{"text": button_text, "callback_data": f"src:{source_id}"}]
            )

        if total_pages > 1:
            nav_row: list[dict] = []
            if page > 0:
                nav_row.append({"text": "◀️", "callback_data": f"src_page:{page - 1}"})
            if page < total_pages - 1:
                nav_row.append({"text": "▶️", "callback_data": f"src_page:{page + 1}"})
            if nav_row:
                buttons.append(nav_row)

        return {"inline_keyboard": buttons}

    async def _handle_label(self, argument: str) -> str:
        name = argument.strip().lower()
        if not name:
            return LABEL_INVALID
        if len(name) > 64:
            return LABEL_INVALID
        if not re.match(r"^[a-z0-9 _-]+$", name):
            return LABEL_INVALID

        existing = await self._labels_repository.get_label_by_name(name)
        if existing:
            return LABEL_DUPLICATE.format(name=name)

        try:
            await self._labels_repository.create_label(name)
        except RepositoryError as exc:
            if "unique" in str(exc).lower():
                return LABEL_DUPLICATE.format(name=name)
            raise

        logger.info("telegram.command.label", extra={"name": name})
        return LABEL_SUCCESS.format(name=name)

    async def _handle_reflect(self, telegram_user_id: int, argument: str = "") -> str:
        if argument == "stats":
            return await self._handle_reflect_stats()

        try:
            result = await self._reflection_service.start_reflection(telegram_user_id)
            self._chat_mode_service.set_mode("reflect")
            return f"{result.question_text}"
        except NoActiveSourceError:
            return "⚠️ No active source. Use /switch or /default to set one."
        except NoNotesError:
            return "⚠️ No notes found in your active source. Send some voice notes first!"
        except AllNotesInternalizedError as exc:
            source_name = "your source"
            try:
                active = await self._source_service.get_active_source()
                if active:
                    source_name = active["source_name"]
            except Exception:
                pass
            return f"You've reviewed all notes from {source_name}! 🎉"

    async def _handle_reflect_stats(self) -> str:
        """Handle /reflect stats command - return reflection summary for active source."""
        try:
            summary = await self._reflection_service.get_reflection_summary(None)
            if summary.total_notes == 0:
                return "📊 No notes yet in your active source."

            total = summary.total_notes
            internalized_pct = round(summary.internalized / total * 100) if total > 0 else 0
            in_progress_pct = round(summary.in_progress / total * 100) if total > 0 else 0
            pending_pct = round(summary.pending / total * 100) if total > 0 else 0

            return (
                f"📊 {summary.source_name} · Reflection Stats\n\n"
                f"📝 Total notes: {total}\n"
                f"✅ Internalized: {summary.internalized} ({internalized_pct}%)\n"
                f"🔄 In progress: {summary.in_progress} ({in_progress_pct}%)\n"
                f"⏳ Pending: {summary.pending} ({pending_pct}%)"
            )
        except NoActiveSourceError:
            return "⚠️ No active source. Use /switch or /default to set one."

    def _handle_unknown_text(self) -> str:
        return UNKNOWN_TEXT

    def _handle_agent_mode(self) -> str:
        self._chat_mode_service.set_mode("agent")
        return AGENT_MODE_ACTIVATED

    def _handle_note_mode(self) -> str:
        self._chat_mode_service.set_mode("note")
        return NOTE_MODE_ACTIVATED

    def _handle_help(self) -> str:
        return HELP_MESSAGE
