import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


# psycopg async cannot run on Windows' default ProactorEventLoop.
@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        yield client
