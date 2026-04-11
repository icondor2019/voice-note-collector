---
name: api-security
description: Defines how to secure API endpoints in this project — webhook validation, REST API key protection, and environment-aware guards
---

# API Security

## 1. Overview

This project uses a **two-layer security model**:

- **External webhook endpoints** — called by third-party services (e.g. Telegram). Each service uses its own service-specific secret header validated on arrival.
- **Internal REST endpoints** — called by trusted clients (your own tools, scripts, dashboards). Protected by a shared `X-API-Key` header.

All security dependencies live in `backend/utils/security.py` — single source of truth. Guards are environment-aware: permissive locally, enforced in production via startup validation.

---

## 2. When to Load This Skill

Load this skill when:

- Adding a new API endpoint (any controller)
- Adding a new external-facing webhook (e.g. new bot integrations)
- Modifying existing security dependencies
- Writing tests for any protected endpoint
- Reviewing settings or environment configuration for prod

---

## 3. Endpoint Classification

### External endpoints
Called by third-party services (e.g. Telegram, future webhooks):

- Must use a **service-specific secret header** (e.g. `X-Telegram-Bot-Api-Secret-Token`)
- Guard lives in `backend/utils/security.py` as a named dependency (e.g. `verify_telegram_secret`)
- Returns **403** on failure

### Internal REST endpoints
Called by trusted clients (your own tools, scripts, dashboards):

- Must use the **`X-API-Key` header**
- Guard lives in `backend/utils/security.py` as `verify_api_key`
- Returns **401** on failure

### Always unprotected
Health check `/api/health`:

- **Never add auth to health** — Railway and monitoring tools need it unauthenticated

---

## 4. How to Wire Security

### Router-level (preferred — protects all routes in one line)

```python
from fastapi import APIRouter, Depends
from backend.utils.security import verify_api_key

router = APIRouter(
    prefix="/api/my-domain",
    tags=["My Domain"],
    dependencies=[Depends(verify_api_key)],
)
```

### Per-route (for mixed endpoints — some protected, some not)

```python
@router.get("/protected", dependencies=[Depends(verify_api_key)])
async def protected_route():
    ...

@router.get("/public")
async def public_route():
    ...
```

### Webhook (external secret per service)

```python
from backend.utils.security import verify_telegram_secret

@router.post("/webhook", dependencies=[Depends(verify_telegram_secret)])
async def webhook(...):
    ...
```

---

## 5. Adding a New Security Guard (for new external services)

When a new external webhook is added (e.g. WhatsApp, Slack):

1. Add the secret as `Optional[str] = None` in `configuration/settings.py`
2. Add it to `validate_config()` required list when `ENVIRONMENT == "prod"`
3. Add it to `.env.example` with a comment
4. Create a new `verify_<service>_secret` async dependency in `backend/utils/security.py`
5. Wire it via `Depends()` on the relevant endpoint
6. Write tests for:
   - Correct secret → passes
   - Wrong secret → 403
   - Missing secret → 403
   - Not configured → passes (permissive fallback)

---

## 6. Environment-Aware Guards (Permissive Fallback)

Guards use a **permissive fallback** pattern: when the env var is `None`, validation is skipped. This is intentional:

- Local dev works without any secrets configured
- Production enforces secrets via `validate_config()` which runs on startup
- **Never hard-code a fallback secret value** — `None` means "not configured"

```python
async def verify_api_key(request: Request) -> None:
    if settings.API_KEY is None:
        logger.debug("api.key.skip")  # local dev — permissive
        return
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != settings.API_KEY:
        logger.warning("api.key.invalid")
        raise HTTPException(status_code=401, detail="Invalid API key")
```

---

## 7. Production Checklist

Before any prod deployment, verify:

- [ ] `ENVIRONMENT=prod` is set
- [ ] `SECRET_KEY` is set (required, no default)
- [ ] `API_KEY` is set (enforced by `validate_config` in prod)
- [ ] `TELEGRAM_WEBHOOK_SECRET` is set (enforced by `validate_config` in prod)
- [ ] `/docs`, `/redoc`, `/openapi.json` return 404 (automatic when `ENVIRONMENT=prod`)
- [ ] `/api/health` returns 200 without any headers
- [ ] New endpoint has been classified (external or internal) and guarded accordingly

---

## 8. Recommendations

- Keep all security dependencies in `backend/utils/security.py` — single source of truth
- Use router-level `dependencies=[]` over per-route when all routes in a controller share the same protection
- Use loguru for all security logging — `logger.warning` on failures, `logger.debug` on skips
- Never log the actual secret or API key values
- Rotate secrets without code changes — they live only in env vars

---

## 9. Future Approach — JWT

The project already has JWT-related settings (`SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`) but JWT is not yet implemented. When the project grows to support multiple users or a frontend:

- Replace or augment `verify_api_key` with Bearer JWT validation
- The `SECRET_KEY` is already reserved for this purpose
- JWT would allow per-user tokens, expiration, and revocation — not possible with a shared API key
- The `backend/utils/security.py` file is the right place to add `verify_jwt_token` when the time comes
- Existing `verify_api_key` can remain for service-to-service calls (scripts, internal tools)
