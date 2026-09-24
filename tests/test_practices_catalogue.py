# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The practices catalogue is the one source for docs, skills and checks (DD-240, #996)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from kairos_ontology.core import ddd
from kairos_ontology.core.projections.dbt import bpa_profile
from kairos_ontology.core.projections.dbt.gold_shape_checks import CODES
from kairos_ontology.practices import (
    AREAS,
    ENFORCEMENTS,
    STAGES,
    area_practices,
    load_catalogue,
    practice,
    practice_for_check,
    render_area_markdown,
)

REPO = Path(__file__).resolve().parent.parent
_SOURCE = "\n".join(
    path.read_text(encoding="utf-8")
    for path in (REPO / "src" / "kairos_ontology" / "core").rglob("*.py")
)


def _generator():
    spec = importlib.util.spec_from_file_location(
        "generate_practices", REPO / "scripts" / "generate_practices.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_rule_has_the_issue_fields():
    for item in load_catalogue():
        assert item.statement and item.rationale, item.id
        assert item.enforcement in ENFORCEMENTS, item.id
        assert item.stage in STAGES, item.id
        assert item.source, item.id


def test_every_catalogue_owned_rule_lives_in_its_area_namespace():
    for area in AREAS:
        for item in area_practices(area):
            if not item.bpa:
                assert item.id.startswith(f"{area}."), item.id


def test_every_checked_rule_names_a_code_the_toolkit_emits():
    """A rule naming a code nothing raises would claim a check that never runs."""
    for item in load_catalogue():
        for code in item.check.split(", "):
            if code != "none":
                assert f'"{code}"' in _SOURCE, (item.id, code)


def test_every_ddd_audit_code_is_a_practice():
    """The `ddd.*` codes stay in core/ddd.py; each one is described by its entry here."""
    codes = {
        value
        for name, value in vars(ddd).items()
        if name.startswith("CODE_") and name != "CODE_PRACTICE_EXCEPTION_UNUSED"
    }
    assert codes, "no ddd codes found"
    for code in codes:
        assert practice(code) is not None, code
        assert practice(code).check == code


def test_every_shape_code_is_a_practice():
    for practice_id, code in CODES.items():
        assert practice(practice_id).check == code
        assert practice_for_check(code).id == practice_id


def test_the_bpa_profile_is_projected_in_whole():
    ids = {item.id for item in area_practices("semantic-model") if item.bpa}
    assert ids == {item.rule_id for item in bpa_profile.all_rules()}


def test_a_blocking_bpa_rule_stays_blocking():
    """No behaviour change: the catalogue reads the profile, it does not reinterpret it."""
    assert practice("DAX_COLUMNS_FULLY_QUALIFIED").enforcement == "blocking"
    assert practice("DAX_COLUMNS_FULLY_QUALIFIED").stage == "compile --check"
    assert practice("MODEL_SHOULD_HAVE_A_DATE_TABLE").stage == "emit-gold"


def test_consistency_errors_cannot_be_excused():
    """An exception is for a design choice, not for a model that disagrees with itself."""
    for code in ("ddd.context-label-conflict", "ddd.class-in-two-contexts"):
        assert not practice(code).excusable


def test_the_new_ddd_rules_are_warnings_only():
    """DD-091: DDD reports and never gates Silver."""
    for item in area_practices("ddd"):
        if item.id not in {value for name, value in vars(ddd).items() if name.startswith("CODE_")}:
            assert item.enforcement == "warning", item.id


@pytest.mark.parametrize("area", AREAS)
def test_the_generated_page_is_current(area):
    page = REPO / "docs" / "guide" / "practices" / f"{area}.md"
    assert page.read_text(encoding="utf-8").replace("\r\n", "\n") == render_area_markdown(area)


def test_the_generator_check_mode_agrees():
    assert _generator().main(["--check"]) == 0


@pytest.mark.parametrize("area", AREAS)
def test_every_rule_is_on_its_page(area):
    text = render_area_markdown(area)
    for item in area_practices(area):
        assert re.search(rf"`{re.escape(item.id)}`", text), item.id


def test_the_design_skills_point_at_the_catalogue():
    """The skills reference the catalogue instead of restating it (#996)."""
    gold = (REPO / ".claude" / "skills" / "kairos-design-gold" / "SKILL.md").read_text("utf-8")
    architecture = (
        REPO / ".claude" / "skills" / "kairos-design-architecture" / "SKILL.md"
    ).read_text("utf-8")
    assert "docs/toolkit/practices/semantic-model.md" in gold
    assert "deactivated_relationships" in gold
    assert "docs/toolkit/practices/ddd.md" in architecture
