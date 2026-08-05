# Label Provenance & Soft-Delete Migration

Adds `created_by` and `deleted_at` to the `labels` table, so a label can be attributed
to whoever created it (human via `/label`, or the LLM during enrichment) and later
deprecated without a hard delete.

> **Status: applied 2026-08-04.** Both columns exist on `labels`; all 27 pre-existing
> rows backfilled to `created_by = 'user'` via the column default.

Both columns are additive with safe defaults, so this is backward compatible with code
that hasn't deployed yet — existing rows and existing readers/writers are unaffected
until the new code ships.

## 1. Add the columns

```sql
ALTER TABLE labels ADD COLUMN created_by TEXT NOT NULL DEFAULT 'user' CHECK (created_by IN ('llm', 'user'));
ALTER TABLE labels ADD COLUMN deleted_at TIMESTAMPTZ;
```

Every pre-existing label was created by a human via `/label`, so defaulting
`created_by` to `'user'` backfills correctly with no data migration needed.

## 2. Deploy the code

`LabelsRepository.create_label` starts passing `created_by` explicitly (`'user'` from
the Telegram `/label` command, `'llm'` from enrichment), and `list_labels` /
`get_label_by_name` start filtering to `deleted_at IS NULL`.

## 3. Verify

```sql
SELECT created_by, COUNT(*) FROM labels GROUP BY created_by;
```

Note: this migration only adds the columns and the read-path filtering. No
`/deprecate-label` command exists yet to actually set `deleted_at` — that's future
work.
