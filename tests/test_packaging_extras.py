# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Packaging parity tests for user-facing extras.

The user-facing extras (``azure``, ``foundry``, ``flatfile``, ``parquet``, ``otel``, ``langfuse``)
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
    / "src"
    / "kairos_ontology"
    / "scaffold"
    / "pyproject.toml.template"
)

USER_FACING_EXTRAS = ["azure", "foundry", "flatfile", "parquet", "otel", "langfuse"]


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


def test_scaffold_template_offers_every_user_facing_extra():
    """Every extra the toolkit ships must be selectable in a scaffolded hub.

    The extras are declared as *bare* requirements — no URL — so the single direct
    reference in ``[project.dependencies]`` stays the only place a hub records the
    toolkit version (issue #297).  The previous version of this test asserted only
    that ``kairos-ontology-toolkit[<extra>]`` appeared somewhere in the pin, which was
    true both with and without the per-extra URLs, and justified those URLs circularly
    ("so hubs exercise the extras pin-rewriter").  The URL shape is asserted in
    tests/test_scaffold_toolkit_pin.py; the rewriter's back-compat with legacy
    five-URL hubs is asserted in tests/test_cli_update_upgrade.py.
    """
    with SCAFFOLD_TEMPLATE.open("rb") as fh:
        data = tomllib.load(fh)
    optional = data["project"].get("optional-dependencies", {})
    for extra in USER_FACING_EXTRAS:
        assert extra in optional, f"scaffold pyproject.toml.template is missing the '{extra}' extra"
        assert optional[extra] == [f"kairos-ontology-toolkit[{extra}]"], (
            f"scaffold '{extra}' extra must be the bare requirement "
            f"kairos-ontology-toolkit[{extra}], got {optional[extra]}"
        )
