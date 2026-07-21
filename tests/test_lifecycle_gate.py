# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the deterministic lifecycle gate (DD-100).

Covers the five scenarios the gate must distinguish (methodology + DD-096 open
decision #4): a claim *proposed* and awaiting approval, an *approved-but-unbound*
(aspirational/stub) claim that blocks release, a *bound* claim that does not,
the committed *validation* result, and the composed *release eligibility*
decision. Every section is asserted to be the literal result of its existing
evaluator (``ClaimCheckReport``/``SourceCoverageReport``/``ProjectionSyncReport``)
so this suite also guards against silently re-deriving a rule.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    EvidenceSource,
    Freshness,
    registry_path,
    write_registry,
)
from kairos_ontology.core.completeness_model import (
    ALIGNMENT_ALGORITHM_VERSION,
    compute_affinity_hash,
)
from kairos_ontology.core.lifecycle_gate import (
    LifecycleGateReport,
    evaluate_lifecycle_gate,
)
from kairos_ontology.core.status import scan_hub_status

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
        rdfs:comment "A domain entity used across gate scenarios." .
    """
)

WIDGET_SILVER_EXT_TTL = textwrap.dedent(
    """\
    @prefix owl: <http://www.w3.org/2002/07/owl#> .

    <http://acme.example/widget-silver-ext> a owl:Ontology .
    """
)

BRONZE_VOCAB_TTL = textwrap.dedent(
    """\
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix bronze: <https://example.com/bronze/crm#> .

    bronze:CRM a kairos-bronze:SourceSystem ;
        rdfs:label "CRM" .

    bronze:widgets a kairos-bronze:SourceTable ;
        kairos-bronze:sourceSystem bronze:CRM ;
        kairos-bronze:tableName "widgets" .

    bronze:widgets_name a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze:widgets ;
        kairos-bronze:columnName "name" .
    """
)

DIRECT_MAPPING_TTL = textwrap.dedent(
    """\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix bronze: <https://example.com/bronze/crm#> .
    @prefix w: <http://acme.example/widget#> .

    bronze:widgets skos:exactMatch w:Widget ;
        kairos-map:mappingType "direct" .

    bronze:widgets_name skos:exactMatch w:name ;
        kairos-map:transform "source.name" .
    """
)


def _claims_yaml(status: str) -> str:
    return textwrap.dedent(
        f"""\
        domain: widget
        schema_version: 1
        claims:
          - id: widget-1
            type: class
            class_uri: http://acme.example/widget#Widget
            origin: authored
            status: {status}
            disposition: claim
        """
    )


def _build_hub(
    root: Path,
    *,
    claim_status: str | None = "approved",
    with_binding: bool = False,
    with_affinity: bool = False,
) -> Path:
    """Write a minimal grouped-layout hub for the ``widget`` domain."""
    hub = root / "hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "model" / "extensions").mkdir(parents=True)
    (hub / "model" / "mappings").mkdir(parents=True)
    (hub / "integration" / "sources" / "_analysis").mkdir(parents=True)
    (hub / "model" / "ontologies" / "widget.ttl").write_text(WIDGET_TTL, encoding="utf-8")
    (hub / "model" / "extensions" / "widget-silver-ext.ttl").write_text(
        WIDGET_SILVER_EXT_TTL, encoding="utf-8"
    )

    if with_binding:
        (hub / "integration" / "sources" / "crm").mkdir(parents=True)
        (hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl").write_text(
            BRONZE_VOCAB_TTL, encoding="utf-8"
        )
        (hub / "model" / "mappings" / "crm-to-widget.ttl").write_text(
            DIRECT_MAPPING_TTL, encoding="utf-8"
        )

    if claim_status is not None:
        (hub / "model" / "claims").mkdir(parents=True, exist_ok=True)
        (hub / "model" / "claims" / "widget-claims.yaml").write_text(
            _claims_yaml(claim_status), encoding="utf-8"
        )

    if with_affinity:
        data = {
            "system": "crm",
            "schema_version": 2,
            "tables": [{"table": "widgets", "domain": "widget", "total_columns": 1}],
        }
        with open(
            hub / "integration" / "sources" / "_analysis" / "crm-affinity.yaml",
            "w",
            encoding="utf-8",
        ) as fh:
            yaml.dump(data, fh, sort_keys=False)

    return hub


def _evaluate(hub: Path) -> LifecycleGateReport:
    return evaluate_lifecycle_gate(
        hub_root=hub,
        claims_dir=hub / "model" / "claims",
        analysis_dir=hub / "integration" / "sources" / "_analysis",
        sources_dir=hub / "integration" / "sources",
        mappings_dir=hub / "model" / "mappings",
        ontologies_dir=hub / "model" / "ontologies",
        extensions_dir=hub / "model" / "extensions",
    )


class TestReleaseEligibility:
    """DD-096: approved-unbound blocks release; bound and no-authority do not."""

    def test_no_claims_registry_is_vacuously_release_eligible(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status=None)
        report = _evaluate(hub)
        assert report.release == ()
        assert not report.release_blocking_domains
        assert report.is_blocking is False

    def test_approved_unbound_claim_blocks_release(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status="approved", with_binding=False)
        report = _evaluate(hub)

        assert len(report.release) == 1
        fact = report.release[0]
        assert fact.domain == "widget"
        assert fact.evaluated is True
        assert fact.bound_classes == ()
        assert fact.aspirational_classes == ("Widget",)
        assert fact.reasons == {"Widget": "approved claim, no bronze mapping (aspirational)"}
        assert fact.release_eligible is False
        assert report.release_blocking_domains == ("widget",)
        assert report.is_blocking is True

    def test_bound_claim_is_release_eligible(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status="approved", with_binding=True)
        report = _evaluate(hub)

        assert len(report.release) == 1
        fact = report.release[0]
        assert fact.bound_classes == ("Widget",)
        assert fact.aspirational_classes == ()
        assert fact.reasons == {}
        assert fact.release_eligible is True
        assert report.release_blocking_domains == ()

    def test_proposed_claim_does_not_block_release(self, tmp_path):
        """A merely-proposed claim is not materialization-eligible (DD-094) —
        it cannot be aspirational/release-blocking; it is only a candidate."""
        hub = _build_hub(tmp_path, claim_status="proposed", with_binding=False)
        report = _evaluate(hub)

        fact = report.release[0]
        assert fact.evaluated is True
        assert fact.aspirational_classes == ()
        assert fact.release_eligible is True
        assert report.is_blocking is False

    def test_domains_filter_scopes_release_facts(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status="approved", with_binding=False)
        report = evaluate_lifecycle_gate(
            hub_root=hub,
            claims_dir=hub / "model" / "claims",
            analysis_dir=hub / "integration" / "sources" / "_analysis",
            sources_dir=hub / "integration" / "sources",
            mappings_dir=hub / "model" / "mappings",
            ontologies_dir=hub / "model" / "ontologies",
            extensions_dir=hub / "model" / "extensions",
            domains_filter=["invoice"],
        )
        assert report.release == ()


class TestProposedAwaitingApproval:
    """Proposed claims are surfaced (proposed_counts) but never release-blocking.

    Uses an affinity-linked, fully-covered registry so ``check-claims``'s own
    ``proposed_counts`` bucket (not just the release facts) is populated —
    the same machine truth ``kairos-flow`` must route to batch approval.
    """

    def _affinity_linked_hub(self, tmp_path, *, extra_status: str = "proposed") -> Path:
        """A fully mapped, affinity-covered hub — the *only* open item is the
        pending claim decision, isolating the "awaiting approval" signal from
        the unrelated source-coverage/extension-sync gates."""
        hub = tmp_path / "hub"
        (hub / "model" / "ontologies").mkdir(parents=True)
        (hub / "model" / "extensions").mkdir(parents=True)
        (hub / "model" / "mappings").mkdir(parents=True)
        (hub / "model" / "claims").mkdir(parents=True)
        (hub / "integration" / "sources" / "crm").mkdir(parents=True)
        analysis = hub / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (hub / "model" / "ontologies" / "widget.ttl").write_text(WIDGET_TTL, encoding="utf-8")
        (hub / "model" / "extensions" / "widget-silver-ext.ttl").write_text(
            WIDGET_SILVER_EXT_TTL, encoding="utf-8"
        )
        (hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl").write_text(
            BRONZE_VOCAB_TTL, encoding="utf-8"
        )
        (hub / "model" / "mappings" / "crm-to-widget.ttl").write_text(
            DIRECT_MAPPING_TTL, encoding="utf-8"
        )
        data = {
            "system": "crm",
            "schema_version": 2,
            "tables": [{"table": "widgets", "domain": "widget", "total_columns": 1}],
        }
        with open(analysis / "crm-affinity.yaml", "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, sort_keys=False)

        registry = ClaimRegistry(
            domain="widget",
            algorithm_version=ALIGNMENT_ALGORITHM_VERSION,
            freshness=Freshness(
                affinity_sha256=compute_affinity_hash([("crm", "widgets")])
            ),
            coverage=[
                CoverageSystem(
                    system="crm",
                    tables=[CoverageTable(table="widgets", total_columns=1)],
                )
            ],
            claims=[
                Claim(
                    id="widget-1",
                    type="class",
                    status=extra_status,
                    disposition="claim",
                    class_uri="http://acme.example/widget#Widget",
                    evidence_sources=[
                        EvidenceSource(type="source_table", system="crm", table="widgets")
                    ],
                )
            ],
        )
        write_registry(registry, registry_path(hub / "model" / "claims", "widget"))
        return hub

    def test_proposed_count_surfaced_and_not_blocking(self, tmp_path):
        hub = self._affinity_linked_hub(tmp_path, extra_status="proposed")
        report = _evaluate(hub)

        assert report.claims.proposed_counts == {"widget": 1}
        assert report.claims.total_proposed == 1
        # Proposed claims are candidates, not decisions — never release-blocking.
        assert report.release[0].release_eligible is True
        assert report.is_blocking is False

    def test_status_scan_surfaces_proposed_and_approved_counts(self, tmp_path):
        """`status.py` itself (not just the gate) exposes proposed/approved facts."""
        hub = self._affinity_linked_hub(tmp_path, extra_status="proposed")
        status = scan_hub_status(hub)
        claims_phase = status.phase("claims")
        inst = next(i for i in claims_phase.instances if i.name == "widget-claims")
        assert inst.facts == {"proposed": 1, "approved": 0}


class TestValidationFact:
    def test_not_evaluated_when_no_report(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status=None)
        report = _evaluate(hub)
        assert report.validation.evaluated is False
        assert report.validation.passed is None
        assert report.is_blocking is False

    def test_passed_true_from_persisted_report(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status=None)
        output = hub / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "validation-report.json").write_text(
            json.dumps(
                {
                    "syntax": {"passed": 1, "failed": 0, "errors": []},
                    "shacl": {"passed": 0, "failed": 0, "errors": []},
                    "consistency": {"passed": 0, "failed": 0, "errors": []},
                }
            ),
            encoding="utf-8",
        )
        report = _evaluate(hub)
        assert report.validation.evaluated is True
        assert report.validation.passed is True
        assert report.is_blocking is False

    def test_failed_validation_blocks_the_gate(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status=None)
        output = hub / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "validation-report.json").write_text(
            json.dumps(
                {
                    "syntax": {"passed": 0, "failed": 1, "errors": ["bad turtle"]},
                    "shacl": {"passed": 0, "failed": 0, "errors": []},
                    "consistency": {"passed": 0, "failed": 0, "errors": []},
                }
            ),
            encoding="utf-8",
        )
        report = _evaluate(hub)
        assert report.validation.passed is False
        assert report.is_blocking is True

    def test_unrecognized_report_content_is_not_objectively_knowable(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status=None)
        output = hub / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "validation-report.json").write_text("{}", encoding="utf-8")
        report = _evaluate(hub)
        assert report.validation.evaluated is True
        assert report.validation.passed is None
        assert report.is_blocking is False


class TestProjectionFact:
    def test_not_evaluated_when_no_output(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status=None)
        report = _evaluate(hub)
        assert report.project.evaluated is False
        assert report.project.targets_generated == ()

    def test_evaluated_when_real_artifact_present(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status=None)
        models = hub / "output" / "medallion" / "dbt" / "models"
        models.mkdir(parents=True)
        (models / "widget.sql").write_text("select 1", encoding="utf-8")
        report = _evaluate(hub)
        assert report.project.evaluated is True
        assert "medallion/dbt" in report.project.targets_generated


class TestComposedReportShape:
    def test_schema_version_and_to_dict_shape(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status="approved", with_binding=False)
        report = _evaluate(hub)
        payload = report.to_dict()

        assert payload["schema_version"] == 1
        assert payload["is_blocking"] is True
        assert payload["release_blocking_domains"] == ["widget"]
        for key in (
            "claims", "source_coverage", "projection_sync", "release",
            "validation", "project", "hub_root",
        ):
            assert key in payload

    def test_is_blocking_is_a_union_of_every_section(self, tmp_path):
        """Release-eligible but failed validation still blocks (pure OR)."""
        hub = _build_hub(tmp_path, claim_status="approved", with_binding=True)
        output = hub / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "validation-report.json").write_text(
            json.dumps({"syntax": {"passed": 0, "failed": 2, "errors": ["x"]}}),
            encoding="utf-8",
        )
        report = _evaluate(hub)
        assert report.release[0].release_eligible is True
        assert report.validation.passed is False
        assert report.is_blocking is True

    def test_no_source_coverage_flag_yields_none_section(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status="approved", with_binding=False)
        report = evaluate_lifecycle_gate(
            hub_root=hub,
            claims_dir=hub / "model" / "claims",
            analysis_dir=hub / "integration" / "sources" / "_analysis",
            sources_dir=hub / "integration" / "sources",
            mappings_dir=hub / "model" / "mappings",
            ontologies_dir=hub / "model" / "ontologies",
            extensions_dir=hub / "model" / "extensions",
            no_source_coverage=True,
        )
        assert report.source_coverage is None
        assert report.to_dict()["source_coverage"] is None


class TestCheckReleaseCli:
    """CLI-level coverage for `kairos-ontology check-release`."""

    def _invoke_in(self, hub: Path, args: list[str]):
        runner = CliRunner()
        with runner.isolated_filesystem() as td:
            # Re-root the pre-built hub under the isolated cwd so auto-detection
            # (find_hub_root) resolves exactly like a real invocation.
            import shutil

            dest = Path(td) / "ontology-hub"
            shutil.copytree(hub, dest)
            return runner.invoke(cli, args), dest

    def test_cli_blocks_on_approved_unbound_claim(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status="approved", with_binding=False)
        result, _dest = self._invoke_in(hub, ["check-release"])
        assert result.exit_code == 1, result.output
        assert "NOT release-eligible" in result.output
        assert "Widget" in result.output

    def test_cli_passes_when_bound(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status="approved", with_binding=True)
        result, _dest = self._invoke_in(hub, ["check-release"])
        assert result.exit_code == 0, result.output
        assert "Release-eligible" in result.output

    def test_cli_warn_only_never_blocks(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status="approved", with_binding=False)
        result, _dest = self._invoke_in(hub, ["check-release", "--warn-only"])
        assert result.exit_code == 0, result.output
        assert "NOT release-eligible" in result.output

    def test_cli_json_output_matches_library_schema(self, tmp_path):
        hub = _build_hub(tmp_path, claim_status="approved", with_binding=True)
        result, _dest = self._invoke_in(hub, ["check-release", "--format", "json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["schema_version"] == 1
        assert payload["is_blocking"] is False
        assert payload["release"][0]["bound_classes"] == ["Widget"]

    def test_cli_help_lists_check_release(self):
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "check-release" in result.output
