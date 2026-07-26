# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
from pathlib import Path

import yaml
import pytest
from click.testing import CliRunner
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from kairos_ontology.core.completeness_model import (
    ALIGNMENT_ALGORITHM_VERSION,
    compute_affinity_hash,
)
from kairos_ontology.core.claim_projection_sync import (
    ScaffoldMetadataError,
    ScaffoldPartialFailureError,
    _collect_hub_domain_bases,
    apply_projection_sync,
    evaluate_projection_sync,
    scaffold_missing_surfaces,
)
from kairos_ontology.core.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    EvidenceSource,
    Freshness,
    load_registry,
    registry_path,
    write_registry,
)
from kairos_ontology.cli.main import cli
from kairos_ontology.core.projections.shared import KAIROS_EXT


def _write_affinity(analysis_dir: Path) -> None:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "system": "crm",
        "schema_version": 2,
        "tables": [{"table": "account", "domain": "party"}],
    }
    with open(analysis_dir / "crm-affinity.yaml", "w", encoding="utf-8") as fh:
        yaml.dump(data, fh, sort_keys=False)


def _write_registry(claims_dir: Path) -> None:
    claim = Claim(
        id="party-trade-party",
        type="class",
        status="approved",
        disposition="claim",
        origin="imported",
        class_uri="https://example.org/ref/party#TradeParty",
        evidence_sources=[EvidenceSource(type="source_table", system="crm", table="account")],
    )
    registry = ClaimRegistry(
        domain="party",
        generated_at="2026-06-15T00:00:00Z",
        algorithm_version=ALIGNMENT_ALGORITHM_VERSION,
        freshness=Freshness(affinity_sha256=compute_affinity_hash({("crm", "account")})),
        coverage=[CoverageSystem(system="crm", tables=[CoverageTable(table="account")])],
        claims=[claim],
    )
    write_registry(registry, registry_path(claims_dir, "party"))


def _write_domain_files(model_dir: Path, *, with_drift: bool) -> None:
    ontologies = model_dir / "ontologies"
    extensions = model_dir / "extensions"
    ontologies.mkdir(parents=True, exist_ok=True)
    extensions.mkdir(parents=True, exist_ok=True)

    ontology = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dom: <https://example.org/domain/party#> .

<https://example.org/domain/party> a owl:Ontology ;
    rdfs:label "Party"@en .

dom:Party a owl:Class ;
    rdfs:label "Party"@en ;
    rdfs:comment "Party entity."@en .
"""
    (ontologies / "party.ttl").write_text(ontology, encoding="utf-8")

    if with_drift:
        ext = """@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

# >>> kairos-managed (generated from the Claim Registry — do not edit)
<https://example.org/domain/party> kairos-ext:silverIncludeImports true .
# <<< kairos-managed
"""
    else:
        ext = """@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix ref: <https://example.org/ref/party#> .

# >>> kairos-managed (generated from the Claim Registry — do not edit)
ref:TradeParty kairos-ext:silverInclude true .
# <<< kairos-managed
"""
    (extensions / "party-silver-ext.ttl").write_text(ext, encoding="utf-8")


def test_evaluate_projection_sync_detects_import_and_include_drift(tmp_path):
    model = tmp_path / "model"
    claims_dir = model / "claims"
    _write_registry(claims_dir)
    _write_domain_files(model, with_drift=True)

    report = evaluate_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=model / "ontologies",
        extensions_dir=model / "extensions",
    )
    assert len(report.domains) == 1
    domain = report.domains[0]
    assert domain.domain == "party"
    assert "https://example.org/ref/party" in domain.missing_imports
    assert "https://example.org/ref/party#TradeParty" in domain.missing_includes
    assert domain.has_bulk_include_imports
    assert not domain.in_sync


def test_apply_projection_sync_rewrites_imports_and_includes(tmp_path):
    model = tmp_path / "model"
    claims_dir = model / "claims"
    _write_registry(claims_dir)
    _write_domain_files(model, with_drift=True)

    report = apply_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=model / "ontologies",
        extensions_dir=model / "extensions",
    )
    assert not report.is_blocking

    onto_graph = Graph()
    onto_graph.parse(model / "ontologies" / "party.ttl", format="turtle")
    onto_subj = next(onto_graph.subjects(RDF.type, OWL.Ontology))
    imports = {str(o).rstrip("#/") for o in onto_graph.objects(onto_subj, OWL.imports)}
    assert imports == {"https://example.org/ref/party"}

    ext_graph = Graph()
    ext_graph.parse(model / "extensions" / "party-silver-ext.ttl", format="turtle")
    include_val = ext_graph.value(
        subject=URIRef("https://example.org/ref/party#TradeParty"),
        predicate=KAIROS_EXT.silverInclude,
    )
    assert str(include_val).lower() in {"true", "1"}
    bulk = ext_graph.value(
        subject=None,
        predicate=KAIROS_EXT.silverIncludeImports,
    )
    assert bulk is None


def test_check_claims_blocks_on_sync_drift_and_passes_after_generation(tmp_path):
    """DD-122: sync drift is visible in ``check-claims`` but does not block it —
    only the owning workflow (``claims-to-silver-ext --check-only``) blocks."""
    model = tmp_path / "model"
    claims_dir = model / "claims"
    _write_registry(claims_dir)
    _write_domain_files(model, with_drift=True)

    analysis = tmp_path / "integration" / "sources" / "_analysis"
    _write_affinity(analysis)

    runner = CliRunner()
    before = runner.invoke(
        cli,
        [
            "check-claims",
            "--analysis-dir",
            str(analysis),
            "--claims-dir",
            str(claims_dir),
            "--no-source-coverage",
        ],
    )
    assert before.exit_code == 0, before.output
    assert "sync drift detected" in before.output
    assert "kairos-design-domain" in before.output

    generate = runner.invoke(
        cli,
        [
            "claims-to-silver-ext",
            "--claims-dir",
            str(claims_dir),
            "--check-only",
        ],
    )
    assert generate.exit_code == 1, generate.output

    apply_cmd = runner.invoke(
        cli,
        [
            "claims-to-silver-ext",
            "--claims-dir",
            str(claims_dir),
        ],
    )
    assert apply_cmd.exit_code == 0, apply_cmd.output

    after = runner.invoke(
        cli,
        [
            "check-claims",
            "--analysis-dir",
            str(analysis),
            "--claims-dir",
            str(claims_dir),
            "--no-source-coverage",
        ],
    )
    assert after.exit_code == 0, after.output


_ORDERS_MODULE_IRI = "https://example.org/reference/orders"
_ORDERS_NS = _ORDERS_MODULE_IRI + "#"


def _write_orders_reference_pack(tmp_path: Path) -> tuple[Path, Path]:
    """A reference-modules pack wiring domain ``orders`` to an *unconditionally*
    activated module (data-domains.yaml group activation), independent of any
    claim — matches the fixture in ``test_reference_modules.py``'s deferred-only
    regression, kept local here so this file's tests stay self-contained."""
    ref_models = tmp_path / "reference-models"
    blueprint = ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint"
    blueprint.mkdir(parents=True)
    module = ref_models / "modules" / "orders.ttl"
    module.parent.mkdir()
    module.write_text(
        f"""\
@prefix ex: <{_ORDERS_NS}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<{_ORDERS_MODULE_IRI}> a owl:Ontology ; owl:versionInfo "1.0.0" .
ex:Order a owl:Class .
ex:SpecialOrder a owl:Class .
""",
        encoding="utf-8",
    )
    (blueprint / "data-domains.yaml").write_text(
        f"""\
schema_version: "2.0"
module_profiles:
  - id: orders
    ontology_iri: {_ORDERS_MODULE_IRI}
    catalog_uri: {_ORDERS_NS}
    version_pin: 1.0.0
    term_namespaces: [{_ORDERS_NS}]
    root_classes: [{_ORDERS_NS}Order]
    projection:
      allowlist: [{_ORDERS_NS}Order]
groups:
  - id: operations
    domains:
      - id: orders
        imports:
          - profile: orders
""",
        encoding="utf-8",
    )
    catalog = ref_models / "catalog-v001.xml"
    catalog.write_text(
        f"""\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="{_ORDERS_NS}" uri="modules/orders.ttl"/>
  <uri name="{_ORDERS_MODULE_IRI}" uri="modules/orders.ttl"/>
</catalog>
""",
        encoding="utf-8",
    )
    return ref_models, catalog


def _write_orders_domain_files(model_dir: Path) -> None:
    ontologies = model_dir / "ontologies"
    extensions = model_dir / "extensions"
    ontologies.mkdir(parents=True, exist_ok=True)
    extensions.mkdir(parents=True, exist_ok=True)
    (ontologies / "orders.ttl").write_text(
        """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://example.org/hub/orders> a owl:Ontology ;
    rdfs:label "Orders"@en .
""",
        encoding="utf-8",
    )
    (extensions / "orders-silver-ext.ttl").write_text(
        "@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .\n",
        encoding="utf-8",
    )


def test_evaluate_projection_sync_surfaces_disputed_claims_and_owner_skill(tmp_path):
    """DD-122: a deferred claim whose module stays active for another reason
    (here the domain's unconditional data-domain activation) is reported as a
    disputed claim through the full ``evaluate_projection_sync`` composition —
    not just at the lower-level ``build_managed_import_plan`` — and the report
    carries the ``owner_skill`` that owns enforcing sync drift."""
    from kairos_ontology.core.claim_registry import Claim as _Claim

    ref_models, catalog = _write_orders_reference_pack(tmp_path)
    model = tmp_path / "model"
    claims_dir = model / "claims"
    _write_orders_domain_files(model)

    registry = ClaimRegistry(
        domain="orders",
        claims=[
            _Claim(
                id="order-class",
                type="class",
                origin="imported",
                status="deferred",
                disposition="claim",
                class_uri=_ORDERS_NS + "SpecialOrder",
            ),
        ],
    )
    write_registry(registry, registry_path(claims_dir, "orders"))

    report = evaluate_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=model / "ontologies",
        extensions_dir=model / "extensions",
        ref_models_dir=ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )

    assert report.owner_skill == "kairos-design-domain"
    assert len(report.domains) == 1
    domain_status = report.domains[0]
    assert domain_status.domain == "orders"
    assert domain_status.disputed_claims, "expected the deferred claim to be disputed"
    entry = domain_status.disputed_claims[0]
    assert entry["claim_id"] == "order-class"
    assert entry["claim_status"] == "deferred"
    assert entry["domain"] == "orders"
    assert "data-domain:orders" in entry["reasons"]
    # The report-level property flattens every domain's disputed claims.
    assert report.disputed_claims == domain_status.disputed_claims


def _write_foundation(ontologies_dir: Path) -> str:
    """Write a ``_`` -prefixed shared base ontology and return its IRI."""
    ontologies_dir.mkdir(parents=True, exist_ok=True)
    foundation_iri = "https://example.org/domain/_foundation"
    foundation = f"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<{foundation_iri}> a owl:Ontology ;
    rdfs:label "Foundation"@en .
"""
    (ontologies_dir / "_foundation.ttl").write_text(foundation, encoding="utf-8")
    return foundation_iri


def test_collect_hub_domain_bases_includes_underscore_prefixed(tmp_path):
    ontologies = tmp_path / "ontologies"
    foundation_iri = _write_foundation(ontologies)
    (ontologies / "party-silver-ext.ttl").write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<https://example.org/domain/party-ext> a owl:Ontology .\n",
        encoding="utf-8",
    )

    bases = _collect_hub_domain_bases(ontologies)

    # _foundation (underscore-prefixed shared base) is a legitimate intra-hub base.
    assert foundation_iri in bases
    # -ext.ttl extension surfaces are not domain bases.
    assert "https://example.org/domain/party-ext" not in bases


def test_collect_hub_domain_bases_rejects_invalid_turtle(tmp_path):
    ontologies = tmp_path / "ontologies"
    ontologies.mkdir(parents=True)
    (ontologies / "_broken.ttl").write_text("@prefix broken: <unterminated", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid Turtle in hub ontology base"):
        _collect_hub_domain_bases(ontologies)


def test_foundation_import_not_flagged_or_stripped(tmp_path):
    """Regression for issue #190 item 1: an intra-hub ``_foundation`` import must
    not be reported as an ``extra owl:imports`` nor stripped during sync."""
    model = tmp_path / "model"
    claims_dir = model / "claims"
    ontologies = model / "ontologies"
    _write_registry(claims_dir)
    _write_domain_files(model, with_drift=False)
    foundation_iri = _write_foundation(ontologies)

    # party.ttl imports BOTH the external ref base (expected) and _foundation (intra-hub).
    ontology = f"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dom: <https://example.org/domain/party#> .

<https://example.org/domain/party> a owl:Ontology ;
    rdfs:label "Party"@en ;
    owl:imports <{foundation_iri}> .

dom:Party a owl:Class ;
    rdfs:label "Party"@en ;
    rdfs:comment "Party entity."@en .

# >>> kairos-managed (generated from the Claim Registry — do not edit)
<https://example.org/domain/party> <http://www.w3.org/2002/07/owl#imports> <https://example.org/ref/party> .
# <<< kairos-managed
"""
    (ontologies / "party.ttl").write_text(ontology, encoding="utf-8")

    report = evaluate_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=ontologies,
        extensions_dir=model / "extensions",
    )
    domain = report.domains[0]
    assert domain.extra_imports == []
    assert domain.in_sync, (
        f"unexpected drift: extra={domain.extra_imports} missing={domain.missing_imports}"
    )

    # apply must preserve the intra-hub foundation import.
    apply_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=ontologies,
        extensions_dir=model / "extensions",
    )
    onto_graph = Graph()
    onto_graph.parse(ontologies / "party.ttl", format="turtle")
    onto_subj = next(onto_graph.subjects(RDF.type, OWL.Ontology))
    imports = {str(o).rstrip("#/") for o in onto_graph.objects(onto_subj, OWL.imports)}
    assert foundation_iri in imports
    assert "https://example.org/ref/party" in imports


def test_scaffold_missing_surfaces_creates_valid_skeletons(tmp_path):
    """Regression for issue #190 item 5: a fresh domain with no ontology/ext files
    is bootstrapped instead of silently skipped."""
    model = tmp_path / "model"
    claims_dir = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    _write_registry(claims_dir)
    # Provide a foundation base so the skeleton infers the hub namespace + import.
    _write_foundation(ontologies)

    result = scaffold_missing_surfaces(
        claims_dir=claims_dir,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
    )
    onto_file = ontologies / "party.ttl"
    ext_file = extensions / "party-silver-ext.ttl"
    assert onto_file in result.created
    assert ext_file in result.created
    assert result.updated == ()
    assert result.errors == ()
    assert result.counts == {"created": 2, "updated": 0, "unchanged": 0}

    # Skeletons are valid TTL with an owl:Ontology subject + provenance header.
    onto_graph = Graph()
    onto_graph.parse(onto_file, format="turtle")
    onto_subj = next(onto_graph.subjects(RDF.type, OWL.Ontology))
    assert str(onto_subj) == "https://example.org/domain/party"
    assert "skeleton scaffolded" in onto_file.read_text(encoding="utf-8").lower()
    # Inferred hub base → imports the foundation shared base.
    imports = {str(o).rstrip("#/") for o in onto_graph.objects(onto_subj, OWL.imports)}
    assert "https://example.org/domain/_foundation" in imports

    # Same baseline metadata checks required of hand-authored ontologies.
    assert onto_graph.value(onto_subj, RDFS.label) is not None
    assert onto_graph.value(onto_subj, RDFS.comment) is not None
    assert onto_graph.value(onto_subj, OWL.versionInfo) is not None

    ext_graph = Graph()
    ext_graph.parse(ext_file, format="turtle")
    ext_subj = next(ext_graph.subjects(RDF.type, OWL.Ontology))
    assert ext_graph.value(ext_subj, RDFS.label) is not None
    assert ext_graph.value(ext_subj, RDFS.comment) is not None
    assert ext_graph.value(ext_subj, OWL.versionInfo) is not None


def test_scaffold_does_not_touch_existing_files(tmp_path):
    model = tmp_path / "model"
    claims_dir = model / "claims"
    _write_registry(claims_dir)
    _write_domain_files(model, with_drift=False)
    before = (model / "ontologies" / "party.ttl").read_text(encoding="utf-8")

    result = scaffold_missing_surfaces(
        claims_dir=claims_dir,
        ontologies_dir=model / "ontologies",
        extensions_dir=model / "extensions",
    )
    assert result.created == ()
    assert (model / "ontologies" / "party.ttl") in result.unchanged
    assert (model / "extensions" / "party-silver-ext.ttl") in result.unchanged
    assert (model / "ontologies" / "party.ttl").read_text(encoding="utf-8") == before


def test_scaffold_is_idempotent_across_repeated_runs(tmp_path):
    """Re-running the scaffold over its own output is a no-op: same set of files,
    zero further writes, second run reports everything as unchanged."""
    model = tmp_path / "model"
    claims_dir = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    _write_registry(claims_dir)
    _write_foundation(ontologies)

    first = scaffold_missing_surfaces(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )
    onto_file = ontologies / "party.ttl"
    ext_file = extensions / "party-silver-ext.ttl"
    onto_before = onto_file.read_text(encoding="utf-8")
    ext_before = ext_file.read_text(encoding="utf-8")

    second = scaffold_missing_surfaces(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )
    assert second.created == ()
    assert onto_file in second.unchanged
    assert ext_file in second.unchanged
    assert onto_file.read_text(encoding="utf-8") == onto_before
    assert ext_file.read_text(encoding="utf-8") == ext_before
    assert first.counts == {"created": 2, "updated": 0, "unchanged": 0}


def test_scaffold_rejects_invalid_domain_slug_without_touching_others(tmp_path):
    """Partial failure: an invalid domain identifier is reported precisely and
    does not prevent sibling domains from being scaffolded, nor is anything
    already written for them rolled back."""
    model = tmp_path / "model"
    claims_dir = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    _write_registry(claims_dir)  # domain "party" — valid
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / "Bad_Domain-claims.yaml").write_text(
        "domain: Bad_Domain\ngenerated_at: '2026-06-15T00:00:00Z'\n"
        "algorithm_version: 1\nfreshness: {}\ncoverage: []\nclaims: []\n",
        encoding="utf-8",
    )
    _write_foundation(ontologies)

    with pytest.raises(ScaffoldPartialFailureError) as excinfo:
        scaffold_missing_surfaces(
            claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
        )
    result = excinfo.value.result
    assert (ontologies / "party.ttl") in result.created
    assert (extensions / "party-silver-ext.ttl") in result.created
    assert len(result.errors) == 1
    assert "Bad_Domain" in result.errors[0]
    assert not (ontologies / "Bad_Domain.ttl").exists()
    # No rollback: the sibling domain's files remain on disk despite the failure.
    assert (ontologies / "party.ttl").exists()
    assert (extensions / "party-silver-ext.ttl").exists()


def test_scaffold_registers_domain_in_master_and_readme(tmp_path):
    """Convergent update: an existing ``_master.ttl`` gains a managed owl:imports
    entry, and an existing README domain table gains a row — both preserving
    authored content outside the region this workflow owns."""
    model = tmp_path / "model"
    claims_dir = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    _write_registry(claims_dir)
    _write_foundation(ontologies)

    master_iri = "https://example.org/domain/master"
    master_text = (
        "# Hand-authored provenance header — KEEP THIS.\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
        f"<{master_iri}> a owl:Ontology ;\n"
        '    rdfs:label "Master"@en ;\n'
        '    owl:versionInfo "0.1.0" .\n'
    )
    master_file = ontologies / "_master.ttl"
    master_file.write_text(master_text, encoding="utf-8")

    readme_text = (
        "# Acme — Ontology Hub\n\n"
        "## Domain model overview\n\n"
        "| Domain | Description | File | Status |\n"
        "|--------|-------------|------|--------|\n"
        "| *(add domains here)* | | | |\n\n"
        "## Master ontology\n\n"
        "Keep it updated.\n"
    )
    readme_file = tmp_path / "README.md"
    readme_file.write_text(readme_text, encoding="utf-8")

    result = scaffold_missing_surfaces(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )
    assert master_file in result.updated
    assert readme_file in result.updated

    master_graph = Graph()
    master_graph.parse(master_file, format="turtle")
    imports = {str(o) for o in master_graph.objects(URIRef(master_iri), OWL.imports)}
    assert "https://example.org/domain/party" in imports
    # Authored header/content survives byte-for-byte outside the managed block.
    assert master_text.splitlines()[0] in master_file.read_text(encoding="utf-8")

    readme_after = readme_file.read_text(encoding="utf-8")
    assert "| party | | `model/ontologies/party.ttl` | Scaffolded |" in readme_after
    assert "*(add domains here)*" not in readme_after
    assert "Keep it updated." in readme_after  # untouched authored content survives

    # Idempotent: re-running with the files now in place changes nothing further.
    again = scaffold_missing_surfaces(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )
    assert master_file in again.unchanged
    assert readme_file in again.unchanged
    assert master_file.read_text(encoding="utf-8") == master_file.read_text(encoding="utf-8")


def test_scaffold_skips_master_registration_when_absent(tmp_path):
    """No ``_master.ttl`` yet: this workflow never creates one — it only converges
    an existing registration. Nothing is written, and no warning is raised for
    what is a perfectly normal state (a hub that doesn't use a master ontology
    yet, or hasn't created it)."""
    model = tmp_path / "model"
    claims_dir = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    _write_registry(claims_dir)
    _write_foundation(ontologies)

    result = scaffold_missing_surfaces(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )
    assert not (ontologies / "_master.ttl").exists()
    assert (ontologies / "_master.ttl") not in result.updated
    assert (ontologies / "_master.ttl") not in result.unchanged


def test_scaffold_metadata_error_message_names_missing_predicates():
    """Direct unit check of the metadata gate: a candidate graph missing required
    ontology-level metadata is rejected before anything would be written."""
    from kairos_ontology.core.claim_projection_sync import _validate_generated_metadata

    graph = Graph()
    subj = URIRef("https://example.org/domain/incomplete")
    graph.add((subj, RDF.type, OWL.Ontology))
    with pytest.raises(ScaffoldMetadataError, match="rdfs:label"):
        _validate_generated_metadata(graph, subj, path=Path("incomplete.ttl"))


def test_apply_bootstraps_then_syncs_fresh_domain(tmp_path):
    """End-to-end: apply on a fresh domain scaffolds skeletons then reaches sync."""
    model = tmp_path / "model"
    claims_dir = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    _write_registry(claims_dir)
    _write_foundation(ontologies)

    report = apply_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
    )
    assert not report.is_blocking, [
        (d.domain, d.error, d.missing_imports) for d in report.out_of_sync
    ]
    assert report.scaffold_result is not None
    assert (ontologies / "party.ttl") in report.scaffold_result.created
    # The approved imported TradeParty claim drove the external import into the skeleton.
    onto_graph = Graph()
    onto_graph.parse(ontologies / "party.ttl", format="turtle")
    onto_subj = next(onto_graph.subjects(RDF.type, OWL.Ontology))
    imports = {str(o).rstrip("#/") for o in onto_graph.objects(onto_subj, OWL.imports)}
    assert "https://example.org/ref/party" in imports


def test_cli_claims_to_silver_ext_prints_scaffold_summary_with_git_hint(tmp_path):
    """The CLI surfaces the explicit created/updated/unchanged accounting, the
    managed-vs-authored explanation, and a git-status hint for new files."""
    model = tmp_path / "model"
    claims_dir = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    _write_registry(claims_dir)
    _write_foundation(ontologies)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "claims-to-silver-ext",
            "--claims-dir",
            str(claims_dir),
            "--ontologies",
            str(ontologies),
            "--extensions",
            str(extensions),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Scaffold / convergence summary" in result.output
    assert "Scaffold summary: " in result.output
    assert "created" in result.output and "unchanged" in result.output
    assert str(ontologies / "party.ttl") in result.output
    assert "untracked in git" in result.output
    assert "git status" in result.output
    assert "Managed regions" in result.output

    # Re-running once everything exists reports unchanged, not created.
    again = runner.invoke(
        cli,
        [
            "claims-to-silver-ext",
            "--claims-dir",
            str(claims_dir),
            "--ontologies",
            str(ontologies),
            "--extensions",
            str(extensions),
        ],
    )
    assert again.exit_code == 0, again.output
    assert "0 created" in again.output


def test_cli_claims_to_silver_ext_reports_partial_failure_without_rollback(tmp_path):
    """CLI-level partial failure: an invalid domain identifier is reported with
    exit code 1 and an explicit no-rollback statement, while the sibling
    domain's already-written files remain on disk."""
    model = tmp_path / "model"
    claims_dir = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    _write_registry(claims_dir)  # domain "party" — valid
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / "Bad_Domain-claims.yaml").write_text(
        "domain: Bad_Domain\ngenerated_at: '2026-06-15T00:00:00Z'\n"
        "algorithm_version: 1\nfreshness: {}\ncoverage: []\nclaims: []\n",
        encoding="utf-8",
    )
    _write_foundation(ontologies)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "claims-to-silver-ext",
            "--claims-dir",
            str(claims_dir),
            "--ontologies",
            str(ontologies),
            "--extensions",
            str(extensions),
        ],
    )
    assert result.exit_code == 1
    assert "Scaffolding failed partway through" in result.output
    assert "No rollback is performed" in result.output
    assert "Bad_Domain" in result.output
    # The sibling domain's files remain — no rollback happened.
    assert (ontologies / "party.ttl").exists()
    assert (extensions / "party-silver-ext.ttl").exists()



# ---------------------------------------------------------------------------
# Issue #191 — managed-block writer preserves authored TTL
# ---------------------------------------------------------------------------

_AUTHORED_ONTOLOGY = """\
# ===========================================================================
# Party domain ontology — AUTHORED provenance header (DD-072). KEEP THIS.
# ===========================================================================
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dom: <https://example.org/domain/party#> .

<https://example.org/domain/party> a owl:Ontology ;
    rdfs:label "Party"@en ;
    owl:imports <https://example.org/domain/_foundation> .

# A locally authored subclass with an explanatory comment that must survive.
dom:VipParty a owl:Class ;
    rdfs:subClassOf <https://example.org/ref/party#TradeParty> ;
    rdfs:label "VIP Party"@en .
"""

_AUTHORED_EXT = """\
# Authored silver extension — keep my comments!
@prefix dom: <https://example.org/domain/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

# Local class include — authored, must survive untouched.
dom:VipParty kairos-ext:silverInclude true .
"""


def _setup_authored(tmp_path):
    model = tmp_path / "model"
    claims_dir = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    ontologies.mkdir(parents=True, exist_ok=True)
    extensions.mkdir(parents=True, exist_ok=True)
    _write_registry(claims_dir)
    _write_foundation(ontologies)
    (ontologies / "party.ttl").write_text(_AUTHORED_ONTOLOGY, encoding="utf-8")
    (extensions / "party-silver-ext.ttl").write_text(_AUTHORED_EXT, encoding="utf-8")
    return claims_dir, ontologies, extensions


def test_managed_block_preserves_authored_content(tmp_path):
    """Issue #191: sync must not destroy header/comments/local triples."""
    claims_dir, ontologies, extensions = _setup_authored(tmp_path)

    report = apply_projection_sync(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )
    assert not report.is_blocking

    onto_text = (ontologies / "party.ttl").read_text(encoding="utf-8")
    ext_text = (extensions / "party-silver-ext.ttl").read_text(encoding="utf-8")

    # Authored provenance header + comments + local subclass survive verbatim.
    assert "AUTHORED provenance header (DD-072). KEEP THIS." in onto_text
    assert "A locally authored subclass with an explanatory comment" in onto_text
    assert "dom:VipParty a owl:Class ;" in onto_text
    assert "keep my comments!" in ext_text
    assert "dom:VipParty kairos-ext:silverInclude true ." in ext_text

    # Managed block was appended with the external import + imported-class include.
    assert "# >>> kairos-managed" in onto_text
    assert "<https://example.org/domain/party> <http://www.w3.org/2002/07/owl#imports> " \
        "<https://example.org/ref/party> ." in onto_text

    # Foundation (intra-hub) import stays in the authored region, not the block.
    authored_region = onto_text.split("# >>> kairos-managed")[0]
    assert "<https://example.org/domain/_foundation>" in authored_region

    # And the result is semantically in sync.
    report2 = evaluate_projection_sync(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )
    assert not report2.is_blocking


def test_managed_block_sync_is_idempotent(tmp_path):
    claims_dir, ontologies, extensions = _setup_authored(tmp_path)

    apply_projection_sync(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )
    onto_after_1 = (ontologies / "party.ttl").read_text(encoding="utf-8")
    ext_after_1 = (extensions / "party-silver-ext.ttl").read_text(encoding="utf-8")

    apply_projection_sync(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )
    onto_after_2 = (ontologies / "party.ttl").read_text(encoding="utf-8")
    ext_after_2 = (extensions / "party-silver-ext.ttl").read_text(encoding="utf-8")

    assert onto_after_1 == onto_after_2
    assert ext_after_1 == ext_after_2
    # Exactly one managed block (no marker accumulation).
    assert onto_after_2.count("# >>> kairos-managed") == 1


def test_managed_block_preserves_authored_content_after_block(tmp_path):
    claims_dir, ontologies, extensions = _setup_authored(tmp_path)
    apply_projection_sync(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )

    ontology_file = ontologies / "party.ttl"
    authored_suffix = (
        "\n# Authored after the managed block; keep this location and text.\n"
        "dom:LocalParty a owl:Class ;\n"
        '    rdfs:label "Local Party"@en .\n'
    )
    ontology_file.write_text(
        ontology_file.read_text(encoding="utf-8") + authored_suffix,
        encoding="utf-8",
    )
    before = ontology_file.read_text(encoding="utf-8")
    before_suffix = before[before.index(authored_suffix):]
    registry_file = registry_path(claims_dir, "party")
    registry = load_registry(registry_file)
    registry.claims.append(
        Claim(
            id="party-organisation",
            type="class",
            status="approved",
            disposition="claim",
            origin="imported",
            class_uri="https://example.org/ref/org#Organisation",
        )
    )
    write_registry(registry, registry_file)

    report = apply_projection_sync(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )

    assert not report.is_blocking
    after = ontology_file.read_text(encoding="utf-8")
    assert after[after.index(authored_suffix):] == before_suffix
    assert after.index("# <<< kairos-managed") < after.index(authored_suffix)
    assert "<https://example.org/ref/org>" in after
    assert after.count("# >>> kairos-managed") == 1


def test_sync_rejects_legacy_inline_imports_without_modifying_authored_ttl(tmp_path):
    """Legacy whole-graph output is migration-required, never auto-rewritten."""
    claims_dir, ontologies, extensions = _setup_authored(tmp_path)
    legacy = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dom: <https://example.org/domain/party#> .

<https://example.org/domain/party> a owl:Ontology ;
    rdfs:label "Party"@en ;
    owl:imports <https://example.org/domain/_foundation> ;
    owl:imports <https://example.org/ref/party> .

dom:VipParty a owl:Class ;
    rdfs:label "VIP Party"@en .
"""
    (ontologies / "party.ttl").write_text(legacy, encoding="utf-8")

    before = (ontologies / "party.ttl").read_text(encoding="utf-8")
    report = apply_projection_sync(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )
    assert report.is_blocking
    assert "migrate --hub" in (report.domains[0].error or "")
    assert (ontologies / "party.ttl").read_text(encoding="utf-8") == before


def test_sync_imported_helper_delegates_to_canonical_filter():
    """`claim_projection_sync` consumes the canonical imported-class filter (DD-096).

    The sync helper must be the canonical
    ``binding_analysis.approved_imported_class_uris`` set minus classes local to the
    importing domain — never a divergent reimplementation of the claim filter.
    """
    from kairos_ontology.core.binding_analysis import approved_imported_class_uris
    from kairos_ontology.core.claim_projection_sync import (
        _approved_imported_class_uris,
    )

    ontology_iri = "https://example.org/domain/party"
    external_a = "https://example.org/ref/party#TradeParty"
    external_b = "https://example.org/ref/org#Organisation"
    local = "https://example.org/domain/party#VipParty"
    registry = ClaimRegistry(
        domain="party",
        claims=[
            # Included: approved + imported + claim/specialize, external.
            Claim(id="a", type="class", status="approved", disposition="claim",
                  origin="imported", class_uri=external_a),
            Claim(id="b", type="class", status="approved", disposition="specialize",
                  origin="imported", class_uri=external_b),
            # Excluded by the sync-local rule (approved imported but local domain URI).
            Claim(id="c", type="class", status="approved", disposition="claim",
                  origin="imported", class_uri=local),
            # Excluded by the canonical filter: proposed / rejected / gap / authored.
            Claim(id="d", type="class", status="proposed", disposition="claim",
                  origin="imported", class_uri="https://example.org/ref/x#Proposed"),
            Claim(id="e", type="class", status="rejected", disposition="claim",
                  origin="imported", class_uri="https://example.org/ref/x#Rejected"),
            Claim(id="f", type="class", status="approved", disposition="gap",
                  origin="imported", class_uri="https://example.org/ref/x#Gap"),
            Claim(id="g", type="class", status="approved", disposition="claim",
                  origin="authored", class_uri="https://example.org/ref/x#Authored"),
        ],
    )

    sync_set = _approved_imported_class_uris(registry, ontology_iri)
    assert sync_set == {external_a, external_b}

    # Parity: the sync set is exactly the canonical set minus local-domain URIs.
    canonical = approved_imported_class_uris(registry)
    assert canonical == {external_a, external_b, local}
    assert sync_set == {u for u in canonical if not u.startswith(ontology_iri)}