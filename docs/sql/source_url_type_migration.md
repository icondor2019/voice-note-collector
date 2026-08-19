# Source URL & Type Migration

Add `url` and `type` columns to the `sources` table.

## SQL

```sql
-- Add url column (nullable text)
ALTER TABLE sources ADD COLUMN url TEXT;

-- Add type column (nullable text with CHECK constraint)
ALTER TABLE sources ADD COLUMN type TEXT CHECK (
  type IN ('youtube', 'instagram', 'facebook', 'linkedin', 'web', 'book', 'course', 'thought')
);
```

## Notes

- Both columns are nullable — existing 22 rows remain unchanged (url=NULL, type=NULL).
- The CHECK constraint enforces valid source type values.
- Non-breaking: existing queries that don't reference these columns continue to work.
