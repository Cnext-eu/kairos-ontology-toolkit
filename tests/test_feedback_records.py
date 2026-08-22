# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the modeling-feedback parser, validator, and serializer (issue #588)."""

from pathlib import Path

import pytest

from kairos_ontology.core import feedback_records as fr

_VALID_FRONTMATTER = (
    "type: Modeling Feedback\n"
    "id: HUB-FB-20260822-a1b2c3\n"
    "title: CargoWise keys off Org\n"
    "area: party\n"
    "status: open\n"
    "generated: { by: kairos-ontology-toolkit/9.9.9, at: 2026-08-22T10:00:00Z }\n"
)

_VALID_BODY = """# Observation

CargoWise keys customer data off Org, not GlbCompany.

# Design implication

Bind identity on Org.

# Resolution

<Not yet resolved.>

# Open follow-ups

<None recorded.>
"""


def _write(dirpath: Path, name: str, frontmatter: str, body: str = _VALID_BODY) -> Path:
    path = dirpath / name
    path.write_text(f"---\n{frontmatter}---\n\n{body}", encoding="utf-8")
    return path


@pytest.fixture()
def bundle(tmp_path: Path) -> Path:
    d = tmp_path / "insights"
    d.mkdir()
    return d


def test_valid_record_has_no_errors(bundle: Path):
    _write(bundle, "HUB-FB-20260822-a1b2c3.md", _VALID_FRONTMATTER)
    result = fr.validate_feedback_bundle(bundle)
    assert result.errors == []
    assert len(result.records) == 1
    assert result.records[0].area == "party"


def test_absent_bundle_is_empty_and_passing(tmp_path: Path):
    result = fr.validate_feedback_bundle(tmp_path / "nope")
    assert result.records == []
    assert result.errors == []


def test_reserved_and_template_files_are_not_records(bundle: Path):
    (bundle / "README.md").write_text("# readme", encoding="utf-8")
    (bundle / "index.md").write_text("# index", encoding="utf-8")
    (bundle / "FEEDBACK-template.md.template").write_text("---\ntype: x\n---\n", encoding="utf-8")
    _write(bundle, "HUB-FB-20260822-a1b2c3.md", _VALID_FRONTMATTER)
    result = fr.validate_feedback_bundle(bundle)
    assert len(result.records) == 1


def test_missing_sources_is_a_warning_not_an_error(bundle: Path):
    """Unlike decisions, feedback never requires evidence -- it's a warning only."""
    _write(bundle, "HUB-FB-20260822-a1b2c3.md", _VALID_FRONTMATTER)
    result = fr.validate_feedback_bundle(bundle)
    assert result.errors == []
    assert any(w.code == "no_sources" for w in result.warnings)


def test_invalid_status_is_an_error(bundle: Path):
    fm = _VALID_FRONTMATTER.replace("status: open", "status: something-else")
    _write(bundle, "HUB-FB-20260822-a1b2c3.md", fm)
    result = fr.validate_feedback_bundle(bundle)
    assert any(e.code == "invalid_status" for e in result.errors)


def test_id_filename_mismatch_is_an_error(bundle: Path):
    _write(bundle, "HUB-FB-20260822-wrong.md", _VALID_FRONTMATTER)
    result = fr.validate_feedback_bundle(bundle)
    assert any(e.code == "id_filename_mismatch" for e in result.errors)


def test_duplicate_id_is_an_error(bundle: Path):
    _write(bundle, "HUB-FB-20260822-a1b2c3.md", _VALID_FRONTMATTER)
    # Same id as above, different filename -- id_filename_mismatch fires too, but
    # duplicate_id must also be reported.
    _write(bundle, "HUB-FB-20260822-dup.md", _VALID_FRONTMATTER)
    result = fr.validate_feedback_bundle(bundle)
    assert any(e.code == "duplicate_id" for e in result.errors)


def test_missing_type_is_okf_conformance_error(bundle: Path):
    fm = _VALID_FRONTMATTER.replace("type: Modeling Feedback\n", "")
    _write(bundle, "HUB-FB-20260822-a1b2c3.md", fm)
    result = fr.validate_feedback_bundle(bundle)
    assert any(e.code == "missing_type" and e.category == "okf_conformance" for e in result.errors)


def test_status_vocabulary_is_open_and_resolved_only():
    """Feedback deliberately has no materiality/lifecycle state machine (unlike decisions)."""
    assert fr.VALID_STATUS == frozenset({"open", "resolved"})


def test_render_new_record_round_trips_through_validation(tmp_path: Path):
    bundle_dir = tmp_path / "insights"
    bundle_dir.mkdir()
    text = fr.render_new_record(
        record_id="HUB-FB-20260822-fresh",
        title="A title",
        version="9.9.9",
        area="party",
        observation="Something was observed.",
        implication="Maybe change the binding.",
        sources=("integration/sources/crm/customers.ttl",),
    )
    (bundle_dir / "HUB-FB-20260822-fresh.md").write_text(text, encoding="utf-8")
    result = fr.validate_feedback_bundle(bundle_dir)
    assert result.errors == []
    record = result.records[0]
    assert record.status == "open"
    assert "Something was observed." in record.body
    assert "Maybe change the binding." in record.body


def test_resolve_record_sets_status_and_resolution_section():
    text = fr.render_new_record(
        record_id="HUB-FB-20260822-r1", title="T", version="9.9.9", observation="Obs."
    )
    resolved = fr.resolve_record(text, note="Confirmed with business.", resolved_at="2026-08-22T12:00:00Z")
    fm, body, err = fr.split_frontmatter(resolved)
    assert err is None
    assert fm["status"] == "resolved"
    assert "Confirmed with business." in body
    assert "2026-08-22T12:00:00Z" in body
    # The other sections must survive untouched.
    assert "Obs." in body
    assert "# Observation" in body
    assert "# Open follow-ups" in body


def test_resolve_record_rejects_an_already_resolved_record():
    text = fr.render_new_record(
        record_id="HUB-FB-20260822-r2", title="T", version="9.9.9", observation="Obs."
    )
    resolved = fr.resolve_record(text, note="First note.", resolved_at="2026-08-22T12:00:00Z")
    with pytest.raises(ValueError, match="already resolved"):
        fr.resolve_record(resolved, note="Second note.", resolved_at="2026-08-22T13:00:00Z")


def test_resolve_record_does_not_introduce_a_stray_leading_blank_line():
    """split_frontmatter/serialize_record round-tripping is easy to get wrong here --
    the closing '---' fence's own blank-line separator can double up if the parsed
    body isn't re-normalized before being re-serialized (see resolve_record's
    docstring-adjacent comment for why this can't be fixed in the shared helpers
    without touching decision_records.py too)."""
    text = fr.render_new_record(
        record_id="HUB-FB-20260822-r3", title="T", version="9.9.9", observation="Obs."
    )
    resolved = fr.resolve_record(text, note="Note.", resolved_at="2026-08-22T12:00:00Z")
    assert "---\n\n# Observation" in resolved
    assert "---\n\n\n# Observation" not in resolved


def test_build_index_markdown_lists_area_and_status(tmp_path: Path):
    bundle_dir = tmp_path / "insights"
    bundle_dir.mkdir()
    _write(bundle_dir, "HUB-FB-20260822-a1b2c3.md", _VALID_FRONTMATTER)
    result = fr.validate_feedback_bundle(bundle_dir)
    index = fr.build_index_markdown(result.records)
    assert "HUB-FB-20260822-a1b2c3" in index
    assert "party" in index
    assert "open" in index
