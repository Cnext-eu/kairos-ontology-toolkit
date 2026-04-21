# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the ontology CRUD router (/api/ontology)."""



class TestQueryOntology:
    def test_query_all(self, client, auth_header, mock_github):
        resp = client.get("/api/ontology/query", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["domain"] == "customer.ttl"
        assert any(c["name"] == "Customer" for c in data[0]["classes"])

    def test_query_with_domain_filter(self, client, auth_header, mock_github):
        resp = client.get("/api/ontology/query?domain=customer", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

    def test_query_with_search(self, client, auth_header, mock_github):
        resp = client.get("/api/ontology/query?search=Customer", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        classes = data[0]["classes"]
        assert len(classes) >= 1
        assert classes[0]["name"] == "Customer"

    def test_query_search_no_match(self, client, auth_header, mock_github):
        resp = client.get("/api/ontology/query?search=NonExistent", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["classes"] == []

    def test_query_missing_auth(self, client, mock_github):
        """Auth is optional for reads — query works without Authorization header."""
        resp = client.get("/api/ontology/query")
        assert resp.status_code == 200


class TestProposeChange:
    def test_add_class(self, client, auth_header, mock_github):
        resp = client.post(
            "/api/ontology/change",
            headers=auth_header,
            json={
                "domain": "customer",
                "action": "add_class",
                "details": {"class_name": "VIPCustomer", "label": "VIP Customer"},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "diff" in body
        assert "new_content" in body
        assert "VIPCustomer" in body["new_content"]

    def test_remove_class(self, client, auth_header, mock_github):
        resp = client.post(
            "/api/ontology/change",
            headers=auth_header,
            json={
                "domain": "customer",
                "action": "remove_class",
                "details": {"class_name": "Customer"},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "diff" in body

    def test_unknown_action(self, client, auth_header, mock_github):
        resp = client.post(
            "/api/ontology/change",
            headers=auth_header,
            json={
                "domain": "customer",
                "action": "drop_table",
                "details": {},
            },
        )
        assert resp.status_code == 400


class TestApplyChange:
    def test_apply(self, client, auth_header, mock_github):
        resp = client.post(
            "/api/ontology/apply",
            headers=auth_header,
            json={
                "domain": "customer",
                "new_content": "# new ttl content",
                "message": "test commit",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "branch" in body
        assert body["pull_request"] == "https://github.com/test-org/test-repo/pull/1"
        mock_github["create_branch"].assert_awaited_once()
        mock_github["write_file"].assert_awaited_once()
        mock_github["create_pull_request"].assert_awaited_once()
