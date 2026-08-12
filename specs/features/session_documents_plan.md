# 1. Feature: session_documents

---

## 2. Context

The Voice Notes AI app currently enriches voice notes individually (title + labels via `NoteEnrichmentService`) and reflects on them individually (pick one note → Socratic question → rate answer via `ReflectionService`). This works mechanically but doesn't match how learning happens — a single note is a fragment of a thought at a moment in time, not enough context to test understanding.

The user wants to evolve from "review individual notes" to "review session documents" — synthesized work products that group multiple notes from one reading/learning period. The document preserves the user's own reflections (not just a summary of the source) and evolves over time with Socratic questions, knowledge gaps, connections, and mind-changes.

**Key constraints from user clarification:**

- **Session trigger**: Explicit `/build_doc` slash command only. No time-based or note-count-based auto-close.
- **Per-note enrichment**: Keep as-is. Documents inherit labels via compute-on-read (union of constituent notes' labels). No label storage on `session_documents`.
- **One service**: `SessionBuilderService.build(source_id, note_ids)` — enriches un-enriched notes, then synthesizes the document. Always in that order. No separate backfill service. No gap-minutes grouping. The caller picks the IDs.
- **Two call sites**: `/build_doc` (queries pending notes from active source) and `POST /api/session-documents` (caller passes explicit `note_ids`). Both call the same `build()` method.
- **Table reuse**: `document_uuid` FK on `voice_note_details` (n:1 notes → document). No new join table.
- **Enrichment cap**: `MAX_LLM_LABEL_CREATIONS_PER_RUN` honored (no bypass — less hallucination risk with fewer notes).
- **Progress reply**: Single interim "⏳ enriching + synthesizing…" message before the LLM calls.
- **Note validation**: `build()` excludes notes where `document_uuid IS NOT NULL` (already grouped) and notes that don't belong to the given `source_id`.
- **Reflection redirect**: Phase 2, documented separately in `specs/features/session_documents_reflection_redirect.md`. Only schema hooks (`reflections.document_id` + `target_type`) added now.
- **`/reflect stats`**: Deferred to Phase 2. Current per-note behavior unchanged.

**Existing patterns to follow:**

- Repository pattern (`VoiceNotesRepository`, `ReflectionRepository`) for DB access
- Service layer (`NoteEnrichmentService`, `ReflectionService`) for business logic
- `TelegramCommandHandler` for slash command routing
- Dependency injection via FastAPI `Depends()` in controllers
- Migration SQL docs in `docs/sql/` (precedent: `label_restructure_migration.md`)
- Spec format in `specs/closed_features/` (precedent: `label_restructure_plan.md`)

---

## 3. Spec

### 3.1 Requirements

#### Schema

1. A `session_documents` table must exist with columns: `id`, `source_id`, `title`, `summary`, `key_ideas`, `open_questions`, `open_gaps`, `status`, `parent_document_id`, `telegram_user_id`, `created_at`, `updated_at`. See §4.3 for full schema.
2. `status` must be constrained to `('ready', 'reviewed')`.
3. `parent_document_id` is a nullable self-referencing FK for future source-level synthesis.
4. `voice_note_details` must gain a `document_uuid` column (nullable FK to `session_documents(id)`, `ON DELETE SET NULL`).
5. A `session_document_components` table must exist with columns: `id`, `session_document_id`, `component_type`, `content`, `source`, `metadata`, `created_at`. See §4.3 for full schema.
6. `component_type` must be constrained to `('socratic_question', 'knowledge_gap', 'connection', 'reflection', 'mind_change')`.
7. `source` (on components) must be constrained to `('llm', 'user')`.
8. `reflections` must gain `target_type` (nullable, CHECK in `('note', 'document')`) and `document_id` (nullable FK to `session_documents(id)`, `ON DELETE SET NULL`). No behavior change — schema hook only.

#### SessionBuilderService

9. A new `SessionBuilderService` must exist with a `build(source_id, note_ids)` method and a `preview(source_id, note_ids)` method.
10. `build()` must:
    a. Validate `note_ids`: exclude notes where `document_uuid IS NOT NULL` (already grouped) and notes that don't belong to `source_id`. Log how many were filtered.
    b. If zero valid notes remain, raise an error (no empty documents).
    c. **Step A — Enrich**: For notes with `voice_note_details.status = 'created'`, call `NoteEnrichmentService.enrich_specific_notes(note_ids)`. Skip already-enriched notes. Honor `MAX_LLM_LABEL_CREATIONS_PER_RUN`.
    d. **Step B — Synthesize**: Create a `session_documents` row (status='ready'). Run a single LLM call on the joined `raw_text`s → `{title, summary, key_ideas, open_questions, open_gaps}`. Update the document row.
    e. Set `voice_note_details.document_uuid` to the new document id for every valid note.
    f. Seed `session_document_components` with one `socratic_question` row per item in `open_questions` (`source='llm'`).
    g. Return the new `session_documents` row.
11. `preview()` must return a read-only summary: pending count, time range, count of un-enriched notes, and a preview list of note titles (enriched) or first ~100 chars of `raw_text` (not enriched). No DB writes.

#### NoteEnrichmentService

12. A new `enrich_specific_notes(note_ids)` method must exist on `NoteEnrichmentService`. It enriches only the given note IDs (not source-wide). Same `MAX_LLM_LABEL_CREATIONS_PER_RUN` cap. Same prompt and JSON parsing as `run_process()`.

#### /build_doc command

13. `/build_doc` must:
    a. Resolve the active source. If none, reply with an error.
    b. Query pending notes: `voice_notes JOIN voice_note_details WHERE source_id = active AND document_uuid IS NULL ORDER BY created_at ASC`.
    c. If zero pending notes, reply "⚠️ No pending notes in this source."
    d. Send an interim message: "⏳ Enriching N notes + synthesizing document…"
    e. Call `SessionBuilderService.build(source_id, note_ids)`.
    f. Reply with: title + summary preview + "📚 N notes · M open questions".
14. `/build_doc stats` must:
    a. Resolve the active source. If none, reply with an error.
    b. Query pending notes (same as above).
    c. Call `SessionBuilderService.preview(source_id, note_ids)`.
    d. Reply with the preview. No DB writes.
15. `/build_doc` must be added to the `/help` message.
16. `/build_doc` must follow the slash-cancels-reflect rule: if in reflect mode, cancel the pending reflection and exit to agent mode before processing.

#### API endpoints

17. `POST /api/session-documents` must accept `{source_id, note_ids, title?}` and call `SessionBuilderService.build()`. Returns the new document + components.
18. `GET /api/session-documents/{id}` must return the document + its components + attached notes (with their labels).
19. Both endpoints must require API key authentication (same `verify_api_key` dependency as other controllers).

#### Labels

20. Document labels are computed on read via JOIN: `voice_note_labels` → `voice_note_details` → `document_uuid`. No label storage on `session_documents`.
21. `SessionDocumentsRepository.get_document_labels(document_id)` must return the distinct active labels for all notes attached to the document.

### 3.2 Acceptance Criteria

- [ ] `session_documents` table exists with all columns and constraints
- [ ] `voice_note_details.document_uuid` column exists as nullable FK to `session_documents(id)`
- [ ] `session_document_components` table exists with all columns and constraints
- [ ] `reflections.target_type` and `reflections.document_id` columns exist
- [ ] `SessionBuilderService.build(source_id, note_ids)` enriches un-enriched notes, then synthesizes a document
- [ ] `build()` excludes notes where `document_uuid IS NOT NULL`
- [ ] `build()` excludes notes that don't belong to `source_id`
- [ ] `build()` raises an error if zero valid notes remain
- [ ] `build()` sets `document_uuid` on all constituent notes
- [ ] `build()` seeds `session_document_components` with `socratic_question` rows from `open_questions`
- [ ] `SessionBuilderService.preview()` returns pending count, time range, un-enriched count, note previews
- [ ] `NoteEnrichmentService.enrich_specific_notes(note_ids)` enriches only the given notes
- [ ] `enrich_specific_notes` honors `MAX_LLM_LABEL_CREATIONS_PER_RUN`
- [ ] `/build_doc` creates a document from all pending notes in the active source
- [ ] `/build_doc` sends an interim "⏳" message before starting
- [ ] `/build_doc` replies with title + summary + counts
- [ ] `/build_doc` with zero pending notes replies with an error
- [ ] `/build_doc` with no active source replies with an error
- [ ] `/build_doc stats` shows a preview without synthesizing
- [ ] `/build_doc` is listed in `/help`
- [ ] `/build_doc` cancels any pending reflection if in reflect mode
- [ ] `POST /api/session-documents` creates a document from explicit `note_ids`
- [ ] `GET /api/session-documents/{id}` returns the document with components and notes
- [ ] `SessionDocumentsRepository.get_document_labels()` returns the union of constituent notes' labels
- [ ] No regression in existing voice note ingestion, enrichment, or reflection behavior
- [ ] Full test suite passes under `./venv/bin/pytest`

---

## 4. Design

### 4.1 Architecture

```
/build_doc (Telegram)          POST /api/session-documents (HTTP)
       │                                    │
       ▼                                    ▼
  query pending notes              note_ids from request body
  (document_uuid IS NULL,
   source_id = active)
       │                                    │
       └──────────────┬─────────────────────┘
                      ▼
          SessionBuilderService.build(source_id, note_ids)
                      │
            ┌─────────┴─────────┐
            ▼                   ▼
       Step A:             Step B:
       Enrich              Synthesize
       (if status='created')  (LLM call)
            │                   │
            ▼                   ▼
       NoteEnrichmentService   session_documents row
       .enrich_specific_notes  + session_document_components
       (cap honored)           (socratic_question rows seeded)
            │                   │
            └─────────┬─────────┘
                      ▼
              voice_note_details.document_uuid = new doc id
```

**State machine for a session document:**

```
            /build_doc (or POST /api/session-documents)
                   │
                   ▼
              ┌─────────┐
              │  ready   │
              └────┬─────┘
                   │
                   │ Phase 2: reflection redirect marks it reviewed
                   │
                   ▼
              ┌──────────┐
              │ reviewed  │
              └──────────┘
```

In v1, documents are created with `status='ready'` and never transition to `'reviewed'` (that's Phase 2).

### 4.2 File Structure

```
docs/sql/
  session_documents_migration.md                    ← new: SQL migration steps

backend/
  models/
    session_document.py                              ← new: SessionDocument, SessionDocumentComponent, SessionDocumentPreview, SessionDocumentStats
  repositories/
    session_documents_repository.py                  ← new: CRUD + get_document_labels + stats
  services/
    session_builder_service.py                      ← new: build() + preview()
    session_synthesis_prompt.py                      ← new: LLM prompt template
    note_enrichment_service.py                       ← modified: add enrich_specific_notes()
    telegram_command_handler.py                      ← modified: add /build_doc + /build_doc stats
  controllers/
    session_documents_controller.py                  ← new: POST + GET endpoints
    telegram_controller.py                           ← modified: wire SessionBuilderService DI

tests/
  repositories/
    test_session_documents_repository.py             ← new
  services/
    test_session_builder_service.py                  ← new
    test_note_enrichment_service.py                   ← extended: enrich_specific_notes tests
  controllers/
    test_session_documents_controller.py             ← new
  test_telegram_command_handler.py                   ← extended: /build_doc cases

specs/features/
  session_documents_proposal.md                      ← new: short rationale
  session_documents_plan.md                          ← this file
  session_documents_reflection_redirect.md          ← new: Phase 2 stub
```

### 4.3 Database Schema

```sql
-- New: session documents table
CREATE TABLE IF NOT EXISTS session_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    title TEXT,
    summary TEXT,
    key_ideas TEXT,
    open_questions TEXT,
    open_gaps TEXT,
    status TEXT NOT NULL DEFAULT 'ready'
        CHECK (status IN ('ready', 'reviewed')),
    parent_document_id UUID REFERENCES session_documents(id) ON DELETE SET NULL,
    telegram_user_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS session_documents_source_created_idx
    ON session_documents (source_id, created_at DESC);

-- New: session document components (evolving artifacts)
CREATE TABLE IF NOT EXISTS session_document_components (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_document_id UUID NOT NULL REFERENCES session_documents(id) ON DELETE CASCADE,
    component_type TEXT NOT NULL
        CHECK (component_type IN ('socratic_question', 'knowledge_gap',
                                  'connection', 'reflection', 'mind_change')),
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'llm'
        CHECK (source IN ('llm', 'user')),
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS session_doc_components_doc_idx
    ON session_document_components (session_document_id, created_at DESC);

-- Reuse: add document_uuid FK to voice_note_details
ALTER TABLE voice_note_details
    ADD COLUMN IF NOT EXISTS document_uuid UUID REFERENCES session_documents(id) ON DELETE SET NULL;

-- Phase 2 hook: extend reflections
ALTER TABLE reflections
    ADD COLUMN IF NOT EXISTS target_type TEXT
        CHECK (target_type IS NULL OR target_type IN ('note', 'document')),
    ADD COLUMN IF NOT EXISTS document_id UUID REFERENCES session_documents(id) ON DELETE SET NULL;
```

**Column notes:**

- `session_documents.source_id`: Required. Every document belongs to one source.
- `session_documents.title`: LLM-generated, 1 sentence.
- `session_documents.summary`: LLM-generated, 2-3 paragraphs. Preserves the user's own reflections.
- `session_documents.key_ideas`: LLM-generated, bullet list (3-7 items).
- `session_documents.open_questions`: LLM-generated, bullet list of questions to explore.
- `session_documents.open_gaps`: LLM-generated, bullet list of what's unclear or underexplored.
- `session_documents.status`: `'ready'` on creation. `'reviewed'` is Phase 2 (reflection redirect).
- `session_documents.parent_document_id`: Nullable self-FK for future source-level synthesis.
- `voice_note_details.document_uuid`: Nullable FK. `IS NULL` = note is pending (not in any document). `ON DELETE SET NULL` so deleting a document doesn't delete the notes.
- `session_document_components.component_type`: What kind of evolving artifact this is.
- `session_document_components.source`: `'llm'` for synthesized content, `'user'` for user-added content.
- `reflections.target_type` / `document_id`: Phase 2 hooks. Nullable. No behavior change in v1.

### 4.4 SessionBuilderService Design

```python
class SessionBuilderService:
    def __init__(
        self,
        session_documents_repository: SessionDocumentsRepository,
        voice_notes_repository: VoiceNotesRepository,
        voice_note_details_repository: VoiceNoteDetailsRepository,
        note_enrichment_service: NoteEnrichmentService,
        openai_client: Any,
        settings: Any,
    ) -> None: ...

    async def build(self, source_id: str, note_ids: list[str]) -> dict:
        """
        1. Validate note_ids: fetch from voice_notes WHERE id IN note_ids
           AND source_id = source_id AND document_uuid IS NULL
        2. If zero valid notes, raise NoValidNotesError
        3. Step A: enrich un-enriched notes (status='created')
           → NoteEnrichmentService.enrich_specific_notes(un_enriched_ids)
        4. Step B: synthesize
           → Create session_documents row (status='ready')
           → Run LLM call on joined raw_texts → {title, summary, key_ideas, open_questions, open_gaps}
           → Update document row with LLM output
           → Set voice_note_details.document_uuid for every valid note
           → Seed session_document_components with socratic_question rows
        5. Return the document row
        """

    async def preview(self, source_id: str, note_ids: list[str]) -> dict:
        """
        Read-only. No DB writes.
        1. Fetch valid pending notes (same validation as build)
        2. Return: {count, time_range, un_enriched_count, notes: [{title or raw_text preview}]}
        """
```

### 4.5 NoteEnrichmentService Changes

New method `enrich_specific_notes(note_ids)`:

```python
async def enrich_specific_notes(self, note_ids: list[str]) -> None:
    """
    Enrich only the given note IDs. Same prompt, same JSON parsing,
    same MAX_LLM_LABEL_CREATIONS_PER_RUN cap as run_process().
    Used by SessionBuilderService.build() before synthesis.
    """
    # 1. Fetch pending notes with source via details repo
    #    (same get_pending_notes_with_source, but filtered by note_ids)
    # 2. Group by source_id
    # 3. For each source group: _enrich_batch (same as run_process)
    # 4. Write titles + labels (same as run_process)
```

### 4.6 TelegramCommandHandler Changes

Add `/build_doc` to the command routing in `handle_text()`:

```python
elif command == "/build_doc":
    if args == "stats":
        reply = await self._handle_build_doc_stats(from_user_id)
    else:
        reply = await self._handle_build_doc(from_user_id, chat_id)
```

New handler methods:

```python
async def _handle_build_doc(self, telegram_user_id: int, chat_id: int) -> str:
    # 1. Resolve active source
    # 2. Query pending notes (document_uuid IS NULL)
    # 3. If zero, return "⚠️ No pending notes in this source."
    # 4. Send interim "⏳ Enriching N notes + synthesizing document…"
    # 5. Call SessionBuilderService.build(source_id, note_ids)
    # 6. Return formatted result

async def _handle_build_doc_stats(self, telegram_user_id: int) -> str:
    # 1. Resolve active source
    # 2. Query pending notes
    # 3. Call SessionBuilderService.preview(source_id, note_ids)
    # 4. Return formatted preview
```

Update `HELP_MESSAGE` to include `/build_doc`.

### 4.7 SessionDocumentsController

```python
router = APIRouter(
    prefix="/api/session-documents",
    tags=["Session Documents"],
    dependencies=[Depends(verify_api_key)],
)

@router.post("", status_code=201)
async def create_session_document(
    payload: SessionDocumentCreateRequest,
    service: SessionBuilderService = Depends(get_session_builder_service),
) -> dict:
    """Create a session document from explicit note_ids."""
    # Validate, call service.build(), return result

@router.get("/{document_id}")
async def get_session_document(
    document_id: str,
    repository: SessionDocumentsRepository = Depends(get_session_documents_repository),
) -> dict:
    """Fetch a session document with its components and attached notes."""
    # Return document + components + notes (with labels)
```

### 4.8 LLM Prompt Design

**Session synthesis prompt:**

```
You are a session synthesis assistant. You will receive a list of voice note transcriptions
from one reading/learning session. Your task is to synthesize them into a coherent document
that preserves the user's own reflections and ideas.

Produce:
- title: 1 sentence summarizing the session
- summary: 2-3 paragraphs preserving the user's own thoughts (not just a summary of the source)
- key_ideas: 3-7 bullet points of the main ideas encountered
- open_questions: bullet points of questions the user might want to explore
- open_gaps: bullet points of what was unclear or underexplored

Notes:
{{TRANSCRIPTIONS}}

Respond in JSON format:
{
  "title": "<1 sentence>",
  "summary": "<2-3 paragraphs>",
  "key_ideas": "<bullet list>",
  "open_questions": "<bullet list>",
  "open_gaps": "<bullet list>"
}
```

---

## 5. Tasks

#### Schema & Migration

- [x] Create `docs/sql/session_documents_migration.md` with CREATE TABLE + ALTER TABLE statements
- [x] Apply migration via `supabase_apply_migration`
- [x] Verify via `supabase_list_tables` and `supabase_execute_sql`
- [x] Run `supabase_get_advisors` to check for security issues

#### Pydantic Models

- [x] Create `backend/models/session_document.py` with `SessionDocument`, `SessionDocumentComponent`, `SessionDocumentPreview`, `SessionDocumentCreateRequest`
- [x] Export from `backend/models/__init__.py`

#### Repository Layer

- [x] Create `backend/repositories/session_documents_repository.py`
- [x] Implement `create_document`, `get_document`, `list_documents`, `update_document`
- [x] Implement `create_component`, `list_components`
- [x] Implement `get_document_labels` (compute-on-read via JOIN)
- [x] Implement `get_pending_note_ids(source_id)` (notes where `document_uuid IS NULL`)
- [x] Implement `attach_notes_to_document(document_id, note_ids)` (set `document_uuid`)
- [x] Export from `backend/repositories/__init__.py`

#### NoteEnrichmentService

- [x] Add `enrich_specific_notes(note_ids)` method to `NoteEnrichmentService`
- [x] Reuse `_enrich_batch` and `_resolve_new_label` (no duplication)
- [x] Honor `MAX_LLM_LABEL_CREATIONS_PER_RUN`

#### SessionSynthesisPrompt

- [x] Create `backend/services/session_synthesis_prompt.py`
- [x] Implement `render_prompt(notes)` → returns the formatted LLM prompt string

#### SessionBuilderService

- [x] Create `backend/services/session_builder_service.py`
- [x] Implement `build(source_id, note_ids)` — validate, enrich, synthesize, attach, seed components
- [x] Implement `preview(source_id, note_ids)` — read-only summary
- [x] Define `NoValidNotesError` exception

#### TelegramCommandHandler

- [x] Add `SessionBuilderService` as a dependency to `TelegramCommandHandler.__init__`
- [x] Add `/build_doc` case to `handle_text()` routing (with `stats` subcommand)
- [x] Implement `_handle_build_doc(telegram_user_id, chat_id)` — interim message + build + reply
- [x] Implement `_handle_build_doc_stats(telegram_user_id)` — preview + reply
- [x] Update `HELP_MESSAGE` to include `/build_doc`
- [x] Ensure slash-cancels-reflect rule applies to `/build_doc`

#### Controller & DI

- [x] Create `backend/controllers/session_documents_controller.py`
- [x] Implement `POST /api/session-documents` endpoint
- [x] Implement `GET /api/session-documents/{id}` endpoint
- [x] Add `get_session_builder_service()` factory in `telegram_controller.py`
- [x] Add `get_session_documents_repository()` factory
- [x] Wire `SessionBuilderService` into `TelegramCommandHandler` DI chain
- [x] Register the new router in `main.py`

#### Documentation

- [x] Add `session_documents` and `session_document_components` to the table list in `docs/project_spec.md` section 4
- [x] Add `SessionBuilderService` to the services table in `docs/project_spec.md` section 9
- [x] Add `/build_doc` to the slash commands table in `docs/project_spec.md` section 10

---

## 6. Tests

### Repository Tests (`tests/repositories/test_session_documents_repository.py`)

- [x] `test_create_document_inserts_row` — assert insert with correct `source_id`, `status='ready'`
- [x] `test_get_document_returns_row_with_components` — assert embedded select returns document + components
- [x] `test_list_documents_filters_by_source` — assert only documents for the given source are returned
- [x] `test_get_document_labels_returns_union` — assert labels from all attached notes are returned, deduplicated
- [x] `test_get_pending_note_ids_excludes_grouped` — assert notes with `document_uuid IS NOT NULL` are excluded
- [x] `test_attach_notes_to_document_sets_uuid` — assert `document_uuid` is set on all given notes
- [x] `test_create_component_inserts_row` — assert component with correct `component_type` and `source` is inserted
- [x] Each repository method raises `RepositoryError` on a client error

### Service Tests (`tests/services/test_session_builder_service.py`)

- [x] `test_build_enriches_un_enriched_notes` — mock enrichment service; assert `enrich_specific_notes` called with un-enriched IDs
- [x] `test_build_skips_already_enriched_notes` — mock enrichment service; assert only `status='created'` notes are enriched
- [x] `test_build_synthesizes_document` — mock LLM; assert document row created with LLM output
- [x] `test_build_seeds_socratic_question_components` — assert one component per `open_questions` item
- [x] `test_build_attaches_notes_to_document` — assert `document_uuid` set on all constituent notes
- [x] `test_build_excludes_already_grouped_notes` — assert notes with `document_uuid IS NOT NULL` are filtered out
- [x] `test_build_excludes_source_mismatch` — assert notes from a different source are filtered out
- [x] `test_build_raises_on_zero_valid_notes` — assert `NoValidNotesError` raised
- [x] `test_preview_returns_count_and_range` — assert preview returns correct count, time range, un-enriched count
- [x] `test_preview_does_not_write` — assert no DB writes occur

### Enrichment Tests (`tests/services/test_note_enrichment_service.py`)

- [x] `test_enrich_specific_notes_enriches_only_given_ids` — assert only the given note IDs are enriched
- [x] `test_enrich_specific_notes_honors_label_cap` — assert `MAX_LLM_LABEL_CREATIONS_PER_RUN` is respected

### Controller Tests (`tests/test_session_documents_endpoints.py`)

- [x] `test_post_create_session_document_returns_201` — assert document created and returned
- [x] `test_post_create_with_invalid_note_ids_returns_400` — assert validation error
- [x] `test_get_session_document_returns_document_with_components` — assert embedded return
- [x] `test_get_session_document_returns_404_for_missing` — assert 404 for unknown ID

### Command Handler Tests (`tests/test_telegram_command_handler.py`)

- [x] `test_build_doc_creates_document` — send `/build_doc`; assert build called, reply contains title + summary
- [x] `test_build_doc_stats_returns_preview` — send `/build_doc stats`; assert preview returned, no build call
- [x] `test_build_doc_no_pending_notes` — mock zero pending; assert error reply
- [x] `test_build_doc_no_active_source` — mock no active source; assert error reply
- [x] `test_build_doc_cancels_reflect_mode` — mock reflect mode; assert reflection cancelled before processing
- [x] `test_build_doc_in_help` — assert `/help` output includes `/build_doc`

---

## 8. Dependencies

- `openai` — already used by `NoteEnrichmentService`; same model (`gpt-4o-mini`) for synthesis
- `supabase-py` async client — already in project for all repository operations
- `session_documents` and `session_document_components` tables must be created in Supabase before deployment
- `voice_note_details.document_uuid` column must be added before deployment
- `reflections.target_type` and `reflections.document_id` columns must be added before deployment
- `loguru` for logging — already used throughout the project
- `pydantic` for model validation — already in project
- No new pip packages required

---

## 9. Notes

- **One service, no overengineering**: `SessionBuilderService.build()` is the single entry point. No separate backfill service. No gap-minutes grouping. The caller (command or API) decides which `note_ids` to pass.
- **Labels computed on read**: No `label_ids` column on `session_documents`. The union of constituent notes' labels is computed via JOIN when needed. Cheap (partial index on `voice_note_labels` already exists).
- **Enrichment cap honored**: `MAX_LLM_LABEL_CREATIONS_PER_RUN` is respected even in the `/build_doc` path. Less hallucination risk with fewer notes. If the cap is hit, some notes may not get new labels, but titles are always generated.
- **`document_uuid IS NULL` = pending**: The predicate for "note not yet in any document" is simply `document_uuid IS NULL` on `voice_note_details`. No separate status enum value needed.
- **Phase 2 hooks are schema-only**: `reflections.target_type` and `reflections.document_id` are added now but unused. Reflection redirect is documented in `specs/features/session_documents_reflection_redirect.md`.
- **`parent_document_id` is nullable**: For future source-level synthesis (sessions → source document). Not populated in v1.
- **Interim message**: `/build_doc` sends "⏳ Enriching N notes + synthesizing document…" before starting the LLM calls. Standard Telegram pattern so the user knows the system is alive.
- **Slash-cancels-reflect**: `/build_doc` follows the same rule as other slash commands — if in reflect mode, cancel the pending reflection and exit to agent mode before processing.

---

## 10. project_spec.md Alignment

Updates required after implementation:

- **Core Concepts**: Add "Session Document: A synthesized work product that groups multiple voice notes from one reading/learning period into a coherent document with title, summary, key ideas, open questions, and gaps."
- **Data Model**: Add `session_documents` and `session_document_components` to the main tables list. Add `document_uuid` to `voice_note_details` columns. Add `target_type` and `document_id` to `reflections` columns.
- **Services table**: Add `SessionBuilderService` row with file path and responsibility description.
- **Slash Commands table**: Add `/build_doc` and `/build_doc stats` rows.

---

## Execution Log

- [2026-08-11 12:00] Agent: Orchestrator | Status: completed | Defined feature spec with user (11 locked decisions)
- [2026-08-11 12:05] Agent: Orchestrator | Status: in_progress | Writing spec files (proposal + plan)
- [2026-08-11 12:10] Agent: Orchestrator | Status: completed | Migration SQL doc written
- [2026-08-11 12:15] Agent: Orchestrator | Status: completed | Migration applied via supabase_apply_migration (session_documents, session_document_components, voice_note_details.document_uuid, reflections.target_type + document_id)
- [2026-08-11 12:16] Agent: Orchestrator | Status: completed | RLS enabled on session_documents + session_document_components (matches project convention)
- [2026-08-11 12:16] Agent: Orchestrator | Status: completed | Migration verified: all tables, columns, FKs, and constraints confirmed via list_tables + execute_sql
- [2026-08-11 12:17] Agent: Orchestrator | Status: in_progress | Delegating code implementation to backend agent
- [2026-08-11 12:30] Agent: Backend | Status: completed | All implementation tasks complete. 344/344 tests pass. Files created: models/session_document.py, repositories/session_documents_repository.py, services/session_synthesis_prompt.py, services/session_builder_service.py, controllers/session_documents_controller.py. Files modified: models/__init__.py, repositories/__init__.py, services/note_enrichment_service.py, services/telegram_command_handler.py, controllers/__init__.py, controllers/telegram_controller.py, docs/project_spec.md. Tests created: repositories/test_session_documents_repository.py, services/test_session_builder_service.py, test_session_documents_endpoints.py. Tests extended: services/test_note_enrichment_service.py, test_telegram_command_handler.py.
- [2026-08-11 22:15] Agent: Backend | Status: completed | Implemented all code: models, repository, enrichment method, synthesis prompt, SessionBuilderService, controller, command handler wiring, DI, router registration
- [2026-08-11 22:15] Agent: Backend | Status: completed | All 344 tests pass (0 failures, 12 pre-existing warnings)
- [2026-08-11 22:20] Agent: Orchestrator | Status: completed | Verified test suite: 344 passed, 0 failed
- [2026-08-11 22:20] Agent: Orchestrator | Status: completed | Verified key files: SessionBuilderService, SessionSynthesisPrompt, SessionDocumentsController, TelegramCommandHandler /build_doc wiring, router registration in __init__.py + main.py
- [2026-08-11 22:25] Agent: Orchestrator | Status: completed | Phase 2 stub spec written: specs/features/session_documents_reflection_redirect.md
- [2026-08-11 22:25] Agent: Orchestrator | Status: in_progress | Final sanity check
- [2026-08-11 22:30] Agent: Orchestrator | Status: completed | Final sanity: 344 tests pass, 0 failures. Security advisors: no new issues for session_documents tables (RLS enabled, matches project convention). /help updated with /build_doc + /build_doc stats.
- [2026-08-11 22:30] Agent: Orchestrator | Status: completed | Feature v1 implementation complete. Phase 2 reflection redirect documented in separate spec.
- [2026-08-11 22:45] Agent: Orchestrator | Status: completed | Live API test for yt-hayek-paper succeeded: HTTP 201, document 667abdcc-7deb-40d6-b6ee-2bc182363c2a, 12 notes linked, 4 components created
- [2026-08-11 22:46] Agent: Orchestrator | Status: completed | Found and fixed targeted enrichment batching bug: enrich_specific_notes() processed only first 5 notes; now processes all notes in batches of 5 while preserving label cap
- [2026-08-11 22:47] Agent: Orchestrator | Status: completed | Added regression test for >5 targeted notes; full suite now 345 passed, 12 warnings
- [2026-08-11 23:00] Agent: Orchestrator | Status: completed | Restructured schema: dropped summary/key_ideas/open_questions/open_gaps columns, added content TEXT, dropped session_document_components table
- [2026-08-11 23:01] Agent: Orchestrator | Status: completed | Cleaned up test document 667abdcc + reset 12 notes to pending
- [2026-08-11 23:10] Agent: Backend | Status: completed | Restructured all code: models, repository, prompt, service, controller, settings, tests for single content column
- [2026-08-11 23:15] Agent: Orchestrator | Status: completed | Fixed reasoning_effort parameter name (reasoning={"effort":...} → reasoning_effort=...)
- [2026-08-11 23:20] Agent: Orchestrator | Status: completed | Full test suite: 343 passed, 0 failed
- [2026-08-11 23:37] Agent: Orchestrator | Status: completed | Reprocessed yt-hayek-paper: HTTP 201, document 4f8b51b6, 12 notes linked, 12 enriched, content 5646 chars
- [2026-08-11 23:38] Agent: Orchestrator | Status: completed | Cleaned up empty document from failed 500 attempt
