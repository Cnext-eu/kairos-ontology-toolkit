# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for the target-first aspirational Silver stub → bind loop (DD-096).

These run the real acme-hub ``client`` projection pipeline (sources, SKOS mappings,
silver-ext, SHACL) through ``generate_dbt_artifacts`` and inject a synthetic,
**unmapped** approved class (``Prospect``) into a *fresh copy* of the client graph so
we can exercise stub emission without mutating the shared fixtures or the acme-hub
files (which would ripple into count-based scenario assertions).

Covers:
* **F1c backward-compat** — flag off, passing ``eligible_class_uris`` changes nothing.
* **F1 stub emission** — flag on, the unmapped eligible class emits a typed zero-row
  stub (``where 1 = 0`` + ``cast(null as ...)``, tagged ``kairos_aspirational_stub``)
  and a schema-yaml ``meta.is_aspirational`` marker.
* **binding wins** — the real mapped classes never turn into stubs.
"""

from __future__ import annotations

from rdflib import Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import OWL, XSD

from kairos_ontology.core.projections.medallion_dbt_projector import (
    generate_dbt_artifacts,
)

from .conftest import (
    EXTENSIONS_DIR,
    MAPPINGS_DIR,
    SHAPES_DIR,
    SOURCES_DIR,
    TEMPLATE_DIR,
    _load_ontology,
)

ACME = Namespace("https://acme.example/ontology/client#")
PROSPECT = str(ACME.Prospect)


def _client_with_prospect():
    """Fresh client (graph, namespace, classes) plus an unmapped ``Prospect`` class."""
    graph, namespace, classes = _load_ontology("client")
    prospect = URIRef(PROSPECT)
    graph.add((prospect, RDF.type, OWL.Class))
    graph.add((prospect, RDFS.label, Literal("Prospect")))
    graph.add((prospect, RDFS.comment, Literal("A potential client, not yet onboarded.")))
    # A datatype property so the stub has a non-structural typed column.
    lead = URIRef(ACME.leadSource)
    graph.add((lead, RDF.type, OWL.DatatypeProperty))
    graph.add((lead, RDFS.label, Literal("lead source")))
    graph.add((lead, RDFS.comment, Literal("Where the prospect originated.")))
    graph.add((lead, RDFS.domain, prospect))
    graph.add((lead, RDFS.range, XSD.string))
    classes = [*classes, {
        "uri": PROSPECT, "name": "Prospect", "label": "Prospect",
        "comment": "A potential client, not yet onboarded.",
    }]
    return graph, namespace, classes


def _project(bundle, *, emit_stubs=False, eligible=None):
    graph, namespace, classes = bundle
    gold_ext = EXTENSIONS_DIR / "client-gold-ext.ttl"
    silver_ext = EXTENSIONS_DIR / "client-silver-ext.ttl"
    return generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="client",
        bronze_dir=SOURCES_DIR,
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        gold_ext_path=gold_ext if gold_ext.exists() else None,
        silver_ext_path=silver_ext if silver_ext.exists() else None,
        emit_aspirational_stubs=emit_stubs,
        eligible_class_uris=eligible,
    )


def _silver_models(artifacts: dict) -> dict[str, str]:
    return {
        k: v
        for k, v in artifacts.items()
        if "models/silver/" in k and k.endswith(".sql")
    }


def _file_artifacts(artifacts: dict) -> dict:
    """Drop internal ``__...__`` analysis keys (coverage, release-gate) not written."""
    return {k: v for k, v in artifacts.items() if not k.startswith("__")}


def test_feature_off_ignores_eligibility():
    """Flag off: passing eligible_class_uris must not change any on-disk file."""
    baseline = _project(_client_with_prospect())
    with_eligible = _project(_client_with_prospect(), emit_stubs=False, eligible={PROSPECT})
    assert _file_artifacts(baseline) == _file_artifacts(with_eligible)
    # And no stub was produced for the unmapped class.
    assert "models/silver/client/prospect.sql" not in baseline


def test_feature_on_emits_stub_for_unmapped_eligible():
    """Flag on: the unmapped eligible class emits a typed zero-row stub model."""
    off = _silver_models(_project(_client_with_prospect()))
    on = _silver_models(
        _project(_client_with_prospect(), emit_stubs=True, eligible={PROSPECT})
    )
    new_models = set(on) - set(off)
    assert new_models == {"models/silver/client/prospect.sql"}
    stub = on["models/silver/client/prospect.sql"]
    assert "where 1 = 0" in stub
    assert "cast(null as" in stub
    assert "prospect_sk" in stub
    assert "prospect_iri" in stub
    assert "lead_source" in stub
    assert "kairos_aspirational_stub" in stub
    assert "'is_aspirational': true" in stub


def test_feature_on_schema_yaml_marks_stub():
    """The stub's schema YAML entry carries meta.is_aspirational."""
    artifacts = _project(
        _client_with_prospect(), emit_stubs=True, eligible={PROSPECT}
    )
    models_yml = [k for k in artifacts if k.endswith("_models.yml")]
    assert models_yml
    assert "is_aspirational" in artifacts[models_yml[0]]


def test_binding_wins_mapped_classes_never_stub():
    """Real mapped client classes never become stubs, even when marked eligible."""
    bundle = _client_with_prospect()
    _, _, classes = bundle
    all_uris = {c["uri"] for c in classes}
    off = _silver_models(_project(_client_with_prospect()))
    on = _silver_models(_project(bundle, emit_stubs=True, eligible=all_uris))
    for name, content in on.items():
        if name in off:  # previously-bound model
            assert "kairos_aspirational_stub" not in content


def test_coverage_data_stub_agnostic_with_real_sources():
    """D2: with real acme-hub sources, the coverage payload is identical on/off.

    Coverage is derived from classes + mappings, so emitting a stub for the unmapped
    Prospect class must not change any coverage number.
    """
    off = _project(_client_with_prospect())
    on = _project(_client_with_prospect(), emit_stubs=True, eligible={PROSPECT})
    assert off.get("__coverage_data__") == on.get("__coverage_data__")
