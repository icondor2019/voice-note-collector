Testing Strategy

Goals
-----

- Fast feedback for regressions during development
- Confidence on webhook handling, idempotency, and persistence rules

Test types
----------

- Unit tests
  - Target: services and repositories in isolation
  - Use pytest and small fixtures/mocks for external clients (Supabase client, HTTP client for Telegram file download)

- Integration tests
  - Target: controller + service + repository wiring using TestClient and a test database or a lightweight Supabase test instance.
  - Use a disposable schema or transactions to reset DB state between tests.

- Replay tests / fixtures
  - Store representative Telegram Update JSON fixtures under tests/fixtures/telegram/.
  - Include voice note variations (voice, audio, different mime types) and edge cases (missing fields).

Patterns and tools
------------------

- Pytest with TestClient for endpoint tests.
- Use VCR-like approach or requests-mock for HTTP interactions with Telegram (file download); prefer to stub out HTTP calls in unit tests and run a small integration test that uses recorded responses.
- Fixtures:
  - settings_override: inject a Test Settings object. For Step 2 tests the JSONL sink path MUST be overridden by passing a path or FileSink into the JSONL writer via constructor/parameter (do NOT rely on environment variables to change path in tests).
  - repository_override: inject an in-memory or file-backed repository for Step 2 tests (do not require DATABASE_URL/Supabase in unit tests).
  - supabase_client_mock: optional lightweight mock (for future/integration tests when Supabase is used).
  - telegram_update_fixture(file_name): loads JSON from tests/fixtures/telegram/...

Idempotency testing
-------------------

- Tests should assert that processing the same Update twice results in only one persisted voice note (repository count remains 1) and a deterministic response for second request (e.g., 200 OK but logged as duplicate).

CI notes
--------

- Run unit tests in CI with environment variables set from CI secrets (only non-sensitive values should be required; sensitive keys can be mocked).
