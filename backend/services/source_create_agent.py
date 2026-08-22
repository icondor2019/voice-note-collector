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
    "test": "ts",
    "other": "ot",
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
| ts-    | test      | Test sources, experiments        |
| ot-    | other     | Anything that doesn't fit        |

### Invalid Type Handling (CRITICAL)
If the user provides an invalid type synonym like 'lesson', 'article', 'podcast', etc.,
do NOT silently map it. Instead, say:
"I don't recognize '{invalid_type}'. Did you mean one of these? → {suggest 2-3 closest canonical types}"
Only proceed after the user confirms a canonical type. Never write an invalid type to the database.

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
6. After collecting name, author, and comment, DO NOT apply changes immediately.
   Show a confirmation summary (see Confirmation Flow below).

## Conversation Flow (/create — no URL)
1. Ask: "What type of source? (youtube, instagram, facebook, linkedin, web, book,
   course, thought, test, other) — or paste a URL."
2. Once you know the type, suggest a name and ask if the user wants to keep it.
3. Ask for author (always).
4. Ask for comment (always).
5. After collecting all fields, show a confirmation summary (see Confirmation Flow below).

## Confirmation Flow (CRITICAL — replaces auto-apply)
After collecting name, author, and comment, do NOT apply changes immediately.
Instead, show a summary of ALL fields (including empty ones) and ask:
"Anything else to add, or shall I apply these changes?"

Example summary:
"Here's what I'll update:
📝 Name: yt-scaling-apis
📎 Type: youtube
🔗 URL: https://youtube.com/watch?v=abc
👤 Author: John Doe
💬 Comment: (empty)

Anything else to add, or shall I apply these changes?"

Apply ONLY on:
- Clear affirmative: 'confirm', 'correct', 'go ahead', 'yes', 'apply', 'that's all', 'looks good'
- 'no, that's all' or 'no, apply' as answer to the "anything else?" prompt

If the user provides a correction or additional information (e.g., "author: Jane",
"actually the type is course"), update the field(s), rebuild the summary, and re-ask.

If the user says a bare ambiguous 'no' without context, ask for clarification:
"Just to confirm — do you mean 'no, that's all, apply' or 'no, I want to change something'?"

On apply, say: "We are now in note mode." Do NOT mention what the next audio will do.

## Output Format
When you have collected all information and the user has confirmed, respond with a
JSON block so the system can parse it:
```json
{
  "action": "update_source",
  "source_name": "yt-fin-aprendizaje",
  "type": "youtube",
  "author": "Javier Maza",
  "comment": "Entrevista sobre el fin del aprendizaje"
}
```
If the user is just answering a question mid-conversation, respond naturally in
text — do NOT output JSON until you have all the information and the user has confirmed.
"""


class SourceCreateStep(str, Enum):
    """Steps in the source creation conversation."""

    AWAITING_NAME_CONFIRM = "awaiting_name_confirm"
    AWAITING_AUTHOR = "awaiting_author"
    AWAITING_COMMENT = "awaiting_comment"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
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
        type: Optional[str] = None,
        step: SourceCreateStep = SourceCreateStep.AWAITING_NAME_CONFIRM,
        conversation_history: Optional[list[dict[str, str]]] = None,
        flow: str = "enrich",
    ) -> None:
        self.source_type = source_type
        self.url = url
        self.suggested_name = suggested_name
        self.source_name = source_name
        self.source_id = source_id
        self.author = author
        self.comment = comment
        self.type = type
        self.step = step
        self.conversation_history: list[dict[str, str]] = conversation_history or []
        self.flow = flow

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "url": self.url,
            "suggested_name": self.suggested_name,
            "source_name": self.source_name,
            "source_id": self.source_id,
            "author": self.author,
            "comment": self.comment,
            "type": self.type,
            "step": self.step.value,
            "conversation_history": self.conversation_history,
            "flow": self.flow,
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
            type=data.get("type"),
            step=SourceCreateStep(data.get("step", "awaiting_name_confirm")),
            conversation_history=data.get("conversation_history", []),
            flow=data.get("flow", "enrich"),
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
    #  Deterministic URL creation (no LLM, no pending context)
    # ------------------------------------------------------------------ #

    async def create_source_from_url(self, url: str, user_id: int) -> str:
        """Create a source deterministically from a URL.

        No LLM call. No pending enrichment context. No follow-up questions.
        Resolves type, generates default name, creates and activates source,
        returns confirmation.
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
                "source_create_agent.deterministic_create",
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
                "source_create_agent.deterministic_create_failed",
                extra={"error": str(exc)},
            )
            return "❌ Failed to create source. Please try again with /create."

        return (
            f"✅ Source created: {suggested_name} ({source_type}).\n"
            f"🔗 {url}\n\n"
            f"Use /update to enrich this source (name, author, comment)."
        )

    # ------------------------------------------------------------------ #
    #  Enrichment flow for any existing active source
    # ------------------------------------------------------------------ #

    async def start_enrich_flow(self, user_id: int, source: dict) -> str:
        """Start enrichment conversation for ANY existing active source.

        Source-agnostic: works regardless of how the source was created
        (URL, /create, /switch, inline keyboard). Clears any existing
        pending context before starting.
        """
        source_id = source.get("id")
        source_name = source.get("source_name", "unknown")
        source_type = source.get("type", "web")
        url = source.get("url")
        author = source.get("author")
        comment = source.get("comment")

        # Clear any existing pending context to prevent state corruption
        self.clear_pending(user_id)

        suggested_name = source_name
        if not suggested_name or suggested_name == "unknown":
            suggested_name = _suggest_source_name(source_type, url)

        ctx = SourceCreateContext(
            source_type=source_type,
            url=url,
            suggested_name=suggested_name,
            source_name=source_name,
            source_id=source_id,
            author=author,
            comment=comment,
            type=source_type,
            step=SourceCreateStep.AWAITING_NAME_CONFIRM,
            flow="enrich",
        )
        # Seed conversation history with the source's CURRENT state
        ctx.conversation_history.append(
            {
                "role": "system",
                "content": (
                    f"The active source has: name={source_name}, "
                    f"type={source_type}, url={url or 'N/A'}, source_id={source_id}, "
                    f"author={author or 'not set'}, comment={comment or 'not set'}. "
                    f"Enrich it by asking the user for name override, author, and comment. "
                    f"After collecting all fields, show a confirmation summary and wait "
                    f"for explicit confirmation before applying."
                ),
            }
        )
        self._pending[user_id] = ctx

        return (
            f"📂 Active source: {source_name} ({source_type}).\n\n"
            f"I suggested the name above. Would you like to keep it or change it?"
        )

    # ------------------------------------------------------------------ #
    #  /create flow
    # ------------------------------------------------------------------ #

    async def start_create_flow(
        self, user_id: int, name_or_url: Optional[str] = None
    ) -> str:
        """Start the source creation flow triggered by /create command."""
        # If argument is a URL, treat as deterministic URL creation
        if name_or_url and UrlDetectorService.is_url(name_or_url):
            url = UrlDetectorService.extract_url(name_or_url)
            return await self.create_source_from_url(url, user_id)

        # If argument is a name, create immediately (no guided flow)
        if name_or_url:
            slug = slugify(name_or_url)
            if not slug:
                return "❌ Invalid source name. Use /create without arguments to start the guided flow."

            # Check for duplicate name
            existing = await self._source_service._repository.get_source_by_name(slug)
            if existing:
                return (
                    f"❌ Source \"{slug}\" already exists. Use /switch to activate it."
                )

            # Create immediately with activate=True, type=None
            try:
                source = await self._source_service.create_source_and_optionally_activate(
                    source_name=slug,
                    activate=True,
                    type=None,
                )
                source_id = source.get("id")
                logger.info(
                    "source_create_agent.created",
                    extra={
                        "source_id": source_id,
                        "source_name": slug,
                        "type": None,
                    },
                )
            except ValueError as exc:
                return f"❌ {exc}"
            except Exception as exc:
                logger.error(
                    "source_create_agent.named_create_failed",
                    extra={"error": str(exc)},
                )
                return "❌ Failed to create source. Please try again with /create."

            return (
                f"✅ Source created and activated: {slug}.\n\n"
                f"We are now in note mode.\n"
                f"Use /update to enrich this source (name, author, comment)."
            )

        # No argument — start guided flow
        ctx = SourceCreateContext(
            source_type="thought",
            step=SourceCreateStep.AWAITING_TYPE,
            flow="create",
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
        """Process the user's responses in the source creation conversation.

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

        # Confirmation step: handle locally (no LLM call) to avoid ambiguity
        if ctx.step == SourceCreateStep.AWAITING_CONFIRMATION:
            return await self._handle_confirmation_step(text, user_id, ctx)

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
            # Delegate to deterministic URL creation
            self.clear_pending(user_id)
            return await self.create_source_from_url(url, user_id)

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
        """Handle the LLM's JSON output to update the source.

        Instead of applying immediately, extract fields into context and
        transition to AWAITING_CONFIRMATION to show a summary first.
        """
        new_name = action.get("source_name")
        new_author = action.get("author")
        new_comment = action.get("comment")
        new_type = action.get("type")

        # Validate name prefix if provided
        if new_name:
            has_prefix = any(new_name.startswith(p) for p in VALID_PREFIXES)
            if not has_prefix:
                return (
                    f"❌ Source name must start with a type prefix.\n"
                    f"Valid prefixes: {', '.join(VALID_PREFIXES)}\n"
                    f"Try again."
                )

        # Validate type if provided
        if new_type and new_type not in VALID_SOURCE_TYPES:
            return (
                f"❌ Invalid source type '{new_type}'.\n"
                f"Must be one of: {', '.join(sorted(VALID_SOURCE_TYPES))}"
            )

        # Update context with proposed values (don't apply yet)
        if new_name is not None:
            ctx.source_name = new_name
        if new_author is not None:
            ctx.author = new_author
        if new_comment is not None:
            ctx.comment = new_comment
        if new_type is not None:
            ctx.type = new_type

        # Transition to confirmation step
        ctx.step = SourceCreateStep.AWAITING_CONFIRMATION
        return self._build_confirmation_summary(ctx)

    def _build_confirmation_summary(self, ctx: SourceCreateContext) -> str:
        """Build a confirmation summary showing all proposed changes.

        Shows all fields including empty ones with '(empty)' placeholder.
        Ends with a prompt asking if anything else should be added.
        """
        name = ctx.source_name or ctx.suggested_name or "(empty)"
        source_type = ctx.type or ctx.source_type or "(empty)"
        url = ctx.url or "(empty)"
        author = ctx.author or "(empty)"
        comment = ctx.comment or "(empty)"

        return (
            f"Here's what I'll update:\n"
            f"📝 Name: {name}\n"
            f"📎 Type: {source_type}\n"
            f"🔗 URL: {url}\n"
            f"👤 Author: {author}\n"
            f"💬 Comment: {comment}\n\n"
            f"Anything else to add, or shall I apply these changes?"
        )

    async def _handle_confirmation_step(
        self, text: str, user_id: int, ctx: SourceCreateContext
    ) -> str:
        """Handle the user's response during the confirmation step.

        Detects:
        - Clear affirmative → apply changes
        - 'no, that's all' → apply changes
        - Correction/addition → update field, rebuild summary, re-ask
        - Ambiguous 'no' → ask for clarification
        """
        text_lower = text.lower().strip()

        # Dispatch based on flow marker: create vs enrich
        async def _apply_or_create() -> str:
            if ctx.flow == "create":
                return await self._create_source_from_context(user_id, ctx)
            return await self._apply_enrichment(user_id, ctx)

        # Clear affirmative responses
        affirmative = {
            "confirm", "correct", "go ahead", "yes", "apply", "that's all",
            "looks good", "ok", "sure", "yep", "y", "please do", "do it",
            "apply it", "apply changes", "save", "save it",
        }
        if text_lower in affirmative:
            return await _apply_or_create()

        # "no, that's all" variants — clear answer to "anything else?"
        no_thats_all = {
            "no, that's all", "no that's all", "no, thats all", "no thats all",
            "no, apply", "no apply", "nothing else", "nope, that's all",
            "nope, apply", "no, go ahead", "no, go ahead and apply",
        }
        if text_lower in no_thats_all:
            return await _apply_or_create()

        # Check for corrections/additions (e.g., "author: Jane", "the type is course")
        correction = self._extract_correction(text, ctx)
        if correction:
            return self._build_confirmation_summary(ctx)

        # Ambiguous bare "no" — ask for clarification
        if text_lower in ("no", "nope", "nah"):
            return (
                "Just to confirm — do you mean 'no, that's all, apply' "
                "or 'no, I want to change something'?"
            )

        # Anything else — treat as potential correction or additional info
        # Try to extract field updates from the text
        correction = self._extract_correction(text, ctx)
        if correction:
            return self._build_confirmation_summary(ctx)

        # If we can't parse it, ask for clarification
        return (
            "I'm not sure if you want to apply the changes or modify something. "
            "Say 'apply' to save, or tell me what you'd like to change."
        )

    def _extract_correction(self, text: str, ctx: SourceCreateContext) -> bool:
        """Try to extract field corrections from user text.

        Returns True if a correction was found and applied to ctx.
        """
        import re

        # Pattern: "field: value" or "field is value"
        # Use original text for value extraction (preserve case)
        # author: Jane
        author_match = re.search(r"(?:author|written by|by)\s*[:=]\s*(.+)", text, re.IGNORECASE)
        if author_match:
            ctx.author = author_match.group(1).strip()
            return True

        # comment: some comment
        comment_match = re.search(r"(?:comment|note|description)\s*[:=]\s*(.+)", text, re.IGNORECASE)
        if comment_match:
            ctx.comment = comment_match.group(1).strip()
            return True

        # type: course
        type_match = re.search(r"(?:type|category)\s*[:=]\s*(.+)", text, re.IGNORECASE)
        if type_match:
            new_type = type_match.group(1).strip().lower()
            if new_type in VALID_SOURCE_TYPES:
                ctx.type = new_type
                # Re-derive name prefix if name exists
                if ctx.source_name:
                    prefix = _TYPE_PREFIX_MAP.get(new_type, "wb")
                    # Replace existing prefix
                    for old_prefix in VALID_PREFIXES:
                        if ctx.source_name.startswith(old_prefix):
                            ctx.source_name = f"{prefix}-{ctx.source_name[len(old_prefix):]}"
                            break
                return True

        # name: new-name
        name_match = re.search(r"(?:name|rename)\s*[:=]\s*(.+)", text, re.IGNORECASE)
        if name_match:
            new_name = name_match.group(1).strip()
            slug = slugify(new_name)
            has_prefix = any(slug.startswith(p) for p in VALID_PREFIXES)
            if has_prefix:
                ctx.source_name = slug
                return True

        return False

    async def _apply_enrichment(self, user_id: int, ctx: SourceCreateContext) -> str:
        """Apply the staged enrichment changes to the source.

        Persists all staged fields, clears pending context, and returns
        the final source summary with 'We are now in note mode.'
        Does NOT mention what the next audio will do.
        """
        source_id = ctx.source_id
        if not source_id:
            return "❌ No source to update. Use /create to start."

        new_name = ctx.source_name
        new_author = ctx.author
        new_comment = ctx.comment
        new_type = ctx.type

        # If type changed and name still has the old type's prefix, re-derive name prefix
        if new_type and new_name:
            new_prefix = _TYPE_PREFIX_MAP.get(new_type, "wb")
            # Check if current name has a mismatched prefix
            for old_type, old_prefix in _TYPE_PREFIX_MAP.items():
                if old_type != new_type and new_name.startswith(f"{old_prefix}-"):
                    # Re-derive name with new prefix
                    new_name = f"{new_prefix}-{new_name[len(old_prefix) + 1:]}"
                    break

        try:
            updated = await self._source_service.update_source(
                source_id=source_id,
                source_name=new_name,
                author=new_author,
                comment=new_comment,
                type=new_type,
            )
            if not updated:
                return "❌ Failed to update source. Please try again."

            # Update context for the final summary
            if new_name:
                ctx.source_name = new_name
            if new_type:
                ctx.source_type = new_type

            self.clear_pending(user_id)
            logger.info(
                "source_create_agent.source_updated",
                extra={
                    "source_id": source_id,
                    "source_name": ctx.source_name,
                    "type": ctx.source_type,
                    "author": ctx.author,
                    "comment": ctx.comment,
                },
            )

            final_name = ctx.source_name or ctx.suggested_name or "unknown"
            final_type = ctx.type or ctx.source_type or "unknown"
            return (
                f"✅ Source updated!\n"
                f"📝 Name: {final_name}\n"
                f"📎 Type: {final_type}\n"
                f"🔗 URL: {ctx.url or '(empty)'}\n"
                f"👤 Author: {ctx.author or '(empty)'}\n"
                f"💬 Comment: {ctx.comment or '(empty)'}\n\n"
                f"We are now in note mode."
            )
        except Exception as exc:
            logger.error(
                "source_create_agent.update_failed",
                extra={"error": str(exc)},
            )
            return "❌ Failed to update source. Please try again."

    async def _create_source_from_context(
        self, user_id: int, ctx: SourceCreateContext
    ) -> str:
        """Create a new source from the collected context (guided /create flow).

        Called by _handle_confirmation_step() when ctx.flow == "create".
        Extracts name, type, author, comment, and optional URL from the
        context, creates the source, activates it, clears pending context,
        and returns a creation confirmation message.
        """
        source_name = ctx.source_name or ctx.suggested_name
        if not source_name:
            self.clear_pending(user_id)
            return "❌ Missing source name. Please try again with /create."

        # Validate name prefix
        has_prefix = any(source_name.startswith(p) for p in VALID_PREFIXES)
        if not has_prefix:
            self.clear_pending(user_id)
            return (
                f"❌ Source name must start with a type prefix.\n"
                f"Valid prefixes: {', '.join(VALID_PREFIXES)}"
            )

        source_type = ctx.type or ctx.source_type

        try:
            source = await self._source_service.create_source_and_optionally_activate(
                source_name=source_name,
                author=ctx.author,
                comment=ctx.comment,
                activate=True,
                url=ctx.url,
                type=source_type,
            )
            self.clear_pending(user_id)
            logger.info(
                "source_create_agent.created",
                extra={
                    "source_name": source_name,
                    "type": source_type,
                    "source_id": source.get("id"),
                },
            )
            final_type = source_type or "unknown"
            return (
                f"✅ Source created and activated!\n"
                f"📝 Name: {source_name}\n"
                f"📎 Type: {final_type}\n"
                f"🔗 URL: {ctx.url or '(empty)'}\n"
                f"👤 Author: {ctx.author or '(empty)'}\n"
                f"💬 Comment: {ctx.comment or '(empty)'}\n\n"
                f"We are now in note mode."
            )
        except ValueError as exc:
            self.clear_pending(user_id)
            return f"❌ {exc}"
        except Exception as exc:
            logger.error(
                "source_create_agent.create_from_context_failed",
                extra={"error": str(exc)},
            )
            self.clear_pending(user_id)
            return "❌ Failed to create source. Please try again with /create."

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

        if ctx.step == SourceCreateStep.AWAITING_NAME:
            # User is providing a name (no suggestion was made yet)
            slug = slugify(text)
            has_prefix = any(slug.startswith(p) for p in VALID_PREFIXES)
            if has_prefix:
                ctx.source_name = slug
                ctx.step = SourceCreateStep.AWAITING_AUTHOR
                return "👤 Who is the author? (or say 'skip' to leave empty)"
            return (
                f"❌ Source name must start with a type prefix.\n"
                f"Valid prefixes: {', '.join(VALID_PREFIXES)}\n"
                f"Try again."
            )

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
            # Transition to confirmation instead of auto-applying
            ctx.step = SourceCreateStep.AWAITING_CONFIRMATION
            return self._build_confirmation_summary(ctx)

        return "Please use /create to start a new source creation."
