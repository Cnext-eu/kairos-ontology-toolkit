"""Tests for the new guided-workflow tools (scaffold_hub, create_domain, explain, suggest)."""

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Stub copilot SDK types so tests run without the real SDK installed
# ---------------------------------------------------------------------------
def _stub_init(self, **kw):
    for k, v in kw.items():
        setattr(self, k, v)


_copilot_tools_mod = SimpleNamespace(
    Tool=type("Tool", (), {"__init__": _stub_init}),
    ToolInvocation=type("ToolInvocation", (), {}),
    ToolResult=type("ToolResult", (), {"__init__": _stub_init}),
)
_copilot_mod = SimpleNamespace()
sys.modules.setdefault("copilot", _copilot_mod)
sys.modules.setdefault("copilot.tools", _copilot_tools_mod)


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

SAMPLE_INCOMPLETE_TTL = """\
@prefix : <http://kairos.example/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:TestOntology a owl:Ontology ;
    rdfs:label "Incomplete Ontology"@en .

:Widget a owl:Class .

:Gadget a owl:Class ;
    rdfs:label "Gadget" ;
    rdfs:comment "A gadget" .
"""


def _make_invocation(arguments: dict):
    inv = _copilot_tools_mod.ToolInvocation()
    inv.arguments = arguments
    return inv


@pytest.fixture()
def mock_gh(monkeypatch):
    """Patch github_service used by copilot_tools."""
    settings = SimpleNamespace(github_ontologies_path="ontologies")
    m_list = AsyncMock(return_value=[
        {"name": "customer.ttl", "path": "ontologies/customer.ttl", "sha": "abc", "size": 500},
    ])
    m_read = AsyncMock(return_value=SAMPLE_TTL)
    m_branch = AsyncMock(return_value={"ref": "refs/heads/test-branch"})
    m_write = AsyncMock(return_value={"content": {"sha": "new_sha"}})
    m_pr = AsyncMock(return_value={"html_url": "https://github.com/org/repo/pull/42"})

    monkeypatch.setattr(
        "service.app.services.copilot_tools.gh.settings", settings
    )
    monkeypatch.setattr(
        "service.app.services.copilot_tools.gh.list_ttl_files", m_list
    )
    monkeypatch.setattr(
        "service.app.services.copilot_tools.gh.read_file", m_read
    )
    monkeypatch.setattr(
        "service.app.services.copilot_tools.gh.create_branch", m_branch
    )
    monkeypatch.setattr(
        "service.app.services.copilot_tools.gh.write_file", m_write
    )
    monkeypatch.setattr(
        "service.app.services.copilot_tools.gh.create_pull_request", m_pr
    )
    return {
        "list_ttl_files": m_list,
        "read_file": m_read,
        "create_branch": m_branch,
        "write_file": m_write,
        "create_pull_request": m_pr,
    }


@pytest.fixture()
def tools(mock_gh):
    from service.app.services.copilot_tools import make_tools
    return {t.name: t for t in make_tools("ghp_fake")}


# ---------------------------------------------------------------------------
# scaffold_hub
# ---------------------------------------------------------------------------
class TestScaffoldHub:
    @pytest.mark.asyncio
    async def test_scaffold_creates_branch_and_pr(self, tools, mock_gh):
        inv = _make_invocation({
            "domain_name": "inventory",
            "description": "Inventory management domain",
        })
        result = await tools["scaffold_hub"].handler(inv)
        assert result.result_type == "success"
        data = json.loads(result.text_result_for_llm)
        assert "branch" in data
        assert "pull_request" in data
        assert "ontologies/inventory.ttl" in data["files_created"]
        assert "shapes/inventory.shacl.ttl" in data["files_created"]
        mock_gh["create_branch"].assert_awaited_once()
        assert mock_gh["write_file"].await_count == 2
        mock_gh["create_pull_request"].assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scaffold_custom_namespace(self, tools, mock_gh):
        inv = _make_invocation({
            "domain_name": "sales",
            "description": "Sales domain",
            "namespace": "http://custom.example/sales#",
        })
        result = await tools["scaffold_hub"].handler(inv)
        assert result.result_type == "success"
        # The write_file call content should contain our namespace
        written_content = mock_gh["write_file"].call_args_list[0].args[2]
        assert "http://custom.example/sales#" in written_content


# ---------------------------------------------------------------------------
# create_domain
# ---------------------------------------------------------------------------
class TestCreateDomain:
    @pytest.mark.asyncio
    async def test_create_domain_generates_valid_ttl(self, tools, mock_gh):
        inv = _make_invocation({
            "domain_name": "product",
            "description": "Product catalog domain",
            "classes": [
                {
                    "name": "Product",
                    "label": "Product",
                    "comment": "A sellable product",
                    "properties": [
                        {"name": "productName", "range": "xsd:string", "label": "Product Name"},
                        {"name": "price", "range": "xsd:decimal", "label": "Price"},
                    ],
                },
            ],
        })
        result = await tools["create_domain"].handler(inv)
        assert result.result_type == "success"
        data = json.loads(result.text_result_for_llm)
        assert data["domain"] == "product"
        assert data["class_count"] == 1
        assert data["validation"]["syntax"]["passed"] is True
        assert "Product" in data["ttl_content"]
        assert "productName" in data["ttl_content"]

    @pytest.mark.asyncio
    async def test_create_domain_multiple_classes(self, tools, mock_gh):
        inv = _make_invocation({
            "domain_name": "order",
            "description": "Order processing",
            "classes": [
                {
                    "name": "Order",
                    "label": "Order",
                    "comment": "A purchase order",
                    "properties": [
                        {"name": "orderDate", "range": "xsd:dateTime", "label": "Order Date"},
                    ],
                },
                {
                    "name": "LineItem",
                    "label": "Line Item",
                    "comment": "A line in an order",
                    "superclass": "Order",
                    "properties": [
                        {"name": "quantity", "range": "xsd:integer", "label": "Quantity"},
                    ],
                },
            ],
        })
        result = await tools["create_domain"].handler(inv)
        data = json.loads(result.text_result_for_llm)
        assert data["class_count"] == 2
        assert "LineItem" in data["ttl_content"]
        assert "rdfs:subClassOf" in data["ttl_content"]

    @pytest.mark.asyncio
    async def test_create_domain_does_not_write(self, tools, mock_gh):
        """create_domain should NOT call write_file."""
        inv = _make_invocation({
            "domain_name": "test",
            "description": "Test",
            "classes": [{"name": "X", "label": "X", "comment": "X", "properties": []}],
        })
        await tools["create_domain"].handler(inv)
        mock_gh["write_file"].assert_not_awaited()


# ---------------------------------------------------------------------------
# explain_ontology
# ---------------------------------------------------------------------------
class TestExplainOntology:
    @pytest.mark.asyncio
    async def test_explain_returns_summary(self, tools, mock_gh):
        inv = _make_invocation({"domain": "customer"})
        result = await tools["explain_ontology"].handler(inv)
        assert result.result_type == "success"
        data = json.loads(result.text_result_for_llm)
        assert data["domain"] == "customer"
        assert "1 class" in data["summary"]
        assert len(data["classes"]) == 1
        assert data["classes"][0]["name"] == "Customer"

    @pytest.mark.asyncio
    async def test_explain_shows_properties(self, tools, mock_gh):
        inv = _make_invocation({"domain": "customer"})
        result = await tools["explain_ontology"].handler(inv)
        data = json.loads(result.text_result_for_llm)
        props = data["classes"][0]["properties"]
        assert any(p["name"] == "customerName" for p in props)


# ---------------------------------------------------------------------------
# suggest_improvements
# ---------------------------------------------------------------------------
class TestSuggestImprovements:
    @pytest.mark.asyncio
    async def test_suggest_returns_suggestions(self, tools, mock_gh):
        inv = _make_invocation({"domain": "customer"})
        result = await tools["suggest_improvements"].handler(inv)
        assert result.result_type == "success"
        data = json.loads(result.text_result_for_llm)
        assert data["domain"] == "customer"
        assert data["suggestion_count"] > 0
        types = [s["type"] for s in data["suggestions"]]
        assert "shacl_shapes" in types

    @pytest.mark.asyncio
    async def test_suggest_finds_missing_labels(self, tools, mock_gh):
        """An incomplete ontology should trigger missing_label and missing_comment."""
        mock_gh["read_file"].return_value = SAMPLE_INCOMPLETE_TTL
        inv = _make_invocation({"domain": "incomplete"})
        result = await tools["suggest_improvements"].handler(inv)
        data = json.loads(result.text_result_for_llm)
        types = [s["type"] for s in data["suggestions"]]
        assert "missing_label" in types or "missing_comment" in types

    @pytest.mark.asyncio
    async def test_suggest_skip_permission(self, tools):
        """suggest_improvements should have skip_permission=True."""
        assert tools["suggest_improvements"].skip_permission is True

    @pytest.mark.asyncio
    async def test_explain_skip_permission(self, tools):
        assert tools["explain_ontology"].skip_permission is True

    @pytest.mark.asyncio
    async def test_create_domain_skip_permission(self, tools):
        assert tools["create_domain"].skip_permission is True
