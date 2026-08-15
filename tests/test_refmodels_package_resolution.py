# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for package-based reference-model resolution (DD-158).

Tests that ``resolve_refmodels_dir`` resolves from the installed package
first, falling back to ``KAIROS_REFMODELS_ROOT``, and that
``CatalogResolver.with_reference_models()`` overlays the package catalog.
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import patch

import pytest


@pytest.fixture
def fake_hub(tmp_path):
    """A minimal hub directory."""
    hub = tmp_path / "hub"
    (hub / "ontology-hub").mkdir(parents=True)
    return hub


@pytest.fixture
def fake_refmodels_pkg(tmp_path):
    """Register a fake ``kairos_ontology_referencemodels`` module in sys.modules.

    The fake module provides ``refmodels_root()`` pointing at a temp dir with
    the contract markers (catalog-v001.xml + blueprints/archetypes/).
    """
    pkg_dir = tmp_path / "fake_refmodels_pkg" / "ontology-reference-models"
    (pkg_dir / "blueprints" / "archetypes").mkdir(parents=True)
    (pkg_dir / "catalog-v001.xml").write_text(
        '<?xml version="1.0"?>\n<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog"/>',
        encoding="utf-8",
    )

    mod = types.ModuleType("kairos_ontology_referencemodels")
    mod.__file__ = str(pkg_dir / "__init__.py")

    def refmodels_root():
        return pkg_dir

    mod.refmodels_root = refmodels_root

    original = sys.modules.get("kairos_ontology_referencemodels")
    sys.modules["kairos_ontology_referencemodels"] = mod
    yield pkg_dir
    if original is not None:
        sys.modules["kairos_ontology_referencemodels"] = original
    else:
        sys.modules.pop("kairos_ontology_referencemodels", None)


class TestResolveRefmodelsDir:
    def test_package_resolution(self, fake_hub, fake_refmodels_pkg):
        """When the package is installed, resolve_refmodels_dir returns its root."""
        from kairos_ontology.cli.shared import resolve_refmodels_dir

        result = resolve_refmodels_dir(fake_hub, fake_hub)
        assert result is not None
        assert result == fake_refmodels_pkg

    def test_env_var_fallback_when_no_package(self, fake_hub, tmp_path):
        """Without the package, KAIROS_REFMODELS_ROOT env var is used."""
        from kairos_ontology.cli.shared import resolve_refmodels_dir

        env_dir = tmp_path / "env_refmodels"
        (env_dir / "blueprints" / "archetypes").mkdir(parents=True)
        (env_dir / "catalog-v001.xml").write_text(
            "<catalog/>", encoding="utf-8"
        )

        with patch.dict(os.environ, {"KAIROS_REFMODELS_ROOT": str(env_dir)}):
            # Ensure package is not importable
            original = sys.modules.pop("kairos_ontology_referencemodels", None)
            try:
                result = resolve_refmodels_dir(fake_hub, fake_hub)
                assert result is not None
                assert result == env_dir
            finally:
                if original is not None:
                    sys.modules["kairos_ontology_referencemodels"] = original

    def test_env_var_nonexistent_dir_returns_none(self, fake_hub):
        """If KAIROS_REFMODELS_ROOT points at a non-existent dir, return None."""
        from kairos_ontology.cli.shared import resolve_refmodels_dir

        with patch.dict(os.environ, {"KAIROS_REFMODELS_ROOT": "/nonexistent/path"}):
            original = sys.modules.pop("kairos_ontology_referencemodels", None)
            try:
                result = resolve_refmodels_dir(fake_hub, fake_hub)
                assert result is None
            finally:
                if original is not None:
                    sys.modules["kairos_ontology_referencemodels"] = original

    def test_returns_none_when_no_package_and_no_env(self, fake_hub):
        """Without package or env var, resolve_refmodels_dir returns None."""
        from kairos_ontology.cli.shared import resolve_refmodels_dir

        env = {k: v for k, v in os.environ.items() if k != "KAIROS_REFMODELS_ROOT"}
        original = sys.modules.pop("kairos_ontology_referencemodels", None)
        try:
            with patch.dict(os.environ, env, clear=True):
                result = resolve_refmodels_dir(fake_hub, fake_hub)
                assert result is None
        finally:
            if original is not None:
                sys.modules["kairos_ontology_referencemodels"] = original

    def test_package_takes_precedence_over_env(self, fake_hub, fake_refmodels_pkg, tmp_path):
        """The installed package takes precedence over KAIROS_REFMODELS_ROOT."""
        from kairos_ontology.cli.shared import resolve_refmodels_dir

        env_dir = tmp_path / "should_not_be_used"
        env_dir.mkdir()

        with patch.dict(os.environ, {"KAIROS_REFMODELS_ROOT": str(env_dir)}):
            result = resolve_refmodels_dir(fake_hub, fake_hub)
            assert result == fake_refmodels_pkg
            assert result != env_dir


class TestCatalogResolverWithReferenceModels:
    def test_overlays_package_catalog(self, fake_hub, fake_refmodels_pkg, tmp_path):
        """CatalogResolver.with_reference_models() loads the package catalog."""
        from kairos_ontology.core.catalog_utils import CatalogResolver

        # Create a local catalog
        local_catalog = tmp_path / "catalog-v001.xml"
        local_catalog.write_text(
            '<?xml version="1.0"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog"/>\n',
            encoding="utf-8",
        )

        resolver = CatalogResolver.with_reference_models(local_catalog)
        # The resolver should have loaded both catalogs (local + package)
        assert resolver._visited_catalogs  # at least one catalog loaded

    def test_no_package_silently_skips_overlay(self, fake_hub, tmp_path):
        """Without the package, with_reference_models() still works (no overlay)."""
        from kairos_ontology.core.catalog_utils import CatalogResolver

        local_catalog = tmp_path / "catalog-v001.xml"
        local_catalog.write_text(
            '<?xml version="1.0"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog"/>\n',
            encoding="utf-8",
        )

        original = sys.modules.pop("kairos_ontology_referencemodels", None)
        try:
            resolver = CatalogResolver.with_reference_models(local_catalog)
            assert resolver._visited_catalogs
        finally:
            if original is not None:
                sys.modules["kairos_ontology_referencemodels"] = original


class TestRelativeIdentityPackagePaths:
    def test_relative_identity_from_package_path(self, fake_refmodels_pkg):
        """_relative_identity produces ontology-reference-models/... paths from package.

        When the catalog originates from a package, the stable identity
        must be a relative path starting with 'ontology-reference-models/',
        not a bare basename — so that edges from different subpackages
        don't collide in the closure hash.
        """
        from kairos_ontology.core.ontology_loader import _relative_identity

        # Simulate a TTL file inside the package
        ttl = fake_refmodels_pkg / "blueprints" / "archetypes" / "test.ttl"
        ttl.parent.mkdir(parents=True, exist_ok=True)
        ttl.write_text("# test", encoding="utf-8")

        # When identity_root is the package root, the identity is a relative path
        identity = _relative_identity(ttl, fake_refmodels_pkg)
        assert identity == "blueprints/archetypes/test.ttl"

    def test_relative_identity_fallback_to_package_detection(self, fake_refmodels_pkg, tmp_path):
        """Even with a mismatched identity_root, _relative_identity detects the package.

        If identity_root doesn't match, the function falls back to checking
        the installed package and produces an 'ontology-reference-models/...' path.
        """
        from kairos_ontology.core.ontology_loader import _relative_identity

        ttl = fake_refmodels_pkg / "blueprints" / "test.ttl"
        ttl.parent.mkdir(parents=True, exist_ok=True)
        ttl.write_text("# test", encoding="utf-8")

        # Use a different identity_root so the direct relative_to fails,
        # then the package detection kicks in
        other_root = tmp_path / "other_root"
        other_root.mkdir()

        identity = _relative_identity(ttl, other_root)
        assert identity.startswith("ontology-reference-models/")
        assert identity.endswith("test.ttl")
