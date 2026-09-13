# Architecture

## Backend
- FastAPI

## DB
- Supabase (PostgreSQL)

## Ingestion
- Telegram webhook

## Transcription
- Groq Whisper

## Frontend
- Server-rendered Jinja templates with locally bundled HTMX, CSS, and JavaScript
- Responsive web library served by the FastAPI monolith
- Supabase email/password authentication restricted to one configured user

### Local UI preview authentication bypass

For local visual testing, `WEB_AUTH_DISABLED` defaults to `true` in this
development branch. The login form then accepts any values and uses
deterministic preview cookies without contacting Supabase. The guard rejects
the bypass whenever `ENVIRONMENT` is `prod` or `production`, so it cannot
disable authentication in Railway production. Revert by setting
`WEB_AUTH_DISABLED=false` (and restarting the server) once Supabase login is
ready.
