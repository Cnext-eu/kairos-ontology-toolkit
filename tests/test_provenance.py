# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the provenance comment header helper (DD-072)."""

from __future__ import annotations

from datetime import datetime, timezone

from rdflib import Graph

from kairos_ontology import __version__
from kairos_ontology.core._provenance import (
    prepend_provenance,
    provenance_comment,
    strip_provenance,
)

FIXED = datetime(2026, 6, 14, 11, 8, 57, tzinfo=timezone.utc)


def test_comment_contains_version_generator_and_date():
    header = provenance_comment("build-glossary", generated_at=FIXED)
    assert f"v{__version__}" in header
    assert "kairos-ontology-toolkit" in header
    assert "Generator : build-glossary" in header
    assert "2026-06-14T11:08:57Z (UTC)" in header
    # Every line is a Turtle comment.
    assert all(line.startswith("#") for line in header.splitlines())


def test_comment_edit_policy_note_varies():
    generated = provenance_comment("import-source", generated_at=FIXED)
    editable = provenance_comment("init", generated_at=FIXED, editable=True)
    assert "Do not edit by hand" in generated
    assert "safe to edit" in editable.lower()


def test_comment_renders_extra_lines():
    header = provenance_comment(
        "import-source", generated_at=FIXED, extra={"Source system": "CRM"}
    )
    assert "# Source system : CRM" in header


def test_naive_datetime_is_treated_as_utc():
    naive = datetime(2026, 6, 14, 11, 8, 57)
    header = provenance_comment("x", generated_at=naive)
    assert "2026-06-14T11:08:57Z (UTC)" in header


def test_prepend_keeps_graph_parseable():
    ttl = "@prefix ex: <https://ex/#> .\nex:A a ex:Thing .\n"
    stamped = prepend_provenance(ttl, "import-source", generated_at=FIXED)
    assert stamped.startswith("#")
    g = Graph()
    g.parse(data=stamped, format="turtle")
    assert len(g) == 1


def test_prepend_is_idempotent():
    ttl = "@prefix ex: <https://ex/#> .\nex:A a ex:Thing .\n"
    once = prepend_provenance(ttl, "import-source", generated_at=FIXED)
    twice = prepend_provenance(once, "import-source", generated_at=FIXED)
    # No stacked headers: exactly two rule lines (open + close) survive.
    rule = "# " + "-" * 70
    assert twice.count(rule) == 2
    assert twice == once


def test_strip_leaves_user_comments_untouched():
    ttl = "# a user comment\n@prefix ex: <https://ex/#> .\n"
    assert strip_provenance(ttl) == ttl


def test_strip_removes_only_toolkit_header():
    ttl = "@prefix ex: <https://ex/#> .\nex:A a ex:Thing .\n"
    stamped = prepend_provenance(ttl, "import-source", generated_at=FIXED)
    assert strip_provenance(stamped).strip() == ttl.strip()
