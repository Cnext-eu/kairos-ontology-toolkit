# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Catalog resolution testing module."""

import xml.etree.ElementTree as ET
from pathlib import Path

from .catalog_utils import CatalogResolver
from .hub_utils import is_domain_ontology_stem
from .ontology_loader import load_ontology


def _check_catalog_structure(catalog_path: Path) -> bool:
    """Validate catalog entries and domain-ontology coverage.

    Exit-code policy — this returns False (fail the command) only for:
    - Dangling ``<uri>`` entries DECLARED IN THE CATALOG UNDER TEST (the hub
      author owns this file and can fix it).
    - An unparseable catalog file.

    Everything else is advisory (printed, but does not affect the return value):
    - Dangling entries declared in a *chained* catalog reached via
      ``<nextCatalog>`` — e.g. the vendored ``ontology-reference-models`` catalog
      every hub chains to. The hub author cannot edit that file, so treating its
      problems as hub failures would redden nearly every real hub.
    - Unmapped domain ontologies (``model/ontologies/*.ttl`` with no catalog
      entry) — nothing but ``init --domain`` ever registers a domain, so any hub
      grown via the design-discovery skill legitimately has unmapped domains
      with no automated remedy.
    - Missing ``<nextCatalog>`` targets and catalog cycles.

    This mirrors the maintainer's stated preference for a soft/advisory gate over
    a hard one that could break non-interactive flows (see DD around skill-gating
    in docs/design/toolkit-design-decisions.md:3127).

    Returns:
        True unless a dangling entry declared in the catalog under test was
        found, or the catalog could not be parsed.
    """
    try:
        resolver = CatalogResolver.with_reference_models(catalog_path)
    except (ET.ParseError, OSError) as exc:
        print(f"❌ Catalog is not parseable: {exc}")
        return False

    passed = True
    catalog_under_test = catalog_path.resolve()

    checkable_entries = [entry for entry in resolver.entries if not entry.absolute]
    absolute_entries = [entry for entry in resolver.entries if entry.absolute]
    own_entries = [
        entry for entry in checkable_entries if entry.declaring_catalog == catalog_under_test
    ]
    chained_entries = [
        entry for entry in checkable_entries if entry.declaring_catalog != catalog_under_test
    ]

    print(f"  {len(resolver.entries)} catalog entr{_plural(len(resolver.entries))} checked")

    own_dangling = sorted(
        {(entry.name, entry.path) for entry in own_entries if not entry.path.exists()}
    )
    if own_dangling:
        passed = False
        print(
            f"❌ {len(own_dangling)} dangling catalog entr{_plural(len(own_dangling))} in "
            f"{catalog_under_test.name} (target file does not exist):"
        )
        for name, path in own_dangling:
            print(f"    ✗ {name} -> {path}")
    elif own_entries:
        print(f"  ✓ All {len(own_entries)} catalog entries declared in this catalog resolve")
    else:
        print("  (no catalog entries declared in this catalog)")

    chained_dangling: dict[Path, list[tuple[str, Path]]] = {}
    for entry in chained_entries:
        if not entry.path.exists():
            chained_dangling.setdefault(entry.declaring_catalog, []).append(
                (entry.name, entry.path)
            )
    if chained_dangling:
        total = sum(len(items) for items in chained_dangling.values())
        print(
            f"⚠️  {total} dangling catalog entr{_plural(total)} declared in a chained catalog "
            "(not owned by this catalog — advisory only):"
        )
        for owner, items in sorted(chained_dangling.items()):
            print(f"    from {owner}:")
            for name, path in sorted(items):
                print(f"      ⚠ {name} -> {path}")

    if absolute_entries:
        print(
            f"  ℹ️  {len(absolute_entries)} catalog entr{_plural(len(absolute_entries))} use an "
            "absolute uri= target (not checked for dangling):"
        )
        for entry in sorted(absolute_entries, key=lambda e: e.name):
            print(f"      ℹ {entry.name} -> {entry.path}")

    ontologies_dir = catalog_path.parent / "model" / "ontologies"
    mapped_paths = {path.resolve() for path in resolver.mappings.values()}
    if not ontologies_dir.is_dir():
        print("  (no model/ontologies directory found — skipping domain-mapping check)")
    else:
        domain_files = [
            path
            for path in sorted(ontologies_dir.glob("*.ttl"))
            if is_domain_ontology_stem(path.stem)
        ]
        if not domain_files:
            print("  (no domain ontology files under model/ontologies — nothing to check)")
        else:
            unmapped = [path for path in domain_files if path.resolve() not in mapped_paths]
            if unmapped:
                print(
                    f"⚠️  {len(unmapped)} domain ontology file(s) not mapped in catalog (advisory — "
                    "only `kairos-ontology init --domain` registers a domain automatically):"
                )
                for path in unmapped:
                    print(f"    ⚠ {path.relative_to(catalog_path.parent)}")
            else:
                print(
                    f"  ✓ All {len(domain_files)} domain ontology file(s) are mapped in the catalog"
                )

    for diagnostic in resolver.diagnostics:
        if diagnostic.get("level") == "warning":
            print(f"  ⚠️  {diagnostic['message']}")

    return passed


def _plural(count: int) -> str:
    return "y" if count == 1 else "ies"


def test_catalog_resolution(catalog_path: Path, ontology_path: Path = None) -> bool:
    """Test catalog resolution.

    Always validates the catalog's own structure (dangling entries, unmapped
    domain ontologies, missing ``<nextCatalog>`` targets, catalog cycles). If
    *ontology_path* is given, additionally exercises import resolution for that
    ontology.

    Returns:
        True unless a dangling entry declared in the catalog under test was
        found, or the catalog could not be parsed — see
        :func:`_check_catalog_structure` for the full exit-code policy.
    """

    print("🔍 Catalog Resolution Test")
    print("=" * 50)
    print(f"\nCatalog: {catalog_path}\n")

    passed = _check_catalog_structure(catalog_path)

    if ontology_path:
        print(f"\nTesting with: {ontology_path}")
        try:
            result = load_ontology(ontology_path, catalog_path=catalog_path)
            print(f"  ✓ Loaded {len(result.graph)} triples")
            if result.diagnostics:
                for diag in result.diagnostics:
                    print(f"  ⚠️  [{diag.level}] {diag.message}")
            else:
                print("  ✓ All imports resolved successfully")
        except Exception as e:
            print(f"  ✗ Failed: {e}")

    if passed:
        print("\n✅ Catalog test completed")
    else:
        print("\n❌ Catalog test failed")

    return passed
