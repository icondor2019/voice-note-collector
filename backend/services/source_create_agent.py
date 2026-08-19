"""Source creation agent — LLM-driven, create-immediately-then-enrich flow.

v2 rewrite: Uses gpt-5.6-luna with reasoning_effort=medium.
Source is created IMMEDIATELY on URL detection, then enriched via conversation.
"""

from __future__ import annotations

import json
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

# --------------------------------------------------------------------------- #
#  System prompt (detailed — with examples, from plan §3.3)
# --------------------------------------------------------------------------- #

SOURCE_CREATE_SYSTEM_PROMPT = """You are a source creation assistant for a voice-note knowledge base app.
Your job is to help the user create and enrich sources by collecting information
through conversation.

## CRITICAL: Source Creation Is Mandatory
When a URL is detected, the source is ALREADY CREATED in the database with an
auto-generated name and type. Your job is to ENRICH it: ask the user if they
want to change the name, and collect author and comment. You are NOT deciding
whether to create — it is already done. You are completing the information.

## Source Naming Convention (STRICT)
Every source name MUST follow this format:
  prefix-word1-word2

- Exactly 3 words separated by hyphens (slugified: lowercase, no spaces, no special chars).
- 4 words ONLY if the user explicitly insists.
- The prefix identifies the source type.

### Valid Prefixes and Types
| Prefix | Type      | Use for                          |
|--------|-----------|----------------------------------|
| yt-    | youtube   | YouTube videos                   |
| ig-    | instagram | Instagram posts                  |
| fb-    | facebook  | Facebook posts                   |
| lkn-   | linkedin  | LinkedIn posts                   |
| wb-    | web       | Any other web URL                |
| bk-    | book      | Books                            |
| cr-    | course    | Online courses                   |
| th-    | thought   | Personal thoughts and ideas      |

### Name Suggestion Examples

**From a URL (no metadata fetched — derive from URL structure):**
- URL: https://www.youtube.com/watch?v=abc123
  → Suggest: yt-youtube-video (fallback when path has no words)
  → Better: yt-regression-metrics (if URL path contains recognizable words)
- URL: https://youtube.com/watch?v=abc&topic=machine-learning
  → Suggest: yt-machine-learning
- URL: https://medium.com/@user/scaling-apis-with-fastapi-12345
  → Suggest: wb-scaling-apis
- URL: https://linkedin.com/pulse/machine-learning-trends-2024
  → Suggest: lkn-machine-trends
- URL: https://instagram.com/p/Cxyz123/
  → Suggest: ig-instagram-post (fallback — IG paths are opaque)

**From a user description (for non-URL sources like books, courses, thoughts):**
- User says: "It's a book about parasitic minds by Pablo Malo"
  → Suggest: bk-parasitic-minds
- User says: "A course about AWS for developers"
  → Suggest: cr-aws-developers
- User says: "I want to capture thoughts about moral philosophy"
  → Suggest: th-moral-philosophy
- User says: "El video trata sobre el fin del aprendizaje, entrevista de Javier Maza"
  → Suggest: yt-fin-aprendizaje
- User says: "It's about scaling APIs"
  → Suggest: wb-scaling-apis

### Name Suggestion Rules
1. Extract 1-2 meaningful words from the URL path or the user's description.
2. Slugify: lowercase, hyphens, no accents, no special characters.
3. Spanish is fine: "fin del aprendizaje" → fin-aprendizaje (drop stop words: del, la, el, de).
4. Keep it SHORT. 2 meaningful words + prefix = 3 total. That's the goal.
5. If the URL path is opaque (e.g., /watch?v=abc), use a generic fallback like
   "video", "post", "article" as the second word.
6. NEVER suggest a full title or sentence as the name. "El Futuro del Aprendizaje" is WRONG.
   "yt-fin-aprendizaje" is RIGHT.

## ALWAYS-ASK RULE (CRITICAL)
You MUST always ask the user for ALL of these fields, even though they are optional:
1. source_name — suggest one, but ask if the user wants a different name
2. author — you MUST ask, even though the user can decline
3. comment — you MUST ask, even though the user can decline

"Optional" means the user can leave it empty — it does NOT mean you can skip asking.
If the user says "skip", "none", "no", or "n/a", accept it and move on.

## Conversation Flow (URL trigger — source already created)
1. The system tells you the source was created with: {name}, {type}, {url}.
2. Tell the user: "✅ Source created: {name} ({type}). I suggested the name above.
   Would you like to keep it or change it?"
3. If the user provides a new name: validate it has a valid prefix, update the source.
4. Ask: "👤 Who is the author? (or say 'skip')"
5. Ask: "💬 Any comment about this source? (or say 'skip')"
6. Update the source with author/comment if provided.
7. Confirm: "✅ Source {name} is ready! Author: {author}. Comment: {comment}."

## Conversation Flow (/create — no URL)
1. Ask: "What type of source? (youtube, instagram, facebook, linkedin, web, book,
   course, thought) — or paste a URL."
2. Once you know the type, suggest a name and ask if the user wants to keep it.
3. Ask for author (always).
4. Ask for comment (always).
5. Create the source, activate it, confirm.

## Output Format
When you have collected all information and need to update/create the source,
respond with a JSON block so the system can parse it:
```json
{
  "action": "update_source",
  "source_name": "yt-fin-aprendizaje",
  "author": "Javier Maza",
  "comment": "Entrevista sobre el fin del aprendizaje"
}
```
If the user is just answering a question mid-conversation, respond naturally in
text — do NOT output JSON until you have all the information.
"""


class SourceCreateStep(str, Enum):
    """Steps in the source creation conversation."""

    AWAITING_NAME_CONFIRM = "awaiting_name_confirm"
    AWAITING_AUTHOR = "awaiting_author"
    AWAITING_COMMENT = "awaiting_comment"
    COMPLETE = "complete"
    # For /create flows (no URL)
    AWAITING_TYPE = "awaiting_type"
    AWAITING_NAME = "awaiting_name"


class SourceCreateContext:
    """Tracks the state of a multi-turn source creation conversation."""

    def __init__(
        self,
        source_type: str,
        url: Optional[str] = None,
        suggested_name: Optional[str] = None,
        source_name: Optional[str] = None,
        source_id: Optional[str] = None,
        author: Optional[str] = None,
        comment: Optional[str] = None,
        step: SourceCreateStep = SourceCreateStep.AWAITING_NAME_CONFIRM,
        conversation_history: Optional[list[dict[str, str]]] = None,
    ) -> None:
        self.source_type = source_type
        self.url = url
        self.suggested_name = suggested_name
        self.source_name = source_name
        self.source_id = source_id
        self.author = author
        self.comment = comment
        self.step = step
        self.conversation_history: list[dict[str, str]] = conversation_history or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "url": self.url,
            "suggested_name": self.suggested_name,
            "source_name": self.source_name,
            "source_id": self.source_id,
            "author": self.author,
            "comment": self.comment,
            "step": self.step.value,
            "conversation_history": self.conversation_history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceCreateContext":
        return cls(
            source_type=data["source_type"],
            url=data.get("url"),
            suggested_name=data.get("suggested_name"),
            source_name=data.get("source_name"),
            source_id=data.get("source_id"),
            author=data.get("author"),
            comment=data.get("comment"),
            step=SourceCreateStep(data.get("step", "awaiting_name_confirm")),
            conversation_history=data.get("conversation_history", []),
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


def _extract_json_block(text: str) -> Optional[dict[str, Any]]:
    """Extract a JSON block from LLM response text.

    Looks for ```json ... ``` or bare JSON with "action" key.
    """
    # Try ```json ... ``` first
    json_match = re.search(r"```json\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try bare JSON object
    json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            if isinstance(parsed, dict) and "action" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    return None


class SourceCreateAgent:
    """LLM-driven source creation agent.

    v2: Uses openai.OpenAI with gpt-5.6-luna and reasoning_effort=medium.
    Create-immediately-then-enrich flow for URL triggers.
    """

    def __init__(
        self,
        source_service: SourceService,
        openai_client: Any = None,
        model: str = "gpt-5.6-luna",
        reasoning_effort: str = "medium",
    ) -> None:
        self._source_service = source_service
        self._openai_client = openai_client
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._pending: dict[int, SourceCreateContext] = {}

    def get_pending_context(self, user_id: int) -> Optional[SourceCreateContext]:
        return self._pending.get(user_id)

    def clear_pending(self, user_id: int) -> None:
        self._pending.pop(user_id, None)

    # ------------------------------------------------------------------ #
    #  LLM call
    # ------------------------------------------------------------------ #

    def _call_llm(self, messages: list[dict[str, str]]) -> str:
        """Call the OpenAI-compatible LLM with reasoning_effort."""
        if not self._openai_client:
            logger.warning("source_create_agent.no_openai_client")
            return ""

        try:
            response = self._openai_client.chat.completions.create(
                model=self._model,
                messages=messages,
                reasoning_effort=self._reasoning_effort,
            )
            content = response.choices[0].message.content if response.choices else ""
            return content or ""
        except Exception as exc:
            logger.error(
                "source_create_agent.llm_error",
                extra={"error": str(exc)},
            )
            return ""

    # ------------------------------------------------------------------ #
    #  URL flow — create immediately, then enrich
    # ------------------------------------------------------------------ #

    async def start_url_flow(self, url: str, user_id: int) -> str:
        """Start the source creation flow triggered by a URL-only message.

        v2: Creates the source IMMEDIATELY, then asks for enrichment.
        """
        source_type = SourceTypeResolver.resolve_type(url)
        suggested_name = _suggest_source_name(source_type, url)

        # Check for duplicate URL
        existing = await self._source_service._repository.get_source_by_url(url)
        if existing:
            return (
                f"⚠️ A source with this URL already exists:\n"
                f"📂 \"{existing.get('source_name', 'unknown')}\"\n\n"
                f"Use /switch {existing.get('source_name', '')} to activate it."
            )

        # CREATE THE SOURCE IMMEDIATELY
        try:
            source = await self._source_service.create_source_and_optionally_activate(
                source_name=suggested_name,
                activate=True,
                url=url,
                type=source_type,
            )
            source_id = source.get("id")
            logger.info(
                "source_create_agent.immediate_create",
                extra={
                    "source_id": source_id,
                    "source_name": suggested_name,
                    "type": source_type,
                    "url": url,
                },
            )
        except ValueError as exc:
            return f"❌ {exc}"
        except Exception as exc:
            logger.error(
                "source_create_agent.immediate_create_failed",
                extra={"error": str(exc)},
            )
            return "❌ Failed to create source. Please try again with /create."

        # Set pending context with source_id for the enrich phase
        ctx = SourceCreateContext(
            source_type=source_type,
            url=url,
            suggested_name=suggested_name,
            source_name=suggested_name,
            source_id=source_id,
            step=SourceCreateStep.AWAITING_NAME_CONFIRM,
        )
        # Seed conversation history with the system context
        ctx.conversation_history.append(
            {
                "role": "system",
                "content": (
                    f"The source was just created with: name={suggested_name}, "
                    f"type={source_type}, url={url}, source_id={source_id}. "
                    f"Now enrich it by asking the user for name override, author, and comment."
                ),
            }
        )
        self._pending[user_id] = ctx

        return (
            f"✅ Source created: {suggested_name} ({source_type}).\n"
            f"🔗 {url}\n\n"
            f"I suggested the name above. Would you like to keep it or change it?"
        )

    # ------------------------------------------------------------------ #
    #  /create flow
    # ------------------------------------------------------------------ #

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
                suggested_name=slug,
                step=SourceCreateStep.AWAITING_TYPE,
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
            step=SourceCreateStep.AWAITING_TYPE,
        )
        self._pending[user_id] = ctx
        return (
            "Let's create a new source!\n\n"
            "What type of source is this?\n"
            f"({', '.join(sorted(VALID_SOURCE_TYPES))})\n\n"
            "Or paste a URL to create a source from it."
        )

    # ------------------------------------------------------------------ #
    #  Handle response — LLM-driven conversation
    # ------------------------------------------------------------------ #

    async def handle_response(self, user_message: str, user_id: int) -> str:
        """Process the user's response in the source creation conversation.

        v2: Uses LLM to drive the conversation. Parses JSON output for
        update_source actions.
        """
        ctx = self._pending.get(user_id)
        if ctx is None:
            return "No pending source creation. Use /create to start."

        text = user_message.strip()

        # For /create flows without URL, handle the state machine steps first
        if ctx.step == SourceCreateStep.AWAITING_TYPE:
            return await self._handle_type_step(text, user_id, ctx)

        # For URL-triggered flow or /create with name: use LLM-driven conversation
        # Add user message to conversation history
        ctx.conversation_history.append({"role": "user", "content": text})

        # Build LLM messages
        llm_messages = self._build_llm_messages(ctx)

        # Call LLM
        llm_response = self._call_llm(llm_messages)

        if not llm_response:
            # LLM failed — fall back to state machine
            return await self._fallback_handle(text, user_id, ctx)

        # Check if LLM response contains a JSON action block
        action = _extract_json_block(llm_response)

        if action and action.get("action") == "update_source":
            return await self._handle_update_action(action, user_id, ctx)

        if action and action.get("action") == "create_source":
            return await self._handle_create_action(action, user_id, ctx)

        # Mid-conversation: update context with any info from the user message
        # and return the LLM's text response
        self._update_context_from_user_input(ctx, text)

        # Add assistant response to history
        ctx.conversation_history.append({"role": "assistant", "content": llm_response})

        return llm_response

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    async def _handle_type_step(
        self, text: str, user_id: int, ctx: SourceCreateContext
    ) -> str:
        """Handle the type selection step for /create flows."""
        # Check if user pasted a URL instead of selecting a type
        if UrlDetectorService.is_url(text):
            url = UrlDetectorService.extract_url(text)
            # Delegate to URL flow
            self.clear_pending(user_id)
            return await self.start_url_flow(url, user_id)

        if text.lower() in VALID_SOURCE_TYPES:
            ctx.source_type = text.lower()
            prefix = _TYPE_PREFIX_MAP.get(ctx.source_type, "wb")

            if ctx.source_name:
                # Name was pre-filled via /create <name>
                ctx.step = SourceCreateStep.AWAITING_AUTHOR
                return "👤 Who is the author? (or say 'skip' to leave empty)"
            else:
                # Ask for name
                suggested = f"{prefix}-new-source"
                ctx.suggested_name = suggested
                ctx.step = SourceCreateStep.AWAITING_NAME
                return (
                    f"📝 Great! Suggested name: {suggested}\n\n"
                    f"Do you want to use this name, or provide a different one?"
                )

        return (
            f"❌ Invalid type. Please choose from:\n"
            f"{', '.join(sorted(VALID_SOURCE_TYPES))}\n\n"
            f"Or paste a URL to create a source from it."
        )

    async def _handle_update_action(
        self, action: dict[str, Any], user_id: int, ctx: SourceCreateContext
    ) -> str:
        """Handle the LLM's JSON output to update the source."""
        source_id = ctx.source_id
        if not source_id:
            return "❌ No source to update. Use /create to start."

        new_name = action.get("source_name")
        new_author = action.get("author")
        new_comment = action.get("comment")

        # Validate name prefix if provided
        if new_name:
            has_prefix = any(new_name.startswith(p) for p in VALID_PREFIXES)
            if not has_prefix:
                return (
                    f"❌ Source name must start with a type prefix.\n"
                    f"Valid prefixes: {', '.join(VALID_PREFIXES)}\n"
                    f"Try again."
                )

        try:
            updated = await self._source_service.update_source(
                source_id=source_id,
                source_name=new_name,
                author=new_author,
                comment=new_comment,
            )
            if not updated:
                return "❌ Failed to update source. Please try again."

            # Update context
            if new_name:
                ctx.source_name = new_name
            if new_author:
                ctx.author = new_author
            if new_comment:
                ctx.comment = new_comment

            self.clear_pending(user_id)
            logger.info(
                "source_create_agent.source_updated",
                extra={
                    "source_id": source_id,
                    "source_name": ctx.source_name,
                    "author": ctx.author,
                    "comment": ctx.comment,
                },
            )

            final_name = ctx.source_name or ctx.suggested_name or "unknown"
            return (
                f"✅ Source \"{final_name}\" is ready!\n"
                f"📎 Type: {ctx.source_type}\n"
                f"🔗 URL: {ctx.url or 'N/A'}\n"
                f"👤 Author: {ctx.author or 'N/A'}\n"
                f"💬 Comment: {ctx.comment or 'N/A'}"
            )
        except Exception as exc:
            logger.error(
                "source_create_agent.update_failed",
                extra={"error": str(exc)},
            )
            return "❌ Failed to update source. Please try again."

    async def _handle_create_action(
        self, action: dict[str, Any], user_id: int, ctx: SourceCreateContext
    ) -> str:
        """Handle the LLM's JSON output to create a new source (/create flow)."""
        source_name = action.get("source_name") or ctx.source_name or ctx.suggested_name
        source_type = action.get("type") or ctx.source_type
        author = action.get("author") or ctx.author
        comment = action.get("comment") or ctx.comment

        if not source_name:
            return "❌ Missing source name. Please try again with /create."

        # Validate name prefix
        has_prefix = any(source_name.startswith(p) for p in VALID_PREFIXES)
        if not has_prefix:
            return (
                f"❌ Source name must start with a type prefix.\n"
                f"Valid prefixes: {', '.join(VALID_PREFIXES)}"
            )

        try:
            source = await self._source_service.create_source_and_optionally_activate(
                source_name=source_name,
                author=author,
                comment=comment,
                activate=True,
                url=ctx.url,
                type=source_type,
            )
            self.clear_pending(user_id)
            logger.info(
                "source_create_agent.created",
                extra={"source_name": source_name, "type": source_type},
            )
            return (
                f"✅ Source \"{source_name}\" created and activated!\n"
                f"📎 Type: {source_type}\n"
                f"🔗 URL: {ctx.url or 'N/A'}\n"
                f"👤 Author: {author or 'N/A'}\n"
                f"💬 Comment: {comment or 'N/A'}"
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

    def _build_llm_messages(self, ctx: SourceCreateContext) -> list[dict[str, str]]:
        """Build the messages list for the LLM call."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SOURCE_CREATE_SYSTEM_PROMPT},
        ]

        # Add context about the current source state
        source_info = (
            f"Current source state:\n"
            f"- source_id: {ctx.source_id or 'not yet created'}\n"
            f"- type: {ctx.source_type}\n"
            f"- url: {ctx.url or 'N/A'}\n"
            f"- suggested_name: {ctx.suggested_name or 'N/A'}\n"
            f"- current_name: {ctx.source_name or 'N/A'}\n"
            f"- author: {ctx.author or 'not provided yet'}\n"
            f"- comment: {ctx.comment or 'not provided yet'}\n"
            f"- step: {ctx.step.value}\n"
        )
        messages.append({"role": "system", "content": source_info})

        # Add conversation history
        for msg in ctx.conversation_history:
            messages.append(msg)

        return messages

    def _update_context_from_user_input(self, ctx: SourceCreateContext, text: str) -> None:
        """Try to extract useful info from the user's message into the context."""
        text_lower = text.lower().strip()

        # Check for skip/decline
        is_skip = text_lower in ("skip", "none", "no", "n/a", "-", "no thanks", "nah")

        # Check if user is accepting the suggested name
        if ctx.step == SourceCreateStep.AWAITING_NAME_CONFIRM:
            if text_lower in ("yes", "y", "ok", "sure", "accept", "keep it", "fine", "good"):
                ctx.source_name = ctx.suggested_name
                ctx.step = SourceCreateStep.AWAITING_AUTHOR
            elif not is_skip:
                # User might be providing a new name
                slug = slugify(text)
                has_prefix = any(slug.startswith(p) for p in VALID_PREFIXES)
                if has_prefix:
                    ctx.source_name = slug
                    ctx.step = SourceCreateStep.AWAITING_AUTHOR
                # Otherwise, the LLM will handle the response
        elif ctx.step == SourceCreateStep.AWAITING_AUTHOR:
            if not is_skip:
                ctx.author = text
                ctx.step = SourceCreateStep.AWAITING_COMMENT
            else:
                ctx.step = SourceCreateStep.AWAITING_COMMENT
        elif ctx.step == SourceCreateStep.AWAITING_COMMENT:
            if not is_skip:
                ctx.comment = text

    async def _fallback_handle(
        self, text: str, user_id: int, ctx: SourceCreateContext
    ) -> str:
        """Fallback state machine when LLM is unavailable."""
        is_skip = text.lower().strip() in ("skip", "none", "no", "n/a", "-")

        if ctx.step == SourceCreateStep.AWAITING_NAME_CONFIRM:
            if text.lower().strip() in ("yes", "y", "ok", "sure", "accept"):
                ctx.source_name = ctx.suggested_name
                ctx.step = SourceCreateStep.AWAITING_AUTHOR
                return "👤 Who is the author? (or say 'skip' to leave empty)"
            else:
                slug = slugify(text)
                has_prefix = any(slug.startswith(p) for p in VALID_PREFIXES)
                if has_prefix:
                    ctx.source_name = slug
                    ctx.step = SourceCreateStep.AWAITING_AUTHOR
                    return "👤 Who is the author? (or say 'skip' to leave empty)"
                return (
                    f"❌ Source name must start with a type prefix.\n"
                    f"Valid prefixes: {', '.join(VALID_PREFIXES)}\n"
                    f"Try again or say 'yes' to use the suggested name."
                )

        elif ctx.step == SourceCreateStep.AWAITING_AUTHOR:
            if not is_skip:
                ctx.author = text
            ctx.step = SourceCreateStep.AWAITING_COMMENT
            return "💬 Any comment about this source? (or say 'skip' to leave empty)"

        elif ctx.step == SourceCreateStep.AWAITING_COMMENT:
            if not is_skip:
                ctx.comment = text
            # Trigger update
            if ctx.source_id:
                action = {
                    "action": "update_source",
                    "source_name": ctx.source_name,
                    "author": ctx.author,
                    "comment": ctx.comment,
                }
                return await self._handle_update_action(action, user_id, ctx)
            else:
                # /create flow — create the source
                action = {
                    "action": "create_source",
                    "source_name": ctx.source_name or ctx.suggested_name,
                    "type": ctx.source_type,
                    "author": ctx.author,
                    "comment": ctx.comment,
                }
                return await self._handle_create_action(action, user_id, ctx)

        return "Please use /create to start a new source creation."
