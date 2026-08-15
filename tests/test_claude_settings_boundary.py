# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Static boundary test pinning the DD-103 semantic-access deny list.

``src/kairos_ontology/scaffold/claude-settings.json`` is the shipped Claude Code
settings file that denies raw ``Read``/``Grep`` access to ontology serializations
(``.ttl``/``.rdf``/``.owl``) under the three guarded hub paths. Nothing else in the
suite pins its exact contents, so a well-meaning "cleanup" could quietly narrow it
back down (e.g. to ``.ttl`` only, or to one anchoring, or to one tool prefix) without
any test failing.

The deny list intentionally duplicates every rule across two axes that look
redundant but are NOT verified as inert on every Claude Code build:

- **anchoring** — both ``/<path>/...`` (repo-root-relative) and ``./<path>/...``
  (cwd-relative) forms, because it is not confirmed which one Claude Code actually
  matches against in every working-directory configuration;
- **tool prefix** — both ``Read(...)`` and ``Grep(...)``, because documentation
  suggests ``Grep`` deny rules may be inert on some builds, but that is not
  verifiable here either.

This is deliberate fail-closed duplication, not sloppiness. Do NOT "simplify" this
file or this test down to one anchoring or one tool prefix.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

from kairos_ontology.cli.shared import _KNOWN_CLAUDE_SETTINGS_HASHES

_SCAFFOLD_SETTINGS = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "kairos_ontology"
    / "scaffold"
    / "claude-settings.json"
)

# The three hub paths DD-103 guards. Kept here, not imported from shared.py, so
# this test independently pins the *intended* boundary rather than whatever the
# implementation currently happens to compute.
_GUARDED_PATHS = (
    "ontology-hub/model/ontologies",
    "ontology-hub/model/shapes",
)

# Ontology/SHACL serializations, and only these — not the JSON Schemas consumed by
# core/archetype_loader.py / core/binding_archetypes.py, and not catalog-v001.xml.
_GUARDED_EXTENSIONS = ("ttl", "rdf", "owl")

# Both tool prefixes: see module docstring for why.
_GUARDED_TOOLS = ("Read", "Grep")

# Both anchorings: see module docstring for why.
_GUARDED_ANCHORS = ("/", "./")


def _expected_rules() -> set[str]:
    return {
        f"{tool}({anchor}{path}/**/*.{ext})"
        for path, ext, tool, anchor in itertools.product(
            _GUARDED_PATHS, _GUARDED_EXTENSIONS, _GUARDED_TOOLS, _GUARDED_ANCHORS
        )
    }


def _load_settings() -> dict:
    return json.loads(_SCAFFOLD_SETTINGS.read_text(encoding="utf-8"))


def test_settings_file_is_valid_json_with_string_deny_list():
    settings = _load_settings()
    deny = settings["permissions"]["deny"]
    assert isinstance(deny, list)
    assert deny, "deny list must not be empty"
    assert all(isinstance(rule, str) for rule in deny)


def test_all_expected_deny_rules_are_present():
    deny = set(_load_settings()["permissions"]["deny"])
    expected = _expected_rules()
    missing = expected - deny
    assert not missing, f"Missing expected deny rule(s): {sorted(missing)}"


def test_deny_list_contains_exactly_the_expected_rules():
    # Guards against silent broadening (e.g. an accidental extra guarded path or
    # extension) as well as narrowing.
    deny = set(_load_settings()["permissions"]["deny"])
    assert deny == _expected_rules()


def test_no_rule_denies_json_or_xml():
    # 19 JSON Schemas are consumed by core/archetype_loader.py and
    # core/binding_archetypes.py. Neither is an ontology serialization, and both
    # must stay off the deny list.
    deny = _load_settings()["permissions"]["deny"]
    for rule in deny:
        assert ".json" not in rule, f"Unexpected .json in deny rule: {rule}"
        assert ".xml" not in rule, f"Unexpected .xml in deny rule: {rule}"


def test_current_scaffold_hash_is_not_a_known_superseded_hash():
    # _KNOWN_CLAUDE_SETTINGS_HASHES must hold only *superseded* generations of this
    # file. If the current file's hash ever ended up in that tuple (e.g. someone
    # "helpfully" adds it after a future edit), `kairos-ontology update` would treat
    # a hub already on the current generation as needing replacement by itself —
    # harmless in effect, but a sign the tuple was mis-maintained and a real
    # regression waiting to happen the next time the file changes again.
    current_hash = hashlib.sha256(_SCAFFOLD_SETTINGS.read_bytes()).hexdigest()
    assert current_hash not in _KNOWN_CLAUDE_SETTINGS_HASHES
