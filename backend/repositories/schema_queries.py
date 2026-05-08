"""SQL queries for creating the database schema."""

# Sources table creation query
CREATE_SOURCES_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name TEXT NOT NULL,
    author TEXT,
    comment TEXT,
    status TEXT NOT NULL DEFAULT 'deactivated' CHECK (status IN ('active', 'deactivated')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# Voice notes table creation query
CREATE_VOICE_NOTES_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS voice_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    raw_text TEXT,
    clean_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    message_id BIGINT UNIQUE,
    audio_file_id TEXT,
    duration_seconds FLOAT
);
"""

# Constraints
CREATE_SINGLE_ACTIVE_SOURCE_INDEX_QUERY = """
CREATE UNIQUE INDEX IF NOT EXISTS sources_one_active_idx
ON sources (status)
WHERE status = 'active';
"""

# Labels table creation query
CREATE_LABELS_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS labels (
    id SERIAL PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (label = LOWER(label) AND LENGTH(label) <= 64)
);
"""

# Voice note details table creation query
CREATE_VOICE_NOTE_DETAILS_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS voice_note_details (
    voice_note_uuid UUID PRIMARY KEY REFERENCES voice_notes(id) ON DELETE CASCADE,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'enriched', 'reviewed')),
    label_ids INTEGER[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""
