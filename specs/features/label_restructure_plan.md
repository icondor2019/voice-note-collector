## 1. Feature: label_restructure

### 2. Context

Labels on a voice note are stored as `label_ids INTEGER[]` on `voice_note_details`. That
shape blocks exploring notes as a graph and carries three concrete defects:

- **No referential integrity.** An array column cannot hold a foreign key, so
  `NoteEnrichmentService._enrich_batch` hand-validates LLM-returned ids against a
  `valid_ids` set — application code compensating for a missing DB constraint.
- **Read-modify-write mutation.** `add_label_id` / `remove_label_id` each do two round
  trips with a lost-update race.
- **No removal history.** Dropping a label from an array leaves no trace.

Two findings from the codebase inventory make the migration cheap:

1. `add_label_id`, `remove_label_id`, and `_update_label_ids` have **zero production
   callers** — only tests reach them.
2. **Nothing queries notes by label.** `label_ids` is write-only at runtime:
   `create_details` seeds `[]`, `update_enrichment` overwrites it, nothing reads it back.

There is therefore no production read path to preserve and no dual-write window needed.
The schema is applied manually in Supabase (`schema_queries.py` has no importers;
`docs/sql/supabase_constraints.md` is the precedent), so the migration ships as a SQL doc.

Decisions taken with the user: keep `labels.id` as `INTEGER` (short ids keep the enrichment
prompt cheap and hard for the model to mangle); scope is structural plus reverse lookup;
no Telegram command surface in this feature.

---

### 3. Spec

### 3.1 Requirements

- A `voice_note_labels` join table relates notes to labels with real foreign keys.
- Removing a label from a note is a soft delete (`deleted_at`), never a hard delete.
- Each pairing records provenance (`applied_by`: `llm` or `user`).
- Re-running enrichment replaces LLM-applied labels but leaves user-applied labels intact.
- A note/label pairing that was soft-deleted can be re-applied later.
- Notes can be looked up by label (reverse lookup) and labels by note.
- `voice_note_details` no longer stores `label_ids` in any form.

### 3.2 Acceptance Criteria

- `voice_note_labels` exists with FKs to `voice_notes(id)` and `labels(id)`, and a partial
  unique index on `(voice_note_uuid, label_id) WHERE deleted_at IS NULL`.
- Existing array data is backfilled with `applied_by = 'llm'` and row counts match.
- `VoiceNoteLabelsRepository` exposes attach, detach, both list directions, a batch list,
  and `replace_llm_labels`.
- `NoteEnrichmentService` writes the title through `update_enrichment` and the labels
  through `replace_llm_labels`, as two separate calls.
- No occurrence of `label_ids` remains in `backend/` outside the enrichment prompt/LLM
  response contract.
- The full test suite passes under `./venv/bin/pytest`.

---

### 4. Design

### 4.1 Architecture

New join table:

```sql
CREATE TABLE voice_note_labels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    voice_note_uuid UUID NOT NULL REFERENCES voice_notes(id) ON DELETE CASCADE,
    label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    applied_by TEXT NOT NULL DEFAULT 'llm' CHECK (applied_by IN ('llm', 'user')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
```

`VoiceNoteLabelsRepository` mirrors the existing repository shape: a `_table` name, an
injected client, and the `_raise_on_error` / `_single` / `_list` static helpers used by
`LabelsRepository`. Failures raise `RepositoryError`.

| Method | Behavior |
|---|---|
| `attach_label(uuid, label_id, applied_by='llm')` | Revive if soft-deleted, no-op if active, else insert. |
| `detach_label(uuid, label_id)` | Sets `deleted_at`; never hard-deletes. |
| `list_labels_for_note(uuid)` | Embedded select `*, labels(id, label)`, active rows only. |
| `list_notes_by_label(label_id)` | Reverse lookup; returns note uuids. |
| `list_labels_for_notes(note_ids)` | Batch via `.in_()`, grouped in Python. |
| `replace_llm_labels(uuid, label_ids)` | Soft-deletes dropped `llm` rows, attaches new ones, leaves `user` rows alone. |

Grouping in Python follows the precedent set by
`ReflectionRepository.get_note_reflection_stats`, which aggregates client-side because
PostgREST cannot.

`attach_label` remains read-then-write, but on a single narrow row now guarded by the
unique index — a concurrent insert fails loudly rather than silently losing data.
Acceptable for a single-user system.

Enrichment splits its single write in two. `update_enrichment` drops its `label_ids`
parameter and writes only `title`, `status`, and `updated_at`. The `valid_ids` filtering in
`_enrich_batch` stays: it stops a hallucinated id from becoming an FK violation mid-batch.

### 4.2 File Structure

```
backend/
  models/voice_note_label.py               (new)
  repositories/voice_note_labels_repository.py  (new)
docs/sql/label_restructure_migration.md    (new)
tests/repositories/test_voice_note_labels_repository.py  (new)
```

---

### 5. Tasks

#### Schema & Models

- [ ] Create `docs/sql/label_restructure_migration.md` with create/backfill/drop steps
- [ ] Add `CREATE_VOICE_NOTE_LABELS_TABLE_QUERY` to `backend/repositories/schema_queries.py`
- [ ] Remove `label_ids` from `CREATE_VOICE_NOTE_DETAILS_TABLE_QUERY`
- [ ] Create `backend/models/voice_note_label.py` with a `VoiceNoteLabel` model
- [ ] Remove `label_ids` from `VoiceNoteDetails` in `backend/models/voice_note_details.py`

#### Repository Layer

- [ ] Create `backend/repositories/voice_note_labels_repository.py`
- [ ] Implement `attach_label`, `detach_label`, `list_labels_for_note`
- [ ] Implement `list_notes_by_label`, `list_labels_for_notes`, `replace_llm_labels`
- [ ] Export `VoiceNoteLabelsRepository` from `backend/repositories/__init__.py`
- [ ] Delete `add_label_id`, `remove_label_id`, `_update_label_ids` from `VoiceNoteDetailsRepository`
- [ ] Remove `"label_ids": []` from `create_details`
- [ ] Drop the `label_ids` parameter from `update_enrichment`

#### Service & Wiring

- [ ] Add a `note_labels_repo` constructor argument to `NoteEnrichmentService`
- [ ] Split the enrichment write into `update_enrichment` + `replace_llm_labels`
- [ ] Add `get_voice_note_labels_repository` to `backend/controllers/enrichment_controller.py`
- [ ] Inject it into `get_enrichment_service`

#### Documentation

- [ ] Add `voice_note_labels` to the table list in `docs/project_spec.md` section 4
- [ ] Fix the stale `backend/schema_queries.py` path in `docs/project_spec.md`

---

### 6. Tests

- [ ] `attach_label` inserts when the pairing is absent
- [ ] `attach_label` revives a soft-deleted pairing instead of inserting a duplicate
- [ ] `attach_label` no-ops when the pairing is already active
- [ ] `detach_label` sets `deleted_at` and does not hard-delete
- [ ] `detach_label` no-ops on an already-detached pairing
- [ ] `list_labels_for_note` excludes soft-deleted rows
- [ ] `list_notes_by_label` returns matching note uuids and excludes soft-deleted rows
- [ ] `list_labels_for_notes` groups by note uuid and returns `{}` for an empty input
- [ ] `replace_llm_labels` soft-deletes dropped `llm` labels and adds new ones
- [ ] `replace_llm_labels` leaves `applied_by='user'` rows intact
- [ ] Each repository method raises `RepositoryError` on a client error
- [ ] Enrichment calls `update_enrichment` and `replace_llm_labels` separately
- [ ] `create_details` payload no longer contains `label_ids`

---

### 8. Dependencies

- `labels` and `voice_notes` tables must exist (they do).
- Migration steps 1–2 must be applied in Supabase before the code is deployed;
  step 4 (`DROP COLUMN`) only after.

---

### 9. Notes

- `LabelsRepository.get_label_by_id` is dead code today. Kept — it is a natural CRUD
  accessor that a follow-up Telegram/API surface will want.
- `voice_note_details.status` (`created` → `enriched` → `reviewed`) is a pipeline state
  machine living on an entity table. Fine for one enrichment step; if summaries or
  embeddings are added later it will not be able to express "titled but not embedded."
  Out of scope here, flagged as the seam to watch.
- `specs/architecture/testing.md` documents conftest fixtures that do not exist. Out of
  scope; noted for a cleanup pass.

---

### 10. project_spec.md Alignment

Updates required:

- Section 4 (Data Model): add `voice_note_labels` to the main tables list.
- Section 4: correct the schema file path from `backend/schema_queries.py` to
  `backend/repositories/schema_queries.py`.

Both are included as explicit tasks in the Documentation section above.
