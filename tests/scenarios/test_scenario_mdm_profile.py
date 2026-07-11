# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for the design-time MDM profile projection (mdm-profile target).

Exercises the ``kairos_ontology.mdm`` package against the synthetic Acme hub:
the profile projector directly, and the full ``run_projections`` wiring through
the core projector registry (verifying discovery, dispatch and output routing).
"""

import json

import pytest

# Importing the mdm package registers the ``mdm-profile`` target with core.
import kairos_ontology.mdm  # noqa: F401
from kairos_ontology.mdm.profile_projector import generate_mdm_profile_artifacts
from kairos_ontology.mdm.validation import validate_mdm_extension

from .conftest import EXTENSIONS_DIR, HUB_ROOT, ONTOLOGIES_DIR

CLIENT_MDM_EXT = EXTENSIONS_DIR / "client-mdm-ext.ttl"


@pytest.fixture(scope="module")
def client_mdm_artifacts(client_ontology):
    graph, namespace, _classes = client_ontology
    return generate_mdm_profile_artifacts(
        graph=graph,
        namespace=namespace,
        ontology_name="client",
        mdm_ext_path=CLIENT_MDM_EXT,
        ontology_metadata={"version": "1.0.0"},
    )


class TestMdmProfileProjection:
    def test_emits_json_and_markdown(self, client_mdm_artifacts):
        assert set(client_mdm_artifacts) == {
            "client-mdm-profile.json",
            "client-mdm-profile.md",
        }

    def test_profile_captures_mastered_client(self, client_mdm_artifacts):
        payload = json.loads(client_mdm_artifacts["client-mdm-profile.json"])
        assert payload["content_digest"].startswith("sha256:")
        concepts = {c["name"]: c for c in payload["mastered_concepts"]}
        assert "Client" in concepts
        client = concepts["Client"]
        assert client["mdm_style"] == "coexistence"
        assert client["workflow"]["maker_checker"] is True
        assert client["workflow"]["sla_hours"] == 48

        attr_names = {a["name"] for a in client["match_attributes"]}
        assert {"clientId", "vatNumber", "clientName"} <= attr_names
        vat = next(a for a in client["match_attributes"] if a["name"] == "vatNumber")
        assert vat["is_identifier"] is True
        assert vat["identifier_type"] == "VAT"

        rule_actions = {r["action"] for r in client["match_rules"]}
        assert {"auto-merge", "candidate"} <= rule_actions
        dq_dims = {d["dimension"] for d in client["data_quality"]}
        assert {"completeness", "validity"} <= dq_dims

    def test_profile_captures_reference_roles_and_artifact(self, client_mdm_artifacts):
        payload = json.loads(client_mdm_artifacts["client-mdm-profile.json"])
        ref_names = {r["name"] for r in payload["reference_lists"]}
        assert "ClientType" in ref_names
        role_names = {r["name"] for r in payload["steward_roles"]}
        assert "Client Steward" in role_names
        assert payload["probabilistic_artifact"]["digest"].startswith("sha256:")

    def test_extension_validates_clean(self, client_ontology):
        graph, namespace, _classes = client_ontology
        from kairos_ontology.core.projections.shared import merge_ext_graph

        merged = merge_ext_graph(graph, CLIENT_MDM_EXT)
        result = validate_mdm_extension(merged, namespace=namespace)
        assert result["passed"], result["errors"]


class TestMdmProfileEndToEnd:
    def test_run_projections_writes_output_mdm(self, tmp_path):
        """Full wiring: run_projections dispatches mdm-profile via the registry."""
        from kairos_ontology.core.projector import run_projections

        output = tmp_path / "output"
        catalog = HUB_ROOT / "catalog-v001.xml"
        run_projections(
            ontologies_path=ONTOLOGIES_DIR,
            catalog_path=catalog if catalog.exists() else output / "missing.xml",
            output_path=output,
            target="mdm-profile",
        )

        profile = output / "mdm" / "client-mdm-profile.json"
        assert profile.exists(), "expected output/mdm/client-mdm-profile.json"
        payload = json.loads(profile.read_text(encoding="utf-8"))
        assert payload["provenance"]["domain"] == "client"
        assert payload["mastered_concepts"]
