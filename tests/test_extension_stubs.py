# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Rendering the accepted `registered-extension` decisions as draft OWL (#883).

The decisions had no consumer: `registered-extension`'s own definition points at
`register-concept`, which registers a *class* the archetype catalog lacks, while these
are *columns* wanting *properties* on classes that already exist. An operator who closed
the DD-169 gate column by column ended with records no tool could act on.

This renders what was already decided. It must not invent anything, and it must not emit
TTL that `validate --syntax` would reject.
"""

import yaml

from kairos_ontology.core.extension_stubs import (
    collect_extension_properties,
    render_extension_ttl,
)

CLASS = "https://example.com/ref/cargo#CargoItem"
OTHER_CLASS = "https://example.com/ref/vessel#Vessel"


def _ledger(tmp_path, entries):
    analysis = tmp_path / "integration" / "sources" / "_analysis"
    analysis.mkdir(parents=True)
    (analysis / "table-dispositions.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "tables": entries}), encoding="utf-8"
    )
    return tmp_path


def _entry(column, *, name, rng="xsd:string", on_class=CLASS, disposition="registered-extension",
           table="cargo", with_property=True):
    entry = {
        "system": "src", "table": table, "column": column,
        "disposition": disposition, "rationale": "real business data", "decided_by": "user",
    }
    if with_property:
        entry["proposed_property"] = {
            "name": name, "range": rng, "on_class": on_class, "why": f"What {name} means.",
        }
    return entry


class TestCollect:
    def test_an_accepted_decision_becomes_a_property(self, tmp_path):
        hub = _ledger(tmp_path, [_entry("BLNR", name="billOfLadingNumber")])

        report = collect_extension_properties(hub)

        assert [p.name for p in report.properties] == ["billOfLadingNumber"]
        assert report.decisions_seen == 1

    def test_other_dispositions_are_ignored(self, tmp_path):
        hub = _ledger(tmp_path, [
            _entry("A", name="alpha", disposition="deferred"),
            _entry("B", name="beta", disposition="not-business-data"),
        ])

        assert collect_extension_properties(hub).properties == []

    def test_a_table_grain_extension_is_a_different_claim(self, tmp_path):
        entry = _entry("", name="alpha")
        entry.pop("column")
        hub = _ledger(tmp_path, [entry])

        assert collect_extension_properties(hub).properties == []

    def test_one_property_merges_the_columns_that_argued_for_it(self, tmp_path):
        """The ADF-clone case: two physical tables, one concept."""
        hub = _ledger(tmp_path, [
            _entry("BLNR", name="billOfLadingNumber", table="cargo"),
            _entry("BLNR", name="billOfLadingNumber", table="cargo_clone"),
        ])

        report = collect_extension_properties(hub)

        assert len(report.properties) == 1
        assert len(report.properties[0].columns) == 2

    def test_a_decision_predating_the_structured_property_is_skipped(self, tmp_path):
        hub = _ledger(tmp_path, [_entry("BLNR", name="x", with_property=False)])

        report = collect_extension_properties(hub)

        assert report.properties == []
        assert report.decisions_seen == 1

    def test_scoping_to_a_class_set(self, tmp_path):
        hub = _ledger(tmp_path, [
            _entry("A", name="alpha", on_class=CLASS),
            _entry("B", name="beta", on_class=OTHER_CLASS),
        ])

        report = collect_extension_properties(hub, class_uris={"CargoItem": CLASS})

        assert [p.name for p in report.properties] == ["alpha"]


class TestSkipRatherThanGuess:
    def test_a_non_datatype_range_is_skipped_with_a_reason(self, tmp_path):
        hub = _ledger(tmp_path, [_entry("SHIPTYPE", name="vesselType", rng="VesselType")])

        report = collect_extension_properties(hub)

        assert report.properties == []
        assert "object property" in report.skipped[0]["reason"]

    def test_a_non_camel_case_name_is_skipped(self, tmp_path):
        hub = _ledger(tmp_path, [_entry("A", name="Bill_Of_Lading")])

        report = collect_extension_properties(hub)

        assert report.properties == []
        assert "camelCase" in report.skipped[0]["reason"]

    def test_one_name_with_two_readings_is_skipped(self, tmp_path):
        """Accepting either silently would pick a class for the reviewer."""
        hub = _ledger(tmp_path, [
            _entry("A", name="code", on_class=CLASS),
            _entry("B", name="code", on_class=OTHER_CLASS),
        ])

        report = collect_extension_properties(hub)

        assert report.properties == []
        assert "different class/range" in report.skipped[0]["reason"]


class TestRender:
    def _render(self, tmp_path, entries):
        report = collect_extension_properties(_ledger(tmp_path, entries))
        return render_extension_ttl(report, namespace="https://acme.com/ont/roro#", domain="roro")

    def test_the_declaration_carries_every_required_annotation(self, tmp_path):
        ttl = self._render(tmp_path, [_entry("BLNR", name="billOfLadingNumber")])

        assert ":billOfLadingNumber a owl:DatatypeProperty ;" in ttl
        assert 'rdfs:label "Bill of lading number"@en ;' in ttl
        assert "rdfs:comment" in ttl
        assert f"rdfs:domain <{CLASS}> ;" in ttl
        assert "rdfs:range xsd:string ." in ttl

    def test_no_source_identifier_reaches_the_comment(self, tmp_path):
        """`validate --syntax` fails a comment naming a source system (SKILL.md §5)."""
        ttl = self._render(tmp_path, [_entry("BLNR", name="billOfLadingNumber")])

        assert "src" not in ttl.split("@prefix")[-1].replace("xsd:string", "")
        assert "BLNR" not in ttl
        assert "cargo#CargoItem" in ttl  # the class URI is fine; the column name is not

    def test_the_draft_parses_as_turtle(self, tmp_path):
        rdflib = __import__("rdflib")
        ttl = self._render(tmp_path, [
            _entry("BLNR", name="billOfLadingNumber"),
            _entry("WASTEIND", name="wasteIndicator", rng="xsd:boolean"),
        ])

        graph = rdflib.Graph()
        graph.parse(data=ttl, format="turtle")

        # type, label, comment, domain, range.
        assert len(graph) == 10  # 2 properties x 5 triples

    def test_it_declares_no_ontology_of_its_own(self, tmp_path):
        """A block to paste into an authored file after review, not a file to import."""
        ttl = self._render(tmp_path, [_entry("BLNR", name="billOfLadingNumber")])

        assert "owl:Ontology" not in ttl
        assert "owl:imports" not in ttl

    def test_it_says_it_is_a_draft(self, tmp_path):
        ttl = self._render(tmp_path, [_entry("BLNR", name="billOfLadingNumber")])

        assert "DRAFT" in ttl
        assert "model/ontologies/" in ttl


class TestLocalNameResolution:
    """propose-alignment records on_class as a bare local name, not a URI (#883).

    The first cut compared those names against full anchor URIs, so nothing ever matched
    and a real hub with 501 accepted decisions rendered zero properties.
    """

    def test_a_local_name_resolves_through_the_anchor_map(self, tmp_path):
        entry = _entry("BLNR", name="billOfLadingNumber")
        entry["proposed_property"]["on_class"] = "CargoItem"
        hub = _ledger(tmp_path, [entry])

        report = collect_extension_properties(hub, class_uris={"CargoItem": CLASS})

        assert [p.on_class for p in report.properties] == [CLASS]

    def test_a_class_outside_the_domain_is_skipped_with_a_reason(self, tmp_path):
        entry = _entry("SHIPNAME", name="vesselName")
        entry["proposed_property"]["on_class"] = "Vessel"
        hub = _ledger(tmp_path, [entry])

        report = collect_extension_properties(hub, class_uris={"CargoItem": CLASS})

        assert report.properties == []
        assert "another domain" in report.skipped[0]["reason"]

    def test_no_map_means_nothing_resolves(self, tmp_path):
        entry = _entry("BLNR", name="billOfLadingNumber")
        entry["proposed_property"]["on_class"] = "CargoItem"

        report = collect_extension_properties(_ledger(tmp_path, [entry]))

        assert report.properties == []


# ---------------------------------------------------------------------------
# A range the compiler cannot emit is refused at render time (#920)
# ---------------------------------------------------------------------------


class TestCompilableRanges:
    """The allow-list was hand-maintained beside the compiler's own XSD table and drifted
    from it: it permitted `xsd:duration`, which has no canonical output type, and omitted
    four types the compiler does support. A property proposed with that range was accepted
    into the ledger, rendered into the ontology, passed `validate` clean, and failed three
    stages later with `mapping.invalid-output-type`.
    """

    def test_the_set_is_derived_from_the_compiler_not_restated(self):
        """Derived, so the two cannot drift apart again."""
        from kairos_ontology.core.extension_stubs import _compilable_xsd_ranges
        from kairos_ontology.core.projections.dbt.policy_normalize import _XSD_TYPE_KINDS

        prefix = "http://www.w3.org/2001/XMLSchema#"
        expected = {f"xsd:{uri[len(prefix):]}" for uri in _XSD_TYPE_KINDS}

        assert _compilable_xsd_ranges() == expected

    def test_duration_is_not_permitted(self):
        """The exact range that reached a real hub's ontology and failed its compile."""
        from kairos_ontology.core.extension_stubs import _compilable_xsd_ranges

        assert "xsd:duration" not in _compilable_xsd_ranges()

    def test_the_ordinary_types_are_permitted(self):
        from kairos_ontology.core.extension_stubs import _compilable_xsd_ranges

        permitted = _compilable_xsd_ranges()
        for value in ("xsd:string", "xsd:integer", "xsd:decimal", "xsd:boolean",
                      "xsd:date", "xsd:dateTime"):
            assert value in permitted

    def test_types_the_old_hand_list_omitted_are_now_permitted(self):
        from kairos_ontology.core.extension_stubs import _compilable_xsd_ranges

        permitted = _compilable_xsd_ranges()
        for value in ("xsd:int", "xsd:short", "xsd:token", "xsd:normalizedString"):
            assert value in permitted

    def test_every_permitted_range_resolves_to_an_output_type(self):
        """The property that matters: the set is not merely derived, it is correct.

        Asserted against `_target_type`, which is what the compiler resolves an XSD range
        through. `_canonical_type` is a different entry point that lower-cases its input
        before lookup, so it is the wrong thing to assert against here -- a first version
        of this test used it and failed every camel-cased type.
        """
        from kairos_ontology.core.extension_stubs import _compilable_xsd_ranges
        from kairos_ontology.core.projections.dbt.policy_normalize import _target_type

        prefix = "http://www.w3.org/2001/XMLSchema#"
        unresolved = [
            value
            for value in sorted(_compilable_xsd_ranges())
            if _target_type(prefix + value.split(":", 1)[1]) is None
        ]

        assert not unresolved, f"permitted but not resolvable: {unresolved}"

    def test_duration_does_not_resolve_to_an_output_type(self):
        """The converse, so the exclusion is justified rather than assumed."""
        from kairos_ontology.core.projections.dbt.policy_normalize import _target_type

        assert _target_type("http://www.w3.org/2001/XMLSchema#duration") is None


# ---------------------------------------------------------------------------
# A class the domain cannot resolve (#912)
# ---------------------------------------------------------------------------


class TestUnresolvableAnchorClass:
    """Global anchoring picks from the whole catalog; a domain's imports are scoped by its
    blueprint. When they disagree the failure is silent: a property declared on an
    unresolvable class renders, passes `validate` (syntax and SHACL both accept an
    `rdfs:domain` pointing anywhere), and is invisible to `generate-bindings`, which
    resolves through the domain's own closure. Measured: 33 properties, inert, until the
    missing `owl:imports` was added by hand.
    """

    @staticmethod
    def _ledger(tmp_path, on_class):
        import yaml

        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (analysis / "table-dispositions.yaml").write_text(
            yaml.dump({"schema_version": 1, "tables": [{
                "system": "sys", "table": "t", "column": "C",
                "disposition": "registered-extension",
                "proposed_property": {
                    "name": "someFlag", "range": "xsd:boolean",
                    "on_class": on_class, "why": "no reference property",
                },
            }]}),
            encoding="utf-8",
        )
        return tmp_path

    def test_a_property_on_an_unresolvable_class_is_skipped_not_rendered(self, tmp_path):
        from kairos_ontology.core.extension_stubs import collect_extension_properties

        hub = self._ledger(tmp_path, "Widget")
        uri = "https://ref.example/ont/other#Widget"

        report = collect_extension_properties(
            hub, class_uris={"Widget": uri}, unresolvable={uri}
        )

        assert [p.name for p in report.properties] == []
        assert any("import closure" in entry["reason"] for entry in report.skipped)

    def test_the_skip_says_both_ways_out(self, tmp_path):
        """Adding the import and re-anchoring are different decisions; name both."""
        from kairos_ontology.core.extension_stubs import collect_extension_properties

        hub = self._ledger(tmp_path, "Widget")
        uri = "https://ref.example/ont/other#Widget"

        report = collect_extension_properties(
            hub, class_uris={"Widget": uri}, unresolvable={uri}
        )
        note = report.skipped[0]["reason"]

        assert "owl:imports" in note
        assert "re-anchor" in note

    def test_a_resolvable_class_still_renders(self, tmp_path):
        from kairos_ontology.core.extension_stubs import collect_extension_properties

        hub = self._ledger(tmp_path, "Widget")
        uri = "https://ref.example/ont/other#Widget"

        report = collect_extension_properties(hub, class_uris={"Widget": uri}, unresolvable=set())

        assert [p.name for p in report.properties] == ["someFlag"]

    def test_the_check_is_advisory_and_never_breaks_a_render(self, tmp_path):
        """A hub mid-authoring may have no loadable master; that must cost a warning."""
        from kairos_ontology.core.extension_stubs import unresolvable_classes

        assert unresolvable_classes(tmp_path, "d", {"Widget": "https://x/#Widget"}) == set()

    def test_no_classes_means_nothing_to_check(self, tmp_path):
        from kairos_ontology.core.extension_stubs import unresolvable_classes

        assert unresolvable_classes(tmp_path, "d", {}) == set()

class TestDispositionedTablesShapeNothing:
    """#925 -- a ruled-out table still contributed anchor classes to the render."""

    def _analysis(self, tmp_path):
        import yaml as _yaml

        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True, exist_ok=True)
        (analysis / "table-anchors.yaml").write_text(
            _yaml.safe_dump(
                {
                    "schema_version": 2,
                    "tables": [
                        {"system": "src", "table": "kept", "domain": "consignment",
                         "anchor_uri": "https://ref.test/ont/consignment#Consignment"},
                        {"system": "src", "table": "ruled_out", "domain": "consignment",
                         "anchor_uri": "https://ref.test/ont/elsewhere#Gone"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return analysis

    def _rule_out(self, tmp_path, disposition="deferred"):
        import yaml as _yaml

        analysis = tmp_path / "integration" / "sources" / "_analysis"
        (analysis / "table-dispositions.yaml").write_text(
            _yaml.safe_dump(
                {
                    "schema_version": 1,
                    "tables": [{"system": "src", "table": "ruled_out",
                                "disposition": disposition, "rationale": "not modelled"}],
                }
            ),
            encoding="utf-8",
        )

    def test_a_ruled_out_table_contributes_no_anchor_class(self, tmp_path):
        from kairos_ontology.core.extension_stubs import anchor_classes_for_domain

        analysis = self._analysis(tmp_path)
        self._rule_out(tmp_path)
        classes = anchor_classes_for_domain(analysis, "consignment", hub_root=tmp_path)
        assert "Consignment" in classes
        assert "Gone" not in classes, (
            "a property rendered on it points outside the domain's imports and only "
            "ever fails validate"
        )

    def test_without_a_hub_root_the_ledger_cannot_be_found(self, tmp_path):
        from kairos_ontology.core.extension_stubs import anchor_classes_for_domain

        analysis = self._analysis(tmp_path)
        self._rule_out(tmp_path)
        assert "Gone" in anchor_classes_for_domain(analysis, "consignment")

    def test_bound_is_not_a_non_generating_disposition(self, tmp_path):
        from kairos_ontology.core.extension_stubs import anchor_classes_for_domain

        analysis = self._analysis(tmp_path)
        self._rule_out(tmp_path, disposition="bound")
        assert "Gone" in anchor_classes_for_domain(analysis, "consignment", hub_root=tmp_path)
