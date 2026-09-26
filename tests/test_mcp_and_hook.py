# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The MCP server serves the closure; the read hook makes a raw read self-correcting (DD-245)."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.hook import read_context
from kairos_ontology.cli.main import cli

_PRODUCT_HUB = Path(__file__).parent / "scenarios" / "v5-product-hub"

BASE = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix base: <urn:base#> .

<urn:base> a owl:Ontology ; rdfs:label "Base" .
base:Party a owl:Class ; rdfs:label "Party" .
base:name a owl:DatatypeProperty ; rdfs:domain base:Party ; rdfs:range xsd:string .
base:email a owl:DatatypeProperty ; rdfs:domain base:Party ; rdfs:range xsd:string .
"""

CUSTOMER = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix base: <urn:base#> .
@prefix : <urn:customer#> .

<urn:customer> a owl:Ontology ; rdfs:label "Customer" ; owl:imports <urn:base> .
:Customer a owl:Class ; rdfs:label "Customer" ; rdfs:subClassOf base:Party .
:Lead a owl:Class ; rdfs:label "Lead" .
"""


@pytest.fixture
def closure_hub(tmp_path: Path) -> Path:
    root = tmp_path / "ontology-hub"
    (root / "refmodels").mkdir(parents=True)
    (root / "model" / "ontologies").mkdir(parents=True)
    (root / "integration").mkdir()
    (root / "refmodels" / "base.ttl").write_text(BASE, encoding="utf-8")
    (root / "model" / "ontologies" / "customer.ttl").write_text(CUSTOMER, encoding="utf-8")
    (root / "catalog-v001.xml").write_text(
        '<?xml version="1.0"?>\n<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        '  <uri name="urn:base" uri="refmodels/base.ttl"/>\n</catalog>\n',
        encoding="utf-8",
    )
    return root


class TestReadContextHook:
    def _post(self, path: Path) -> dict:
        return read_context(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": str(path)},
            }
        )

    def test_a_domain_read_gets_the_closure_context(self, closure_hub: Path):
        answer = self._post(closure_hub / "model" / "ontologies" / "customer.ttl")
        context = answer["hookSpecificOutput"]["additionalContext"]
        assert answer["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        assert "imports 1 module(s): urn:base" in context
        assert "Customer (2 inherited)" in context
        assert "1 of its 2 classes" in context
        assert "list-class-properties <IRI> --domain customer" in context

    def test_other_reads_are_silent(self, closure_hub: Path, tmp_path: Path):
        assert self._post(closure_hub / "catalog-v001.xml") == {}
        assert self._post(closure_hub / "refmodels" / "base.ttl") == {}
        assert self._post(tmp_path / "notes.ttl") == {}
        assert read_context({}) == {}

    def test_a_reference_model_read_is_denied_before_it_happens(self):
        answer = read_context(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {
                    "file_path": "C:/hub/.venv/Lib/site-packages/kairos_ontology_referencemodels/bsp/party.ttl"
                },
            }
        )
        output = answer["hookSpecificOutput"]
        assert output["permissionDecision"] == "deny"
        assert "explain-term" in output["permissionDecisionReason"]
        # A domain file is not denied: authoring needs the read (#659).
        assert (
            read_context(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_input": {"file_path": "/hub/model/ontologies/x.ttl"},
                }
            )
            == {}
        )

    def test_the_command_reads_stdin_and_never_fails(self, closure_hub: Path):
        payload = json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "tool_input": {
                    "file_path": str(closure_hub / "model" / "ontologies" / "customer.ttl")
                },
            }
        )
        result = CliRunner().invoke(cli, ["hook", "read-context"], input=payload)
        assert result.exit_code == 0, result.output
        assert "urn:base" in json.loads(result.output)["hookSpecificOutput"]["additionalContext"]
        broken = CliRunner().invoke(cli, ["hook", "read-context"], input="not json")
        assert broken.exit_code == 0
        assert json.loads(broken.output) == {}


mcp = pytest.importorskip("mcp")


def _call(server, name: str, arguments: dict):
    from mcp import Client

    from kairos_ontology.cli.mcp_server import tool_result_json

    async def run():
        async with Client(server) as client:
            return tool_result_json(await client.call_tool(name, arguments))

    return asyncio.run(run())


class TestMcpServer:
    @pytest.fixture
    def server(self, closure_hub: Path):
        from kairos_ontology.cli.mcp_server import build_server

        return build_server(closure_hub)

    def test_every_tool_says_it_reads_the_closure(self, server):
        from mcp import Client

        async def names():
            async with Client(server) as client:
                return {t.name: t.description or "" for t in (await client.list_tools()).tools}

        tools = asyncio.run(names())
        assert set(tools) == {
            "show_class_inventory",
            "list_class_properties",
            "explain_term",
            "resolve_ontology",
            "compile_check",
            "compile_explain",
            "logs_show",
        }
        for name in ("show_class_inventory", "list_class_properties", "explain_term"):
            assert "owl:imports" in tools[name]

    def test_list_class_properties_includes_inherited_with_origin(self, server):
        payload = _call(
            server,
            "list_class_properties",
            {"class_iri": "urn:customer#Customer", "domain": "customer"},
        )
        origins = {row["name"]: row["origin"] for row in payload["properties"]}
        assert origins == {"name": "inherited", "email": "inherited"}
        assert payload["coverage"]["inherited_properties"] is True

    def test_explain_term_names_uncarried_fields_under_rdfs(self, server):
        payload = _call(
            server,
            "explain_term",
            {"iri": "urn:customer#Customer", "domain": "customer", "profile": "rdfs"},
        )
        assert payload["term"]["uri"] == "urn:customer#Customer"
        assert "equivalent_classes" in payload["not_carried_by_profile"]

    def test_resolve_ontology_lists_the_closure(self, server):
        payload = _call(server, "resolve_ontology", {"domain": "customer"})
        assert payload["import_complete"] is True
        assert {entry["import_uri"] for entry in payload["manifest"]} >= {"urn:base"}

    def test_compile_check_on_the_product_hub(self, tmp_path: Path):
        from kairos_ontology.cli.mcp_server import build_server

        hub = tmp_path / "hub"
        shutil.copytree(_PRODUCT_HUB, hub)
        payload = _call(build_server(hub), "compile_check", {"domain": "billing"})
        assert payload["domain"] == "billing"
        assert payload["succeeded"] is True
        assert isinstance(payload["diagnostics"], list)

    def test_serve_without_the_extra_explains_the_install(self, monkeypatch, closure_hub: Path):
        import builtins

        real_import = builtins.__import__

        def no_mcp(name, *args, **kwargs):
            if name.startswith("mcp"):
                raise ImportError("no mcp")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_mcp)
        result = CliRunner().invoke(cli, ["mcp", "serve", "--hub", str(closure_hub)])
        assert result.exit_code != 0
        assert "[mcp] extra" in result.output
