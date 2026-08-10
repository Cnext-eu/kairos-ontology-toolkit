# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Keep the Stage 4 retirement inventory aligned with production imports."""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PACKAGE = SRC / "kairos_ontology"
INVENTORY_PATH = ROOT / "docs" / "design" / "stage4-retirement-import-inventory.json"


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SRC).with_suffix("").parts)


def _resolve_import(importer: str, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = importer.split(".")[:-1]
    keep = len(package) - (node.level - 1)
    prefix = package[:keep]
    if node.module:
        prefix.append(node.module)
    return ".".join(prefix)


def _production_imports() -> dict[str, dict[str, set[str]]]:
    imports: dict[str, dict[str, set[str]]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        importer = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("kairos_ontology."):
                        imports.setdefault(alias.name, {}).setdefault(importer, set()).add("*")
            elif isinstance(node, ast.ImportFrom):
                target = _resolve_import(importer, node)
                if target.startswith("kairos_ontology."):
                    imports.setdefault(target, {}).setdefault(importer, set()).update(
                        alias.name for alias in node.names
                    )
    return imports


def _python_import_targets(root: Path) -> dict[Path, set[str]]:
    imports: dict[Path, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        targets: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                targets.add(node.module)
        imports[path] = targets
    return imports


@pytest.fixture(scope="module")
def inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def test_retirement_import_inventory_matches_python_ast(inventory):
    """Any new production import into a retirement module must be classified first."""
    actual = _production_imports()
    failures: list[str] = []
    for wave in inventory["waves"]:
        for module, details in wave["retired_modules"].items():
            expected = {
                importer: set(symbols) for importer, symbols in details["importers"].items()
            }
            observed = actual.get(module, {})
            if wave.get("status") == "retired":
                expected = {}
            if observed != expected:
                failures.append(
                    f"{module}\n  expected={sorted((k, sorted(v)) for k, v in expected.items())}"
                    f"\n  observed={sorted((k, sorted(v)) for k, v in observed.items())}"
                )
    assert not failures, (
        "Stage 4 production imports changed. Classify the edge in "
        f"{INVENTORY_PATH.relative_to(ROOT)} before changing a deletion wave:\n"
        + "\n".join(failures)
    )


def test_retired_production_markers_are_absent(inventory):
    cleanup_module = PACKAGE / "cli" / "shared.py"
    cleanup_markers = {
        "integration/preparation",
        "kairos-prep",
        ".sessions-projection",
        ".sessions-design-import",
        "release-baseline",
    }
    present = [
        f"{path.relative_to(PACKAGE)}: {marker}"
        for path in sorted(PACKAGE.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".jinja2"}
        for marker in inventory["forbidden_production_markers"]
        if marker in path.read_text(encoding="utf-8")
        and not (path == cleanup_module and marker in cleanup_markers)
    ]
    assert not present, f"retired Stage 4 production markers remain: {present}"


def test_inventory_modules_assets_skills_and_tests_exist(inventory):
    missing: list[str] = []
    for wave in inventory["waves"]:
        retired = wave.get("status") == "retired"
        for module in [*wave["retired_modules"], *wave.get("mixed_modules", {})]:
            path = SRC / Path(*module.split(".")).with_suffix(".py")
            if retired and module in wave["retired_modules"]:
                if path.exists():
                    missing.append(f"{wave['id']}: retired module still exists: {module}")
                with pytest.raises(ModuleNotFoundError):
                    importlib.import_module(module)
            elif not path.is_file():
                missing.append(f"{wave['id']}: module {module}")
        for key in ("scaffold_assets", "tests"):
            for relative in wave[key]:
                exists = (ROOT / relative).is_file()
                if retired and exists:
                    missing.append(f"{wave['id']}: retired {key} still exists: {relative}")
                elif not retired and not exists:
                    missing.append(f"{wave['id']}: {key} {relative}")
        for relative in wave.get("retained_scaffold_assets", []):
            if not (ROOT / relative).is_file():
                missing.append(f"{wave['id']}: retained scaffold asset {relative}")
        for module, symbols in wave.get("retained_modules", {}).items():
            imported = importlib.import_module(module)
            for symbol in symbols:
                if not hasattr(imported, symbol):
                    missing.append(f"{wave['id']}: retained symbol {module}.{symbol}")
    for relative in inventory["stage7_test_architecture"]["retired_test_paths"]:
        if (ROOT / relative).exists():
            missing.append(f"stage7-test-architecture: retired path still exists: {relative}")
    assert not missing, "Inventory contains missing entries:\n" + "\n".join(missing)


def test_managed_skill_reference_inventory_is_complete_and_mirrored(inventory):
    markers = tuple(inventory["managed_skill_reference_markers"])
    actual: set[str] = set()
    for path in sorted((ROOT / ".github" / "skills").glob("*/SKILL.md")):
        content = path.read_text(encoding="utf-8").lower()
        if any(marker in content for marker in markers):
            actual.add(path.relative_to(ROOT).as_posix())

    expected = {
        reference
        for wave in inventory["waves"]
        if wave.get("status") != "retired"
        for reference in wave["managed_skill_references"]
    }
    assert actual == expected

    for reference in expected:
        relative = Path(reference).relative_to(".github/skills")
        scaffold_copy = PACKAGE / "scaffold" / "skills" / relative
        assert scaffold_copy.is_file(), f"missing managed skill mirror: {scaffold_copy}"


def test_removed_subsystems_are_absent_from_cli_help_and_managed_guidance(inventory):
    paths = [
        PACKAGE / "cli" / "main.py",
        ROOT / ".github" / "copilot-instructions.md",
        PACKAGE / "scaffold" / "copilot-instructions.md",
        ROOT / ".github" / "skills" / "kairos-help" / "SKILL.md",
        PACKAGE / "scaffold" / "skills" / "kairos-help" / "SKILL.md",
    ]
    paths.extend(sorted((ROOT / ".github" / "skills").glob("*/SKILL.md")))
    paths.extend(sorted((PACKAGE / "scaffold" / "skills").glob("*/SKILL.md")))

    failures = [
        f"{path.relative_to(ROOT)}: {marker}"
        for path in paths
        for marker in inventory["forbidden_cli_help_markers"]
        if marker in path.read_text(encoding="utf-8")
    ]
    assert not failures, "Removed subsystem references remain:\n" + "\n".join(failures)


def _registered_cli_commands() -> dict[str, str]:
    path = PACKAGE / "cli" / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    commands: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "command"
            ):
                continue
            name = next(
                (
                    keyword.value.value
                    for keyword in decorator.keywords
                    if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
                ),
                node.name.replace("_", "-"),
            )
            commands[name] = node.name
    return commands


def test_inventory_cli_registrations_are_exact(inventory):
    active = {
        command
        for wave in inventory["waves"]
        if wave.get("status") != "retired"
        for command in wave["cli_registrations"]
    }
    obsolete = {
        "capture-dbt-contract-evidence",
        "check-claims",
        "check-projection",
        "check-release",
        "check-transformation-readiness",
        "claims-to-silver-ext",
        "decide-claims",
        "derive-claims",
        "inventory-dbt-candidates",
        "lifecycle",
        "migrate-column-iris",
        "migrate-claims",
        "status",
        "reconstruct-dbt-transformation",
        "sync-dbt-contracts",
    }
    retired = {
        command
        for wave in inventory["waves"]
        if wave.get("status") == "retired"
        for command in wave["cli_registrations"]
    }
    expected = active - retired
    assert active | retired == obsolete
    registrations = _registered_cli_commands()
    assert expected <= registrations.keys()
    assert retired.isdisjoint(registrations)


def test_mixed_modules_classify_retired_and_retained_symbols(inventory):
    for wave in inventory["waves"]:
        for module, classification in wave.get("mixed_modules", {}).items():
            assert classification["retire"] or classification["retain_or_extract"]
            assert classification["retain_or_extract"], (
                f"{module} is not mixed; move it to retired_modules if nothing survives"
            )
            assert classification["reason"]


def test_active_tests_do_not_import_retired_modules(inventory):
    retired = {
        module
        for wave in inventory["waves"]
        if wave.get("status") == "retired"
        for module in wave["retired_modules"]
    }
    violations = [
        f"{path.relative_to(ROOT)}: {target}"
        for path, targets in _python_import_targets(ROOT / "tests").items()
        for target in targets
        if any(target == module or target.startswith(f"{module}.") for module in retired)
    ]
    assert not violations, "Active tests import retired modules:\n" + "\n".join(violations)


def test_active_tests_do_not_invoke_retired_cli_commands(inventory):
    retired = {
        command
        for wave in inventory["waves"]
        if wave.get("status") == "retired"
        for command in wave["cli_registrations"]
    }
    violations: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "invoke"
            ):
                continue
            command = next(
                (
                    item.value
                    for argument in node.args
                    if isinstance(argument, (ast.List, ast.Tuple))
                    for item in argument.elts
                    if isinstance(item, ast.Constant)
                    and isinstance(item.value, str)
                    and item.value in retired
                ),
                None,
            )
            if command:
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {command}")
    assert not violations, "Active tests invoke retired commands:\n" + "\n".join(violations)
