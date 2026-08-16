# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Blueprint-declared cross-domain classes are anchor candidates (DD-181).

A source table often holds rows of an entity its domain *references* rather than
*owns*. ``stops`` sits under ``consignment``, but each row is a transport call —
a concept ``route-schedule`` owns. Offered only home classes, the model correctly
declines to anchor, and 306 columns across nine tables end up unanchored (DD-180)
with no route forward but importing a module the domain has no business owning.

A declared ``cross_domain_relationship`` is the blueprint stating that reach is
authorised. Honouring it needs no flag: the declaration *is* the authorisation.
"""

import textwrap

import yaml

from kairos_ontology.core.analyse_sources import (
    bridge_anchor_classes,
    load_cross_domain_bridges,
)
from kairos_ontology.core.propose_alignment import (
    _bridge_tag,
    _format_ref_inventory,
)

TC = "https://ex.org/dcsa/transport-call#TransportCall"
INV = "https://ex.org/bsp/financial#Invoice"

BRIDGES = [
    {
        "id": "consignment-to-route",
        "source_domain": "consignment",
        "target_domain": "route-schedule",
        "property_uri": "https://ex.org/sc#hasStop",
        "range_class_uri": TC,
    },
    {
        "id": "consignment-to-invoice",
        "source_domain": "consignment",
        "target_domain": "financial",
        "property_uri": "https://ex.org/sc#invoicedVia",
        "range_class_uri": INV,
    },
    {
        "id": "booking-to-consignment",
        "source_domain": "booking",
        "target_domain": "consignment",
        "property_uri": "https://ex.org/sc#booked",
        "range_class_uri": "https://ex.org/mmt/consignment#Consignment",
    },
]


def write_blueprint(root, bridges, accelerator="logistics"):
    path = root / "accelerator-packs" / accelerator / "client-hub-blueprint"
    path.mkdir(parents=True)
    (path / "data-domains.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "groups": [], "cross_domain_relationships": bridges}),
        encoding="utf-8",
    )
    return root


class TestLoader:
    def test_reads_declared_bridges(self, tmp_path):
        assert len(load_cross_domain_bridges(write_blueprint(tmp_path, BRIDGES))) == 3

    def test_returns_bridges_verbatim(self, tmp_path):
        """Each consumer applies its own field requirement, so nothing is filtered."""
        partial = [{"id": "x", "source_domain": "a", "property_uri": "https://ex.org/p"}]
        loaded = load_cross_domain_bridges(write_blueprint(tmp_path, partial))
        assert loaded == partial, "the scaffold header needs property_uri-only bridges"

    def test_missing_blueprint_is_not_an_error(self, tmp_path):
        assert load_cross_domain_bridges(tmp_path) == []

    def test_unreadable_blueprint_is_not_an_error(self, tmp_path):
        path = tmp_path / "accelerator-packs" / "logistics" / "client-hub-blueprint"
        path.mkdir(parents=True)
        (path / "data-domains.yaml").write_text("{[ not yaml", encoding="utf-8")
        assert load_cross_domain_bridges(tmp_path) == []


class TestBridgeAnchorClasses:
    def test_selects_only_bridges_declared_from_this_domain(self):
        found = bridge_anchor_classes(BRIDGES, "consignment")
        assert found == {TC: "route-schedule", INV: "financial"}

    def test_a_bridge_is_directional(self):
        """booking->consignment does not let consignment anchor to booking's classes."""
        assert "https://ex.org/mmt/consignment#Consignment" not in bridge_anchor_classes(
            BRIDGES, "consignment"
        )
        assert bridge_anchor_classes(BRIDGES, "booking") == {
            "https://ex.org/mmt/consignment#Consignment": "consignment"
        }

    def test_domain_with_no_bridges_gets_nothing(self):
        assert bridge_anchor_classes(BRIDGES, "compliance") == {}

    def test_bridges_without_a_range_class_are_skipped(self):
        """The anchor pool needs a class; a property-only bridge cannot supply one."""
        assert bridge_anchor_classes([{"source_domain": "d", "property_uri": "p"}], "d") == {}


class TestPromptMarking:
    def test_bridged_class_is_marked_cross_domain_with_its_owner(self):
        tag = _bridge_tag({"bridge_target_domain": "route-schedule"})
        assert "CROSS-DOMAIN" in tag
        assert "route-schedule" in tag

    def test_marking_states_that_redeclaring_is_not_allowed(self):
        """Anchoring to a bridged class is fine; minting a local copy is the defect."""
        tag = _bridge_tag({"bridge_target_domain": "route-schedule"})
        assert "redeclaring it locally is not" in tag

    def test_home_class_carries_no_marker(self):
        assert _bridge_tag({"name": "Consignment"}) == ""

    def test_inventory_renders_the_marker(self):
        text = _format_ref_inventory(
            [
                {"name": "Consignment", "label": "Consignment", "properties": []},
                {
                    "name": "TransportCall",
                    "label": "Transport Call",
                    "properties": [],
                    "bridge_target_domain": "route-schedule",
                },
            ]
        )
        assert "CLASS: Consignment (Consignment)\n" in text + "\n"
        assert "CROSS-DOMAIN" in text
        # Only the bridged class is marked.
        assert text.count("CROSS-DOMAIN") == 1


class TestResolution:
    """resolve_bridge_anchor_classes needs a catalog, so it is exercised end-to-end."""

    def test_no_bridges_resolves_to_nothing(self, tmp_path):
        from kairos_ontology.core.propose_alignment import resolve_bridge_anchor_classes

        assert resolve_bridge_anchor_classes({}, tmp_path / "catalog.xml") == []

    def test_no_catalog_resolves_to_nothing(self):
        from kairos_ontology.core.propose_alignment import resolve_bridge_anchor_classes

        assert resolve_bridge_anchor_classes({TC: "route-schedule"}, None) == []

    def test_resolves_a_bridged_class_and_tags_its_owner(self, tmp_path):
        from kairos_ontology.core.propose_alignment import resolve_bridge_anchor_classes

        module = tmp_path / "transport-call.ttl"
        module.write_text(
            textwrap.dedent(
                f"""\
                @prefix owl: <http://www.w3.org/2002/07/owl#> .
                @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
                <https://ex.org/dcsa/transport-call#> a owl:Ontology .
                <{TC}> a owl:Class ; rdfs:label "Transport Call" .
                """
            ),
            encoding="utf-8",
        )
        catalog = tmp_path / "catalog.xml"
        catalog.write_text(
            '<?xml version="1.0"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            '  <uri name="https://ex.org/dcsa/transport-call#" uri="transport-call.ttl"/>\n'
            "</catalog>\n",
            encoding="utf-8",
        )
        found = resolve_bridge_anchor_classes({TC: "route-schedule"}, catalog)
        assert [c["name"] for c in found] == ["TransportCall"]
        assert found[0]["bridge_target_domain"] == "route-schedule"

    def test_a_class_already_in_the_home_pool_is_excluded(self, tmp_path):
        """The model has seen it; offering it twice only inflates the prompt."""
        from kairos_ontology.core.propose_alignment import resolve_bridge_anchor_classes

        assert (
            resolve_bridge_anchor_classes(
                {TC: "route-schedule"}, tmp_path / "catalog.xml", exclude_uris={TC}
            )
            == []
        )


class TestDefaultOn:
    def test_bridge_loading_is_not_gated_on_the_cross_module_flag(self):
        """The blueprint declaration is the authorisation — a CLI flag would override it."""
        import inspect

        from kairos_ontology.core import propose_alignment as pa

        source = inspect.getsource(pa._propose_alignments)
        load_at = source.index("load_cross_domain_bridges(")
        # The call must not sit inside the `if cross_module:` guard.
        guard_at = source.index("if cross_module:")
        assert load_at < guard_at, (
            "cross-domain bridges must load before (and independently of) the "
            "cross-module flag; see DD-181."
        )


class TestAcceleratorResolution:
    """The pack must be resolved, not guessed (found on the live hub)."""

    def test_glob_order_would_pick_the_wrong_pack(self, tmp_path):
        """`financial-services` sorts before `logistics`; first-match is not the hub's."""
        write_blueprint(tmp_path, [], accelerator="financial-services")
        write_blueprint(tmp_path, BRIDGES, accelerator="logistics")
        assert load_cross_domain_bridges(tmp_path) == [], (
            "unresolved lookup returns the alphabetically-first pack — which is why "
            "the caller must resolve the accelerator rather than omit it"
        )
        assert len(load_cross_domain_bridges(tmp_path, "logistics")) == 3

    def test_hub_root_is_found_by_walking_up_to_pyproject(self, tmp_path):
        from kairos_ontology.core.propose_alignment import _hub_root_from_catalog

        hub = tmp_path / "hub"
        (hub / "ontology-hub").mkdir(parents=True)
        (hub / "pyproject.toml").write_text("[tool.kairos]\n", encoding="utf-8")
        catalog = hub / "ontology-hub" / "catalog-v001.xml"
        catalog.write_text("<catalog/>", encoding="utf-8")
        assert _hub_root_from_catalog(catalog) == hub.resolve()

    def test_no_pyproject_anywhere_yields_none(self, tmp_path):
        from kairos_ontology.core.propose_alignment import _hub_root_from_catalog

        catalog = tmp_path / "catalog-v001.xml"
        catalog.write_text("<catalog/>", encoding="utf-8")
        assert _hub_root_from_catalog(catalog) is None

    def test_no_catalog_yields_none(self):
        from kairos_ontology.core.propose_alignment import _hub_root_from_catalog

        assert _hub_root_from_catalog(None) is None
