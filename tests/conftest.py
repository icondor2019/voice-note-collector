import os
import sys

import pytest

ROOT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_PATH not in sys.path:
    sys.path.insert(0, ROOT_PATH)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
