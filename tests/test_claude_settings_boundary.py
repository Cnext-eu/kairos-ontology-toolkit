# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Static boundary test pinning the DD-103 semantic-access deny list.

``src/kairos_ontology/scaffold/claude-settings.json`` is the shipped Claude Code
settings file that denies raw ``Grep`` access to ontology serializations
(``.ttl``/``.rdf``/``.owl``) under the three guarded hub paths, and (dataplatform
improvements backlog item #18) denies ``Edit``/``Write`` under ``ontology-hub-publish/``
so compiler-owned output can't be hand-edited. Nothing else in the suite pins its exact
contents, so a well-meaning "cleanup" could quietly narrow it back down (e.g. to ``.ttl``
only, or to one anchoring, or to one tool prefix) without any test failing.

The deny list intentionally duplicates every rule across two axes that look
redundant but are NOT verified as inert on every Claude Code build:

- **anchoring** — both ``/<path>/...`` (repo-root-relative) and ``./<path>/...``
  (cwd-relative) forms, because it is not confirmed which one Claude Code actually
  matches against in every working-directory configuration;
**``Read`` is deliberately NOT denied (issue #659).** It was, until it turned out to
forbid the exact workflow ``kairos-design-domain`` documents: Claude Code requires a
prior ``Read`` of a file before ``Edit`` will touch it, so denying ``Read`` on
``model/ontologies/**`` and ``model/shapes/**`` made hand-authoring a domain ``.ttl``
(step 6b) or its governance SHACL structurally impossible, even though ``Edit``/``Write``
were never denied. DD-103 is a boundary on *inspection* -- understand ontologies through
``explain-term``/``show-class-inventory``/``list-class-properties``/``resolve-ontology``,
not by scanning serialized RDF as unstructured text -- and ``Grep`` is what actually does
that scanning. Do not re-add ``Read`` here without solving the ``Edit`` precondition.

The anchoring duplication below is deliberate fail-closed redundancy, not sloppiness.
Do NOT "simplify" this file or this test down to one anchoring.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

from kairos_ontology.cli.shared import _KNOWN_CLAUDE_SETTINGS_HASHES

_GENERATIONS_DIR = Path(__file__).resolve().parent / "fixtures" / "claude-settings-generations"

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

# `Grep` only: `Read` is intentionally permitted so ontology authoring can happen at
# all. See the module docstring, and issue #659.
_GUARDED_TOOLS = ("Grep",)

# Both anchorings: see module docstring for why.
_GUARDED_ANCHORS = ("/", "./")

# Item #18: compiler-owned output must never be hand-edited (CICD.md / kairos-execute-project
# already say so in prose; this makes it a mechanical guard). Edit/Write only -- Read/Grep of
# emitted output is normal and expected.
_PUBLISH_GUARDED_PATH = "ontology-hub-publish"
_PUBLISH_GUARDED_TOOLS = ("Edit", "Write")


def _expected_rules() -> set[str]:
    ttl_rules = {
        f"{tool}({anchor}{path}/**/*.{ext})"
        for path, ext, tool, anchor in itertools.product(
            _GUARDED_PATHS, _GUARDED_EXTENSIONS, _GUARDED_TOOLS, _GUARDED_ANCHORS
        )
    }
    publish_rules = {
        f"{tool}({anchor}{_PUBLISH_GUARDED_PATH}/**)"
        for tool, anchor in itertools.product(_PUBLISH_GUARDED_TOOLS, _GUARDED_ANCHORS)
    }
    return ttl_rules | publish_rules


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


def _lf_hash(data: bytes) -> str:
    normalized = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def test_current_scaffold_hash_is_not_a_known_superseded_hash():
    # _KNOWN_CLAUDE_SETTINGS_HASHES must hold only *superseded* generations of this
    # file. If the current file's hash ever ended up in that tuple (e.g. someone
    # "helpfully" adds it after a future edit), `kairos-ontology update` would treat
    # a hub already on the current generation as needing replacement by itself —
    # harmless in effect, but a sign the tuple was mis-maintained and a real
    # regression waiting to happen the next time the file changes again.
    current_hash = _lf_hash(_SCAFFOLD_SETTINGS.read_bytes())
    assert current_hash not in _KNOWN_CLAUDE_SETTINGS_HASHES


def test_read_is_never_denied_on_authorable_paths():
    """Denying ``Read`` also disables ``Edit``, which needs a prior ``Read``.

    That is not a style preference: it made `kairos-design-domain`'s documented
    authoring steps impossible to complete under the default scaffold (issue #659).
    """
    deny = _load_settings()["permissions"]["deny"]
    read_rules = [rule for rule in deny if rule.startswith("Read(")]
    assert not read_rules, (
        "Read is denied again on ontology/shapes paths, which silently blocks Edit: "
        f"{read_rules}"
    )


def test_grep_and_publish_guards_survive():
    """The parts of the boundary that were never the problem must stay intact."""
    deny = set(_load_settings()["permissions"]["deny"])
    assert "Grep(./ontology-hub/model/ontologies/**/*.ttl)" in deny
    assert "Grep(./ontology-hub/model/shapes/**/*.ttl)" in deny
    assert "Edit(./ontology-hub-publish/**)" in deny
    assert "Write(./ontology-hub-publish/**)" in deny


def test_superseded_generation_is_recorded_so_update_can_deliver_the_fix():
    """Existing hubs only receive this change if the prior hash is registered.

    This is the **LF-normalized** hash of the pre-#659 generation. It used to be that
    generation's CRLF rendering (issue #684), so the entry only matched on a Windows checkout:
    ``update --check`` then exited 1 on Windows and 0 on Linux for the identical commit.
    """
    assert (
        "6e6ee7d78b3f32e890ac2c7f4bbd4c77546a068bee136f61f96a7cb4a3d4a0e6"
        in _KNOWN_CLAUDE_SETTINGS_HASHES
    )


def test_every_registered_hash_is_line_ending_normalized():
    """No entry may be a CRLF rendering of a generation (issue #684).

    A CRLF hash silently turns managed-file identity into a per-platform question: the same
    committed file is "a known superseded generation" on Windows and "unrecognized, leave it
    alone" on Linux. Nothing else in the suite would notice, because both branches are
    plausible in isolation -- which is exactly how the previous entry survived.

    Checked against vendored fixtures rather than git history: CI checks out at
    ``fetch-depth: 1``, so a test that reached for old revisions passed locally and failed
    only in CI.
    """
    fixtures = sorted(_GENERATIONS_DIR.glob("*.json"))
    assert fixtures, f"no vendored generations in {_GENERATIONS_DIR}"

    lf_hashes = {_lf_hash(path.read_bytes()): path.name for path in fixtures}
    # Raw sha256 of the CRLF rendering -- deliberately NOT `_lf_hash`, which normalizes and
    # would just hand back the LF digest, making this check vacuous.
    crlf_hashes = {
        hashlib.sha256(path.read_bytes().replace(b"\n", b"\r\n")).hexdigest(): path.name
        for path in fixtures
    }

    unexplained = set(_KNOWN_CLAUDE_SETTINGS_HASHES) - set(lf_hashes)
    assert not unexplained, (
        "registered hash(es) match no vendored generation's LF content. If a generation was "
        "just added, vendor it under tests/fixtures/claude-settings-generations/; otherwise "
        f"the entry was likely captured from a CRLF checkout: {sorted(unexplained)}"
    )

    crlf_entries = {
        digest: crlf_hashes[digest]
        for digest in _KNOWN_CLAUDE_SETTINGS_HASHES
        if digest in crlf_hashes
    }
    assert not crlf_entries, (
        f"registered hash(es) are the CRLF rendering of a generation: {crlf_entries}"
    )


def test_every_vendored_generation_is_stored_with_lf_endings():
    """A CRLF fixture would re-introduce the bug these fixtures exist to pin."""
    for path in sorted(_GENERATIONS_DIR.glob("*.json")):
        assert b"\r" not in path.read_bytes(), f"{path.name} must be stored with LF endings"


def test_the_pre_659_generation_is_the_one_that_denied_read():
    """Pins what the #659 change actually was, which the report must be able to state.

    The twelve ``Read(...)`` denies are the *shipped* pre-#659 file, not a hub customization
    -- which is why `update` replacing them is the fix being delivered rather than data loss.
    """
    pre_659 = json.loads(
        (_GENERATIONS_DIR / "04-pre-659-read-denies.json").read_text(encoding="utf-8")
    )
    read_rules = [rule for rule in pre_659["permissions"]["deny"] if rule.startswith("Read(")]
    assert len(read_rules) == 12
    # 2 guarded paths x 3 extensions x 2 anchorings.
    assert len(_GUARDED_PATHS) * len(_GUARDED_EXTENSIONS) * len(_GUARDED_ANCHORS) == 12
    # And they are gone from what ships today.
    assert not [
        rule for rule in _load_settings()["permissions"]["deny"] if rule.startswith("Read(")
    ]
