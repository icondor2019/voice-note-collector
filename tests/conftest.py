import os
import sys

import pytest

ROOT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_PATH not in sys.path:
    sys.path.insert(0, ROOT_PATH)

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("TELEGRAM_ALLOWED_USER_ID", "123")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
