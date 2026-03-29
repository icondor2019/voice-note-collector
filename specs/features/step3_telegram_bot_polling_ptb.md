## 1. Feature: step3_telegram_bot_polling_ptb

### 2. Objective
Add Telegram ingestion via a long-polling worker using `python-telegram-bot` (PTB) so local development can ingest real Telegram messages without webhooks/tunnels, while reusing the existing JSONL persistence + idempotency logic and keeping the FastAPI app for future retrieval/UI.

**Status (as of 2026-03-29): Cancelled / deprioritized.** The user decided to go all-in on the webhook approach; PTB polling will not be pursued for the current MVP.

---

### 3. Approved by user

spec_approved_by_user = false
approved_by_user = true

### 4. Tasks

#### Dependencies & packaging

- [ ] Add `python-telegram-bot` to the project dependencies (pin a compatible major version; ensure it supports `Application` + `run_polling`).
- [ ] Update any dependency docs/lockfiles used by the repo (e.g., `requirements.txt`, `requirements-dev.txt`, etc.) to include PTB consistently.

#### Bot runner (polling worker)

- [ ] Create a polling runner module (choose one location; keep it stable for deploy): e.g., `backend/bot/runner.py`.
- [ ] Implement an entrypoint function (e.g., `main()`), which:
  - [ ] Loads settings via existing `configuration/settings.py`.
  - [ ] Validates `TELEGRAM_BOT_TOKEN` is present; if missing, logs a clear error and exits non-zero.
  - [ ] Builds a PTB `Application` and starts long polling via `run_polling(...)`.
- [ ] Ensure graceful shutdown:
  - [ ] Handle SIGINT/SIGTERM so Railway/local stops do not corrupt ongoing writes.
  - [ ] Ensure the PTB application stops cleanly and flushes logs.
- [ ] Add structured logging for startup/shutdown and per-message handling (never log `TELEGRAM_BOT_TOKEN`).

#### Message handlers (MVP scope)

- [ ] Create a handlers module (e.g., `backend/bot/handlers.py`) containing pure functions that accept PTB `Update`/`Context` (or extracted dicts) and return a normalized ingestion event.
- [ ] Implement handler for text messages:
  - [ ] Extract `chat_id`, `message_id`, `from_user_id`, `message_date`, and a truncated `text_preview`.
- [ ] Implement handler for voice/audio messages:
  - [ ] Support `message.voice` and `message.audio` (at minimum capture `file_id` and `duration_seconds` when present).
- [ ] Unsupported message types:
  - [ ] Log “ignored” with correlation fields and do not persist an ingestion event.

#### Persistence & idempotency (reuse Step 2 JSONL)

- [ ] Reuse the existing JSONL ingestion persistence service from Step 2 (no new store for this step).
- [ ] Reuse/align idempotency key rules with Step 2:
  - [ ] Primary: `chat_id:message_id`.
  - [ ] Fallback: `update_id` if message is absent (should be rare in polling path; still safe).
- [ ] Ensure the polling worker uses the same JSONL output file path default as Step 2 (or clearly document if different), and that duplicates are skipped.
- [ ] Decide and document error behavior for persistence failures in polling mode:
  - [ ] The worker should not crash on a single write error; it should log and continue.

#### Settings constraints & optional allowlist

- [ ] Confirm no new *mandatory* env vars are introduced for polling.
- [ ] (Optional) Implement an allowlist policy using the existing `TELEGRAM_BOT_USER` setting:
  - [ ] If `TELEGRAM_BOT_USER` is set, only process messages from that username (or log and ignore others).
  - [ ] If unset, process all incoming messages (single-user assumption).
  - [ ] Document this behavior.

#### Webhook endpoint status (explicit decision)

- [ ] Keep the existing webhook endpoint (`POST /api/telegram/webhook`) as **legacy/optional** for deployed environments.
- [ ] Update documentation to mark webhook ingestion as deprecated for local dev, and polling as the recommended local workflow.
- [ ] Ensure no code is removed in this step; webhook tests remain as-is unless they require updates due to shared persistence changes.

#### Documentation (local run + Railway deploy)

- [ ] Update `README.md` with local polling workflow:
  - [ ] Set `TELEGRAM_BOT_TOKEN` (and optionally `TELEGRAM_BOT_USER`).
  - [ ] Start the polling worker (explicit command, e.g., `python -m backend.bot.runner`).
  - [ ] Send a real text message and a real voice note/audio to the bot.
  - [ ] Verify the JSONL file contains appended ingestion events and dedupe works when re-sending the same message (where possible).
- [ ] Add Railway deployment guidance:
  - [ ] Document that polling should run as a separate **worker** service/process from the FastAPI web service.
  - [ ] Provide the expected Railway start command for the worker (e.g., `python -m backend.bot.runner`).
  - [ ] Clarify that the FastAPI service remains for future retrieval/UI and can be deployed separately.

#### Testing

- [ ] Add unit tests for polling handlers without Telegram network calls:
  - [ ] Build `Update` objects using `Update.de_json(<fixture_dict>, bot)` or by constructing minimal PTB objects needed.
  - [ ] Add fixtures (dict JSON) for at least: text message update, voice message update, audio message update, unsupported type.
  - [ ] Assert normalized ingestion event fields match expectations.
- [ ] Add tests covering JSONL persistence integration from the handler path:
  - [ ] When called twice with the same `chat_id:message_id`, only one line is written.
  - [ ] Unsupported messages do not write.
- [ ] (Optional manual E2E) Document a manual verification checklist for `run_polling` (no automation required).

---

### 5. Dependencies

- Step 2 JSONL ingestion persistence + idempotency logic must exist and be reusable by the polling worker.
- Existing settings keys are available:
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_BOT_USER` (optional allowlist behavior)
- Existing FastAPI app remains in the repo (no changes required beyond docs/clarifications).
- PTB library (`python-telegram-bot`) added to dependencies.

---

### 6. Definition of Done

- A PTB long-polling worker entrypoint exists and can be started locally with a documented command.
- Sending a real Telegram **text** message to the bot while the worker is running results in exactly one persisted JSONL ingestion event with `chat_id`, `message_id`, and `text_preview`.
- Sending a real Telegram **voice** (or audio) message results in exactly one persisted JSONL ingestion event with `chat_id`, `message_id`, and `telegram_file_id` (plus duration when available).
- Idempotency works: processing the same update twice (via unit test replay) does not create duplicate JSONL lines (dedupe key `chat_id:message_id`).
- Unit tests pass (`pytest`) and do not hit Telegram network.
- README documents:
  - Local polling usage (no webhook/ngrok)
  - Where the JSONL file is written and how to inspect it
  - Railway worker deployment command and the separation from the FastAPI service
- Existing webhook endpoint is explicitly documented as legacy/optional (not removed).

---

### 7. Notes

- This spec is **cancelled/deprioritized** in favor of the webhook-based Telegram ingestion approach (per user decision). Do not implement PTB polling unless the roadmap changes.
- Scope for this step is ingestion + persistence only (no transcription download required unless already part of the JSONL event schema).
- PTB version choice matters (v20+ uses asyncio and `Application`); pin the dependency to avoid breaking API changes.
- Polling vs webhook coexistence:
  - Running both simultaneously may cause double-processing if both receive the same messages (depending on webhook configuration). Documentation should recommend using **either** polling (local/dev) **or** webhook (production/legacy), not both.
- Allowlist: Prefer using existing `TELEGRAM_BOT_USER` as an optional single-user guard; do not introduce new mandatory env vars.
- Logging must avoid secrets; never print the bot token.

---

### 8. Execution logs

- [2026-03-29 00:00] Agent: Planner | Status: completed | Created feature spec for Telegram ingestion via PTB long polling worker, including handler tasks, JSONL reuse, webhook legacy status, testing strategy, and local/Railway run documentation
- [2026-03-29 00:01] Agent: Planner | Status: cancelled | User decision: deprioritize PTB polling and proceed with webhook-only Telegram ingestion approach for MVP; spec retained for reference
