# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for hub_utils.find_hub_root()."""

from kairos_ontology.hub_utils import find_hub_root


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
