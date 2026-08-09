# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Drift guard: every compiler diagnostic code must be documented.

``docs/design/diagnostic-codes.md`` is the stable catalog of every
``CompileDiagnostic.code`` literal constructed anywhere under
``core/compiler/*.py``. This test statically parses that same source tree (via the
``ast`` module, not just a text grep) and fails if any code is missing from the
catalog -- whether it is a plain ``CompileDiagnostic(code="...")`` call, a code passed
positionally to a local helper (``_diagnostic``/``_diag``/``_reject``/``_add``/
``_failure``/``_enum_value``), or a code assigned through a lookup-table remap such as
``kernel.py``'s ``code_map``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import kairos_ontology.core.compiler as compiler_package

COMPILER_DIR = Path(compiler_package.__file__).parent
DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "design" / "diagnostic-codes.md"


def _string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _local_code_param_index(tree: ast.AST) -> dict[str, tuple[int, bool]]:
    """Map local function name -> (positional index of its ``code`` parameter, is_method).

    ``is_method`` is a heuristic: the function's first parameter is literally named
    ``self``, so a bound call site (``self.foo(...)`` / ``obj.foo(...)``) omits it from
    the call's argument list.
    """
    mapping: dict[str, tuple[int, bool]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = [arg.arg for arg in node.args.args]
            if "code" in names:
                is_method = bool(names) and names[0] == "self"
                mapping[node.name] = (names.index("code"), is_method)
    return mapping


def _joined_str_prefix(node: ast.JoinedStr) -> str:
    prefix = ""
    for part in node.values:
        if isinstance(part, ast.Constant):
            prefix += str(part.value)
        else:
            break
    return prefix


def _scan_file(path: Path) -> tuple[set[str], list[tuple[int, str]]]:
    """Return (literal codes, [(lineno, dynamic-prefix), ...]) found in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    code_param_index = _local_code_param_index(tree)
    codes: set[str] = set()
    dynamic: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_attr_call = isinstance(func, ast.Attribute)
        if isinstance(func, ast.Name):
            name = func.id
        elif is_attr_call:
            name = func.attr
        else:
            continue

        value_node = None
        for keyword in node.keywords:
            if keyword.arg == "code":
                value_node = keyword.value
        if value_node is None:
            idx = None
            if name == "CompileDiagnostic":
                idx = 0
            elif name in code_param_index:
                raw_idx, is_method = code_param_index[name]
                idx = raw_idx - 1 if (is_method and is_attr_call) else raw_idx
            if idx is not None and idx >= 0 and len(node.args) > idx:
                value_node = node.args[idx]
        if value_node is None:
            continue

        literal = _string_value(value_node)
        if literal is not None:
            codes.add(literal)
        elif isinstance(value_node, ast.JoinedStr):
            dynamic.append((node.lineno, _joined_str_prefix(value_node)))
        # A bare ast.Name (a forwarded parameter) contributes nothing here -- the real
        # literal is captured at whichever call site supplies that argument.

    # A handful of codes are assigned through a lookup-table remap
    # (``dataclasses.replace(item, code=code_map.get(...))``) rather than a direct call
    # argument. Any dict literal bound to a name containing "code_map" is treated as such
    # a table, and its string values are collected as codes too.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            if not any(isinstance(t, ast.Name) and "code_map" in t.id for t in node.targets):
                continue
            for value_node in node.value.values:
                literal = _string_value(value_node)
                if literal is not None:
                    codes.add(literal)

    return codes, dynamic


def _all_source_codes() -> tuple[set[str], dict[str, list[tuple[int, str]]]]:
    codes: set[str] = set()
    dynamic_by_file: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(COMPILER_DIR.glob("*.py")):
        file_codes, dynamic = _scan_file(path)
        codes.update(file_codes)
        if dynamic:
            dynamic_by_file[path.name] = dynamic
    return codes, dynamic_by_file


def _documented_codes() -> set[str]:
    text = DOC_PATH.read_text(encoding="utf-8")
    return {match for match in _extract_table_codes(text)}


def _extract_table_codes(text: str) -> list[str]:
    import re

    # Every catalog row starts with "| `<code>` |" (a Markdown table cell holding one
    # inline-code diagnostic code).
    return re.findall(r"^\|\s*`([^`]+)`\s*\|", text, flags=re.MULTILINE)


def test_diagnostic_catalog_doc_exists():
    assert DOC_PATH.is_file(), f"expected diagnostic catalog at {DOC_PATH}"


def test_no_dynamically_constructed_codes_are_silently_uncataloged():
    """Guard the AST scan itself: fail loudly if a future ``code=f"..."`` shows up.

    As of this writing every diagnostic code in ``core/compiler`` is a fixed string
    literal. If a genuinely dynamic (non-enumerable) code is introduced, this test must
    be updated deliberately -- either to special-case the new pattern in ``_scan_file``
    (as was done for the ``code_map`` remap) or to document the pattern in
    ``docs/design/diagnostic-codes.md`` and adjust the comparison below accordingly.
    """
    _, dynamic_by_file = _all_source_codes()
    assert dynamic_by_file == {}, (
        "found dynamically-constructed diagnostic code(s) that this static scan cannot "
        f"enumerate as exact literals: {dynamic_by_file!r}. Document the pattern in "
        "docs/design/diagnostic-codes.md and extend the scan/test accordingly."
    )


def test_every_diagnostic_code_is_documented():
    source_codes, _ = _all_source_codes()
    documented = _documented_codes()

    assert source_codes, "expected to find at least one diagnostic code in core/compiler"
    missing = sorted(source_codes - documented)
    assert not missing, (
        "diagnostic code(s) constructed in core/compiler are missing from "
        f"docs/design/diagnostic-codes.md: {missing}. Add a row for each to the catalog."
    )


def test_documented_codes_are_all_still_real():
    """Catch the opposite drift: a catalog row for a code nobody constructs anymore."""
    source_codes, _ = _all_source_codes()
    documented = _documented_codes()

    stale = sorted(documented - source_codes)
    assert not stale, (
        "docs/design/diagnostic-codes.md documents code(s) no longer constructed anywhere "
        f"in core/compiler: {stale}. Remove the stale row(s) or restore the construction site."
    )
