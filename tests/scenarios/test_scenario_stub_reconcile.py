# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Obsolete-output reconciliation scenario tests (DD-096 C3).

`run_projections` writes a projection manifest so a later run can delete dbt
artifacts it no longer produces. These tests project the *same* hub twice into the
same output tree and assert an aspirational Silver stub is removed on the second
run when:

* the ``emit_aspirational_stubs`` feature is turned off; or
* the underlying claim transitions ``approved`` → ``deferred`` (no longer
  materialization-eligible).

Only toolkit-recorded files are ever deleted (manifest-scoped), so hand-authored
files are never touched.
"""

from pathlib import Path

from kairos_ontology.core.projector import run_projections

from .test_scenario_release_gate import WIDGET_CLAIMS_YAML, _build_hub

STUB_SQL = "models/silver/widget/widget.sql"
DBT_ROOT = "output/medallion/dbt"


def _project(hub, *, emit_stubs: bool):
    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "catalog-v001.xml",
        output_path=hub / "output",
        target="dbt",
        emit_aspirational_stubs=emit_stubs,
    )


def _stub_path(hub) -> Path:
    return hub / DBT_ROOT / STUB_SQL


def _manifest_path(hub) -> Path:
    return hub / DBT_ROOT / ".kairos-projection-manifest.json"


def test_stub_removed_when_feature_disabled(tmp_path):
    """A stub written with the flag on is deleted on a later flag-off projection."""
    hub = _build_hub(tmp_path, with_claims=True)

    _project(hub, emit_stubs=True)
    assert _stub_path(hub).is_file(), "stub should be written with the feature on"
    assert _manifest_path(hub).is_file(), "projection manifest should be written"
    assert STUB_SQL in _manifest_path(hub).read_text(encoding="utf-8")

    _project(hub, emit_stubs=False)
    assert not _stub_path(hub).exists(), "stub should be reconciled away when flag off"
    assert STUB_SQL not in _manifest_path(hub).read_text(encoding="utf-8")


def test_stub_removed_when_claim_deferred(tmp_path):
    """approved → deferred drops eligibility, so the stub is reconciled away."""
    hub = _build_hub(tmp_path, with_claims=True)

    _project(hub, emit_stubs=True)
    assert _stub_path(hub).is_file()

    # Transition the claim out of the approved/eligible state.
    deferred = WIDGET_CLAIMS_YAML.replace("status: approved", "status: deferred")
    (hub / "model" / "claims" / "widget-claims.yaml").write_text(deferred, encoding="utf-8")

    _project(hub, emit_stubs=True)
    assert not _stub_path(hub).exists(), "deferred claim must not retain a stub"


def test_reconcile_is_idempotent(tmp_path):
    """Re-projecting an unchanged hub keeps real models and the manifest stable."""
    hub = _build_hub(tmp_path, with_claims=True)

    _project(hub, emit_stubs=True)
    manifest_first = _manifest_path(hub).read_text(encoding="utf-8")
    assert _stub_path(hub).is_file()

    _project(hub, emit_stubs=True)
    assert _stub_path(hub).is_file(), "stub must survive an identical re-projection"
    assert _manifest_path(hub).read_text(encoding="utf-8") == manifest_first
