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

    def test_env_var_used_when_set(self, fake_hub, fake_refmodels_pkg, tmp_path):
        """When KAIROS_REFMODELS_ROOT is set, it takes precedence over the package."""
        from kairos_ontology.cli.shared import resolve_refmodels_dir

        env_dir = tmp_path / "env_refmodels"
        (env_dir / "blueprints" / "archetypes").mkdir(parents=True)
        (env_dir / "catalog-v001.xml").write_text(
            "<catalog/>", encoding="utf-8"
        )

        with patch.dict(os.environ, {"KAIROS_REFMODELS_ROOT": str(env_dir)}):
            result = resolve_refmodels_dir(fake_hub, fake_hub)
            assert result is not None
            assert result == env_dir

    def test_env_var_nonexistent_dir_falls_through_to_package(self, fake_hub, fake_refmodels_pkg):
        """If KAIROS_REFMODELS_ROOT points at a non-existent dir, fall through to package."""
        from kairos_ontology.cli.shared import resolve_refmodels_dir

        with patch.dict(os.environ, {"KAIROS_REFMODELS_ROOT": "/nonexistent/path"}):
            result = resolve_refmodels_dir(fake_hub, fake_hub)
            assert result == fake_refmodels_pkg

    def test_package_used_when_no_env_var(self, fake_hub, fake_refmodels_pkg):
        """Without env var but with package installed, resolve_refmodels_dir returns package."""
        from kairos_ontology.cli.shared import resolve_refmodels_dir

        env = {k: v for k, v in os.environ.items() if k != "KAIROS_REFMODELS_ROOT"}
        with patch.dict(os.environ, env, clear=True):
            result = resolve_refmodels_dir(fake_hub, fake_hub)
            assert result == fake_refmodels_pkg

    def test_env_var_takes_precedence_over_package(self, fake_hub, fake_refmodels_pkg, tmp_path):
        """KAIROS_REFMODELS_ROOT takes precedence over the installed package."""
        from kairos_ontology.cli.shared import resolve_refmodels_dir

        env_dir = tmp_path / "env_override"
        (env_dir / "blueprints" / "archetypes").mkdir(parents=True)
        (env_dir / "catalog-v001.xml").write_text(
            "<?xml version='1.0'?>\n<catalog/>\n", encoding="utf-8"
        )

        with patch.dict(os.environ, {"KAIROS_REFMODELS_ROOT": str(env_dir)}):
            result = resolve_refmodels_dir(fake_hub, fake_hub)
            assert result == env_dir
            assert result != fake_refmodels_pkg


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


    # -- overlay precedence (issue #602) ----------------------------------

    @staticmethod
    def _catalog(path, entries):
        lines = [
            '<?xml version="1.0"?>',
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">',
        ]
        lines += [f'  <uri name="{name}" uri="{target}"/>' for name, target in entries]
        lines.append("</catalog>")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_hub_entry_wins_over_a_colliding_overlay_entry(self, tmp_path):
        """DD-158: the overlay is additive-only -- the hub catalog's entries win.

        A hub may deliberately map a reference-model IRI onto its own TTL (the
        acme-hub scenario does exactly this). Loading the overlay last used to
        overwrite that mapping, so the compile silently resolved against different
        bytes than the author asked for, with no diagnostic.
        """
        from kairos_ontology.core.catalog_utils import CatalogResolver

        iri = "https://refmodel.example/ontology/party"
        (tmp_path / "hub").mkdir()
        (tmp_path / "hub" / "mine.ttl").write_text("# hub copy\n", encoding="utf-8")
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "theirs.ttl").write_text("# package copy\n", encoding="utf-8")

        hub = self._catalog(tmp_path / "hub" / "catalog-v001.xml", [(iri, "mine.ttl")])
        pkg = self._catalog(tmp_path / "pkg" / "catalog-v001.xml", [(iri, "theirs.ttl")])

        resolver = CatalogResolver(hub, extra_catalogs=[pkg])
        mine = (tmp_path / "hub" / "mine.ttl").resolve()

        assert resolver.mappings[iri] == mine
        # Every normalized variant must agree; winning the exact lookup but losing
        # the trailing-#/slash ones would be its own bug.
        assert resolver.mappings[iri + "#"] == mine
        assert resolver.mappings[iri + "/"] == mine

    def test_overlay_still_supplies_iris_the_hub_does_not_declare(self, tmp_path):
        """Additive-only must stay additive -- the overlay is the point."""
        from kairos_ontology.core.catalog_utils import CatalogResolver

        (tmp_path / "hub").mkdir()
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "fibo.ttl").write_text("# fibo\n", encoding="utf-8")

        hub = self._catalog(tmp_path / "hub" / "catalog-v001.xml", [])
        pkg = self._catalog(
            tmp_path / "pkg" / "catalog-v001.xml", [("https://ref.example/fibo", "fibo.ttl")]
        )

        resolver = CatalogResolver(hub, extra_catalogs=[pkg])

        assert (
            resolver.mappings["https://ref.example/fibo"]
            == (tmp_path / "pkg" / "fibo.ttl").resolve()
        )


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
