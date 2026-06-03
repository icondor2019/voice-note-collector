Backend Architecture

Goal
----
Define module structure, controller (router) aggregator pattern, service boundaries and simple implementation rules so backend contributors can implement features consistently.

Project layout (recommended)
--------------------------

src/
  app/
    main.py                # FastAPI app factory
    settings.py            # Pydantic Settings (see configuration.md)
    routers/               # APIRouter modules (controllers)
      __init__.py          # router aggregator
      webhook.py           # POST /api/telegram/webhook
      frontend.py          # minimal UI endpoints
    services/              # business logic
      __init__.py
      agents/              # sub-agents for reflection (multi-agent flow)
        question_agent.py  # generates reflection questions
        scorer_agent.py    # rates answers 1-10
        hint_agent.py      # Socratic hints in note language
      multi_agent_service.py  # supervisor + sub-graphs (chat, reflection)
      telegram_ingest.py   # ingest/update processing, idempotency (uses chat_id:message_id for Step 2)
      voice_notes.py       # metadata composition + domain rules
      storage.py           # supabase storage wrappers
    repositories/          # DB access
      __init__.py
      voice_note_repo.py   # CRUD with Supabase client
    models/                # Pydantic request/response models + domain DTOs
      agent.py             # AgentState, ReflectionContext, AgentResult, MultiAgentResult
      telegram_models.py
      domain.py
    utils/                 # small helpers (http client, backoff)
    tests/                 # unit and integration tests (see testing.md)

Supervisor + sub-graphs pattern
-------------------------------

The `MultiAgentService` uses a flat LangGraph `StateGraph` with a
deterministic `supervisor_node` (no LLM call) that routes on
`state.mode`:

- `agent` → `chat_node` (wraps `ChatAgentService.get_response()`)
- `reflect` → `reflect_node` (Python if/else dispatch over
  `state.pending_reflection`)

The `reflect_node` dispatches to:
- `_start_reflection` — picks a note via `NoteSelectorService`, calls
  `question_agent.run(note)`, persists via `ReflectionRepository`
- `_classify_and_route` — small LLM call for intent classification
  (HINT | CONTEXT | ANSWER), then routes to `_hint`, `_context`, or `_answer`
- `_answer` — scores the answer via `scorer_agent.run(...)`, persists,
  then auto-loops by calling `_start_reflection` for the next note

Sub-agents (`QuestionAgent`, `ScorerAgent`, `HintAgent`) are pure LLM
callers with structured outputs. They share a single `ChatOpenAI`
instance and never write to the database.

Controller / Aggregator pattern
-------------------------------

- Each router module defines a single APIRouter (e.g., webhook.py exports router).
- src/app/routers/__init__.py imports and aggregates routers into a list to be mounted by app factory.
- Controllers are thin: validate request, perform authentication/quick-sanity checks, call a single service method, return fast response.

Service layer
-------------

- Responsibilities
  - Encapsulate business rules and orchestration across repositories and external clients.
  - Perform idempotency checks and decide whether to persist/skip.
  - Map external models (Telegram Update) to domain models and repositories.

- Boundaries
  - Do not perform HTTP request parsing (controller does validation). Services return domain DTOs or domain exceptions.
  - Services may spawn background tasks or return tasks to be scheduled by the controller using FastAPI BackgroundTasks.

Repository layer
----------------

- Single responsibility: CRUD operations, queries, and low-level mapping to DB schema.
- For Step 2, repository implementations may be in-memory or file-backed and SHOULD be injectable for tests. Supabase/Postgres-specific implementations are future work and are out of scope for Step 2 unless an explicit decision is made to include them.

Minimal error handling policy
---------------------------

- Controllers: catch and translate known domain exceptions to HTTP responses (e.g., Conflict for duplicate).
- Services: raise domain exceptions for expected failures; log and bubble unexpected ones.

Logging and observability
-------------------------

- Use structured logging (json-friendly). Log key identifiers: telegram message_id, file_unique_id, user id.
- Each request handled by FastAPI should include a request_id (generated in middleware) for traceability.

Testing notes
-------------

- Keep business logic in services and repositories for easy unit testing. Controllers use TestClient for integration tests (see testing.md).
