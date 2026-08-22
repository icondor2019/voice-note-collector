# Source Usage Status Migration

Add `usage_status` column to the `sources` table to control visibility in the `/sources` list.

## SQL

```sql
-- Add usage_status column (NOT NULL, default 'active', CHECK constraint)
ALTER TABLE sources ADD COLUMN usage_status TEXT NOT NULL DEFAULT 'active' CHECK (usage_status IN ('active', 'archive'));
```

## Notes

- All 32 existing rows get `usage_status = 'active'` by default.
- This column is SEPARATE from the existing `status` column (active/deactivated) which tracks the current chat source.
- `usage_status` controls visibility in the `/sources` list: 'active' = visible, 'archive' = hidden.
- A source can be `status='active'` (current chat source) AND `usage_status='archive'` (hidden from lists) simultaneously.
- Non-breaking: existing queries that don't reference this column continue to work.
