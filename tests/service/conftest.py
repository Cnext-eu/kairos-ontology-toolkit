"""Fixtures for service tests."""

import pytest
from fastapi.testclient import TestClient

# Override settings BEFORE importing app so config picks up test values
_ENV = {
    "KAIROS_GITHUB_APP_ID": "12345",
    "KAIROS_GITHUB_APP_PRIVATE_KEY": "fake-key",
    "KAIROS_GITHUB_INSTALLATION_ID": "67890",
    "KAIROS_GITHUB_REPO_OWNER": "test-org",
    "KAIROS_GITHUB_REPO_NAME": "test-repo",
    "KAIROS_GITHUB_DEFAULT_BRANCH": "main",
    "KAIROS_GITHUB_ONTOLOGIES_PATH": "ontologies",
    "KAIROS_ALLOWED_ORIGINS": "*",
}


SAMPLE_TTL = """\
@prefix : <http://kairos.example/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:TestOntology a owl:Ontology ;
    rdfs:label "Test Ontology"@en .

:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .

:customerName a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Name" .
"""


@pytest.fixture()
def mock_env(monkeypatch):
    """Set env vars for the service config."""
    for k, v in _ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture()
def client(mock_env):
    """Create a TestClient with mocked settings.

    We import *inside* the fixture so monkeypatch env vars take effect.
    """
    # Re-import to pick up patched env
    from service.app.main import app

    return TestClient(app)


@pytest.fixture()
def auth_header():
    return {"Authorization": "Bearer ghp_test_token_12345"}


@pytest.fixture()
def mock_github(monkeypatch):
    """Patch get_github_service to return a mock module with async helpers."""
    from unittest.mock import AsyncMock
    from types import SimpleNamespace

    m_list = AsyncMock(return_value=[
        {"name": "customer.ttl", "path": "ontologies/customer.ttl", "sha": "abc123", "size": 500},
    ])
    m_read = AsyncMock(return_value=SAMPLE_TTL)
    m_branch = AsyncMock(return_value={"ref": "refs/heads/test-branch"})
    m_write = AsyncMock(return_value={"content": {"sha": "new_sha"}})
    m_pr = AsyncMock(return_value={"html_url": "https://github.com/test-org/test-repo/pull/1"})

    fake_gh = SimpleNamespace(
        list_ttl_files=m_list,
        read_file=m_read,
        create_branch=m_branch,
        write_file=m_write,
        create_pull_request=m_pr,
    )

    monkeypatch.setattr("service.app.routers.ontology.get_github_service", lambda: fake_gh)
    monkeypatch.setattr("service.app.routers.validation.get_github_service", lambda: fake_gh)
    monkeypatch.setattr("service.app.routers.projection.get_github_service", lambda: fake_gh)
    monkeypatch.setattr("service.app.routers.chat.get_github_service", lambda: fake_gh)

    yield {
        "list_ttl_files": m_list,
        "read_file": m_read,
        "create_branch": m_branch,
        "write_file": m_write,
        "create_pull_request": m_pr,
    }
