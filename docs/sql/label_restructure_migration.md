# Label Restructure Migration

Replaces `voice_note_details.label_ids INTEGER[]` with a `voice_note_labels` join table.

> **Status: fully applied 2026-08-03.** All four steps ran against the project database and
> were verified end to end (17 pairings backfilled, live enrichment run confirmed the
> non-destructive re-run and revive paths, `label_ids` dropped). Kept here as the record of
> what was applied. See `label_ids_pre_drop_snapshot.md` for the pre-drop rollback artifact.

Apply these steps in Supabase/Postgres by hand, **in order**. Steps 1–2 are safe to run
before deploying the code. Step 4 must wait until the new code is live.

## 1. Create the join table

```sql
CREATE TABLE IF NOT EXISTS voice_note_labels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    voice_note_uuid UUID NOT NULL REFERENCES voice_notes(id) ON DELETE CASCADE,
    label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    applied_by TEXT NOT NULL DEFAULT 'llm' CHECK (applied_by IN ('llm', 'user')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS voice_note_labels_active_idx
ON voice_note_labels (voice_note_uuid, label_id)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS voice_note_labels_label_idx
ON voice_note_labels (label_id)
WHERE deleted_at IS NULL;

ALTER TABLE voice_note_labels ENABLE ROW LEVEL SECURITY;
```

The unique index is partial so a soft-deleted pairing can be re-applied later.

RLS is enabled with no policies, matching every other voice-note table: nothing is
reachable through the public PostgREST API, and the backend reaches it with the
`service_role` key, which bypasses RLS.

## 2. Backfill from the existing arrays

```sql
INSERT INTO voice_note_labels (voice_note_uuid, label_id, applied_by)
SELECT d.voice_note_uuid, unnest(d.label_ids), 'llm'
FROM voice_note_details d
WHERE array_length(d.label_ids, 1) > 0
ON CONFLICT (voice_note_uuid, label_id) WHERE deleted_at IS NULL DO NOTHING;
```

Every existing pairing is attributed to `llm`, since enrichment was the only writer.

Verify the row count matches the arrays:

```sql
SELECT
    (SELECT COUNT(*) FROM voice_note_labels WHERE deleted_at IS NULL) AS migrated,
    (SELECT COALESCE(SUM(array_length(label_ids, 1)), 0) FROM voice_note_details) AS expected;
```

## 3. Deploy the code

`VoiceNoteDetailsRepository` stops reading and writing `label_ids` at this point.

## 4. Drop the old column

Only after step 3 is live and verified:

```sql
ALTER TABLE voice_note_details DROP COLUMN label_ids;
```
