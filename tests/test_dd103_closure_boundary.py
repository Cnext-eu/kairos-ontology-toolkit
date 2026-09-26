# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Every rdflib parse outside the loader is inventoried with a reason (DD-243).

DD-103 makes ``load_ontology`` the one semantic-loading API, because a domain ``.ttl`` read
alone is missing what its ``owl:imports`` bring in. Nothing enforced that: the audit behind
DD-243 found four user-facing readers that parsed one file and reported its classes as the
whole story. This test pins every ``Graph().parse`` call site in production code to
``docs/dev/dd103-single-file-parse-inventory.json``, where each carries a reason a reviewer
can check. A new site fails the suite until it is either routed through ``load_ontology``
or added with a reason; a removed site fails until its row is deleted.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "kairos_ontology"
INVENTORY_PATH = ROOT / "docs" / "dev" / "dd103-single-file-parse-inventory.json"

#: The loader owns the closure; its parses are the point.
EXEMPT_MODULES = {"core/ontology_loader.py"}

#: Why a parse may legitimately read one file. ``single-file-semantics`` is a known gap
#: (a reader that should use the closure and does not yet); every such row names the
#: decision that tracks it, and the row disappears when the reader is fixed.
REASONS = {
    "syntax": "checks that the text parses; reads no meaning from it",
    "iri": "reads the owl:Ontology IRI or version only",
    "imports": "reads the authored owl:imports edges only",
    "declaration": "reports what this one file declares, by design (documented in the function)",
    "bronze-vocabulary": "a source vocabulary; has no owl:imports",
    "mapping": "a mapping / SKOS document, not an ontology",
    "extension": "a kairos-ext, DDD overlay or policy extension merged onto a loaded closure",
    "shapes": "a SHACL shapes graph",
    "glossary": "a businessdiscovery glossary",
    "vocabulary": "a toolkit-shipped vocabulary (kairos-ddd, kairos-bronze, ...)",
    "legacy-api": "public helper with no internal caller; kept for compatibility",
    "single-file-semantics": "KNOWN GAP: reads meaning from one file; tracked by a DD",
}


def _module_key(path: Path, package: Path = PACKAGE) -> str:
    return path.relative_to(package).as_posix()


def _graph_bound_names(scope_nodes: list[ast.AST]) -> set[str]:
    """Names assigned from ``Graph(...)`` anywhere in the given scopes."""
    names: set[str] = set()
    for scope in scope_nodes:
        for node in ast.walk(scope):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "Graph"
                ):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
    return names


def scan_parse_sites(package: Path = PACKAGE) -> dict[str, set[str]]:
    """``{module: {enclosing function}}`` for every rdflib ``.parse(`` call.

    A call counts when its receiver is ``Graph()``, a name bound from ``Graph(...)`` in the
    same function or module, or when it passes ``format=`` (rdflib's signature; ``ast.parse``
    and ``argparse`` never do). Keyed by function, not line, so an edit inside a function
    does not move the inventory.
    """
    sites: dict[str, set[str]] = {}
    for path in sorted(package.rglob("*.py")):
        key = _module_key(path, package)
        if key in EXEMPT_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        module_names = _graph_bound_names([tree])
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "parse":
                continue
            receiver = node.func.value
            enclosing: list[ast.AST] = []
            cursor = parents.get(node)
            while cursor is not None:
                if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    enclosing.append(cursor)
                cursor = parents.get(cursor)
            local_names = _graph_bound_names(enclosing) | module_names
            is_graph = (
                isinstance(receiver, ast.Call)
                and isinstance(receiver.func, ast.Name)
                and receiver.func.id == "Graph"
            ) or (isinstance(receiver, ast.Name) and receiver.id in local_names)
            has_format = any(keyword.arg == "format" for keyword in node.keywords)
            if not (is_graph or has_format):
                continue
            function = ".".join(reversed([item.name for item in enclosing])) or "<module>"
            sites.setdefault(key, set()).add(function)
    return sites


@pytest.fixture(scope="module")
def inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _inventory_sites(inventory: dict) -> dict[str, set[str]]:
    sites: dict[str, set[str]] = {}
    for row in inventory["sites"]:
        sites.setdefault(row["module"], set()).add(row["function"])
    return sites


def test_every_parse_site_is_inventoried_and_every_row_still_exists(inventory):
    actual = scan_parse_sites()
    expected = _inventory_sites(inventory)
    new = sorted(
        f"{module}::{function}"
        for module, functions in actual.items()
        for function in functions - expected.get(module, set())
    )
    stale = sorted(
        f"{module}::{function}"
        for module, functions in expected.items()
        for function in functions - actual.get(module, set())
    )
    assert not new, (
        "rdflib parse outside load_ontology with no inventory row (DD-243). If this reads "
        "the meaning of a domain or reference ontology, use core.ontology_loader.load_ontology "
        "and read the closure's semantic_index. Otherwise add the site to "
        f"{INVENTORY_PATH.relative_to(ROOT).as_posix()} with a reason:\n" + "\n".join(new)
    )
    assert not stale, "inventory rows whose parse no longer exists; delete them:\n" + "\n".join(
        stale
    )


def test_every_row_has_a_known_reason_and_known_gaps_name_their_decision(inventory):
    bad = []
    for row in inventory["sites"]:
        if row["reason"] not in REASONS:
            bad.append(f"{row['module']}::{row['function']}: unknown reason {row['reason']!r}")
        if row["reason"] == "single-file-semantics" and not row.get("tracked_by", "").startswith(
            "DD-"
        ):
            bad.append(f"{row['module']}::{row['function']}: known gap must cite a DD")
    assert not bad, "\n".join(bad)


def test_the_reason_vocabulary_is_documented(inventory):
    assert set(inventory["reasons"]) == set(REASONS)


def test_the_scanner_sees_a_new_parse(tmp_path: Path):
    """The guard is only as good as its scanner: a fresh single-file parse must be found,
    whether the receiver is ``Graph()``, a name bound from it, or a call passing ``format=``."""
    package = tmp_path / "pkg"
    (package / "core").mkdir(parents=True)
    (package / "core" / "reader.py").write_text(
        "from rdflib import Graph\n"
        "\n"
        "def inline(path):\n"
        "    return Graph().parse(path)\n"
        "\n"
        "def bound(path):\n"
        "    graph = Graph()\n"
        "    graph.parse(path)\n"
        "    return graph\n"
        "\n"
        "class Loader:\n"
        "    def keyword(self, source, text):\n"
        "        return source.parse(data=text, format='turtle')\n"
        "\n"
        "def not_rdflib(text):\n"
        "    import ast\n"
        "    return ast.parse(text)\n",
        encoding="utf-8",
    )
    assert scan_parse_sites(package) == {"core/reader.py": {"inline", "bound", "Loader.keyword"}}


def test_the_loader_is_the_only_exempt_module(inventory):
    assert set(inventory["exempt_modules"]) == EXEMPT_MODULES
    for module in EXEMPT_MODULES:
        assert (PACKAGE / module).is_file()
