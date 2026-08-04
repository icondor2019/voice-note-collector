# `label_ids` snapshot taken before DROP COLUMN

Captured 2026-08-03, immediately before
`ALTER TABLE voice_note_details DROP COLUMN label_ids;`

These are the 10 rows that held array data — the same 17 pairings backfilled into
`voice_note_labels` by `label_restructure_migration.md`.

**Note:** by the time this snapshot was taken the arrays were already stale. A live
enrichment run had written to `voice_note_labels` only, so the join table is the accurate
record and this file is strictly a rollback artifact for the original backfill.

```sql
-- Recovery: recreate the column and restore the pre-migration arrays.
ALTER TABLE voice_note_details ADD COLUMN label_ids INTEGER[] NOT NULL DEFAULT '{}';

UPDATE voice_note_details SET label_ids = v.label_ids
FROM (VALUES
  ('02a52376-a1d4-4a61-9881-138ec663a4b9'::uuid, ARRAY[1,2]),
  ('1bfba713-05e2-4179-ba06-ee3d683d0d1a'::uuid, ARRAY[8,3,2]),
  ('42319973-d7cc-48d7-8cd5-e27a8c0fc014'::uuid, ARRAY[1,13]),
  ('4ee3727b-34e8-4533-bf9a-83a13d6dbf0a'::uuid, ARRAY[1]),
  ('77f4b9be-7cea-4b4c-9a29-1e977bc7b034'::uuid, ARRAY[1]),
  ('808a62e4-c9d6-46f0-9573-4f9a837d6774'::uuid, ARRAY[5,12,4]),
  ('c9712dc4-947c-4161-8c14-c518d9cf7ce6'::uuid, ARRAY[1]),
  ('d2d8d26f-898b-4c10-a839-c16604627dbd'::uuid, ARRAY[8,3]),
  ('de742855-4943-438d-a5d3-18eff994a700'::uuid, ARRAY[1]),
  ('f3d3643a-c4de-46e5-928e-2034ee8dac0f'::uuid, ARRAY[1])
) AS v(voice_note_uuid, label_ids)
WHERE voice_note_details.voice_note_uuid = v.voice_note_uuid;
```
