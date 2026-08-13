# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Static meta-test for the CI workflow's reference-models checkout (issue #315).

``tests/test_refmodels_contract.py`` is a hard requirement in CI (see
``_fail_if_missing_in_ci`` there), which only works if
``.github/workflows/ci.yml`` actually checks out
``kairos-ontology-referencemodels`` and points ``KAIROS_REFMODELS_ROOT`` at it.

This test parses the workflow file itself with ``yaml.safe_load`` and asserts the
checkout step and env var are present and sane. It needs no network access and no
real checkout, so it runs unconditionally, everywhere — its whole point is to catch
someone removing or breaking the checkout step without touching this file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.test_refmodels_contract import _fail_if_missing_in_ci

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

_REFMODELS_REPO = "Cnext-eu/kairos-ontology-referencemodels"
_DISALLOWED_REFS = {"main", "master", "head"}


def _load_workflow() -> dict[str, Any]:
    with _CI_WORKFLOW.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _iter_job_envs(workflow: dict[str, Any]):
    """Yield every env mapping declared anywhere at job level."""
    jobs = workflow.get("jobs", {})
    for job in jobs.values():
        env = job.get("env")
        if env:
            yield env


def _iter_steps(workflow: dict[str, Any]):
    jobs = workflow.get("jobs", {})
    for job in jobs.values():
        for step in job.get("steps", []):
            yield step


def _find_refmodels_checkout_step(workflow: dict[str, Any]) -> dict[str, Any] | None:
    for step in _iter_steps(workflow):
        uses = step.get("uses", "")
        if not uses.startswith("actions/checkout@"):
            continue
        with_block = step.get("with", {}) or {}
        if with_block.get("repository") == _REFMODELS_REPO:
            return step
    return None


def test_ci_workflow_checks_out_refmodels_repo() -> None:
    workflow = _load_workflow()
    step = _find_refmodels_checkout_step(workflow)
    assert step is not None, (
        f"no actions/checkout step found in {_CI_WORKFLOW} with "
        f"with.repository == {_REFMODELS_REPO!r}"
    )


def test_ci_workflow_refmodels_ref_is_pinned() -> None:
    workflow = _load_workflow()
    step = _find_refmodels_checkout_step(workflow)
    assert step is not None

    with_block = step.get("with", {}) or {}
    ref = with_block.get("ref")

    # ``ref`` may be a literal value or an ``${{ env.FOO }}`` expression — either way
    # it must resolve to something concrete. Resolve simple ``env.NAME`` expressions
    # against the job/workflow env so a pin hidden behind a variable is still checked.
    resolved_ref = ref
    if isinstance(ref, str) and ref.strip().startswith("${{") and "env." in ref:
        var_name = ref.split("env.", 1)[1].split("}}", 1)[0].strip()
        for env in _iter_job_envs(workflow):
            if var_name in env:
                resolved_ref = env[var_name]
                break

    assert isinstance(resolved_ref, str) and resolved_ref.strip(), (
        f"with.ref for the {_REFMODELS_REPO} checkout step must be a non-empty string, "
        f"got {ref!r}"
    )
    assert resolved_ref.strip().lower() not in _DISALLOWED_REFS, (
        f"with.ref for the {_REFMODELS_REPO} checkout step resolves to "
        f"{resolved_ref!r} — it must be pinned to a specific tag/sha, not a floating "
        "branch. Bump the pin deliberately via its own PR instead."
    )


def test_ci_workflow_sets_kairos_refmodels_root_env() -> None:
    workflow = _load_workflow()
    assert any("KAIROS_REFMODELS_ROOT" in env for env in _iter_job_envs(workflow)), (
        f"expected KAIROS_REFMODELS_ROOT to be set at job level in {_CI_WORKFLOW}"
    )


# ---------------------------------------------------------------------------
# Unit tests for tests.test_refmodels_contract._fail_if_missing_in_ci (#315)
# ---------------------------------------------------------------------------
# Called directly with a hand-built environ so these run unconditionally, without
# depending on whether *this* machine has a real reference-models checkout.


def test_fail_if_missing_in_ci_raises_when_root_missing_in_ci() -> None:
    with pytest.raises(RuntimeError):
        _fail_if_missing_in_ci(None, {"CI": "true"})


def test_fail_if_missing_in_ci_is_silent_outside_ci() -> None:
    _fail_if_missing_in_ci(None, {})  # must not raise
