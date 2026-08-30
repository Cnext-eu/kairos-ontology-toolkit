# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Fail-closed structural physical source-binding validation (DD-206 §5, Group B).

DD-206 §5: "The dataplatform owns real database, schema, and table identifiers. The
hub owns the logical source names used by generated models. The scaffold must provide
a validation step that compares package source usage with dataplatform bindings and
fails on missing, unknown, duplicate, or stale entries."

This module implements the **structural** half only: missing / unknown / duplicate.
Staleness (a binding that was valid but no longer matches after a hub bump) needs a
manifest/versioning design that does not exist yet and is explicitly out of scope.

Two authoritative inputs:

1. The compiler's own emitted contracted source declarations -- the hub package's
   ``models/silver/_{source_name}__sources.yml`` catalogs (rendered from
   ``templates/dbt/sources.yml.jinja2``, see ``core/projections/dbt/shape.py``'s
   ``_source_catalogs``) -- are the authoritative list of which logical
   ``(source_name, table_name)`` pairs a package actually references. Once installed
   via ``dbt deps`` they land under ``dbt_packages/<package_name>/models/silver/``
   (dbt always installs a git package with a ``subdirectory:`` at
   ``dbt_packages/<package_name>/``, reproducing that subdirectory's own tree
   verbatim -- ``<package_name>`` comes from the installed package's own
   ``dbt_project.yml`` ``name:``, not from the hub repository name, so this module
   globs across every installed package rather than assuming one fixed name).
2. The dataplatform's own physical binding files: ``models/_sources.yml`` and any
   other ``*.yml``/``*.yaml`` under ``models/`` that also happens to declare a
   top-level ``sources:`` key (dbt itself resolves ``sources:`` blocks merged across
   every properties file in the project, so a user splitting bindings across
   several files is a legitimate pattern this module must also honour).

Leaf module: no :mod:`kairos_ontology.cli` import, so it stays unit-testable without
Click (the same rule ``core/dbt_contract_lint.py`` documents).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .hub_utils import is_scaffold_placeholder_text

SCHEMA_VERSION = 1

SEVERITY_ERROR = "error"

FINDING_MISSING = "missing"
FINDING_UNKNOWN = "unknown"
FINDING_DUPLICATE = "duplicate"
FINDING_PARSE_ERROR = "parse-error"

#: Glob (relative to the dataplatform's ``dbt_packages/`` directory) matching every
#: installed hub package's emitted contracted-source catalog. One level of wildcard
#: for the package name, then the fixed tree the hub always emits into
#: (``core/projections/dbt/shape.py``'s ``_source_catalogs``:
#: ``models/silver/_{source_name}__sources.yml``).
_HUB_SOURCE_CATALOG_GLOB = "*/models/silver/_*__sources.yml"

# Literal placeholder values the dataplatform scaffold writes into a fresh
# `_sources.yml` before a human fills in the real physical location -- see
# `scaffold/dataplatform/models/_sources.yml.template` (`{DATABASE}`/`{SCHEMA}`
# bracket tokens, substituted at scaffold time) and `cli/setup.py`'s
# `init-dataplatform` `_sources.yml` pre-population path (literal
# "your_bronze_database" / "your_bronze_schema" strings). Neither is a `<...>`
# angle-bracket sentinel, so `is_scaffold_placeholder_text` alone would not catch
# them.
_PLACEHOLDER_LITERALS = frozenset(
    {
        "your_bronze_database",
        "your_bronze_schema",
        "{database}",
        "{schema}",
    }
)


class SourceBindingDiscoveryError(RuntimeError):
    """Raised when a required input for source-binding validation is absent.

    Distinct from a validation *finding*: this means the command was not even run
    from a state where validation is possible (e.g. ``dbt deps`` was never run), so
    it is raised rather than folded into the report as a finding.
    """


def _is_placeholder_value(value: str | None) -> bool:
    """Return True when *value* is empty, whitespace, or a known scaffold stub."""
    if value is None:
        return True
    text = value.strip()
    if not text:
        return True
    if text.lower() in _PLACEHOLDER_LITERALS:
        return True
    return is_scaffold_placeholder_text(text)


@dataclass(frozen=True, slots=True)
class _SourcePair:
    source_name: str
    table_name: str


@dataclass(frozen=True, slots=True)
class DeclaredSourceUsage:
    """One ``(source_name, table_name)`` pair the installed hub package declares."""

    source_name: str
    table_name: str
    origin: str


@dataclass(frozen=True, slots=True)
class PhysicalSourceBinding:
    """One ``(source_name, table_name)`` physical binding entry from the dataplatform.

    Field names mirror ``core/compiler/adapter.py``'s ``ResolvedRelation`` vocabulary
    (``database``/``schema``/``table_name``) for consistency across the codebase --
    this dataclass does not import or depend on that class, which belongs to a
    different (hub design-time) context.
    """

    source_name: str
    table_name: str
    database: str
    schema: str
    origin: str

    @property
    def is_placeholder(self) -> bool:
        return _is_placeholder_value(self.database) or _is_placeholder_value(self.schema)


@dataclass(frozen=True, slots=True)
class SourceBindingFinding:
    """One fail-closed verdict: missing, unknown, duplicate, or a parse error."""

    kind: str
    source_name: str
    table_name: str
    message: str
    severity: str = SEVERITY_ERROR

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "source_name": self.source_name,
            "table_name": self.table_name,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class SourceBindingReport:
    """Every finding, plus what was actually scanned and validated."""

    declared_pairs: int = 0
    bound_pairs: int = 0
    validated_pairs: int = 0
    findings: tuple[SourceBindingFinding, ...] = ()
    declared_files: tuple[str, ...] = field(default_factory=tuple)
    binding_files: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "passed": self.passed,
            "declared_pairs": self.declared_pairs,
            "bound_pairs": self.bound_pairs,
            "validated_pairs": self.validated_pairs,
            "declared_files": list(self.declared_files),
            "binding_files": list(self.binding_files),
            "findings": [finding.to_dict() for finding in self.findings],
        }


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _load_yaml(path: Path) -> tuple[Any, str | None]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return None, str(exc)
    return data, None


def discover_declared_source_usage(
    dbt_packages_dir: Path,
    *,
    display_root: Path | None = None,
) -> tuple[tuple[DeclaredSourceUsage, ...], tuple[SourceBindingFinding, ...]]:
    """Parse every installed hub package's ``_{source}__sources.yml`` catalog.

    Only ``(source_name, table_name)`` pairs matter here -- the emitted catalog may
    or may not carry ``database``/``schema`` depending on ``logical_sources_only``
    (see ``sources.yml.jinja2``), but the dataplatform's own binding files are the
    sole authority for physical location regardless.
    """
    root = display_root or dbt_packages_dir
    usages: list[DeclaredSourceUsage] = []
    findings: list[SourceBindingFinding] = []
    if not dbt_packages_dir.is_dir():
        return (), ()

    for path in sorted(dbt_packages_dir.glob(_HUB_SOURCE_CATALOG_GLOB)):
        rel = _relative(path, root)
        data, error = _load_yaml(path)
        if error is not None:
            findings.append(
                SourceBindingFinding(
                    kind=FINDING_PARSE_ERROR,
                    source_name="",
                    table_name="",
                    message=f"{rel}: could not parse YAML ({error})",
                )
            )
            continue
        if not isinstance(data, dict):
            continue
        for block in data.get("sources") or []:
            if not isinstance(block, dict):
                continue
            source_name = str(block.get("name") or "").strip()
            if not source_name:
                continue
            for table in block.get("tables") or []:
                if not isinstance(table, dict):
                    continue
                table_name = str(table.get("name") or "").strip()
                if not table_name:
                    continue
                usages.append(DeclaredSourceUsage(source_name, table_name, rel))
    return tuple(usages), tuple(findings)


def discover_physical_bindings(
    models_dir: Path,
    *,
    display_root: Path | None = None,
) -> tuple[tuple[PhysicalSourceBinding, ...], tuple[SourceBindingFinding, ...]]:
    """Parse every ``models/**/*.yml`` (or ``.yaml``) file that declares ``sources:``.

    dbt itself merges ``sources:`` blocks declared across any number of properties
    files anywhere under ``models/``, so a dataplatform that splits physical
    bindings across several files (e.g. one per source system) is a legitimate
    pattern, not just ``models/_sources.yml``. Files with no top-level ``sources:``
    key (ordinary model properties YAML) are silently skipped.
    """
    root = display_root or models_dir
    bindings: list[PhysicalSourceBinding] = []
    findings: list[SourceBindingFinding] = []
    if not models_dir.is_dir():
        return (), ()

    paths = sorted({*models_dir.rglob("*.yml"), *models_dir.rglob("*.yaml")})
    for path in paths:
        rel = _relative(path, root)
        data, error = _load_yaml(path)
        if error is not None:
            findings.append(
                SourceBindingFinding(
                    kind=FINDING_PARSE_ERROR,
                    source_name="",
                    table_name="",
                    message=f"{rel}: could not parse YAML ({error})",
                )
            )
            continue
        if not isinstance(data, dict) or "sources" not in data:
            continue  # not a dbt sources file -- e.g. an ordinary model properties YAML
        for block in data.get("sources") or []:
            if not isinstance(block, dict):
                continue
            source_name = str(block.get("name") or "").strip()
            if not source_name:
                continue
            database = block.get("database")
            schema = block.get("schema")
            database = "" if database is None else str(database)
            schema = "" if schema is None else str(schema)
            for table in block.get("tables") or []:
                if not isinstance(table, dict):
                    continue
                table_name = str(table.get("name") or "").strip()
                if not table_name:
                    continue
                bindings.append(
                    PhysicalSourceBinding(source_name, table_name, database, schema, rel)
                )
    return tuple(bindings), tuple(findings)


def validate_source_bindings(
    project_root: Path,
    *,
    dbt_packages_dir: Path | None = None,
    models_dir: Path | None = None,
) -> SourceBindingReport:
    """Validate physical source bindings for the dataplatform project at *project_root*.

    Raises :class:`SourceBindingDiscoveryError` when the inputs required to run
    validation at all are absent (``dbt_packages/`` or ``models/`` missing) --
    almost always because ``dbt deps`` has not been run yet. A directory that
    exists but yields zero declared/bound pairs is not itself an error.
    """
    project_root = Path(project_root).resolve()
    packages_dir = (
        Path(dbt_packages_dir).resolve() if dbt_packages_dir is not None else project_root / "dbt_packages"
    )
    resolved_models_dir = (
        Path(models_dir).resolve() if models_dir is not None else project_root / "models"
    )

    if not packages_dir.is_dir():
        raise SourceBindingDiscoveryError(
            f"{packages_dir} does not exist. Run `dbt deps` in the dataplatform project "
            "first so the hub package's models/silver/_{source}__sources.yml catalogs are "
            "installed locally."
        )
    if not resolved_models_dir.is_dir():
        raise SourceBindingDiscoveryError(
            f"{resolved_models_dir} does not exist. Expected the dataplatform's own "
            "models/ directory, containing at least models/_sources.yml."
        )

    declared, declared_parse_findings = discover_declared_source_usage(
        packages_dir, display_root=project_root
    )
    bound, bound_parse_findings = discover_physical_bindings(
        resolved_models_dir, display_root=project_root
    )

    findings: list[SourceBindingFinding] = [*declared_parse_findings, *bound_parse_findings]

    declared_pairs: dict[_SourcePair, list[DeclaredSourceUsage]] = {}
    for usage in declared:
        pair = _SourcePair(usage.source_name, usage.table_name)
        declared_pairs.setdefault(pair, []).append(usage)

    bound_by_pair: dict[_SourcePair, list[PhysicalSourceBinding]] = {}
    for binding in bound:
        pair = _SourcePair(binding.source_name, binding.table_name)
        bound_by_pair.setdefault(pair, []).append(binding)

    validated = 0
    for pair in declared_pairs:
        group = bound_by_pair.get(pair)
        if not group:
            findings.append(
                SourceBindingFinding(
                    kind=FINDING_MISSING,
                    source_name=pair.source_name,
                    table_name=pair.table_name,
                    message=(
                        f"source '{pair.source_name}' table '{pair.table_name}' is used by "
                        "the installed hub package but has no physical binding entry in "
                        "models/_sources.yml (or another models/**/*.yml sources file)."
                    ),
                )
            )
            continue

        distinct_locations = {(binding.database.strip(), binding.schema.strip()) for binding in group}
        if len(distinct_locations) > 1:
            origins = ", ".join(sorted({binding.origin for binding in group}))
            findings.append(
                SourceBindingFinding(
                    kind=FINDING_DUPLICATE,
                    source_name=pair.source_name,
                    table_name=pair.table_name,
                    message=(
                        f"source '{pair.source_name}' table '{pair.table_name}' is bound more "
                        f"than once with conflicting database/schema values across: {origins}."
                    ),
                )
            )
            continue

        if any(binding.is_placeholder for binding in group):
            origins = ", ".join(sorted({binding.origin for binding in group}))
            findings.append(
                SourceBindingFinding(
                    kind=FINDING_MISSING,
                    source_name=pair.source_name,
                    table_name=pair.table_name,
                    message=(
                        f"source '{pair.source_name}' table '{pair.table_name}' has a physical "
                        f"binding entry in {origins}, but its database/schema is still empty "
                        "or an unedited scaffold placeholder."
                    ),
                )
            )
            continue

        validated += 1

    for pair, group in bound_by_pair.items():
        if pair in declared_pairs:
            continue
        origins = ", ".join(sorted({binding.origin for binding in group}))
        findings.append(
            SourceBindingFinding(
                kind=FINDING_UNKNOWN,
                source_name=pair.source_name,
                table_name=pair.table_name,
                message=(
                    f"physical binding entry for source '{pair.source_name}' table "
                    f"'{pair.table_name}' is declared in {origins}, but the installed hub "
                    "package does not use it."
                ),
            )
        )

    findings.sort(key=lambda finding: (finding.kind, finding.source_name, finding.table_name))

    declared_files = tuple(sorted({usage.origin for usage in declared}))
    binding_files = tuple(sorted({binding.origin for binding in bound}))

    return SourceBindingReport(
        declared_pairs=len(declared_pairs),
        bound_pairs=len(bound_by_pair),
        validated_pairs=validated,
        findings=tuple(findings),
        declared_files=declared_files,
        binding_files=binding_files,
    )
