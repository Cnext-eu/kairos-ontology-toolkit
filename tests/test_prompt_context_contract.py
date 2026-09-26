# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Every AI call site is inventoried; those that show ontology terms render them through
``core.prompt_context`` (DD-243, DD-244).

A prompt that lists classes and properties from a single file, or from a cut pool with no
disclosure, is where the model concludes "the reference model lacks it". The inventory in
``docs/dev/ai-prompt-inventory.json`` names each call site, says whether its prompt carries
ontology terms, and for those that do, whether the builder module renders them through the
one helper that reads the closure index and discloses cuts. A builder that does not yet is a
known gap that names its decision; the row disappears when it is wired.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "kairos_ontology"
INVENTORY_PATH = ROOT / "docs" / "dev" / "ai-prompt-inventory.json"
HELPER_MODULE = "kairos_ontology.core.prompt_context"

#: The wrapper itself, and nothing else, may call the SDK directly.
EXEMPT_MODULES = {"core/ai_provider.py"}


def scan_ai_call_sites(package: Path = PACKAGE) -> dict[str, set[str]]:
    """``{module: {enclosing function}}`` for every chat-completion call.

    Matches ``create_chat_completion(...)`` and a raw ``<x>.chat.completions.create(...)``.
    """
    sites: dict[str, set[str]] = {}
    for path in sorted(package.rglob("*.py")):
        key = path.relative_to(package).as_posix()
        if key in EXEMPT_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            matched = (isinstance(func, ast.Name) and func.id == "create_chat_completion") or (
                isinstance(func, ast.Attribute)
                and func.attr == "create"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "completions"
                and isinstance(func.value.value, ast.Attribute)
                and func.value.value.attr == "chat"
            )
            if not matched:
                continue
            names = []
            cursor = parents.get(node)
            while cursor is not None:
                if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.append(cursor.name)
                cursor = parents.get(cursor)
            sites.setdefault(key, set()).add(".".join(reversed(names)) or "<module>")
    return sites


def _imports_helper(module_path: Path) -> bool:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            resolved = node.module or ""
            if node.level:
                # Relative import inside kairos_ontology.core: ``from .prompt_context import``
                # or ``from ..core.prompt_context import``.
                if resolved.endswith("prompt_context") or any(
                    alias.name == "prompt_context" for alias in node.names
                ):
                    return True
            elif resolved == HELPER_MODULE or (
                resolved == HELPER_MODULE.rsplit(".", 1)[0]
                and any(alias.name == "prompt_context" for alias in node.names)
            ):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name == HELPER_MODULE for alias in node.names):
                return True
    return False


@pytest.fixture(scope="module")
def inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def test_every_ai_call_site_is_inventoried_and_every_row_still_exists(inventory):
    actual = scan_ai_call_sites()
    expected: dict[str, set[str]] = {}
    for row in inventory["sites"]:
        expected.setdefault(row["module"], set()).add(row["function"])
    new = sorted(f"{m}::{f}" for m, fs in actual.items() for f in fs - expected.get(m, set()))
    stale = sorted(f"{m}::{f}" for m, fs in expected.items() for f in fs - actual.get(m, set()))
    assert not new, (
        "AI call site with no inventory row (DD-244). Add it to "
        f"{INVENTORY_PATH.relative_to(ROOT).as_posix()} and say whether the prompt carries "
        "ontology terms:\n" + "\n".join(new)
    )
    assert not stale, "inventory rows whose call no longer exists; delete them:\n" + "\n".join(
        stale
    )


def test_prompts_with_ontology_terms_render_through_the_helper_or_name_their_gap(inventory):
    failures = []
    for row in inventory["sites"]:
        if not row["ontology_terms"]:
            continue
        module_path = PACKAGE / row["module"]
        wired = _imports_helper(module_path)
        gap = row.get("known_gap", "")
        if wired and gap:
            failures.append(f"{row['module']}: imports the helper; drop its known_gap")
        if not wired and not gap.startswith("DD-"):
            failures.append(
                f"{row['module']}::{row['function']}: shows ontology terms without "
                f"{HELPER_MODULE}; wire it or record the gap as 'DD-…'"
            )
    assert not failures, "\n".join(failures)


#: The one raw SDK call that is not a gap: a connectivity probe that sends no hub content.
RAW_SDK_ALLOWED = {"core/ai_preflight.py"}


def test_raw_sdk_calls_are_limited_to_the_recorded_exceptions(inventory):
    """Only the wrapper talks to the SDK; a raw call bypasses tracing and redaction, so
    every one is either the probe or a known gap that names its decision."""
    offenders = [
        f"{row['module']}::{row['function']}"
        for row in inventory["sites"]
        if row.get("raw_sdk")
        and row["module"] not in RAW_SDK_ALLOWED
        and not row.get("known_gap", "").startswith("DD-")
    ]
    assert not offenders, (
        "raw SDK call must go through create_chat_completion or name a DD:\n" + "\n".join(offenders)
    )
