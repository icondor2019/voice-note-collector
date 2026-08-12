# Session Documents Migration

Introduces `session_documents` and `session_document_components` tables, adds a
`document_uuid` FK to `voice_note_details` (n:1 notes → document), and extends
`reflections` with Phase 2 schema hooks (`target_type`, `document_id`).

> **Status: pending application.** Apply via Supabase MCP (`supabase_apply_migration`)
> or manually in the Supabase dashboard. Steps 1–3 are safe to run before deploying
> the code. Step 4 (reflections extension) is also safe — it adds nullable columns
> with no behavior change.

Apply these steps in Supabase/Postgres **in order**.

## 1. Create the session_documents table

```sql
CREATE TABLE IF NOT EXISTS session_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    title TEXT,
    summary TEXT,
    key_ideas TEXT,
    open_questions TEXT,
    open_gaps TEXT,
    status TEXT NOT NULL DEFAULT 'ready'
        CHECK (status IN ('ready', 'reviewed')),
    parent_document_id UUID REFERENCES session_documents(id) ON DELETE SET NULL,
    telegram_user_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS session_documents_source_created_idx
    ON session_documents (source_id, created_at DESC);
```

RLS is not enabled on this table in v1 (matches the pattern of `sources` and
`voice_notes` — the backend reaches it with the `service_role` key, which bypasses
RLS). If advisors flag this, enable RLS with no policies (same as
`voice_note_labels`).

## 2. Create the session_document_components table

```sql
CREATE TABLE IF NOT EXISTS session_document_components (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_document_id UUID NOT NULL REFERENCES session_documents(id) ON DELETE CASCADE,
    component_type TEXT NOT NULL
        CHECK (component_type IN ('socratic_question', 'knowledge_gap',
                                  'connection', 'reflection', 'mind_change')),
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'llm'
        CHECK (source IN ('llm', 'user')),
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS session_doc_components_doc_idx
    ON session_document_components (session_document_id, created_at DESC);
```

## 3. Add document_uuid FK to voice_note_details

```sql
ALTER TABLE voice_note_details
    ADD COLUMN IF NOT EXISTS document_uuid UUID
    REFERENCES session_documents(id) ON DELETE SET NULL;
```

`document_uuid IS NULL` = note is pending (not in any document).
`ON DELETE SET NULL` so deleting a document doesn't delete the notes — they
become pending again and can be re-grouped.

## 4. Extend reflections with Phase 2 hooks (schema only, no behavior change)

```sql
ALTER TABLE reflections
    ADD COLUMN IF NOT EXISTS target_type TEXT
        CHECK (target_type IS NULL OR target_type IN ('note', 'document')),
    ADD COLUMN IF NOT EXISTS document_id UUID
        REFERENCES session_documents(id) ON DELETE SET NULL;
```

These columns are nullable and unused in v1. They exist so that Phase 2
(reflection redirect to documents) doesn't require another migration.

## Verification

After applying all steps, verify:

```sql
-- Check tables exist
SELECT table_name FROM information_schema.tables
WHERE table_name IN ('session_documents', 'session_document_components')
  AND table_schema = 'public';

-- Check voice_note_details.document_uuid exists
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'voice_note_details' AND column_name = 'document_uuid';

-- Check reflections extensions
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'reflections'
  AND column_name IN ('target_type', 'document_id');
```
