# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""AI attribution on generated artifacts (DD-178).

An ontology reads as authoritative — that is what one is for — so an artifact
whose content a language model proposed has to say so on its face, where anyone
opening the file sees it, not only in a run log nobody keeps. These tests pin
what is stamped and, as importantly, what is *not*: a deterministic generator
must never claim AI assistance it did not use.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from kairos_ontology.core._provenance import (
    ai_attribution,
    ai_attribution_note,
    prepend_provenance,
    provenance_comment,
    strip_provenance,
)

FIXED = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)


class TestAIAttributionFields:
    def test_records_what_a_rerun_would_need(self):
        extra = ai_attribution(
            model="gpt-5.5", role="alignment", seed=20260101, reasoning_effort="medium"
        )
        assert extra == {
            "AI model": "gpt-5.5",
            "AI role": "alignment",
            "AI seed": "20260101",
            "AI effort": "medium",
        }

    def test_absent_settings_are_not_claimed(self):
        """An artifact generated without a seed must not report one."""
        extra = ai_attribution(model="gpt-5.5", seed=None, reasoning_effort=None)
        assert extra == {"AI model": "gpt-5.5"}
        assert "AI seed" not in extra

    def test_seed_zero_is_recorded_not_dropped(self):
        """0 is a legitimate seed; only None means 'not set'."""
        assert ai_attribution(model="m", seed=0)["AI seed"] == "0"


class TestHeaderStamping:
    def test_disclaimer_present_only_when_ai_generated(self):
        with_ai = provenance_comment("propose-alignment", generated_at=FIXED, ai_generated=True)
        without = provenance_comment("import-source", generated_at=FIXED)
        assert "AI-ASSISTED" in with_ai
        assert "proposal for human review" in with_ai
        assert "AI-ASSISTED" not in without

    def test_model_appears_in_the_header(self):
        header = provenance_comment(
            "propose-alignment",
            generated_at=FIXED,
            extra=ai_attribution(model="gpt-5.5", role="alignment", seed=7),
            ai_generated=True,
        )
        assert "# AI model : gpt-5.5" in header
        assert "# AI role : alignment" in header
        assert "# AI seed : 7" in header

    def test_every_line_stays_commented(self):
        """The block is prepended to Turtle and YAML; an uncommented line breaks both."""
        header = provenance_comment(
            "x", generated_at=FIXED, extra=ai_attribution(model="m"), ai_generated=True
        )
        for line in header.splitlines():
            assert line.startswith("#"), f"uncommented line would corrupt the artifact: {line!r}"

    def test_header_is_deterministic_for_a_fixed_timestamp(self):
        """A regenerated artifact must not diff on the header alone."""
        kwargs = dict(
            generated_at=FIXED, extra=ai_attribution(model="m", seed=1), ai_generated=True
        )
        assert provenance_comment("g", **kwargs) == provenance_comment("g", **kwargs)


class TestRoundTrip:
    def test_ai_header_is_stripped_and_not_stacked(self):
        ttl = "@prefix ex: <http://example.org/> .\n"
        once = prepend_provenance(
            ttl, "g", generated_at=FIXED, extra=ai_attribution(model="m"), ai_generated=True
        )
        twice = prepend_provenance(
            once, "g", generated_at=FIXED, extra=ai_attribution(model="m"), ai_generated=True
        )
        assert once == twice
        assert once.count("AI-ASSISTED") == 1
        assert strip_provenance(once) == ttl

    def test_turtle_still_parses_with_the_ai_header(self):
        from rdflib import Graph

        ttl = "@prefix ex: <http://example.org/> .\nex:a a ex:B .\n"
        stamped = prepend_provenance(
            ttl, "g", generated_at=FIXED, extra=ai_attribution(model="m"), ai_generated=True
        )
        assert len(Graph().parse(data=stamped, format="turtle")) == 1

    def test_yaml_still_parses_with_the_ai_header(self):
        import yaml

        stamped = (
            provenance_comment(
                "propose-alignment",
                generated_at=FIXED,
                extra=ai_attribution(model="m"),
                ai_generated=True,
            )
            + yaml.safe_dump({"domain": "party", "tables": []})
        )
        assert yaml.safe_load(stamped) == {"domain": "party", "tables": []}


class TestMarkdownNote:
    def test_reflects_the_live_configuration(self):
        with patch.dict(
            "os.environ",
            {"KAIROS_AI_ALIGNMENT_MODEL": "gpt-5.5", "KAIROS_AI_ALIGNMENT_SEED": "42"},
        ):
            note = ai_attribution_note("alignment")
        assert "gpt-5.5" in note
        assert "42" in note
        assert "human review" in note

    def test_omits_a_disabled_seed(self):
        with patch.dict("os.environ", {"KAIROS_AI_ALIGNMENT_SEED": "off"}):
            assert "seed" not in ai_attribution_note("alignment")

    def test_report_leads_with_the_note(self):
        """The qualifier must precede the numbers it qualifies."""
        from kairos_ontology.core.alignment_report import AlignmentReport, render_markdown

        md = render_markdown(AlignmentReport())
        body = md.splitlines()
        note_at = next(i for i, ln in enumerate(body) if "AI-assisted" in ln)
        assert note_at < 4, "attribution should sit at the top of the report"


class TestDeterministicGeneratorsAreNotMislabelled:
    @pytest.mark.parametrize("generator", ["init", "new-repo", "build-glossary", "import-source"])
    def test_no_ai_claim_by_default(self, generator):
        assert "AI-ASSISTED" not in provenance_comment(generator, generated_at=FIXED)
