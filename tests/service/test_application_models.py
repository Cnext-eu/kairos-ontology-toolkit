"""Tests for the /api/application-models endpoints."""

from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest


SAMPLE_MMD = """\
classDiagram
  class Customer {
    +String name
    +String email
  }
  class Order {
    +String id
    +Date date
  }
  Customer "1" --> "*" Order : places
"""


@pytest.fixture()
def mock_app_model_service(monkeypatch):
    """Patch get_github_service with mocks for application-model functions."""
    m_list = AsyncMock(return_value=[
        {"name": "customer-order.mmd", "path": "application-models/customer-order.mmd", "sha": "aaa", "size": 200},
    ])
    m_read_mmd = AsyncMock(return_value=SAMPLE_MMD)

    fake_gh = SimpleNamespace(
        list_mmd_files=m_list,
        read_mmd_file=m_read_mmd,
    )

    monkeypatch.setattr(
        "service.app.routers.application_models.get_github_service",
        lambda: fake_gh,
    )
    return {"list_mmd_files": m_list, "read_mmd_file": m_read_mmd}


class TestListApplicationModels:
    def test_returns_list(self, client, mock_app_model_service):
        resp = client.get("/api/application-models/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["name"] == "customer-order.mmd"

    def test_passes_repo_headers(self, client, mock_app_model_service):
        client.get(
            "/api/application-models/",
            headers={"X-Kairos-Repo-Owner": "myorg", "X-Kairos-Repo-Name": "myrepo"},
        )
        mock_app_model_service["list_mmd_files"].assert_called_once_with(
            owner="myorg", repo="myrepo"
        )

    def test_empty_when_no_models(self, client, monkeypatch, mock_env):
        from unittest.mock import AsyncMock
        from types import SimpleNamespace

        fake_gh = SimpleNamespace(list_mmd_files=AsyncMock(return_value=[]))
        monkeypatch.setattr(
            "service.app.routers.application_models.get_github_service",
            lambda: fake_gh,
        )
        resp = client.get("/api/application-models/")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetApplicationModel:
    def test_returns_content(self, client, mock_app_model_service):
        resp = client.get("/api/application-models/customer-order")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "customer-order"
        assert "classDiagram" in data["content"]

    def test_passes_name_to_service(self, client, mock_app_model_service):
        client.get("/api/application-models/customer-order")
        mock_app_model_service["read_mmd_file"].assert_called_once_with(
            "customer-order", owner=None, repo=None
        )

    def test_returns_404_on_not_found(self, client, monkeypatch, mock_env):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        async def _raise(*args, **kwargs):
            raise FileNotFoundError("no such file")

        fake_gh = SimpleNamespace(read_mmd_file=_raise)
        monkeypatch.setattr(
            "service.app.routers.application_models.get_github_service",
            lambda: fake_gh,
        )
        resp = client.get("/api/application-models/nonexistent")
        assert resp.status_code == 404

    def test_returns_500_on_unexpected_error(self, client, monkeypatch, mock_env):
        from types import SimpleNamespace

        async def _raise(*args, **kwargs):
            raise RuntimeError("network failure")

        fake_gh = SimpleNamespace(read_mmd_file=_raise)
        monkeypatch.setattr(
            "service.app.routers.application_models.get_github_service",
            lambda: fake_gh,
        )
        resp = client.get("/api/application-models/any")
        assert resp.status_code == 500
