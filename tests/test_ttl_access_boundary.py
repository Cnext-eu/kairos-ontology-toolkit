# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Static boundary test enforcing DD-103 (canonical ontology closure).

DD-103 ("Canonical ontology closure and versioned semantic index",
``docs/design/toolkit-design-decisions.md``) designates ``core/ontology_loader.py``
(``load_ontology()``) and its ``SemanticIndex`` as the single semantic-loading API.
Raw ``rdflib.Graph().parse(...)`` calls scattered across other modules bypass the
catalog-backed ``owl:imports`` closure, the completeness/diagnostics contract, and the
versioned semantic index that the loader guarantees — exactly the failure modes DD-103
exists to close.

This test statically scans ``src/kairos_ontology/core/*.py`` (top-level modules only —
NOT subdirectories such as ``core/compiler/`` or ``core/projections/``, which independently
parse ontology/SHACL content in the same way and were out of scope for this audit) via AST
and fails if any module *other than* the modules in ``_EXEMPT_MODULES`` below calls
``<graph>.parse(...)`` (rdflib-style TTL/RDF parsing) or opens a literal ``.ttl`` path via
``open()``/``read_text()``/``read_bytes()``.

``_CANONICAL_LOADERS`` are the two designated DD-103 modules and need no further
justification. ``_KNOWN_VIOLATIONS`` is an explicit, individually-commented list of
modules that were found — during the audit that added this test — to already call
``rdflib.Graph().parse()`` directly, bypassing the canonical loader. Fixing them is a
separate, out-of-scope migration (DD-103 itself frames this as an incremental
migration: "Semantic consumers must declare a profile and may no longer parse
domain/reference ontologies independently"). They are listed here honestly as known,
pre-existing debt — not as endorsed exceptions — so this test can still catch *new*
modules quietly reaching for ``rdflib.Graph().parse()`` instead of the canonical loader.

Do not add a module to ``_KNOWN_VIOLATIONS`` to make this test pass. If a module
genuinely needs raw ontology access, route it through
:func:`kairos_ontology.core.ontology_loader.load_ontology` (or its ``SemanticIndex``)
instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).resolve().parent.parent / "src" / "kairos_ontology" / "core"

# The two designated canonical loader modules (DD-103 "Implementation" list). These are
# *not* exceptions to the rule — they are the rule.
_CANONICAL_LOADERS = frozenset({"ontology_loader.py", "catalog_utils.py"})

# Pre-existing DD-103 violations found by this test's audit (2026-08). Each parses TTL
# directly via rdflib instead of going through core.ontology_loader.load_ontology() /
# SemanticIndex. None of these were introduced or fixed by this change; they are
# recorded here explicitly so the boundary test can still guard the rest of core/*.py.
# Do NOT extend this dict casually — a new entry here is a new admission of DD-103 debt
# and should get its own review/decision-record note.
_KNOWN_VIOLATIONS: dict[str, str] = {
    "analyse_sources.py": "parses source-vocabulary/discovery TTL directly for source analysis heuristics",
    "authoring_scaffolds.py": "parses hub ontology/mapping TTL directly when generating authoring scaffolds",
    "coverage_report.py": "parses mapping-binding TTL directly for coverage reporting",
    "ddd.py": "parses DDD vocabulary/overlay/shapes TTL directly for DDD projections",
    "design_validation.py": "parses ontology/shapes/extension TTL directly for design-time validation",
    "draft_model_report.py": "parses ontology TTL directly to draft a model report",
    "evidence_loaders.py": "parses imported dbt evidence TTL directly",
    "import_source.py": "parses existing source-vocabulary TTL directly before merging imported schema",
    "ontology_ops.py": (
        "low-level exact-domain/namespace ontology helpers; DD-103 itself carves these out "
        "for 'inventory / non-binding uses only' but they still parse TTL directly"
    ),
    "ontology_scope.py": "parses a single ontology file directly to compute file-scope diagnostics",
    "projector.py": "parses default/extension/peer ontology graphs directly during projection",
    "reference_modules.py": "legacy compatibility path parses a reference-module ontology file directly",
    "silver_sample_audit.py": "parses ontology TTL directly for Silver sample auditing",
    "source_analysis.py": "parses source-vocabulary TTL directly for source analysis",
    "source_catalog.py": "parses catalog-resolved ontology TTL directly for source cataloging",
    "source_privacy.py": "parses source-vocabulary TTL directly to evaluate privacy/PII flags",
    "suggest_shapes.py": "parses vocabulary TTL directly to suggest SHACL shapes",
    "validator.py": "parses ontology/shapes/extension/mapping TTL directly for SHACL/syntax validation",
}

_EXEMPT_MODULES = _CANONICAL_LOADERS | frozenset(_KNOWN_VIOLATIONS)

# xml.etree.ElementTree is commonly aliased to one of these; its .parse() parses XML
# (e.g. catalog-v001.xml), never Turtle, and is not a DD-103 concern.
_NON_RDFLIB_PARSE_RECEIVERS = frozenset({"ET", "ElementTree", "etree"})


def _base_name(node: ast.AST) -> str | None:
    """Return the leftmost ``Name`` id in an attribute/call chain, if any.

    E.g. for ``graph.parse(...)`` this returns ``"graph"``; for ``Graph().parse(...)``
    it returns ``"Graph"``.
    """
    while isinstance(node, ast.Attribute):
        node = node.value
    while isinstance(node, ast.Call):
        node = node.func
    return node.id if isinstance(node, ast.Name) else None


def _find_violations(path: Path) -> list[str]:
    """Return human-readable descriptions of TTL-boundary violations in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "parse":
            base = _base_name(func.value)
            if base not in _NON_RDFLIB_PARSE_RECEIVERS:
                findings.append(
                    f"{path.name}:{node.lineno}: `.parse(...)` call (receiver={base!r})"
                )
        elif isinstance(func, ast.Name) and func.id == "open":
            if node.args and isinstance(node.args[0], ast.Constant):
                value = node.args[0].value
                if isinstance(value, str) and value.endswith(".ttl"):
                    findings.append(f"{path.name}:{node.lineno}: open() on a literal .ttl path")
        elif isinstance(func, ast.Attribute) and func.attr in ("read_text", "read_bytes"):
            receiver = func.value
            if (
                isinstance(receiver, ast.Constant)
                and isinstance(receiver.value, str)
                and receiver.value.endswith(".ttl")
            ):
                findings.append(f"{path.name}:{node.lineno}: {func.attr}() on a literal .ttl path")
    return findings


def _scan_core_top_level() -> dict[str, list[str]]:
    """Scan every top-level ``core/*.py`` module and return ``{filename: findings}``."""
    return {
        path.name: violations
        for path in sorted(_CORE_DIR.glob("*.py"))
        for violations in [_find_violations(path)]
        if violations
    }


def test_core_dir_exists():
    """Sanity check: the scan target exists (catches a moved/renamed package)."""
    assert _CORE_DIR.is_dir(), f"expected core/ at {_CORE_DIR}"


def test_no_new_direct_ttl_parsing_outside_canonical_loader_and_known_violations():
    """No module outside the exempt list may parse TTL directly (DD-103).

    Only ``core/ontology_loader.py`` and ``core/catalog_utils.py`` are the designated
    canonical loader; the modules in ``_KNOWN_VIOLATIONS`` are pre-existing debt tracked
    explicitly. Any *other* module found here has newly started bypassing the canonical
    loader and must be routed through ``load_ontology()`` / ``SemanticIndex`` instead.
    """
    flagged = _scan_core_top_level()
    unexpected = {
        name: findings for name, findings in flagged.items() if name not in _EXEMPT_MODULES
    }

    if unexpected:
        details = "\n".join(
            f"  {name}:\n" + "\n".join(f"    {f}" for f in findings)
            for name, findings in sorted(unexpected.items())
        )
        pytest.fail(
            "Found module(s) in src/kairos_ontology/core/ parsing TTL directly, bypassing "
            "the DD-103 canonical loader (core/ontology_loader.py). Route semantic access "
            "through load_ontology()/SemanticIndex instead, or — if this is deliberate, "
            "reviewed, low-level utility work — add it to _KNOWN_VIOLATIONS in this test "
            "with an honest comment explaining why:\n" + details
        )


def test_canonical_loaders_still_parse_ttl_directly():
    """Sanity check: the canonical loaders are exempted because they DO parse TTL.

    If this ever fails, ``core/ontology_loader.py`` or ``core/catalog_utils.py`` no
    longer needs the exemption (or was refactored) — the exempt list should shrink
    accordingly rather than staying stale.
    """
    flagged = _scan_core_top_level()
    for name in _CANONICAL_LOADERS:
        assert name in flagged, f"{name} no longer parses TTL directly — remove its exemption"


def test_known_violations_list_is_not_stale():
    """Every entry in _KNOWN_VIOLATIONS must still be a genuine, current violation.

    Keeps the exemption list honest: an entry that no longer parses TTL directly (e.g.
    migrated to the canonical loader in an unrelated change) must be removed here, not
    left behind as dead cover.
    """
    flagged = _scan_core_top_level()
    stale = [name for name in _KNOWN_VIOLATIONS if name not in flagged]
    assert not stale, (
        f"_KNOWN_VIOLATIONS entries no longer parse TTL directly (remove from the "
        f"exemption list): {stale}"
    )


def test_known_violations_are_all_present_in_core():
    """Every _KNOWN_VIOLATIONS filename must correspond to a real core/*.py module."""
    existing = {path.name for path in _CORE_DIR.glob("*.py")}
    missing = [name for name in _KNOWN_VIOLATIONS if name not in existing]
    assert not missing, f"_KNOWN_VIOLATIONS references non-existent core modules: {missing}"
