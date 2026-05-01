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
from rdflib import Graph, Namespace

from .conftest import HUB_ROOT, MAPPINGS_DIR, SHAPES_DIR


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
# FK auto-inference via natural key matching
# ===========================================================================

class TestFKAutoInference:
    """Verify FK auto-inference generates proper joins in E2E projection."""

    def test_split_subclass_fk_join_generated(self, projected_hub):
        """Split subclass models should auto-infer FK join to ClientType."""
        client_dir = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "client"
        )
        # Check IndividualClient and SoleProprietorClient (split subclasses)
        for model_name in ("individual_client", "sole_proprietor_client"):
            sql_file = client_dir / f"{model_name}.sql"
            if not sql_file.exists():
                pytest.skip(f"{model_name}.sql not found")
            content = sql_file.read_text(encoding="utf-8")
            assert "client_type_ref" in content, (
                f"{model_name} missing client_type_ref join alias"
            )
            assert "ref('client_type')" in content, (
                f"{model_name} missing ref to client_type model"
            )
            assert "client_type_sk" in content, (
                f"{model_name} missing client_type_sk FK column"
            )
            # Should NOT have NULL for client_type_sk
            lines = content.split("\n")
            sk_lines = [l for l in lines if "client_type_sk" in l]
            for line in sk_lines:
                assert "NULL" not in line, (
                    f"{model_name}: client_type_sk is NULL, "
                    f"auto-inference should have resolved it: {line}"
                )

    def test_fk_join_condition_uses_nk(self, projected_hub):
        """FK join should reference the NK column of the target class."""
        client_dir = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "client"
        )
        # Pick any split subclass
        sql_file = client_dir / "individual_client.sql"
        if not sql_file.exists():
            pytest.skip("individual_client.sql not found")
        content = sql_file.read_text(encoding="utf-8")
        # Should join on type_code (ClientType's naturalKey)
        assert "type_code" in content, (
            "FK join missing type_code (ClientType NK) in join condition"
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


# ===========================================================================
# Mapping cross-validation — RDF mappings ↔ dbt SQL output
# ===========================================================================

def _parse_expected_mappings(mapping_file: Path) -> dict:
    """Parse a SKOS mapping TTL and return structured expectations.

    Returns:
        {
            "table_mappings": [(bronze_table_local, target_class_local, mapping_type)],
            "column_mappings": [(bronze_col_local, target_prop_local, transform)],
            "fk_mappings": [(bronze_col_local, target_prop_local, transform)],
        }

    FK mappings (ObjectProperties that resolve to joins) are separated from
    regular column mappings because they produce SK join columns, not direct
    target-named columns in the SQL output.
    """
    from kairos_ontology.projections.uri_utils import extract_local_name

    g = Graph()
    g.parse(mapping_file, format="turtle")

    SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
    KAIROS_MAP = Namespace("https://kairos.cnext.eu/mapping#")
    RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")

    match_preds = [
        SKOS.exactMatch, SKOS.closeMatch, SKOS.narrowMatch,
        SKOS.broadMatch, SKOS.relatedMatch,
    ]

    table_mappings = []
    column_mappings = []
    fk_mappings = []

    for pred in match_preds:
        for subj, obj in g.subject_objects(pred):
            subj_local = extract_local_name(str(subj))
            obj_local = extract_local_name(str(obj))
            mapping_type = str(g.value(subj, KAIROS_MAP.mappingType) or "direct")
            transform = str(g.value(subj, KAIROS_MAP.transform) or "")
            comment = str(g.value(subj, RDFS.comment) or "")

            # Heuristic: table-level mappings have PascalCase targets (classes)
            # column-level have camelCase targets (properties)
            if obj_local and obj_local[0].isupper():
                table_mappings.append((subj_local, obj_local, mapping_type))
            elif "FK" in comment or "join" in comment.lower():
                # FK mappings produce SK join columns, not direct columns
                fk_mappings.append((subj_local, obj_local, transform))
            else:
                column_mappings.append((subj_local, obj_local, transform))

    return {
        "table_mappings": table_mappings,
        "column_mappings": column_mappings,
        "fk_mappings": fk_mappings,
    }


def _to_snake_case(name: str) -> str:
    """Convert camelCase/PascalCase to snake_case."""
    import re
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class TestMappingToSqlConsistency:
    """Cross-validate: every column mapping in TTL → column in dbt SQL output."""

    def test_adminpulse_column_mappings_in_sql(self, projected_hub):
        """All AdminPulse column mappings should produce columns in dbt SQL."""
        mapping_file = MAPPINGS_DIR / "adminpulse-to-client.ttl"
        expected = _parse_expected_mappings(mapping_file)

        client_dir = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "client"
        )
        # Collect all SQL content from client models
        all_sql = ""
        for f in client_dir.rglob("*.sql"):
            all_sql += f.read_text(encoding="utf-8") + "\n"
        all_sql_lower = all_sql.lower()

        missing = []
        for _bronze_col, target_prop, transform in expected["column_mappings"]:
            # The target property should appear as a snake_case column alias
            snake_col = _to_snake_case(target_prop)
            if snake_col not in all_sql_lower:
                missing.append(f"{target_prop} → {snake_col}")

        assert not missing, (
            f"Mapping columns not found in dbt SQL output:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_billingpro_column_mappings_in_sql(self, projected_hub):
        """All BillingPro column mappings should produce columns in dbt SQL."""
        mapping_file = MAPPINGS_DIR / "billingpro-to-invoice.ttl"
        expected = _parse_expected_mappings(mapping_file)

        invoice_dir = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "invoice"
        )
        all_sql = ""
        for f in invoice_dir.rglob("*.sql"):
            all_sql += f.read_text(encoding="utf-8") + "\n"
        all_sql_lower = all_sql.lower()

        missing = []
        for _bronze_col, target_prop, transform in expected["column_mappings"]:
            snake_col = _to_snake_case(target_prop)
            if snake_col not in all_sql_lower:
                missing.append(f"{target_prop} → {snake_col}")

        assert not missing, (
            f"Mapping columns not found in dbt SQL output:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_crmsystem_column_mappings_in_sql(self, projected_hub):
        """All CRM system column mappings should produce columns in dbt SQL."""
        mapping_file = MAPPINGS_DIR / "crmsystem-to-client.ttl"
        expected = _parse_expected_mappings(mapping_file)

        client_dir = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "client"
        )
        all_sql = ""
        for f in client_dir.rglob("*.sql"):
            all_sql += f.read_text(encoding="utf-8") + "\n"
        all_sql_lower = all_sql.lower()

        missing = []
        for _bronze_col, target_prop, transform in expected["column_mappings"]:
            snake_col = _to_snake_case(target_prop)
            if snake_col not in all_sql_lower:
                missing.append(f"{target_prop} → {snake_col}")

        assert not missing, (
            f"Mapping columns not found in dbt SQL output:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_transforms_in_sql(self, projected_hub):
        """Transform expressions from mapping files should appear in SQL."""
        mapping_file = MAPPINGS_DIR / "billingpro-to-invoice.ttl"
        expected = _parse_expected_mappings(mapping_file)

        invoice_dir = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "invoice"
        )
        all_sql = ""
        for f in invoice_dir.rglob("*.sql"):
            all_sql += f.read_text(encoding="utf-8") + "\n"

        # Check that non-trivial transforms (CAST, expressions) appear in SQL
        transforms_found = 0
        transforms_expected = 0
        for _bronze_col, _target_prop, transform in expected["column_mappings"]:
            if not transform or transform.startswith("source."):
                continue  # simple column rename, won't appear verbatim
            transforms_expected += 1
            # The transform with "source." prefix stripped should be in SQL
            # (projector replaces source.X with the actual ref)
            # Check for the function/expression keyword
            keywords = []
            if "CAST(" in transform.upper():
                keywords.append("CAST(")
            if "*" in transform:
                keywords.append("*")
            if keywords and any(kw in all_sql.upper() for kw in keywords):
                transforms_found += 1

        assert transforms_found > 0, (
            f"No transform expressions found in SQL "
            f"(expected {transforms_expected} non-trivial transforms)"
        )

    def test_table_mappings_produce_models(self, projected_hub):
        """Each table-level mapping should produce at least one .sql model file."""
        mapping_file = MAPPINGS_DIR / "billingpro-to-invoice.ttl"
        expected = _parse_expected_mappings(mapping_file)

        invoice_dir = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "invoice"
        )
        sql_files = {f.stem.lower() for f in invoice_dir.rglob("*.sql")}

        missing = []
        for _bronze_tbl, target_class, _mtype in expected["table_mappings"]:
            snake_model = _to_snake_case(target_class)
            # The model file should match the target class name
            if not any(snake_model in f for f in sql_files):
                missing.append(f"{target_class} → {snake_model}.sql")

        assert not missing, (
            f"Table mappings without corresponding dbt model:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_schema_yaml_columns_match_mappings(self, projected_hub):
        """Columns in _models.yml should include all mapped properties."""
        mapping_file = MAPPINGS_DIR / "billingpro-to-invoice.ttl"
        expected = _parse_expected_mappings(mapping_file)

        invoice_dir = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "invoice"
        )
        models_files = list(invoice_dir.glob("_*__models.yml"))
        assert models_files, "No _models.yml found for invoice"

        # Collect all column names from schema YAML
        all_yaml_columns = set()
        for mf in models_files:
            content = yaml.safe_load(mf.read_text(encoding="utf-8"))
            for model in content.get("models", []):
                for col in model.get("columns", []):
                    all_yaml_columns.add(col["name"].lower())

        # Check that mapped properties appear as columns
        missing = []
        for _bronze_col, target_prop, _transform in expected["column_mappings"]:
            snake_col = _to_snake_case(target_prop)
            if snake_col not in all_yaml_columns:
                missing.append(f"{target_prop} → {snake_col}")

        assert not missing, (
            f"Mapped columns missing from _models.yml:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )


# ===========================================================================
# SHACL cross-validation — shapes constraints ↔ dbt tests in _models.yml
# ===========================================================================

def _parse_shacl_constraints(shapes_file: Path) -> dict[str, dict]:
    """Parse a SHACL shapes TTL and return expected constraints per property.

    Returns:
        {
            (target_class_local, property_local): {
                "min_count": int | None,
                "max_count": int | None,
                "pattern": str | None,
                "min_length": int | None,
                "min_inclusive": int | None,
            }
        }
    """
    from kairos_ontology.projections.uri_utils import extract_local_name

    g = Graph()
    g.parse(shapes_file, format="turtle")

    SH = Namespace("http://www.w3.org/ns/shacl#")
    RDF_NS = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")

    constraints = {}

    for node_shape in g.subjects(RDF_NS.type, SH.NodeShape):
        target_class = g.value(node_shape, SH.targetClass)
        if not target_class:
            continue
        class_local = extract_local_name(str(target_class))

        for ps in g.objects(node_shape, SH.property):
            path = g.value(ps, SH.path)
            if not path:
                continue
            prop_local = extract_local_name(str(path))

            constraint = {
                "min_count": None,
                "max_count": None,
                "pattern": None,
                "min_length": None,
                "min_inclusive": None,
            }

            mc = g.value(ps, SH.minCount)
            if mc:
                constraint["min_count"] = int(mc)
            xc = g.value(ps, SH.maxCount)
            if xc:
                constraint["max_count"] = int(xc)
            pat = g.value(ps, SH.pattern)
            if pat:
                constraint["pattern"] = str(pat)
            ml = g.value(ps, SH.minLength)
            if ml:
                constraint["min_length"] = int(ml)
            mi = g.value(ps, SH.minInclusive)
            if mi:
                constraint["min_inclusive"] = int(mi)

            constraints[(class_local, prop_local)] = constraint

    return constraints


class TestShaclToDbtTests:
    """Cross-validate: SHACL constraints → dbt tests in _models.yml."""

    def test_client_not_null_from_min_count(self, projected_hub):
        """sh:minCount 1 → not_null test on column."""
        constraints = _parse_shacl_constraints(SHAPES_DIR / "client-shapes.ttl")
        models_yml = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "client" / "_client__models.yml"
        )
        data = yaml.safe_load(models_yml.read_text(encoding="utf-8"))

        # Find columns that should be not_null per SHACL
        expected_not_null = [
            (cls, prop)
            for (cls, prop), c in constraints.items()
            if c["min_count"] and c["min_count"] > 0
        ]
        assert expected_not_null, "No minCount constraints found in SHACL"

        # Build lookup: model_name → {col_name: tests}
        tests_lookup = {}
        for model in data.get("models", []):
            model_tests = {}
            for col in model.get("columns", []):
                model_tests[col["name"]] = col.get("tests", [])
            tests_lookup[model["name"]] = model_tests

        missing = []
        for cls, prop in expected_not_null:
            col_name = _to_snake_case(prop)
            model_name = _to_snake_case(cls)
            model_tests = tests_lookup.get(model_name, {})
            col_tests = model_tests.get(col_name, [])
            # Tests can be strings or dicts
            test_names = [t if isinstance(t, str) else list(t.keys())[0] for t in col_tests]
            if "not_null" not in test_names:
                missing.append(f"{cls}.{prop} ({model_name}.{col_name})")

        assert not missing, (
            f"SHACL sh:minCount 1 not reflected as not_null in dbt tests:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_client_unique_from_min_max_count_1(self, projected_hub):
        """sh:minCount 1 + sh:maxCount 1 → unique test on column."""
        constraints = _parse_shacl_constraints(SHAPES_DIR / "client-shapes.ttl")
        models_yml = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "client" / "_client__models.yml"
        )
        data = yaml.safe_load(models_yml.read_text(encoding="utf-8"))

        expected_unique = [
            (cls, prop)
            for (cls, prop), c in constraints.items()
            if c["min_count"] == 1 and c["max_count"] == 1
        ]
        assert expected_unique, "No minCount+maxCount=1 constraints found"

        tests_lookup = {}
        for model in data.get("models", []):
            model_tests = {}
            for col in model.get("columns", []):
                model_tests[col["name"]] = col.get("tests", [])
            tests_lookup[model["name"]] = model_tests

        missing = []
        for cls, prop in expected_unique:
            col_name = _to_snake_case(prop)
            model_name = _to_snake_case(cls)
            model_tests = tests_lookup.get(model_name, {})
            col_tests = model_tests.get(col_name, [])
            test_names = [t if isinstance(t, str) else list(t.keys())[0] for t in col_tests]
            if "unique" not in test_names:
                missing.append(f"{cls}.{prop} ({model_name}.{col_name})")

        assert not missing, (
            f"SHACL sh:minCount+maxCount=1 not reflected as unique in dbt:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_client_regex_from_pattern(self, projected_hub):
        """sh:pattern → dbt_expectations regex test."""
        constraints = _parse_shacl_constraints(SHAPES_DIR / "client-shapes.ttl")
        models_yml = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "client" / "_client__models.yml"
        )
        data = yaml.safe_load(models_yml.read_text(encoding="utf-8"))

        expected_patterns = [
            (cls, prop, c["pattern"])
            for (cls, prop), c in constraints.items()
            if c["pattern"]
        ]
        assert expected_patterns, "No sh:pattern constraints found"

        tests_lookup = {}
        for model in data.get("models", []):
            model_tests = {}
            for col in model.get("columns", []):
                model_tests[col["name"]] = col.get("tests", [])
            tests_lookup[model["name"]] = model_tests

        missing = []
        for cls, prop, pattern in expected_patterns:
            col_name = _to_snake_case(prop)
            model_name = _to_snake_case(cls)
            model_tests = tests_lookup.get(model_name, {})
            col_tests = model_tests.get(col_name, [])
            # Look for regex test (can be dict with nested structure)
            has_regex = any(
                "expect_column_values_to_match_regex" in str(t)
                for t in col_tests
            )
            if not has_regex:
                missing.append(f"{cls}.{prop} pattern='{pattern}'")

        assert not missing, (
            f"SHACL sh:pattern not reflected as regex test in dbt:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_invoice_min_inclusive_from_shacl(self, projected_hub):
        """sh:minInclusive → dbt_expectations between test."""
        constraints = _parse_shacl_constraints(SHAPES_DIR / "invoice-shapes.ttl")
        models_yml = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "invoice" / "_invoice__models.yml"
        )
        data = yaml.safe_load(models_yml.read_text(encoding="utf-8"))

        expected_min = [
            (cls, prop, c["min_inclusive"])
            for (cls, prop), c in constraints.items()
            if c["min_inclusive"] is not None
        ]
        assert expected_min, "No sh:minInclusive constraints found"

        tests_lookup = {}
        for model in data.get("models", []):
            model_tests = {}
            for col in model.get("columns", []):
                model_tests[col["name"]] = col.get("tests", [])
            tests_lookup[model["name"]] = model_tests

        missing = []
        for cls, prop, min_val in expected_min:
            col_name = _to_snake_case(prop)
            model_name = _to_snake_case(cls)
            model_tests = tests_lookup.get(model_name, {})
            col_tests = model_tests.get(col_name, [])
            has_between = any(
                "expect_column_values_to_be_between" in str(t)
                for t in col_tests
            )
            if not has_between:
                missing.append(f"{cls}.{prop} minInclusive={min_val}")

        assert not missing, (
            f"SHACL sh:minInclusive not reflected as between test in dbt:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_invoice_not_null_constraints(self, projected_hub):
        """Invoice SHACL sh:minCount 1 → not_null in _models.yml."""
        constraints = _parse_shacl_constraints(SHAPES_DIR / "invoice-shapes.ttl")
        models_yml = (
            projected_hub / "output" / "medallion" / "dbt"
            / "models" / "silver" / "invoice" / "_invoice__models.yml"
        )
        data = yaml.safe_load(models_yml.read_text(encoding="utf-8"))

        expected_not_null = [
            (cls, prop)
            for (cls, prop), c in constraints.items()
            if c["min_count"] and c["min_count"] > 0
        ]

        tests_lookup = {}
        for model in data.get("models", []):
            model_tests = {}
            for col in model.get("columns", []):
                model_tests[col["name"]] = col.get("tests", [])
            tests_lookup[model["name"]] = model_tests

        missing = []
        for cls, prop in expected_not_null:
            col_name = _to_snake_case(prop)
            model_name = _to_snake_case(cls)
            model_tests = tests_lookup.get(model_name, {})
            col_tests = model_tests.get(col_name, [])
            test_names = [t if isinstance(t, str) else list(t.keys())[0] for t in col_tests]
            if "not_null" not in test_names:
                missing.append(f"{cls}.{prop} ({model_name}.{col_name})")

        assert not missing, (
            f"Invoice SHACL sh:minCount 1 not reflected as not_null:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )
