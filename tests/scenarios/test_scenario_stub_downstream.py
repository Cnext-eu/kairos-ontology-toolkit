# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Downstream-over-stub scenario tests (DD-096 / DEC-2, plan item F1d).

Per DEC-2, gold / Power BI are still generated over a domain that contains an
aspirational Silver stub (the star schema stays stable); release-eligibility is
enforced separately by the `--strict` gate, not by suppressing gold. These tests
project *all* targets over a minimal hub whose only class is an approved-but-unbound
claim and assert:

* the typed zero-row Silver stub is written to disk when stubs are enabled;
* running every target over a stub dependency completes without error;
* with stubs *off* the stub file is absent (feature-off unchanged);
* the strict gate still blocks such a hub transitively (gold depends on the stub).
"""

from pathlib import Path

import pytest

from kairos_ontology.core.projector import ProjectionRunError, run_projections

from .test_scenario_release_gate import _build_hub

STUB_SQL = "models/silver/widget/widget.sql"


def _project_all(hub, *, emit_stubs: bool, strict: bool = False):
    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "catalog-v001.xml",  # absent — graceful fallback
        output_path=hub / "output",
        target="all",
        emit_aspirational_stubs=emit_stubs,
        strict=strict,
    )


def _find(hub, rel: str) -> Path | None:
    for p in (hub / "output").rglob("*"):
        if p.is_file() and p.as_posix().endswith(rel):
            return p
    return None


def test_all_targets_over_stub_dependency_succeeds(tmp_path):
    """target=all with stubs on completes and writes the Silver stub over which
    gold/Power BI are generated (DEC-2: downstream allowed over a stub)."""
    hub = _build_hub(tmp_path, with_claims=True)
    _project_all(hub, emit_stubs=True, strict=False)  # must not raise
    stub = _find(hub, STUB_SQL)
    assert stub is not None, "aspirational Silver stub was not written"
    assert "kairos_aspirational_stub" in stub.read_text(encoding="utf-8")


def test_all_targets_feature_off_writes_no_stub(tmp_path):
    """target=all with stubs off leaves the unbound class unmaterialized."""
    hub = _build_hub(tmp_path, with_claims=True)
    _project_all(hub, emit_stubs=False, strict=False)
    assert _find(hub, STUB_SQL) is None


def test_strict_gate_blocks_all_targets_over_stub(tmp_path):
    """The strict gate blocks release even when the unbound claim feeds gold/Power BI."""
    hub = _build_hub(tmp_path, with_claims=True)
    with pytest.raises(ProjectionRunError):
        _project_all(hub, emit_stubs=True, strict=True)
