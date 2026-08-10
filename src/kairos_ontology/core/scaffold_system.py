# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Core logic for ``kairos-ontology scaffold-system``.

A batch entry point over ``scaffold-binding`` (``core/scaffold_binding.py``) and
``propose-alignment`` (``core/propose_alignment.py``): for every table under
``integration/sources/<system>/`` that has no ``EntityBinding`` yet
(:func:`kairos_ontology.core.scaffold_binding.list_unscaffolded_tables`), decide whether it is a
good ``passthrough`` candidate and, if so, scaffold it -- then compile every domain touched and
produce one review report.

**Where the ``--target-class`` comes from.** This module never guesses an accelerator class: it
only reuses whatever ``propose-alignment`` already proposed for the table, read back from its
persisted ``<domain>-alignment.yaml`` (``propose_alignment.alignment_to_dict``'s on-disk shape)
under ``_analysis/``. A ``TableAlignment.ref_class`` is a bare accelerator class *name* (e.g.
``"TradeParty"``, not a full IRI or ``prefix:Local`` qname -- see
:func:`kairos_ontology.core.propose_alignment.align_table`), so it is resolved to a full class
URI via the same ``extract_ref_model_inventory`` lookup ``propose-alignment`` itself used to
build the class pool the LLM chose from (keyed off the alignment document's own
``domain_uris``). A table with no alignment evidence, or whose ``ref_class`` cannot be re-
resolved, is **declined**, never scaffolded against an invented guess.

**The "mechanical passthrough candidate" heuristic (:func:`_decline_if_not_mechanical`) is a
first cut, not a sophisticated classifier.** Nothing in ``analyse-sources`` or
``propose-alignment`` today distinguishes a "mechanical" single-source table from one that
genuinely needs multi-source conformance design, so this module applies two narrow, explicit,
easily-overridden checks instead of inventing a heavier one:

1. ``ref_class_confidence`` (as reported by ``propose-alignment``) must meet
   :data:`MIN_REF_CLASS_CONFIDENCE`.
2. no *other* table in the same ``<domain>-alignment.yaml`` claims the same ``ref_class`` --
   two source tables both aligning to one accelerator class is exactly the shape of a
   multi-source merge that a mechanical, single-table ``passthrough`` binding cannot express
   (that is what the ``merged-master`` archetype and its survivorship ``conformance:`` are for).

Either check failing declines the table as ``non-mechanical`` with the evidence spelled out in
the decline detail, so a human can override the call (via plain ``scaffold-binding``) when the
heuristic is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from .compiler import CompileMode, compile_domain
from .propose_alignment import extract_ref_model_inventory
from .scaffold_binding import (
    ScaffoldBindingError,
    list_source_tables,
    list_unscaffolded_tables,
    run_scaffold_binding,
)

SCHEMA_VERSION = 1

#: scaffold-system only ever attempts the ``passthrough`` archetype -- the one archetype whose
#: fields (grain, identity) are fully mechanically derivable with no irreducible modeling
#: judgement (see ``scaffold_binding.py``'s module docstring). Every other archetype scaffolds a
#: skeleton with sentinel placeholders that intentionally require a human, which is exactly the
#: "needs design" case this batch command declines rather than attempts.
ARCHETYPE_ID = "passthrough"

#: First-cut heuristic threshold (see module docstring) -- a ``propose-alignment`` table→class
#: confidence below this is treated as too weak to scaffold mechanically.
MIN_REF_CLASS_CONFIDENCE = 0.5


class ScaffoldSystemError(ValueError):
    """Raised for a user-facing ``scaffold-system`` failure (e.g. unknown --system)."""


# --------------------------------------------------------------------------------------
# Result shape (plain dataclasses, JSON/dict friendly, no CLI dependency).
# --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ScaffoldSystemDecline:
    """One table this run considered but did not scaffold, and why."""

    table: str
    reason: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"table": self.table, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ScaffoldSystemCompileDiagnostic:
    """One ``compile --check`` finding attributed back to a specific scaffolded binding."""

    code: str
    message: str
    severity: str
    pointer: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "pointer": self.pointer,
        }


@dataclass(frozen=True, slots=True)
class ScaffoldSystemTableResult:
    """One table successfully scaffolded (or previewed, under ``--dry-run``) this run."""

    table: str
    domain: str
    target_class: str
    binding_path: Path
    written: bool
    mapped_columns: tuple[str, ...] = ()
    technical_field_columns: tuple[str, ...] = ()
    orphan_columns: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    compile_diagnostics: tuple[ScaffoldSystemCompileDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "domain": self.domain,
            "target_class": self.target_class,
            "binding_path": str(self.binding_path),
            "written": self.written,
            "mapped_columns": list(self.mapped_columns),
            "technical_field_columns": list(self.technical_field_columns),
            "orphan_columns": list(self.orphan_columns),
            "notes": list(self.notes),
            "compile_diagnostics": [item.to_dict() for item in self.compile_diagnostics],
        }


@dataclass(frozen=True, slots=True)
class ScaffoldSystemResult:
    """The single review report for one ``scaffold-system`` run."""

    system: str
    dry_run: bool
    scaffolded: tuple[ScaffoldSystemTableResult, ...]
    declined: tuple[ScaffoldSystemDecline, ...]
    domains_compiled: tuple[str, ...]
    notes: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "system": self.system,
            "dry_run": self.dry_run,
            "scaffolded": [item.to_dict() for item in self.scaffolded],
            "declined": [item.to_dict() for item in self.declined],
            "domains_compiled": list(self.domains_compiled),
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------------------
# propose-alignment evidence lookup (reuses the on-disk shape written by
# propose_alignment.alignment_to_dict / write_alignment_output; never reparses the LLM prompt).
# --------------------------------------------------------------------------------------
def _find_alignment_entry(
    analysis_dir: Path, system: str, table: str
) -> tuple[Path, dict[str, Any], dict[str, Any]] | None:
    """Return ``(alignment_path, document, table_dict)`` for the table's alignment evidence.

    Mirrors :func:`kairos_ontology.core.fit_report._find_source_alignment`'s table lookup, but
    also returns the parsed top-level document -- this caller additionally needs ``domain`` and
    ``domain_uris`` (fit-report's per-table evidence does not). Returns ``None`` when no
    ``*-alignment.yaml`` under *analysis_dir* records this ``(system, table)``.
    """
    for path in sorted(analysis_dir.glob("*-alignment.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(document, dict):
            continue
        for table_dict in document.get("tables", ()) or ():
            if not isinstance(table_dict, dict):
                continue
            if (
                str(table_dict.get("system", "")).lower() == system.lower()
                and str(table_dict.get("table", "")).lower() == table.lower()
            ):
                return path, document, table_dict
    return None


def _resolve_target_class(
    document: dict[str, Any],
    table_dict: dict[str, Any],
    *,
    catalog_path: Path | None,
) -> tuple[str | None, str, str]:
    """Resolve propose-alignment's ``ref_class`` (a bare class name) to a full class URI.

    Returns ``(class_uri, domain, "")`` on success. Returns ``(None, domain, detail)`` when the
    evidence cannot be turned into a scaffoldable target class -- *domain* is still returned
    (best-effort, from the alignment document) so the caller's decline message has context; a
    class is never guessed.
    """
    domain = str(document.get("domain") or "")
    ref_class = str(table_dict.get("ref_class") or "")
    if not ref_class:
        status = table_dict.get("ref_class_status", "unmatched")
        return (
            None,
            domain,
            (
                f"propose-alignment recorded no confident accelerator class for this table "
                f"(ref_class_status={status!r})."
            ),
        )
    domain_uris = [str(uri) for uri in (document.get("domain_uris") or ())]
    if not domain_uris:
        return (
            None,
            domain,
            (
                f"propose-alignment evidence has no domain_uris (accelerator owl:imports) recorded "
                f"alongside ref_class {ref_class!r}; cannot resolve it to a class URI."
            ),
        )
    try:
        inventory = extract_ref_model_inventory(domain_uris, catalog_path)
    except Exception as exc:  # noqa: BLE001 - a broken accelerator checkout must not crash the batch
        return (
            None,
            domain,
            (
                f"could not resolve the accelerator class inventory for ref_class {ref_class!r} "
                f"(domain_uris={domain_uris}): {exc}"
            ),
        )
    match = next((cls for cls in inventory if str(cls.get("name")) == ref_class), None)
    if match is None:
        return (
            None,
            domain,
            (
                f"propose-alignment's ref_class {ref_class!r} does not resolve to any class in the "
                f"accelerator inventory for domain_uris={domain_uris} (stale or renamed evidence -- "
                "re-run propose-alignment, or scaffold this table by hand with `scaffold-binding "
                "--target-class`)."
            ),
        )
    class_uri = str(match.get("uri") or "")
    if not class_uri:
        return (
            None,
            domain,
            f"accelerator class {ref_class!r} has no URI in the resolved inventory.",
        )
    return class_uri, domain, ""


def _decline_if_not_mechanical(
    document: dict[str, Any], table_dict: dict[str, Any], ref_class: str
) -> str | None:
    """Apply the module docstring's first-cut passthrough-candidate heuristic.

    Returns a decline detail string when the table looks like it needs design (low-confidence
    class match, or another table in the same alignment run claims the same class -- a multi-
    source-merge signal), or ``None`` when it looks mechanical enough for a passthrough scaffold.
    """
    confidence = float(table_dict.get("ref_class_confidence") or 0.0)
    if confidence < MIN_REF_CLASS_CONFIDENCE:
        return (
            f"propose-alignment's ref_class_confidence ({confidence:.2f}) is below the "
            f"{MIN_REF_CLASS_CONFIDENCE:.2f} first-cut threshold for a mechanical passthrough "
            "scaffold; review the alignment by hand."
        )
    this_key = (str(table_dict.get("system", "")), str(table_dict.get("table", "")))
    claimants = sorted(
        f"{other.get('system')}.{other.get('table')}"
        for other in document.get("tables", ()) or ()
        if isinstance(other, dict)
        and other.get("ref_class") == ref_class
        and (str(other.get("system", "")), str(other.get("table", ""))) != this_key
    )
    if claimants:
        return (
            f"ref_class {ref_class!r} is also claimed by {', '.join(claimants)} in the same "
            "propose-alignment run -- likely needs a merged-master/conformance design rather "
            "than a single-table passthrough (first-cut heuristic; verify by hand)."
        )
    return None


# --------------------------------------------------------------------------------------
# Entry point.
# --------------------------------------------------------------------------------------
def run_scaffold_system(
    hub_root: Path,
    *,
    system: str,
    accelerator: str | None = None,
    ref_models_dir: Path | None = None,
    catalog_path: Path | None = None,
    analysis_dir: Path | None = None,
    platform: str = "fabric",
    dry_run: bool = False,
) -> ScaffoldSystemResult:
    """Scaffold every good ``passthrough`` candidate under ``integration/sources/<system>/``.

    For every table (not just the unscaffolded ones -- an already-bound table is reported as
    declined with reason ``already-covered`` rather than silently omitted):

    1. Skip (``already-covered``) if an ``EntityBinding`` already targets it.
    2. Look up ``propose-alignment`` evidence for it under *analysis_dir*; decline
       (``no-alignment-evidence``) if none exists.
    3. Resolve its ``ref_class`` to a full accelerator class URI; decline (``ambiguous-class`` /
       ``ambiguous-domain``) if it cannot be resolved.
    4. Apply the first-cut mechanical-passthrough heuristic; decline (``non-mechanical``) if it
       fails.
    5. Call :func:`kairos_ontology.core.scaffold_binding.run_scaffold_binding` for every
       remaining candidate (``dry_run`` is forwarded unchanged); decline (``scaffold-failed``)
       on a :class:`ScaffoldBindingError`.

    Then, unless *dry_run*, ``compile --check`` (:func:`kairos_ontology.core.compiler.compile_domain`)
    every domain touched by a written binding, and attributes each diagnostic back to the
    scaffolded binding it points at (by file name).
    """
    all_tables = sorted(list_source_tables(hub_root, system))
    if not all_tables:
        raise ScaffoldSystemError(
            f"no tables found under integration/sources/{system}/ (unknown --system, or the "
            "Bronze vocabulary has not been imported yet)."
        )
    unscaffolded = set(list_unscaffolded_tables(hub_root, system))
    has_analysis = analysis_dir is not None and analysis_dir.is_dir()

    scaffolded: list[ScaffoldSystemTableResult] = []
    declined: list[ScaffoldSystemDecline] = []
    domains_touched: set[str] = set()

    for table in all_tables:
        if table not in unscaffolded:
            declined.append(
                ScaffoldSystemDecline(
                    table, "already-covered", "an EntityBinding already targets this table."
                )
            )
            continue

        entry = _find_alignment_entry(analysis_dir, system, table) if has_analysis else None
        if entry is None:
            declined.append(
                ScaffoldSystemDecline(
                    table,
                    "no-alignment-evidence",
                    f"no propose-alignment evidence found for {system}.{table}"
                    + (f" under {analysis_dir}" if analysis_dir is not None else "")
                    + "; run `kairos-ontology propose-alignment` first.",
                )
            )
            continue
        _alignment_path, document, table_dict = entry
        ref_class = str(table_dict.get("ref_class") or "")

        class_uri, domain, detail = _resolve_target_class(
            document, table_dict, catalog_path=catalog_path
        )
        if class_uri is None:
            declined.append(ScaffoldSystemDecline(table, "ambiguous-class", detail))
            continue
        if not domain:
            declined.append(
                ScaffoldSystemDecline(
                    table,
                    "ambiguous-domain",
                    "propose-alignment evidence does not declare a domain for this table.",
                )
            )
            continue

        non_mechanical = _decline_if_not_mechanical(document, table_dict, ref_class)
        if non_mechanical is not None:
            declined.append(ScaffoldSystemDecline(table, "non-mechanical", non_mechanical))
            continue

        try:
            result = run_scaffold_binding(
                hub_root,
                system=system,
                table=table,
                archetype_id=ARCHETYPE_ID,
                target_class=class_uri,
                domain=domain,
                force=False,
                ref_models_dir=ref_models_dir,
                catalog_path=catalog_path,
                accelerator=accelerator,
                analysis_dir=analysis_dir,
                platform=platform,
                dry_run=dry_run,
            )
        except ScaffoldBindingError as exc:
            declined.append(ScaffoldSystemDecline(table, "scaffold-failed", str(exc)))
            continue

        scaffolded.append(
            ScaffoldSystemTableResult(
                table=table,
                domain=result.domain,
                target_class=result.target_class,
                binding_path=result.binding_path,
                written=result.written,
                mapped_columns=result.mapped_columns,
                technical_field_columns=result.technical_field_columns,
                orphan_columns=result.orphan_columns,
                notes=result.notes,
            )
        )
        if result.written:
            domains_touched.add(result.domain)

    notes: list[str] = []
    domains_compiled: tuple[str, ...] = ()
    if dry_run:
        if scaffolded:
            notes.append(
                "dry-run: compile diagnostics are not available -- no bindings were written to "
                "compile against."
            )
    elif domains_touched:
        domains_compiled = tuple(sorted(domains_touched))
        diagnostics_by_binding_name: dict[str, list[ScaffoldSystemCompileDiagnostic]] = {}
        for domain in domains_compiled:
            compiled = compile_domain(hub_root, domain, mode=CompileMode.CHECK)
            for item in compiled.diagnostics.ordered:
                if not item.location.path:
                    continue
                diagnostics_by_binding_name.setdefault(Path(item.location.path).name, []).append(
                    ScaffoldSystemCompileDiagnostic(
                        code=item.code,
                        message=item.message,
                        severity=item.severity.value,
                        pointer=item.location.pointer,
                    )
                )
        if diagnostics_by_binding_name:
            scaffolded = [
                replace(
                    table_result,
                    compile_diagnostics=tuple(
                        diagnostics_by_binding_name.get(table_result.binding_path.name, ())
                    ),
                )
                for table_result in scaffolded
            ]

    return ScaffoldSystemResult(
        system=system,
        dry_run=dry_run,
        scaffolded=tuple(scaffolded),
        declined=tuple(declined),
        domains_compiled=domains_compiled,
        notes=tuple(notes),
    )
