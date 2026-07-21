# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Parity tests: one canonical BindingAnalysis drives every consumer (DD-096).

The canonical :func:`binding_analysis.build` result must agree — over the real
acme-hub ``client`` pipeline — with:

* the dbt projector's emitted aspirational **stub** set (``stubs_enabled=True``),
* the dbt projector's ``__unbound_eligible__`` **release-gate** set (independent of
  whether stubs are emitted), and
* the deterministic ``status`` scan's aspirational-stub reporting.

An unmapped, approved ``Prospect`` class is injected into a *fresh copy* of the
client graph (as in ``test_scenario_aspirational_stubs``) so we exercise the
aspirational path without mutating shared fixtures.
"""

from __future__ import annotations

from kairos_ontology.core import binding_analysis as ba
from kairos_ontology.core.projections.medallion_dbt_projector import (
    _parse_bronze,
    _parse_skos_mappings,
    generate_dbt_artifacts,
)

from .conftest import (
    EXTENSIONS_DIR,
    MAPPINGS_DIR,
    SHAPES_DIR,
    SOURCES_DIR,
    TEMPLATE_DIR,
)
from .test_scenario_aspirational_stubs import PROSPECT, _client_with_prospect


def _analysis(bundle, *, stubs_enabled: bool, eligible):
    graph, _namespace, classes = bundle
    systems = _parse_bronze(SOURCES_DIR)
    mappings, _ = _parse_skos_mappings(MAPPINGS_DIR)
    return ba.build(
        classes=classes,
        graph=graph,
        systems=systems,
        mappings=mappings,
        eligible_class_uris=eligible,
        stubs_enabled=stubs_enabled,
    )


def _project(bundle, *, emit_stubs: bool, eligible):
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


def _names_for(bundle, uris):
    _graph, _ns, classes = bundle
    by_uri = {c["uri"]: c["name"] for c in classes}
    return sorted(by_uri[u] for u in uris if u in by_uri)


def test_analysis_release_set_matches_projector_unbound_eligible():
    """release_blocking_class_uris parity with ``__unbound_eligible__`` — both flags."""
    for emit_stubs in (True, False):
        bundle = _client_with_prospect()
        analysis = _analysis(bundle, stubs_enabled=emit_stubs, eligible={PROSPECT})
        artifacts = _project(bundle, emit_stubs=emit_stubs, eligible={PROSPECT})

        expected_names = _names_for(bundle, analysis.release_blocking_class_uris())
        gate_names = sorted(artifacts.get("__unbound_eligible__", []))
        assert gate_names == expected_names == ["Prospect"]


def test_analysis_aspirational_matches_emitted_stub_models():
    """When stubs are emitted, the stub model set == analysis aspirational set."""
    bundle = _client_with_prospect()
    analysis = _analysis(bundle, stubs_enabled=True, eligible={PROSPECT})
    off = _project(_client_with_prospect(), emit_stubs=False, eligible={PROSPECT})
    on = _project(bundle, emit_stubs=True, eligible={PROSPECT})

    off_models = {k for k in off if "models/silver/" in k and k.endswith(".sql")}
    on_models = {k for k in on if "models/silver/" in k and k.endswith(".sql")}
    new_stub_models = on_models - off_models

    # Aspirational (Prospect) is the only class stubbed; real mapped classes stay bound.
    assert analysis.aspirational_class_uris() == [PROSPECT]
    assert analysis.is_aspirational(PROSPECT)
    assert new_stub_models == {"models/silver/client/prospect.sql"}


def test_analysis_mapped_classes_are_bound_not_aspirational():
    """Every real (mapped) client class is BOUND and never release-blocking."""
    bundle = _client_with_prospect()
    _graph, _ns, classes = bundle
    analysis = _analysis(bundle, stubs_enabled=True, eligible={PROSPECT})
    for cls in classes:
        if cls["uri"] == PROSPECT:
            continue
        # Mapped acme-hub client classes bind to bronze; folded subtypes may FOLD.
        assert analysis.state(cls["uri"]) in {ba.BOUND, ba.FOLDED}
        assert not analysis.is_aspirational(cls["uri"])
        assert not analysis.is_release_blocking(cls["uri"])


def test_release_facts_are_stub_flag_invariant():
    """The release-blocking set does not depend on whether stubs are emitted."""
    on = _analysis(_client_with_prospect(), stubs_enabled=True, eligible={PROSPECT})
    off = _analysis(_client_with_prospect(), stubs_enabled=False, eligible={PROSPECT})
    assert on.release_blocking_class_uris() == off.release_blocking_class_uris()
    assert on.aspirational_class_uris() == off.aspirational_class_uris()
    # Only *materialization* differs with the flag.
    assert on.is_materialized(PROSPECT) is True
    assert off.is_materialized(PROSPECT) is False
