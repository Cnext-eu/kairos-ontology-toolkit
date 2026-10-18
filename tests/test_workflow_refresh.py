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
    """A recorded generation that equals a current template would make refresh a no-op.

    Compared against *both* repo kinds' live templates. It used to check only the
    dataplatform one, so a hub generation was compared against a file it could never
    equal -- which made the assertion vacuous for exactly the generations that then
    went missing.
    """
    assert _SUPERSEDED_WORKFLOW_TEMPLATES, "no superseded generations registered"
    for destination, names in _SUPERSEDED_WORKFLOW_TEMPLATES.items():
        loaded = _superseded_workflow_templates(destination)
        assert len(loaded) == len(names), f"missing superseded template file(s) for {destination}"
        live = [
            (_SCAFFOLD_DIR / sources[destination]).read_text(encoding="utf-8")
            for sources in (_HUB_WORKFLOW_SOURCES, _DATAPLATFORM_WORKFLOW_SOURCES)
            if destination in sources
        ]
        assert live, f"no live template for {destination}"
        for previous in loaded:
            for current in live:
                assert previous != current, destination


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


#: SHA-256 of every live workflow template. This is a deliberate tripwire, not a
#: content assertion: editing a workflow template obliges you to record the outgoing
#: bytes as a superseded generation (see the MAINTENANCE note on
#: ``_SUPERSEDED_WORKFLOW_TEMPLATES``), and nothing else enforced that. Commit 4d26224
#: changed ``pr-validate.yml`` without recording its predecessor, which left every
#: already-scaffolded hub reporting "customized" and unable to auto-refresh -- and the
#: suite stayed green, because the only check compared hub generations against the
#: *dataplatform* template, which they can never equal.
_LIVE_WORKFLOW_TEMPLATE_DIGESTS: dict[str, str] = {
    "github-workflows/managed-check.yml":
        "664f3c795c777926b85e4105e871e302ed5ee5fc5d3e848eda3076ec244c7ee3",
    "github-workflows/pr-validate.yml":
        "40db5f1df542e1d89d58ec9f6fb226902611e0b515767250ea95c2a472041cc4",
    "github-workflows/full-validate.yml":
        "64fa0918bd8d7b779d564ebe6931d2e4f9dca5c1610da38904f589c5b673b688",
    "github-workflows/release-projections.yml":
        "ebc4fc14155ef567a6c18ea1d72d9a15de3ef70da0107efd97d25de58b8a3263",
    "github-workflows/assign-copilot.yml":
        "06e75b76b56fe7d8444c2e0d1555b3e23c752791f3f42338c41b36b23ed63938",
    "github-workflows/copilot-setup-steps.yml":
        "ae22f6ee6d9946c17ac2daf2ad7af35100e0341ea4de82aece117db72fec9c48",
    "dataplatform/.github/workflows/pr-validate.yml.template":
        "a9fdc19b294f4c3709b1c36de0e2b899356cfa9c2b86b434b6a0845f0406709e",
    "dataplatform/.github/workflows/promote.yml.template":
        "708d7dd2cb855bb6fafebd5d4f487b9b0408de2ab48ac107c3c1ab546eb59673",
    "dataplatform/.github/workflows/deploy-powerbi-semantic-model.yml.template":
        "bf9f901d98265b4f169360a0a8287e0df4eb0fb21a67ab1e6c6cfd15bdb7f3e0",
    "dataplatform/fabric/KairosModelBpa.Notebook/notebook-content.py.template":
        "3f4397ed56eafa311ec5c6f9f887e5a02dd9cbec078013e13c6bed3344b3849d",
    "dataplatform/fabric/KairosModelBpa.Notebook/.platform.template":
        "696c070e628a7d7a2435e54fe1abf384f1efb293124ad3e2b0112112cf368144",
}


def test_live_workflow_templates_match_their_recorded_digests():
    """Changing a workflow template must be a deliberate, two-part act.

    If this fails you edited a template. That is fine -- but before updating the digest
    below, copy the *previous* bytes of that file to
    ``scaffold/superseded-workflows/<slug>/<n>.template`` and add it to
    ``_SUPERSEDED_WORKFLOW_TEMPLATES`` in ``cli/shared.py``. Skip that and every repo
    already holding the old generation classifies as "customized" and silently stops
    receiving template fixes, which is the failure this tripwire exists to prevent.
    """
    import hashlib

    tracked = set(_HUB_WORKFLOW_SOURCES.values()) | set(_DATAPLATFORM_WORKFLOW_SOURCES.values())
    assert set(_LIVE_WORKFLOW_TEMPLATE_DIGESTS) == tracked, (
        "the digest table and the managed-workflow source maps have drifted; add or "
        "remove the entry for the workflow you just registered"
    )
    for relative, expected in sorted(_LIVE_WORKFLOW_TEMPLATE_DIGESTS.items()):
        path = _SCAFFOLD_DIR / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, (
            f"{relative} changed. Record the outgoing generation under "
            f"scaffold/superseded-workflows/, register it in "
            f"_SUPERSEDED_WORKFLOW_TEMPLATES, then set this digest to {actual}."
        )


def test_recorded_hub_generations_are_refreshable(tmp_path):
    """Every recorded hub generation must classify as refreshable, not customized.

    Generation 2 predates the ERD relocation (its drift gate still diffed
    ``ontology-hub-publish/powerbi``); generation 3 is the single-job shape, before
    validation and compile were split; generation 4 predates #721/#771, before
    ``KAIROS_SKILL_CONTEXT`` moved to workflow level and every ``uv run`` gained
    ``--no-sync``. A hub sitting on any of them must be offered the upgrade
    automatically rather than reported as locally customized -- that is the whole
    point of recording the outgoing bytes.

    The count is asserted so that adding a generation without recording it here fails
    loudly; bump it when you record a new one.
    """
    destination = ".github/workflows/pr-validate.yml"
    current = (_SCAFFOLD_DIR / _HUB_WORKFLOW_SOURCES[destination]).read_text(encoding="utf-8")
    superseded = _superseded_workflow_templates(destination)

    hub_generations = [
        text
        for name, text in zip(_SUPERSEDED_WORKFLOW_TEMPLATES[destination], superseded)
        if name.startswith("hub-pr-validate/")
    ]
    assert len(hub_generations) == 9, "expected nine recorded hub generations"

    for generation in hub_generations[1:]:
        scaffolded = tmp_path / "pr-validate.yml"
        scaffolded.write_text(generation, encoding="utf-8")
        status = classify(scaffolded, current, superseded)
        assert status.state == "outdated"
        assert status.refreshable


def test_every_changed_workflow_records_its_outgoing_generation(tmp_path):
    """A hub on the previous generation of *any* managed workflow stays refreshable.

    #771/#773 changed four hub workflows at once, and only `pr-validate.yml` had a
    recorded history before that. Without an entry per workflow, a hub holding the
    shipped bytes of `full-validate.yml`, `managed-check.yml` or
    `release-projections.yml` would classify as "customized" and silently stop
    receiving template fixes -- the exact failure the ledger exists to prevent, and the
    one #772 is about.
    """
    for destination in (
        ".github/workflows/pr-validate.yml",
        ".github/workflows/full-validate.yml",
        ".github/workflows/managed-check.yml",
        ".github/workflows/release-projections.yml",
        ".github/workflows/copilot-setup-steps.yml",
    ):
        current = (
            _SCAFFOLD_DIR / _HUB_WORKFLOW_SOURCES[destination]
        ).read_text(encoding="utf-8")
        superseded = _superseded_workflow_templates(destination)
        assert superseded, f"{destination} has no recorded outgoing generation"

        scaffolded = tmp_path / "workflow.yml"
        scaffolded.write_text(superseded[-1], encoding="utf-8")
        status = classify(scaffolded, current, superseded)
        assert status.state == "outdated", f"{destination}: {status.state}"
        assert status.refreshable, destination


@pytest.mark.parametrize(
    "destination",
    [".github/workflows/pr-validate.yml", ".github/workflows/deploy-powerbi-semantic-model.yml"],
)
def test_a_dataplatform_on_the_tag_ref_generation_is_refreshed_to_sha_pins(tmp_path, destination):
    """#1124: a dataplatform holding the rendered pre-pinning workflow gets the pinned one.

    Rendered with this repo's own substitutions, the refresh must keep them and replace
    every tag ref -- otherwise the scanner finding the pinning fixes would stay in every
    dataplatform scaffolded before it.
    """
    import re

    current = (_SCAFFOLD_DIR / _DATAPLATFORM_WORKFLOW_SOURCES[destination]).read_text(
        encoding="utf-8"
    )
    superseded = _superseded_workflow_templates(destination)
    previous = next(t for t in reversed(superseded) if "astral-sh/setup-uv@v10.0.1" in t)
    names = set(re.findall(r"(?<!\$)\{([A-Z_][A-Z0-9_]*)\}", previous))
    subs = {name: f"acme-{name.lower().replace('_', '-')}" for name in names}

    scaffolded = tmp_path / "workflow.yml"
    scaffolded.write_text(render(previous, subs), encoding="utf-8")
    status = classify(scaffolded, current, superseded)
    assert status.state == "outdated", status.state
    assert status.refreshable

    refreshed = render(current, status.substitutions or {})
    assert "setup-uv@v10.0.1" not in refreshed
    assert "astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d # v10.0.1" in refreshed
    for value in subs.values():
        if value in scaffolded.read_text(encoding="utf-8"):
            assert value in refreshed, value
