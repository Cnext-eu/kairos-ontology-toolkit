# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Packaging parity tests for user-facing extras.

The four user-facing extras (``azure``, ``foundry``, ``flatfile``, ``parquet``)
are declared twice on purpose:

* ``[project.optional-dependencies]`` — what ships in the wheel metadata, so the
  documented ``pip install kairos-ontology-toolkit[<extra>]`` actually works.
* ``[dependency-groups]`` — for ``uv sync --group <extra>`` workflows.

These must stay in sync (same pins). This test guards against drift, which has
previously caused silent no-op installs (the extras existed only as
dependency-groups and ``pip install ...[extra]`` resolved nothing).
"""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
SCAFFOLD_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "src" / "kairos_ontology" / "scaffold" / "pyproject.toml.template"
)

USER_FACING_EXTRAS = ["azure", "foundry", "flatfile", "parquet"]


def _load_pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def test_optional_dependencies_declares_user_facing_extras():
    data = _load_pyproject()
    optional = data["project"].get("optional-dependencies", {})
    for extra in USER_FACING_EXTRAS:
        assert extra in optional, (
            f"[project.optional-dependencies] is missing '{extra}'; "
            f"`pip install kairos-ontology-toolkit[{extra}]` would resolve nothing"
        )


def test_extras_mirror_dependency_groups():
    data = _load_pyproject()
    optional = data["project"].get("optional-dependencies", {})
    groups = data.get("dependency-groups", {})
    for extra in USER_FACING_EXTRAS:
        assert extra in groups, f"[dependency-groups] is missing '{extra}'"
        assert sorted(optional[extra]) == sorted(groups[extra]), (
            f"extra '{extra}' differs between [project.optional-dependencies] and "
            f"[dependency-groups]: {optional[extra]} != {groups[extra]}"
        )


def test_dev_group_is_not_an_optional_dependency():
    """`dev` is a developer-only group and must not leak into wheel extras."""
    data = _load_pyproject()
    optional = data["project"].get("optional-dependencies", {})
    assert "dev" not in optional


def test_scaffold_template_declares_user_facing_extras():
    """The scaffold pyproject template must pin every user-facing extra so hubs
    scaffolded/upgraded via the toolkit exercise the extras pin-rewriter."""
    with SCAFFOLD_TEMPLATE.open("rb") as fh:
        data = tomllib.load(fh)
    optional = data["project"].get("optional-dependencies", {})
    for extra in USER_FACING_EXTRAS:
        assert extra in optional, (
            f"scaffold pyproject.toml.template is missing the '{extra}' extra pin"
        )
        pins = optional[extra]
        assert any(
            f"kairos-ontology-toolkit[{extra}]" in pin for pin in pins
        ), f"scaffold '{extra}' extra must pin kairos-ontology-toolkit[{extra}]"
