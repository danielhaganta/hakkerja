from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_session
from app.main import app


class FakeResult:
    def __init__(self, row: tuple[bool, bool]) -> None:
        self._row = row

    def one(self) -> tuple[bool, bool]:
        return self._row


class FakeSession:
    def __init__(
        self, *, is_available: bool = True, is_installed: bool = True, is_reachable: bool = True
    ) -> None:
        self._row = (is_available, is_installed)
        self._is_reachable = is_reachable

    async def execute(self, *_args: Any) -> FakeResult:
        if not self._is_reachable:
            raise OperationalError("SELECT", {}, Exception("connection refused"))
        return FakeResult(self._row)


def use_session(session: FakeSession) -> None:
    async def override() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_session] = override


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_deep_health_ok_when_pgvector_installed(client: TestClient) -> None:
    use_session(FakeSession())

    response = client.get("/health/deep")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "pgvector": {"available": True, "installed": True},
    }


def test_deep_health_ok_when_pgvector_available_but_not_installed(client: TestClient) -> None:
    use_session(FakeSession(is_installed=False))

    response = client.get("/health/deep")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "pgvector": {"available": True, "installed": False},
    }


def test_deep_health_degraded_when_pgvector_unavailable(client: TestClient) -> None:
    use_session(FakeSession(is_available=False, is_installed=False))

    response = client.get("/health/deep")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "database": "ok",
        "pgvector": {"available": False, "installed": False},
    }


def test_deep_health_degraded_when_db_unreachable(client: TestClient) -> None:
    use_session(FakeSession(is_reachable=False))

    response = client.get("/health/deep")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unreachable", "pgvector": None}
