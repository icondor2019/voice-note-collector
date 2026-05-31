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
* Simple label system for notes
* Dual-mode Telegram bot: note mode (default) and agent mode (LLM-powered via LangGraph + gpt-4o-mini)
* Reflection Agent: `/reflect` slash command that asks a question based on last 5 notes from active source, rates the user's response (1-10), and provides structured feedback
* Reflection stats: `/reflect stats` subcommand showing internalization progress per active source

### Excluded (for now)

* Embeddings / vector search
* RAG pipelines
* Audio processing (merging, editing)
* Real-time streaming
* Authentication system
* Multi-user support

---

## 3. Core Concepts

- Voice note: An audio message sent by the user, along with its transcription and metadata.
- Source: A category or project that voice notes can be associated with. One source can be active at a time.
- Label: A tag that can be applied to voice notes for organization and retrieval.
- voice note details: Additional metadata about a voice note, such labels, title and processing status.
- Chat memory: Per-user short-term conversation history stored in Supabase, scoped by telegram_user_id, used to provide context to the chat agent.
- Reflection: A single-turn interaction where the bot asks a question based on a single note from the active source, the user responds (text or voice), and the bot rates the response (1-10). Notes are marked as "internalized" when meet a criteria

---

## 4. Data Model

Table schemas are defined in backend/schema_queries.py
Main tables:
- voice_notes
- sources
- labels
- voice_note_details
- voice_note_chat_memory (stores per-user short-term conversation history for the chat agent)
- reflections (stores reflection sessions with rating, feedback, status: pending/completed/cancelled)

---

## 5. System Flow

- input: user only interacts with Telgram. Can send voice notes, slash commands. 
- processing: dependening on the input: 
   audio: the system processes the audio, transcribes it, and stores it in the database.
   slash command: the system executes the command, ex: /newsource "Book A" → creates a new source and set it as active.
   images: not supported for now
   plain text: in note mode → stored as a voice note; in agent mode → sent to ChatAgentService for LLM response
- output: most of it is backend executions. depending on the input also could include confirmation messages in telegram

---


## 6. Constraints

* Single user system (no authentication required)
* Low infrastructure complexity
* Deployed on Railway
* Uses external APIs (Telegram, Groq, OpenAI)

---

## 7. Error Handling Strategy

* If audio download fails → log and skip
* If transcription fails → store note with raw_text = NULL
* If DB insert fails → retry once, then log
* System must not crash on single failure

---

## 8. Idempotency

* Each Telegram message must be processed once
* Use `message_id` to prevent duplicates

---

## 9. Services

| Service | File | Responsibility |
|---------|------|----------------|
| VoiceNoteService | backend/services/voice_note_service.py | Create and store voice notes in Supabase |
| TranscriptionService | backend/services/transcription_service.py | Transcribe audio via Groq Whisper |
| TelegramIngestionService | backend/services/telegram_ingestion_service.py | Orchestrate audio download, transcription, and storage |
| ChatModeService | backend/services/chat_mode_service.py | Global in-memory flag for note/agent mode toggle |
| ChatAgentService | backend/services/chat_agent_service.py | LangGraph LLM agent (gpt-4o-mini) with per-user short-term memory (last 5 messages); handles agent-mode messages |
| NoteEnrichmentService | backend/services/note_enrichment_service.py | Async enrichment pipeline for stored notes |
| ReflectionService | backend/services/reflection_service.py | Generates reflection questions via LLM, rates user responses (1-10), manages reflection state in Supabase, provides internalization stats via get_reflection_summary() |
| NoteSelectorService | backend/services/note_selector_service.py | Selects a non-internalized note from a source's recent pool for reflection |