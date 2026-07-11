# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Domain-Driven Design (DDD) overlay support — discovery and validation (DD-091).

The DDD overlay is an OPTIONAL, ADDITIVE design layer expressed in
``{domain}-ddd-ext.ttl`` files under ``model/extensions/``. This module provides a
dedicated validation path that:

1. Discovers ``*-ddd-ext.ttl`` overlays.
2. Loads each overlay merged with its matching domain ontology and the packaged
   ``kairos-ddd`` vocabulary.
3. Applies the packaged DDD SHACL shapes to the merged graph.
4. Independently scans the overlay graph alone for leaked silver/gold projection
   predicates (kept separate because the merged graph may legitimately carry
   ``kairos-ext:`` annotations inherited from the domain ontology).

The vocabulary and shapes are loaded from the installed package, so hubs that
predate the feature validate correctly without a hub-local copy.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pyshacl import validate as shacl_validate
from rdflib import Graph, Namespace

logger = logging.getLogger(__name__)

DDD_NS = Namespace("https://kairos.cnext.eu/ddd#")
KAIROS_EXT_NS = "https://kairos.cnext.eu/ext#"

# Packaged vocabulary + shapes (bundled in scaffold/, loaded from the package so
# existing hubs validate without a hub-local copy).
_SCAFFOLD_DIR = Path(__file__).resolve().parent.parent / "scaffold"
DDD_VOCAB_PATH = _SCAFFOLD_DIR / "kairos-ddd.ttl"
DDD_SHAPES_PATH = _SCAFFOLD_DIR / "kairos-ddd-shapes.shacl.ttl"

_OVERLAY_SUFFIX = "-ddd-ext.ttl"


def discover_ddd_overlays(extensions_dir: Path) -> list[Path]:
    """Return sorted ``*-ddd-ext.ttl`` overlay files under *extensions_dir*."""
    if extensions_dir is None or not extensions_dir.is_dir():
        return []
    return sorted(extensions_dir.glob(f"*{_OVERLAY_SUFFIX}"))


def overlay_domain_name(overlay_path: Path) -> str:
    """Return the domain name for an overlay (``client-ddd-ext.ttl`` -> ``client``)."""
    return overlay_path.name[: -len(_OVERLAY_SUFFIX)]


def find_domain_ontology(overlay_path: Path, ontologies_dir: Path) -> Optional[Path]:
    """Locate the domain ontology TTL matching *overlay_path*."""
    if ontologies_dir is None or not ontologies_dir.is_dir():
        return None
    candidate = ontologies_dir / f"{overlay_domain_name(overlay_path)}.ttl"
    return candidate if candidate.exists() else None


def load_ddd_vocabulary() -> Graph:
    """Load the packaged kairos-ddd vocabulary graph."""
    g = Graph()
    if DDD_VOCAB_PATH.exists():
        g.parse(DDD_VOCAB_PATH, format="turtle")
    return g


def _load_domain_graph(
    domain_ontology_path: Optional[Path], catalog_path: Optional[Path]
) -> Graph:
    """Load the domain ontology, resolving imports via catalog when available."""
    graph = Graph()
    if domain_ontology_path is None or not domain_ontology_path.exists():
        return graph
    if catalog_path and catalog_path.exists():
        from .catalog_utils import load_graph_with_catalog

        return load_graph_with_catalog(domain_ontology_path, catalog_path).graph
    graph.parse(domain_ontology_path, format="turtle")
    return graph


def build_merged_graph(
    overlay_path: Path,
    domain_ontology_path: Optional[Path],
    catalog_path: Optional[Path] = None,
) -> Graph:
    """Build the merged graph: domain ontology + DDD overlay + kairos-ddd vocab."""
    graph = _load_domain_graph(domain_ontology_path, catalog_path)
    graph.parse(overlay_path, format="turtle")
    for triple in load_ddd_vocabulary():
        graph.add(triple)
    return graph


def _scan_ext_leak(overlay_graph: Graph) -> list[str]:
    """Return silver/gold ``kairos-ext:`` predicates present in the overlay alone.

    Scanning the overlay in isolation avoids false positives from ``kairos-ext:``
    annotations that legitimately live in the domain ontology (e.g. naturalKey).
    """
    leaked: set[str] = set()
    for _s, p, _o in overlay_graph:
        p_str = str(p)
        if not p_str.startswith(KAIROS_EXT_NS):
            continue
        local = p_str[len(KAIROS_EXT_NS):]
        if local.startswith("silver") or local.startswith("gold"):
            leaked.add(f"kairos-ext:{local}")
    return sorted(leaked)


def validate_ddd_overlay(
    overlay_path: Path,
    domain_ontology_path: Optional[Path],
    catalog_path: Optional[Path] = None,
) -> dict:
    """Validate a single DDD overlay.

    Returns a dict with keys:
        ``passed`` (bool), ``syntax`` {passed, errors}, ``shacl`` {passed, report},
        ``ext_leak`` {passed, predicates}.
    """
    result: dict = {
        "passed": True,
        "syntax": {"passed": True, "errors": []},
        "shacl": {"passed": True, "report": ""},
        "ext_leak": {"passed": True, "predicates": []},
    }

    # 1. Syntax: parse the overlay on its own.
    overlay_graph = Graph()
    try:
        overlay_graph.parse(overlay_path, format="turtle")
    except Exception as exc:  # noqa: BLE001 - surface any parse error
        result["passed"] = False
        result["syntax"]["passed"] = False
        result["syntax"]["errors"].append(str(exc))
        return result  # cannot continue without a parseable overlay

    # 2. Silver/gold projection-predicate leak (overlay only).
    leaked = _scan_ext_leak(overlay_graph)
    if leaked:
        result["passed"] = False
        result["ext_leak"]["passed"] = False
        result["ext_leak"]["predicates"] = leaked

    # 3. SHACL over the merged graph (domain + overlay + vocab).
    try:
        merged = build_merged_graph(overlay_path, domain_ontology_path, catalog_path)
        shapes_graph = Graph()
        shapes_graph.parse(DDD_SHAPES_PATH, format="turtle")
        conforms, _report_graph, report_text = shacl_validate(
            merged,
            shacl_graph=shapes_graph,
            inference="none",
            abort_on_first=False,
        )
        if not conforms:
            result["passed"] = False
            result["shacl"]["passed"] = False
            result["shacl"]["report"] = report_text
    except Exception as exc:  # noqa: BLE001
        result["passed"] = False
        result["shacl"]["passed"] = False
        result["shacl"]["report"] = str(exc)

    return result


def run_ddd_validation(
    extensions_dir: Path,
    ontologies_dir: Path,
    catalog_path: Optional[Path] = None,
) -> int:
    """Run the dedicated DDD overlay validation across a hub.

    Prints a per-overlay report and returns the number of failing overlays.
    When no ``*-ddd-ext.ttl`` overlays exist, DDD validation is skipped (the
    feature is optional and additive).
    """
    print("\n\U0001f9e9 Kairos DDD Overlay Validation")
    print("=" * 50)

    overlays = discover_ddd_overlays(extensions_dir)
    if not overlays:
        print("  (no *-ddd-ext.ttl overlays found — DDD validation not applicable)")
        return 0

    failures = 0
    for overlay in overlays:
        domain_ontology = find_domain_ontology(overlay, ontologies_dir)
        res = validate_ddd_overlay(overlay, domain_ontology, catalog_path)
        if res["passed"]:
            print(f"  \u2705 {overlay.name}")
            continue

        failures += 1
        print(f"  \u274c {overlay.name}")
        if not res["syntax"]["passed"]:
            for err in res["syntax"]["errors"]:
                print(f"     syntax: {err}")
        if not res["ext_leak"]["passed"]:
            preds = ", ".join(res["ext_leak"]["predicates"])
            print(
                "     projection leak: overlay must not use silver/gold "
                f"kairos-ext predicates ({preds})"
            )
        if not res["shacl"]["passed"]:
            report = res["shacl"]["report"].strip()
            print(f"     SHACL:\n{report}")

    print(f"\n  Validated {len(overlays)} DDD overlay(s), {failures} failed")
    return failures
