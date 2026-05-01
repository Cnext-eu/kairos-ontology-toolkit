# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""End-to-end projection tests — run the full pipeline and inspect output files.

Unlike the unit/scenario tests that call ``generate_*_artifacts()`` and inspect
in-memory dicts, these tests invoke ``run_projections()`` against the acme-hub
and verify the actual file tree written to disk.  This catches bugs in output
paths, file naming, missing artifacts, and cross-target consistency.
"""

import shutil
from pathlib import Path

import pytest
import yaml

from .conftest import HUB_ROOT


# ---------------------------------------------------------------------------
# Fixture — run full projection once, share the output tree
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def projected_hub(tmp_path_factory):
    """Copy acme-hub → tmp, run ``run_projections(target="all")``, return root."""
    hub = tmp_path_factory.mktemp("acme-hub")
    shutil.copytree(HUB_ROOT, hub, dirs_exist_ok=True)

    from kairos_ontology.projector import run_projections

    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "catalog-v001.xml",  # does not exist — graceful fallback
        output_path=hub / "output",
        target="all",
    )
    return hub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_relative(root: Path) -> set[str]:
    """Return set of POSIX-style relative paths for all files under *root*."""
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


# ===========================================================================
# dbt output tree
# ===========================================================================

class TestDbtOutputTree:
    """Verify expected directories and key files exist in the dbt output."""

    def test_dbt_project_yml_exists(self, projected_hub):
        dbt = projected_hub / "output" / "medallion" / "dbt"
        assert (dbt / "dbt_project.yml").is_file()

    def test_client_silver_models_dir(self, projected_hub):
        dbt = projected_hub / "output" / "medallion" / "dbt"
        silver_client = dbt / "models" / "silver" / "client"
        assert silver_client.is_dir(), f"Missing: {silver_client}"
        sql_files = list(silver_client.rglob("*.sql"))
        assert len(sql_files) >= 1, "No .sql files in silver/client/"

    def test_invoice_silver_models_dir(self, projected_hub):
        dbt = projected_hub / "output" / "medallion" / "dbt"
        silver_invoice = dbt / "models" / "silver" / "invoice"
        assert silver_invoice.is_dir(), f"Missing: {silver_invoice}"
        sql_files = list(silver_invoice.rglob("*.sql"))
        assert len(sql_files) >= 1, "No .sql files in silver/invoice/"

    def test_analyses_dir_has_ddl(self, projected_hub):
        """Silver DDL files live under analyses/{domain}/."""
        dbt = projected_hub / "output" / "medallion" / "dbt"
        analyses = dbt / "analyses"
        assert analyses.is_dir(), "Missing analyses/ directory"
        sql_files = list(analyses.rglob("*.sql"))
        assert len(sql_files) >= 1, "No DDL .sql files in analyses/"

    def test_docs_diagrams_has_erd(self, projected_hub):
        """Mermaid ERD files live under docs/diagrams/."""
        dbt = projected_hub / "output" / "medallion" / "dbt"
        diagrams = dbt / "docs" / "diagrams"
        assert diagrams.is_dir(), "Missing docs/diagrams/ directory"
        mmd_files = list(diagrams.rglob("*.mmd"))
        assert len(mmd_files) >= 1, "No .mmd ERD files"

    def test_master_erd_exists(self, projected_hub):
        dbt = projected_hub / "output" / "medallion" / "dbt"
        master = dbt / "docs" / "diagrams" / "master-erd.mmd"
        assert master.is_file(), "Missing master-erd.mmd"


# ===========================================================================
# dbt content validation
# ===========================================================================

class TestDbtContent:
    """Validate dbt file content — parseable YAML, non-empty SQL."""

    def test_dbt_project_yml_valid_yaml(self, projected_hub):
        path = projected_hub / "output" / "medallion" / "dbt" / "dbt_project.yml"
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "name" in content, "dbt_project.yml missing 'name' key"
        assert "profile" in content, "dbt_project.yml missing 'profile' key"

    def test_sources_yml_exist(self, projected_hub):
        """Per-source _*__sources.yml files should exist under models/silver/."""
        silver = projected_hub / "output" / "medallion" / "dbt" / "models" / "silver"
        sources_files = list(silver.glob("_*__sources.yml"))
        assert len(sources_files) >= 2, (
            f"Expected ≥2 source YAML files, found: {[f.name for f in sources_files]}"
        )
        for sf in sources_files:
            content = yaml.safe_load(sf.read_text(encoding="utf-8"))
            assert "sources" in content, f"{sf.name} missing 'sources' key"

    def test_models_yml_per_domain(self, projected_hub):
        """Each domain should have a _*__models.yml with column definitions."""
        dbt = projected_hub / "output" / "medallion" / "dbt"
        for domain in ("client", "invoice"):
            domain_dir = dbt / "models" / "silver" / domain
            models_files = list(domain_dir.glob("_*__models.yml"))
            assert len(models_files) >= 1, (
                f"No _models.yml found for {domain} in {domain_dir}"
            )
            for mf in models_files:
                content = yaml.safe_load(mf.read_text(encoding="utf-8"))
                assert "models" in content, f"{mf.name} missing 'models'"
                has_columns = any(m.get("columns") for m in content["models"])
                assert has_columns, f"{mf.name}: no model has columns"

    def test_sql_files_non_empty(self, projected_hub):
        """Every generated .sql file should contain actual SQL content."""
        dbt = projected_hub / "output" / "medallion" / "dbt"
        models_dir = dbt / "models"
        if not models_dir.exists():
            pytest.skip("No models/ directory")
        sql_files = list(models_dir.rglob("*.sql"))
        assert len(sql_files) >= 2, "Expected at least 2 SQL model files"
        for sql_file in sql_files:
            content = sql_file.read_text(encoding="utf-8").strip()
            assert len(content) > 10, f"SQL file is empty/trivial: {sql_file.name}"
            # Should contain SELECT (fundamental for any dbt model)
            assert "SELECT" in content.upper() or "select" in content, (
                f"SQL file missing SELECT: {sql_file.name}"
            )


# ===========================================================================
# Gold / Power BI output tree
# ===========================================================================

class TestGoldOutputTree:
    """Verify gold (Power BI / TMDL) output structure."""

    def test_gold_output_dir_exists(self, projected_hub):
        gold = projected_hub / "output" / "medallion" / "powerbi"
        assert gold.is_dir(), "Missing output/medallion/powerbi/ directory"

    def test_tmdl_definition_exists(self, projected_hub):
        """At least one domain should produce a TMDL model.tmdl file."""
        gold = projected_hub / "output" / "medallion" / "powerbi"
        tmdl_files = list(gold.rglob("model.tmdl"))
        assert len(tmdl_files) >= 1, "No model.tmdl files in gold output"

    def test_tmdl_tables_subdir(self, projected_hub):
        """TMDL output should have a tables/ subdirectory with .tmdl files."""
        gold = projected_hub / "output" / "medallion" / "powerbi"
        tables_dirs = list(gold.rglob("tables"))
        has_table_files = any(
            list(d.glob("*.tmdl")) for d in tables_dirs if d.is_dir()
        )
        assert has_table_files, "No .tmdl table files in tables/ subdirectory"

    def test_gold_ddl_exists(self, projected_hub):
        """Gold DDL SQL file should exist for at least one domain."""
        gold = projected_hub / "output" / "medallion" / "powerbi"
        sql_files = list(gold.rglob("*.sql"))
        assert len(sql_files) >= 1, "No DDL .sql files in gold output"

    def test_gold_erd_exists(self, projected_hub):
        """Gold ERD Mermaid file should exist for at least one domain."""
        gold = projected_hub / "output" / "medallion" / "powerbi"
        mmd_files = list(gold.rglob("*.mmd"))
        assert len(mmd_files) >= 1, "No .mmd ERD files in gold output"


# ===========================================================================
# Multi-source and cross-domain consistency
# ===========================================================================

class TestMultiSourceConsistency:
    """Client domain has 2 sources (AdminPulse + CRMSystem) → per-source views + union."""

    def test_client_has_per_source_views(self, projected_hub):
        """Client silver should have per-source SQL files."""
        client_dir = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "client"
        )
        sql_files = {f.name for f in client_dir.rglob("*.sql")}
        # Should have admin_pulse and crm_system specific files
        has_adminpulse = any("admin" in f.lower() for f in sql_files)
        has_crmsystem = any("crm" in f.lower() for f in sql_files)
        assert has_adminpulse, (
            f"No AdminPulse per-source view found in: {sql_files}"
        )
        assert has_crmsystem, (
            f"No CRM system per-source view found in: {sql_files}"
        )

    def test_invoice_single_source(self, projected_hub):
        """Invoice domain has 1 source (BillingPro) — should still have models."""
        invoice_dir = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "invoice"
        )
        sql_files = list(invoice_dir.rglob("*.sql"))
        assert len(sql_files) >= 1, "Invoice domain has no SQL model files"


class TestCrossDomainConsistency:
    """Both client and invoice domains should be present across all targets."""

    def test_both_domains_in_dbt(self, projected_hub):
        dbt = projected_hub / "output" / "medallion" / "dbt" / "models" / "silver"
        assert (dbt / "client").is_dir(), "client missing from dbt silver"
        assert (dbt / "invoice").is_dir(), "invoice missing from dbt silver"

    def test_both_domains_in_gold(self, projected_hub):
        gold = projected_hub / "output" / "medallion" / "powerbi"
        files = _collect_relative(gold)
        has_client = any("client" in f.lower() for f in files)
        has_invoice = any("invoice" in f.lower() for f in files)
        assert has_client, f"client missing from gold output: {files}"
        assert has_invoice, f"invoice missing from gold output: {files}"

    def test_projection_report_exists(self, projected_hub):
        report = projected_hub / "output" / "projection-report.json"
        assert report.is_file(), "Missing projection-report.json"

    def test_projection_report_no_errors(self, projected_hub):
        """The projection report should not contain any errors."""
        import json
        report = projected_hub / "output" / "projection-report.json"
        data = json.loads(report.read_text(encoding="utf-8"))
        errors = data.get("summary", {}).get("errors", 0)
        assert errors == 0, (
            f"Projection report has {errors} error(s): "
            f"{[e for e in data.get('events', []) if e.get('level') == 'error']}"
        )

    def test_domain_manifests_exist(self, projected_hub):
        """Per-domain projection manifests should be written."""
        output = projected_hub / "output"
        manifests = list(output.glob("*-projection-manifest.json"))
        assert len(manifests) >= 2, (
            f"Expected manifests for client + invoice, found: {[m.name for m in manifests]}"
        )
