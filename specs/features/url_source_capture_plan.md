# 1. Feature: url_source_capture

---

## 2. Context

The Voice Notes AI app currently creates sources via `/create <name>` (slugifies, activates) or `POST /api/sources` (manual fields). The `sources` table has columns: `source_name`, `author`, `comment`, `id`, `status`, `created_at`, `modified_at` — no `url` or `type`.

The user wants to evolve source creation into an agent-driven flow where:
- Sending a message that is **entirely a URL** (nothing else) creates a source automatically
- The agent fills a pydantic model with source information by **asking the user** for each field
- Source types are auto-detected from URL domains (youtube, instagram, etc.) with user override
- Non-URL sources (thoughts, books, courses) are triggered via `/create` (with or without args)
- The source is activated by default after creation

**Key constraints from user clarification:**

- **Two triggers**: (1) a text message that is **entirely a URL** (the whole message is a URL — no additional text, comments, or commands), (2) explicit request via `/create` command
- **No URL fetching / scraping**: Out of scope for this feature. The agent does NOT fetch metadata from the URL. The agent asks the user for all additional information instead. This avoids over-engineering for capturing just 1-2 optional fields.
- **Always ask rule**: Even though `author`, `comment`, and other fields are optional (the user can decline to provide them), it is **NOT optional for the agent to ask**. The agent MUST always ask for every field. "Optional" means the user can leave it empty — it does NOT mean the agent can skip asking.
- **Type auto-detection**: From URL domain (youtube.com → `youtube`, instagram.com → `instagram`, etc.). User can override.
- **Source naming**: Prefix + word1 + word2 (3 words), agent suggests a name, user can override. Prefixes: `yt`, `ig`, `fb`, `lkn`, `wb`, `bk`, `cr`, `th`.
- **Activation**: Default activate on creation (matching current `/create` behavior).
- **Note mode + URL**: Auto-switch to agent mode when a URL-only message is detected in note mode. Stay in agent mode (user switches back manually).
- **Separate flow**: URL capture is a separate flow from `/create <name>`. The `/create` command gains a new path: `/create` (no args) or `/create <name>` both trigger agent conversation to complete source info.
- **Pydantic model**: `source_name` (required), `type` (required), `url` (optional), `author` (optional), `comment` (optional).
- **Future-proofing the URL trigger**: The "whole message is a URL" rule is intentional. It leaves room for future features where a URL mixed with text (e.g. "tell me what this URL contains") is a different intent (exploration), not source creation. Mixing plain text with URLs must NOT trigger source creation.

**Existing patterns to follow:**

- Repository pattern (`SourcesRepository`) for DB access
- Service layer (`SourceService`) for business logic
- `TelegramCommandHandler` for slash command routing
- `MultiAgentService` with LangGraph StateGraph for agent routing
- `ChatModeService` for mode management
- Dependency injection via FastAPI `Depends()` in controllers
- Migration SQL docs in `docs/sql/`

---

## 3. Spec

### 3.1 Requirements

#### Schema

1. The `sources` table must gain a `url` column (nullable text).
2. The `sources` table must gain a `type` column (nullable text, CHECK constraint: `youtube`, `instagram`, `facebook`, `linkedin`, `web`, `book`, `course`, `thought`).
3. Existing 22 sources remain unchanged (`url=NULL`, `type=NULL`).

#### Source Pydantic Model

4. A `SourceCreateByAgentRequest` pydantic model must exist with fields:
   - `source_name: str` (required) — slugified, prefix + word1 + word2
   - `type: str` (required) — one of the 8 type values
   - `url: Optional[str] = None`
   - `author: Optional[str] = None`
   - `comment: Optional[str] = None`
5. The model must validate that `source_name` follows the prefix convention (starts with one of: `yt-`, `ig-`, `fb-`, `lkn-`, `wb-`, `bk-`, `cr-`, `th-`).

#### URL Detection Service

6. A `UrlDetectorService` must exist with a `is_url(text: str) -> bool` method that returns `True` **only if the entire message (after trimming whitespace) is a URL**. If the message contains any additional text, words, or commands beyond the URL, it must return `False`.
7. A `extract_url(text: str) -> str` method (or the trimmed text itself) returns the URL when `is_url` is `True`.
8. URL detection must handle common formats: `https://...`, `http://...`, `www....`, and bare domains like `youtube.com/...`.
9. **Critical**: A message like `"check this https://youtube.com/watch?v=abc"` must NOT trigger source creation — it contains additional text. Only a message that is purely a URL triggers the flow.

#### Source Type Resolver

10. A `SourceTypeResolver` must exist with a `resolve_type(url: str) -> str` method that maps URL domains to source types:
    - `youtube.com`, `youtu.be` → `youtube`
    - `instagram.com` → `instagram`
    - `facebook.com`, `fb.com` → `facebook`
    - `linkedin.com` → `linkedin`
    - Everything else → `web`
11. Non-URL source types (`book`, `course`, `thought`) are set by the agent during conversation, not by URL detection.

#### Source Name Suggestion

12. The agent must suggest a source name based on:
    - The source type prefix (e.g., `yt-` for youtube)
    - The URL itself (domain, path segments) — the agent can derive 1-2 meaningful words from the URL structure since no metadata is fetched
    - Format: `prefix-word1-word2` (3 words, slugified)
13. The user can accept the suggestion or provide their own name.
14. For non-URL sources (book, course, thought), the agent asks the user for a name and suggests one based on the conversation context.

#### Agent Source Creation Flow

15. When a message that is **entirely a URL** is received (any mode):
    a. Auto-switch to agent mode if not already in agent mode.
    b. Resolve source type from URL domain.
    c. Generate a suggested source name from the URL.
    d. Present to the user: "📎 Source detected: [type]\n🔗 [url]\n📝 Suggested name: [suggested-name]\n\nDo you want to use this name, or provide a different one?"
    e. If user accepts: use the suggested name. If user provides a different name: validate it.
    f. **Always ask** the user for `author` and `comment` (the user may decline, but the agent must ask).
    g. Create the source with all collected fields, activate it, confirm.

16. When `/create` (no args) is used:
    a. Agent asks: "What type of source is this? (book, course, thought, or paste a URL)"
    b. Based on response, agent asks for source name (suggest if possible) and other fields.
    c. **Always ask** for `author` and `comment`.
    d. Create the source, activate it, confirm.

17. When `/create <name>` is used (with a name argument):
    a. If the argument is a URL: treat as URL trigger (flow 15).
    b. If the argument is a name: validate it, then ask for type and optional fields (author, comment).
    c. **Always ask** for `author` and `comment`.
    d. Create the source, activate it, confirm.

#### Repository & Service Updates

18. `SourcesRepository.create_source()` must accept optional `url` and `type` parameters.
19. `SourceService.create_source_and_optionally_activate()` must accept optional `url` and `type` parameters.
20. `SourcesRepository` must support querying sources by URL (to detect duplicates).

#### Telegram Command Handler Updates

21. `_handle_create()` must detect if the argument is a URL and route to the agent flow.
22. `_handle_create()` with no argument must route to the agent flow for non-URL source creation.
23. The agent conversation state must be tracked (pending source creation context) so the agent can collect multi-turn information.

#### Message Handler Updates

24. `TelegramMessageHandler.handle()` must check if the **entire message is a URL** before the current mode-based routing.
25. If a URL-only message is detected in note mode, auto-switch to agent mode and route to the URL source creation flow.
26. If a URL-only message is detected in agent mode, route to the URL source creation flow (not the generic chat agent).
27. A message that contains a URL plus additional text must NOT trigger source creation — it follows normal mode routing.

#### Multi-Agent Service Updates

28. The `MultiAgentService` supervisor must recognize a "source_create" intent and route to a new `source_create_node`.
29. A new `SourceCreateAgent` (or node in the existing graph) must handle the multi-turn source creation conversation.
30. The agent must use a system prompt that includes the naming conventions, type prefixes, the pydantic model schema, and the **always-ask rule** (the agent must ask for every optional field even though the user can decline).

---

### 3.2 Acceptance Criteria

1. Sending `https://www.youtube.com/watch?v=abc123` (and nothing else) in a message creates a source with `type=youtube`, `url=https://www.youtube.com/watch?v=abc123`, `source_name=yt-suggested-name`, `status=active`.
2. Sending `https://instagram.com/p/xyz` (and nothing else) creates a source with `type=instagram`, name prefixed `ig-`, agent asks user for name/author/comment.
3. Sending `check this https://youtube.com/watch?v=abc` (URL + additional text) does NOT trigger source creation — follows normal mode routing.
4. Sending `/create` (no args) triggers agent conversation to create a non-URL source (book, course, thought).
5. Sending `/create my-source` triggers agent conversation to complete source info (type, author, comment).
6. Sending `/create https://youtube.com/abc` treats the URL as a URL trigger and follows the URL flow.
7. Source names follow the prefix convention: `yt-`, `ig-`, `fb-`, `lkn-`, `wb-`, `bk-`, `cr-`, `th-`.
8. Agent suggests a 3-word source name; user can override.
9. New sources are activated by default (become the active source).
10. URL-only detection works in both note mode and agent mode (auto-switches from note mode).
11. Duplicate URL detection: if a source with the same URL already exists, warn the user and offer to switch to it.
12. Existing 22 sources remain unchanged (`url=NULL`, `type=NULL`).
13. The `type` column CHECK constraint enforces valid values.
14. The agent **always asks** for `author` and `comment` — the user can decline, but the agent must not skip asking.

---

## 4. Design

### 4.1 Architecture

**URL-Only Detection → Type Resolution → Agent Conversation (always asks) → Source Creation**

The flow is:

1. **Entry points**: A text message that is entirely a URL OR `/create` command
2. **Detection**: `UrlDetectorService.is_url(text)` returns `True` only if the whole message is a URL
3. **Type resolution**: `SourceTypeResolver.resolve_type(url)` maps domain → type
4. **Name suggestion**: Agent generates `prefix-word1-word2` from the URL structure (no fetching)
5. **Conversation**: Agent presents suggestion, **always asks** for author and comment (user can decline)
6. **Creation**: `SourceService.create_source_and_optionally_activate()` with all collected fields
7. **Confirmation**: Agent confirms creation, source is active

**Integration points:**

- `TelegramMessageHandler` → detects URL-only messages before routing to note/agent mode
- `MultiAgentService` → new `source_create_node` in the StateGraph
- `TelegramCommandHandler` → `/create` command routes to agent flow
- `SourcesRepository` → updated `create_source()` with `url` and `type` params

### 4.2 File Structure

```
backend/
├── models/
│   └── source.py                    # SourceCreateByAgentRequest pydantic model
├── services/
│   ├── url_detector_service.py      # URL-only detection from text
│   ├── source_type_resolver.py      # Domain → type mapping
│   ├── source_create_agent.py       # Agent node for source creation conversation
│   ├── source_service.py            # Updated: accept url, type params
│   ├── multi_agent_service.py       # Updated: add source_create_node
│   ├── telegram_command_handler.py  # Updated: /create routes to agent
│   └── telegram_message_handler.py  # Updated: URL-only detection before mode routing
├── repositories/
│   └── sources_repository.py        # Updated: create_source with url, type
└── controllers/
    └── sources_controller.py        # Updated: SourceCreateRequest with url, type

docs/sql/
└── source_url_type_migration.md     # Migration SQL for url + type columns

specs/features/
└── url_source_capture_plan.md       # This file
```

---

## 5. Tasks

### Branch Setup

- [x] Create and checkout a new git branch `feat/url-source-capture` from the current branch before any implementation begins
- [x] All subsequent work (schema migration, services, agent, handlers, tests) must be committed to this branch
- [x] Branch is merged back only after the feature is verified and archived

### Schema Migration

- [x] Create `docs/sql/source_url_type_migration.md` with SQL to add `url` (nullable text) and `type` (nullable text with CHECK constraint) columns to the `sources` table
- [x] Apply the migration to the Supabase database

### Pydantic Model

- [x] Create `backend/models/source.py` with `SourceCreateByAgentRequest` pydantic model (source_name, type, url, author, comment) and prefix validation

### URL Detection Service

- [x] Create `backend/services/url_detector_service.py` with `is_url(text: str) -> bool` (returns True only if the entire message is a URL) and `extract_url(text: str) -> str` using regex for http/https/www/bare-domain URLs

### Source Type Resolver

- [x] Create `backend/services/source_type_resolver.py` with `resolve_type(url: str) -> str` method mapping domains to types (youtube, instagram, facebook, linkedin, web)

### Repository Updates

- [x] Update `backend/repositories/sources_repository.py`: add `url` and `type` parameters to `create_source()` method
- [x] Add `get_source_by_url(url: str)` method to `SourcesRepository` for duplicate detection

### Service Updates

- [x] Update `backend/services/source_service.py`: add `url` and `type` parameters to `create_source_and_optionally_activate()` method
- [x] Add duplicate URL check logic to `SourceService`

### Source Name Suggestion

- [x] Add `_suggest_source_name(source_type: str, url: Optional[str] = None) -> str` helper to the source create agent (prefix + 2 meaningful words derived from the URL structure, no fetching)

### Source Create Agent

- [x] Create `backend/services/source_create_agent.py` with a LangGraph node that handles multi-turn source creation conversation
- [x] Implement system prompt with naming conventions, type prefixes, pydantic model schema, and the **always-ask rule**
- [x] Implement URL trigger flow: detect type → suggest name from URL → **always ask** for author/comment → create source
- [x] Implement `/create` (no args) flow: ask type → ask name → **always ask** for fields → create source
- [x] Implement `/create <name>` flow: validate name → ask type → **always ask** for fields → create source
- [x] Implement `/create <url>` flow: treat as URL trigger

### Multi-Agent Service Updates

- [x] Update `backend/services/multi_agent_service.py`: add `source_create_node` to the StateGraph
- [x] Update supervisor routing to detect source creation intent (URL-only message or `/create` command)
- [x] Add `SourceCreateContext` to `AgentState` for tracking pending source creation state

### Telegram Command Handler Updates

- [x] Update `backend/services/telegram_command_handler.py`: modify `_handle_create()` to detect URLs and route to agent flow
- [x] Update `_handle_create()` with no argument to route to agent flow
- [x] Update help message to document new `/create` behavior

### Telegram Message Handler Updates

- [x] Update `backend/services/telegram_message_handler.py`: add URL-only detection before mode-based routing in `handle()`
- [x] Auto-switch to agent mode when URL-only message detected in note mode
- [x] Route URL-only messages to source creation flow instead of generic chat agent
- [x] Ensure messages with URL + additional text do NOT trigger source creation

### Controller Updates

- [x] Update `backend/controllers/sources_controller.py`: add `url` and `type` fields to `SourceCreateRequest`
- [x] Update the POST endpoint to pass `url` and `type` to the service

### Documentation

- [x] Update `docs/project_spec.md` to document the new source creation flow and schema changes

---

## 6. Tests

- [x] Test `UrlDetectorService.is_url()` returns True for URL-only messages (https, http, www, bare domain)
- [x] Test `UrlDetectorService.is_url()` returns False for URL + additional text (e.g. "check this https://youtube.com/abc")
- [x] Test `UrlDetectorService.is_url()` returns False for plain text, commands, empty strings
- [x] Test `SourceTypeResolver.resolve_type()` with all supported domains (youtube, youtu.be, instagram, facebook, fb.com, linkedin, generic web)
- [x] Test `SourceCreateByAgentRequest` validation: valid prefix passes, invalid prefix raises error
- [x] Test `SourcesRepository.create_source()` with `url` and `type` parameters
- [x] Test `SourcesRepository.get_source_by_url()` returns correct source
- [x] Test source name suggestion generates 3-word slug with correct prefix from URL
- [x] Test URL-only detection in note mode triggers auto-switch to agent mode
- [x] Test URL + text message does NOT trigger source creation (follows normal routing)
- [x] Test `/create` (no args) triggers agent conversation
- [x] Test `/create <url>` triggers URL source creation flow
- [x] Test `/create <name>` triggers agent conversation for name-based creation
- [x] Test the agent **always asks** for author and comment (even though they are optional)
- [x] Test duplicate URL detection warns user
- [x] Test existing sources remain unchanged after migration (url=NULL, type=NULL)

---

## 7. Dependencies

- Supabase database access for migration
- `re` module for URL regex detection
- Existing `MultiAgentService` and `ChatModeService` infrastructure

---

## 8. Notes

- **No URL fetching**: This feature deliberately does NOT fetch/scrape URL metadata. The agent asks the user for all additional information. This keeps the scope small and avoids over-engineering for 1-2 optional fields. Fetching can be added in a future feature.
- **Always-ask rule**: The agent must always ask for every optional field (author, comment). "Optional" means the user can leave it empty — it does NOT mean the agent can skip asking. This is a hard requirement.
- **URL-only trigger**: The URL trigger fires ONLY when the entire message is a URL. This is intentional to avoid complex text parsing and to leave room for future features where a URL mixed with text (e.g. "tell me what this URL contains") is a different intent (exploration), not source creation.
- **URL regex**: Use a regex that validates the entire string is a URL (anchored `^...$`). Match `https?://...`, `www....`, and bare domains like `youtube.com/...`. The key is the whole message must be a URL.
- **Agent state management**: The source creation flow is multi-turn. The agent needs to track context (partial source info) across messages. This is similar to how `ReflectionContext` works in the existing `MultiAgentService`.
- **Slug validation**: The existing `slugify()` and `validate_slug_input()` utilities in `backend/utils/slug.py` should be reused for name validation.
- **Migration safety**: Adding nullable columns is non-breaking. Existing queries that don't reference `url` or `type` will continue to work unchanged.

---

## 9. project_spec.md Alignment

The following changes to `docs/project_spec.md` are required:

- **Sources section**: Add `url` (nullable text) and `type` (nullable text, CHECK: youtube|instagram|facebook|linkedin|web|book|course|thought) to the sources table documentation
- **Source creation section**: Document the new agent-driven source creation flow (URL-only trigger + `/create` variants). Document the always-ask rule.
- **Naming conventions section**: Document the source name prefix convention (yt-, ig-, fb-, lkn-, wb-, bk-, cr-, th-) and the 3-word naming rule
- **Agent modes section**: Document the new source creation agent flow and its integration with the MultiAgentService

---

## Execution Log

- [2026-08-18 20:45] Agent: Backend | Status: in_progress | Started implementation of url_source_capture feature
- [2026-08-18 20:46] Agent: Backend | Status: completed | Created branch feat/url-source-capture
- [2026-08-18 20:46] Agent: Backend | Status: completed | Created docs/sql/source_url_type_migration.md and applied migration to Supabase (migration name: source_url_type)
- [2026-08-18 20:47] Agent: Backend | Status: completed | Created backend/models/source.py with SourceCreateByAgentRequest pydantic model
- [2026-08-18 20:47] Agent: Backend | Status: completed | Created backend/services/url_detector_service.py with anchored regex URL detection
- [2026-08-18 20:47] Agent: Backend | Status: completed | Created backend/services/source_type_resolver.py with domain-to-type mapping
- [2026-08-18 20:48] Agent: Backend | Status: completed | Updated SourcesRepository: added url/type params to create_source(), added get_source_by_url()
- [2026-08-18 20:48] Agent: Backend | Status: completed | Updated SourceService: added url/type params, duplicate URL check
- [2026-08-18 20:49] Agent: Backend | Status: completed | Created backend/services/source_create_agent.py with multi-turn conversation, always-ask rule, name suggestion
- [2026-08-18 20:50] Agent: Backend | Status: completed | Updated MultiAgentService: added source_create_node, SourceCreateContext to AgentState, supervisor routing
- [2026-08-18 20:50] Agent: Backend | Status: completed | Updated TelegramCommandHandler: /create routes to agent flow, updated help message
- [2026-08-18 20:51] Agent: Backend | Status: completed | Updated TelegramMessageHandler: URL-only detection before mode routing, auto-switch to agent mode
- [2026-08-18 20:51] Agent: Backend | Status: completed | Updated sources_controller: added url/type to SourceCreateRequest
- [2026-08-18 20:51] Agent: Backend | Status: completed | Updated telegram_controller: wired SourceCreateAgent dependency
- [2026-08-18 20:52] Agent: Backend | Status: completed | Created tests/test_url_source_capture.py (47 tests) and tests/test_url_source_capture_integration.py (8 tests)
- [2026-08-18 20:53] Agent: Backend | Status: completed | Fixed test_sources_endpoints.py StubSourceService to accept url/type params
- [2026-08-18 20:53] Agent: Backend | Status: completed | Updated docs/project_spec.md with new source creation flow documentation
- [2026-08-18 20:53] Agent: Backend | Status: completed | All 398 tests pass (55 new + 343 existing)
