# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for hub_utils.find_hub_root()."""

from pathlib import Path

from kairos_ontology.core.hub_utils import (
    body_is_unedited_template,
    find_hub_root,
    find_managed_root,
    is_scaffold_placeholder_text,
    placeholder_fields,
    publish_root,
    resolve_hub_output_dir,
    strip_doubled_hub_segment,
    HUB_DIRNAME,
)


class TestPublishRoot:
    """Tests for publish_root() sibling resolution."""

    def test_sibling_of_hub(self):
        """publish_root returns a sibling folder next to the hub."""
        hub = Path("/repo/ontology-hub")
        assert publish_root(hub) == Path("/repo/ontology-hub-publish")

    def test_uses_literal_name_not_hub_name(self):
        """The publish folder name is literal, not derived from the hub folder."""
        hub = Path("/repo/custom-hub-name")
        assert publish_root(hub).name == "ontology-hub-publish"


class TestStripDoubledHubSegment:
    """Tests for strip_doubled_hub_segment() — prevents path doubling (#462, #466)."""

    def test_strips_leading_hub_dirname(self, tmp_path):
        """A repo-root-relative path starting with 'ontology-hub/' gets the prefix stripped."""
        result = strip_doubled_hub_segment(
            Path("ontology-hub/integration/discovery/foo.yaml"), tmp_path
        )
        assert result == Path("integration/discovery/foo.yaml")

    def test_strips_leading_hub_dirname_from_string(self, tmp_path):
        result = strip_doubled_hub_segment(
            "ontology-hub/integration/discovery/foo.yaml", tmp_path
        )
        assert result == Path("integration/discovery/foo.yaml")

    def test_no_strip_when_first_segment_is_not_hub_dirname(self, tmp_path):
        """A hub-root-relative path (no 'ontology-hub' prefix) is returned as-is."""
        result = strip_doubled_hub_segment(
            Path("integration/discovery/foo.yaml"), tmp_path
        )
        assert result == Path("integration/discovery/foo.yaml")

    def test_no_strip_for_unrelated_first_segment(self, tmp_path):
        result = strip_doubled_hub_segment(
            Path("ontology-reference-models/foo.ttl"), tmp_path
        )
        assert result == Path("ontology-reference-models/foo.ttl")

    def test_single_segment_path_unchanged(self, tmp_path):
        result = strip_doubled_hub_segment(Path("foo.yaml"), tmp_path)
        assert result == Path("foo.yaml")

    def test_absolute_path_unchanged(self, tmp_path):
        """Absolute paths should never be modified."""
        result = strip_doubled_hub_segment(Path("/abs/path/foo.yaml"), tmp_path)
        assert result == Path("/abs/path/foo.yaml")

    def test_hub_dirname_constant_is_ontology_hub(self):
        assert HUB_DIRNAME == "ontology-hub"


class TestFindHubRoot:
    """Tests for find_hub_root() hub-root detection."""

    def test_detects_ontology_hub_with_model_ontologies(self, tmp_path):
        """ontology-hub/model/ontologies/ exists → returns ontology-hub/."""
        hub = tmp_path / "ontology-hub"
        (hub / "model" / "ontologies").mkdir(parents=True)
        assert find_hub_root(tmp_path) == hub

    def test_detects_cwd_as_hub_root(self, tmp_path):
        """CWD itself has model/ontologies/ → returns CWD."""
        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        assert find_hub_root(tmp_path) == tmp_path

    def test_ontology_hub_takes_precedence_over_cwd(self, tmp_path):
        """When both exist, ontology-hub/ wins over CWD."""
        hub = tmp_path / "ontology-hub"
        (hub / "model" / "ontologies").mkdir(parents=True)
        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        assert find_hub_root(tmp_path) == hub

    def test_freshly_scaffolded_hub_with_marker(self, tmp_path):
        """ontology-hub/ exists with model/ dir but no model/ontologies/ → detected."""
        hub = tmp_path / "ontology-hub"
        (hub / "model").mkdir(parents=True)
        (hub / "integration").mkdir(parents=True)
        assert find_hub_root(tmp_path) == hub

    def test_freshly_scaffolded_hub_single_marker(self, tmp_path):
        """ontology-hub/ with just one marker dir (integration/) → detected."""
        hub = tmp_path / "ontology-hub"
        (hub / "integration").mkdir(parents=True)
        assert find_hub_root(tmp_path) == hub

    def test_empty_ontology_hub_ignored(self, tmp_path):
        """Empty ontology-hub/ without marker dirs → returns None."""
        (tmp_path / "ontology-hub").mkdir()
        assert find_hub_root(tmp_path) is None

    def test_no_hub_found(self, tmp_path):
        """No hub-like structure → returns None."""
        assert find_hub_root(tmp_path) is None

    def test_require_model_rejects_fresh_hub(self, tmp_path):
        """require_model=True skips the fallback for freshly scaffolded hubs."""
        hub = tmp_path / "ontology-hub"
        (hub / "model").mkdir(parents=True)
        (hub / "integration").mkdir(parents=True)
        assert find_hub_root(tmp_path, require_model=True) is None

    def test_require_model_accepts_initialized_hub(self, tmp_path):
        """require_model=True accepts hub with model/ontologies/."""
        hub = tmp_path / "ontology-hub"
        (hub / "model" / "ontologies").mkdir(parents=True)
        assert find_hub_root(tmp_path, require_model=True) == hub

    def test_defaults_to_cwd(self, tmp_path, monkeypatch):
        """When cwd is None, uses Path.cwd()."""
        hub = tmp_path / "ontology-hub"
        (hub / "model" / "ontologies").mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        assert find_hub_root() == hub


_MANAGED_INSTRUCTIONS = "<!-- kairos-ontology-toolkit:managed v1.0.0 -->\n# Copilot instructions\n"


def _make_pin_hub(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[tool.kairos]\nchannel = "stable"\n', encoding="utf-8")


def _make_marker_hub(root):
    gh = root / ".github"
    gh.mkdir(parents=True, exist_ok=True)
    (gh / "copilot-instructions.md").write_text(_MANAGED_INSTRUCTIONS, encoding="utf-8")


class TestFindManagedRoot:
    """Tests for find_managed_root() upward-walking detection."""

    def test_detects_pyproject_pin_anchor(self, tmp_path):
        _make_pin_hub(tmp_path)
        assert find_managed_root(tmp_path) == tmp_path.resolve()

    def test_detects_dependency_pin_anchor(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            'dependencies = ["kairos-ontology-toolkit @ https://x/y.whl"]\n',
            encoding="utf-8",
        )
        assert find_managed_root(tmp_path) == tmp_path.resolve()

    def test_detects_github_marker_anchor(self, tmp_path):
        _make_marker_hub(tmp_path)
        assert find_managed_root(tmp_path) == tmp_path.resolve()

    def test_ignores_unmarked_github_instructions(self, tmp_path):
        gh = tmp_path / ".github"
        gh.mkdir(parents=True)
        (gh / "copilot-instructions.md").write_text("# nothing managed\n", encoding="utf-8")
        assert find_managed_root(tmp_path) is None

    def test_detects_dataplatform_anchor(self, tmp_path):
        (tmp_path / "dbt_project.yml").write_text("name: dp\n", encoding="utf-8")
        (tmp_path / ".github").mkdir()
        assert find_managed_root(tmp_path) == tmp_path.resolve()

    def test_walks_up_from_subdirectory(self, tmp_path):
        """Called from a content subdir → returns the hub root above it."""
        _make_pin_hub(tmp_path)
        subdir = tmp_path / "ontology-hub" / "model"
        subdir.mkdir(parents=True)
        assert find_managed_root(subdir) == tmp_path.resolve()

    def test_returns_none_for_non_hub(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "unrelated"\n', encoding="utf-8"
        )
        assert find_managed_root(tmp_path) is None

    def test_defaults_to_cwd(self, tmp_path, monkeypatch):
        _make_pin_hub(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert find_managed_root() == tmp_path.resolve()


class TestResolveHubOutputDir:
    """Tests for resolve_hub_output_dir() — the shared "where do I write?" helper (#296)."""

    def test_resolves_against_ontology_hub_from_repo_root(self, tmp_path):
        hub = tmp_path / "ontology-hub"
        (hub / "model" / "ontologies").mkdir(parents=True)

        output, root = resolve_hub_output_dir("integration/discovery/bi", cwd=tmp_path)

        assert output == hub / "integration" / "discovery" / "bi"
        assert root == hub

    def test_resolves_when_cwd_is_the_hub_root(self, tmp_path):
        (tmp_path / "model" / "ontologies").mkdir(parents=True)

        output, root = resolve_hub_output_dir("integration/sources/erp", cwd=tmp_path)

        assert output == tmp_path / "integration" / "sources" / "erp"
        assert root == tmp_path

    def test_walks_up_from_a_deep_subdirectory(self, tmp_path):
        """Without the ancestor pass this returns a doubly-nested relative path."""
        hub = tmp_path / "ontology-hub"
        (hub / "model" / "ontologies").mkdir(parents=True)
        deep = hub / "integration" / "discovery"
        deep.mkdir(parents=True)

        output, root = resolve_hub_output_dir("integration/discovery/bi", cwd=deep)

        assert output == hub / "integration" / "discovery" / "bi"
        assert root == hub

    def test_ancestor_pass_requires_model_ontologies(self, tmp_path):
        """A bare ontology-hub/ name several levels up is too weak to redirect writes."""
        hub = tmp_path / "ontology-hub"
        (hub / "integration").mkdir(parents=True)
        deep = hub / "integration" / "nested"
        deep.mkdir(parents=True)

        output, root = resolve_hub_output_dir("integration/discovery/bi", cwd=deep)

        assert root is None
        assert output == Path("integration/discovery/bi")

    def test_no_hub_returns_the_relative_path_and_none(self, tmp_path):
        output, root = resolve_hub_output_dir("integration/discovery/bi", cwd=tmp_path)

        assert root is None
        assert output == Path("integration/discovery/bi")

    def test_accepts_a_path_or_a_string(self, tmp_path):
        (tmp_path / "model" / "ontologies").mkdir(parents=True)

        from_str, _ = resolve_hub_output_dir("integration/discovery/bi", cwd=tmp_path)
        from_path, _ = resolve_hub_output_dir(Path("integration/discovery/bi"), cwd=tmp_path)

        assert from_str == from_path

    def test_defaults_to_cwd(self, tmp_path, monkeypatch):
        hub = tmp_path / "ontology-hub"
        (hub / "model" / "ontologies").mkdir(parents=True)
        monkeypatch.chdir(tmp_path)

        output, root = resolve_hub_output_dir("integration/discovery/bi")

        assert root == hub
        assert output == hub / "integration" / "discovery" / "bi"


class TestIsScaffoldPlaceholderText:
    """Tests for is_scaffold_placeholder_text() (D2, #416)."""

    def test_angle_bracket_stub_is_placeholder(self):
        assert is_scaffold_placeholder_text("<option>") is True

    def test_confirm_sentinel_is_placeholder(self):
        """Subsumes the `<CONFIRM_...>` sentinel family used by scaffold_staging.py
        / scaffold_binding.py -- an angle-bracket stub like any other."""
        assert is_scaffold_placeholder_text("<CONFIRM_TARGET_CLASS>") is True

    def test_bare_todo_is_placeholder(self):
        assert is_scaffold_placeholder_text("TODO") is True

    def test_bare_tbd_is_placeholder(self):
        assert is_scaffold_placeholder_text("TBD") is True

    def test_todo_within_sentence_is_placeholder(self):
        assert is_scaffold_placeholder_text("TODO: fill this in") is True

    def test_real_prose_is_not_placeholder(self):
        assert is_scaffold_placeholder_text("A short human-authored summary.") is False

    def test_empty_string_is_not_placeholder(self):
        """Blank is a separate concern (missing), not itself a placeholder."""
        assert is_scaffold_placeholder_text("") is False
        assert is_scaffold_placeholder_text("   ") is False

    def test_non_string_is_not_placeholder(self):
        assert is_scaffold_placeholder_text(None) is False
        assert is_scaffold_placeholder_text([]) is False

    def test_word_containing_todo_as_substring_is_not_flagged(self):
        """`_WORD_RE` tokenizes on word boundaries, so this must not
        false-positive on a real word merely containing the letters."""
        assert is_scaffold_placeholder_text("Autodocumentation pipeline") is False


class TestPlaceholderFields:
    """Tests for placeholder_fields() (D2, #416)."""

    def test_missing_key_is_unfilled(self):
        assert placeholder_fields({}, required=("summary",)) == ["summary"]

    def test_none_value_is_unfilled(self):
        assert placeholder_fields({"summary": None}, required=("summary",)) == ["summary"]

    def test_blank_string_is_unfilled(self):
        assert placeholder_fields({"summary": "   "}, required=("summary",)) == ["summary"]

    def test_placeholder_string_is_unfilled(self):
        assert placeholder_fields({"summary": "TODO"}, required=("summary",)) == ["summary"]

    def test_empty_list_is_unfilled(self):
        assert placeholder_fields({"terms": []}, required=("terms",)) == ["terms"]

    def test_real_value_is_filled(self):
        assert placeholder_fields({"summary": "Real content."}, required=("summary",)) == []

    def test_non_mapping_reports_all_required_as_unfilled(self):
        assert placeholder_fields(None, required=("a", "b")) == ["a", "b"]

    def test_only_requested_keys_are_checked(self):
        assert placeholder_fields({"a": "TODO", "b": "fine"}, required=("b",)) == []


class TestBodyIsUneditedTemplate:
    """Tests for body_is_unedited_template() (D2, #416)."""

    def test_identical_body_is_unedited(self):
        template = "# Context\n\n<fill in>\n"
        assert body_is_unedited_template(template, template) is True

    def test_whitespace_only_difference_is_still_unedited(self):
        template = "# Context\n\n<fill in>\n"
        assert body_is_unedited_template("  " + template + "\n\n", template) is True

    def test_edited_body_is_not_unedited(self):
        template = "# Context\n\n<fill in>\n"
        edited = "# Context\n\nReal, authored content.\n"
        assert body_is_unedited_template(edited, template) is False
