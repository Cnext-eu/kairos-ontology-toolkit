# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Enforce the semantic-loading boundary and inventory direct parse exceptions."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
CORE = ROOT / "src" / "kairos_ontology" / "core"

# Every production module that directly parses RDF must be classified. Domain/reference
# ontology semantics are absent from this allow-list except ontology_loader itself.
ALLOWED_DIRECT_PARSE_SITES = {
    "analyse_sources.py": "source vocabularies and ontology-package discovery",
    "authoring_scaffolds.py": "source vocabularies and SKOS mapping overlays",
    "catalog_utils.py": "XML catalog parsing",
    "evidence_loaders.py": "advisory SKOS mapping evidence",
    "compiler/kernel.py": (
        "source vocabulary extraction only; domain ontology semantics use ontology_loader"
    ),
    "coverage_report.py": "SKOS mappings",
    "dbt_contracts.py": "dbt YAML artifact parsing",
    "ddd.py": "DDD vocabulary, overlay, and SHACL shapes",
    "design_validation.py": "source vocabularies, mapping and extension overlays, and SHACL shapes",
    "draft_model_report.py": "business glossary",
    "import_source.py": "authored source-vocabulary mutation",
    "ontology_loader.py": "canonical domain/reference ontology loader",
    "ontology_scope.py": "hub ontology declarations only",
    "ontology_ops.py": "explicit single-file CRUD and syntax API",
    "projector.py": "Silver extension overlays and reference defaults",
    "reference_modules.py": "typed module-profile annotation overlays",
    "silver_sample_audit.py": "source vocabularies",
    "source_catalog.py": "source vocabularies",
    "source_analysis.py": "source and SKOS mapping vocabularies",
    "source_privacy.py": "source-vocabulary privacy inspection",
    "suggest_shapes.py": "source vocabulary",
    "validator.py": "syntax/content checks, extensions, mappings, and SHACL shapes",
    "projections/a2ui_projector.py": "SHACL shapes",
    "projections/ddd_projector.py": "DDD overlay",
    "projections/medallion_dbt_projector.py": "sources, mappings, extensions, and templates",
    "projections/medallion_gold_projector.py": "SHACL shapes",
    "projections/medallion_silver_projector.py": "SHACL shapes",
    "projections/dbt/render.py": "Jinja template syntax validation",
    "projections/dbt/mapping_bind.py": "typed SKOS mapping contracts",
    "projections/dbt/policy_bind.py": "source preparation policy TTL",
    "projections/report_projector.py": "sources, mappings, extensions, and report inputs",
    "projections/shared.py": "projection extension overlays",
    "projections/skos_utils.py": "SKOS mappings",
}


def test_every_direct_parse_site_has_an_explicit_nonsemantic_classification():
    actual = {
        path.relative_to(CORE).as_posix()
        for path in CORE.rglob("*.py")
        if ".parse(" in path.read_text(encoding="utf-8")
    }

    assert actual <= set(ALLOWED_DIRECT_PARSE_SITES), (
        "New direct parse site bypasses the canonical semantic loader: "
        f"{sorted(actual - set(ALLOWED_DIRECT_PARSE_SITES))}"
    )


def test_legacy_catalog_graph_loader_has_no_production_consumers():
    offenders = []
    package = ROOT / "src" / "kairos_ontology"
    allowed = {
        package / "__init__.py",
        CORE / "catalog_utils.py",
    }
    for path in package.rglob("*.py"):
        if path in allowed:
            continue
        if "load_graph_with_catalog" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []
