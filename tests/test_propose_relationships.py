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
    SENTINEL_JOIN_COLUMN,
    SENTINEL_PROPERTY,
    RelationshipProposal,
    collapse_competing_properties,
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


#: The `missingParent: "null"` is the point, not decoration: one real hub authors
#: exactly this with a comment naming the code types it deliberately tolerates, and
#: #722 reports the proposal re-rendering it as `missingParent: error`. Quoted because
#: the schema enum is the *string* "null" while bare YAML `null` parses to None.
_AUTHORED_RELATIONSHIP = f"""
  - property: {_BRIDGE_PROPERTY}
    target: {_CONSIGNMENT_CLASS}
    join: [{{local: consignment_id, foreign: consignment_id}}]
    cardinality: many-to-one
    mode: non-temporal
    missingParent: "null"
    ambiguousParent: error
"""


def _binding(name: str, domain: str, target_class: str, source_key: str, extra: str = "",
             relationships: str = "[]", key_property: str = "") -> str:
    """One authored binding.

    *key_property* is the ontology property the binding maps its key column to. It matters
    because ``join.foreign`` names the column the parent *emits*: a key carried through
    ``fields:`` reaches Silver as ``camel_to_snake`` of the property's local name, not
    under the source column's name. A parent with no ``fields:`` entry for its key emits a
    surrogate key and nothing else, so no natural-key join to it is possible at all.
    """
    fields = "fields: []\n"
    if key_property:
        fields = (
            "fields:\n"
            f"  - property: {key_property}\n"
            f"    expression: {source_key}\n"
        )
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
        + fields
        + f"relationships: {relationships}\n" + extra
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
        _binding("consignments", "consignment", _CONSIGNMENT_CLASS, "consignment_id",
                 key_property="cons:consignmentReference"),
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
        """local names the child's source column, foreign the column the parent emits.

        The asymmetry is the emitted SQL's: the child side reads from the raw source CTE
        (``src.<local>``) while the parent side reads from the built model
        (``ref(parent).<foreign>``). Naming the parent's *source* column here produced a
        join against a column the parent model does not have -- it compiled, emitted, and
        would fail only when dbt ran (#928).
        """
        proposal = _report(hub).proposals[0]
        assert proposal.join_resolved is True
        assert proposal.local_column == "consignment_id"
        assert proposal.foreign_column == "consignment_reference"

    def test_cross_domain_target_gets_an_external_reference(self, hub):
        """DD-138: a cross-domain parent is a declared contract, not a discovered peer.

        The key *type* is sentinelled here on purpose: the parent carries its key through
        ``fields:``, which states no canonical type, so nothing in the hub states it.
        Guessing ``string`` would look right and silently break the compiler's key-type
        compatibility check.

        The key *column* is the emitted one, and must equal ``join.foreign`` exactly --
        the compiler enforces that, and both name the parent model's column.
        """
        proposal = _report(hub).proposals[0]
        assert proposal.external_reference == {
            # The dbt model name derives from the target class, not the binding/table.
            "name": "consignment",
            "domain": "consignment",
            "key": [{"column": "consignment_reference", "type": "<CONFIRM_KEY_TYPE>"}],
        }
        assert proposal.external_reference["key"][0]["column"] == proposal.foreign_column

    def test_a_qname_parent_class_slugs_to_the_model_the_compiler_emits(self, hub):
        """#724: the proposal is handed the authored token, the compiler the resolved class.

        A parent authoring `target: {class: cons:Consignment}` -- the form the canonical
        example uses -- used to yield `externalReference.name: cons_consignment`, because
        `_local_name` splits on `#` and `/` only and the colon then mapped to an
        underscore. The compiler slugs `ResolvedClass.name` from the semantic index and
        emits `consignment`, so the pasted `ref()` named a model that never exists --
        and `externalReference` skips model-existence checking, so nothing failed closed.
        """
        (hub / "integration" / "bindings" / "consignments.binding.yaml").write_text(
            _binding("consignments", "consignment", "cons:Consignment", "consignment_id",
                     key_property="cons:consignmentReference"),
            encoding="utf-8",
        )
        proposal = _report(hub).proposals[0]
        assert proposal.external_reference["name"] == "consignment"

    def test_a_qname_class_still_matches_its_endpoint_by_local_name(self, hub):
        """The same blind spot in the endpoint index, which keys on the authored token.

        A hub authoring its own class as a qname while the blueprint declares a full URI
        would key `cons:consignment` against `consignment` and match nothing, so the
        bridge silently produced no proposal at all.
        """
        (hub / "integration" / "bindings" / "consignments.binding.yaml").write_text(
            _binding("consignments", "consignment", "cons:Consignment", "consignment_id",
                     key_property="cons:consignmentReference"),
            encoding="utf-8",
        )
        report = _report(hub)
        assert [p.parent_binding for p in report.proposals] == ["consignments"]
        assert report.proposals[0].endpoint_match == "local-name"

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


_HUB_NS = "https://hub.test/ont/logistics#"
_LOCAL_CONSIGNMENT = f"{_HUB_NS}LocalConsignment"
_HOUSE_CONSIGNMENT = f"{_HUB_NS}HouseConsignment"
_CARRIER_BOOKING = f"{_HUB_NS}CarrierBooking"

#: The prescribed hub pattern: subclass the reference-model class rather than bind it.
_HUB_ONTOLOGY = f"""\
@prefix hub:  <{_HUB_NS}> .
@prefix refb: <https://ref.test/ont/booking#> .
@prefix refc: <https://ref.test/ont/consignment#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://hub.test/ont/logistics> a owl:Ontology ; owl:versionInfo "1.0.0" .
hub:CarrierBooking a owl:Class ; rdfs:label "Carrier booking" ;
  rdfs:subClassOf refb:Booking .
hub:LocalConsignment a owl:Class ; rdfs:label "Local consignment" ;
  rdfs:subClassOf refc:Consignment .
"""


class TestSubclassEndpoints:
    """#732: a hub subclass of the endpoint class is a match, read from the RDFS closure.

    Blueprint bridges and reference object properties name *reference* classes; the
    prescribed hub pattern is to subclass them. Before this, only exact URI or a
    same-local-name coincidence matched, so the entries DD-139 told authors to derive with
    this command could not be derived -- and once #729 made the compiler accept a subclass
    endpoint, the proposer was the only thing still refusing it.
    """

    def _ontology(self, hub: Path, ttl: str = _HUB_ONTOLOGY) -> None:
        (hub / "model" / "ontologies" / "logistics.ttl").write_text(ttl, encoding="utf-8")

    def _rebind(self, hub: Path, bookings_class: str, consignments_class: str) -> None:
        child_extra = (
            "technicalFields:\n"
            "  - name: consignment_id\n"
            "    expression: consignment_id\n"
            "    type: string\n"
            "    nullable: false\n"
            "    purpose: relationship\n"
        )
        (hub / "integration" / "bindings" / "bookings.binding.yaml").write_text(
            _binding("bookings", "booking", bookings_class, "booking_id", child_extra),
            encoding="utf-8",
        )
        (hub / "integration" / "bindings" / "consignments.binding.yaml").write_text(
            _binding("consignments", "consignment", consignments_class, "consignment_id",
                     key_property="cons:consignmentReference"),
            encoding="utf-8",
        )

    def test_a_hub_subclass_of_each_endpoint_is_proposed(self, hub):
        self._ontology(hub)
        self._rebind(hub, _CARRIER_BOOKING, _LOCAL_CONSIGNMENT)
        report = _report(hub)
        assert [p.parent_binding for p in report.proposals] == ["consignments"]
        proposal = report.proposals[0]
        assert proposal.endpoint_match == "subclass"
        # The pasteable target is the class the hub binds, never the blueprint's URI.
        assert proposal.target_class == _LOCAL_CONSIGNMENT
        assert proposal.join_resolved
        assert any("rdfs:subClassOf" in note for note in report.notes)

    def test_a_qname_subclass_target_resolves_through_the_hub_prefixes(self, hub):
        self._ontology(hub)
        self._rebind(hub, "hub:CarrierBooking", "hub:LocalConsignment")
        report = _report(hub)
        assert [p.endpoint_match for p in report.proposals] == ["subclass"]
        assert report.proposals[0].target_class == "hub:LocalConsignment"

    def test_a_qname_that_denotes_the_endpoint_class_is_a_uri_match(self, hub):
        """Expanding the qname against the hub's own ``@prefix`` promotes what used to be a
        ``local-name`` coincidence to the exact match it always was."""
        self._ontology(hub)
        self._rebind(hub, _BOOKING_CLASS, "refc:Consignment")
        report = _report(hub)
        assert [p.endpoint_match for p in report.proposals] == ["uri"]

    def test_a_superclass_of_the_endpoint_is_not_matched(self, hub):
        """Downward only. If the edge names the *subclass*, binding its parent would let
        instances outside the endpoint satisfy the join -- the same asymmetry the compiler
        enforces (#729)."""
        self._ontology(hub)
        blueprint = (
            hub.parent / "ontology-reference-models" / "accelerator-packs" / "logistics"
            / "client-hub-blueprint" / "data-domains.yaml"
        )
        blueprint.write_text(
            _DATA_DOMAINS_YAML.replace(_CONSIGNMENT_CLASS, _LOCAL_CONSIGNMENT),
            encoding="utf-8",
        )
        self._rebind(hub, _BOOKING_CLASS, _CONSIGNMENT_CLASS)
        assert _report(hub).proposals == ()

    def test_several_bound_subclasses_each_yield_a_proposal(self, hub):
        """Nothing here picks for the author; every bound descendant is a candidate."""
        self._ontology(
            hub,
            _HUB_ONTOLOGY
            + "hub:HouseConsignment a owl:Class ; rdfs:subClassOf refc:Consignment .\n",
        )
        self._rebind(hub, _CARRIER_BOOKING, _LOCAL_CONSIGNMENT)
        (hub / "integration" / "bindings" / "house.binding.yaml").write_text(
            _binding("house", "consignment", _HOUSE_CONSIGNMENT, "consignment_id"),
            encoding="utf-8",
        )
        report = _report(hub)
        assert sorted(p.parent_binding for p in report.proposals) == ["consignments", "house"]
        assert {p.endpoint_match for p in report.proposals} == {"subclass"}
        assert any("several bound subclasses" in note for note in report.notes)

    def test_an_ontology_edge_between_reference_classes_proposes_the_hub_subclasses(self, hub):
        """The #729 shape without any blueprint: the reference model declares the object
        property between its own classes; the hub binds subclasses of both."""
        self._ontology(
            hub,
            _HUB_ONTOLOGY
            + "refb:bookedConsignment a owl:ObjectProperty ;\n"
            "  rdfs:domain refb:Booking ; rdfs:range refc:Consignment .\n",
        )
        self._rebind(hub, _CARRIER_BOOKING, _LOCAL_CONSIGNMENT)
        report = build_relationship_proposals(hub_root=hub, ref_models_dir=None)
        assert [(p.evidence, p.endpoint_match) for p in report.proposals] == [
            ("ontology", "subclass")
        ]
        assert report.proposals[0].property_uri == "https://ref.test/ont/booking#bookedConsignment"

    def test_subclass_ranks_between_uri_and_local_name(self, hub):
        """A reviewer sees exact matches first, then sound subsumption, then the heuristic."""
        from kairos_ontology.core.propose_relationships import _ENDPOINT_MATCH_RANK

        assert sorted(_ENDPOINT_MATCH_RANK, key=_ENDPOINT_MATCH_RANK.__getitem__) == [
            "uri",
            "subclass",
            "local-name",
        ]


class TestAlreadyAuthored:
    """#722: a relationship the binding already carries is not work, and not a proposal.

    On the reporting hub five of eight resolved proposals were verbatim re-renders of
    entries already present -- and because `to_yaml` hard-codes the policy fields, pasting
    one back would have replaced a deliberate `missingParent: null` with `error`, breaking
    the load for exactly the code types its comment named.
    """

    def _author(self, hub: Path, relationships: str, extra: str = "") -> None:
        (hub / "integration" / "bindings" / "bookings.binding.yaml").write_text(
            _binding("bookings", "booking", _BOOKING_CLASS, "booking_id", extra,
                     relationships=relationships),
            encoding="utf-8",
        )

    def test_an_authored_pair_is_not_re_proposed(self, hub):
        self._author(hub, _AUTHORED_RELATIONSHIP)
        report = _report(hub)
        assert report.proposals == ()
        assert report.already_authored == (
            ("bookings", _BRIDGE_PROPERTY, _CONSIGNMENT_CLASS),
        )

    def test_an_authored_qname_target_matches_a_uri_parent_class(self, hub):
        """The parent binding's `target.class` is a URI; the child may author a qname.

        `kernel._relationship_ref_uri` accepts a full URI, a `prefix:Local` qname, or a
        bare local name, and the canonical example uses the qname form -- so comparing
        raw strings would miss the match and re-propose the entry anyway.
        """
        self._author(hub, _AUTHORED_RELATIONSHIP.replace(
            f"target: {_CONSIGNMENT_CLASS}", "target: cons:Consignment"))
        assert _report(hub).proposals == ()

    def test_a_different_property_to_the_same_target_is_still_proposed(self, hub):
        self._author(hub, _AUTHORED_RELATIONSHIP.replace(
            _BRIDGE_PROPERTY, "https://ref.test/ont/supply-chain#someOtherProperty"))
        report = _report(hub)
        assert report.already_authored == ()
        assert [p.property_uri for p in report.proposals] == [_BRIDGE_PROPERTY]

    def test_the_same_property_to_a_different_target_is_still_proposed(self, hub):
        """The dangerous direction for a tolerant comparison: a false *suppression*.

        Matching on the property alone would withhold a real proposal because the binding
        happens to point the same property somewhere else.
        """
        self._author(hub, _AUTHORED_RELATIONSHIP.replace(
            f"target: {_CONSIGNMENT_CLASS}", "target: cons:SomethingElse"))
        report = _report(hub)
        assert report.already_authored == ()
        assert [p.property_uri for p in report.proposals] == [_BRIDGE_PROPERTY]

    def test_the_authored_note_warns_against_overwriting_policy(self, hub):
        self._author(hub, _AUTHORED_RELATIONSHIP)
        assert any("already authored" in note for note in _report(hub).notes)


class TestJoinKeySelection:
    """#722: the child's own identity is not a foreign key to its parent."""

    def _rekey(self, hub: Path, extra: str = "") -> None:
        for name, domain, klass in (
            ("bookings", "booking", _BOOKING_CLASS),
            ("consignments", "consignment", _CONSIGNMENT_CLASS),
        ):
            (hub / "integration" / "bindings" / f"{name}.binding.yaml").write_text(
                _binding(name, domain, klass, "source_record_id",
                         extra if name == "bookings" else ""),
                encoding="utf-8",
            )

    def test_the_childs_own_surrogate_identity_is_not_a_join_key(self, hub):
        """A hub with one uniform identity column name joined every row to itself."""
        self._rekey(hub)
        proposal = _report(hub).proposals[0]
        assert proposal.join_resolved is False
        assert proposal.local_column == "<CONFIRM_JOIN_COLUMN>"

    def test_an_unresolved_proposal_surfaces_declared_carriers_as_candidates(self, hub):
        """The FK the old rule ignored is exactly the column DD-139 made the author declare."""
        self._rekey(hub, extra=(
            "technicalFields:\n"
            "  - name: parent_invoice_source_id\n"
            "    expression: parent_invoice_source_id\n"
            "    type: string\n"
            "    nullable: false\n"
            "    purpose: relationship\n"
        ))
        proposal = _report(hub).proposals[0]
        assert proposal.join_resolved is False
        assert proposal.join_candidates == ("parent_invoice_source_id",)

    def test_a_declared_carrier_is_labelled_as_its_own_evidence_tier(self, hub):
        """The stock fixture's carrier now resolves via tier 0, not name equality."""
        assert _report(hub).proposals[0].join_evidence == "declared-fk"


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
        assert payload["schema_version"] == 2
        assert payload["proposals"][0]["evidence"] == "blueprint"
        assert payload["proposals"][0]["endpoint_match"] == "uri"

    def test_the_header_counts_proposals_and_authored_entries(self, hub, monkeypatch):
        """#722: a bare list of entries reads as N units of available work."""
        (hub / "integration" / "bindings" / "bookings.binding.yaml").write_text(
            _binding("bookings", "booking", _BOOKING_CLASS, "booking_id",
                     relationships=_AUTHORED_RELATIONSHIP),
            encoding="utf-8",
        )
        result = self._invoke(hub, monkeypatch, [])
        assert result.exit_code == 0
        assert "Proposals: 0 (0 with resolved join columns)" in result.output
        assert "1 already authored, not re-proposed" in result.output
        # The entry itself is never rendered, so there is nothing to paste back over
        # the authored policy. (The advisory note names the policy fields in prose;
        # what must be absent is a pasteable YAML entry.)
        assert "- property:" not in result.output

    def test_json_lists_the_authored_pairs_it_withheld(self, hub, monkeypatch):
        """A tolerant local-name match must be reviewable, not merely counted."""
        (hub / "integration" / "bindings" / "bookings.binding.yaml").write_text(
            _binding("bookings", "booking", _BOOKING_CLASS, "booking_id",
                     relationships=_AUTHORED_RELATIONSHIP),
            encoding="utf-8",
        )
        result = self._invoke(hub, monkeypatch, ["--format", "json"])
        payload = json.loads(result.output)
        assert payload["proposals"] == []
        assert payload["already_authored"] == [
            {
                "child_binding": "bookings",
                "property": _BRIDGE_PROPERTY,
                "target": _CONSIGNMENT_CLASS,
            }
        ]

    def test_no_unresolved_filters_sentinel_proposals(self, hub, monkeypatch):
        (hub / "integration" / "bindings" / "bookings.binding.yaml").write_text(
            _binding("bookings", "booking", _BOOKING_CLASS, "booking_id"), encoding="utf-8"
        )
        result = self._invoke(hub, monkeypatch, ["--no-unresolved", "--format", "json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["proposals"] == []

class TestTheJoinNamesTheColumnTheParentEmits:
    """#928 -- proposals joined on the parent's *source* column, which it may not emit.

    The emitted SQL reads the child from the raw source CTE and the parent from the built
    model, so the two sides of a join are not in the same namespace. Every proposal
    against a parent that renames its key on the way into Silver -- which is the normal
    case, since a mapped field is emitted under the ontology property's name -- named a
    column the parent model does not have. It compiled, it emitted, and it would fail
    only when dbt ran.
    """

    def _hub(self, tmp_path, key_property, parent_extra=""):
        hub_root = tmp_path / "hub"
        bindings = hub_root / "integration" / "bindings"
        bindings.mkdir(parents=True)
        (hub_root / "model" / "ontologies").mkdir(parents=True)
        (hub_root / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
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
            _binding(
                "consignments", "consignment", _CONSIGNMENT_CLASS, "consignment_id",
                parent_extra, key_property=key_property,
            ),
            encoding="utf-8",
        )
        ref_models = tmp_path / "ontology-reference-models"
        blueprint = ref_models / "accelerator-packs" / "logistics" / "client-hub-blueprint"
        blueprint.mkdir(parents=True)
        (blueprint / "data-domains.yaml").write_text(_DATA_DOMAINS_YAML, encoding="utf-8")
        return hub_root

    def test_a_renaming_parent_is_joined_on_its_emitted_name(self, tmp_path):
        hub = self._hub(tmp_path, "cons:consignmentReference")
        proposal = _report(hub).proposals[0]
        assert proposal.local_column == "consignment_id", "the child reads its source column"
        assert proposal.foreign_column == "consignment_reference", (
            "the parent reads its model column"
        )

    def test_a_parent_that_does_not_emit_its_key_has_no_join(self, tmp_path):
        """No column to join to is not a join with a guessed column name."""
        hub = self._hub(tmp_path, "")
        proposal = _report(hub).proposals[0]
        assert proposal.join_resolved is False
        assert proposal.foreign_column == SENTINEL_JOIN_COLUMN
        assert "does not emit" in proposal.join_evidence
        assert proposal.external_reference["key"][0]["column"] == SENTINEL_JOIN_COLUMN

    def test_a_technical_field_still_wins_over_a_mapped_field(self, tmp_path):
        """An authored technicalField names its own output column; that is authoritative."""
        parent_extra = (
            "technicalFields:\n"
            "  - name: cons_key\n"
            "    expression: consignment_id\n"
            "    type: string\n"
            "    nullable: false\n"
            "    purpose: identity\n"
        )
        hub = self._hub(tmp_path, "cons:consignmentReference", parent_extra)
        proposal = _report(hub).proposals[0]
        assert proposal.foreign_column == "cons_key"
        assert proposal.external_reference["key"][0]["type"] == "string", (
            "a technicalField states a canonical type, so it is not sentinelled"
        )

    def test_the_external_key_always_equals_join_foreign(self, tmp_path):
        """The compiler requires exact equality; a proposal that breaks it cannot compile."""
        for key_property in ("cons:consignmentReference", ""):
            hub = self._hub(tmp_path / key_property.replace(":", "_" ) or "none", key_property)
            proposal = _report(hub).proposals[0]
            assert (
                proposal.external_reference["key"][0]["column"] == proposal.foreign_column
            )

def _proposal(prop: str, *, local="account_ref", foreign="party_id", child="bookings",
              parent="parties") -> RelationshipProposal:
    return RelationshipProposal(
        child_binding=child, child_domain="booking",
        parent_binding=parent, parent_domain="party",
        property_uri=prop, target_class="p:Party",
        evidence="ontology", evidence_id=prop.rsplit("#", 1)[-1],
        endpoint_match="uri", local_column=local, foreign_column=foreign,
        join_resolved=True, external_reference=None,
    )


_GENERIC = "https://ref.test/ont/c#hasParty"
_CONSIGNEE = "https://ref.test/ont/c#hasConsignee"
_CARRIER = "https://ref.test/ont/c#hasCarrier"
_FROM = "https://ref.test/ont/c#fromLocation"
_TO = "https://ref.test/ont/c#toLocation"


class TestCollapsingCompetingProperties:
    """#928 -- N properties between the same two classes became N equal proposals.

    They share one join, so at most one of them can be true of it. Accepting the set as
    printed asserted that one key was simultaneously every role in a reference model's
    party hierarchy.
    """

    def test_a_declared_subproperty_is_folded_into_its_parent(self):
        ancestors = {_CONSIGNEE: frozenset({_GENERIC}), _CARRIER: frozenset({_GENERIC}),
                     _GENERIC: frozenset()}
        out = collapse_competing_properties(
            [_proposal(_GENERIC), _proposal(_CONSIGNEE), _proposal(_CARRIER)], ancestors
        )
        assert len(out) == 1
        assert out[0].property_uri == _GENERIC, (
            "the join says the rows are related, not which role the party plays"
        )
        assert out[0].narrower_alternatives == (_CARRIER, _CONSIGNEE)
        assert out[0].competing_properties == ()

    def test_the_generic_survivor_stays_pasteable(self):
        ancestors = {_CONSIGNEE: frozenset({_GENERIC}), _GENERIC: frozenset()}
        [out] = collapse_competing_properties(
            [_proposal(_GENERIC), _proposal(_CONSIGNEE)], ancestors
        )
        assert SENTINEL_PROPERTY not in out.to_yaml()
        assert _GENERIC in out.to_yaml()
        assert "Narrow only if the source distinguishes the role" in out.to_yaml()

    def test_siblings_with_no_hierarchy_become_one_explicit_choice(self):
        out = collapse_competing_properties(
            [_proposal(_FROM), _proposal(_TO)], {_FROM: frozenset(), _TO: frozenset()}
        )
        assert len(out) == 1
        assert out[0].competing_properties == (_TO,)
        assert out[0].narrower_alternatives == ()

    def test_a_genuine_either_or_is_not_pasteable_as_one_arm(self):
        """Two directional properties on one non-directional column: pick, do not paste."""
        [out] = collapse_competing_properties(
            [_proposal(_FROM), _proposal(_TO)], {_FROM: frozenset(), _TO: frozenset()}
        )
        rendered = out.to_yaml()
        assert f"property: {SENTINEL_PROPERTY}" in rendered
        assert _FROM in rendered and _TO in rendered, "both arms are named in the comment"

    def test_different_joins_are_never_merged(self):
        out = collapse_competing_properties(
            [_proposal(_FROM, local="from_id"), _proposal(_TO, local="to_id")],
            {_FROM: frozenset(), _TO: frozenset()},
        )
        assert len(out) == 2, "a source that distinguishes the roles keeps both"
        assert all(not item.competing_properties for item in out)

    def test_different_parents_are_never_merged(self):
        out = collapse_competing_properties(
            [_proposal(_FROM, parent="a"), _proposal(_FROM, parent="b")],
            {_FROM: frozenset()},
        )
        assert len(out) == 2

    def test_a_lone_proposal_is_untouched(self):
        [out] = collapse_competing_properties([_proposal(_GENERIC)], {})
        assert out.competing_properties == ()
        assert out.narrower_alternatives == ()


class TestTargetResolvability:
    """#928 -- a proposal may name a class the child domain cannot resolve."""

    def test_an_unresolvable_target_is_flagged_and_warned_about_in_yaml(self):
        from dataclasses import replace

        out = replace(_proposal(_GENERIC), target_resolvable=False)
        rendered = out.to_yaml()
        assert "does not import the module declaring the target class" in rendered
        assert "the paste will not compile" in rendered

    def test_a_resolvable_target_says_nothing(self):
        assert "owl:imports" not in _proposal(_GENERIC).to_yaml()
