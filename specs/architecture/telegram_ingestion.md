Telegram Ingestion

Purpose
-------

Define the webhook contract, event model, raw JSONL persistence, idempotency rules and recommended processing flow so implementers can build the ingestion service consistently for Step 2 (Telegram webhook ingestion MVP).

Webhook endpoint contract
------------------------

- Endpoint: POST /api/telegram/webhook
- Content-Type: application/json
- Body: Telegram Update object (as defined by Telegram API). Implement a Pydantic model subset that covers the fields we'll use:
  - update_id: int
  - message: object | null
    - message_id: int
    - chat: {id: int}
    - from: {id: int, is_bot: bool, first_name: str, username?: str}
    - voice?: {file_id: str, duration: int, mime_type?: str, file_size?: int}
    - audio?: {file_id: str, ...}

- Response:
  - 200 OK on successful receipt and scheduled processing
  - 400 Bad Request for invalid payloads
  - 401 Unauthorized when basic verification fails (MVP: lightweight checks against TELEGRAM_BOT_USER)

Quick verification (MVP)
------------------------

- MVP allows only two Telegram settings: TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_USER. No other Telegram-specific environment variables are required for Step 2.
- The webhook should perform lightweight checks:
  - If message.from.is_bot is True, ignore.
  - If message appears targeted to a different bot username, log and ignore.
  - Future (out of scope for Step 2): support WEBHOOK_SECRET_TOKEN header and HMAC verification — document only as a security hardening task.

Raw JSONL persistence (MVP)
--------------------------

- Purpose: keep an append-only stream of raw updates to enable replay and debugging.
- Format: one JSON object per line (JSONL). Default file path for Step 2: ./data/telegram_ingestion_events.jsonl.
- Implementation rules for MVP:
  - Writes must be append-only and performed off the request critical path (e.g., FastAPI BackgroundTasks).
  - Each line must include: received_at (ISO8601), request_id, update_id, raw_update_body.
  - Tests must override the JSONL sink path by injecting a FileSink or path into the JSONL writer via constructor/parameter; tests must NOT rely on environment variables to change the sink path.
  - Roll-over / rotation not required in MVP; document as future work.

Idempotency model (Step 2)
-------------------------

- Primary idempotency key for Step 2: chat_id:message_id (derived from message.chat.id and message.message_id). This follows the approved feature spec and avoids relying on Telegram file_unique_id for this step.
- Constraints:
  - Only one persisted voice note per chat_id:message_id.
  - Persistence for Step 2 must enforce uniqueness by adding a unique constraint/index on (chat_id, message_id) or equivalent.
- Processing behavior:
  - On receiving an update, the service checks persistence for an existing record with the same chat_id:message_id.
  - If exists: skip further processing; return 200 and log duplicate.
  - If not exists: persist metadata and enqueue or perform file download/storage in background.

Background processing vs synchronous
----------------------------------

- Webhook handler must acknowledge rapidly. Heavy operations (downloading files from Telegram, storing large audio) must be performed in a background task or short-lived worker.
- For MVP it's acceptable to use FastAPI BackgroundTasks to download the file and store it; a simple in-process queue is also acceptable for Step 2.

Error handling
--------------

- If a background task fails to download/store file, record a processing_error field in the persistence layer with timestamp and error message and allow reprocessing. For Step 2, a simple text field and retry mechanism is sufficient.

Example minimal domain model (for implementers)
----------------------------------------------

- voice_notes table (Step 2 minimal):
  - id: uuid PK
  - chat_id: integer
  - message_id: integer
  - telegram_user_id: integer
  - duration_seconds: integer NULLABLE
  - mime_type: text NULLABLE
  - file_size: integer NULLABLE
  - storage_path: text NULLABLE
  - received_at: timestamp
  - processing_error: text NULLABLE
  - UNIQUE(chat_id, message_id)  -- enforces idempotency for Step 2

Notes
-----

- References to provider-specific persistence (e.g., Supabase, Postgres, external object storage) are considered future steps. Step 2 focuses on webhook receipt, JSONL raw capture (file at ./data/telegram_ingestion_events.jsonl by default), idempotency using chat_id:message_id, and background download orchestration. Implementers may use in-memory or file-backed repositories for MVP tests and local runs.
