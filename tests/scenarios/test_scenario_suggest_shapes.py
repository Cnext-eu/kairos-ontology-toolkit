# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for `suggest-shapes` (DD-076) against acme-hub source data.

Exercises draft SHACL generation from a real bronze vocabulary, including the
DD-075 PII masking guarantee for the CRM email column.
"""

from pathlib import Path

from kairos_ontology.suggest_shapes import suggest_shapes

ACME_HUB = Path(__file__).parent / "acme-hub"
CRM_VOCAB = ACME_HUB / "integration" / "sources" / "crmsystem" / "crmsystem.vocabulary.ttl"


class TestSuggestShapesAcmeHub:
    def test_draft_shapes_generated(self, tmp_path):
        out = tmp_path / "crmsystem.ttl"
        written = suggest_shapes(CRM_VOCAB, out)
        assert written.exists()
        text = out.read_text(encoding="utf-8")
        # A NodeShape for the Customers table with typed property shapes.
        assert "NodeShape" in text
        assert "PropertyShape" in text
        assert "datatype" in text
        # Example values surfaced for non-PII columns.
        assert "Acme NV" in text or "C-1001" in text

    def test_pii_email_is_masked(self, tmp_path):
        out = tmp_path / "crmsystem.ttl"
        suggest_shapes(CRM_VOCAB, out)
        text = out.read_text(encoding="utf-8")
        # Raw email sample values must NEVER appear in the committed draft.
        assert "jane.doe@acme.example" not in text
        assert "bob@globex.example" not in text

    def test_no_sample_values_suppresses_examples(self, tmp_path):
        out = tmp_path / "crmsystem.ttl"
        suggest_shapes(CRM_VOCAB, out, include_sample_values=False)
        text = out.read_text(encoding="utf-8")
        assert "Example values:" not in text
        # Datatype constraints are still emitted (not sample-dependent).
        assert "datatype" in text

    def test_output_suffix_is_plain_ttl(self, tmp_path):
        # DD-076: drafts use .ttl (not .shacl.ttl) so the validator does not
        # auto-load them from a shapes directory.
        out = tmp_path / "crmsystem.ttl"
        written = suggest_shapes(CRM_VOCAB, out)
        assert written.name.endswith(".ttl")
        assert not written.name.endswith(".shacl.ttl")
