# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for scripts/collect_changelog.py (changelog.d fragment assembly)."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import collect_changelog  # noqa: E402


def _fragment(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def test_readme_is_documentation_not_a_fragment(tmp_path):
    _fragment(tmp_path, "README.md", "### Fixed\n- docs\n")
    _fragment(tmp_path, "775-thing.md", "### Fixed\n- real\n")
    assert [p.name for p in collect_changelog.fragment_paths(tmp_path)] == ["775-thing.md"]


def test_missing_directory_yields_no_fragments(tmp_path):
    assert collect_changelog.fragment_paths(tmp_path / "absent") == []


def test_parse_splits_multiple_sections():
    parsed = collect_changelog.parse_fragment("### Added\n- a\n\n### Fixed\n- b\n")
    assert parsed == {"Added": ["- a"], "Fixed": ["- b"]}


def test_fragment_without_a_heading_is_rejected():
    """No sensible default section exists, and guessing puts the entry in the wrong place."""
    with pytest.raises(ValueError, match="no '### Section' heading"):
        collect_changelog.parse_fragment("- forgot the heading\n")


def test_empty_section_is_rejected():
    with pytest.raises(ValueError, match="no content"):
        collect_changelog.parse_fragment("### Fixed\n\n")


def test_assemble_names_the_offending_file(tmp_path):
    _fragment(tmp_path, "700-bad.md", "- no heading\n")
    with pytest.raises(ValueError, match="700-bad.md"):
        collect_changelog.assemble(collect_changelog.fragment_paths(tmp_path))


def test_sections_are_ordered_and_merged_across_fragments(tmp_path):
    _fragment(tmp_path, "002-b.md", "### Fixed\n- second fix\n")
    _fragment(tmp_path, "001-a.md", "### Fixed\n- first fix\n\n### Added\n- a feature\n")
    section = collect_changelog.assemble(collect_changelog.fragment_paths(tmp_path))
    assert section == (
        "### Added\n- a feature\n\n### Fixed\n- first fix\n- second fix"
    )


def test_qualified_heading_sorts_with_its_base_word(tmp_path):
    _fragment(tmp_path, "001-a.md", "### Removed (BREAKING)\n- gone\n")
    _fragment(tmp_path, "002-b.md", "### Added\n- new\n")
    section = collect_changelog.assemble(collect_changelog.fragment_paths(tmp_path))
    assert section.index("### Added") < section.index("### Removed (BREAKING)")


def test_unknown_section_is_kept_at_the_end_never_dropped(tmp_path):
    """Losing an authored entry silently is the one failure mode worth ruling out."""
    _fragment(tmp_path, "001-a.md", "### Wildcard\n- unusual\n")
    _fragment(tmp_path, "002-b.md", "### Fixed\n- ordinary\n")
    section = collect_changelog.assemble(collect_changelog.fragment_paths(tmp_path))
    assert section.index("### Fixed") < section.index("### Wildcard")
    assert "- unusual" in section


def test_apply_inserts_under_unreleased_and_keeps_what_was_there(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Performance\n- existing\n\n## [5.17.0]\n- old\n",
        encoding="utf-8",
    )
    merged = collect_changelog.apply("### Fixed\n- new", changelog)
    assert "## [Unreleased]\n\n### Fixed\n- new\n\n### Performance\n- existing" in merged
    assert merged.index("### Fixed") < merged.index("## [5.17.0]")
    assert "- old" in merged


def test_apply_requires_an_unreleased_heading(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [5.17.0]\n- old\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unreleased"):
        collect_changelog.apply("### Fixed\n- new", changelog)


def test_the_real_changelog_still_has_the_anchor_the_script_needs():
    """A rename of `## [Unreleased]` must fail here, not at release time."""
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert collect_changelog.UNRELEASED in text


def test_main_without_fragments_is_a_no_op(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(collect_changelog, "FRAGMENTS", tmp_path / "absent")
    assert collect_changelog.main([]) == 0
    assert "nothing to collect" in capsys.readouterr().out


def test_main_dry_run_prints_without_touching_anything(tmp_path, monkeypatch, capsys):
    fragments = tmp_path / "changelog.d"
    _fragment(fragments, "001-a.md", "### Fixed\n- a fix\n")
    monkeypatch.setattr(collect_changelog, "FRAGMENTS", fragments)
    assert collect_changelog.main([]) == 0
    assert "- a fix" in capsys.readouterr().out
    assert (fragments / "001-a.md").is_file()


def test_main_apply_writes_lf_and_removes_the_fragments(tmp_path, monkeypatch):
    fragments = tmp_path / "changelog.d"
    _fragment(fragments, "001-a.md", "### Fixed\n- a fix\n")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [Unreleased]\n\n## [5.17.0]\n", encoding="utf-8")
    monkeypatch.setattr(collect_changelog, "FRAGMENTS", fragments)
    monkeypatch.setattr(collect_changelog, "CHANGELOG", changelog)

    assert collect_changelog.main(["--apply"]) == 0

    assert not (fragments / "001-a.md").exists()
    # LF, not CRLF: autocrlf=false and no .gitattributes, so a translated rewrite would
    # show up as a whole-file whitespace diff.
    raw = changelog.read_bytes()
    assert b"\r\n" not in raw
    assert b"- a fix" in raw


def test_main_reports_a_bad_fragment_instead_of_writing(tmp_path, monkeypatch, capsys):
    fragments = tmp_path / "changelog.d"
    _fragment(fragments, "001-a.md", "- no heading\n")
    monkeypatch.setattr(collect_changelog, "FRAGMENTS", fragments)
    assert collect_changelog.main(["--apply"]) == 1
    assert "001-a.md" in capsys.readouterr().err
