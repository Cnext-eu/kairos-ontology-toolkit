# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A hub-facing skill that reads ontology meaning names the closure-aware command (DD-243).

The audit behind DD-243 found the rule "never read a raw `.ttl` as text" in six skills and
the *working steps* of the design skills saying "read the import closure" with no command
named. An agent takes the path it is shown. So: any managed skill that talks about
``model/ontologies`` or the import closure must name at least one of the four inspection
commands and carry the rule. Skills not there yet are listed as known gaps, which the
follow-up skills PR empties; a skill that regresses fails here.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / ".claude" / "skills"

#: Talks about ontology meaning.
TRIGGER = re.compile(r"model/ontologies|import closure", re.IGNORECASE)
#: Names a closure-aware way to read it.
COMMANDS = re.compile(r"show-class-inventory|list-class-properties|explain-term|resolve-ontology")
#: Carries the DD-103 rule, in any of the phrasings the skills use today.
RULE = re.compile(r"never read (a )?raw|as text", re.IGNORECASE)

#: Managed skills that mention ontology files only to describe the hub layout.
LAYOUT_ONLY = {"kairos-setup-config", "kairos-setup-init"}

#: Managed skills that still say "read the ontology" without naming the command. The
#: skills PR (DD-243 follow-up) removes each of these; nothing may be added.
KNOWN_GAPS: set[str] = set()


def _unmanaged() -> set[str]:
    spec = importlib.util.spec_from_file_location(
        "sync_dev_skills", ROOT / "scripts" / "sync_dev_skills.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return set(module._UNMANAGED_SKILL_DIRS)


def _managed_skills() -> list[Path]:
    unmanaged = _unmanaged()
    return sorted(p for p in SKILLS.glob("*/SKILL.md") if p.parent.name not in unmanaged)


@pytest.mark.parametrize("skill", _managed_skills(), ids=lambda p: p.parent.name)
def test_a_skill_that_reads_ontology_meaning_names_the_command(skill: Path):
    name = skill.parent.name
    text = skill.read_text(encoding="utf-8")
    if name in LAYOUT_ONLY or not TRIGGER.search(text):
        return
    compliant = bool(COMMANDS.search(text)) and bool(RULE.search(text))
    if name in KNOWN_GAPS:
        assert not compliant, f"{name} is compliant now; remove it from KNOWN_GAPS"
        return
    assert compliant, (
        f"{name} mentions the ontology or its import closure but names none of "
        "show-class-inventory / list-class-properties / explain-term / resolve-ontology, "
        "or lacks the DD-103 rule. A domain .ttl read alone misses its owl:imports."
    )


def test_known_gaps_are_managed_skills():
    names = {p.parent.name for p in _managed_skills()}
    assert KNOWN_GAPS <= names
    assert LAYOUT_ONLY <= names
