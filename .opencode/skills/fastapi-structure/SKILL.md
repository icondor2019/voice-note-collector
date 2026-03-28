---
name: fastapi-structure
description: Defines the folder structure and organization for a FastAPI project
---

# FastAPI Project Structure

This skill defines how to organize a FastAPI backend using a modular structure.

## Project Structure

project_root/
├── main.py
├── configuration/
│ └── settings.py
├── backend/
│ ├── init.py
│ ├── auth.py
│ ├── models.py
│ ├── controllers/
│ │ ├── init.py
│ │ ├── health_controller.py
│ │ ├── <domain>_controller.py
│ ├── responses/
│ └── utils/
├── tests/
│ └── test_endpoints.py
└── requirements.txt


## Responsibilities

### main.py
- App creation
- Middleware configuration
- Router inclusion
- Lifespan events
- MUST NOT contain endpoint logic

---

### configuration/settings.py
- Environment variables
- Constants
- App configuration

---

### backend/controllers/
- Contains all API endpoints grouped by domain
- Each file represents a feature/domain

---

### backend/models.py
- Pydantic models
- Request/response schemas

---

### backend/responses/
- Structured API responses (optional)

---

### backend/utils/
- Shared utilities
- Helper functions

---

### tests/
- Endpoint and integration tests

---

## Rules

- Keep separation of concerns strict
- Do not mix business logic with controllers
- Keep files modular and focused