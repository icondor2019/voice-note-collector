Architecture Overview

Context
-------
This project is a small service to collect voice notes sent to a Telegram bot, persist raw events, and provide minimal frontend access. The technology stack for the backend MVP is:

- FastAPI for HTTP/webhook and minimal frontend
-- Supabase (Postgres + Storage) for persistent storage (future/integration; Step 2 MVP does not require Supabase to be present)
- Telegram webhook ingestion for incoming voice notes

High-level components
---------------------

- API (FastAPI)
  - Webhook endpoint for Telegram updates
  - Admin / minimal frontend endpoints (HTML/JS)
- Services
  - Telegram Ingestion Service (validation, idempotency, raw persistence)
  - VoiceNote Service (business logic, metadata, DB persistence)
  - Storage Service (Supabase Storage or signed URL wrappers)
  - Repository / DB layer (Supabase client or Postgres queries)
- Persistence
  - Supabase Postgres for normalized metadata
  - Supabase Storage (or external blob store) for audio files
  - JSONL raw event sink (append-only), implemented as a simple file stub for MVP

Primary flows
-------------

1. Telegram → Webhook: Telegram posts Update objects to FastAPI webhook.
2. Validation & acceptance: FastAPI router validates the Update with Pydantic models and performs quick authenticity checks (MVP uses TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_USER settings; see config spec).
3. Raw capture: The raw JSON is appended to a JSONL sink (local file or object store) for replay/debug.
4. Idempotency check: Service checks for duplicate chat_id:message_id in persistence to avoid re-processing (Step 2 uses chat_id:message_id as primary idempotency key).
5. Persist metadata: Voice note metadata is saved to the chosen persistence for the runtime (in Step 2 this can be in-memory or file-backed). Integration with Postgres/Supabase and external storage is a future step.
6. Frontend/API: Minimal UI can fetch voice note metadata and playback URLs.

Non-functional constraints
-------------------------

- Keep webhook handler fast — acknowledge with 200 quickly; defer heavy work to background tasks or short-lived threads.
- Keep code small and modular: clear controller (router) vs service vs repository separation.
- Only two Telegram-specific settings are permitted in MVP: TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_USER. Webhook secret-token verification is documented as a future hardening step.
