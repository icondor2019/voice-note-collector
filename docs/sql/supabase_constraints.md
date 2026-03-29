# Supabase Constraints for Sources & Voice Notes

Apply these constraints in Supabase/Postgres to enforce correctness.

## voice_notes.message_id uniqueness (idempotency)

```sql
ALTER TABLE voice_notes
ADD CONSTRAINT voice_notes_message_id_unique UNIQUE (message_id);
```

## Single active source (partial unique index)

```sql
CREATE UNIQUE INDEX sources_one_active_idx
ON sources (status)
WHERE status = 'active';
```
