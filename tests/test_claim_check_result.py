# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the versioned, machine-readable ``check-claims`` result (DD-122).

Covers the facets ``build_claim_check_result``/``ClaimCheckResult`` compose:
registry validity, semantic-generation completeness (consuming the additive
``generation_outcomes`` metadata, tolerating legacy artifacts without it),
curation completeness (the narrowed blocking scope), mapping readiness, and
projection sync — each independently reported, with ``curation_complete``
gated only by registry/freshness/semantic-policy/undecided-claims.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from kairos_ontology.core.claim_check_result import (
    CLAIM_CHECK_RESULT_SCHEMA_VERSION,
    build_claim_check_result,
)
from kairos_ontology.core.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    Freshness,
    GenerationOutcome,
    registry_path,
    write_registry,
)
from kairos_ontology.core.claim_projection_sync import ProjectionSyncReport
from kairos_ontology.core.completeness_model import (
    ALIGNMENT_ALGORITHM_VERSION,
    compute_affinity_hash,
)
from kairos_ontology.core.source_coverage import SourceCoverageReport


def _write_affinity(analysis_dir: Path, system: str, tables: list[tuple[str, str]]) -> None:
    """Write a schema_version 2 affinity report. tables = [(table, domain), ...]."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "system": system,
        "schema_version": 2,
        "tables": [{"table": t, "domain": d} for t, d in tables],
    }
    with open(analysis_dir / f"{system}-affinity.yaml", "w", encoding="utf-8") as fh:
        yaml.dump(data, fh, sort_keys=False)


def _registry(
    domain: str,
    tables: list[tuple[str, str]],
    *,
    claims: list[Claim] | None = None,
    generation_outcomes: list[GenerationOutcome] | None = None,
) -> ClaimRegistry:
    """Build a fresh, valid Claim Registry covering ``tables`` = [(system, table), ...]."""
    systems: dict[str, list[CoverageTable]] = {}
    for system, table in tables:
        systems.setdefault(system, []).append(CoverageTable(table=table))
    coverage = [CoverageSystem(system=s, tables=t) for s, t in systems.items()]
    return ClaimRegistry(
        domain=domain,
        generated_at="2026-06-15T00:00:00Z",
        algorithm_version=ALIGNMENT_ALGORITHM_VERSION,
        freshness=Freshness(affinity_sha256=compute_affinity_hash(tables)),
        coverage=coverage,
        claims=claims or [],
        generation_outcomes=generation_outcomes or [],
    )


def _build_hub(tmp_path: Path) -> dict[str, Path]:
    hub = tmp_path / "hub"
    dirs = {
        "hub_root": hub,
        "claims_dir": hub / "model" / "claims",
        "analysis_dir": hub / "integration" / "sources" / "_analysis",
        "sources_dir": hub / "integration" / "sources",
        "mappings_dir": hub / "model" / "mappings",
        "ontologies_dir": hub / "model" / "ontologies",
        "extensions_dir": hub / "model" / "extensions",
    }
    for key, path in dirs.items():
        if key != "hub_root":
            path.mkdir(parents=True, exist_ok=True)
    return dirs


def _build(tmp_path: Path, **overrides) -> object:
    dirs = _build_hub(tmp_path)
    kwargs = {
        "hub_root": dirs["hub_root"],
        "claims_dir": dirs["claims_dir"],
        "analysis_dir": dirs["analysis_dir"],
        "sources_dir": dirs["sources_dir"],
        "mappings_dir": dirs["mappings_dir"],
        "ontologies_dir": dirs["ontologies_dir"],
        "extensions_dir": dirs["extensions_dir"],
        "no_extension_sync": True,
    }
    kwargs.update(overrides)
    return dirs, build_claim_check_result(**kwargs)


class TestSchemaAndScaffolding:
    def test_schema_version_is_stable_and_reported(self, tmp_path):
        dirs, result = _build(tmp_path)
        assert result.schema_version == CLAIM_CHECK_RESULT_SCHEMA_VERSION
        assert result.to_dict()["schema_version"] == CLAIM_CHECK_RESULT_SCHEMA_VERSION

    def test_to_dict_exposes_every_independently_reported_facet(self, tmp_path):
        dirs, result = _build(tmp_path)
        payload = result.to_dict()
        for key in (
            "schema_version",
            "hub_root",
            "strict",
            "curation_complete",
            "registry",
            "semantic_generation",
            "mapping",
            "projection_sync",
            "disputed_claims",
        ):
            assert key in payload


class TestSemanticGenerationLegacyTolerance:
    """DD-122: semantic-generation completeness consumes the additive
    ``generation_outcomes`` metadata when present, and tolerates its absence in
    legacy artifacts (registries written before the feature existed)."""

    def test_legacy_registry_without_generation_outcomes_is_vacuously_complete(self, tmp_path):
        dirs, _ = _build(tmp_path)
        _write_affinity(dirs["analysis_dir"], "crm", [("widgets", "widget")])
        # A pre-feature registry: no ``generation_outcomes`` key at all in the
        # persisted YAML (not merely an empty list from this session's code).
        raw = _registry("widget", [("crm", "widgets")])
        write_registry(raw, registry_path(dirs["claims_dir"], "widget"))
        legacy_path = registry_path(dirs["claims_dir"], "widget")
        data = yaml.safe_load(legacy_path.read_text(encoding="utf-8"))
        assert "generation_outcomes" not in data

        _, result = _build(tmp_path)

        assert result.semantic_generation.domains == ()
        assert result.semantic_generation.complete is True
        assert result.curation_complete is True

    def test_incomplete_generation_is_visible_but_does_not_block_curation(self, tmp_path):
        dirs, _ = _build(tmp_path)
        _write_affinity(dirs["analysis_dir"], "crm", [("widgets", "widget")])
        reg = _registry(
            "widget",
            [("crm", "widgets")],
            generation_outcomes=[
                GenerationOutcome(
                    system="crm",
                    table="widgets",
                    outcome="provider_failure",
                    error="RuntimeError: boom",
                ),
            ],
        )
        write_registry(reg, registry_path(dirs["claims_dir"], "widget"))

        _, result = _build(tmp_path, strict=True)

        assert result.registry.is_blocking is False
        fact = result.semantic_generation.domains[0]
        assert fact.domain == "widget"
        assert any("provider_failure" in t for t in fact.incomplete_tables)
        assert fact.complete is False
        assert result.semantic_generation.complete is False
        # Non-blocking: independently reported, never gates curation_complete.
        assert result.curation_complete is True
        assert result.to_dict()["semantic_generation"]["complete"] is False


class TestCurationCompleteWhileMappingPending:
    """DD-122: mapping readiness is visible via its own facet (with
    ``owner_skill``) but never gates ``curation_complete`` in ``check-claims``
    — only its owning workflow (``kairos-design-mapping``) enforces it."""

    def test_curation_complete_true_despite_uncovered_mapping(self, tmp_path):
        dirs, _ = _build(tmp_path)
        _write_affinity(dirs["analysis_dir"], "crm", [("widgets", "widget")])
        reg = _registry("widget", [("crm", "widgets")])
        write_registry(reg, registry_path(dirs["claims_dir"], "widget"))
        # No mapping file is written for the "widgets" table — it stays uncovered.

        _, result = _build(tmp_path, strict=True)

        assert result.registry.is_blocking is False
        assert result.registry.has_undecided_claims() is False
        assert result.mapping is not None
        assert result.mapping.is_blocking is True
        assert "crm.widgets" in result.mapping.uncovered.get("widget", [])
        assert result.curation_complete is True
        # Still visible in the composed JSON, with its owning skill attached.
        payload = result.to_dict()
        assert payload["mapping"]["is_blocking"] is True
        assert payload["mapping"]["owner_skill"] == "kairos-design-mapping"

    def test_require_mapping_flag_opts_a_workflow_into_blocking(self, tmp_path):
        """DD-122: ``check-claims`` stays exit-0 on mapping gaps by default, but
        an owning pre-flight (e.g. the DD-094 silver/dbt projection gate) can
        opt into blocking on the same facet via ``--require-mapping`` without
        widening default curation-gate behavior."""
        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        dirs = _build_hub(tmp_path)
        _write_affinity(dirs["analysis_dir"], "crm", [("widgets", "widget")])
        reg = _registry("widget", [("crm", "widgets")])
        write_registry(reg, registry_path(dirs["claims_dir"], "widget"))

        runner = CliRunner()
        args = [
            "check-claims",
            "--claims-dir",
            str(dirs["claims_dir"]),
            "--analysis-dir",
            str(dirs["analysis_dir"]),
            "--sources",
            str(dirs["sources_dir"]),
            "--mappings",
            str(dirs["mappings_dir"]),
            "--no-extension-sync",
        ]
        default_run = runner.invoke(cli, args)
        assert default_run.exit_code == 0, default_run.output

        strict_run = runner.invoke(cli, [*args, "--require-mapping"])
        assert strict_run.exit_code == 1, strict_run.output
        assert "--require-mapping" in strict_run.output


class TestSyncAndMappingOwnership:
    """DD-122: mapping and projection-sync are owned by different skills and
    both stay non-blocking in ``check-claims``, but remain independently
    visible with their ``owner_skill``."""

    def test_default_owner_skills_on_bare_reports(self):
        assert ProjectionSyncReport().owner_skill == "kairos-design-domain"
        assert SourceCoverageReport().owner_skill == "kairos-design-mapping"

    def test_owner_skills_round_trip_through_result_to_dict(self, tmp_path):
        dirs, _ = _build(tmp_path)
        _write_affinity(dirs["analysis_dir"], "crm", [("widgets", "widget")])
        reg = _registry("widget", [("crm", "widgets")])
        write_registry(reg, registry_path(dirs["claims_dir"], "widget"))

        _, result = _build(tmp_path)
        payload = result.to_dict()

        assert payload["mapping"]["owner_skill"] == "kairos-design-mapping"
        assert payload["projection_sync"]["owner_skill"] == "kairos-design-domain"


class TestCliTextJsonParity:
    """Integration seam (DD-122): ``check-claims``'s two output formats compute
    their exit code on separate code paths. They must never disagree, and the
    JSON path must emit the versioned :class:`ClaimCheckResult` verbatim so a
    skill/CI step can parse it instead of scraping text.
    """

    @staticmethod
    def _args(dirs: dict[str, Path]) -> list[str]:
        return [
            "check-claims",
            "--claims-dir",
            str(dirs["claims_dir"]),
            "--analysis-dir",
            str(dirs["analysis_dir"]),
            "--sources",
            str(dirs["sources_dir"]),
            "--mappings",
            str(dirs["mappings_dir"]),
            "--no-extension-sync",
        ]

    def _hub_with_mapping_gap(self, tmp_path: Path) -> dict[str, Path]:
        dirs = _build_hub(tmp_path)
        _write_affinity(dirs["analysis_dir"], "crm", [("widgets", "widget")])
        write_registry(
            _registry("widget", [("crm", "widgets")]),
            registry_path(dirs["claims_dir"], "widget"),
        )
        return dirs

    def test_json_format_emits_the_versioned_result_verbatim(self, tmp_path):
        import json

        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        dirs = self._hub_with_mapping_gap(tmp_path)
        run = CliRunner().invoke(cli, [*self._args(dirs), "--format", "json"])

        assert run.exit_code == 0, run.output
        payload = json.loads(run.output)
        assert payload["schema_version"] == CLAIM_CHECK_RESULT_SCHEMA_VERSION
        assert payload["curation_complete"] is True
        # Mapping stays visible with its owning skill even though it never blocks.
        assert payload["mapping"]["is_blocking"] is True
        assert payload["mapping"]["owner_skill"] == "kairos-design-mapping"
        assert payload["semantic_generation"]["complete"] is True
        assert payload["disputed_claims"] == []

    def test_text_and_json_exit_codes_agree_across_flag_combinations(self, tmp_path):
        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        runner = CliRunner()
        for extra in ([], ["--require-mapping"], ["--strict"], ["--require-mapping", "--warn-only"]):
            case = "-".join(a.strip("-") for a in extra) or "default"
            dirs = self._hub_with_mapping_gap(tmp_path / f"case-{case}")
            args = [*self._args(dirs), *extra]
            text_run = runner.invoke(cli, args)
            json_run = runner.invoke(cli, [*args, "--format", "json"])
            assert text_run.exit_code == json_run.exit_code, (
                f"{extra}: text={text_run.exit_code} json={json_run.exit_code}\n"
                f"{text_run.output}\n---\n{json_run.output}"
            )
        # And the flag actually changes the outcome (the parity above is not vacuous).
        dirs = self._hub_with_mapping_gap(tmp_path / "effect")
        assert runner.invoke(cli, self._args(dirs)).exit_code == 0
        assert runner.invoke(
            cli, [*self._args(dirs), "--require-mapping"]
        ).exit_code == 1
