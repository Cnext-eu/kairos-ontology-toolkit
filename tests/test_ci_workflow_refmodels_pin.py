# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Static meta-test for the reference-models dev-dependency pin (issue #315).

``tests/test_refmodels_contract.py`` is a hard requirement in CI (see
``_fail_if_missing_in_ci`` there), which only works if ``kairos-ontology-referencemodels``
is installed as a dev dependency (pinned to a published release wheel in ``pyproject.toml``).

This test parses ``pyproject.toml`` with ``tomllib`` and asserts the pin is present and
sane. It needs no network access and no real checkout, so it runs unconditionally,
everywhere — its whole point is to catch someone removing or breaking the pin without
touching this file.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from tests.test_refmodels_contract import _fail_if_missing_in_ci

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

_REFMODELS_PACKAGE = "kairos-ontology-referencemodels"
_REFMODELS_RELEASE_URL_RE = re.compile(
    r"https://github\.com/Cnext-eu/kairos-ontology-referencemodels/releases/download/"
    r"(?P<tag>[^/\s\"']+)/kairos_ontology_referencemodels-[^/\s\"']+-py3-none-any\.whl"
)
_DISALLOWED_REFS = {"main", "master", "head"}


def _load_pyproject() -> dict:
    with _PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _dev_dependencies(data: dict) -> list[str]:
    """Return dev dependencies from either [dependency-groups] dev or
    [project.optional-dependencies.dev], whichever has entries.
    """
    # uv-style dependency-groups (preferred)
    groups = data.get("dependency-groups", {})
    if "dev" in groups:
        return [str(d) for d in groups["dev"]]
    # pip-style optional-dependencies (fallback)
    deps = (
        data.get("project", {})
        .get("optional-dependencies", {})
        .get("dev", [])
    )
    return [str(d) for d in deps]


def _uv_sources(data: dict) -> dict:
    """Return [tool.uv.sources] entries, if any."""
    return data.get("tool", {}).get("uv", {}).get("sources", {})


def test_pyproject_pins_refmodels_as_dev_dependency() -> None:
    data = _load_pyproject()
    deps = _dev_dependencies(data)
    refmodels_deps = [d for d in deps if _REFMODELS_PACKAGE in d]
    assert refmodels_deps, (
        f"no {_REFMODELS_PACKAGE!r} entry found in dev dependencies "
        f"in {_PYPROJECT}"
    )


def test_refmodels_pin_targets_a_release_wheel() -> None:
    """The referencemodels dev dependency must be pinned to a GitHub Release
    wheel URL, either inline (direct-URL specifier) or via [tool.uv.sources].

    A temporary [tool.uv.sources] git override is acceptable during the
    transition period (before the first wheel is published), but it must
    point to a specific branch, not a floating ref.
    """
    data = _load_pyproject()
    deps = _dev_dependencies(data)
    refmodels_deps = [d for d in deps if _REFMODELS_PACKAGE in d]
    assert refmodels_deps

    # Check for inline release-wheel URL first
    match = _REFMODELS_RELEASE_URL_RE.search(refmodels_deps[0])
    if match:
        return  # Inline pin — good

    # No inline URL — check [tool.uv.sources] for a wheel URL or git override
    sources = _uv_sources(data)
    assert _REFMODELS_PACKAGE in sources, (
        f"{_REFMODELS_PACKAGE!r} has no inline wheel URL and no [tool.uv.sources] entry "
        f"— it must be pinned to a specific release."
    )
    source_spec = sources[_REFMODELS_PACKAGE]
    if isinstance(source_spec, dict):
        # A direct-URL wheel pin is the preferred form (DD-158)
        if "url" in source_spec:
            assert _REFMODELS_RELEASE_URL_RE.search(
                source_spec["url"]
            ), f"[tool.uv.sources] url for {_REFMODELS_PACKAGE!r} must be a release wheel URL"
        # A git source override is acceptable temporarily (see DD-158)
        else:
            assert "git" in source_spec or "path" in source_spec, (
                f"[tool.uv.sources] for {_REFMODELS_PACKAGE!r} must specify url, git, or path"
            )


def test_refmodels_pin_is_not_a_floating_branch() -> None:
    """If pinned via a release wheel URL, the tag must not be a floating branch."""
    data = _load_pyproject()
    deps = _dev_dependencies(data)
    refmodels_deps = [d for d in deps if _REFMODELS_PACKAGE in d]
    assert refmodels_deps

    match = _REFMODELS_RELEASE_URL_RE.search(refmodels_deps[0])
    if not match:
        # Pin is via [tool.uv.sources] — skip this check (git override has its own constraints)
        return

    tag = match.group("tag").strip().lower()
    assert tag not in _DISALLOWED_REFS, (
        f"the {_REFMODELS_PACKAGE} pin resolves to {tag!r} — it must be pinned to a "
        "specific tag, not a floating branch."
    )


# ---------------------------------------------------------------------------
# Unit tests for tests.test_refmodels_contract._fail_if_missing_in_ci (#315)
# ---------------------------------------------------------------------------
# Called directly with a hand-built environ so these run unconditionally, without
# depending on whether *this* machine has reference models installed.


def test_fail_if_missing_in_ci_raises_when_root_missing_in_ci() -> None:
    with pytest.raises(RuntimeError):
        _fail_if_missing_in_ci(None, {"CI": "true"})


def test_fail_if_missing_in_ci_is_silent_outside_ci() -> None:
    _fail_if_missing_in_ci(None, {})  # must not raise
