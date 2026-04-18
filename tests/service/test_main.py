"""Tests for /health and CORS on the FastAPI app."""


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_cors_headers(client):
    resp = client.options(
        "/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    # CORS middleware should reply (may be 200 or 400 depending on FastAPI version,
    # but the access-control-allow-origin header must be present)
    assert "access-control-allow-origin" in resp.headers
