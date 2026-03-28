# Project Specification: Voice Notes AI

---

## 1. Objective

Build a system to capture voice-based ideas and convert them into structured, queryable text.

The system should allow the user to:

* Send voice notes via Telegram
* Automatically transcribe them into text
* Store them with structured metadata
* Retrieve and explore them later via a web interface

The primary goal is to create a **personal knowledge capture system**, optimized for future use in AI workflows (e.g., RAG).

---

## 2. Scope (MVP)

### Included

* Telegram bot integration (audio ingestion)
* Audio transcription using external API (Groq Whisper)
* Storage of notes in Supabase (PostgreSQL)
* Source management system (with active source)
* Basic web interface to view notes
* Filtering notes by source

### Excluded (for now)

* Embeddings / vector search
* RAG pipelines
* Audio processing (merging, editing)
* Real-time streaming
* Authentication system
* Multi-user support

---

## 3. Core Concepts

### 3.1 Voice Note

A voice note is the fundamental unit of the system.

It represents a single audio message sent by the user and its corresponding transcription.

Each voice note is:

* independent
* chronologically ordered
* associated with a `source`

---

### 3.2 Source

A `source` represents the context of a note.

Examples:

* a book
* an author
* a topic
* a personal idea stream

#### Rules:

* Only one source can be **active** at a time
* All incoming notes are assigned to the **active source**
* If no source is explicitly selected, a **default source** is used
* Sources can be created dynamically

---

## 4. Data Model

### Table: sources

* id (UUID, primary key)
* source_name (TEXT, NOT NULL)
* author (TEXT, optional)
* comment (TEXT, optional)
* status (TEXT → 'active' | 'deactivated')
* created_at (TIMESTAMP)
* modified_at (TIMESTAMP)

---

### Table: voice_notes

* id (UUID, primary key)
* source_id (UUID, foreign key → sources.id)
* raw_text (TEXT, transcription output)
* clean_text (TEXT, nullable)
* created_at (TIMESTAMP)
* message_id (BIGINT)
* audio_file_id (TEXT)
* duration_seconds (FLOAT, optional)

---

## 5. System Flow

### 5.1 Ingestion Flow

1. User sends a voice note via Telegram
2. Telegram sends update to webhook endpoint
3. Backend extracts audio metadata
4. Backend retrieves the currently active source
5. Backend downloads audio file
6. Audio is sent to transcription service
7. Transcription is returned as text
8. Note is stored in database with active `source_id`

---

### 5.2 Source Management Flow

1. User sends command via Telegram:

   ```
   /source <source_name>
   ```
2. Backend checks if source exists:

   * If exists → activate it
   * If not → create and activate it
3. Backend ensures:

   * All other sources are set to `deactivated`
   * Only one source remains `active`

---

### 5.3 Retrieval Flow

1. User opens web interface
2. Frontend calls backend API
3. Backend fetches notes from database
4. Notes are displayed in chronological order
5. User can filter notes by source

---

## 6. Functional Requirements

### FR1: Telegram Ingestion

* System must receive Telegram webhook updates
* Must detect and process voice/audio messages
* Must ignore unsupported message types

---

### FR2: Audio Download

* System must retrieve audio file using Telegram API
* Must handle download errors gracefully

---

### FR3: Transcription

* System must send audio to transcription provider (Groq)
* Must receive and store transcription result
* Must handle transcription failures (store note with null or retry later)

---

### FR4: Persistence

* System must store notes in Supabase
* Must ensure each note is stored once (idempotency via message_id)

---

### FR5: Retrieval API

* System must expose endpoint to fetch notes
* Must support filtering by `source_id`
* Must return notes ordered by `created_at`

---

### FR6: Web UI

* System must display list of notes
* Must allow filtering by source
* Must show text clearly and readable

---

### FR7: Source Management

* System must allow creating sources
* System must allow switching active source
* System must ensure only one source is active
* System must assign all notes to the active source

---

## 7. Non-Functional Requirements

* System must be simple and maintainable
* System must minimize operational cost
* System must be modular (services-based architecture)
* System must be extensible for AI features
* System must tolerate partial failures (e.g., transcription failure)

---

## 8. Constraints

* Single user system (no authentication required)
* Low infrastructure complexity
* Deployed on Railway
* Uses external APIs (Telegram, Groq)

---

## 9. Error Handling Strategy

* If audio download fails → log and skip
* If transcription fails → store note with raw_text = NULL
* If DB insert fails → retry once, then log
* System must not crash on single failure

---

## 10. Idempotency

* Each Telegram message must be processed once
* Use `message_id` to prevent duplicates

---

## 11. Default Source

* System must initialize with a default source:

  * `source_name = "default"`
  * `status = "active"`
* This source is used when no other source has been selected

---

## 12. Future Extensions

* Text cleaning pipeline (raw → clean_text)
* Tag extraction (books, authors, concepts)
* Embeddings and vector search
* RAG-based querying
* Semantic search UI
* Note linking and knowledge graph

---

## 13. Open Questions

* Should transcription be synchronous or async?
* Should failed transcriptions be retried automatically?
* Should we allow editing or merging sources?

---

## 14. Success Criteria (MVP)

The system is successful if:

* User can send voice notes via Telegram
* Notes are transcribed and stored
* Notes are always assigned to a valid source
* User can switch sources dynamically
* User can view notes in a web UI
* Notes can be filtered by source
* System runs reliably with minimal intervention

---
