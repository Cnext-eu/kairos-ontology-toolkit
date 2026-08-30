# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Promote a dataplatform-authored contracted dbt transform into the hub (issue #634).

Today a hand-authored ``int_merged__<entity>``/``int_<source>__<entity>`` model can only
be authored/iterated inside the ontology hub, because :func:`~.dbt_contracts.scan_dbt_contracts`
hard-requires the scanned tree to be inside the hub root to resolve ``target_class`` and check
hub-wide ``virtual_source_iri`` uniqueness (see :mod:`.dbt_contract_lint`). This module is the
mechanical "copy, then validate" step that lets an engineer instead author and test the model
as an ordinary local dbt model in their own dataplatform repo, then promote the finished model
into the hub in one step.

This is a **copy**, not a move: the source SQL and properties YAML in the dataplatform repo are
never touched or deleted. Validation happens strictly *after* copying (there is no way to fully
validate pre-copy, for the reason above); a validation failure rolls back by deleting the two
files this module just wrote, so an invalid model is never left sitting in the hub tree.

Deliberately does **not** wire the EntityBinding (``source.dbtModel.{name,sqlPath,contractPath}``)
or record a Decision Log entry -- both stay manual follow-up steps for the binding author,
exactly as issue #634 scopes it.
"""

from __future__ import annotations

import copy
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .dbt_contract_lint import (
    ClassResolver,
    DbtContractLintReport,
    _INTERMEDIATE_PREFIXES,
    run_dbt_contract_lint,
)


class PromoteTransformError(ValueError):
    """Raised for a user-facing ``promote-transform`` failure."""


class PromoteTransformValidationError(PromoteTransformError):
    """Raised when the promoted model fails the hub contract validator.

    By the time this is raised, the two just-written destination files have already been
    deleted (rollback) -- the caller only needs to report *why*, not clean up.
    """

    def __init__(self, model_name: str, report: DbtContractLintReport) -> None:
        self.model_name = model_name
        self.report = report
        error_summary = "; ".join(f"{f.path}: {f.message}" for f in report.errors)
        super().__init__(
            f"model {model_name!r} failed contract validation after promotion into the hub "
            f"(rolled back -- nothing was left behind): {error_summary}"
        )


@dataclass(frozen=True, slots=True)
class PromoteTransformResult:
    """Everything written (or, in dry-run, that would be written) for one promoted model."""

    model_name: str
    domain: str
    sql_source_path: Path
    properties_source_path: Path
    sql_dest_path: Path
    properties_dest_path: Path
    sql_written: bool
    properties_written: bool
    #: ``None`` in dry-run (validation is reported as "would run", never actually run).
    validation_report: DbtContractLintReport | None
    notes: tuple[str, ...] = field(default_factory=tuple)


def _dbt_project_root_candidates(start: Path) -> list[Path]:
    """Return *start* plus every ancestor up to (and including) a ``dbt_project.yml`` root.

    Mirrors how dbt itself resolves properties files relative to a model file: they may live
    anywhere in the enclosing project, not only next to the ``.sql`` file. Stops climbing once
    the enclosing dbt project root is reached (inclusive) so an unrelated ancestor directory
    outside the dataplatform project is never scanned; also stops at the filesystem root if no
    ``dbt_project.yml`` is found at all (e.g. a bare test fixture with no project file).
    """

    candidates: list[Path] = []
    current = start.resolve()
    while True:
        candidates.append(current)
        if (current / "dbt_project.yml").is_file():
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return candidates


def _extract_model_entry(path: Path, model_name: str) -> dict[str, Any] | None:
    """Return a deep copy of the ``models[]`` entry named *model_name* in *path*, if any.

    Returns ``None`` for an unparseable document, a non-mapping document, a missing/non-list
    ``models`` key, or simply no entry with a matching name -- every one of these just means
    "this file is not the one", not a hard error; the caller decides what "not found anywhere"
    means.
    """

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(document, dict):
        return None
    models = document.get("models")
    if not isinstance(models, list):
        return None
    for entry in models:
        if isinstance(entry, dict) and entry.get("name") == model_name:
            return copy.deepcopy(entry)
    return None


def _find_properties_matches(sql_path: Path, model_name: str) -> list[tuple[Path, dict[str, Any]]]:
    """Search the SQL file's directory and its ancestors for *model_name*'s properties entry.

    Returns every ``(file, entry)`` match found, across every candidate directory -- the
    caller treats more than one distinct matching file as ambiguous, regardless of which
    directory level it came from.
    """

    matches: list[tuple[Path, dict[str, Any]]] = []
    seen_files: set[Path] = set()
    for directory in _dbt_project_root_candidates(sql_path.parent):
        if not directory.is_dir():
            continue
        for candidate in sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")]):
            resolved = candidate.resolve()
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            entry = _extract_model_entry(candidate, model_name)
            if entry is not None:
                matches.append((candidate, entry))
    return matches


def run_promote_transform(
    hub_root: Path,
    sql_path: Path,
    *,
    domain: str,
    properties_path: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    resolve_target_class: ClassResolver | None = None,
) -> PromoteTransformResult:
    """Promote one dataplatform-authored contracted model into *hub_root*.

    *sql_path* is the dataplatform-authored ``.sql`` file; its stem is the model name and must
    match the hub's existing intermediate naming convention (:data:`._INTERMEDIATE_PREFIXES`).
    *properties_path*, if given, is used directly; otherwise the properties entry is
    auto-discovered next to *sql_path* (see :func:`_find_properties_matches`). Never overwrites
    an existing destination file unless *force* is set. *dry_run* reports what would be written
    (and that validation would run) without writing anything.

    A real (non-dry-run) promotion always validates the hub afterward via
    :func:`~.dbt_contract_lint.run_dbt_contract_lint`; a failure deletes both just-written
    destination files and raises :class:`PromoteTransformValidationError`.
    """

    hub_root = Path(hub_root)
    sql_path = Path(sql_path)
    if not sql_path.is_file():
        raise PromoteTransformError(f"{sql_path}: no such SQL file")
    if not domain or not domain.strip():
        raise PromoteTransformError("--domain must be a non-empty string")

    model_name = sql_path.stem
    if not any(model_name.startswith(prefix) for prefix in _INTERMEDIATE_PREFIXES):
        allowed = " or ".join(f"{prefix}<entity>" for prefix in _INTERMEDIATE_PREFIXES)
        raise PromoteTransformError(
            f"{sql_path.name!r} does not match the contracted intermediate naming convention "
            f"({allowed}); rename the model before promoting it. A stg_* staging model is "
            "internal to a hand-authored transform and is never promoted on its own."
        )

    if properties_path is not None:
        properties_path = Path(properties_path)
        entry = _extract_model_entry(properties_path, model_name)
        if entry is None:
            raise PromoteTransformError(
                f"model {model_name!r} was not found in {properties_path}"
            )
        source_properties_path = properties_path
    else:
        matches = _find_properties_matches(sql_path, model_name)
        if not matches:
            raise PromoteTransformError(
                f"no properties YAML entry for model {model_name!r} was found in "
                f"{sql_path.parent} or its parent directories; pass --properties explicitly."
            )
        distinct_files = sorted({path for path, _ in matches})
        if len(distinct_files) > 1:
            listed = ", ".join(str(path) for path in distinct_files)
            raise PromoteTransformError(
                f"model {model_name!r} was found in {len(distinct_files)} properties YAML "
                f"files ({listed}); ambiguous -- pass --properties to disambiguate."
            )
        source_properties_path, entry = matches[0]

    models_dir = (
        hub_root / "integration" / "transforms" / "dbt" / "models" / "intermediate" / domain
    )
    sql_dest_path = models_dir / f"{model_name}.sql"
    properties_dest_path = models_dir / f"{model_name}.yml"

    existing = [path for path in (sql_dest_path, properties_dest_path) if path.is_file()]
    if existing and not force:
        listed = " ".join(
            f"{path} already exists; not overwritten (pass --force)." for path in existing
        )
        raise PromoteTransformError(listed)

    if dry_run:
        return PromoteTransformResult(
            model_name=model_name,
            domain=domain,
            sql_source_path=sql_path,
            properties_source_path=source_properties_path,
            sql_dest_path=sql_dest_path,
            properties_dest_path=properties_dest_path,
            sql_written=False,
            properties_written=False,
            validation_report=None,
            notes=(
                f"dry-run: {sql_dest_path} was not written.",
                f"dry-run: {properties_dest_path} was not written.",
                "dry-run: contract validation (validate-dbt-contracts) was not run.",
            ),
        )

    models_dir.mkdir(parents=True, exist_ok=True)
    document = {"version": 2, "models": [entry]}
    properties_dest_path.write_text(
        yaml.safe_dump(document, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    # Verbatim byte copy -- never a text read/write, which could normalize line endings.
    shutil.copy2(sql_path, sql_dest_path)

    report = run_dbt_contract_lint(hub_root, resolve_target_class=resolve_target_class)
    if not report.passed:
        for path in (sql_dest_path, properties_dest_path):
            if path.is_file():
                path.unlink()
        raise PromoteTransformValidationError(model_name, report)

    return PromoteTransformResult(
        model_name=model_name,
        domain=domain,
        sql_source_path=sql_path,
        properties_source_path=source_properties_path,
        sql_dest_path=sql_dest_path,
        properties_dest_path=properties_dest_path,
        sql_written=True,
        properties_written=True,
        validation_report=report,
    )
