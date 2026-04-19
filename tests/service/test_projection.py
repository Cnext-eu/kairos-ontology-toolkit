"""Tests for the projection router (/api/project)."""


class TestListTargets:
    def test_list_targets(self, client):
        resp = client.get("/api/project/targets")
        assert resp.status_code == 200
        targets = resp.json()["targets"]
        assert "dbt" in targets
        assert "neo4j" in targets
        assert "prompt" in targets


class TestGenerateProjection:
    def test_project_all_targets(self, client, auth_header, mock_github):
        resp = client.post(
            "/api/project",
            headers=auth_header,
            json={"domain": "customer"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["domain"] == "customer"
        assert "targets" in body
        # Should have results for all targets
        assert len(body["targets"]) > 0

    def test_project_specific_target(self, client, auth_header, mock_github):
        resp = client.post(
            "/api/project",
            headers=auth_header,
            json={"domain": "customer", "targets": ["prompt"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "targets" in body

    def test_project_missing_auth(self, client, mock_github):
        """Auth is optional for reads — projection works without Authorization header."""
        resp = client.post("/api/project", json={"domain": "customer"})
        assert resp.status_code == 200
