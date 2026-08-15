# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for ``kairos-ontology propose-relationships`` (issue #493, DD-160).

The motivating failure: a hub shipped 27 EntityBindings with ``relationships: []`` --
every silver model isolated -- while the accelerator blueprint declared 24 cross-domain
bridges nothing in the v5 path ever read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.propose_relationships import (
    build_relationship_proposals,
    load_blueprint_bridges,
)

_BOOKING_CLASS = "https://ref.test/ont/booking#Booking"
_CONSIGNMENT_CLASS = "https://ref.test/ont/consignment#Consignment"
_BRIDGE_PROPERTY = "https://ref.test/ont/supply-chain#bookedConsignment"

_DATA_DOMAINS_YAML = f"""\
schema_version: "1.0"
groups:
  - id: transport
    name: Transport
    domains:
      - id: booking
        name: Booking
      - id: consignment
        name: Consignment
cross_domain_relationships:
  - id: booking-to-consignment
    description: Links a Booking to the Consignment it creates.
    domain_class_uri: {_BOOKING_CLASS}
    property_uri: {_BRIDGE_PROPERTY}
    range_class_uri: {_CONSIGNMENT_CLASS}
    source_domain: booking
    target_domain: consignment
    status: new-bridge
"""


def _binding(name: str, domain: str, target_class: str, source_key: str, extra: str = "") -> str:
    return (
        "apiVersion: kairos.eu/v5\n"
        "kind: EntityBinding\n"
        "metadata:\n"
        f"  name: {name}\n"
        f"  domain: {domain}\n"
        "source:\n"
        f"  relation: src.{name}\n"
        "target:\n"
        f"  class: {target_class}\n"
        "grain:\n"
        f"  columns: [{source_key}]\n"
        "identity:\n"
        "  strategy: source-natural\n"
        f"  sourceKey: [{source_key}]\n"
        "load:\n"
        "  mode: full-refresh\n"
        "fields: []\n"
        "relationships: []\n" + extra
    )


@pytest.fixture()
def hub(tmp_path: Path) -> Path:
    hub_root = tmp_path / "hub"
    bindings = hub_root / "integration" / "bindings"
    bindings.mkdir(parents=True)
    (hub_root / "model" / "ontologies").mkdir(parents=True)
    (hub_root / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")

    # The child carries the parent's key column as a technical field, which is exactly
    # the shape scaffold-binding produces and the #491 warning flags.
    child_extra = (
        "technicalFields:\n"
        "  - name: consignment_id\n"
        "    expression: consignment_id\n"
        "    type: string\n"
        "    nullable: false\n"
        "    purpose: relationship\n"
    )
    (bindings / "bookings.binding.yaml").write_text(
        _binding("bookings", "booking", _BOOKING_CLASS, "booking_id", child_extra),
        encoding="utf-8",
    )
    (bindings / "consignments.binding.yaml").write_text(
        _binding("consignments", "consignment", _CONSIGNMENT_CLASS, "consignment_id"),
        encoding="utf-8",
    )

    ref_models = tmp_path / "ontology-reference-models"
    blueprint = ref_models / "accelerator-packs" / "logistics" / "client-hub-blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "data-domains.yaml").write_text(_DATA_DOMAINS_YAML, encoding="utf-8")
    return hub_root


def _report(hub: Path):
    return build_relationship_proposals(
        hub_root=hub,
        ref_models_dir=hub.parent / "ontology-reference-models",
        accelerator="logistics",
    )


class TestBlueprintBridges:
    def test_bridges_are_read_from_the_blueprint(self, hub):
        bridges = load_blueprint_bridges(hub.parent / "ontology-reference-models", "logistics")
        assert [b.id for b in bridges] == ["booking-to-consignment"]
        assert bridges[0].property_uri == _BRIDGE_PROPERTY

    def test_missing_blueprint_is_not_an_error(self, tmp_path):
        assert load_blueprint_bridges(tmp_path / "nope", "logistics") == ()


class TestProposals:
    def test_property_comes_from_the_blueprint_not_a_guess(self, hub):
        report = _report(hub)
        assert len(report.proposals) == 1
        proposal = report.proposals[0]
        assert proposal.property_uri == _BRIDGE_PROPERTY
        assert proposal.evidence == "blueprint"
        assert proposal.evidence_id == "booking-to-consignment"
        assert proposal.child_binding == "bookings"
        assert proposal.parent_binding == "consignments"

    def test_join_columns_are_matched_deterministically(self, hub):
        proposal = _report(hub).proposals[0]
        assert proposal.join_resolved is True
        assert proposal.local_column == "consignment_id"
        assert proposal.foreign_column == "consignment_id"

    def test_cross_domain_target_gets_an_external_reference(self, hub):
        """DD-138: a cross-domain parent is a declared contract, not a discovered peer.

        The key *type* is sentinelled here on purpose: the parent binding declares
        ``consignment_id`` only as an identity source key, which carries no canonical
        type, so nothing in the hub states it. Guessing ``string`` would look right and
        silently break the compiler's key-type compatibility check.
        """
        proposal = _report(hub).proposals[0]
        assert proposal.external_reference == {
            # The dbt model name derives from the target class, not the binding/table.
            "name": "consignment",
            "domain": "consignment",
            "key": [{"column": "consignment_id", "type": "<CONFIRM_KEY_TYPE>"}],
        }

    def test_key_type_is_derived_when_the_parent_materializes_the_column(self, hub):
        """When the parent DOES declare the column's type, use it rather than a sentinel."""
        (hub / "integration" / "bindings" / "consignments.binding.yaml").write_text(
            _binding(
                "consignments",
                "consignment",
                _CONSIGNMENT_CLASS,
                "consignment_id",
                "technicalFields:\n"
                "  - name: consignment_key\n"
                "    expression: consignment_id\n"
                "    type: int64\n"
                "    nullable: false\n"
                "    purpose: identity\n",
            ),
            encoding="utf-8",
        )
        proposal = _report(hub).proposals[0]
        assert proposal.external_reference["key"] == [
            # The parent's authored *output* column name, not its source column.
            {"column": "consignment_key", "type": "int64"}
        ]

    def test_rendered_yaml_is_a_complete_relationships_entry(self, hub):
        rendered = _report(hub).proposals[0].to_yaml()
        for required in (
            "property:",
            "target:",
            "join:",
            "cardinality:",
            "mode:",
            "missingParent:",
            "ambiguousParent:",
        ):
            assert required in rendered

    def test_unmatched_join_uses_a_sentinel_not_a_plausible_guess(self, hub):
        """A wrong-looking column beats a right-looking wrong one."""
        binding = hub / "integration" / "bindings" / "bookings.binding.yaml"
        binding.write_text(
            _binding("bookings", "booking", _BOOKING_CLASS, "booking_id"), encoding="utf-8"
        )
        proposal = _report(hub).proposals[0]
        assert proposal.join_resolved is False
        assert proposal.local_column == "<CONFIRM_JOIN_COLUMN>"
        assert proposal.external_reference["key"] == [
            {"column": "<CONFIRM_JOIN_COLUMN>", "type": "<CONFIRM_KEY_TYPE>"}
        ]

    def test_zero_relationship_bindings_are_reported(self, hub):
        report = _report(hub)
        assert set(report.bindings_without_relationships) == {"bookings", "consignments"}
        assert report.blueprint_bridges == 1
        assert report.bridges_with_both_endpoints_bound == 1

    def test_domain_filter_limits_proposals(self, hub):
        report = build_relationship_proposals(
            hub_root=hub,
            ref_models_dir=hub.parent / "ontology-reference-models",
            accelerator="logistics",
            domain="consignment",
        )
        assert report.proposals == ()

    def test_unbound_endpoint_yields_no_proposal(self, hub):
        (hub / "integration" / "bindings" / "consignments.binding.yaml").unlink()
        assert _report(hub).proposals == ()


class TestCLI:
    def _invoke(self, hub: Path, monkeypatch, args):
        monkeypatch.chdir(hub)
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(hub.parent / "ontology-reference-models"))
        return CliRunner().invoke(cli, ["propose-relationships", *args])

    def test_text_output_is_advisory_and_exits_zero(self, hub, monkeypatch):
        result = self._invoke(hub, monkeypatch, [])
        assert result.exit_code == 0
        assert "bookings" in result.output
        assert "Advisory" in result.output

    def test_json_output_shape(self, hub, monkeypatch):
        result = self._invoke(hub, monkeypatch, ["--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["schema_version"] == 1
        assert payload["proposals"][0]["evidence"] == "blueprint"
        assert payload["proposals"][0]["endpoint_match"] == "uri"

    def test_no_unresolved_filters_sentinel_proposals(self, hub, monkeypatch):
        (hub / "integration" / "bindings" / "bookings.binding.yaml").write_text(
            _binding("bookings", "booking", _BOOKING_CLASS, "booking_id"), encoding="utf-8"
        )
        result = self._invoke(hub, monkeypatch, ["--no-unresolved", "--format", "json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["proposals"] == []
