# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Fail-closed structural physical source-binding validation (DD-206 §5, Group B).

DD-206 §5: "The dataplatform owns real database, schema, and table identifiers. The
hub owns the logical source names used by generated models. The scaffold must provide
a validation step that compares package source usage with dataplatform bindings and
fails on missing, unknown, duplicate, or stale entries."

This module implements all four checks. missing / unknown / duplicate are pure
name-matching between what the installed hub package currently declares and what the
dataplatform currently binds -- structural, and independent of any hub commit.
Staleness is different: it is a human-signoff-tracking concept. A binding's
``database``/``schema`` values may have been reviewed and confirmed correct for an
*older* hub commit, and not explicitly re-confirmed since the hub was bumped to a
newer SHA -- even though it still structurally validates by name. That confirmation
is recorded per-source in the dataplatform's own binding file(s), under each source's
native dbt ``meta:`` block (``meta.kairos.verified_hub_sha``, see
``scaffold/dataplatform/models/_sources.yml.template``'s header comment for the
convention). Staleness checking is opt-in: it only runs when a caller passes
``current_hub_sha`` to :func:`validate_source_bindings`; a repo that has not adopted
that convention (or the ``bump-hub``-style SHA pin it is compared against) sees no
behavior change at all.

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

import re
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
FINDING_STALE = "stale"
FINDING_PARSE_ERROR = "parse-error"

#: Matches a full lowercase 40-character git commit SHA. Deliberately a local,
#: duplicate-but-tiny copy of ``cli/shared.py``'s ``_COMMIT_SHA_RE`` rather than an
#: import of it -- this module stays leaf (no ``kairos_ontology.cli`` import) so it
#: is unit-testable without Click, per the module docstring's rule.
_COMMIT_SHA_RE = re.compile(r"[0-9a-f]{40}")

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
    verified_hub_sha: str | None = None

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
            verified_hub_sha = _extract_verified_hub_sha(block)
            for table in block.get("tables") or []:
                if not isinstance(table, dict):
                    continue
                table_name = str(table.get("name") or "").strip()
                if not table_name:
                    continue
                bindings.append(
                    PhysicalSourceBinding(
                        source_name, table_name, database, schema, rel, verified_hub_sha
                    )
                )
    return tuple(bindings), tuple(findings)


def _extract_verified_hub_sha(source_block: dict[str, Any]) -> str | None:
    """Read ``meta.kairos.verified_hub_sha`` off one parsed ``sources:`` block.

    dbt's native ``sources:`` schema already supports an arbitrary ``meta:`` block
    per source -- this is not a new dbt extension, just a new key read from under it
    (see ``scaffold/dataplatform/models/_sources.yml.template``'s header comment).
    Returns ``None`` when the source carries no ``meta:``/``kairos:``/
    ``verified_hub_sha`` at all, or when any of those levels is not a mapping.
    """
    meta = source_block.get("meta")
    if not isinstance(meta, dict):
        return None
    kairos_meta = meta.get("kairos")
    if not isinstance(kairos_meta, dict):
        return None
    raw = kairos_meta.get("verified_hub_sha")
    if raw is None:
        return None
    return str(raw).strip()


def validate_source_bindings(
    project_root: Path,
    *,
    dbt_packages_dir: Path | None = None,
    models_dir: Path | None = None,
    current_hub_sha: str | None = None,
) -> SourceBindingReport:
    """Validate physical source bindings for the dataplatform project at *project_root*.

    Raises :class:`SourceBindingDiscoveryError` when the inputs required to run
    validation at all are absent (``dbt_packages/`` or ``models/`` missing) --
    almost always because ``dbt deps`` has not been run yet. A directory that
    exists but yields zero declared/bound pairs is not itself an error.

    *current_hub_sha*, when given, additionally enables staleness checking (DD-206
    §5's fourth finding type): every physically bound source whose ``meta.kairos.
    verified_hub_sha`` is absent, or does not match *current_hub_sha*, gets one
    :data:`FINDING_STALE` finding (per source, not per table -- confirmation happens
    at the source level). Defaults to ``None``, which skips staleness checking
    entirely -- fully backward compatible with every existing call site.
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

    if current_hub_sha is not None:
        target = current_hub_sha.strip().lower()
        bindings_by_source: dict[str, list[PhysicalSourceBinding]] = {}
        for binding in bound:
            bindings_by_source.setdefault(binding.source_name, []).append(binding)
        for source_name, group in sorted(bindings_by_source.items()):
            recorded = {(b.verified_hub_sha or "").strip().lower() for b in group}
            if recorded == {target}:
                continue  # every binding for this source already confirmed for target
            present = sorted(sha for sha in recorded if sha)
            detail = (
                f"recorded as verified for {', '.join(present)}"
                if present
                else "never recorded as verified for any hub commit"
            )
            findings.append(
                SourceBindingFinding(
                    kind=FINDING_STALE,
                    source_name=source_name,
                    table_name="",
                    message=(
                        f"source '{source_name}' has not been re-confirmed for hub commit "
                        f"{target} ({detail}). Review its physical binding, then run "
                        "`validate-source-bindings --confirm` (or `stamp_verified_bindings`) "
                        "once satisfied it is still correct."
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


# --- stamp_verified_bindings -------------------------------------------------------
#
# What a human runs *after* reviewing physical bindings post hub-bump, to mark every
# currently bound source confirmed for the new hub commit. Deliberately line/regex
# surgical rather than a `yaml.safe_load` + `yaml.dump()` round-trip -- these binding
# files are meant to stay human-edited and readable (comments, key order, quoting
# style), and `cli/shared.py`'s `_rewrite_hub_package_pin`/
# `_rewrite_toolkit_dependency_source` already establish that convention for other
# "surgically update one field in a human-maintained file" cases in this codebase.


@dataclass(frozen=True, slots=True)
class StampedBindingsReport:
    """What :func:`stamp_verified_bindings` actually rewrote."""

    hub_sha: str
    stamped_sources: tuple[str, ...] = ()
    updated_files: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "hub_sha": self.hub_sha,
            "stamped_sources": list(self.stamped_sources),
            "updated_files": list(self.updated_files),
        }


def _indent_of(line: str) -> int:
    stripped = line.lstrip(" \t")
    return len(line) - len(stripped)


def _line_eol(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


def _body_end(lines: list[str], parent_idx: int, parent_indent: int) -> int:
    """First index after *parent_idx* whose (non-blank) indent is <= *parent_indent*.

    This is where the mapping/sequence value that starts right after the line at
    *parent_idx* ends -- everything more indented than *parent_indent* belongs to
    it. Blank lines are skipped over. Returns ``len(lines)`` if the body runs to the
    end of the file.
    """
    i = parent_idx + 1
    n = len(lines)
    while i < n:
        if lines[i].strip() != "" and _indent_of(lines[i]) <= parent_indent:
            return i
        i += 1
    return n


def _find_direct_child(lines: list[str], parent_idx: int, parent_indent: int, key: str) -> int | None:
    """Return the index of a direct ``key:`` child of the mapping at *parent_idx*, if any.

    Only lines at the (auto-detected) indentation of the parent's first child line
    are considered direct children; anything more deeply indented (a child's own
    nested value, e.g. a ``tables:`` list) is skipped over rather than mistaken for
    a sibling key.
    """
    end = _body_end(lines, parent_idx, parent_indent)
    key_re = re.compile(rf"^{re.escape(key)}:(?:\s|$)")
    child_indent: int | None = None
    i = parent_idx + 1
    while i < end:
        line = lines[i]
        if line.strip() == "":
            i += 1
            continue
        indent = _indent_of(line)
        if child_indent is None:
            child_indent = indent
        if indent == child_indent and key_re.match(line.strip()):
            return i
        i += 1
    return None


_SOURCE_LIST_ITEM_RE = re.compile(r"^-\s+name:\s*(\S.*?)\s*$")


def _stamp_source_block(lines: list[str], dash_idx: int, dash_indent: int, sha: str) -> bool:
    """Ensure the source item at *dash_idx* has ``meta.kairos.verified_hub_sha == sha``.

    Mutates *lines* in place -- inserting or replacing whole lines only, so every
    other line (including surrounding blank lines and comments) is left untouched --
    and returns True iff anything actually changed.
    """
    eol = _line_eol(lines[dash_idx]) or "\n"
    quoted = f'"{sha}"'

    meta_idx = _find_direct_child(lines, dash_idx, dash_indent, "meta")
    if meta_idx is None:
        indent = dash_indent + 2
        insert_at = _body_end(lines, dash_idx, dash_indent)
        lines[insert_at:insert_at] = [
            f"{' ' * indent}meta:{eol}",
            f"{' ' * (indent + 2)}kairos:{eol}",
            f"{' ' * (indent + 4)}verified_hub_sha: {quoted}{eol}",
        ]
        return True

    meta_indent = _indent_of(lines[meta_idx])
    kairos_idx = _find_direct_child(lines, meta_idx, meta_indent, "kairos")
    if kairos_idx is None:
        indent = meta_indent + 2
        insert_at = _body_end(lines, meta_idx, meta_indent)
        lines[insert_at:insert_at] = [
            f"{' ' * indent}kairos:{eol}",
            f"{' ' * (indent + 2)}verified_hub_sha: {quoted}{eol}",
        ]
        return True

    kairos_indent = _indent_of(lines[kairos_idx])
    sha_idx = _find_direct_child(lines, kairos_idx, kairos_indent, "verified_hub_sha")
    if sha_idx is None:
        indent = kairos_indent + 2
        insert_at = _body_end(lines, kairos_idx, kairos_indent)
        lines.insert(insert_at, f"{' ' * indent}verified_hub_sha: {quoted}{eol}")
        return True

    old_line = lines[sha_idx]
    indent = _indent_of(old_line)
    new_line = f"{' ' * indent}verified_hub_sha: {quoted}{_line_eol(old_line) or eol}"
    if old_line == new_line:
        return False
    lines[sha_idx] = new_line
    return True


def _stamp_source_meta(content: str, sha: str) -> tuple[str, tuple[str, ...]]:
    """Stamp every source under one file's top-level ``sources:`` key to *sha*.

    Returns the (possibly unchanged) rewritten content and the names of every
    source found -- regardless of whether stamping it actually changed anything,
    since a source already correctly stamped still counts as "covered" for the
    caller's report.
    """
    lines = content.splitlines(keepends=True)
    stamped: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        if _indent_of(line) == 0 and line.strip() == "sources:":
            source_list_end = _body_end(lines, i, 0)
            item_indent: int | None = None
            j = i + 1
            while j < source_list_end:
                item_line = lines[j]
                if item_line.strip() == "":
                    j += 1
                    continue
                indent = _indent_of(item_line)
                if item_indent is None:
                    item_indent = indent
                if indent == item_indent:
                    match = _SOURCE_LIST_ITEM_RE.match(item_line.strip())
                    if match is not None:
                        source_name = match.group(1)
                        _stamp_source_block(lines, j, item_indent, sha)
                        stamped.append(source_name)
                        j = _body_end(lines, j, item_indent)
                        source_list_end = _body_end(lines, i, 0)
                        continue
                j += 1
            i = source_list_end
            continue
        i += 1
    return "".join(lines), tuple(stamped)


def stamp_verified_bindings(
    project_root: Path,
    hub_sha: str,
    *,
    models_dir: Path | None = None,
) -> StampedBindingsReport:
    """Stamp every physically bound source's ``meta.kairos.verified_hub_sha`` to *hub_sha*.

    This is what a human runs after reviewing bindings post hub-bump: it marks every
    source currently declared in the dataplatform's own binding file(s) (the same
    ``models/**/*.yml``/``.yaml`` files with a top-level ``sources:`` key that
    :func:`discover_physical_bindings` reads) as confirmed correct for *hub_sha*,
    rewriting only the ``meta.kairos.verified_hub_sha`` line(s) via surgical,
    indentation-based line edits -- never a full ``yaml.dump()`` round-trip -- so
    every other line, comment, and formatting choice in a human-edited binding file
    is left byte-for-byte unchanged.

    Returns a :class:`StampedBindingsReport` listing which source names were found
    (and (re)stamped) and which files were actually rewritten on disk; a file with
    no top-level ``sources:`` key is left untouched, and a file whose sources were
    already stamped for *hub_sha* is not rewritten even though its sources are still
    reported as covered.
    """
    normalized = hub_sha.strip().lower()
    if not _COMMIT_SHA_RE.fullmatch(normalized):
        raise ValueError("hub_sha must be a 40-character hexadecimal commit SHA")

    project_root = Path(project_root).resolve()
    resolved_models_dir = (
        Path(models_dir).resolve() if models_dir is not None else project_root / "models"
    )
    if not resolved_models_dir.is_dir():
        return StampedBindingsReport(hub_sha=normalized)

    stamped_sources: set[str] = set()
    updated_files: list[str] = []
    paths = sorted({*resolved_models_dir.rglob("*.yml"), *resolved_models_dir.rglob("*.yaml")})
    for path in paths:
        content = path.read_text(encoding="utf-8")
        data, error = _load_yaml(path)
        if error is not None or not isinstance(data, dict) or "sources" not in data:
            continue
        new_content, names = _stamp_source_meta(content, normalized)
        stamped_sources.update(names)
        if new_content != content:
            path.write_text(new_content, encoding="utf-8")
            updated_files.append(_relative(path, project_root))

    return StampedBindingsReport(
        hub_sha=normalized,
        stamped_sources=tuple(sorted(stamped_sources)),
        updated_files=tuple(updated_files),
    )
