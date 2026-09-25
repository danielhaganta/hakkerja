from fastapi.testclient import TestClient


def test_deep_health_reaches_real_database(client: TestClient) -> None:
    response = client.get("/health/deep")

    assert response.status_code == 200
    assert response.json()["pgvector"]["available"] is True
