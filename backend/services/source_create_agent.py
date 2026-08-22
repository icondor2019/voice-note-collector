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
Your job is to help the user create and enrich sources by understanding their
INTENTION from each message — not by asking one-by-one questions.

## CRITICAL: Intention-Based, Multilingual, First-Interaction Capture
- Capture ALL available information from the user's FIRST message (name, type, author, comment).
- Do NOT ask for fields one at a time. Show what you understood in a summary.
- Understand INTENTION from the message content, not from keywords.
- Support Spanish, English, and mixed-language messages naturally.
- If the user says anything indicating approval — in any language — save immediately.
  Examples: "si", "claro", "dale", "guarda", "go ahead", "looks good", "that's all",
  "no I don't care just save it", "si, apply it", "claro, go ahead", "dale, guardalo".
- NEVER ask the user to say 'skip'. If a field is not mentioned, leave it as null.
- You may SUGGEST refinements (e.g., "I suggest the name bk-parasitic-minds") but only
  as notes within the summary, not as blocking questions.

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

## Intention Values
You must ALWAYS respond with a JSON block containing these three fields:

1. **"reply"**: The user-facing message (can be multi-line, any language).
2. **"fields"**: Parsed field values from the user's message. Set to `null` for fields
   the user did NOT mention. NEVER invent values. Fields: source_name, type, author, comment.
3. **"intention"**: One of:
   - **"capture"**: You parsed fields from the user's message. Show a summary of what you
     understood. Suggest refinements as notes. Stay in awaiting_input.
   - **"apply"**: The user approved (in any language). Save immediately with whatever you
     understood. Transition to complete.
   - **"ask"**: The user's message was ambiguous or contained no useful info. Ask a
     clarifying question. Stay in awaiting_input.

## Output Format (CRITICAL — ALWAYS return this JSON structure)
You MUST ALWAYS respond with a JSON block in this exact format:
```json
{
  "reply": "Here is what I understood:\nName: bk-parasitic-minds\nAuthor: Pablo Malo\n\nDoes this look right?",
  "fields": {
    "source_name": "bk-parasitic-minds",
    "type": "book",
    "author": "Pablo Malo",
    "comment": null
  },
  "intention": "capture"
}
```

### Examples by intention:

**intention: "capture"** (user provided info, show summary):
```json
{
  "reply": "Here's what I captured:\n📝 Name: yt-fin-aprendizaje\n👤 Author: Javier Maza\n💬 Comment: Entrevista sobre el fin del aprendizaje\n\nDoes this look right? Say 'yes' to save, or tell me what to change.",
  "fields": {
    "source_name": "yt-fin-aprendizaje",
    "type": "youtube",
    "author": "Javier Maza",
    "comment": "Entrevista sobre el fin del aprendizaje"
  },
  "intention": "capture"
}
```

**intention: "apply"** (user approved, save immediately):
```json
{
  "reply": "✅ Saved! We are now in note mode.",
  "fields": {
    "source_name": "yt-fin-aprendizaje",
    "type": "youtube",
    "author": "Javier Maza",
    "comment": "Entrevista sobre el fin del aprendizaje"
  },
  "intention": "apply"
}
```

**intention: "ask"** (ambiguous, ask clarifying question):
```json
{
  "reply": "What would you like to update? You can change the name, author, comment, or type.",
  "fields": {
    "source_name": null,
    "type": null,
    "author": null,
    "comment": null
  },
  "intention": "ask"
}
```

On apply, the reply should include "We are now in note mode." Do NOT mention what the next audio will do.
"""


class SourceCreateStep(str, Enum):
    """Steps in the source creation conversation."""

    AWAITING_INPUT = "awaiting_input"
    COMPLETE = "complete"


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
        step: SourceCreateStep = SourceCreateStep.AWAITING_INPUT,
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
        raw_step = data.get("step", "awaiting_input")
        try:
            step = SourceCreateStep(raw_step)
        except ValueError:
            # Old step values (e.g. "awaiting_name_confirm", "awaiting_type") are
            # no longer valid — fall back to AWAITING_INPUT so the conversation
            # can continue.
            step = SourceCreateStep.AWAITING_INPUT
        return cls(
            source_type=data["source_type"],
            url=data.get("url"),
            suggested_name=data.get("suggested_name"),
            source_name=data.get("source_name"),
            source_id=data.get("source_id"),
            author=data.get("author"),
            comment=data.get("comment"),
            type=data.get("type"),
            step=step,
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

    Looks for ```json ... ``` or bare JSON with "intention" or "action" key.
    Handles nested JSON objects (e.g. fields dict inside the top-level object).
    """
    # Try ```json ... ``` first
    json_match = re.search(r"```json\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try bare JSON object — use a brace-counting approach for nested objects
    start = text.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        if isinstance(parsed, dict) and (
                            "intention" in parsed or "action" in parsed
                        ):
                            return parsed
                    except json.JSONDecodeError:
                        pass
                    break

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
            step=SourceCreateStep.AWAITING_INPUT,
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
                    f"The user wants to enrich this source. Capture all information "
                    f"from the user's first message and show what you understood. "
                    f"Save immediately on any approval signal in any language."
                ),
            }
        )
        self._pending[user_id] = ctx

        return (
            f"📂 Active source: {source_name} ({source_type}).\n\n"
            f"Tell me what you'd like to update — name, author, comment, or anything else."
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
            step=SourceCreateStep.AWAITING_INPUT,
            flow="create",
        )
        self._pending[user_id] = ctx
        return (
            "Let's create a new source!\n\n"
            "Tell me about it — what type, name, author, and any comment. "
            "You can describe it in your own words, in any language."
        )

    # ------------------------------------------------------------------ #
    #  Handle response — LLM-driven conversation
    # ------------------------------------------------------------------ #

    async def handle_response(self, user_message: str, user_id: int) -> str:
        """Process the user's responses in the source creation conversation.

        All messages go through the LLM (intention-based). The only exception
        is URL-only messages during /create guided flow, which are handled
        deterministically before the LLM call.
        """
        ctx = self._pending.get(user_id)
        if ctx is None:
            return "No pending source creation. Use /create to start."

        text = user_message.strip()

        # Pre-LLM URL-only check: create flow + URL-only message → deterministic creation
        if ctx.flow == "create" and UrlDetectorService.is_url(text):
            url = UrlDetectorService.extract_url(text)
            self.clear_pending(user_id)
            return await self.create_source_from_url(url, user_id)

        # Add user message to conversation history
        ctx.conversation_history.append({"role": "user", "content": text})

        # Build LLM messages
        llm_messages = self._build_llm_messages(ctx)

        # Call LLM
        llm_response = self._call_llm(llm_messages)

        if not llm_response:
            # LLM failed — graceful error, keep context alive for retry
            return "I'm having trouble processing that. Could you try again?"

        # Parse JSON from LLM response
        parsed = _extract_json_block(llm_response)

        if not parsed or "intention" not in parsed:
            # No valid JSON or missing intention key — graceful error
            return "I'm having trouble processing that. Could you try again?"

        return await self._handle_llm_response(parsed, user_id, ctx)

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    async def _handle_llm_response(
        self, parsed: dict[str, Any], user_id: int, ctx: SourceCreateContext
    ) -> str:
        """Handle the LLM's structured JSON response.

        Extracts reply, fields, and intention. Validates field values.
        Routes by intention: apply → persist, capture/ask → show reply.
        """
        reply = parsed.get("reply", "")
        fields = parsed.get("fields", {})
        intention = parsed.get("intention", "")

        if not isinstance(fields, dict):
            fields = {}

        # Extract field values (null means user didn't mention)
        new_name = fields.get("source_name")
        new_type = fields.get("type")
        new_author = fields.get("author")
        new_comment = fields.get("comment")

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

        # Update context with any non-null fields
        if new_name is not None:
            ctx.source_name = new_name
        if new_type is not None:
            ctx.type = new_type
        if new_author is not None:
            ctx.author = new_author
        if new_comment is not None:
            ctx.comment = new_comment

        # Route by intention
        if intention == "apply":
            if ctx.flow == "create":
                result = await self._create_source_from_context(user_id, ctx)
            else:
                result = await self._apply_enrichment(user_id, ctx)
            return result

        # intention == "capture" or "ask" — show reply, stay in AWAITING_INPUT
        ctx.conversation_history.append({"role": "assistant", "content": reply})
        return reply

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

        Called by _handle_llm_response() when intention == "apply" and ctx.flow == "create".
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
            f"- flow: {ctx.flow}\n"
        )
        messages.append({"role": "system", "content": source_info})

        # Add conversation history
        for msg in ctx.conversation_history:
            messages.append(msg)

        return messages

    # TODO: Fall back to another LLM provider in a future session. The deterministic
    # keyword-matching fallback was removed in favor of always-probabilistic LLM-driven
    # interaction.
