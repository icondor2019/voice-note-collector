# 1. Feature: url_source_capture (v2 — routing fix + create-immediately-then-enrich)

---

## 2. Context

The Voice Notes AI app currently creates sources via `/create <name>` (slugifies, activates) or `POST /api/sources` (manual fields). The `sources` table now has `url` and `type` columns (added in v1 of this feature).

**v1 was implemented but failed in live testing.** Three bugs were found (see §10 Post-Mortem). This v2 plan fixes them and changes the core design.

### What went wrong in v1 (summary — full post-mortem in §10)

1. **Routing bug (critical)**: `MultiAgentService.handle()` hardcodes `source_create_context: None` and never hydrates it from `SourceCreateAgent.get_pending_context()`. After the initial URL message, all subsequent messages routed to the generic chat_node — the `SourceCreateAgent` was never invoked again. The agent literally said "I don't have the ability to save sources."
2. **Design bug**: v1 created the source only AFTER collecting all fields. The user's intent is: **URL detection → source created immediately → agent enriches/updates afterward**. Source creation is mandatory on URL detection.
3. **Prompt bug**: The system prompt was too generic. No examples of how to suggest names. The LLM suggested full titles ("El Futuro del Aprendizaje") instead of `yt-word1-word2` slugs.

### v2 design changes

- **Create-immediately-then-enrich**: When a URL is detected, the source is created IMMEDIATELY with auto-detected type, the URL, and a suggested name. The agent THEN asks the user for name override, author, and comment — and UPDATES the source. Source creation is not optional.
- **Routing fix**: `MultiAgentService.handle()` must hydrate `source_create_context` from `SourceCreateAgent.get_pending_context(user_id)` before invoking the graph. The supervisor checks this to route to `source_create_node`.
- **LLM-driven agent**: The `SourceCreateAgent` uses `ChatOpenAI` with model `gpt-5.6-luna` and `reasoning_effort="medium"` (same as session synthesis). The agent is LLM-driven, not a hardcoded state machine — the system prompt guides the conversation.
- **Detailed system prompt**: The prompt includes naming conventions, type prefixes, the always-ask rule, AND concrete examples of name suggestions from URLs and from user descriptions.

**Key constraints (carried from v1):**

- **Two triggers**: (1) a text message that is **entirely a URL**, (2) explicit request via `/create` command
- **No URL fetching / scraping**: Out of scope. The agent asks the user for all additional information.
- **Always ask rule**: The agent MUST always ask for `author` and `comment`. "Optional" means the user can leave it empty — it does NOT mean the agent can skip asking.
- **URL-only trigger**: The whole message must be a URL. URL + additional text does NOT trigger source creation (future-proofing for exploration intent).
- **Source naming**: `prefix-word1-word2` (3 words, slugified). Prefixes: `yt`, `ig`, `fb`, `lkn`, `wb`, `bk`, `cr`, `th`. Agent suggests, user can override. 4-word exceptions only if user decides.
- **Activation**: Source is active immediately after creation.
- **Model**: `gpt-5.6-luna` with `reasoning_effort="medium"` (new setting `SOURCE_CREATE_MODEL` + `SOURCE_CREATE_REASONING_EFFORT`).

**Existing patterns to follow:**

- `SESSION_SYNTHESIS_MODEL` / `SESSION_SYNTHESIS_REASONING_EFFORT` pattern in `configuration/settings.py` — replicate for source creation
- `session_builder_service.py` uses `openai_client.chat.completions.create(model=..., reasoning_effort=...)` — follow this pattern
- Repository pattern (`SourcesRepository`), service layer (`SourceService`), `MultiAgentService` LangGraph StateGraph
- `ChatModeService` for mode management, FastAPI `Depends()` for DI

---

## 3. Spec

### 3.1 Requirements

#### Schema (already applied in v1 — no changes)

1. The `sources` table has `url` (nullable text) and `type` (nullable text, CHECK: youtube|instagram|facebook|linkedin|web|book|course|thought). ✅ Done.
2. `SourcesRepository` has `create_source(url=, type=)`, `get_source_by_url()`, and `update_source(source_id, **fields)`. **NEW: add `update_source()` method** for the enrich phase.

#### Configuration (NEW)

3. Add `SOURCE_CREATE_MODEL: str = "gpt-5.6-luna"` to `configuration/settings.py`.
4. Add `SOURCE_CREATE_REASONING_EFFORT: str = "medium"` to `configuration/settings.py`.

#### Source Pydantic Model (already exists — minor update)

5. `SourceCreateByAgentRequest` exists with `source_name`, `type`, `url`, `author`, `comment` + prefix validation. ✅
6. **NEW**: Add `SourceUpdateRequest` pydantic model with optional fields (`source_name`, `author`, `comment`) for the enrich/update phase.

#### URL Detection Service (already exists — no changes)

7. `UrlDetectorService.is_url(text) -> bool` (anchored regex, whole-message-is-URL). ✅
8. `UrlDetectorService.extract_url(text) -> str`. ✅

#### Source Type Resolver (already exists — no changes)

9. `SourceTypeResolver.resolve_type(url) -> str`. ✅

#### Repository Updates (NEW: add update_source)

10. Add `update_source(source_id: str, source_name: Optional[str] = None, author: Optional[str] = None, comment: Optional[str] = None) -> Optional[dict]` to `SourcesRepository`. This is used by the enrich phase to update the source after creation.

#### Service Updates (NEW: add update method)

11. Add `update_source(source_id: str, **fields) -> Optional[dict]` to `SourceService` that delegates to the repository.

#### Source Create Agent (REWRITE — LLM-driven)

12. The `SourceCreateAgent` must use `ChatOpenAI` (or `openai.OpenAI`) with `model=settings.SOURCE_CREATE_MODEL` and `reasoning_effort=settings.SOURCE_CREATE_REASONING_EFFORT`.
13. The agent must use the detailed system prompt (see §3.3) with naming conventions, type prefixes, always-ask rule, AND concrete examples of name suggestions.
14. **URL trigger flow (create-immediately-then-enrich)**:
    a. URL detected → auto-switch to agent mode.
    b. Resolve type from URL domain.
    c. Check for duplicate URL → if exists, warn + offer /switch.
    d. **CREATE THE SOURCE IMMEDIATELY** with: `url`, `type`, `source_name=<suggested>`, `status=active`. This is mandatory — the source exists in the DB right now.
    e. Send confirmation: "✅ Source created: [name] (type, url). Let me get a few more details."
    f. Ask the user if they want to keep the suggested name or change it.
    g. **Always ask** for `author` (user can decline).
    h. **Always ask** for `comment` (user can decline).
    i. UPDATE the source with any new info (name override, author, comment) via `update_source()`.
    j. Send final confirmation with all fields.
15. **`/create` (no args) flow**: agent asks for type → asks for name (suggests one) → **always asks** for author + comment → creates source → activates → confirms.
16. **`/create <name>` flow**: validate name prefix → ask for type → **always asks** for author + comment → create source → activate → confirms.
17. **`/create <url>` flow**: treat as URL trigger (flow 14).

#### Multi-Agent Service Updates (CRITICAL FIX)

18. **`MultiAgentService.handle()` must hydrate `source_create_context`** from `SourceCreateAgent.get_pending_context(telegram_user_id)` before invoking the graph. If a pending context exists, set it in the state so the supervisor routes to `source_create_node`.
19. The supervisor routing logic: `if state.get("source_create_context") is not None → route to source_create_node`. This already exists but was dead code because the context was always None.
20. After `source_create_node` completes (conversation done), clear the pending context via `SourceCreateAgent.clear_pending(user_id)`.

#### Telegram Message Handler (minor fix)

21. The URL-only detection (line 99-111) already routes to `source_create_agent.start_url_flow()`. This is correct for the first message. ✅
22. **The fix is in MultiAgentService** (§18): subsequent non-URL messages must reach `source_create_node` because the pending context is hydrated. No change needed in the message handler itself — it routes to `_route_to_multi_agent()` for agent-mode text, and the MultiAgentService now correctly routes to `source_create_node`.

#### Telegram Command Handler (already done — no changes)

23. `/create` routes to `source_create_agent.start_create_flow()`. ✅

#### Controller Updates (NEW: wire model to agent)

24. Update `telegram_controller.py`: the `get_source_create_agent()` dependency must pass the LLM client (OpenAI with `SOURCE_CREATE_MODEL` + `SOURCE_CREATE_REASONING_EFFORT`) to the `SourceCreateAgent`.

---

### 3.2 Acceptance Criteria

1. Sending `https://www.youtube.com/watch?v=abc123` (and nothing else) **immediately creates** a source with `type=youtube`, `url=...`, `source_name=yt-<suggested>`, `status=active`. The source EXISTS in the DB before the agent asks any questions.
2. After immediate creation, the agent asks the user for name override, author, and comment. The agent UPDATES the source with the user's answers.
3. Sending `https://instagram.com/p/xyz` (and nothing else) immediately creates a source with `type=instagram`, name prefixed `ig-`, then agent asks for name/author/comment.
4. Sending `check this https://youtube.com/watch?v=abc` (URL + text) does NOT trigger source creation.
5. Sending `/create` (no args) triggers agent conversation to create a non-URL source.
6. Sending `/create my-source` triggers agent conversation to complete source info.
7. Source names follow `prefix-word1-word2` (3 words). Agent suggestions follow this format exactly.
8. The agent **always asks** for `author` and `comment` — the user can decline, but the agent must not skip asking.
9. **Routing fix**: After the initial URL message, subsequent text messages (the user's answers) reach `source_create_node`, NOT the generic chat_node. The agent continues the source creation conversation.
10. Duplicate URL detection: if a source with the same URL already exists, warn the user and offer to switch.
11. The agent uses `gpt-5.6-luna` with `reasoning_effort="medium"`.
12. The agent's name suggestions are short slugs (`yt-fin-aprendizaje`), NOT full titles ("El Futuro del Aprendizaje").

---

### 3.3 System Prompt (DETAILED — with examples)

The `SourceCreateAgent` must use this system prompt (stored in `backend/services/source_create_agent.py` or a dedicated prompt module):

```
You are a source creation assistant for a voice-note knowledge base app.
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
```

---

## 4. Design

### 4.1 Architecture (v2)

**URL-Only Detection → IMMEDIATE Source Creation → Agent Enrichment (LLM-driven, always asks) → Source Update**

```
Message received
    │
    ├─ Is entire message a URL? ──YES──→ start_url_flow()
    │                                        │
    │                                        ├─ Resolve type from domain
    │                                        ├─ Check duplicate URL
    │                                        ├─ CREATE SOURCE IMMEDIATELY (url, type, suggested name, active)
    │                                        ├─ Set pending context (source_id, step=AWAITING_NAME_CONFIRM)
    │                                        └─ Send: "✅ Source created: {name}. Keep it or change it?"
    │
    ├─ Is it /create? ──YES──→ start_create_flow()
    │                              │
    │                              └─ Agent conversation (no immediate creation — collect type, name first)
    │
    └─ Other text in agent mode ──→ MultiAgentService.handle()
                                        │
                                        ├─ Hydrate source_create_context from SourceCreateAgent.get_pending_context()
                                        │
                                        ├─ context is NOT None? ──YES──→ source_create_node
                                        │                                    │
                                        │                                    └─ LLM-driven conversation:
                                        │                                       ask name override, author, comment
                                        │                                       → update_source() when done
                                        │                                       → clear_pending()
                                        │
                                        └─ context is None? ──YES──→ chat_node (generic chat)
```

### 4.2 Key Design Decisions (v2)

1. **Create-immediately-then-enrich**: The source is created the moment a URL is detected. The agent's job is to enrich (name override, author, comment) by UPDATING the existing source. This guarantees the source always exists — even if the user abandons the conversation.

2. **LLM-driven conversation**: The `SourceCreateAgent` uses `gpt-5.6-luna` with `reasoning_effort="medium"` and the detailed system prompt. The LLM handles the natural conversation flow (suggesting names, asking for fields). The agent code parses the LLM's JSON output to call `update_source()`.

3. **Routing fix**: `MultiAgentService.handle()` hydrates `source_create_context` from `SourceCreateAgent.get_pending_context(user_id)`. This was the critical v1 bug — the context was always None.

4. **Pending context tracks source_id**: The `SourceCreateContext` now includes `source_id` (the ID of the already-created source) so the agent can update it during enrichment.

### 4.3 File Structure (v2 changes)

```
backend/
├── models/
│   └── source.py                    # SourceCreateByAgentRequest + NEW: SourceUpdateRequest
├── services/
│   ├── url_detector_service.py      # (no changes)
│   ├── source_type_resolver.py      # (no changes)
│   ├── source_create_agent.py       # REWRITE: LLM-driven, create-immediately-then-enrich
│   ├── source_service.py            # NEW: add update_source()
│   ├── multi_agent_service.py       # FIX: hydrate source_create_context
│   ├── telegram_command_handler.py  # (no changes)
│   └── telegram_message_handler.py  # (no changes — fix is in MultiAgentService)
├── repositories/
│   └── sources_repository.py        # NEW: add update_source()
└── controllers/
    └── telegram_controller.py       # NEW: wire LLM client to SourceCreateAgent

configuration/
└── settings.py                      # NEW: SOURCE_CREATE_MODEL, SOURCE_CREATE_REASONING_EFFORT

docs/sql/
└── source_url_type_migration.md     # (no changes — already applied)
```

---

## 5. Tasks (v2 — only the changes needed)

### Configuration

- [x] Add `SOURCE_CREATE_MODEL: str = "gpt-5.6-luna"` and `SOURCE_CREATE_REASONING_EFFORT: str = "medium"` to `configuration/settings.py`

### Repository

- [x] Add `update_source(source_id, source_name=None, author=None, comment=None)` method to `SourcesRepository`

### Service

- [x] Add `update_source(source_id, **fields)` method to `SourceService`

### Pydantic Model

- [x] Add `SourceUpdateRequest` model to `backend/models/source.py` (optional: source_name, author, comment)

### Source Create Agent (REWRITE)

- [x] Rewrite `backend/services/source_create_agent.py`:
  - [x] Use `openai.OpenAI` client with `model=settings.SOURCE_CREATE_MODEL`, `reasoning_effort=settings.SOURCE_CREATE_REASONING_EFFORT`
  - [x] Implement the detailed system prompt from §3.3 (with naming examples)
  - [x] `start_url_flow()`: resolve type → check duplicate → **CREATE SOURCE IMMEDIATELY** → set pending context with `source_id` → send confirmation + ask name
  - [x] `handle_response()`: LLM-driven conversation — pass user message + context to LLM, parse JSON output, call `update_source()` when done
  - [x] `start_create_flow()`: LLM-driven conversation for `/create` (no immediate creation — collect type/name first, then create)
  - [x] `SourceCreateContext` must include `source_id` (for the update phase)

### Multi-Agent Service (CRITICAL FIX)

- [x] Fix `MultiAgentService.handle()`: hydrate `source_create_context` from `SourceCreateAgent.get_pending_context(telegram_user_id)` before invoking the graph
- [x] Ensure supervisor routes to `source_create_node` when context is not None
- [x] Clear pending context after conversation completes

### Controller

- [x] Update `telegram_controller.py` `get_source_create_agent()`: pass OpenAI client with `SOURCE_CREATE_MODEL` + `SOURCE_CREATE_REASONING_EFFORT` to `SourceCreateAgent`
- [x] Fix DI scoping bug: make `SourceCreateAgent` a module-level singleton (lazy init) so `_pending` dict survives across HTTP requests

### Tests

- [x] Test: URL detected → source created IMMEDIATELY (verify DB row exists before agent asks questions)
- [x] Test: after immediate creation, agent asks for name override, author, comment
- [x] Test: agent UPDATES the source with user's answers (verify DB row updated)
- [x] Test: routing fix — subsequent text messages reach `source_create_node` (not chat_node) when pending context exists
- [x] Test: `update_source()` repository method updates correct fields
- [x] Test: name suggestions are short slugs (`yt-fin-aprendizaje`), not full titles
- [x] Test: the agent always asks for author and comment
- [x] Test: duplicate URL detection warns user
- [x] Test: `/create` (no args) flow creates source after collecting info
- [x] Re-run all existing tests (398 must still pass)
- [x] Test: singleton pattern — same `SourceCreateAgent` instance returned across multiple `get_source_create_agent()` calls
- [x] Test: multi-request flow — pending context set in request 1 is retrievable in request 2

### Documentation

- [x] Update `docs/project_spec.md` with the create-immediately-then-enrich flow

---

## 6. Tests (v2)

- [x] Test URL → immediate source creation (source exists in DB with url, type, suggested name, status=active)
- [x] Test agent enrichment updates the source (name override, author, comment)
- [x] Test routing: pending context hydrated → supervisor routes to source_create_node
- [x] Test routing: no pending context → supervisor routes to chat_node (generic chat)
- [x] Test `SourcesRepository.update_source()` updates only provided fields
- [x] Test `SourceUpdateRequest` model validation
- [x] Test name suggestion from URL produces `prefix-word1-word2` slug
- [x] Test name suggestion from user description produces `prefix-word1-word2` slug
- [x] Test agent always asks for author and comment
- [x] Test duplicate URL detection
- [x] Test `/create` (no args) flow
- [x] Test `/create <name>` flow
- [x] Test `/create <url>` flow
- [x] All 398 existing tests still pass (434 total: 398 existing + 36 new v2 tests)

---

## 7. Dependencies

- `openai` Python SDK (already installed — used by session_builder_service.py)
- `gpt-5.6-luna` model (already used for session synthesis)
- Supabase database (migration already applied)
- Existing `MultiAgentService`, `ChatModeService`, `SourceService` infrastructure

---

## 8. Notes

- **Create-immediately-then-enrich**: This is the core v2 change. The source is created the moment a URL is detected. Even if the user abandons the conversation, the source exists with the URL, type, and a suggested name. The agent enriches afterward.
- **LLM-driven agent**: The agent uses `gpt-5.6-luna` with `reasoning_effort="medium"`. The system prompt (§3.3) is detailed with examples. The LLM handles natural conversation; the agent code parses JSON output to call `update_source()`.
- **Routing fix**: The v1 bug was that `MultiAgentService.handle()` hardcoded `source_create_context: None`. The fix is to hydrate it from `SourceCreateAgent.get_pending_context(user_id)`.
- **No URL fetching**: Still out of scope. The agent asks the user for all additional info.
- **Always-ask rule**: Still mandatory. The agent must ask for author and comment even though they're optional.
- **Name suggestions**: The system prompt has concrete examples. The LLM must suggest `prefix-word1-word2` slugs, never full titles.

---

## 9. project_spec.md Alignment

- Update the source creation flow to document create-immediately-then-enrich
- Document the `SOURCE_CREATE_MODEL` and `SOURCE_CREATE_REASONING_EFFORT` settings
- Document the routing: URL → immediate creation → agent enrichment via `source_create_node`

---

## 10. Post-Mortem (v1 failures — for reference)

### Bug #1 — Routing (CRITICAL)
**Symptom**: After sending a URL, the agent responded as a generic chatbot. It said "I don't have the ability to save sources."
**Root cause**: `MultiAgentService.handle()` line 127: `"source_create_context": None` — always None, never hydrated. The supervisor check `if state.get("source_create_context") is not None` was dead code. Subsequent messages went to `chat_node` (generic LLM), not `source_create_node`.
**Fix**: Hydrate `source_create_context` from `SourceCreateAgent.get_pending_context(user_id)` in `handle()` before invoking the graph.

### Bug #2 — Design (create-after-collect vs create-immediately)
**Symptom**: Source was never created because the conversation never completed (it was in the generic chat).
**Root cause**: v1 created the source only at the END of the conversation (`_handle_comment_step`). If the conversation broke down (Bug #1), no source was created.
**Fix**: Create the source IMMEDIATELY on URL detection. Enrich afterward via `update_source()`.

### Bug #3 — Prompt (generic, no examples)
**Symptom**: The LLM suggested full titles ("El Futuro del Aprendizaje: ¿Fin o Transformación?") instead of `yt-fin-aprendizaje` slugs.
**Root cause**: The system prompt had no examples of name suggestions. The LLM defaulted to natural-language titles.
**Fix**: Detailed system prompt (§3.3) with concrete examples of name suggestions from URLs and from user descriptions. Explicit rule: "NEVER suggest a full title. `yt-fin-aprendizaje` is RIGHT, `El Futuro del Aprendizaje` is WRONG."

### Live conversation evidence (voice_note_chat_memory, 2026-08-19)
- User sent YouTube URL → `start_url_flow()` fired correctly, set pending context
- User sent description ("el video trata sobre...") → NOT a URL → routed to `MultiAgentService.handle()` → `source_create_context` was None → went to `chat_node` → generic chatbot
- Agent suggested 6 long titles (wrong format)
- User formatted the name themselves: "yt-fin-aprendizaje"
- Agent said "Sounds great!" but didn't create the source
- User asked "did you save the source?"
- Agent: "I'm sorry, I don't have the ability to save sources."

---

## Execution Log

- [2026-08-18 20:45] Agent: Backend | Status: in_progress | Started implementation of url_source_capture feature (v1)
- [2026-08-18 20:53] Agent: Backend | Status: completed | v1 implementation done, 398 tests pass
- [2026-08-19 02:09] User | Live test failed | Agent behaved as generic chatbot, source never created
- [2026-08-19 02:30] Agent: Orchestrator | Status: completed | Root cause analysis: 3 bugs identified (routing, design, prompt)
- [2026-08-19 02:45] Agent: Orchestrator | Status: in_progress | v2 plan created — create-immediately-then-enrich, routing fix, detailed prompt with examples, luna model
- [2026-08-19 03:00] Agent: Backend | Status: in_progress | Started v2 implementation
- [2026-08-19 03:05] Agent: Backend | Status: completed | Configuration: added SOURCE_CREATE_MODEL + SOURCE_CREATE_REASONING_EFFORT to settings.py
- [2026-08-19 03:07] Agent: Backend | Status: completed | Repository: added update_source() to SourcesRepository
- [2026-08-19 03:08] Agent: Backend | Status: completed | Service: added update_source() to SourceService
- [2026-08-19 03:09] Agent: Backend | Status: completed | Model: added SourceUpdateRequest to backend/models/source.py
- [2026-08-19 03:10] Agent: Backend | Status: completed | Agent model: added source_id to SourceCreateContext TypedDict
- [2026-08-19 03:15] Agent: Backend | Status: completed | REWROTE SourceCreateAgent: LLM-driven, create-immediately-then-enrich, detailed system prompt with examples, openai.OpenAI client with gpt-5.6-luna + reasoning_effort=medium
- [2026-08-19 03:17] Agent: Backend | Status: completed | CRITICAL FIX: MultiAgentService.handle() now hydrates source_create_context from SourceCreateAgent.get_pending_context()
- [2026-08-19 03:18] Agent: Backend | Status: completed | Controller: wired OpenAI client to SourceCreateAgent in telegram_controller.py
- [2026-08-19 03:20] Agent: Backend | Status: completed | Updated v1 tests to match v2 behavior (immediate creation reply format)
- [2026-08-19 03:25] Agent: Backend | Status: completed | Wrote 36 new v2 tests in test_url_source_capture_v2.py
- [2026-08-19 03:26] Agent: Backend | Status: completed | All 434 tests pass (398 existing + 36 new v2)
- [2026-08-19 03:27] Agent: Backend | Status: completed | Updated docs/project_spec.md with create-immediately-then-enrich flow
- [2026-08-19 03:28] Agent: Backend | Status: completed | v2 implementation complete. All tasks done.
- [2026-08-19 04:00] Agent: Backend | Status: in_progress | Fixing DI scoping bug: SourceCreateAgent created fresh per request, losing _pending dict
- [2026-08-19 04:05] Agent: Backend | Status: completed | Made SourceCreateAgent a module-level singleton with lazy initialization in telegram_controller.py (matches ChatModeService pattern)
- [2026-08-19 04:06] Agent: Backend | Status: completed | Added 8 singleton tests in test_source_create_agent_singleton.py — all pass
- [2026-08-19 04:07] Agent: Backend | Status: completed | Full test suite: 442 passed (434 existing + 8 new), 0 failed
