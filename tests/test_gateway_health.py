from fastapi.testclient import TestClient

from careos.gateway.main import app


client = TestClient(app)


def test_gateway_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "careos-lite-gateway"
