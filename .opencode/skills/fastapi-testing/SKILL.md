---
name: fastapi-testing
description: Defines how to test FastAPI endpoints using pytest and TestClient
---

# FastAPI Testing

This skill defines how to write tests for FastAPI applications.

---

## Setup

Use FastAPI TestClient:

```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
```

Example Test
```python
def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
```

### Test Structure
- Group tests by domain
- Use classes for organization

```python
class TestHealthEndpoints:
    def test_health_check(self):
        ...
```

### Testing Protected Routes
```python

import pytest

@pytest.mark.parametrize("method,path", [
    ("GET", "/api/user/profile"),
])
def test_requires_auth(method, path):
    response = client.request(method, path)
    assert response.status_code in (401, 403)
```

### Rules
- Do not require running server
- Use TestClient only
- Cover:
  - happy path
  - authentication
  - edge cases

### Running Tests
pytest tests/ -v

### Dependencies
pytest>=8.0.0
httpx>=0.27.0

---