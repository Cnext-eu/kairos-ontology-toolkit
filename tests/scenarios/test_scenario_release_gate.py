# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Release-gate scenario tests (DD-096 / DEC-1).

`project --strict` must block a release when an approved, materialization-eligible
claim has no bronze mapping (an *unbound target*). These tests build a minimal
synthetic hub with a single local, approved, unmapped class claim and assert:

* strict=False projects without error (today's behaviour, unbound class skipped);
* strict=True raises with the unbound class named;
* a fully-bound hub (no unbound eligible claims) passes strict.

The synthetic hub has no external ``owl:imports`` so the claim-projection sync gate
stays in-sync — isolating the release-gate behaviour under test.
"""

import textwrap

import pytest

from kairos_ontology.core.projector import ProjectionRunError, run_projections

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


def _build_hub(root, *, with_claims: bool):
    """Write a minimal grouped-layout hub under *root* and return the hub dir."""
    hub = root / "hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "model" / "extensions").mkdir(parents=True)
    (hub / "model" / "shapes").mkdir(parents=True)
    (hub / "output").mkdir(parents=True)
    (hub / "model" / "ontologies" / "widget.ttl").write_text(WIDGET_TTL, encoding="utf-8")
    (hub / "model" / "extensions" / "widget-silver-ext.ttl").write_text(
        WIDGET_SILVER_EXT_TTL, encoding="utf-8"
    )
    if with_claims:
        (hub / "model" / "claims").mkdir(parents=True)
        (hub / "model" / "claims" / "widget-claims.yaml").write_text(
            WIDGET_CLAIMS_YAML, encoding="utf-8"
        )
    return hub


def _project(hub, *, strict: bool):
    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "catalog-v001.xml",  # absent — graceful fallback
        output_path=hub / "output",
        target="dbt",
        strict=strict,
    )


def test_strict_gate_blocks_unbound_approved_claim(tmp_path):
    """strict=True fails when an approved eligible claim has no bronze mapping."""
    hub = _build_hub(tmp_path, with_claims=True)
    with pytest.raises(ProjectionRunError) as exc:
        _project(hub, strict=True)
    msg = str(exc.value)
    assert "Release gate" in msg
    assert "Widget" in msg


def test_non_strict_projects_unbound_claim_without_error(tmp_path):
    """Without --strict, an unbound approved claim is skipped, not fatal."""
    hub = _build_hub(tmp_path, with_claims=True)
    _project(hub, strict=False)  # must not raise


def test_strict_gate_passes_without_eligible_claims(tmp_path):
    """A hub with no claims registry has no unbound targets → strict passes."""
    hub = _build_hub(tmp_path, with_claims=False)
    _project(hub, strict=True)  # must not raise


def test_strict_gate_env_fallback(tmp_path, monkeypatch):
    """KAIROS_PROJECT_STRICT=1 enables the gate without the CLI flag."""
    hub = _build_hub(tmp_path, with_claims=True)
    monkeypatch.setenv("KAIROS_PROJECT_STRICT", "1")
    with pytest.raises(ProjectionRunError):
        _project(hub, strict=False)
