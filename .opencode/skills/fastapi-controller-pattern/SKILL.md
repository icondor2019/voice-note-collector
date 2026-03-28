---
name: fastapi-controller-pattern
description: Defines how to implement controllers using APIRouter and an aggregator pattern
---

# FastAPI Controller Pattern

This skill defines how to structure API endpoints using APIRouter.

---

## Controller File Pattern

Each controller must define a router:

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/example", tags=["Example"])
```

## Rules

File name: <domain>_controller.py
Use APIRouter, NOT app
Always define prefix and tags
Keep endpoints grouped by domain

Example:
``` python
from fastapi import APIRouter

router = APIRouter(prefix="/api/example", tags=["Example"])


@router.get("")
async def list_items():
    return {"data": []}
```

### health_controller (requiered)
```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/health", tags=["Health"])


@router.get("")
async def health_check():
    return {"status": "healthy"}
```

## Router Aggregator Pattern

All routers must be aggregated in this path:
backend/controllers/__init__.py

```python
from fastapi import APIRouter
from backend.controllers.health_controller import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
```

## Rules
- Import each router with alias
- Create a single api_router
- Include all routers
- Export ONLY api_router

## main.py Integration
```python
from backend.controllers import api_router

app.include_router(api_router)
```

## Grouping Guidelines
- Group by domain (users, notes, sources)
- Separate domains that grow independently
- Keep auth endpoints together