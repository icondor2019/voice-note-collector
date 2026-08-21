# Source Type Extension: `test` and `other`

Add `test` and `other` to the `sources.type` CHECK constraint.

## Context

The existing CHECK constraint on `sources.type` only allows:
`youtube`, `instagram`, `facebook`, `linkedin`, `web`, `book`, `course`, `thought`.

This migration extends it to also allow `test` and `other`.

## SQL

```sql
-- Drop the existing CHECK constraint (name may vary — check with \d sources)
ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_type_check;

-- Re-create with the expanded set of valid types
ALTER TABLE sources ADD CONSTRAINT sources_type_check CHECK (
  type IN (
    'youtube', 'instagram', 'facebook', 'linkedin',
    'web', 'book', 'course', 'thought',
    'test', 'other'
  )
);
```

## Notes

- Non-breaking: existing rows with valid types are unaffected.
- The constraint name `sources_type_check` is the conventional name; if the original
  constraint was created with a different name (e.g. `sources_type_key`), adjust the
  `DROP CONSTRAINT` accordingly. Verify with `\d sources` in psql.
- `test` prefix: `ts-`
- `other` prefix: `ot-`
- This migration must be applied before the application code attempts to insert
  `test` or `other` as a source type.
