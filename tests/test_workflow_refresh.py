# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scaffolded ``.github/workflows/*.yml`` can receive template fixes (issue #658).

They were written once at scaffold time and never revisited, so a real fix landing in a
workflow template could not reach any repo that already existed -- and `update` reported
"all managed files up to date" while silently skipping every one of them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kairos_ontology.cli.shared import (
    _DATAPLATFORM_WORKFLOW_SOURCES,
    _HUB_WORKFLOW_SOURCES,
    _SCAFFOLD_DIR,
    _SUPERSEDED_WORKFLOW_TEMPLATES,
    _superseded_workflow_templates,
    _workflow_sources,
)
from kairos_ontology.cli.workflow_refresh import classify, recover_substitutions, render

_TEMPLATE = 'name: x\non: push\nenv:\n  HUB_ORG: "{ORG}"\n  HUB_REPO: "{HUB_REPO}"\n'


def test_recover_substitutions_round_trips():
    rendered = render(_TEMPLATE, {"ORG": "Cnext-eu", "HUB_REPO": "my-hub"})
    assert recover_substitutions(_TEMPLATE, rendered) == {
        "ORG": "Cnext-eu",
        "HUB_REPO": "my-hub",
    }


def test_recover_substitutions_rejects_any_real_edit():
    """The whole safety property: a modified file must never look refreshable."""
    rendered = render(_TEMPLATE, {"ORG": "Cnext-eu", "HUB_REPO": "my-hub"})
    assert recover_substitutions(_TEMPLATE, rendered + "  EXTRA: 1\n") is None
    assert (
        recover_substitutions(_TEMPLATE, rendered.replace("on: push", "on: pull_request")) is None
    )


def test_repeated_placeholder_must_resolve_consistently():
    template = 'a: "{ORG}"\nb: "{ORG}"\n'
    assert recover_substitutions(template, 'a: "x"\nb: "x"\n') == {"ORG": "x"}
    assert recover_substitutions(template, 'a: "x"\nb: "y"\n') is None


def test_classify_distinguishes_current_outdated_and_customized(tmp_path):
    superseded = _TEMPLATE.replace("on: push", "on: [push]")
    destination = tmp_path / "wf.yml"
    subs = {"ORG": "Cnext-eu", "HUB_REPO": "my-hub"}

    assert classify(destination, _TEMPLATE, (superseded,)).state == "missing"

    destination.write_text(render(_TEMPLATE, subs), encoding="utf-8")
    current = classify(destination, _TEMPLATE, (superseded,))
    assert current.state == "current"
    assert not current.refreshable

    destination.write_text(render(superseded, subs), encoding="utf-8")
    outdated = classify(destination, _TEMPLATE, (superseded,))
    assert outdated.state == "outdated"
    assert outdated.refreshable
    assert outdated.substitutions == subs

    destination.write_text(render(_TEMPLATE, subs) + "  # my own step\n", encoding="utf-8")
    customized = classify(destination, _TEMPLATE, (superseded,))
    assert customized.state == "customized"
    assert not customized.refreshable, "a customized workflow must never be auto-rewritten"


@pytest.mark.parametrize(
    "sources", (_HUB_WORKFLOW_SOURCES, _DATAPLATFORM_WORKFLOW_SOURCES), ids=("hub", "dataplatform")
)
def test_every_registered_workflow_source_exists(sources):
    for relative in sources.values():
        assert (_SCAFFOLD_DIR / relative).is_file(), relative


def test_workflow_sources_selects_by_repo_kind(tmp_path):
    hub = tmp_path / "hub"
    hub.mkdir()
    assert set(_workflow_sources(hub)) == set(_HUB_WORKFLOW_SOURCES)

    dataplatform = tmp_path / "dp"
    dataplatform.mkdir()
    (dataplatform / "dbt_project.yml").write_text("name: x\n", encoding="utf-8")
    assert set(_workflow_sources(dataplatform)) == set(_DATAPLATFORM_WORKFLOW_SOURCES)


def test_every_superseded_template_file_exists_and_differs_from_current():
    """A recorded generation that equals the current template would make refresh a no-op."""
    assert _SUPERSEDED_WORKFLOW_TEMPLATES, "no superseded generations registered"
    for destination, names in _SUPERSEDED_WORKFLOW_TEMPLATES.items():
        loaded = _superseded_workflow_templates(destination)
        assert len(loaded) == len(names), f"missing superseded template file(s) for {destination}"
        current = (_SCAFFOLD_DIR / _DATAPLATFORM_WORKFLOW_SOURCES[destination]).read_text(
            encoding="utf-8"
        )
        for previous in loaded:
            assert previous != current


def test_pre_guard_pr_validate_generation_is_refreshable(tmp_path):
    """The concrete case #658 was filed about, end to end.

    `pr-validate.yml.template` gained a guard against `local:` dbt package pins in #650.
    A dataplatform scaffolded before that had no way to receive it. An untouched copy of
    the old generation must now classify as refreshable, and re-rendering must carry the
    repo's own substitutions through while adding the guard.
    """
    destination = ".github/workflows/pr-validate.yml"
    current = (_SCAFFOLD_DIR / _DATAPLATFORM_WORKFLOW_SOURCES[destination]).read_text(
        encoding="utf-8"
    )
    superseded = _superseded_workflow_templates(destination)
    assert superseded, "the pre-guard generation is not registered"

    subs = {"DBT_CI_PROFILE_YAML": "        acme_dp:\n          target: ci"}
    scaffolded = tmp_path / "pr-validate.yml"
    scaffolded.write_text(render(superseded[0], subs), encoding="utf-8")

    status = classify(scaffolded, current, superseded)
    assert status.state == "outdated"
    assert status.refreshable

    refreshed = render(current, status.substitutions or {})
    assert "local:" in refreshed, "refresh did not deliver the guard"
    assert "local:" not in scaffolded.read_text(encoding="utf-8")
    # The repo's own rendered values -- here its dbt CI profile block -- survive.
    assert "acme_dp" in refreshed
    assert "{DBT_CI_PROFILE_YAML}" not in refreshed


def test_current_generations_are_never_registered_as_superseded():
    """A current template listed as superseded would make `update` rewrite a current file."""
    for destination, names in _SUPERSEDED_WORKFLOW_TEMPLATES.items():
        source = _DATAPLATFORM_WORKFLOW_SOURCES.get(destination) or _HUB_WORKFLOW_SOURCES.get(
            destination
        )
        current = (_SCAFFOLD_DIR / source).read_text(encoding="utf-8")
        for name in names:
            recorded = (_SCAFFOLD_DIR / "superseded-workflows" / name).read_text(encoding="utf-8")
            assert recorded != current, f"{name} is the current generation of {destination}"


def test_superseded_templates_ship_in_the_package():
    """They are read at runtime by `update`, so they must be inside the package tree."""
    root = _SCAFFOLD_DIR / "superseded-workflows"
    assert root.is_dir()
    assert Path(root).is_relative_to(_SCAFFOLD_DIR)
    assert list(root.rglob("*.template"))
