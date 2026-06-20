# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
from pathlib import Path

import yaml
import pytest
from click.testing import CliRunner
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF

from kairos_ontology.alignment_coverage import (
    ALIGNMENT_ALGORITHM_VERSION,
    compute_affinity_hash,
)
from kairos_ontology.claim_projection_sync import (
    _collect_hub_domain_bases,
    apply_projection_sync,
    evaluate_projection_sync,
    scaffold_missing_surfaces,
)
from kairos_ontology.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    EvidenceSource,
    Freshness,
    registry_path,
    write_registry,
)
from kairos_ontology.cli.main import cli
from kairos_ontology.projections.shared import KAIROS_EXT


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

<https://example.org/domain/party> kairos-ext:silverIncludeImports true .
"""
    else:
        ext = """@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix ref: <https://example.org/ref/party#> .

ref:TradeParty kairos-ext:silverInclude true .
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
    assert before.exit_code == 1, before.output
    assert "sync drift detected" in before.output

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
    owl:imports <{foundation_iri}> ;
    owl:imports <https://example.org/ref/party> .

dom:Party a owl:Class ;
    rdfs:label "Party"@en ;
    rdfs:comment "Party entity."@en .
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

    created = scaffold_missing_surfaces(
        claims_dir=claims_dir,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
    )
    onto_file = ontologies / "party.ttl"
    ext_file = extensions / "party-silver-ext.ttl"
    assert onto_file in created
    assert ext_file in created

    # Skeletons are valid TTL with an owl:Ontology subject + provenance header.
    onto_graph = Graph()
    onto_graph.parse(onto_file, format="turtle")
    onto_subj = next(onto_graph.subjects(RDF.type, OWL.Ontology))
    assert str(onto_subj) == "https://example.org/domain/party"
    assert "skeleton scaffolded" in onto_file.read_text(encoding="utf-8").lower()
    # Inferred hub base → imports the foundation shared base.
    imports = {str(o).rstrip("#/") for o in onto_graph.objects(onto_subj, OWL.imports)}
    assert "https://example.org/domain/_foundation" in imports


def test_scaffold_does_not_touch_existing_files(tmp_path):
    model = tmp_path / "model"
    claims_dir = model / "claims"
    _write_registry(claims_dir)
    _write_domain_files(model, with_drift=False)
    before = (model / "ontologies" / "party.ttl").read_text(encoding="utf-8")

    created = scaffold_missing_surfaces(
        claims_dir=claims_dir,
        ontologies_dir=model / "ontologies",
        extensions_dir=model / "extensions",
    )
    assert created == []
    assert (model / "ontologies" / "party.ttl").read_text(encoding="utf-8") == before


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
    # The approved imported TradeParty claim drove the external import into the skeleton.
    onto_graph = Graph()
    onto_graph.parse(ontologies / "party.ttl", format="turtle")
    onto_subj = next(onto_graph.subjects(RDF.type, OWL.Ontology))
    imports = {str(o).rstrip("#/") for o in onto_graph.objects(onto_subj, OWL.imports)}
    assert "https://example.org/ref/party" in imports


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


def test_managed_block_migrates_legacy_inline_imports(tmp_path):
    """A legacy file with an inline external import (no markers) is migrated:
    the managed import moves into the block, authored local triples are kept."""
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

    apply_projection_sync(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )
    onto_text = (ontologies / "party.ttl").read_text(encoding="utf-8")

    # The external import now lives only inside the managed block...
    authored_region, _, managed_region = onto_text.partition("# >>> kairos-managed")
    assert "<https://example.org/ref/party>" in managed_region
    assert "<https://example.org/ref/party>" not in authored_region
    # ...the foundation import stays authored, and the local class is retained.
    assert "<https://example.org/domain/_foundation>" in authored_region
    assert "VipParty" in onto_text

    report = evaluate_projection_sync(
        claims_dir=claims_dir, ontologies_dir=ontologies, extensions_dir=extensions
    )
    assert not report.is_blocking