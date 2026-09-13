## 1. Feature: web_note_build_selection

### 2. Context

The authenticated web library already renders notes and documents, while `SessionBuilderService.build(source_id, note_ids)` contains the complete enrichment and synthesis pipeline used by the Telegram build flow. This feature adds a secure web selection surface without duplicating that pipeline.

### 3. Spec

#### 3.1 Requirements

- Enter note selection through a 500 ms long press or an accessible Select control.
- Select one or more eligible notes from a single source.
- Keep already-used notes visible but disabled.
- Confirm the source and count before building, show loading/error feedback, and redirect to the created document.
- Protect the web mutation with the existing session and CSRF mechanisms.

#### 3.2 Acceptance Criteria

- `POST /notes/build` delegates to `SessionBuilderService.build()` and returns a document redirect on success.
- Invalid CSRF, no valid notes, and incomplete enrichment map to the documented error responses.
- The selection state survives HTMX load-more swaps, enforces one source, prevents double submission, and supports keyboard operation.
- Existing Telegram/API build behavior remains unchanged.

### 4. Design

#### 4.1 Architecture

The web controller exposes a session-authenticated JSON action and reuses the existing builder dependency. Note cards derive eligibility from the existing `voice_note_details.document_uuid` relation; no schema changes are required.

#### 4.2 File Structure

- `backend/controllers/web_controller.py`
- `backend/repositories/voice_notes_repository.py`
- `frontend/templates/notes/`, `frontend/static/js/app.js`, `frontend/static/css/app.css`
- `tests/controllers/test_web_controller.py`, `tests/repositories/test_web_library_queries.py`

### 5. Tasks

- [x] Create branch `codex/web-note-build-selection` from updated `origin/main`.
- [x] Add note eligibility projection and secure web build endpoint.
- [x] Add long-press, accessible selection controls, source restriction, confirmation dialog, loading and error states.
- [x] Update project specification and focused tests.
- [x] Run the complete regression suite and bounded visual QA.

### 6. Tests

- [x] Repository eligibility and document-membership coverage.
- [x] Web endpoint success, CSRF, and builder-error coverage.
- [x] Template and JavaScript contract coverage.
- [x] Full suite and bounded desktop/responsive-state visual verification.

### 8. Dependencies

Existing Supabase relations, web authentication/CSRF, HTMX, and `SessionBuilderService`. No new package or migration.

### 9. Notes

The build remains synchronous. The server revalidates source ownership and document eligibility through the existing builder before enriching or synthesizing notes.

### 10. project_spec.md Alignment

Updated `docs/project_spec.md` to describe the authenticated web build capability and single-source restriction.
