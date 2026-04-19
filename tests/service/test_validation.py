"""Tests for the validation router (/api/validate)."""

from .conftest import SAMPLE_TTL


class TestValidateDomain:
    def test_validate_domain(self, client, auth_header, mock_github):
        resp = client.post(
            "/api/validate",
            headers=auth_header,
            json={"domain": "customer"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["syntax"]["passed"] is True

    def test_validate_domain_missing_auth(self, client, mock_github):
        """Auth is optional for reads — validation works without Authorization header."""
        resp = client.post("/api/validate", json={"domain": "customer"})
        assert resp.status_code == 200


class TestValidateContent:
    def test_validate_raw_content(self, client):
        resp = client.post(
            "/api/validate/content",
            json={"ontology_content": SAMPLE_TTL},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["syntax"]["passed"] is True

    def test_validate_invalid_content(self, client):
        resp = client.post(
            "/api/validate/content",
            json={"ontology_content": "this is not valid turtle at all"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["syntax"]["passed"] is False
