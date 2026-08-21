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
* Multi-agent service: a single `MultiAgentService` with a supervisor and sub-graphs for chat and reflection. Reflect is a first-class mode with Socratic hints and auto-continuation.
* Reflection Agent: `/reflect` slash command that starts a Socratic reflection loop on a non-internalized note from the active source, with `HintAgent` (bilingual Socratic hints), `ScorerAgent` (1-10 rating + structured feedback), and auto-continuation to the next note. Slash-cancels-reflect: any slash command in reflect mode cancels the pending reflection and exits to agent mode.
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
- Label: A tag that can be applied to voice notes for organization and retrieval. The note-to-label relation lives in the `voice_note_labels` join table, which soft-deletes removals and tracks whether each label came from the enrichment LLM or the user.
- voice note details: Additional metadata about a voice note, such as title and processing status.
- Chat memory: Per-user short-term conversation history stored in Supabase, scoped by telegram_user_id, used to provide context to the chat agent.
- Reflection: A single-turn interaction where the bot asks a question based on a single note from the active source, the user responds (text or voice), and the bot rates the response (1-10). Notes are marked as "internalized" when meet a criteria
- Session Document: A synthesized work product that groups multiple voice notes from one reading/learning period into a coherent document with title, summary, key ideas, open questions, and gaps.
- Multi-agent architecture: A single `MultiAgentService` LangGraph `StateGraph` with a deterministic `supervisor_node` that routes on `mode` to either a `chat_node` (wrapping `ChatAgentService`) or a `reflect_node` (Python if/else dispatch over `pending_reflection` to `start_reflection` / `cancel_reflection` / `_classify_and_route` → `_hint` / `_context` / `_answer` with auto-loop). Sub-agents (`QuestionAgent`, `ScorerAgent`, `HintAgent`) are pure LLM calls; the orchestrator is the only writer to the DB.

---

## 4. Data Model

Table schemas are defined in backend/repositories/schema_queries.py
Main tables:
- voice_notes
- sources (includes `url` nullable text and `type` nullable text with CHECK constraint: youtube|instagram|facebook|linkedin|web|book|course|thought|test|other)
- labels
- voice_note_details (includes document_uuid FK to session_documents)
- voice_note_labels (join table between voice notes and labels; soft-deleted via deleted_at, and records whether the label was applied by the LLM or the user)
- voice_note_chat_memory (stores per-user short-term conversation history for the chat agent)
- reflections (stores reflection sessions with rating, feedback, status: pending/completed/cancelled; includes target_type and document_id for Phase 2 document reflection)
- session_documents (synthesized work products grouping multiple voice notes; status: ready/reviewed)
- session_document_components (append-only evolving artifacts for session documents: socratic_question, knowledge_gap, connection, reflection, mind_change)

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
| MultiAgentService | backend/services/multi_agent_service.py | Unified entry point. Owns a LangGraph `StateGraph` with `supervisor_node` → `chat_node` | `reflect_node` | `source_create_node`. `handle(user_message, telegram_user_id) -> MultiAgentResult` hydrates `pending_reflection` AND `source_create_context` (from `SourceCreateAgent.get_pending_context()`), invokes the graph, returns the reply + outcome. The supervisor routes to `source_create_node` when a pending source creation context exists. |
| SourceCreateAgent | backend/services/source_create_agent.py | LLM-driven (gpt-5.6-luna, reasoning_effort=medium) multi-turn source creation and enrichment. **Two decoupled concerns**: (1) `create_source_from_url()` — deterministic URL creation (no LLM, no pending context), resolves type, generates default name, creates and activates source. (2) `start_enrich_flow()` — source-agnostic enrichment initiation for ANY active source (sets pending context for LLM conversation). Handles `/create` variants (guided flow, name-based). Enforces always-ask rule (must ask for author and comment). **Confirmation flow**: after collecting all fields, shows a summary of exact proposed changes (including empty fields) and waits for explicit confirmation before persisting. Affirmative responses apply; corrections revise the summary; ambiguous `no` triggers clarification. On apply: persists all staged fields, clears ephemeral pending context, sends final summary with "We are now in note mode." `start_url_flow()` has been deleted. Supports `test` (prefix `ts-`) and `other` (prefix `ot-`) source types. Invalid type synonyms are explained and mapped to canonical types after user confirmation. |
| UrlDetectorService | backend/services/url_detector_service.py | Detects URL-only messages (entire message is a URL). Returns False for URL + additional text. |
| SourceTypeResolver | backend/services/source_type_resolver.py | Maps URL domains to source types (youtube, instagram, facebook, linkedin, web). |
| QuestionAgent | backend/services/agents/question_agent.py | Generates a reflection question for a single note. Wraps `QUESTION_GENERATION_PROMPT` (moved verbatim from `ReflectionService`). Returns `AgentResult(outcome="asked", reply=question_text, updates={question_type, question_text})`. |
| ScorerAgent | backend/services/agents/scorer_agent.py | Rates a user's answer 1-10 and produces structured bullet-point feedback. Wraps `RATING_PROMPT` (moved verbatim from `ReflectionService`); rating clamped 1-10. Returns `AgentResult(outcome="scored", reply=feedback, updates={rating})`. |
| HintAgent | backend/services/agents/hint_agent.py | Socratic, bilingual (English or Spanish — language of the note). New `HINT_PROMPT`. Never reveals the answer. Returns `AgentResult(outcome="hinted", reply=socratic_text)`. |
| TelegramBotClient | backend/services/telegram_bot_client.py | Thin httpx wrapper for the Telegram Bot API. Methods: send_message, send_message_with_inline_keyboard (for reply_markup keyboards), edit_message_text (handles "message is not modified" gracefully), answer_callback_query (dismisses inline button loading indicator). |
| SessionBuilderService | backend/services/session_builder_service.py | Synthesizes session documents from multiple voice notes. build(source_id, note_ids) enriches un-enriched notes then synthesizes via LLM. preview(source_id, note_ids) returns read-only summary. |

---

## 10. Slash Commands

| Command | Description |
|---------|-------------|
| `/note` | Switch to note mode (default) |
| `/agent` | Switch to agent mode (LLM-powered chat) |
| `/reflect` | Enter reflect mode and start a reflection on a non-internalized note from the active source. Posts the first question. |
| `/reflect stats` | Show internalization progress for the active source |
| `/build_doc` | Synthesize pending notes from the active source into a session document. Enriches un-enriched notes first, then synthesizes via LLM. |
| `/build_doc stats` | Preview pending notes for a session document without synthesizing (no DB writes). |
| `/current` | Show the current mode and pending state |
| `/help` | List all available commands |
| `/sources` | **Displays an interactive inline keyboard** (one button per source, ✅ marks the active source, pagination at 6 per page with ◀️/▶️ navigation). Tapping a source activates it and edits the message in place. `/switch <name>` is unchanged. |
| `/create` | Start guided source creation flow (agent asks for type, name, author, comment) |
| `/create <name>` | Create a source with a given name (must have type prefix, e.g. `yt-my-video`) |
| `/create <url>` | Create a source from a URL (deterministic: auto-detects type, generates default name, no LLM) |
| `/update` | Enrich the active source's metadata (name, author, comment) via LLM conversation. Works on any active source regardless of how it was created. |
| `/switch <name>` / `/default` / other source commands | Source management (unchanged) |

**URL-only trigger**: Sending a message that is entirely a URL (no additional text) triggers **deterministic creation**: the system auto-detects the type from the domain, generates a default name, creates the source immediately in the DB, and returns a confirmation. **No LLM call. No enrichment. No follow-up questions.** To enrich the source afterwards, the user sends `/update`.

**Source naming convention**: All source names follow the format `prefix-word1-word2` (3 words, slugified). Valid prefixes: `yt-` (youtube), `ig-` (instagram), `fb-` (facebook), `lkn-` (linkedin), `wb-` (web), `bk-` (book), `cr-` (course), `th-` (thought), `ts-` (test), `ot-` (other).

**Slash-cancels-reflect rule**: any slash command sent while in `reflect` mode cancels the pending reflection and switches the mode back to `agent`. No dedicated `/reflect cancel` is needed.

---

## 11. Modes

`ChatModeService` (process-global in-memory flag) accepts three values:

| Mode | Default | Behavior |
|------|---------|----------|
| `note` | yes | Voice notes and non-slash text are saved as notes. |
| `agent` | no | Voice notes and non-slash text are routed through `MultiAgentService.chat_node` → `ChatAgentService`. |
| `reflect` | no | Voice notes and non-slash text are routed through `MultiAgentService.reflect_node` → Socratic reflection loop. Hints and reminders are in the language of the active note. Auto-continues to the next non-internalized note after each answer until exhausted. |

`note` mode never reaches `MultiAgentService` — the message handler saves the note before calling the service.