# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The dbt version contract is declared once and every surface agrees (#789).

The toolkit imposes constraints on the dbt stack it scaffolds into and emits for, and
none of them were written down: they existed only as pins copied into templates, and were
rediscovered by trial when a hub or a dataplatform broke. Two of them pointed in opposite
directions at once, so exactly one dbt-fabric release satisfied both, and the only way to
find it was bisecting releases.

The worst consequence was a contradiction that shipped: the v5 Silver path emits
generic-test config under the dbt 1.10+ ``arguments:`` key while the scaffold pinned
``dbt-core>=1.9,<1.10`` — so a freshly scaffolded hub could not parse the package the
toolkit emits for it.

These tests bind the declaration in ``core.adapters`` to every surface that repeats it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.adapters import (
    DBT_ADAPTER_PACKAGES,
    DBT_CORE_FLOOR,
    DBT_CORE_REQUIREMENT,
    DBT_PACKAGE_REQUIREMENTS,
    SUPPORTED_ADAPTER_IDS,
    dbt_adapter_requirement,
)

_SCAFFOLD = Path(__file__).resolve().parents[1] / "src" / "kairos_ontology" / "scaffold"
_TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "kairos_ontology" / "templates"


def _hub_pyproject() -> str:
    return (_SCAFFOLD / "pyproject.toml.template").read_text(encoding="utf-8")


def test_the_declared_floor_is_at_least_the_syntax_the_emitter_uses():
    """The floor is not cosmetic: below 1.10 the emitted package does not parse.

    ``_generic_test`` nests arguments under ``arguments:``, which dbt 1.9 rejects with
    "takes no keyword argument 'arguments'" — a message about the macro, not the version.
    """
    assert DBT_CORE_FLOOR.startswith(">=1.10"), DBT_CORE_FLOOR
    # The hub's installed range must sit inside the floor the emitter requires.
    assert DBT_CORE_REQUIREMENT.startswith(">=1.10"), DBT_CORE_REQUIREMENT
    assert "<" not in DBT_CORE_FLOOR, (
        "the emitted package must not inherit the hub's install-time ceiling"
    )


def test_the_hub_scaffold_pins_the_declared_core_requirement():
    pyproject = _hub_pyproject()
    expected = f'"dbt-core{DBT_CORE_REQUIREMENT}"'
    assert pyproject.count(expected) == 3, (
        f"expected {expected} in all three dbt-validate extras; the template and "
        "core.adapters have drifted"
    )
    assert "dbt-core>=1.9" not in pyproject


@pytest.mark.parametrize("adapter", sorted(SUPPORTED_ADAPTER_IDS))
def test_the_hub_scaffold_pins_each_declared_adapter(adapter):
    assert f'"{dbt_adapter_requirement(adapter)}"' in _hub_pyproject()


@pytest.mark.parametrize("adapter", sorted(SUPPORTED_ADAPTER_IDS))
def test_every_adapter_declares_a_requirement(adapter):
    """A new adapter must not silently inherit an unpinned dbt."""
    assert adapter in DBT_ADAPTER_PACKAGES
    requirement = dbt_adapter_requirement(adapter)
    assert requirement.startswith(DBT_ADAPTER_PACKAGES[adapter])
    assert any(op in requirement for op in ("==", ">=")), requirement


def test_the_emitted_package_declares_require_dbt_version():
    """A consumer on an incompatible dbt should learn that, not read a macro error."""
    template = (_TEMPLATES / "dbt" / "dbt_project.yml.jinja2").read_text(encoding="utf-8")
    assert "require-dbt-version" in template
    assert "{{ require_dbt_version }}" in template


def test_the_emitted_packages_yml_uses_the_declared_ranges():
    template = (_TEMPLATES / "dbt" / "packages.yml.jinja2").read_text(encoding="utf-8")
    # Rendered from the constants, so no literal version may remain in the template.
    assert "dbt_packages" in template
    for lower, upper in DBT_PACKAGE_REQUIREMENTS.values():
        assert lower not in template
        assert upper not in template


def test_the_rendered_package_config_round_trips(tmp_path):
    """Render both templates for real: a Jinja typo must not reach a hub."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(_TEMPLATES / "dbt")), keep_trailing_newline=True)
    project = yaml.safe_load(
        env.get_template("dbt_project.yml.jinja2").render(
            project_name="acme_project",
            domains=[{"name": "party"}],
            gold_domains=[],
            adapter="fabric-warehouse",
            require_dbt_version=DBT_CORE_FLOOR,
        )
    )
    assert project["require-dbt-version"] == DBT_CORE_FLOOR

    packages = yaml.safe_load(
        env.get_template("packages.yml.jinja2").render(
            dbt_packages=sorted(DBT_PACKAGE_REQUIREMENTS.items()),
        )
    )
    rendered = {entry["package"]: entry["version"] for entry in packages["packages"]}
    assert rendered == {
        name: [lower, upper] for name, (lower, upper) in DBT_PACKAGE_REQUIREMENTS.items()
    }


def test_hub_and_dataplatform_do_not_declare_divergent_adapter_pins():
    """#789 part 4: the two scaffolds drifted, and each hid what the other would catch.

    The dataplatform built its own `>=1.9.0,<2.0.0` pin, so it resolved a different dbt
    than the hub whose package it consumes — and the deprecations the hub emits were only
    observable downstream. Both now read the same declaration.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "kairos_ontology"
        / "cli"
        / "setup.py"
    ).read_text(encoding="utf-8")
    assert "dbt_adapter_requirement(adapter)" in source
    # Code only: the comment there quotes the old pin to explain what changed.
    code = [
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    ]
    assert not [line for line in code if ">=1.9.0,<2.0.0" in line]
