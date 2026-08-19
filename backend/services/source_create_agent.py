"""Source creation agent — multi-turn conversation for creating sources."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional
from urllib.parse import urlparse

from loguru import logger

from backend.models.source import VALID_PREFIXES, VALID_SOURCE_TYPES, SourceCreateByAgentRequest
from backend.services.source_service import SourceService
from backend.services.source_type_resolver import SourceTypeResolver
from backend.services.url_detector_service import UrlDetectorService
from backend.utils.slug import slugify

# Type → prefix mapping
_TYPE_PREFIX_MAP: dict[str, str] = {
    "youtube": "yt",
    "instagram": "ig",
    "facebook": "fb",
    "linkedin": "lkn",
    "web": "wb",
    "book": "bk",
    "course": "cr",
    "thought": "th",
}

SOURCE_CREATE_SYSTEM_PROMPT = """You are a source creation assistant. Your job is to collect information \
to create a new source in the user's knowledge base.

## Source Naming Convention
Every source name MUST follow this format: prefix-word1-word2 (exactly 3 words, slugified).
Valid prefixes:
- yt- (youtube)
- ig- (instagram)
- fb- (facebook)
- lkn- (linkedin)
- wb- (web)
- bk- (book)
- cr- (course)
- th- (thought)

## Source Types
Valid types: youtube, instagram, facebook, linkedin, web, book, course, thought

## ALWAYS-ASK RULE (CRITICAL)
You MUST always ask the user for ALL of these fields, even though they are optional:
1. source_name — suggest one based on the URL or context, but let the user override
2. type — auto-detect from URL domain, but let the user override
3. author — you MUST ask, even though the user can decline
4. comment — you MUST ask, even though the user can decline
5. url — if not already provided

"Optional" means the user can leave it empty — it does NOT mean you can skip asking.

## Conversation Flow
1. Present the detected source info (type, URL, suggested name)
2. Ask if the user wants to use the suggested name or provide a different one
3. Ask for the author (user can say "skip" or "none")
4. Ask for a comment (user can say "skip" or "none")
5. Confirm all details and create the source

## Output Format
When you have all the information, respond with a JSON block:
```json
{
  "source_name": "yt-cool-video",
  "type": "youtube",
  "url": "https://youtube.com/watch?v=abc",
  "author": "John Doe",
  "comment": "Great tutorial"
}
```
"""


class SourceCreateStep(str, Enum):
    """Steps in the source creation conversation."""

    AWAITING_NAME = "awaiting_name"
    AWAITING_AUTHOR = "awaiting_author"
    AWAITING_COMMENT = "awaiting_comment"
    COMPLETE = "complete"


class SourceCreateContext:
    """Tracks the state of a multi-turn source creation conversation."""

    def __init__(
        self,
        source_type: str,
        url: Optional[str] = None,
        suggested_name: Optional[str] = None,
        source_name: Optional[str] = None,
        author: Optional[str] = None,
        comment: Optional[str] = None,
        step: SourceCreateStep = SourceCreateStep.AWAITING_NAME,
    ) -> None:
        self.source_type = source_type
        self.url = url
        self.suggested_name = suggested_name
        self.source_name = source_name
        self.author = author
        self.comment = comment
        self.step = step

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "url": self.url,
            "suggested_name": self.suggested_name,
            "source_name": self.source_name,
            "author": self.author,
            "comment": self.comment,
            "step": self.step.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceCreateContext":
        return cls(
            source_type=data["source_type"],
            url=data.get("url"),
            suggested_name=data.get("suggested_name"),
            source_name=data.get("source_name"),
            author=data.get("author"),
            comment=data.get("comment"),
            step=SourceCreateStep(data.get("step", "awaiting_name")),
        )


def _suggest_source_name(source_type: str, url: Optional[str] = None) -> str:
    """Generate a suggested source name from the type prefix and URL structure.

    Format: prefix-word1-word2 (3 words, slugified).
    No URL fetching — derives words from the URL's domain and path segments.
    """
    prefix = _TYPE_PREFIX_MAP.get(source_type, "wb")

    if not url:
        return f"{prefix}-new-source"

    try:
        # Handle bare domains
        parseable_url = url if "://" in url else f"https://{url}"
        parsed = urlparse(parseable_url)
        hostname = (parsed.hostname or "").lower()

        # Extract meaningful words from domain
        domain_parts = hostname.replace("www.", "").split(".")
        domain_word = domain_parts[0] if domain_parts else "source"

        # Extract words from path
        path_words: list[str] = []
        if parsed.path and parsed.path != "/":
            segments = [s for s in parsed.path.split("/") if s]
            for seg in segments[:3]:
                # Clean segment: remove query-like chars, take first meaningful part
                cleaned = re.sub(r"[^a-zA-Z0-9]", " ", seg).strip()
                words = cleaned.split()
                path_words.extend(words[:2])

        # Build name from domain + path words
        if path_words:
            word1 = slugify(domain_word) or "source"
            word2 = slugify(path_words[0]) or "item"
        else:
            # For URLs without meaningful paths, use domain + "source"
            word1 = slugify(domain_word) or "source"
            word2 = "source"

        # Ensure we have valid slug parts
        word1 = re.sub(r"[^a-z0-9]", "", word1.lower()) or "source"
        word2 = re.sub(r"[^a-z0-9]", "", word2.lower()) or "item"

        return f"{prefix}-{word1}-{word2}"
    except Exception:
        return f"{prefix}-new-source"


class SourceCreateAgent:
    """Handles multi-turn source creation conversation.

    This agent collects source information from the user across multiple
    messages, then creates the source when all required fields are gathered.
    """

    def __init__(self, source_service: SourceService) -> None:
        self._source_service = source_service
        self._pending: dict[int, SourceCreateContext] = {}

    def get_pending_context(self, user_id: int) -> Optional[SourceCreateContext]:
        return self._pending.get(user_id)

    def clear_pending(self, user_id: int) -> None:
        self._pending.pop(user_id, None)

    async def start_url_flow(
        self, url: str, user_id: int
    ) -> str:
        """Start the source creation flow triggered by a URL-only message."""
        source_type = SourceTypeResolver.resolve_type(url)
        suggested_name = _suggest_source_name(source_type, url)

        ctx = SourceCreateContext(
            source_type=source_type,
            url=url,
            suggested_name=suggested_name,
            step=SourceCreateStep.AWAITING_NAME,
        )
        self._pending[user_id] = ctx

        # Check for duplicate URL
        existing = await self._source_service._repository.get_source_by_url(url)
        if existing:
            self.clear_pending(user_id)
            return (
                f"⚠️ A source with this URL already exists:\n"
                f"📂 \"{existing.get('source_name', 'unknown')}\"\n\n"
                f"Use /switch {existing.get('source_name', '')} to activate it."
            )

        return (
            f"📎 Source detected: {source_type}\n"
            f"🔗 {url}\n"
            f"📝 Suggested name: {suggested_name}\n\n"
            f"Do you want to use this name, or provide a different one?"
        )

    async def start_create_flow(
        self, user_id: int, name_or_url: Optional[str] = None
    ) -> str:
        """Start the source creation flow triggered by /create command."""
        # If argument is a URL, treat as URL trigger
        if name_or_url and UrlDetectorService.is_url(name_or_url):
            url = UrlDetectorService.extract_url(name_or_url)
            return await self.start_url_flow(url, user_id)

        # If argument is a name, validate and pre-fill
        if name_or_url:
            slug = slugify(name_or_url)
            # Check if the name already has a valid prefix
            has_prefix = any(slug.startswith(p) for p in VALID_PREFIXES)
            if not has_prefix:
                return (
                    f"❌ Source name must start with a type prefix.\n\n"
                    f"Valid prefixes: {', '.join(VALID_PREFIXES)}\n"
                    f"Example: yt-my-video, bk-cookbook-recipes, th-daily-thoughts\n\n"
                    f"Use /create without arguments to start the guided flow."
                )

            ctx = SourceCreateContext(
                source_type="web",  # will be asked
                source_name=slug,
                step=SourceCreateStep.AWAITING_AUTHOR,
            )
            self._pending[user_id] = ctx
            return (
                f"📝 Source name: {slug}\n\n"
                f"What type of source is this?\n"
                f"({', '.join(sorted(VALID_SOURCE_TYPES))})"
            )

        # No argument — start guided flow
        ctx = SourceCreateContext(
            source_type="thought",
            step=SourceCreateStep.AWAITING_NAME,
        )
        self._pending[user_id] = ctx
        return (
            "Let's create a new source!\n\n"
            "What type of source is this?\n"
            f"({', '.join(sorted(VALID_SOURCE_TYPES))})\n\n"
            "Or paste a URL to create a source from it."
        )

    async def handle_response(
        self, user_message: str, user_id: int
    ) -> str:
        """Process the user's response in the source creation flow."""
        ctx = self._pending.get(user_id)
        if ctx is None:
            return "No pending source creation. Use /create to start."

        text = user_message.strip()

        # Handle skip/decline
        is_skip = text.lower() in ("skip", "none", "no", "n/a", "-")

        if ctx.step == SourceCreateStep.AWAITING_NAME:
            return await self._handle_name_step(text, is_skip, user_id, ctx)
        elif ctx.step == SourceCreateStep.AWAITING_AUTHOR:
            return await self._handle_author_step(text, is_skip, user_id, ctx)
        elif ctx.step == SourceCreateStep.AWAITING_COMMENT:
            return await self._handle_comment_step(text, is_skip, user_id, ctx)
        else:
            self.clear_pending(user_id)
            return "Source creation is complete. Use /create to start a new one."

    async def _handle_name_step(
        self, text: str, is_skip: bool, user_id: int, ctx: SourceCreateContext
    ) -> str:
        # First, check if user is providing the type (for /create no-args flow)
        if text.lower() in VALID_SOURCE_TYPES:
            ctx.source_type = text.lower()
            prefix = _TYPE_PREFIX_MAP.get(ctx.source_type, "wb")
            suggested = f"{prefix}-new-source"
            ctx.suggested_name = suggested
            return (
                f"📝 Great! Suggested name: {suggested}\n\n"
                f"Do you want to use this name, or provide a different one?"
            )

        # Check if user is accepting the suggested name
        if text.lower() in ("yes", "y", "ok", "sure", "accept"):
            if ctx.suggested_name:
                ctx.source_name = ctx.suggested_name
            else:
                return "Please provide a source name (format: prefix-word1-word2)."
        elif UrlDetectorService.is_url(text):
            # User pasted a URL as name
            url = UrlDetectorService.extract_url(text)
            ctx.url = url
            ctx.source_type = SourceTypeResolver.resolve_type(url)
            ctx.suggested_name = _suggest_source_name(ctx.source_type, url)
            ctx.source_name = ctx.suggested_name
        else:
            # User provided a custom name
            slug = slugify(text)
            has_prefix = any(slug.startswith(p) for p in VALID_PREFIXES)
            if not has_prefix:
                return (
                    f"❌ Source name must start with a type prefix.\n"
                    f"Valid prefixes: {', '.join(VALID_PREFIXES)}\n"
                    f"Try again or say 'skip' to use the suggested name."
                )
            ctx.source_name = slug

        ctx.step = SourceCreateStep.AWAITING_AUTHOR
        return "👤 Who is the author? (or say 'skip' to leave empty)"

    async def _handle_author_step(
        self, text: str, is_skip: bool, user_id: int, ctx: SourceCreateContext
    ) -> str:
        if not is_skip:
            ctx.author = text

        ctx.step = SourceCreateStep.AWAITING_COMMENT
        return "💬 Any comment about this source? (or say 'skip' to leave empty)"

    async def _handle_comment_step(
        self, text: str, is_skip: bool, user_id: int, ctx: SourceCreateContext
    ) -> str:
        if not is_skip:
            ctx.comment = text

        ctx.step = SourceCreateStep.COMPLETE

        # Validate and create
        try:
            request = SourceCreateByAgentRequest(
                source_name=ctx.source_name or ctx.suggested_name or "wb-new-source",
                type=ctx.source_type,
                url=ctx.url,
                author=ctx.author,
                comment=ctx.comment,
            )
        except ValueError as exc:
            return f"❌ Validation error: {exc}\nUse /create to start over."

        try:
            source = await self._source_service.create_source_and_optionally_activate(
                source_name=request.source_name,
                author=request.author,
                comment=request.comment,
                activate=True,
                url=request.url,
                type=request.type,
            )
            self.clear_pending(user_id)
            logger.info(
                "source_create_agent.created",
                extra={"source_name": request.source_name, "type": request.type},
            )
            return (
                f"✅ Source \"{request.source_name}\" created and activated!\n"
                f"📎 Type: {request.type}\n"
                f"🔗 URL: {request.url or 'N/A'}\n"
                f"👤 Author: {request.author or 'N/A'}\n"
                f"💬 Comment: {request.comment or 'N/A'}"
            )
        except ValueError as exc:
            self.clear_pending(user_id)
            return f"❌ {exc}"
        except Exception as exc:
            logger.error(
                "source_create_agent.create_failed",
                extra={"error": str(exc)},
            )
            return "❌ Failed to create source. Please try again with /create."
