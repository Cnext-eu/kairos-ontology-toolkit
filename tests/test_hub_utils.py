# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for hub_utils.find_hub_root()."""

from kairos_ontology.core.hub_utils import find_hub_root, find_managed_root


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
        """ontology-hub/ with just one marker dir (output/) → detected."""
        hub = tmp_path / "ontology-hub"
        (hub / "output").mkdir(parents=True)
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


_MANAGED_INSTRUCTIONS = (
    "<!-- kairos-ontology-toolkit:managed v1.0.0 -->\n# Copilot instructions\n"
)


def _make_pin_hub(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[tool.kairos]\nchannel = "stable"\n', encoding="utf-8"
    )


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
