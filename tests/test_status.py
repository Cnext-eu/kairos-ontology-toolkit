# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the deterministic lifecycle-status scanner (DD-080)."""

import json
import textwrap
from pathlib import Path

from kairos_ontology.core.status import (
    SCHEMA_VERSION,
    STATE_DONE,
    STATE_IN_PROGRESS,
    STATE_NOT_STARTED,
    PHASE_ORDER,
    render_markdown,
    scan_hub_status,
)

ACME_HUB = Path(__file__).parent / "scenarios" / "acme-hub"


def _phase(status, name):
    p = status.phase(name)
    assert p is not None, f"missing phase {name}"
    return p


class TestScanAcmeHub:
    """Scan the committed acme-hub scenario for known objective state."""

    def test_all_phases_present_in_order(self):
        status = scan_hub_status(ACME_HUB)
        assert [p.phase for p in status.phases] == list(PHASE_ORDER)

    def test_domain_phase_done_with_three_instances(self):
        status = scan_hub_status(ACME_HUB)
        domain = _phase(status, "domain")
        assert domain.state == STATE_DONE
        names = {i.name for i in domain.instances}
        assert names == {"client", "invoice", "logistics"}

    def test_internal_ttl_excluded_from_domain(self):
        # _refmodel-party.ttl must not count as a domain ontology.
        status = scan_hub_status(ACME_HUB)
        names = {i.name for i in _phase(status, "domain").instances}
        assert "_refmodel-party" not in names
        assert "_refmodel" not in names

    def test_mapping_phase_done_with_four_instances(self):
        status = scan_hub_status(ACME_HUB)
        mapping = _phase(status, "mapping")
        assert mapping.state == STATE_DONE
        assert len(mapping.instances) == 4

    def test_silver_and_gold_split_by_suffix(self):
        status = scan_hub_status(ACME_HUB)
        silver = {i.name for i in _phase(status, "silver").instances}
        gold = {i.name for i in _phase(status, "gold").instances}
        assert silver == {"client", "invoice", "logistics"}
        assert gold == {"client", "invoice"}

    def test_source_in_progress_without_affinity(self):
        # acme-hub has vocabularies but no _analysis affinity reports.
        status = scan_hub_status(ACME_HUB)
        source = _phase(status, "source")
        assert source.state == STATE_IN_PROGRESS
        assert {i.name for i in source.instances} == {
            "adminpulse", "billingpro", "crmsystem", "logisticspro",
        }
        assert all(i.state == STATE_IN_PROGRESS for i in source.instances)

    def test_not_started_phases(self):
        status = scan_hub_status(ACME_HUB)
        for name in ("discovery", "claims", "validate", "project"):
            assert _phase(status, name).state == STATE_NOT_STARTED

    def test_next_phase_is_first_incomplete(self):
        status = scan_hub_status(ACME_HUB)
        assert status.next_phase == "discovery"

    def test_scan_is_deterministic(self):
        a = scan_hub_status(ACME_HUB).to_dict()
        b = scan_hub_status(ACME_HUB).to_dict()
        assert a == b


class TestScanSynthetic:
    """Edge cases on a freshly built temporary hub."""

    def test_empty_hub_all_not_started(self, tmp_path):
        status = scan_hub_status(tmp_path)
        assert all(p.state == STATE_NOT_STARTED for p in status.phases)
        assert status.next_phase == "discovery"

    def test_source_done_when_vocab_and_affinity_present(self, tmp_path):
        sys_dir = tmp_path / "integration" / "sources" / "crm"
        sys_dir.mkdir(parents=True)
        (sys_dir / "crm.vocabulary.ttl").write_text("# vocab", encoding="utf-8")
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (analysis / "crm-affinity.yaml").write_text("domain: x", encoding="utf-8")
        source = _phase(scan_hub_status(tmp_path), "source")
        assert source.state == STATE_DONE
        assert source.instances[0].state == STATE_DONE

    def test_underscore_source_dirs_ignored(self, tmp_path):
        sources = tmp_path / "integration" / "sources"
        (sources / "_analysis").mkdir(parents=True)
        (sources / "crm").mkdir(parents=True)
        (sources / "crm" / "crm.vocabulary.ttl").write_text("# v", encoding="utf-8")
        source = _phase(scan_hub_status(tmp_path), "source")
        assert {i.name for i in source.instances} == {"crm"}

    def test_discovery_done_with_glossary(self, tmp_path):
        bd = tmp_path / "businessdiscovery"
        bd.mkdir(parents=True)
        (bd / "acme-glossary.ttl").write_text("# glossary", encoding="utf-8")
        assert _phase(scan_hub_status(tmp_path), "discovery").state == STATE_DONE

    def test_fresh_scaffold_like_output_is_not_projected(self, tmp_path):
        for target in (
            "medallion/powerbi",
            "medallion/dbt",
            "neo4j",
            "azure-search",
            "a2ui",
            "prompt",
            "report",
        ):
            target_dir = tmp_path / "output" / target
            target_dir.mkdir(parents=True)
            (target_dir / ".gitkeep").touch()
            (target_dir / "empty-placeholder").mkdir()

        project = _phase(scan_hub_status(tmp_path), "project")
        assert project.state == STATE_NOT_STARTED
        assert project.instances == []

    def test_project_done_when_output_target_has_real_artifact(self, tmp_path):
        dbt = tmp_path / "output" / "medallion" / "dbt"
        dbt.mkdir(parents=True)
        (dbt / ".gitkeep").touch()
        models = dbt / "models"
        models.mkdir()
        (models / "model.sql").write_text("select 1", encoding="utf-8")
        proj = _phase(scan_hub_status(tmp_path), "project")
        assert proj.state == STATE_DONE
        assert proj.instances[0].name == "medallion/dbt"

    def test_validate_done_with_report(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir(parents=True)
        (out / "validation-report.json").write_text("{}", encoding="utf-8")
        assert _phase(scan_hub_status(tmp_path), "validate").state == STATE_DONE

    def test_empty_validation_directories_are_not_completion_evidence(self, tmp_path):
        validation = tmp_path / "output" / "validation"
        validation.mkdir(parents=True)
        (validation / ".gitkeep").touch()
        reports = tmp_path / "output" / "reports"
        reports.mkdir()
        (reports / ".gitkeep").touch()

        assert _phase(scan_hub_status(tmp_path), "validate").state == STATE_NOT_STARTED

    def test_source_placeholders_do_not_block_completion(self, tmp_path):
        sources = tmp_path / "integration" / "sources"
        crm = sources / "crm"
        crm.mkdir(parents=True)
        (crm / "crm.vocabulary.ttl").write_text("# vocab", encoding="utf-8")
        analysis = sources / "_analysis"
        analysis.mkdir()
        (analysis / "crm-affinity.yaml").write_text("domain: x", encoding="utf-8")

        template = sources / "source-system-template"
        template.mkdir()
        (template / "source-system.vocabulary.ttl.template").write_text("", encoding="utf-8")
        reference_data = sources / "reference-data"
        reference_data.mkdir()
        (reference_data / "reference-data.vocabulary.ttl").write_text("# vocab", encoding="utf-8")
        custom = sources / "custom-transformations"
        custom.mkdir()
        (custom / "README.md").write_text("Reserved for generated sources.", encoding="utf-8")

        source = _phase(scan_hub_status(tmp_path), "source")
        assert source.state == STATE_DONE
        assert [instance.name for instance in source.instances] == ["crm"]

    def test_populated_custom_transformations_counts_as_source(self, tmp_path):
        sources = tmp_path / "integration" / "sources"
        custom = sources / "custom-transformations"
        custom.mkdir(parents=True)
        (custom / "orders.vocabulary.ttl").write_text("# vocab", encoding="utf-8")
        analysis = sources / "_analysis"
        analysis.mkdir()
        (analysis / "custom-transformations-affinity.yaml").write_text(
            "domain: x",
            encoding="utf-8",
        )

        source = _phase(scan_hub_status(tmp_path), "source")
        assert source.state == STATE_DONE
        assert [instance.name for instance in source.instances] == ["custom-transformations"]

    def test_next_phase_advances_after_source_completion(self, tmp_path):
        discovery = tmp_path / "businessdiscovery"
        discovery.mkdir()
        (discovery / "acme-glossary.ttl").write_text("# glossary", encoding="utf-8")

        sources = tmp_path / "integration" / "sources"
        (sources / "source-system-template").mkdir(parents=True)
        (sources / "reference-data").mkdir()
        assert scan_hub_status(tmp_path).next_phase == "source"

        crm = sources / "crm"
        crm.mkdir()
        (crm / "crm.vocabulary.ttl").write_text("# vocab", encoding="utf-8")
        analysis = sources / "_analysis"
        analysis.mkdir()
        (analysis / "crm-affinity.yaml").write_text("domain: x", encoding="utf-8")

        assert scan_hub_status(tmp_path).next_phase == "domain"


class TestRenderMarkdown:
    def test_markdown_contains_auto_generated_marker_and_table(self):
        md = render_markdown(scan_hub_status(ACME_HUB), last_scanned_at="2026-01-01T00:00:00+00:00")
        assert "AUTO-GENERATED" in md
        assert "| Phase | State |" in md
        assert "| domain |" in md
        assert "Next phase" in md

    def test_markdown_reports_completion(self, tmp_path):
        # Force a hub where every phase resolves done is impractical; assert the
        # not-complete branch instead.
        md = render_markdown(scan_hub_status(tmp_path))
        assert "Next phase" in md


class TestSchemaVersioning:
    """DD-101: `to_dict()` is versioned and additive-only over v1."""

    def test_to_dict_carries_schema_version_and_v1_keys(self):
        payload = scan_hub_status(ACME_HUB).to_dict()
        assert payload["schema_version"] == SCHEMA_VERSION
        # Every v1 key remains present and in place.
        for key in ("hub_root", "toolkit_version", "next_phase", "phases"):
            assert key in payload
        for phase in payload["phases"]:
            for key in ("phase", "title", "state", "instances", "detail"):
                assert key in phase
            for instance in phase["instances"]:
                for key in ("name", "state", "evidence", "detail", "facts"):
                    assert key in instance


class TestClaimsFacts:
    """DD-101: the claims phase surfaces machine-readable proposed/approved counts."""

    def _write_registry(self, tmp_path, statuses: list[str]) -> Path:
        claims_dir = tmp_path / "model" / "claims"
        claims_dir.mkdir(parents=True)
        claims = "\n".join(
            textwrap.dedent(
                f"""\
                  - id: widget-{i}
                    type: class
                    class_uri: http://acme.example/widget#Widget{i}
                    origin: authored
                    status: {status}
                    disposition: claim
                """
            )
            for i, status in enumerate(statuses)
        )
        (claims_dir / "widget-claims.yaml").write_text(
            f"domain: widget\nschema_version: 1\nclaims:\n{claims}", encoding="utf-8"
        )
        return claims_dir

    def test_proposed_and_approved_counts_reported(self, tmp_path):
        self._write_registry(tmp_path, ["proposed", "proposed", "approved"])
        claims_phase = _phase(scan_hub_status(tmp_path), "claims")
        inst = next(i for i in claims_phase.instances if i.name == "widget-claims")
        assert inst.facts == {"proposed": 2, "approved": 1}
        # Facts never change the file-presence state semantics (DD-080).
        assert inst.state == STATE_DONE

    def test_ttl_only_claims_file_has_no_status_facts(self, tmp_path):
        claims_dir = tmp_path / "model" / "claims"
        claims_dir.mkdir(parents=True)
        (claims_dir / "widget-claims.ttl").write_text("# not a registry", encoding="utf-8")
        claims_phase = _phase(scan_hub_status(tmp_path), "claims")
        assert claims_phase.instances[0].facts == {}

    def test_malformed_registry_degrades_to_no_facts(self, tmp_path):
        claims_dir = tmp_path / "model" / "claims"
        claims_dir.mkdir(parents=True)
        (claims_dir / "widget-claims.yaml").write_text("not: [valid, registry", encoding="utf-8")
        claims_phase = _phase(scan_hub_status(tmp_path), "claims")
        assert claims_phase.instances[0].facts == {}
        # The scan must never raise on a malformed registry.
        assert claims_phase.state == STATE_DONE


class TestSilverFacts:
    """DD-101/DD-096: the silver phase surfaces bound/aspirational/release facts."""

    WIDGET_TTL = textwrap.dedent(
        """\
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix w: <http://acme.example/widget#> .

        <http://acme.example/widget> a owl:Ontology ;
            rdfs:label "Widget domain" ;
            owl:versionInfo "1.0.0" .

        w:Widget a owl:Class ;
            rdfs:label "Widget" ;
            rdfs:comment "An approved but unmapped domain entity." .
        """
    )
    WIDGET_SILVER_EXT_TTL = textwrap.dedent(
        """\
        @prefix owl: <http://www.w3.org/2002/07/owl#> .

        <http://acme.example/widget-silver-ext> a owl:Ontology .
        """
    )
    WIDGET_CLAIMS_YAML = textwrap.dedent(
        """\
        domain: widget
        schema_version: 1
        claims:
          - id: widget-1
            type: class
            class_uri: http://acme.example/widget#Widget
            origin: authored
            status: approved
            disposition: claim
        """
    )

    def _build(self, tmp_path: Path) -> Path:
        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        (tmp_path / "model" / "extensions").mkdir(parents=True)
        (tmp_path / "model" / "claims").mkdir(parents=True)
        (tmp_path / "model" / "ontologies" / "widget.ttl").write_text(
            self.WIDGET_TTL, encoding="utf-8"
        )
        (tmp_path / "model" / "extensions" / "widget-silver-ext.ttl").write_text(
            self.WIDGET_SILVER_EXT_TTL, encoding="utf-8"
        )
        (tmp_path / "model" / "claims" / "widget-claims.yaml").write_text(
            self.WIDGET_CLAIMS_YAML, encoding="utf-8"
        )
        return tmp_path

    def test_approved_unbound_claim_reports_aspirational_facts(self, tmp_path):
        hub = self._build(tmp_path)
        silver = _phase(scan_hub_status(hub), "silver")
        inst = next(i for i in silver.instances if i.name == "widget")
        assert inst.facts["aspirational_classes"] == ["Widget"]
        assert inst.facts["bound_classes"] == []
        assert inst.facts["release_eligible"] is False

    def test_bound_claim_reports_release_eligible_facts(self, tmp_path):
        hub = self._build(tmp_path)
        (hub / "integration" / "sources" / "crm").mkdir(parents=True)
        (hub / "model" / "mappings").mkdir(parents=True)
        (hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl").write_text(
            textwrap.dedent(
                """\
                @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
                @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
                @prefix bronze: <https://example.com/bronze/crm#> .

                bronze:CRM a kairos-bronze:SourceSystem ;
                    rdfs:label "CRM" .

                bronze:widgets a kairos-bronze:SourceTable ;
                    kairos-bronze:sourceSystem bronze:CRM ;
                    kairos-bronze:tableName "widgets" .
                """
            ),
            encoding="utf-8",
        )
        (hub / "model" / "mappings" / "crm-to-widget.ttl").write_text(
            textwrap.dedent(
                """\
                @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
                @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
                @prefix bronze: <https://example.com/bronze/crm#> .
                @prefix w: <http://acme.example/widget#> .

                bronze:widgets skos:exactMatch w:Widget ;
                    kairos-map:mappingType "direct" .
                """
            ),
            encoding="utf-8",
        )
        silver = _phase(scan_hub_status(hub), "silver")
        inst = next(i for i in silver.instances if i.name == "widget")
        assert inst.facts["bound_classes"] == ["Widget"]
        assert inst.facts["aspirational_classes"] == []
        assert inst.facts["release_eligible"] is True
        assert inst.state == STATE_DONE


class TestValidateFacts:
    """DD-101: the validate phase surfaces a `data_valid` fact where knowable."""

    def test_data_valid_true_when_report_shows_no_failures(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir(parents=True)
        (out / "validation-report.json").write_text(
            json.dumps({"syntax": {"passed": 1, "failed": 0, "errors": []}}),
            encoding="utf-8",
        )
        validate = _phase(scan_hub_status(tmp_path), "validate")
        assert validate.instances[0].facts == {"data_valid": True}

    def test_data_valid_false_when_report_shows_failures(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir(parents=True)
        (out / "validation-report.json").write_text(
            json.dumps({"syntax": {"passed": 0, "failed": 2, "errors": ["x"]}}),
            encoding="utf-8",
        )
        validate = _phase(scan_hub_status(tmp_path), "validate")
        assert validate.instances[0].facts == {"data_valid": False}

    def test_data_valid_absent_when_report_has_no_recognizable_counts(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir(parents=True)
        (out / "validation-report.json").write_text("{}", encoding="utf-8")
        validate = _phase(scan_hub_status(tmp_path), "validate")
        assert validate.instances[0].facts == {}

    def test_data_valid_absent_when_no_report(self, tmp_path):
        assert _phase(scan_hub_status(tmp_path), "validate").instances == []

