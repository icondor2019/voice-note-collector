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

# Chat memory table creation query
CREATE_CHAT_MEMORY_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS voice_note_chat_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_user_id BIGINT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS voice_note_chat_memory_user_created_idx
ON voice_note_chat_memory (telegram_user_id, created_at DESC);
"""

# Reflections table creation query
CREATE_REFLECTIONS_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS reflections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_user_id BIGINT NOT NULL,
    voice_note_id UUID REFERENCES voice_notes(id) ON DELETE SET NULL,
    question_type TEXT NOT NULL CHECK (question_type IN ('follow-up', 'reflective', 'quiz', 'elaboration', 'comparison')),
    question_text TEXT NOT NULL,
    answer_text TEXT,
    rating INTEGER CHECK (rating IS NULL OR (rating >= 1 AND rating <= 10)),
    feedback TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS reflections_user_status_idx
ON reflections (telegram_user_id, status);

CREATE INDEX IF NOT EXISTS reflections_user_created_idx
ON reflections (telegram_user_id, created_at DESC);
"""
