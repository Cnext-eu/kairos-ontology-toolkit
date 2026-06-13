# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for hub-root-aware path resolution in `validate` / `project` (DD-064).

Regression coverage for the cwd-relative default-path bug: running the commands
from inside ``ontology-hub/`` used to make Click hard-error on the ``--shapes``
default (validate) and nest projection output under
``ontology-hub/ontology-hub/output/`` (project).
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

import kairos_ontology.cli.main as cli_main
from kairos_ontology.cli.main import cli

VALID_TTL = """\
@prefix : <https://acme.com/ont/client#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://acme.com/ont/client> a owl:Ontology ;
    rdfs:label "Client"@en ;
    owl:versionInfo "0.1.0" .

:Client a owl:Class ;
    rdfs:label "Client"@en ;
    rdfs:comment "A client."@en .
"""


def _make_hub(root: Path, *, with_shapes: bool = True, with_catalog: bool = False) -> Path:
    """Create a minimal hub at ``root/ontology-hub`` and return the hub root."""
    hub = root / "ontology-hub"
    ont = hub / "model" / "ontologies"
    ont.mkdir(parents=True)
    (ont / "client.ttl").write_text(VALID_TTL, encoding="utf-8")
    if with_shapes:
        (hub / "model" / "shapes").mkdir(parents=True)
    if with_catalog:
        (hub / "catalog-v001.xml").write_text(
            '<?xml version="1.0"?><catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog"/>',
            encoding="utf-8",
        )
    return hub


def _patch_validation(monkeypatch):
    """Patch validation entry points; return a dict capturing their kwargs."""
    calls: dict[str, dict] = {}
    monkeypatch.setattr(cli_main, "run_validation", lambda **kw: calls.update(validation=kw))
    monkeypatch.setattr(cli_main, "run_gdpr_validation", lambda **kw: calls.update(gdpr=kw))
    return calls


def _patch_projections(monkeypatch):
    calls: dict[str, dict] = {}
    monkeypatch.setattr(cli_main, "run_projections", lambda **kw: calls.update(projection=kw))
    return calls


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #
def test_validate_from_repo_root(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    calls = _patch_validation(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["validate", "--syntax"])
    assert result.exit_code == 0, result.output
    assert calls["validation"]["ontologies_path"] == hub / "model" / "ontologies"
    assert calls["validation"]["shapes_path"] == hub / "model" / "shapes"


def test_validate_from_inside_hub(tmp_path, monkeypatch):
    """Previously exited 2 on the bad --shapes default; must now resolve cleanly."""
    hub = _make_hub(tmp_path)
    calls = _patch_validation(monkeypatch)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["validate", "--syntax"])
    assert result.exit_code == 0, result.output
    assert "does not exist" not in result.output
    assert calls["validation"]["ontologies_path"] == hub / "model" / "ontologies"
    assert calls["validation"]["shapes_path"] == hub / "model" / "shapes"


def test_validate_no_shapes_dir(tmp_path, monkeypatch):
    """A hub without a shapes/ dir must not trigger a Click exists error."""
    hub = _make_hub(tmp_path, with_shapes=False)
    calls = _patch_validation(monkeypatch)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["validate"])
    assert result.exit_code == 0, result.output
    assert "does not exist" not in result.output
    # shapes path still resolved (just non-existent) — run_validation guards it.
    assert calls["validation"]["shapes_path"] == hub / "model" / "shapes"


def test_validate_missing_ontologies_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no hub here
    result = CliRunner().invoke(cli, ["validate", "--syntax"])
    assert result.exit_code == 1
    assert "Cannot find ontologies directory" in result.output


def test_validate_explicit_paths_win(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    calls = _patch_validation(monkeypatch)
    other = tmp_path / "custom_ont"
    other.mkdir()
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["validate", "--syntax", "--ontologies", str(other)])
    assert result.exit_code == 0, result.output
    assert calls["validation"]["ontologies_path"] == other


# --------------------------------------------------------------------------- #
# project
# --------------------------------------------------------------------------- #
def test_project_from_inside_hub_no_nesting(tmp_path, monkeypatch):
    """Output must resolve to <hub>/output, never <hub>/ontology-hub/output."""
    hub = _make_hub(tmp_path)
    calls = _patch_projections(monkeypatch)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["project", "--target", "neo4j"])
    assert result.exit_code == 0, result.output
    assert calls["projection"]["output_path"] == hub / "output"
    assert calls["projection"]["output_path"] != hub / "ontology-hub" / "output"


def test_project_from_repo_root(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    calls = _patch_projections(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["project", "--target", "neo4j"])
    assert result.exit_code == 0, result.output
    assert calls["projection"]["output_path"] == hub / "output"


def test_project_catalog_autodetect_from_inside_hub(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path, with_catalog=True)
    calls = _patch_projections(monkeypatch)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["project", "--target", "neo4j"])
    assert result.exit_code == 0, result.output
    assert calls["projection"]["catalog_path"] == hub / "catalog-v001.xml"


def test_project_explicit_output_wins(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    calls = _patch_projections(monkeypatch)
    custom_out = tmp_path / "build"
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["project", "--target", "neo4j", "--output", str(custom_out)])
    assert result.exit_code == 0, result.output
    assert calls["projection"]["output_path"] == custom_out
