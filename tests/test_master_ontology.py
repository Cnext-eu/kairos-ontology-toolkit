# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for ``core/master_ontology.py`` (issue #393)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kairos_ontology.core.master_ontology import (
    MasterOntologySyncError,
    list_active_master_imports,
    sync_master_ontology_import,
)

_SCAFFOLD_MASTER = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://acme.com/ont/master> a owl:Ontology ;
    rdfs:label "Acme Master Ontology"@en ;
    rdfs:comment "Unified ontology that imports all domain ontologies for Acme"@en ;
    owl:versionInfo "0.1.0" .

## -- Add owl:imports for each domain ontology below --
## Example:
##   owl:imports <https://acme.com/ont/customer> ;
##   owl:imports <https://acme.com/ont/order> .
"""


def _write(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _read(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


class TestListActiveMasterImports:
    def test_scaffold_template_has_no_active_imports(self, tmp_path):
        master = tmp_path / "_master.ttl"
        _write(master, _SCAFFOLD_MASTER)
        assert list_active_master_imports(master) == set()

    def test_commented_out_example_is_ignored_even_after_a_live_import(self, tmp_path):
        master = tmp_path / "_master.ttl"
        text = _SCAFFOLD_MASTER.replace(
            "## -- Add owl:imports for each domain ontology below --",
            "<https://acme.com/ont/master> owl:imports <https://acme.com/ont/party> .\n\n"
            "## -- Add owl:imports for each domain ontology below --",
        )
        _write(master, text)
        imports = list_active_master_imports(master)
        assert imports == {"https://acme.com/ont/party"}
        assert "https://acme.com/ont/customer" not in imports
        assert "https://acme.com/ont/order" not in imports

    def test_live_imports_are_found(self, tmp_path):
        master = tmp_path / "_master.ttl"
        text = _SCAFFOLD_MASTER + (
            "<https://acme.com/ont/master> owl:imports <https://acme.com/ont/party> .\n"
        )
        _write(master, text)
        assert list_active_master_imports(master) == {"https://acme.com/ont/party"}


class TestSyncMasterOntologyImport:
    def test_inserts_after_marker_comment_when_no_imports_exist(self, tmp_path):
        master = tmp_path / "_master.ttl"
        _write(master, _SCAFFOLD_MASTER)

        inserted = sync_master_ontology_import(master, "https://acme.com/ont/party")
        assert inserted is True

        text = _read(master)
        marker_idx = text.index("## -- Add owl:imports for each domain ontology below --")
        new_triple_idx = text.index(
            "<https://acme.com/ont/master> owl:imports <https://acme.com/ont/party> ."
        )
        example_idx = text.index("## Example:")
        # Anchored right after the marker line, before the commented-out example.
        assert marker_idx < new_triple_idx < example_idx
        assert list_active_master_imports(master) == {"https://acme.com/ont/party"}

    def test_inserts_after_last_existing_import(self, tmp_path):
        master = tmp_path / "_master.ttl"
        _write(master, _SCAFFOLD_MASTER)

        # First insert anchors on the marker comment (no imports exist yet).
        assert sync_master_ontology_import(master, "https://acme.com/ont/party") is True
        # Second insert must now anchor on the just-inserted live import line,
        # not re-anchor on the marker comment (which would place it before party).
        assert sync_master_ontology_import(master, "https://acme.com/ont/booking") is True

        updated = _read(master)
        party_idx = updated.index(
            "<https://acme.com/ont/master> owl:imports <https://acme.com/ont/party> ."
        )
        booking_idx = updated.index(
            "<https://acme.com/ont/master> owl:imports <https://acme.com/ont/booking> ."
        )
        marker_idx = updated.index(
            "## -- Add owl:imports for each domain ontology below --"
        )
        assert marker_idx < party_idx < booking_idx
        assert list_active_master_imports(master) == {
            "https://acme.com/ont/party",
            "https://acme.com/ont/booking",
        }

    def test_idempotent_same_iri_returns_false_and_does_not_duplicate(self, tmp_path):
        master = tmp_path / "_master.ttl"
        _write(master, _SCAFFOLD_MASTER)

        first = sync_master_ontology_import(master, "https://acme.com/ont/party")
        assert first is True
        before = _read(master)

        second = sync_master_ontology_import(master, "https://acme.com/ont/party")
        assert second is False
        after = _read(master)

        assert before == after
        assert after.count("https://acme.com/ont/party") == 1

    def test_trailing_slash_is_treated_as_same_iri(self, tmp_path):
        master = tmp_path / "_master.ttl"
        text = _SCAFFOLD_MASTER + (
            "<https://acme.com/ont/master> owl:imports <https://acme.com/ont/party/> .\n"
        )
        _write(master, text)

        inserted = sync_master_ontology_import(master, "https://acme.com/ont/party")
        assert inserted is False

    def test_crlf_line_endings_are_preserved(self, tmp_path):
        master = tmp_path / "_master.ttl"
        crlf_text = _SCAFFOLD_MASTER.replace("\n", "\r\n")
        _write(master, crlf_text)

        sync_master_ontology_import(master, "https://acme.com/ont/party")

        raw = master.read_bytes()
        assert b"\r\n" in raw
        # No bare LF that isn't part of a CRLF pair.
        assert raw.replace(b"\r\n", b"").count(b"\n") == 0

    def test_preserves_everything_outside_the_touched_span(self, tmp_path):
        master = tmp_path / "_master.ttl"
        _write(master, _SCAFFOLD_MASTER)
        before = _read(master)

        sync_master_ontology_import(master, "https://acme.com/ont/party")
        after = _read(master)

        # Every line of the original file must still appear, in order, in the
        # updated file -- only new content was inserted, nothing was rewritten.
        before_lines = before.splitlines()
        after_lines = after.splitlines()
        idx = 0
        for line in after_lines:
            if idx < len(before_lines) and line == before_lines[idx]:
                idx += 1
        assert idx == len(before_lines)

    def test_last_resort_appends_standalone_triple_when_marker_and_imports_absent(
        self, tmp_path
    ):
        master = tmp_path / "_master.ttl"
        text = (
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
            "<https://acme.com/ont/master> a owl:Ontology ;\n"
            '    rdfs:label "Acme Master Ontology"@en ;\n'
            '    owl:versionInfo "0.1.0" .\n'
        )
        _write(master, text)

        inserted = sync_master_ontology_import(master, "https://acme.com/ont/party")
        assert inserted is True
        assert list_active_master_imports(master) == {"https://acme.com/ont/party"}
        # Original content is untouched, new triple appended at the end.
        updated = _read(master)
        assert updated.startswith(text)

    def test_invalid_proposed_text_is_not_written(self, tmp_path, monkeypatch):
        import kairos_ontology.core.master_ontology as master_ontology_mod

        master = tmp_path / "_master.ttl"
        _write(master, _SCAFFOLD_MASTER)
        before = master.read_bytes()

        # Force the final validation step to fail deterministically -- rdflib's
        # Turtle parser is lenient about malformed-looking IRIs (it only warns), so
        # this stubs the validator itself rather than relying on crafting text
        # rdflib happens to reject.
        def _always_fails(_text, **_kwargs):
            raise ValueError("synthetic parse failure for this test")

        monkeypatch.setattr(master_ontology_mod, "validate_turtle_text", _always_fails)

        with pytest.raises(MasterOntologySyncError):
            sync_master_ontology_import(master, "https://acme.com/ont/party")

        assert master.read_bytes() == before

    def test_no_ontology_declaration_raises_and_does_not_write(self, tmp_path):
        master = tmp_path / "_master.ttl"
        text = "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n# no owl:Ontology here\n"
        _write(master, text)
        before = master.read_bytes()

        with pytest.raises(MasterOntologySyncError):
            sync_master_ontology_import(master, "https://acme.com/ont/party")

        assert master.read_bytes() == before

    def test_corrupt_master_ttl_raises_and_does_not_write(self, tmp_path):
        master = tmp_path / "_master.ttl"
        text = "this is not valid turtle at all {{{ owl:imports <><><"
        _write(master, text)
        before = master.read_bytes()

        with pytest.raises(MasterOntologySyncError):
            sync_master_ontology_import(master, "https://acme.com/ont/party")

        assert master.read_bytes() == before
