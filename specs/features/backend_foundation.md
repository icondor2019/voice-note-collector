# Feature: backend_foundation

## Objective
Establish a minimal, testable FastAPI backend foundation (app skeleton + configuration + health endpoint) that can be deployed and later extended for Telegram ingestion, transcription, persistence, and a retrieval UI.

---

## Tasks

### Project Structure (FastAPI skeleton)

- [ ] Create `main.py` to instantiate the FastAPI app and include an aggregated API router (no endpoint logic inside `main.py`)
- [ ] Create package `backend/` with `__init__.py`
- [ ] Create `backend/controllers/` package with `__init__.py`
- [ ] Create `backend/controllers/health_controller.py` implementing `GET /api/health` returning a simple healthy payload
- [ ] Create `backend/controllers/__init__.py` router aggregator exporting `api_router` and including `health_controller.router`

### Configuration Management

- [ ] Create `configuration/` package with `__init__.py`
- [ ] Create `configuration/settings.py` using `pydantic-settings` (`BaseSettings`) to load environment variables from `.env`
- [ ] Define settings fields needed by later MVP steps (Telegram, Supabase, transcription), while keeping Step 1 runnable without external credentials (e.g., allow optional values or safe defaults for non-Step-1 keys)
- [ ] Deprecate the current `configurations/settings.py` module (decide: delete or keep as legacy; ensure the backend uses only `configuration/settings.py` going forward)
- [ ] Add `.env.example` documenting all required environment variables and placeholders

### Dependency & Local Run Setup

- [ ] Add/Update `requirements.txt` with runtime dependencies (FastAPI, Uvicorn, pydantic-settings) and test dependencies (pytest, httpx)
- [ ] Update `README.md` with local run instructions (`uvicorn main:app --reload`) and `.env` setup notes

### Testing

- [ ] Create `tests/test_health_endpoint.py` using `fastapi.testclient.TestClient` to assert `GET /api/health` returns HTTP 200 and the expected payload shape

---

## Dependencies

- Python packages: `fastapi`, `uvicorn`, `pydantic-settings`, `pytest`, `httpx`
- A consistent module layout matching the project’s intended FastAPI structure (controllers + router aggregator)

---

## Definition of Done

- `uvicorn main:app --reload` starts successfully with only a `.env` file (or environment) appropriate for Step 1
- `GET /api/health` responds with HTTP 200 and a stable payload (tester can verify)
- `pytest -v` passes locally
- Settings are loaded via `configuration/settings.py` (no import-time crashes; non-Step-1 credentials do not block running health/tests)
- Repository contains `.env.example` listing all environment variables required by later MVP steps

---

## Notes

- Keep Step 1 strictly foundational: no Telegram webhook handling, no DB calls, no transcription calls.
- Avoid side effects at import time in settings (e.g., printing errors or raising immediately); later features can enforce required keys where needed.
- API prefix convention for this project: `/api/...`.
