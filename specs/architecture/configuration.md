Configuration and Settings

Principles
----------

- Use Pydantic BaseSettings to centralize configuration.
- Load from environment variables in production; allow .env files during local development.
- Keep defaults safe and minimal; do not embed secrets in code.

Required settings (MVP)
-----------------------

- TELEGRAM_BOT_TOKEN: str
  - Description: API token for the Telegram bot. Required for any operation that needs to call Telegram APIs (downloading files, etc.).

- TELEGRAM_BOT_USER: str
  - Description: Bot username (without @). Used for basic verification and logging.

Notes on other settings
-----------------------

- For Step 2 (MVP) we intentionally exclude DATABASE_URL, SUPABASE_*, JSONL_SINK_PATH, and other persistence-related environment variables from the required settings in this spec. Persistence targets and credentials are considered out-of-scope for Step 2 and will be added in future architecture decisions. Implementations for Step 2 should use constructor injection or test fixtures to provide alternate persistence (file-backed or in-memory) and the JSONL sink path.

Suggested Settings file (src/app/settings.py) — minimal for Step 2
-----------------------------------------------------------------

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_BOT_USER: str
    # For Step 2 (MVP) do not add DATABASE_URL, SUPABASE_*, or JSONL_SINK_PATH here.
    WEBHOOK_SECRET_TOKEN: Optional[str] = None  # future hardening; not required for MVP

    class Config:
        env_file = ".env"

Security notes
--------------

- Only TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_USER are permitted Telegram-specific settings in the Step 2 MVP. Do not add provider-specific toggles without an explicit decision.
- Webhook secret-token verification (e.g., custom header, HMAC) is recommended for production and is documented as WEBHOOK_SECRET_TOKEN; it's out of scope for Step 2 but should be implemented before public deployment.

Runtime behavior
----------------

- Settings are initialized once in app factory and injected where needed (pass Settings instance into services or use dependency injection via FastAPI dependency).
