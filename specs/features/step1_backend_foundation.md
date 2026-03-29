## 1. Feature: step1_backend_foundation

### 2. Objective
Establish a runnable, testable FastAPI backend baseline that later steps can extend (Telegram ingestion, transcription, Supabase persistence, retrieval UI).

---

### 3. Approved by user

approved_by_user = true

### 4. Tasks

#### Goals
- Run the backend locally with a single command.
- Provide a stable health endpoint for smoke checks and deployment readiness.
- Introduce a centralized settings module that can later carry Telegram/Supabase/Groq config **without** making Step 1 depend on those credentials.
- Provide a minimal automated test suite foundation.

#### In scope
- FastAPI app entrypoint (`main.py`) that wires routers (no business logic).
- Router aggregator pattern (single `api_router`).
- `GET /api/health` returning HTTP 200 with a stable payload.
- Settings module using `pydantic-settings` (loads `.env` if present; safe defaults).
- `.env.example` capturing the env vars intended for later steps.
- `pytest` test verifying the health endpoint.
- Minimal run instructions in `README.md`.

#### Out of scope (explicitly NOT in Step 1)
- Telegram webhook endpoints and message handling
- `/source` command handling / source activation
- Audio download and Groq transcription
- Supabase integration, schema, migrations, persistence
- Retrieval API for voice notes/sources
- Web UI

### 5. Dependencies
- Python: `fastapi`, `uvicorn`, `pydantic-settings`
- Tests: `pytest`, `httpx`

#### User stories
1. As a developer, I can start the API and hit `/api/health` to confirm it’s running.
2. As a developer, I can run tests locally without external credentials.
3. As a future implementer, I have an agreed router + settings structure to plug features into.

### 6. Definition of Done
- `uvicorn main:app --reload` starts successfully.
- `GET /api/health` returns 200 and a stable JSON payload (e.g. `{ "status": "ok" }`).
- `pytest -v` passes.
- Settings are centralized (no import-time crashes if Telegram/Supabase/Groq env vars are missing).
- `.env.example` exists and documents planned env vars.

#### Implementation checklist (ordered)
1. Add FastAPI entrypoint `main.py` that creates the app and includes an aggregated API router.
2. Create `backend/controllers` router aggregator exporting `api_router`.
3. Implement `backend/controllers/health_controller.py` with `GET /api/health`.
4. Add `configuration/settings.py` using `pydantic-settings` and loading `.env`.
5. Add `.env.example` (include placeholders for Telegram/Supabase/Groq for later steps).
6. Ensure dependencies exist in `requirements.txt` (runtime + test).
7. Update `README.md` with local run + test commands.
8. Add `tests/test_health_endpoint.py` validating `/api/health`.

### 7. Notes
- Keep Step 1 fully local and service-independent.
- Step 2 will introduce Telegram webhook + `/source` switching.

---

### 8. Execution logs

- [2026-03-29 00:00] Agent: Planner | Status: completed | User approved; normalized spec format to required sections (1-8) without changing intent/tasks
