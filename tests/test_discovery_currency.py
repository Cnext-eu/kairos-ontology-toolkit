# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""An artifact grounded in a glossary that has since changed (#885).

`*-alignment.yaml` fingerprints its affinity input (DD-094) and its resolved import
closure (#518) so either going stale is visible. The business glossary was the one input
nothing recorded — and it is the one a human maintains between runs, so it is the one
most likely to move underneath an artifact built from it.
"""

import yaml

from kairos_ontology.core.discovery_currency import (
    GLOSSARY_FINGERPRINT_KEY,
    UNGROUNDED,
    detect_glossary_drift,
    glossary_fingerprint,
)

GLOSSARY = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix glossary: <https://example.com/glossary#> .

glossary:Allocation a skos:Concept ;
    skos:prefLabel "Allocation"@en ;
    skos:definition "A verbal agreement giving a customer places on a ship."@en .
"""


def _hub(tmp_path, glossary: str | None = GLOSSARY):
    hub = tmp_path / "ontology-hub"
    (hub / "businessdiscovery").mkdir(parents=True)
    if glossary is not None:
        (hub / "businessdiscovery" / "acme-glossary.ttl").write_text(glossary, encoding="utf-8")
    return hub


def _artifact(hub, fingerprint: str | None):
    path = hub / "roro-alignment.yaml"
    document = {"domain": "roro", "tables": []}
    if fingerprint is not None:
        document[GLOSSARY_FINGERPRINT_KEY] = fingerprint
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


class TestGlossaryFingerprint:
    def test_a_hub_without_a_glossary_is_ungrounded_not_empty(self, tmp_path):
        """An omitted key and a known-absent glossary are different facts."""
        assert glossary_fingerprint(_hub(tmp_path, glossary=None)) == UNGROUNDED

    def test_the_same_glossary_digests_the_same(self, tmp_path):
        first = glossary_fingerprint(_hub(tmp_path / "a"))
        second = glossary_fingerprint(_hub(tmp_path / "b"))

        assert first == second != UNGROUNDED

    def test_a_new_term_changes_the_digest(self, tmp_path):
        before = glossary_fingerprint(_hub(tmp_path / "a"))
        after = glossary_fingerprint(
            _hub(
                tmp_path / "b",
                GLOSSARY + '\nglossary:Berth a skos:Concept ;\n'
                '    skos:prefLabel "Berth"@en ;\n'
                '    skos:definition "A mooring location."@en .\n',
            )
        )

        assert before != after

    def test_a_changed_definition_changes_the_digest(self, tmp_path):
        before = glossary_fingerprint(_hub(tmp_path / "a"))
        after = glossary_fingerprint(
            _hub(tmp_path / "b", GLOSSARY.replace("places on a ship", "capacity on a voyage"))
        )

        assert before != after

    def test_reformatting_the_turtle_does_not(self, tmp_path):
        """The digest covers what reaches a prompt, not the file's bytes."""
        before = glossary_fingerprint(_hub(tmp_path / "a"))
        after = glossary_fingerprint(
            _hub(tmp_path / "b", "# a leading comment\n\n" + GLOSSARY.replace("    ", "  "))
        )

        assert before == after


class TestDetectGlossaryDrift:
    def test_a_current_artifact_reports_nothing(self, tmp_path):
        hub = _hub(tmp_path)
        path = _artifact(hub, glossary_fingerprint(hub))

        assert detect_glossary_drift(path, hub) is None

    def test_an_artifact_without_a_fingerprint_is_not_called_stale(self, tmp_path):
        """Generated before this existed. Warning about an invisible difference teaches
        readers to ignore warnings."""
        hub = _hub(tmp_path)

        assert detect_glossary_drift(_artifact(hub, None), hub) is None

    def test_a_changed_glossary_is_drift(self, tmp_path):
        hub = _hub(tmp_path)
        path = _artifact(hub, "a-fingerprint-from-an-older-vocabulary")

        drift = detect_glossary_drift(path, hub)

        assert drift is not None
        assert "different version" in drift.describe()
        assert not drift.was_ungrounded

    def test_an_ungrounded_artifact_against_a_hub_that_now_has_one(self, tmp_path):
        hub = _hub(tmp_path)
        path = _artifact(hub, UNGROUNDED)

        drift = detect_glossary_drift(path, hub)

        assert drift is not None
        assert drift.was_ungrounded
        assert "no business glossary in scope" in drift.describe()

    def test_an_unreadable_artifact_reports_nothing(self, tmp_path):
        hub = _hub(tmp_path)
        path = hub / "broken-alignment.yaml"
        path.write_text("this is not: valid: yaml: [[[", encoding="utf-8")

        assert detect_glossary_drift(path, hub) is None


# ---------------------------------------------------------------------------
# The vocabulary reaches the anchoring prompt (issue #885 item 2)
# ---------------------------------------------------------------------------


SEE_ALSO_GLOSSARY = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix glossary: <https://example.com/glossary#> .

glossary:Berth a skos:Concept ;
    rdfs:seeAlso <https://ref.example.com/ont/tic#Berth> ;
    skos:prefLabel "Berth"@en ;
    skos:definition "A mooring location in a port."@en .

glossary:HouseStyle a skos:Concept ;
    skos:prefLabel "House Style"@en ;
    skos:definition "An internal naming habit with no class attached."@en .
"""


class TestAnchorGlossaryBlock:
    """anchor-tables decides what every table IS; the glossary says what the business
    calls its concepts and which class each one is. It saw none of it (#885)."""

    def _hub(self, tmp_path, ttl=SEE_ALSO_GLOSSARY):
        hub = tmp_path / "ontology-hub"
        (hub / "businessdiscovery").mkdir(parents=True)
        if ttl is not None:
            (hub / "businessdiscovery" / "acme-glossary.ttl").write_text(ttl, encoding="utf-8")
        return hub

    def test_a_term_with_a_class_is_rendered_with_it(self, tmp_path):
        from kairos_ontology.core.anchor_tables import render_anchor_glossary

        text = render_anchor_glossary(self._hub(tmp_path))

        assert "Berth -> https://ref.example.com/ont/tic#Berth" in text
        assert "A mooring location in a port." in text

    def test_a_term_with_no_class_is_not_evidence_for_anchoring(self, tmp_path):
        from kairos_ontology.core.anchor_tables import render_anchor_glossary

        text = render_anchor_glossary(self._hub(tmp_path))

        assert "House Style" not in text

    def test_it_is_stated_as_evidence_not_as_an_instruction(self, tmp_path):
        from kairos_ontology.core.anchor_tables import render_anchor_glossary

        text = render_anchor_glossary(self._hub(tmp_path))

        assert "not an instruction" in text

    def test_no_glossary_means_no_section_at_all(self, tmp_path):
        from kairos_ontology.core.anchor_tables import render_anchor_glossary

        assert render_anchor_glossary(self._hub(tmp_path, ttl=None)) == ""

    def test_no_hub_is_not_an_error(self):
        from kairos_ontology.core.anchor_tables import render_anchor_glossary

        assert render_anchor_glossary(None) == ""
