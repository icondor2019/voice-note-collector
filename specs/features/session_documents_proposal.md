# Proposal: Session Documents — From Per-Note Review to Session-Level Understanding

## Intent

Today the app stores voice notes and enriches them individually (title + labels). Reflection is also per-note: pick one note, ask a Socratic question, rate the answer. This works mechanically but doesn't match how learning actually happens — a single note is a fragment of a thought at a moment in time, not enough context to test understanding.

Goal: introduce a **session document** layer that groups multiple notes from one reading/learning period into a single synthesized document. The document preserves the user's own reflections (not just a summary of the source) and evolves over time with Socratic questions, knowledge gaps, connections, and mind-changes. Reflection will eventually target documents instead of notes (Phase 2, separate spec).

The progression: **Raw thoughts → Session understanding → Source understanding → Ongoing review**.

## Scope

### In Scope (v1)
- New `session_documents` table: synthesized work product with `title`, `summary`, `key_ideas`, `open_questions`, `open_gaps`.
- New `session_document_components` table: append-only evolving artifacts (`socratic_question`, `knowledge_gap`, `connection`, `reflection`, `mind_change`).
- Reuse `voice_note_details` with a new `document_uuid` FK column (n:1 notes → document). No new join table.
- One service: `SessionBuilderService.build(source_id, note_ids)` — enriches un-enriched notes, then synthesizes the document. Always in that order. Same service called from both the command and the API.
- `/build_doc` slash command: reads pending notes (`document_uuid IS NULL`) from the active source, calls `build()`.
- `/build_doc stats` subcommand: preview pending notes without synthesizing (no DB writes).
- `POST /api/session-documents` endpoint: caller passes explicit `note_ids`, same `build()` call.
- `GET /api/session-documents/{id}` endpoint: fetch document + components + attached notes.
- `NoteEnrichmentService.enrich_specific_notes(note_ids)`: targeted enrichment for a specific note list (same `MAX_LLM_LABEL_CREATIONS_PER_RUN` cap).
- Labels on documents are computed on read (union of constituent notes' labels via JOIN). No label storage on `session_documents`.
- `reflections` table extended with `target_type` + `document_id` columns (schema hook only, no behavior change).
- `parent_document_id` on `session_documents` (nullable, for future source-level synthesis).

### Out of Scope (Phase 2 — separate spec)
- Reflection redirect: picking documents instead of notes for Socratic review.
- `/reflect stats` rewrite over `session_documents`.
- `SessionSelectorService` (sibling to `NoteSelectorService`).
- Document-flavored prompts for `QuestionAgent` / `ScorerAgent` / `HintAgent`.
- Source-level synthesis (chapter/book → one document from many session documents).
- Web UI for viewing documents.
- Time-based or note-count-based auto-close of sessions.

## Approach

### One service, two call sites

```
/build_doc (Telegram)          POST /api/session-documents (HTTP)
       │                                    │
       ▼                                    ▼
  query pending notes              note_ids from request body
  (document_uuid IS NULL)
       │                                    │
       └──────────────┬─────────────────────┘
                      ▼
          SessionBuilderService.build(source_id, note_ids)
                      │
                ┌─────┴─────┐
                ▼           ▼
          Step A:       Step B:
          Enrich        Synthesize
          (if needed)   (LLM call)
                │           │
                ▼           ▼
          titles +     session_documents row
          labels       + components seeded
                      │
                      ▼
              voice_note_details.document_uuid = new doc id
```

### Validation

`build()` validates `note_ids`:
- Excludes notes where `document_uuid IS NOT NULL` (already grouped).
- Excludes notes that don't belong to the given `source_id`.
- Logs how many were filtered.

### Enrichment integration

- Only notes with `voice_note_details.status = 'created'` get enriched (already-enriched notes skip — no double spend).
- Same `MAX_LLM_LABEL_CREATIONS_PER_RUN` cap honored (less hallucination risk with fewer notes).
- Order: enrich → wait → synthesize. The synthesis LLM benefits from per-note titles as anchors.

### Key decisions (locked with user)

| Decision | Choice |
|---|---|
| Session trigger | Explicit `/build_doc` slash command |
| Per-note enrichment | Keep as-is |
| Label inheritance | Compute on read (no storage on documents) |
| Backfill | No separate service — same `build()` called with explicit `note_ids` |
| Table reuse | `document_uuid` FK on `voice_note_details` (n:1, no join table) |
| `/reflect stats` | Deferred to Phase 2 |
| Stats preview | `/build_doc stats` subcommand |
| Enrichment cap | Honored (no bypass) |
| Progress reply | Single interim "⏳ enriching + synthesizing…" message |
| Phase 2 hooks | `reflections.document_id` + `target_type` (schema only) |
| Note validation | Exclude already-grouped + source mismatches |
