## 1. Feature: step2_telegram_ingestion_webhook

### 2. Objective
Implement webhook-based Telegram ingestion for the MVP: when a user sends the bot a message (at minimum text and voice note), the backend reliably receives the Telegram update via a FastAPI endpoint and persists enough core metadata to prove ingestion works (transcription and Supabase persistence may be stubbed).

---

### 3. Approved by user

spec_approved_by_user = true
approved_by_user = true

### 4. Tasks

#### Configuration & environment variables

- [x] Confirm Telegram configuration uses the existing settings fields only:
  - [x] `TELEGRAM_BOT_TOKEN: Optional[str] = None`
  - [x] `TELEGRAM_BOT_USER: Optional[str] = None`
- [x] Update `.env.example` to document only the Telegram variables used by this feature:
  - [x] `TELEGRAM_BOT_TOKEN`
  - [x] `TELEGRAM_BOT_USER`

#### API contract (endpoints)

- [x] Create `backend/controllers/telegram_controller.py` with an `APIRouter(prefix="/api/telegram")`
- [x] Wire the new controller into `backend/controllers/__init__.py` aggregator
- [x] Implement `POST /api/telegram/webhook`
  - [x] Accept JSON Telegram Update payloads (at minimum: `message`, `edited_message`, `channel_post`, `callback_query` should not crash parsing; only `message` needs MVP handling)
  - [x] Return `200` quickly for unsupported message types (do not raise)
  - [x] Ensure request parsing errors return `400` with a safe message (no token leakage)
- [ ] (Optional, dev-only) Implement `POST /api/telegram/set_webhook`
  - [ ] Call Telegram `setWebhook` using `TELEGRAM_BOT_TOKEN`
  - [ ] Accept the webhook callback URL as a request field (so this feature does not require additional settings/env vars)
  - [ ] Return a clear JSON result with Telegram response fields needed for debugging (ok/description/error_code)

#### Update handling (MVP message types)

- [x] Implement parsing logic to extract core metadata for:
  - [x] Text messages (`message.text`)
  - [x] Voice notes (`message.voice`) and/or audio (`message.audio`) metadata (file_id, duration, mime type if present)
- [x] Normalize extracted fields into an internal “ingestion event” dict/model (for persistence + logging), including at least:
  - [x] `received_at` (server timestamp)
  - [x] `update_id`
  - [x] `chat_id`
  - [x] `from_user_id` (if available)
  - [x] `message_id`
  - [x] `message_date` (Telegram timestamp)
  - [x] `message_type` (text|voice|audio|unsupported)
  - [x] `text_preview` (optional; truncated)
  - [x] `telegram_file_id` (for voice/audio)
  - [x] `duration_seconds` (for voice/audio)

#### Idempotency & reliability

- [x] Define the idempotency key as `chat_id:message_id` (fallback to `update_id` when `message` absent)
- [x] Implement best-effort dedupe for webhook retries:
  - [x] If a persistent store exists (future Supabase), enforce uniqueness on `chat_id + message_id`
  - [x] Until then, implement a minimal dedupe mechanism compatible with the chosen stub persistence (e.g., skip writing duplicates to the events file)
- [x] Ensure webhook handler is safe to call multiple times with the same payload (no unbounded growth of duplicates)

#### Persistence (proof of ingestion; may be stubbed)

- [x] Create a minimal ingestion persistence interface (service/module) to record ingestion events without requiring Supabase
- [x] Implement file-based JSONL persistence for MVP (append one JSON object per line)
  - [x] Default file path: `./data/telegram_ingestion_events.jsonl`
  - [x] Allow tests to override the file path via constructor/parameter injection (not via env var)
- [x] Ensure persistence failures do not crash the process; log and (decision) either return `500` to trigger Telegram retry or return `200` to avoid retry storms (capture decision in code comments and in logs)

#### Logging & error handling

- [x] Add structured logs for each received update with correlation fields (`update_id`, `chat_id`, `message_id`, `message_type`)
- [x] Log and safely ignore unsupported updates (no stack traces for expected cases)
- [x] Ensure logs never print `TELEGRAM_BOT_TOKEN`

#### Testing

- [x] Add unit/integration tests for `POST /api/telegram/webhook`:
  - [x] Accepts a valid text update and returns `200`
  - [x] Accepts a valid voice update and returns `200`
  - [x] Returns `200` for unsupported message types (e.g., sticker) and logs “ignored”
  - [x] Idempotency: sending the same payload twice does not create two persisted ingestion events (for the chosen stub persistence)
- [x] Add test fixtures under `tests/fixtures/telegram/` for representative updates (text + voice)

#### Documentation

- [x] Update `README.md` with webhook setup steps:
  - [x] How to set env vars locally
  - [x] How to expose local server for Telegram (e.g., via a tunnel) and set the webhook (via helper endpoint or manual curl)
  - [x] How to run the replay test using a captured fixture payload

---

### 5. Dependencies

- Step 1 backend foundation must be in place (FastAPI app, router aggregation, settings module, tests)
- Telegram Bot created and token available (`TELEGRAM_BOT_TOKEN`)
- A network-accessible base URL for Telegram to reach the webhook in non-local environments (deployment or tunnel URL)
- (Optional for helper endpoint) HTTP client dependency already used in the project test stack (e.g., `httpx`)
- (Future) Supabase persistence feature to replace/augment stub persistence

---

### 6. Definition of Done

- `POST /api/telegram/webhook` exists and responds:
  - With `200` for valid text updates and valid voice updates
  - With `200` for unsupported Telegram message types (ignored gracefully)
- For at least one real Telegram message (text and voice) sent to the bot, the backend logs a structured “received update” line and persists an ingestion event record containing `chat_id`, `message_id`, and either `text_preview` or `telegram_file_id`
- Sending the same Telegram update payload twice (replay) does not create duplicate persisted ingestion events (idempotency by `chat_id:message_id`)
- Tests pass (`pytest -v`) including webhook tests using fixture payloads (no Telegram network calls required)
- README documents how to configure and verify the webhook and how to run the local replay test

---

### 7. Notes

#### Endpoint behavior details

- Security validation (future hardening; not MVP / not in DoD):
  - Optionally configure Telegram `setWebhook.secret_token` and verify inbound `X-Telegram-Bot-Api-Secret-Token`.
  - The env var name previously referenced for this (`TELEGRAM_WEBHOOK_SECRET_TOKEN`) is explicitly out of MVP scope for this spec.
  - Tests for this feature must not depend on secret-token header verification.

#### Idempotency

- Telegram may retry webhook delivery; idempotency must be based on Telegram identifiers.
- Use `chat_id + message_id` as the primary dedupe key (since `message_id` is scoped to a chat).

#### Test strategy

1) End-to-end (real Telegram):
   - Configure the webhook to point at the deployed backend.
   - Send one text message and one voice note to the bot.
   - Verify: 200 responses in server logs (or access logs), structured “received update” logs, and a persisted ingestion event record.

2) Fast local replay (no Telegram calls):
    - Save a real Telegram update JSON payload as a fixture under `tests/fixtures/telegram/`.
    - POST the fixture body to `/api/telegram/webhook` using TestClient.
    - Verify response code, extracted metadata, and dedupe behavior.

#### Open questions (minimal)

- Should we support a polling fallback (getUpdates) for local dev, or webhook-only for MVP?
- Which message types are in-scope for MVP ingestion besides `text` and `voice` (e.g., `audio`, `video_note`, `document`)?
- For persistence “proof”, is file-based JSONL acceptable until Supabase is implemented, or must we block this feature until DB persistence exists?

---

### 8. Execution logs

### Status: APPROVED_BY_USER

- [2026-03-29 12:00] Agent: Planner | Status: completed | Created feature spec for webhook-based Telegram ingestion (endpoints, env vars, idempotency, persistence stub, and test strategy)
- [2026-03-29 12:20] Agent: Planner | Status: completed | Updated spec per user feedback: marked approved, aligned config to existing TELEGRAM_BOT_TOKEN/TELEGRAM_BOT_USER only, and moved webhook secret-token header verification to future hardening (removed from MVP tasks/DoD/tests)
- [2026-03-29 12:25] Agent: Planner | Status: completed | Clarified dependencies and test strategy to avoid any secret-token header reliance
- [2026-03-29 12:35] Agent: Backend | Status: in_progress | Started implementing Telegram webhook ingestion
- [2026-03-29 12:50] Agent: Backend | Status: completed | Implemented webhook controller, ingestion service, JSONL persistence, fixtures, and tests
- [2026-03-29 12:55] Agent: Backend | Status: failed | pytest unavailable in venv (No module named pytest)
- [2026-03-29 12:58] Agent: Backend | Status: in_progress | Fixed unsupported updates to skip JSONL persistence while preserving ignored logs
- [2026-03-29 13:10] Agent: Reviewer | Status: completed | Reviewed Step 2 Telegram ingestion tests/fixtures for DoD and edge cases
- [2026-03-29 13:25] Agent: Backend | Status: in_progress | Hardened webhook tests for invalid JSON, audio fixtures, stored JSONL field assertions, and robust override cleanup
- [2026-03-29 14:05] Agent: Backend | Status: completed | Ran test suite (pytest -v); Telegram webhook ingestion tests passed

- [2026-03-29 14:10] Agent: Planner | Status: in_progress | Changed overall Execution logs status from COMPLETED to AWAITING_USER_ACCEPTANCE because only the user can declare the feature done; implementation checklist remains unchanged pending user sign-off

- [2026-03-29 15:00] Agent: Planner | Status: completed | Option B semantics update: added spec_approved_by_user=true (spec previously approved) and reset approved_by_user=false to represent post-implementation user acceptance only

- [2026-03-29 16:00] Agent: Planner | Status: completed | User tested ngrok successfully and approved the webhook approach; set approved_by_user=true
