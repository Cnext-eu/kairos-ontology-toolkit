# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-193: the profiling class catalog is scoped to the resolved accelerator.

Before this, ``build_class_catalog`` offered every module the whole installed
reference-models package maps as an anchor candidate — including modules no
accelerator domain imports, directly or transitively (issue #558: ~400 FIBO
classes as UNOWNED noise in a logistics run). Pins: a module the accelerator
never reaches is excluded outright (not merely marked UNOWNED); a module
reached only via ``owl:imports`` from an accelerator-declared module remains
visible (transitivity is unaffected — only the seed set narrows); and an
unresolved accelerator keeps the unrestricted legacy behaviour rather than
returning an empty catalog.
"""

from __future__ import annotations

from pathlib import Path

from kairos_ontology.core.anchor_tables import build_class_catalog
from kairos_ontology.core.class_anchoring import read_reference_terms

OWNED = "https://ref.test/ont/owned"
FOUNDATION = "https://ref.test/ont/foundation"
UNRELATED = "https://ref.test/ont/unrelated"


def _write_ttl(path: Path, ns: str, class_name: str, imports: str | None = None) -> None:
    imp_line = f"owl:imports <{imports}#> ;" if imports else ""
    path.write_text(
        f"""
        @prefix : <{ns}#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        <{ns}> a owl:Ontology ; rdfs:label "{class_name} ns"@en ; {imp_line}
            owl:versionInfo "1" .

        :{class_name} a owl:Class ; rdfs:label "{class_name}"@en ;
            rdfs:comment "{class_name} class."@en .
        """,
        encoding="utf-8",
    )


def _build_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """(catalog_path, ref_models_dir) with owned/foundation/unrelated modules.

    ``owned`` is the accelerator's own declared import; it ``owl:imports``
    ``foundation`` (transitive, not independently declared); ``unrelated`` is
    mapped in the SAME catalog but reachable from neither.
    """
    hub = tmp_path / "hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    ref_models = tmp_path / "ontology-reference-models"
    modules_dir = ref_models / "modules"
    modules_dir.mkdir(parents=True)
    _write_ttl(modules_dir / "owned.ttl", OWNED, "OwnedClass", imports=FOUNDATION)
    _write_ttl(modules_dir / "foundation.ttl", FOUNDATION, "FoundationClass")
    _write_ttl(modules_dir / "unrelated.ttl", UNRELATED, "UnrelatedClass")

    catalog = hub / "catalog-v001.xml"
    catalog.write_text(
        "\n".join([
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">',
            f'  <uri name="{OWNED}#" uri="{modules_dir / "owned.ttl"}"/>',
            f'  <uri name="{FOUNDATION}#" uri="{modules_dir / "foundation.ttl"}"/>',
            f'  <uri name="{UNRELATED}#" uri="{modules_dir / "unrelated.ttl"}"/>',
            "</catalog>", "",
        ]),
        encoding="utf-8",
    )

    blueprint = ref_models / "accelerator-packs" / "logistics" / "client-hub-blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "data-domains.yaml").write_text(
        f"""
        schema_version: "1.0"
        groups:
          - id: g
            name: G
            domains:
              - id: booking
                name: Booking
                imports:
                  - uri: "{OWNED}#"
                    module: "Owned"
        """,
        encoding="utf-8",
    )
    return catalog, ref_models


class TestBuildClassCatalogScoping:
    def test_module_outside_the_accelerator_closure_is_excluded_outright(self, tmp_path):
        catalog, ref_models = _build_fixture(tmp_path)
        result = build_class_catalog(catalog, ref_models, "logistics")
        assert "UnrelatedClass" not in result.text
        assert "UnrelatedClass" not in result.index

    def test_directly_owned_module_appears_and_is_marked_owned(self, tmp_path):
        catalog, ref_models = _build_fixture(tmp_path)
        result = build_class_catalog(catalog, ref_models, "logistics")
        assert "owned by domain 'booking'" in result.text
        assert "OwnedClass" in result.index

    def test_transitively_imported_module_remains_visible_as_unowned(self, tmp_path):
        """Scoping narrows the SEED set; each seed's own owl:imports closure
        still resolves in full — a foundation module reached only via import
        from an accelerator-declared module is not silently dropped."""
        catalog, ref_models = _build_fixture(tmp_path)
        result = build_class_catalog(catalog, ref_models, "logistics")
        assert "FoundationClass" in result.index
        assert "FoundationClass [UNOWNED]" in result.text

    def test_unresolved_accelerator_keeps_the_unrestricted_legacy_behaviour(self, tmp_path):
        catalog, ref_models = _build_fixture(tmp_path)
        result = build_class_catalog(catalog, ref_models, "no-such-accelerator")
        assert "UnrelatedClass" in result.index, (
            "an accelerator name that resolves to nothing must not silently "
            "empty the catalog — that regresses to worse than the bug"
        )

    def test_no_ref_models_dir_keeps_the_unrestricted_legacy_behaviour(self, tmp_path):
        catalog, _ref_models = _build_fixture(tmp_path)
        result = build_class_catalog(catalog, None, "logistics")
        assert "UnrelatedClass" in result.index


class TestReadReferenceTermsModuleScope:
    def test_module_scope_none_is_unrestricted(self, tmp_path):
        catalog, _ = _build_fixture(tmp_path)
        names = {t.name for t in read_reference_terms(catalog)}
        assert {"OwnedClass", "FoundationClass", "UnrelatedClass"} <= names

    def test_module_scope_filters_to_the_given_seed_set(self, tmp_path):
        catalog, _ = _build_fixture(tmp_path)
        names = {t.name for t in read_reference_terms(catalog, module_scope={OWNED + "#"})}
        assert "OwnedClass" in names
        assert "FoundationClass" in names, "the seed's own import closure still resolves"
        assert "UnrelatedClass" not in names

    def test_module_scope_normalizes_trailing_hash_and_slash(self, tmp_path):
        catalog, _ = _build_fixture(tmp_path)
        bare = {t.name for t in read_reference_terms(catalog, module_scope={OWNED})}
        hashed = {t.name for t in read_reference_terms(catalog, module_scope={OWNED + "#"})}
        assert bare == hashed

    def test_empty_module_scope_yields_no_terms(self, tmp_path):
        catalog, _ = _build_fixture(tmp_path)
        assert read_reference_terms(catalog, module_scope=set()) == []