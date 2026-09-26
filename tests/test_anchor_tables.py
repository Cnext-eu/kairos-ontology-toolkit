# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Global table anchoring (DD-185).

The testbed facts these tests pin: ownership marks in the catalog are what took
known-answer accuracy from 5/6 to 6/6; sample values in the anchor prompt cost
accuracy (5/6) and tokens, so the outline is names-only; invented class names
must be rejected, never kept; and domain derivation must be bridge-aware so a
table anchored to a bridged class stays in the bridging domain instead of being
moved to the owner (a grain error).
"""

from unittest.mock import MagicMock, patch

import yaml

from kairos_ontology.core.anchor_tables import (
    ANCHOR_CONFIDENCE_FLOOR,
    ANCHORS_FILENAME,
    ClassCatalog,
    anchor_response_schema,
    build_anchor_prompt,
    derive_domain,
    load_table_anchors,
)


def _recorder(lines):
    """A report callback with the level parameter run_anchor_tables passes (#1039)."""
    return lambda message, level="info": lines.append(message)


def catalog(**bridged):
    return ClassCatalog(
        text="- TransportCall [owned by domain 'route-schedule']: A call at a location.\n"
        "- Consignment [owned by domain 'consignment']: Goods moving together.\n"
        "- Widget [UNOWNED]: A thing.",
        index={
            "TransportCall": [
                {"module": "https://ex.org/tc", "uri": "https://ex.org/tc#TransportCall"}
            ],
            "Consignment": [
                # Deliberately two copies, the unowned one first: the live defect
                # was ownership derived from an arbitrary single copy.
                {"module": "https://ex.org/other", "uri": "https://ex.org/other#Consignment"},
                {"module": "https://ex.org/cons", "uri": "https://ex.org/cons#Consignment"},
            ],
            "Widget": [{"module": "https://ex.org/w", "uri": "https://ex.org/w#Widget"}],
        },
        owners={"https://ex.org/tc": ["route-schedule"], "https://ex.org/cons": ["consignment"]},
        bridged_from=bridged.get("bridged_from", {}),
    )


class TestDomainDerivation:
    def test_owner_wins_when_unambiguous(self):
        domain, basis, owners, bridged = derive_domain("Consignment", catalog())
        assert (domain, basis) == ("consignment", "owner")

    def test_bridge_keeps_the_table_in_the_bridging_domain(self):
        """The stops case: consignment bridges to TransportCall, route-schedule owns it.
        Affinity says consignment — the table must NOT move to the owner."""
        cat = catalog(bridged_from={"https://ex.org/tc#TransportCall": ["consignment"]})
        domain, basis, _, _ = derive_domain("TransportCall", cat, affinity_domain="consignment")
        assert domain == "consignment"
        assert basis == "bridge+affinity"

    def test_owner_wins_without_an_affinity_prior(self):
        cat = catalog(bridged_from={"https://ex.org/tc#TransportCall": ["consignment"]})
        domain, basis, _, _ = derive_domain("TransportCall", cat)
        assert (domain, basis) == ("route-schedule", "owner")

    def test_affinity_outside_the_candidates_does_not_win(self):
        """Affinity is a tie-break within legitimate candidates, not a veto."""
        domain, basis, _, _ = derive_domain("Consignment", catalog(), affinity_domain="party")
        assert (domain, basis) == ("consignment", "owner")

    def test_unowned_anchor_keeps_affinity_and_is_flagged(self):
        """The extension worklist: a real class no domain imports."""
        domain, basis, owners, bridged = derive_domain("Widget", catalog(), affinity_domain="party")
        assert (domain, basis) == ("party", "unowned")
        assert owners == [] and bridged == []


_ADDRESS = "https://onerecord/cargo#Address"


def shared_catalog():
    """The #1040 shape: two domains own the OneRecord cargo module."""
    return ClassCatalog(
        text="- Address [owned by domain 'booking', 'reference-data']: A postal address.",
        index={"Address": [{"module": "https://onerecord/cargo", "uri": _ADDRESS}]},
        owners={"https://onerecord/cargo": ["booking", "reference-data"]},
    )


class TestSharedOwnerTieBreak:
    """DD-247: several owners, affinity names none of them (#1040)."""

    def test_a_hub_domain_subclassing_the_anchor_wins_even_as_a_non_owner(self):
        domain, basis, owners, _ = derive_domain(
            "Address", shared_catalog(), affinity_domain="party",
            hub_subclass_domains={_ADDRESS: {"party"}},
        )
        assert (domain, basis) == ("party", "hub-subclass")
        assert owners == ["booking", "reference-data"]

    def test_among_subclassing_domains_an_owner_beats_the_alphabet(self):
        domain, basis, _, _ = derive_domain(
            "Address", shared_catalog(), affinity_domain="claims",
            hub_subclass_domains={_ADDRESS: {"reference-data", "party"}},
        )
        assert (domain, basis) == ("reference-data", "hub-subclass")

    def test_a_secondary_affinity_owner_breaks_the_tie(self):
        domain, basis, _, _ = derive_domain(
            "Address", shared_catalog(), affinity_domain="party",
            secondary_domains=("claims", "reference-data"),
        )
        assert (domain, basis) == ("reference-data", "owner+secondary")

    def test_without_evidence_the_first_owner_is_kept(self):
        """Kept, not replaced by affinity: the affinity pool may not reach the anchor."""
        domain, basis, _, _ = derive_domain("Address", shared_catalog(), affinity_domain="party")
        assert (domain, basis) == ("booking", "owner")

    def test_affinity_among_the_owners_still_wins_first(self):
        domain, basis, _, _ = derive_domain(
            "Address", shared_catalog(), affinity_domain="reference-data",
            hub_subclass_domains={_ADDRESS: {"booking"}},
        )
        assert (domain, basis) == ("reference-data", "owner+affinity")

    def test_a_single_owner_is_never_overruled(self):
        domain, basis, _, _ = derive_domain(
            "Consignment", catalog(), affinity_domain="party",
            secondary_domains=("party",),
            hub_subclass_domains={"https://ex.org/cons#Consignment": {"party"}},
        )
        assert (domain, basis) == ("consignment", "owner")


class TestHubSubclassEvidence:
    PREFIXES = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    )

    def _hub(self, tmp_path, name, body):
        ontologies = tmp_path / "model" / "ontologies"
        ontologies.mkdir(parents=True, exist_ok=True)
        (ontologies / f"{name}.ttl").write_text(
            self.PREFIXES
            + f"<https://hub/{name}> a owl:Ontology .\n"
            + body.format(ns=f"https://hub/{name}#"),
            encoding="utf-8",
        )
        return tmp_path

    def test_subclass_of_counts(self, tmp_path):
        from kairos_ontology.core.anchor_tables import load_hub_subclass_domains

        hub = self._hub(tmp_path, "party",
                        f"<{{ns}}PartyAddress> a owl:Class ; rdfs:subClassOf <{_ADDRESS}> .\n")
        assert load_hub_subclass_domains(hub, {"party"}) == {_ADDRESS: {"party"}}

    def test_equivalent_class_does_not_count(self, tmp_path):
        """Not a compile anchor (#730), so not evidence of ownership either."""
        from kairos_ontology.core.anchor_tables import load_hub_subclass_domains

        hub = self._hub(tmp_path, "party",
                        f"<{{ns}}PartyAddress> a owl:Class ; owl:equivalentClass <{_ADDRESS}> .\n")
        assert load_hub_subclass_domains(hub, {"party"}) == {}

    def test_unknown_domains_and_broken_files_are_no_evidence(self, tmp_path):
        from kairos_ontology.core.anchor_tables import load_hub_subclass_domains

        hub = self._hub(tmp_path, "shared",
                        f"<{{ns}}X> a owl:Class ; rdfs:subClassOf <{_ADDRESS}> .\n")
        (hub / "model" / "ontologies" / "party.ttl").write_text("not turtle {", encoding="utf-8")
        assert load_hub_subclass_domains(hub, {"party"}) == {}
        assert load_hub_subclass_domains(tmp_path / "nowhere", {"party"}) == {}


class TestOwnerAmbiguousFlag:
    def _run(self, tmp_path, affinity=None):
        import json

        from kairos_ontology.core import anchor_tables as at

        vocab = tmp_path / "sources" / "cw" / "vocabulary"
        vocab.mkdir(parents=True)
        (vocab / "orgaddress.vocabulary.ttl").write_text("# no triples\n", encoding="utf-8")
        if affinity is not None:
            analysis = tmp_path / "_analysis"
            analysis.mkdir()
            (analysis / "src-cw.affinity.yaml").write_text(
                yaml.safe_dump({"system": "cw", "tables": [{"table": "orgaddress", **affinity}]}),
                encoding="utf-8",
            )
        client = MagicMock()
        message = MagicMock()
        message.content = json.dumps({"anchors": {"cw.orgaddress": {
            "anchor": "Address", "alternate": None, "confidence": 0.9,
            "grain_columns": ["pk"], "natural_key": ["pk"], "load_hint": "scd"}}})
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=message)]
        )
        lines: list[str] = []
        with patch.object(at, "build_class_catalog", return_value=shared_catalog()), \
                patch.object(at, "build_source_outline",
                             return_value=[("cw", "orgaddress", ["pk", "street"])]):
            out = at.run_anchor_tables(
                client=client, model="m",
                sources_dir=tmp_path / "sources",
                catalog_path=tmp_path / "catalog.xml",
                ref_models_dir=None, accelerator=None,
                analysis_dir=tmp_path / "_analysis",
                report=lambda message, level="info": lines.append((message, level)),
            )
        return yaml.safe_load(out.read_text(encoding="utf-8"))["tables"][0], lines

    def test_an_unresolved_tie_is_flagged_and_reported(self, tmp_path):
        from kairos_ontology.core.anchor_tables import OWNER_AMBIGUOUS_FLAG

        entry, lines = self._run(tmp_path, {"domain": "party"})
        assert entry["domain"] == "booking" and entry["domain_basis"] == "owner"
        assert OWNER_AMBIGUOUS_FLAG in entry["flags"]
        assert any("cw.orgaddress" in line and "owners: booking, reference-data" in line
                   and level == "warning" for line, level in lines), "survives --quiet"

    def test_a_secondary_affinity_resolves_it_without_a_flag(self, tmp_path):
        """The shape analyse-sources writes: one mapping per secondary domain."""
        from kairos_ontology.core.anchor_tables import OWNER_AMBIGUOUS_FLAG

        entry, _ = self._run(tmp_path, {"domain": "party", "secondary_domains": [
            {"domain": "customs", "domain_group": "compliance", "domain_uris": ["https://x#"]},
            {"domain": "reference-data", "domain_group": "visibility-events",
             "domain_uris": ["https://onerecord/cargo#"]},
        ]})
        assert (entry["domain"], entry["domain_basis"]) == ("reference-data", "owner+secondary")
        assert OWNER_AMBIGUOUS_FLAG not in entry["flags"]

    def test_bare_secondary_domain_ids_are_read_too(self, tmp_path):
        entry, _ = self._run(
            tmp_path, {"domain": "party", "secondary_domains": ["reference-data"]}
        )
        assert entry["domain_basis"] == "owner+secondary"


class TestPrompt:
    CHUNK = [("qargo", "stops", ["stop_id", "arrival_time"])]

    def test_contains_every_table_and_the_catalog(self):
        text = build_anchor_prompt(self.CHUNK, catalog(), 3)
        assert "TABLE qargo.stops (2 columns): stop_id, arrival_time" in text
        assert "TransportCall [owned by domain 'route-schedule']" in text

    def test_carries_the_anchoring_pattern_rules(self):
        text = build_anchor_prompt(self.CHUNK, catalog(), 3)
        assert "subclass-identity-by-role" in text
        assert "governed-code-list" in text
        assert "ONE ROW" in text

    def test_no_sample_values_anywhere(self):
        """Tested: samples cost accuracy (5/6 vs 6/6) and ~7k tokens here."""
        text = build_anchor_prompt(self.CHUNK, catalog(), 3)
        assert "samples" not in text.lower()

    def test_prefers_owned_classes_explicitly(self):
        assert "UNOWNED" in build_anchor_prompt(self.CHUNK, catalog(), 3)


class TestResponseSchema:
    def test_every_table_is_a_required_key(self):
        """The DD-177 shape: omitting a table is a schema violation."""
        fmt = anchor_response_schema(["qargo.stops", "qargo.orders"])
        anchors = fmt["json_schema"]["schema"]["properties"]["anchors"]
        assert anchors["required"] == ["qargo.stops", "qargo.orders"]
        assert anchors["additionalProperties"] is False

    def test_class_names_are_free_strings_not_enums(self):
        """1,275 candidates exceed the provider's 1,000-value enum budget (DD-177)."""
        fmt = anchor_response_schema(["t"])
        verdict = fmt["json_schema"]["schema"]["$defs"]["Verdict"]["properties"]
        assert "enum" not in verdict["anchor"]

    def test_binding_skeleton_fields_are_required(self):
        fmt = anchor_response_schema(["t"])
        verdict = fmt["json_schema"]["schema"]["$defs"]["Verdict"]
        for f in ("grain_columns", "natural_key", "load_hint"):
            assert f in verdict["required"]


class TestRunAndArtifact:
    def _run(self, tmp_path, response_anchors):
        from kairos_ontology.core import anchor_tables as at

        vocab = tmp_path / "sources" / "qargo" / "vocabulary"
        vocab.mkdir(parents=True)
        # Parseable-but-empty: the outline is patched below, but the
        # schema-catalogue screen reads the vocabularies for real.
        (vocab / "stops.vocabulary.ttl").write_text("# no triples\n", encoding="utf-8")

        client = MagicMock()
        message = MagicMock()
        message.content = str(response_anchors).replace("'", '"').replace("None", "null")
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=message)]
        )
        with patch.object(at, "build_class_catalog", return_value=catalog(
            bridged_from={"https://ex.org/tc#TransportCall": ["consignment"]}
        )), patch.object(
            at, "build_source_outline",
            return_value=[("qargo", "stops", ["stop_id", "arrival_time"])],
        ):
            return at.run_anchor_tables(
                client=client, model="m",
                sources_dir=tmp_path / "sources",
                catalog_path=tmp_path / "catalog.xml",
                ref_models_dir=None, accelerator=None,
                analysis_dir=tmp_path / "_analysis",
            )

    def test_writes_a_provenance_stamped_loadable_artifact(self, tmp_path):
        out = self._run(tmp_path, {"anchors": {"qargo.stops": {
            "anchor": "TransportCall", "alternate": None, "confidence": 0.91,
            "grain_columns": ["stop_id"], "natural_key": ["stop_id"], "load_hint": "scd"}}})
        text = out.read_text(encoding="utf-8")
        assert "AI-ASSISTED" in text, "model-authored artifact must say so (DD-178)"
        anchors = load_table_anchors(tmp_path / "_analysis")
        entry = anchors[("qargo", "stops")]
        assert entry["anchor"] == "TransportCall"
        assert entry["grain_columns"] == ["stop_id"]
        assert entry["domain"] == "route-schedule"  # owner; no affinity prior in test

    def test_invented_class_names_are_rejected_with_evidence(self, tmp_path):
        out = self._run(tmp_path, {"anchors": {"qargo.stops": {
            "anchor": "MadeUpClass", "alternate": None, "confidence": 0.9,
            "grain_columns": [], "natural_key": [], "load_hint": None}}})
        doc = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert doc["tables"] == []
        assert "MadeUpClass" in doc["unanchored"][0]["note"]

    def test_null_anchor_lands_in_unanchored(self, tmp_path):
        out = self._run(tmp_path, {"anchors": {"qargo.stops": {
            "anchor": None, "alternate": None, "confidence": 0.1,
            "grain_columns": [], "natural_key": [], "load_hint": None}}})
        doc = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert len(doc["unanchored"]) == 1

    def test_loader_is_empty_when_no_artifact(self, tmp_path):
        assert load_table_anchors(tmp_path) == {}


class TestCliReRun:
    """#1039: core passes a level with drift and skipped-ruling lines; the CLI
    callback took one argument, so every re-run crashed after the model spend and
    before the anchors file was written."""

    VERDICT = {"anchors": {"qargo.stops": {
        "anchor": "TransportCall", "alternate": None, "confidence": 0.91,
        "grain_columns": ["stop_id"], "natural_key": ["stop_id"], "load_hint": "scd"}}}

    def _invoke(self, tmp_path, monkeypatch, *extra):
        import json

        from click.testing import CliRunner

        from kairos_ontology.cli import sources as cli_sources
        from kairos_ontology.core import anchor_tables as at

        vocab = tmp_path / "sources" / "qargo" / "vocabulary"
        vocab.mkdir(parents=True, exist_ok=True)
        (vocab / "stops.vocabulary.ttl").write_text("# no triples\n", encoding="utf-8")
        (tmp_path / "catalog.xml").write_text("<catalog/>", encoding="utf-8")

        client = MagicMock()
        message = MagicMock()
        message.content = json.dumps(self.VERDICT)
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=message)]
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "kairos_ontology.core.ai_preflight.require_ai_provider", lambda *a, **k: None
        )
        monkeypatch.setattr(
            "kairos_ontology.core.ai_provider.get_ai_client", lambda *a, **k: client
        )
        monkeypatch.setattr(cli_sources, "require_business_discovery", lambda *a, **k: None)
        monkeypatch.setattr(at, "build_class_catalog", lambda *a, **k: catalog())
        monkeypatch.setattr(
            at, "build_source_outline",
            lambda *a, **k: [("qargo", "stops", ["stop_id", "arrival_time"])],
        )
        return CliRunner().invoke(
            cli_sources.anchor_tables_cmd,
            [
                "--sources", str(tmp_path / "sources"),
                "--analysis", str(tmp_path / "_analysis"),
                "--catalog", str(tmp_path / "catalog.xml"),
                "--accelerator", "logistics",
                "--model", "m",
                *extra,
            ],
        )

    def test_a_re_run_reports_drift_and_rewrites_the_anchors(self, tmp_path, monkeypatch):
        first = self._invoke(tmp_path, monkeypatch)
        assert first.exit_code == 0, first.output
        out = tmp_path / "_analysis" / ANCHORS_FILENAME
        out.write_text(out.read_text(encoding="utf-8") + "# marker\n", encoding="utf-8")

        second = self._invoke(tmp_path, monkeypatch)
        assert second.exit_code == 0, second.output
        assert "# marker" not in out.read_text(encoding="utf-8"), "anchors file rewritten"
        assert "drift" in second.output.lower()

    def test_a_skipped_ruling_is_reported_even_under_quiet(self, tmp_path, monkeypatch):
        rulings = tmp_path / "discovery" / "design-rulings.yaml"
        rulings.parent.mkdir(parents=True)
        rulings.write_text("not: a list\n", encoding="utf-8")

        result = self._invoke(tmp_path, monkeypatch, "--quiet")
        assert result.exit_code == 0, result.output
        assert "ruling <file> skipped" in result.output
        assert "Anchoring tables in" not in result.output, "info lines stay quiet"


class TestAlignmentConsumption:
    """The floor and pool checks in _propose_alignments, tested at their contract."""

    def test_floor_constant_is_sane(self):
        assert 0 < ANCHOR_CONFIDENCE_FLOOR < 1

    def test_anchored_status_is_distinct_from_confirmed(self):
        """An LLM anchor must never masquerade as a human confirmation."""
        from kairos_ontology.core.propose_alignment import align_table
        import inspect

        sig = inspect.signature(align_table)
        assert sig.parameters["anchor_status"].default == "confirmed"
        assert sig.parameters["anchor_confidence"].default is None

    def test_artifact_filename_is_stable(self):
        assert ANCHORS_FILENAME == "hub.table-anchors.yaml"


class TestExcludedColumns:
    """DD-164 column dispositions feed the anchor prompt (the tenant_id case)."""

    def _ledger(self, tmp_path, entries):
        import yaml as _y

        (tmp_path / "table-dispositions.yaml").write_text(
            _y.safe_dump({"tables": entries}), encoding="utf-8"
        )
        from kairos_ontology.core.anchor_tables import load_excluded_columns

        return load_excluded_columns(tmp_path)

    def test_not_business_data_columns_are_excluded(self, tmp_path):
        excluded = self._ledger(
            tmp_path,
            [{"system": "qargo", "table": "stops", "column": "tenant_id",
              "disposition": "not-business-data"}],
        )
        assert ("qargo", "stops", "tenant_id") in excluded

    def test_system_wide_wildcard_excludes_everywhere(self, tmp_path):
        """A SaaS tenant discriminator appears in every table the vendor ships."""
        from kairos_ontology.core.anchor_tables import _is_excluded

        excluded = self._ledger(
            tmp_path,
            [{"system": "qargo", "table": "", "column": "tenant_id",
              "disposition": "not-business-data"}],
        )
        assert _is_excluded(excluded, "qargo", "stops", "tenant_id")
        assert _is_excluded(excluded, "qargo", "companies", "tenant_id")
        assert not _is_excluded(excluded, "qlik", "orders", "tenant_id")

    def test_table_dispositions_without_column_do_not_exclude(self, tmp_path):
        """Table-grain scope decisions are a different mechanism; leave them alone."""
        assert self._ledger(
            tmp_path,
            [{"system": "qargo", "table": "stops", "disposition": "not-business-data"}],
        ) == set()

    def test_outline_drops_excluded_columns(self, tmp_path, monkeypatch):
        from kairos_ontology.core import anchor_tables as at

        vocab = tmp_path / "qargo" / "vocabulary"
        vocab.mkdir(parents=True)
        (vocab / "stops.vocabulary.ttl").write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            at, "parse_source_vocabulary",
            lambda _p: {"stops": [{"name": "tenant_id"}, {"name": "stop_id"}]},
        )
        outline = at.build_source_outline(
            tmp_path, excluded_columns={("qargo", "", "tenant_id")}
        )
        assert outline == [("qargo", "stops", ["stop_id"])]


class TestDuplicateNameDerivation:
    def test_ownership_aggregates_across_copies(self):
        """Consignment exists in an unowned module AND mmt/consignment; the owned
        copy must decide, whatever order the copies arrived in."""
        domain, basis, owners, _ = derive_domain("Consignment", catalog())
        assert (domain, basis) == ("consignment", "owner")
        assert owners == ["consignment"]


def collision_catalog():
    """Two ``Booking`` copies, both owned by ``booking`` — the live #519 shape.

    The property-free copy is FIRST, because that is what made the live defect:
    ownership could not separate the copies, so read order decided and
    ``onerecord/cargo#Booking`` (zero properties in closure) won over
    ``dcsa/booking#Booking`` (23).
    """
    return ClassCatalog(
        text="- Booking [owned by domain 'booking']: A booking.",
        index={
            "Booking": [
                {"module": "https://onerecord/cargo", "uri": "https://onerecord/cargo#Booking",
                 "properties": []},
                {"module": "https://dcsa/booking", "uri": "https://dcsa/booking#Booking",
                 "properties": ["bookingStatus", "carrierBookingReference", "vesselName"]},
            ],
            "Widget": [
                {"module": "https://ex.org/w", "uri": "https://ex.org/w#Widget",
                 "properties": ["carrierBookingReference", "vesselName", "bookingStatus"]},
            ],
        },
        owners={"https://onerecord/cargo": ["booking"], "https://dcsa/booking": ["booking"]},
    )


BOOKING_COLUMNS = ["booking_id", "booking_status", "carrier_booking_reference", "vessel_name"]


class TestClassCopySelection:
    """#519 part 1: a name collision must not be decided by catalog read order."""

    def test_property_overlap_breaks_a_name_collision(self):
        """Both copies owned by 'booking'; only one can carry the table's columns."""
        from kairos_ontology.core.anchor_tables import choose_class_copy

        cat = collision_catalog()
        chosen = choose_class_copy(cat.index["Booking"], cat, "booking", BOOKING_COLUMNS)
        assert chosen["uri"] == "https://dcsa/booking#Booking"

    def test_ownership_still_outranks_overlap(self):
        """A perfect-overlap class in a module no domain owns must not win: the
        ownership mark is what took the tested call from 5/6 to 6/6."""
        from kairos_ontology.core.anchor_tables import choose_class_copy

        cat = collision_catalog()
        copies = cat.index["Booking"] + cat.index["Widget"]
        chosen = choose_class_copy(copies, cat, "booking", BOOKING_COLUMNS)
        assert chosen["uri"] == "https://dcsa/booking#Booking"

    def test_property_count_breaks_a_zero_overlap_tie(self):
        from kairos_ontology.core.anchor_tables import choose_class_copy

        cat = collision_catalog()
        chosen = choose_class_copy(cat.index["Booking"], cat, "booking", ["unrelated_field"])
        assert chosen["uri"] == "https://dcsa/booking#Booking"

    def test_overlap_ignores_generic_tokens(self):
        """'id'/'name'/'code' match nearly every class and must not score."""
        from kairos_ontology.core.anchor_tables import column_property_overlap

        copy = {"properties": ["orderName", "orderCode"]}
        assert column_property_overlap(["shipment_name", "shipment_code"], copy) == 0
        assert column_property_overlap(["order_reference"], copy) == 1

    def test_no_properties_means_no_overlap(self):
        from kairos_ontology.core.anchor_tables import column_property_overlap

        assert column_property_overlap(BOOKING_COLUMNS, {"properties": []}) == 0


def cross_domain_person_catalog():
    """A name collides across copies owned by two DIFFERENT domains — the #564
    shape. A bare IATA ``Person`` (owned only by ``party``, no properties) vs. a
    richer BSP ``Person`` (owned only by ``financial``, several properties).
    Neither domain owns the other's copy at all."""
    return ClassCatalog(
        text="- Person [owned by domain 'party']: A person.",
        index={
            "Person": [
                {"module": "https://iata/party", "uri": "https://iata/party#Person",
                 "properties": []},
                {"module": "https://bsp/financial", "uri": "https://bsp/financial#Person",
                 "properties": ["firstName", "lastName", "taxId"]},
            ],
        },
        owners={"https://iata/party": ["party"], "https://bsp/financial": ["financial"]},
    )


PERSON_COLUMNS = ["first_name", "last_name", "tax_id"]


class TestClassCopySelectionAcrossDomains:
    """#564: a same-domain hard pre-filter must not discard a richer copy owned
    by a DIFFERENT domain before richness is ever compared."""

    def test_a_richer_copy_owned_by_a_different_domain_still_wins_on_overlap(self):
        """Anchoring domain is 'party' (owns only the empty copy); the richer BSP
        copy, owned only by 'financial', must still win because its properties
        actually overlap the table's columns."""
        from kairos_ontology.core.anchor_tables import choose_class_copy

        cat = cross_domain_person_catalog()
        chosen = choose_class_copy(cat.index["Person"], cat, "party", PERSON_COLUMNS)
        assert chosen["uri"] == "https://bsp/financial#Person"

    def test_a_richer_copy_owned_by_a_different_domain_still_wins_on_property_count(self):
        """Even with zero column overlap, the richer copy wins on property count
        -- same-domain ownership only breaks a tie on both of those, it never
        pre-filters the richer copy out."""
        from kairos_ontology.core.anchor_tables import choose_class_copy

        cat = cross_domain_person_catalog()
        chosen = choose_class_copy(cat.index["Person"], cat, "party", ["unrelated_field"])
        assert chosen["uri"] == "https://bsp/financial#Person"

    def test_same_domain_ownership_breaks_a_genuine_tie(self):
        """Equal overlap AND equal property count: same-domain ownership is the
        deciding tie-break, not irrelevant."""
        from kairos_ontology.core.anchor_tables import choose_class_copy

        cat = ClassCatalog(
            text="- Person [owned by domain 'party']: A person.",
            index={
                "Person": [
                    {"module": "https://iata/party", "uri": "https://iata/party#Person",
                     "properties": ["firstName", "lastName"]},
                    {"module": "https://bsp/financial", "uri": "https://bsp/financial#Person",
                     "properties": ["firstName", "lastName"]},
                ],
            },
            owners={"https://iata/party": ["party"], "https://bsp/financial": ["financial"]},
        )
        chosen = choose_class_copy(cat.index["Person"], cat, "party", ["unrelated_field"])
        assert chosen["uri"] == "https://iata/party#Person"


class TestPropertylessAnchorWarning:
    """#519 part 1, the floor: a 90-column table pinned to a class with no
    properties produced no class at all, silently."""

    def _run(self, tmp_path, cat, columns, anchor):
        import json

        from kairos_ontology.core import anchor_tables as at

        vocab = tmp_path / "sources" / "qargo" / "vocabulary"
        vocab.mkdir(parents=True)
        (vocab / "bookings.vocabulary.ttl").write_text("# no triples\n", encoding="utf-8")

        client = MagicMock()
        message = MagicMock()
        message.content = json.dumps(
            {"anchors": {"qargo.bookings": {
                "anchor": anchor, "alternate": None, "confidence": 0.98,
                "grain_columns": ["booking_id"], "natural_key": ["booking_id"],
                "load_hint": "scd"}}}
        )
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=message)]
        )
        lines: list[str] = []
        with patch.object(at, "build_class_catalog", return_value=cat), patch.object(
            at, "build_source_outline", return_value=[("qargo", "bookings", columns)]
        ):
            out = at.run_anchor_tables(
                client=client, model="m",
                sources_dir=tmp_path / "sources",
                catalog_path=tmp_path / "catalog.xml",
                ref_models_dir=None, accelerator=None,
                analysis_dir=tmp_path / "_analysis",
                report=_recorder(lines),
            )
        return yaml.safe_load(out.read_text(encoding="utf-8")), lines

    def test_the_artifact_records_the_property_bearing_copy(self, tmp_path):
        doc, _ = self._run(tmp_path, collision_catalog(), BOOKING_COLUMNS, "Booking")
        entry = doc["tables"][0]
        assert entry["anchor_uri"] == "https://dcsa/booking#Booking"
        assert entry["anchor_properties"] == 3
        assert entry["anchor_column_overlap"] >= 1
        assert "warning" not in entry

    def test_a_propertyless_anchor_is_flagged_loudly(self, tmp_path):
        cat = collision_catalog()
        cat.index["Booking"] = [cat.index["Booking"][0]]  # only the empty copy resolves
        doc, lines = self._run(tmp_path, cat, BOOKING_COLUMNS, "Booking")
        entry = doc["tables"][0]
        assert entry["anchor_properties"] == 0
        assert "no properties in the resolved closure" in entry["warning"]
        assert any("WARNING" in line and "NO properties" in line for line in lines)

    def test_a_propertyless_anchor_carries_a_deterministic_sheet_flag(self, tmp_path):
        """#564: the console-only warning must also survive into the reviewable
        table-anchors.yaml artifact as a flag, not just a printed line."""
        from kairos_ontology.core.anchor_tables import PROPERTY_LESS_ANCHOR_FLAG

        cat = collision_catalog()
        cat.index["Booking"] = [cat.index["Booking"][0]]
        doc, _ = self._run(tmp_path, cat, BOOKING_COLUMNS, "Booking")
        entry = doc["tables"][0]
        assert PROPERTY_LESS_ANCHOR_FLAG in entry["flags"]

    def test_a_property_bearing_anchor_carries_no_such_flag(self, tmp_path):
        from kairos_ontology.core.anchor_tables import PROPERTY_LESS_ANCHOR_FLAG

        doc, _ = self._run(tmp_path, collision_catalog(), BOOKING_COLUMNS, "Booking")
        entry = doc["tables"][0]
        assert PROPERTY_LESS_ANCHOR_FLAG not in entry["flags"]

    def test_a_columnless_table_is_not_warned_about(self, tmp_path):
        """Only a table WITH columns makes a propertyless anchor wrong."""
        cat = collision_catalog()
        cat.index["Booking"] = [cat.index["Booking"][0]]
        doc, lines = self._run(tmp_path, cat, [], "Booking")
        assert "warning" not in doc["tables"][0]
        assert not any("WARNING" in line for line in lines)


def _cols(*specs):
    """``("name", "sample|sample")`` pairs into profiler column dicts."""
    return [
        {"name": name, "samples": samples.split("|") if samples else []}
        for name, samples in specs
    ]


class TestSchemaCatalogueScreen:
    """#519 part 2: the source's description of its own schema is not business data.

    A false positive here silently deletes a real business table before anyone
    sees it, so every rule is deliberately steep and every exclusion carries its
    evidence. Validated against the live 75-table hub: exactly the four
    "Qargo Tables Columns Info" sheets, nothing else.
    """

    def _detect(self, tables, decided=None):
        from kairos_ontology.core.anchor_tables import detect_schema_catalogue_tables

        return {e["table"]: e for e in detect_schema_catalogue_tables(tables, decided)}

    ALL_TABLE_COLUMN = ("qargo", "Qargo Tables Columns Info__AllTableColumn", _cols(
        ("table_name", ""), ("column_name", ""), ("data_type", ""),
        ("ordinal_position", ""), ("is_nullable", ""), ("column_default", ""),
    ))
    ALL_TABLES = ("qargo", "Qargo Tables Columns Info__AllTables", _cols(
        ("table_name", "bookings|orders|stops|companies|contacts|goods"),
    ))
    ORDERS = ("qargo", "orders", _cols(("order_id", "1|2"), ("customer_name", "Acme")))
    BOOKINGS = ("qargo", "bookings", _cols(("booking_id", "1")))
    STOPS = ("qargo", "stops", _cols(("stop_id", "1")))
    COMPANIES = ("qargo", "companies", _cols(("company_id", "1")))
    CONTACTS = ("qargo", "contacts", _cols(("contact_id", "1")))
    GOODS = ("qargo", "goods", _cols(("goods_id", "1")))
    BUSINESS = [ORDERS, BOOKINGS, STOPS, COMPANIES, CONTACTS, GOODS]

    def test_an_information_schema_table_is_excluded(self):
        found = self._detect([self.ALL_TABLE_COLUMN, *self.BUSINESS])
        assert "information-schema fields" in found[self.ALL_TABLE_COLUMN[1]]["reason"]
        assert found[self.ALL_TABLE_COLUMN[1]]["disposition"] == "not-business-data"

    def test_a_table_whose_rows_name_other_tables_is_excluded(self):
        found = self._detect([self.ALL_TABLES, *self.BUSINESS])
        assert "names of 6 other tables" in found[self.ALL_TABLES[1]]["reason"]

    def test_business_tables_are_never_touched(self):
        found = self._detect([self.ALL_TABLE_COLUMN, self.ALL_TABLES, *self.BUSINESS])
        assert set(found) == {self.ALL_TABLE_COLUMN[1], self.ALL_TABLES[1]}

    def test_a_business_table_with_a_name_column_is_kept(self):
        """The stated false positive to avoid: 'name' is not evidence of anything."""
        lookup = ("qargo", "order_types", _cols(("name", "standard|express"), ("code", "S|E")))
        assert self._detect([lookup, *self.BUSINESS]) == {}

    def test_a_wide_table_holding_table_names_is_kept(self):
        """A polymorphic audit/comment table legitimately records entity names;
        only a table whose ENTIRE content is a list of tables is a catalogue."""
        audit = ("qargo", "audit_log", _cols(
            ("entity", "bookings|orders|stops|companies|contacts|goods"),
            ("actor", "ada"), ("action", "update"), ("at", "2026-01-01"),
            ("before", "{}"), ("after", "{}"),
        ))
        assert self._detect([audit, *self.BUSINESS]) == {}

    def test_two_catalogue_columns_are_not_enough(self):
        """A shipping table recording a data_type and a column_name is not a catalogue."""
        near = ("qargo", "field_overrides", _cols(
            ("column_name", ""), ("data_type", ""), ("order_id", ""), ("override", ""),
        ))
        assert self._detect([near, *self.BUSINESS]) == {}

    def test_a_sibling_sheet_of_a_proven_catalogue_workbook_is_excluded(self):
        """The __orders_table case: its own columns look exactly like business
        data — nothing is suspicious about it except the company it keeps."""
        sheet = ("qargo", "Qargo Tables Columns Info__orders_table", _cols(
            ("order_id", "1"), ("customer_name", "Acme"), ("total_price", "10"),
        ))
        found = self._detect([self.ALL_TABLE_COLUMN, sheet, *self.BUSINESS])
        assert "shown to be a schema catalogue by sibling sheet" in found[sheet[1]]["reason"]

    def test_a_sheet_of_a_business_workbook_is_kept(self):
        """Same shape, workbook name that claims nothing about schemas."""
        proven = ("qlik", "Margins 2025__AllTableColumn", self.ALL_TABLE_COLUMN[2])
        sheet = ("qlik", "Margins 2025__Containers", _cols(("unit", "40ft"), ("margin", "3")))
        found = self._detect([proven, sheet])
        assert sheet[1] not in found
        assert proven[1] in found, "the catalogue sheet itself still goes"

    def test_the_sibling_rule_does_not_chain(self):
        """A sheet excluded BY the sibling rule is not evidence for anything else."""
        sheet_a = ("qargo", "Tables And Columns__extract_a", _cols(("a", "1")))
        sheet_b = ("qargo", "Tables And Columns__extract_b", _cols(("b", "1")))
        assert self._detect([sheet_a, sheet_b]) == {}

    def test_a_recorded_disposition_overrules_the_heuristic(self):
        """Someone already decided this table is in scope; a heuristic does not
        get to overturn a ledger entry."""
        found = self._detect(
            [self.ALL_TABLES, *self.BUSINESS],
            {("qargo", self.ALL_TABLES[1]): "bound"},
        )
        assert found == {}

    def test_a_matching_not_business_data_disposition_still_excludes(self):
        found = self._detect(
            [self.ALL_TABLES, *self.BUSINESS],
            {("qargo", self.ALL_TABLES[1]): "not-business-data"},
        )
        assert self.ALL_TABLES[1] in found

    def test_table_names_are_matched_per_system(self):
        """Another system's table names are not evidence about this one."""
        listing = ("qargo", "Tables Columns__list", _cols(
            ("table_name", "bookings|orders|stops|companies|contacts|goods"),
        ))
        elsewhere = [("qlik", t, c) for _, t, c in self.BUSINESS]
        assert self._detect([listing, *elsewhere]) == {}


class TestSchemaCatalogueIsRoutedBeforeAnchoring:
    def test_excluded_tables_are_reported_and_never_anchored(self, tmp_path):
        import json

        from kairos_ontology.core import anchor_tables as at

        (tmp_path / "sources").mkdir()
        catalogue = ("qargo", "Qargo Tables Columns Info__AllTables", _cols(
            ("table_name", "bookings|orders|stops|companies|contacts|goods"),
        ))
        business = [
            ("qargo", "orders", _cols(("order_id", "1"))),
            ("qargo", "bookings", _cols(("booking_id", "1"))),
            ("qargo", "stops", _cols(("stop_id", "1"))),
            ("qargo", "companies", _cols(("company_id", "1"))),
            ("qargo", "contacts", _cols(("contact_id", "1"))),
            ("qargo", "goods", _cols(("goods_id", "1"))),
        ]
        client = MagicMock()
        message = MagicMock()
        message.content = json.dumps({"anchors": {}})
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=message)]
        )
        lines: list[str] = []
        with patch.object(at, "build_class_catalog", return_value=catalog()), patch.object(
            at, "read_source_tables", return_value=[catalogue, *business]
        ):
            out = at.run_anchor_tables(
                client=client, model="m",
                sources_dir=tmp_path / "sources",
                catalog_path=tmp_path / "catalog.xml",
                ref_models_dir=None, accelerator=None,
                analysis_dir=tmp_path / "_analysis",
                report=_recorder(lines),
            )
        doc = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert [e["table"] for e in doc["excluded"]] == [catalogue[1]]
        assert doc["excluded"][0]["reason"]
        assert doc["table_count"] == len(business), "screened out before anchoring"
        assert catalogue[1] not in {t["table"] for t in doc["unanchored"]}
        assert any("schema-catalogue" in line for line in lines)

        prompt = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert catalogue[1] not in prompt, "a screened table must not reach the model"

    def _run_screen(self, tmp_path, **kwargs):
        """Anchor one catalogue table plus six business tables; return the artifact."""
        import json

        from kairos_ontology.core import anchor_tables as at

        (tmp_path / "sources").mkdir()
        catalogue = ("qargo", "Qargo Tables Columns Info__AllTables", _cols(
            ("table_name", "bookings|orders|stops|companies|contacts|goods"),
        ))
        business = [
            ("qargo", "orders", _cols(("order_id", "1"))),
            ("qargo", "bookings", _cols(("booking_id", "1"))),
            ("qargo", "stops", _cols(("stop_id", "1"))),
            ("qargo", "companies", _cols(("company_id", "1"))),
            ("qargo", "contacts", _cols(("contact_id", "1"))),
            ("qargo", "goods", _cols(("goods_id", "1"))),
        ]
        client = MagicMock()
        message = MagicMock()
        message.content = json.dumps({"anchors": {}})
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=message)]
        )
        with patch.object(at, "build_class_catalog", return_value=catalog()), patch.object(
            at, "read_source_tables", return_value=[catalogue, *business]
        ):
            out = at.run_anchor_tables(
                client=client, model="m",
                sources_dir=tmp_path / "sources",
                catalog_path=tmp_path / "catalog.xml",
                ref_models_dir=None, accelerator=None,
                analysis_dir=tmp_path / "_analysis",
                **kwargs,
            )
        return catalogue[1], out, len(business)

    def test_the_exclusion_is_readable_back_with_its_evidence(self, tmp_path):
        """#528: the block was write-only. A downstream stage must be able to ask
        'is this table business data at all?' without re-running the screen."""
        from kairos_ontology.core.anchor_tables import load_excluded_tables

        table, _out, _n = self._run_screen(tmp_path)
        excluded = load_excluded_tables(tmp_path / "_analysis")
        assert set(excluded) == {("qargo", table)}
        assert "names of 6 other tables" in excluded[("qargo", table)], (
            "the evidence travels with the exclusion, so a stage that honours it "
            "can say what it dropped and why"
        )

    def test_the_loader_is_empty_without_an_artifact(self, tmp_path):
        from kairos_ontology.core.anchor_tables import load_excluded_tables

        assert load_excluded_tables(tmp_path) == {}

    def test_the_screen_can_be_switched_off(self, tmp_path):
        """A false positive must be answerable without a code change (#525)."""
        from kairos_ontology.core.anchor_tables import load_excluded_tables

        table, out, n_business = self._run_screen(tmp_path, screen_schema_catalogues=False)
        doc = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert doc["excluded"] == []
        assert doc["table_count"] == n_business + 1
        assert table in {t["table"] for t in doc["unanchored"]}
        assert load_excluded_tables(tmp_path / "_analysis") == {}


class TestRegroupByAnchor:
    """The half of the inversion that makes affinity derived (DD-185)."""

    URIS = {"consignment": ["https://ex.org/mmt/consignment#"],
            "route-schedule": ["https://ex.org/dcsa/transport-call#"]}

    def _grouping(self):
        return {
            "events": [{"system": "qargo", "table": "stops", "domain_uris": ["https://ex.org/ev#"]}],
            "party": [{"system": "qargo", "table": "companies", "domain_uris": ["https://ex.org/p#"]}],
        }

    def test_misplaced_table_moves_to_its_derived_domain(self):
        from kairos_ontology.core.anchor_tables import regroup_by_anchor

        anchors = {("qargo", "stops"): {"anchor": "TransportCall", "confidence": 0.86,
                                        "domain": "route-schedule"}}
        grouped, moves = regroup_by_anchor(self._grouping(), anchors, self.URIS)
        assert "events" not in grouped
        assert grouped["route-schedule"][0]["table"] == "stops"
        assert grouped["route-schedule"][0]["domain_uris"] == self.URIS["route-schedule"]
        assert moves == [{"system": "qargo", "table": "stops", "from": "events",
                          "to": "route-schedule", "anchor": "TransportCall"}]

    def test_low_confidence_anchor_does_not_move_a_table(self):
        from kairos_ontology.core.anchor_tables import regroup_by_anchor

        anchors = {("qargo", "stops"): {"anchor": "TransportCall", "confidence": 0.4,
                                        "domain": "route-schedule"}}
        grouped, moves = regroup_by_anchor(self._grouping(), anchors, self.URIS)
        assert moves == [] and "events" in grouped

    def test_unknown_target_uris_block_the_move(self):
        """No URIs means an empty class pool — strictly worse than the wrong one."""
        from kairos_ontology.core.anchor_tables import regroup_by_anchor

        anchors = {("qargo", "stops"): {"anchor": "Widget", "confidence": 0.9,
                                        "domain": "widget-domain"}}
        grouped, moves = regroup_by_anchor(self._grouping(), anchors, self.URIS)
        assert moves == [] and grouped["events"][0]["table"] == "stops"

    def test_agreeing_domain_is_left_untouched(self):
        from kairos_ontology.core.anchor_tables import regroup_by_anchor

        anchors = {("qargo", "companies"): {"anchor": "TradeParty", "confidence": 0.9,
                                            "domain": "party"}}
        grouped, moves = regroup_by_anchor(self._grouping(), anchors, self.URIS)
        assert moves == []
        assert grouped["party"][0]["domain_uris"] == ["https://ex.org/p#"], "no rewrite in place"

    def test_unanchored_tables_stay_put(self):
        from kairos_ontology.core.anchor_tables import regroup_by_anchor

        grouped, moves = regroup_by_anchor(self._grouping(), {}, self.URIS)
        assert moves == [] and set(grouped) == {"events", "party"}


# ---------------------------------------------------------------------------
# An operational column is not part of the business grain (#914)
# ---------------------------------------------------------------------------


class TestBusinessGrain:
    """``grain_columns`` becomes the Silver row's identity: generate-bindings turns each
    one into a ``purpose: identity`` technical field. A system-versioning column in there
    does not identify the entity more precisely, it changes what the entity *is*.

    Measured on a real hub: the model proposed
    ``natural_key: [KLMEMO, SETNR]`` and ``grain_columns: [KLMEMO, SETNR, ttSysStartTime]``,
    and five of seven generated bindings then carried a row-validity timestamp as part of
    identity -- turning "one row per consignment" into "one row per consignment per
    version" with nothing objecting.
    """

    @staticmethod
    def _grain(grain, natural_key):
        from kairos_ontology.core.anchor_tables import _business_grain

        return _business_grain(grain, natural_key)

    def test_a_system_versioning_column_is_dropped(self):
        assert self._grain(
            ["KLMEMO", "SETNR", "ttSysStartTime"], ["KLMEMO", "SETNR"]
        ) == ["KLMEMO", "SETNR"]

    def test_a_business_grain_is_untouched(self):
        assert self._grain(["REFXX", "VOLGNR"], ["REFXX", "VOLGNR"]) == ["REFXX", "VOLGNR"]

    def test_a_column_the_model_put_in_the_natural_key_is_never_dropped(self):
        """The stage that proposed the grain said this column identifies the entity.

        That statement outranks a name-shaped guess, because `_is_operational_column` is
        the narrow classifier whose false positives delete real data.
        """
        assert self._grain(["created_at"], ["created_at"]) == ["created_at"]

    def test_an_all_operational_grain_is_returned_untouched(self):
        """A table with no grain is not a safer answer than one with a questionable grain.

        Emptying it would make `generate-bindings` skip the table entirely, turning a
        reviewable oddity into a silent absence.
        """
        assert self._grain(["ttSysStartTime", "ttSysEndTime"], []) == [
            "ttSysStartTime",
            "ttSysEndTime",
        ]

    def test_natural_key_protection_ignores_case(self):
        """The grain and the natural key are both model output and need not agree on case.

        Only the protection is case-insensitive. Whether a name *looks* operational is
        `_is_operational_column`'s business, and it is token-based -- an all-caps
        concatenation like TTSYSSTARTTIME has no boundaries to split on and is therefore
        not recognised. That is a property of the predicate, not of this filter.
        """
        assert self._grain(["klmemo", "ttSysStartTime"], ["KLMEMO"]) == ["klmemo"]

    def test_an_empty_grain_stays_empty(self):
        assert self._grain([], []) == []


# ---------------------------------------------------------------------------
# Two tables of different grain on one class (#917)
# ---------------------------------------------------------------------------


def _anchored(table, entity, key, uri="https://ex/ont#ConsignmentItem", system="sys"):
    return {
        "system": system,
        "table": table,
        "anchor": uri.rsplit("#", 1)[-1],
        "anchor_uri": uri,
        "likely_entity": entity,
        "natural_key": key,
    }


class TestGrainCollapseDetection:
    """`likely_entity` has always been persisted so a detector could "detect when tables
    with different candidate entities collapse onto one ref_class". The detector was never
    written. Measured on a real hub: a unit-grain table and an item-grain table on one
    class, and a port-pair table and a multi-leg table on another. Nothing objected until
    `compile` asked for a conformance merge -- the one remedy that must not be applied.
    """

    @staticmethod
    def _detect(tables):
        from kairos_ontology.core.anchor_tables import detect_grain_collapses

        return detect_grain_collapses(tables)

    def test_different_entities_and_different_key_arity_is_a_collapse(self):
        findings = self._detect([
            _anchored("gate_shipment", "TerminalGateShipment", ["ref", "seq"]),
            _anchored("cargo_detail", "RoRoGoodsUnit", ["ref", "seq", "item"]),
        ])

        assert len(findings) == 1
        assert [t["table"] for t in findings[0]["tables"]] == ["cargo_detail", "gate_shipment"]

    def test_the_same_entity_from_two_systems_is_not_a_collapse(self):
        """That is the multi-source case DD-133 3c exists for, and must stay clean."""
        findings = self._detect([
            _anchored("orders", "SalesOrder", ["id"], system="erp"),
            _anchored("orders", "SalesOrder", ["order_id"], system="crm"),
        ])

        assert findings == []

    def test_a_cosmetic_key_spelling_difference_is_not_a_collapse(self):
        """Two systems spelling one key differently is not a grain difference."""
        findings = self._detect([
            _anchored("a", "SalesOrder", ["REFXX"], system="erp"),
            _anchored("b", "PurchaseOrder", ["refxx"], system="erp"),
        ])

        assert findings == []

    def test_different_entities_with_the_same_key_shape_is_not_flagged(self):
        """Both conditions are required; a differing label alone is too weak a signal."""
        findings = self._detect([
            _anchored("a", "ThingOne", ["id"]),
            _anchored("b", "ThingTwo", ["code"]),
        ])

        assert findings == []

    def test_a_table_with_no_candidate_entity_does_not_trigger_it(self):
        findings = self._detect([
            _anchored("a", "", ["ref"]),
            _anchored("b", "RoRoGoodsUnit", ["ref", "seq"]),
        ])

        assert findings == []

    def test_one_table_on_a_class_is_never_a_collapse(self):
        assert self._detect([_anchored("a", "Thing", ["id"])]) == []

    def test_the_report_refuses_the_conformance_remedy(self):
        """The gate that notices asks for a merge; the report has to say not to."""
        from kairos_ontology.core.anchor_tables import render_grain_collapses

        text = render_grain_collapses(self._detect([
            _anchored("gate_shipment", "TerminalGateShipment", ["ref", "seq"]),
            _anchored("cargo_detail", "RoRoGoodsUnit", ["ref", "seq", "item"]),
        ]))

        assert "Do NOT resolve this by declaring conformance" in text
        assert "re-anchor" in text

    def test_nothing_renders_when_nothing_collapsed(self):
        from kairos_ontology.core.anchor_tables import render_grain_collapses

        assert render_grain_collapses([]) == ""


# ---------------------------------------------------------------------------
# A replication lane is not a second source (#916)
# ---------------------------------------------------------------------------


class TestReplicaDetection:
    """Eight such pairs on one hub: 21% of anchored tables, 25% of alignment spend, and a
    false `conformance.group-required` for each, asking to merge a table with itself.
    """

    @staticmethod
    def _detect(mapping):
        from kairos_ontology.core.anchor_tables import detect_replica_tables

        return detect_replica_tables(mapping)

    def test_a_watermark_only_copy_is_a_replica(self):
        findings = self._detect({
            ("sys", "orders"): ["id", "customer", "amount", "status", "created_by", "region"],
            ("sys", "cdc_orders"): ["id", "customer", "amount", "status", "created_by", "region", "ts_ms"],
        })

        assert len(findings) == 1
        assert findings[0]["tables"] == ["cdc_orders", "orders"]
        assert findings[0]["only_in"]["cdc_orders"] == ["ts_ms"]
        assert findings[0]["only_in"]["orders"] == []

    def test_a_lane_that_also_lags_the_base_is_still_a_replica(self):
        """Schema drift is normal: on the hub measured, one lane was missing a real
        business column its twin had. Requiring a strict superset misses the real cases.
        """
        findings = self._detect({
            ("sys", "orders"): ["id", "customer", "amount", "status", "created_by", "region", "iso_size_type"],
            ("sys", "cdc_orders"): ["id", "customer", "amount", "status", "created_by", "region", "ts_ms"],
        })

        assert len(findings) == 1
        assert findings[0]["only_in"]["orders"] == ["iso_size_type"]

    def test_the_pair_is_unordered_when_both_sides_carry_operational_extras(self):
        """Either orientation satisfies the test, so asserting which is the lane would be
        a coin flip presented as a fact. The decision does not depend on the label.
        """
        findings = self._detect({
            ("sys", "orders"): ["id", "customer", "amount", "status", "created_by", "region", "_rescued_data"],
            ("sys", "cdc_orders"): ["id", "customer", "amount", "status", "created_by", "region", "ts_ms"],
        })

        assert len(findings) == 1
        assert sorted(findings[0]["tables"]) == ["cdc_orders", "orders"]
        assert findings[0]["only_in"]["orders"] == ["_rescued_data"]
        assert findings[0]["only_in"]["cdc_orders"] == ["ts_ms"]

    def test_a_copy_in_a_different_system_is_not_a_replica(self):
        """Two systems carrying one table is the multi-source case, not a lane."""
        findings = self._detect({
            ("erp", "orders"): ["id", "customer", "amount", "status", "created_by", "region"],
            ("warehouse", "orders"): ["id", "customer", "amount", "status", "created_by", "region", "ts_ms"],
        })

        assert findings == []

    def test_a_table_adding_real_business_columns_is_not_a_replica(self):
        """However similar the name, a wider table is doing something of its own."""
        findings = self._detect({
            ("sys", "orders"): ["id", "customer", "amount", "status", "created_by", "region"],
            ("sys", "orders_enriched"): ["id", "customer", "amount", "status", "created_by", "region", "credit_rating"],
        })

        assert findings == []

    def test_a_copy_missing_a_column_is_not_a_replica(self):
        findings = self._detect({
            ("sys", "orders"): ["id", "customer", "amount", "status", "created_by", "region", "a", "b", "c"],
            ("sys", "orders_slim"): ["id", "customer", "amount", "status", "created_by", "region", "ts_ms"],
        })

        assert findings == []

    def test_too_many_extra_columns_is_not_a_replica(self):
        findings = self._detect({
            ("sys", "orders"): ["id"],
            ("sys", "wide"): ["id", "ts_ms", "created_at", "updated_at", "modified_by"],
        })

        assert findings == []

    def test_identical_column_sets_are_not_reported(self):
        """No extra column means no watermark, so this is a different question."""
        findings = self._detect({
            ("sys", "a"): ["id", "customer", "amount", "status", "created_by", "region"],
            ("sys", "b"): ["id", "customer", "amount", "status", "created_by", "region"],
        })

        assert findings == []

    def test_the_report_does_not_tell_you_to_drop_the_replica(self):
        """A CDC lane is often the more current copy, so this is a choice."""
        from kairos_ontology.core.anchor_tables import render_replica_tables

        text = render_replica_tables(self._detect({
            ("sys", "orders"): ["id", "customer", "amount", "status", "created_by", "region"],
            ("sys", "cdc_orders"): ["id", "customer", "amount", "status", "created_by", "region", "ts_ms"],
        }))

        assert "this is a choice, not a cleanup" in text
        assert "record a disposition" in text
        assert "only in cdc_orders: ts_ms" in text
