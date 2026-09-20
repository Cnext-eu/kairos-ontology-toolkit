# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Domain-Driven Design (DDD) overlay support — discovery and validation (DD-091, DD-229).

The DDD overlay is an OPTIONAL, ADDITIVE design layer. It has two kinds of file under
``model/extensions/``:

- **one hub-wide strategic file**, ``ddd-contexts-ext.ttl``, holding the bounded contexts,
  their subdomain type, and the context map (``ContextRelationship`` individuals) — the
  strategic design, which by its nature cuts across domain ontologies (DD-229);
- **one tactical overlay per domain**, ``{domain}-ddd-ext.ttl``, annotating that domain's
  own classes: context membership, tactical pattern, aggregate root, invariants, design
  notes, and the context-specific language (``skos:scopeNote``, ``skos:example``,
  ``skos:altLabel``).

This module provides the dedicated validation path:

1. Discovers the strategic file and the ``*-ddd-ext.ttl`` overlays.
2. Validates the strategic file on its own (syntax, leak scan, SHACL over strategic +
   vocabulary).
3. Loads each overlay merged with its matching domain ontology, the strategic file and
   the packaged ``kairos-ddd`` vocabulary, and applies the packaged DDD SHACL shapes.
4. Independently scans each file alone for leaked silver/gold projection predicates
   (kept separate because the merged graph may legitimately carry ``kairos-ext:``
   annotations inherited from the domain ontology).
5. Audits the whole set for cross-file inconsistencies per-domain SHACL cannot see: a
   context declared in several files with differing labels, a class placed in two
   contexts by two overlays.

The vocabulary and shapes are loaded from the installed package, so hubs that
predate the feature validate correctly without a hub-local copy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pyshacl import validate as shacl_validate
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF, RDFS

logger = logging.getLogger(__name__)

DDD_NS = Namespace("https://kairos.cnext.eu/ddd#")
KAIROS_EXT_NS = "https://kairos.cnext.eu/ext#"

# Packaged vocabulary + shapes (bundled in scaffold/, loaded from the package so
# existing hubs validate without a hub-local copy).
_SCAFFOLD_DIR = Path(__file__).resolve().parent.parent / "scaffold"
DDD_VOCAB_PATH = _SCAFFOLD_DIR / "kairos-ddd.ttl"
DDD_SHAPES_PATH = _SCAFFOLD_DIR / "kairos-ddd-shapes.shacl.ttl"

_OVERLAY_SUFFIX = "-ddd-ext.ttl"

#: The one hub-wide strategic file (DD-229). Deliberately does NOT match the
#: ``*-ddd-ext.ttl`` overlay glob: an overlay is validated merged with the domain ontology
#: its filename names, and a file with no such domain is an orphan (#848). The strategic
#: file has no domain -- it is merged into every overlay's graph instead.
STRATEGIC_FILE_NAME = "ddd-contexts-ext.ttl"

#: Diagnostic codes of the hub-wide consistency audit. Recorded in DD-229 and
#: ``docs/dev/cli-behaviour-notes.md`` rather than ``diagnostic-codes.md``, which catalogues
#: compile diagnostics only.
CODE_CONTEXT_REDECLARED = "ddd.context-redeclared"
CODE_CONTEXT_LABEL_CONFLICT = "ddd.context-label-conflict"
CODE_CLASS_IN_TWO_CONTEXTS = "ddd.class-in-two-contexts"
CODE_TACTICAL_IN_STRATEGIC = "ddd.tactical-in-strategic-file"

#: Class-level (tactical) predicates that belong in a domain overlay, never in the
#: strategic file, whose graph holds no classes to validate them against.
_TACTICAL_PREDICATES = (DDD_NS.tacticalPattern, DDD_NS.aggregateRoot, DDD_NS.invariant)


@dataclass(frozen=True)
class DddDiagnostic:
    """One finding of the hub-wide consistency audit."""

    level: str  # "error" | "warning"
    code: str
    message: str


def discover_ddd_overlays(extensions_dir: Path) -> list[Path]:
    """Return sorted ``*-ddd-ext.ttl`` overlay files under *extensions_dir*.

    The strategic file is not an overlay and is never returned here; see
    :func:`find_strategic_file`.
    """
    if extensions_dir is None or not extensions_dir.is_dir():
        return []
    return sorted(
        path
        for path in extensions_dir.glob(f"*{_OVERLAY_SUFFIX}")
        if path.name != STRATEGIC_FILE_NAME
    )


def find_strategic_file(extensions_dir: Optional[Path]) -> Optional[Path]:
    """Return the hub-wide strategic file when the hub has one."""
    if extensions_dir is None:
        return None
    candidate = Path(extensions_dir) / STRATEGIC_FILE_NAME
    return candidate if candidate.is_file() else None


def overlay_domain_name(overlay_path: Path) -> str:
    """Return the domain name for an overlay (``client-ddd-ext.ttl`` -> ``client``)."""
    return overlay_path.name[: -len(_OVERLAY_SUFFIX)]


def expected_domain_ontology(overlay_path: Path, ontologies_dir: Path) -> Path:
    """Return where *overlay_path*'s domain ontology must live, whether or not it does.

    Split out of :func:`find_domain_ontology` so a caller reporting the miss can name the
    file it looked for (#848). "No matching domain ontology" is only actionable if the
    reader is told which name was expected.
    """
    return Path(ontologies_dir) / f"{overlay_domain_name(overlay_path)}.ttl"


def find_domain_ontology(overlay_path: Path, ontologies_dir: Path) -> Optional[Path]:
    """Locate the domain ontology TTL matching *overlay_path*."""
    if ontologies_dir is None or not ontologies_dir.is_dir():
        return None
    candidate = expected_domain_ontology(overlay_path, ontologies_dir)
    return candidate if candidate.exists() else None


def load_ddd_vocabulary() -> Graph:
    """Load the packaged kairos-ddd vocabulary graph."""
    g = Graph()
    if DDD_VOCAB_PATH.exists():
        g.parse(DDD_VOCAB_PATH, format="turtle")
    return g


def _load_domain_graph(domain_ontology_path: Optional[Path], catalog_path: Optional[Path]) -> Graph:
    """Load the domain ontology, resolving imports via catalog when available."""
    graph = Graph()
    if domain_ontology_path is None or not domain_ontology_path.exists():
        return graph
    from .ontology_loader import SemanticProfile, load_ontology

    loaded = load_ontology(
        domain_ontology_path,
        catalog_path=(catalog_path if catalog_path and catalog_path.exists() else None),
        profile=SemanticProfile.KAIROS_DESIGN,
    ).graph
    # A copy, never the loader's own graph: the loader caches per path and process, and
    # `build_merged_graph` parses the overlay INTO the graph it is handed. Returning the
    # cached object made every overlay validated earlier in the process part of the next
    # one's merged graph -- an AggregateMember without a root passed because an earlier
    # test's `aggregateRoot` triple was still there, and a clean overlay failed rule 9
    # because an earlier one had placed the same class in a second context.
    for triple in loaded:
        graph.add(triple)
    return graph


def build_merged_graph(
    overlay_path: Path,
    domain_ontology_path: Optional[Path],
    catalog_path: Optional[Path] = None,
    strategic_path: Optional[Path] = None,
) -> Graph:
    """Build the merged graph: domain ontology + strategic file + overlay + vocabulary.

    The strategic file is merged into *every* overlay's graph (DD-229), which is what lets
    an overlay reference a context by IRI without redeclaring it. A hub that predates the
    strategic file and still declares its contexts inside each overlay merges nothing extra
    and validates exactly as before.
    """
    graph = _load_domain_graph(domain_ontology_path, catalog_path)
    if strategic_path is not None and Path(strategic_path).is_file():
        graph.parse(strategic_path, format="turtle")
    graph.parse(overlay_path, format="turtle")
    for triple in load_ddd_vocabulary():
        graph.add(triple)
    return graph


def _scan_ext_leak(overlay_graph: Graph) -> list[str]:
    """Return silver/gold ``kairos-ext:`` predicates present in the overlay alone.

    Scanning the overlay in isolation avoids false positives from ``kairos-ext:``
    annotations that legitimately live in the domain ontology (e.g. naturalKey).
    SKOS predicates (``skos:scopeNote``, ``skos:example``, ``skos:altLabel``) are not
    ``kairos-ext`` and pass: they are the ubiquitous-language layer, not projection control.
    """
    leaked: set[str] = set()
    for _s, p, _o in overlay_graph:
        p_str = str(p)
        if not p_str.startswith(KAIROS_EXT_NS):
            continue
        local = p_str[len(KAIROS_EXT_NS) :]
        if local.startswith("silver") or local.startswith("gold"):
            leaked.add(f"kairos-ext:{local}")
    return sorted(leaked)


def _run_shapes(graph: Graph) -> tuple[bool, str]:
    shapes_graph = Graph()
    shapes_graph.parse(DDD_SHAPES_PATH, format="turtle")
    conforms, _report_graph, report_text = shacl_validate(
        graph,
        shacl_graph=shapes_graph,
        inference="none",
        abort_on_first=False,
    )
    return conforms, report_text


def _new_result() -> dict:
    return {
        "passed": True,
        "syntax": {"passed": True, "errors": []},
        "domain": {"passed": True, "expected": ""},
        "shacl": {"passed": True, "report": ""},
        "ext_leak": {"passed": True, "predicates": []},
        "strategic": {"passed": True, "tactical_predicates": []},
    }


def validate_ddd_overlay(
    overlay_path: Path,
    domain_ontology_path: Optional[Path],
    catalog_path: Optional[Path] = None,
    strategic_path: Optional[Path] = None,
) -> dict:
    """Validate a single DDD overlay.

    Returns a dict with keys:
        ``passed`` (bool), ``syntax`` {passed, errors}, ``domain`` {passed, expected},
        ``shacl`` {passed, report}, ``ext_leak`` {passed, predicates}.

    *domain_ontology_path* of ``None`` is a **failure**, not a mode (#848). SHACL would
    otherwise run against ``empty graph + overlay + vocabulary``, where the shapes that
    would catch the miss cannot fire -- the triples they target are exactly the ones that
    went missing -- so the overlay was reported as passing while nothing had validated it.

    *strategic_path*, when given, is merged into the graph so context references resolve
    (DD-229).
    """
    result = _new_result()

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

    # 3. The overlay must have a domain ontology to be merged with.
    if domain_ontology_path is None:
        result["passed"] = False
        result["domain"]["passed"] = False
        result["domain"]["expected"] = f"{overlay_domain_name(overlay_path)}.ttl"
        # SHACL is deliberately not run. Against an empty domain graph an overlay using
        # `kairos-ddd:aggregateRoot` fails rule 4 with "must point to an owl:Class present
        # in the merged domain graph", which reads as a modelling error in the overlay and
        # sends the reader looking in entirely the wrong place.
        return result

    # 4. SHACL over the merged graph (domain + strategic + overlay + vocab).
    try:
        merged = build_merged_graph(
            overlay_path, domain_ontology_path, catalog_path, strategic_path
        )
        conforms, report_text = _run_shapes(merged)
        if not conforms:
            result["passed"] = False
            result["shacl"]["passed"] = False
            result["shacl"]["report"] = report_text
    except Exception as exc:  # noqa: BLE001
        result["passed"] = False
        result["shacl"]["passed"] = False
        result["shacl"]["report"] = str(exc)

    return result


def validate_strategic_file(strategic_path: Path) -> dict:
    """Validate the hub-wide strategic file on its own (DD-229).

    Same result shape as :func:`validate_ddd_overlay`. The graph is the strategic file plus
    the vocabulary: contexts need labels and a known subdomain type, relationships need two
    declared endpoints and a known pattern. Class-level tactical predicates are refused
    here -- there is no domain graph to check them against, and a tactical annotation in
    the strategic file would silently escape the per-domain validation that owns it.
    """
    result = _new_result()
    graph = Graph()
    try:
        graph.parse(strategic_path, format="turtle")
    except Exception as exc:  # noqa: BLE001
        result["passed"] = False
        result["syntax"]["passed"] = False
        result["syntax"]["errors"].append(str(exc))
        return result

    leaked = _scan_ext_leak(graph)
    if leaked:
        result["passed"] = False
        result["ext_leak"]["passed"] = False
        result["ext_leak"]["predicates"] = leaked

    tactical = sorted(
        f"kairos-ddd:{str(pred)[len(str(DDD_NS)) :]}"
        for pred in _TACTICAL_PREDICATES
        if next(graph.subject_objects(pred), None) is not None
    )
    if tactical:
        result["passed"] = False
        result["strategic"]["passed"] = False
        result["strategic"]["tactical_predicates"] = tactical

    try:
        for triple in load_ddd_vocabulary():
            graph.add(triple)
        conforms, report_text = _run_shapes(graph)
        if not conforms:
            result["passed"] = False
            result["shacl"]["passed"] = False
            result["shacl"]["report"] = report_text
    except Exception as exc:  # noqa: BLE001
        result["passed"] = False
        result["shacl"]["passed"] = False
        result["shacl"]["report"] = str(exc)
    return result


def _parse_quietly(path: Path) -> Optional[Graph]:
    graph = Graph()
    try:
        graph.parse(path, format="turtle")
    except Exception:  # noqa: BLE001 - syntax is reported by the per-file validation
        return None
    return graph


def audit_ddd_consistency(
    overlays: list[Path],
    strategic_path: Optional[Path] = None,
) -> list[DddDiagnostic]:
    """Find what per-domain validation cannot: disagreements *between* files.

    Per-domain SHACL sees one overlay at a time. Two overlays can therefore declare the
    same context with different labels, or place one class in two contexts, and each
    validates clean while the rendered architecture disagrees with itself. This audit
    reads every file together and reports:

    - ``ddd.context-redeclared`` (warning): one context IRI declared in more than one file
      with consistent labels. Harmless in RDF, but hand-maintained; the strategic file is
      where a context is declared once.
    - ``ddd.context-label-conflict`` (error): the same IRI, different labels. The reports
      would render two names for one context.
    - ``ddd.class-in-two-contexts`` (error): one class assigned to different contexts by
      different files. A class belongs to exactly one context; the per-file ``maxCount 1``
      shape catches the same mistake inside one file.
    """
    files = [*([strategic_path] if strategic_path is not None else []), *overlays]
    context_files: dict[URIRef, list[tuple[str, Optional[str]]]] = {}
    class_files: dict[URIRef, list[tuple[str, URIRef]]] = {}
    for path in files:
        graph = _parse_quietly(Path(path))
        if graph is None:
            continue
        for ctx in graph.subjects(RDF.type, DDD_NS.BoundedContext):
            label = graph.value(ctx, RDFS.label)
            context_files.setdefault(ctx, []).append(
                (Path(path).name, str(label) if label is not None else None)
            )
        for subject, ctx in graph.subject_objects(DDD_NS.boundedContext):
            if isinstance(ctx, URIRef):
                class_files.setdefault(subject, []).append((Path(path).name, ctx))

    diagnostics: list[DddDiagnostic] = []
    for ctx, entries in sorted(context_files.items(), key=lambda item: str(item[0])):
        if len(entries) < 2:
            continue
        names = ", ".join(sorted(name for name, _ in entries))
        labels = sorted({label for _, label in entries if label is not None})
        if len(labels) > 1:
            diagnostics.append(
                DddDiagnostic(
                    "error",
                    CODE_CONTEXT_LABEL_CONFLICT,
                    f"{ctx} is declared in {names} with different labels "
                    f"({' / '.join(repr(label) for label in labels)}); the reports would "
                    f"render two names for one context. Declare it once, in {STRATEGIC_FILE_NAME}.",
                )
            )
        else:
            diagnostics.append(
                DddDiagnostic(
                    "warning",
                    CODE_CONTEXT_REDECLARED,
                    f"{ctx} is declared in {names}; move the declaration to "
                    f"{STRATEGIC_FILE_NAME} and reference it from the overlays.",
                )
            )
    for subject, entries in sorted(class_files.items(), key=lambda item: str(item[0])):
        contexts = {ctx for _, ctx in entries}
        if len(contexts) < 2:
            continue
        placements = ", ".join(f"{name} -> {ctx}" for name, ctx in sorted(entries, key=str))
        diagnostics.append(
            DddDiagnostic(
                "error",
                CODE_CLASS_IN_TWO_CONTEXTS,
                f"{subject} is placed in two bounded contexts ({placements}); a class "
                "belongs to exactly one context.",
            )
        )
    return diagnostics


def _print_failure(res: dict, *, domain_hint: str = "") -> None:
    if not res["syntax"]["passed"]:
        for err in res["syntax"]["errors"]:
            print(f"     syntax: {err}")
    if not res["domain"]["passed"]:
        print(domain_hint)
    if not res["ext_leak"]["passed"]:
        preds = ", ".join(res["ext_leak"]["predicates"])
        print(
            f"     projection leak: overlay must not use silver/gold kairos-ext predicates ({preds})"
        )
    if not res["strategic"]["passed"]:
        preds = ", ".join(res["strategic"]["tactical_predicates"])
        print(
            f"     tactical annotations in the strategic file ({preds}); class-level design "
            "belongs in the domain's own {domain}-ddd-ext.ttl, where it is validated against "
            "that domain's classes."
        )
    if not res["shacl"]["passed"]:
        report = res["shacl"]["report"].strip()
        print(f"     SHACL:\n{report}")


def run_ddd_validation(
    extensions_dir: Path,
    ontologies_dir: Path,
    catalog_path: Optional[Path] = None,
) -> int:
    """Run the dedicated DDD validation across a hub.

    Prints a per-file report and returns the number of failing items (files plus
    hub-wide consistency errors). When neither overlays nor a strategic file exist, DDD
    validation is skipped (the feature is optional and additive).
    """
    print("\n\U0001f9e9 Kairos DDD Overlay Validation")
    print("=" * 50)

    overlays = discover_ddd_overlays(extensions_dir)
    strategic = find_strategic_file(extensions_dir)
    if not overlays and strategic is None:
        print(
            f"  (no *-ddd-ext.ttl overlays or {STRATEGIC_FILE_NAME} found — DDD validation not applicable)"
        )
        return 0

    failures = 0
    if strategic is not None:
        res = validate_strategic_file(strategic)
        if res["passed"]:
            print(f"  ✅ {strategic.name} (strategic: contexts and context map)")
        else:
            failures += 1
            print(f"  ❌ {strategic.name} (strategic)")
            _print_failure(res)

    for overlay in overlays:
        domain_ontology = find_domain_ontology(overlay, ontologies_dir)
        res = validate_ddd_overlay(overlay, domain_ontology, catalog_path, strategic_path=strategic)
        if res["passed"]:
            print(f"  ✅ {overlay.name}")
            continue

        failures += 1
        print(f"  ❌ {overlay.name}")
        _print_failure(
            res,
            domain_hint=(
                "     no domain ontology at "
                f"{expected_domain_ontology(overlay, ontologies_dir)} -- an overlay is "
                "validated merged with the ontology its filename names, so this one was "
                "not validated at all. Rename the overlay to match its domain, or remove it."
            ),
        )

    diagnostics = audit_ddd_consistency(overlays, strategic)
    warnings = 0
    for diagnostic in diagnostics:
        if diagnostic.level == "error":
            failures += 1
            print(f"  ❌ {diagnostic.code}: {diagnostic.message}")
        else:
            warnings += 1
            print(f"  ⚠ {diagnostic.code}: {diagnostic.message}")

    # "Checked", not "Validated": an overlay with no domain ontology is counted here but
    # was never validated against anything, and the summary used to assert otherwise.
    strategic_note = " + strategic file" if strategic is not None else ""
    print(
        f"\n  Checked {len(overlays)} DDD overlay(s){strategic_note}, "
        f"{failures} failed, {warnings} warning(s)"
    )
    return failures
