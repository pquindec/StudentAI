import pytest
from fastapi.testclient import TestClient

from app.core.security import TokenAuthMiddleware


def test_without_token_is_401(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("header", ["Bearer wrong", "bearer x", "", "Basic abc"])
def test_wrong_token_is_401(client: TestClient, header: str) -> None:
    assert client.get("/api/v1/health", headers={"Authorization": header}).status_code == 401


def test_valid_token_is_200(client: TestClient, auth: dict[str, str]) -> None:
    r = client.get("/api/v1/health", headers=auth)
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "0.1.0", "schema_version": 1}


def test_unknown_route_also_requires_token(client: TestClient) -> None:
    assert client.get("/api/v1/does-not-exist").status_code == 401


def test_docs_disabled(client: TestClient, auth: dict[str, str]) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path, headers=auth).status_code == 404


def test_short_token_rejected() -> None:
    with pytest.raises(ValueError):
        TokenAuthMiddleware(app=None, token="short")  # type: ignore[arg-type]  # noqa: S106
