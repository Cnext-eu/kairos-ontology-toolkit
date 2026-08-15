# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Preview DD-133 3c multi-source conformance before authoring bindings (issue #286).

``plan-sources`` reports, for a canonical class, the grain/identity type-kinds of any
existing bindings already targeting it, and -- when a candidate ``--source`` (plus its
would-be identity ``--key-column``\\ s) is given -- whether that candidate could satisfy
the same DD-133 3c contract if bound directly. It runs the same grain/identity
type-kind comparison :mod:`kairos_ontology.core.compiler.conformance` runs at compile
time, one step earlier in the workflow, using only already-authored evidence (existing
bindings and source vocabularies) -- never a new conformance rule.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .compiler.bindings import EntityBinding, load_entity_binding
from .compiler.dbt_source import resolve_dbt_model_source
from .compiler.result import CompileError
from .fit_report import _sniff_binding_domain, _sniff_binding_target_class, resolve_token_uri
from .ontology_loader import SemanticProfile, load_ontology
from .projections.dbt.policy_normalize import _source_type
from .source_catalog import build_source_catalog


class PlanSourcesError(Exception):
    """Raised for user-facing ``plan-sources`` failures."""


@dataclass(frozen=True, slots=True)
class TypedColumn:
    """One column with its raw source type and canonical type-kind (if recognized)."""

    name: str
    data_type: str
    kind: str | None


@dataclass(frozen=True, slots=True)
class BindingConformanceFact:
    """One existing binding's grain/identity type-kind contract and conformance policy."""

    name: str
    source_path: str
    source_ref: str
    grain: tuple[TypedColumn, ...]
    identity_strategy: str
    identity: tuple[TypedColumn, ...]
    conformance_group: str | None
    source_precedence: int | None
    conflict: str | None
    union_mode: str | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateSourceFact:
    """A not-yet-bound candidate source's identity type-kinds and compatibility verdict."""

    source_system: str
    source_table: str
    key_columns: tuple[TypedColumn, ...]
    compatible: bool | None
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanSourcesResult:
    """Complete advisory report for one canonical class."""

    class_token: str
    class_uri: str
    bindings: tuple[BindingConformanceFact, ...]
    candidate: CandidateSourceFact | None
    warnings: tuple[str, ...] = ()


def _kind(data_type: str) -> str | None:
    spec = _source_type(data_type)
    return spec.kind.value if spec is not None else None


def _typed_columns(names: tuple[str, ...], columns: dict[str, str]) -> tuple[TypedColumn, ...]:
    return tuple(
        TypedColumn(
            name=name,
            data_type=columns.get(name, ""),
            kind=_kind(columns[name]) if name in columns else None,
        )
        for name in names
    )


def _relation_columns(binding: EntityBinding, hub_root: Path, sources_dir: Path) -> dict[str, str]:
    """Return ``{column_name: raw_data_type}`` for *binding*'s resolved source relation."""
    if binding.source.relation:
        if "." not in binding.source.relation:
            return {}
        system, table = binding.source.relation.split(".", 1)
        catalog = build_source_catalog(sources_dir)
        table_columns = catalog.analysis_tables().get(system, {}).get(table, [])
        return {item["name"]: item.get("data_type", "unknown") for item in table_columns}
    if binding.source.dbt_model is not None:
        try:
            relation = resolve_dbt_model_source(binding, hub_root)
        except CompileError:
            return {}
        return {column.name: column.data_type for column in relation.columns}
    return {}


def _find_bindings_for_class(
    loaded, ontology_path: Path, bindings_dir: Path, class_uri: str
) -> list[Path]:
    """Return every binding (not just an unambiguous one) whose target resolves to class_uri."""
    domain = ontology_path.stem
    matches: list[Path] = []
    for path in sorted(bindings_dir.glob("*.binding.yaml")):
        text = path.read_text(encoding="utf-8")
        binding_domain = _sniff_binding_domain(text)
        if binding_domain and binding_domain != domain:
            continue
        token = _sniff_binding_target_class(text)
        if not token:
            continue
        resolved = resolve_token_uri(loaded, ontology_path, token)
        if resolved == class_uri:
            matches.append(path)
    return matches


def _detect_natural_key_mismatches(
    facts: list[BindingConformanceFact],
) -> dict[str, list[str]]:
    """Return ``{binding_name: [warning, ...]}`` for natural-key column-name mismatches.

    Two bindings in the same conformance group that target the same class with
    *different* natural-key column name sets (ordering ignored) cannot satisfy a
    raw multi-source conformance contract — each source has a different natural
    identity column, so the rows cannot be unioned on the same key.
    """
    warnings: dict[str, list[str]] = {}

    groups: dict[str, list[BindingConformanceFact]] = {}
    for fact in facts:
        if fact.conformance_group is None:
            continue
        groups.setdefault(fact.conformance_group, []).append(fact)

    for group, group_facts in groups.items():
        if len(group_facts) < 2:
            continue
        distinct_key_sets: list[tuple[str, set[str]]] = [
            (fact.name, {col.name for col in fact.identity}) for fact in group_facts
        ]
        unique_name_sets = frozenset(frozenset(col_set) for _, col_set in distinct_key_sets)
        if len(unique_name_sets) < 2:
            continue
        for name_a, cols_a in distinct_key_sets:
            for name_b, cols_b in distinct_key_sets:
                if name_a >= name_b:
                    continue
                if cols_a == cols_b:
                    continue
                msg = (
                    f"natural key column names differ across bindings in "
                    f"conformance group '{group}': binding '{name_a}' has keys "
                    f"{sorted(cols_a)}, binding '{name_b}' has keys {sorted(cols_b)}; "
                    "raw conformance is infeasible when sources have different natural "
                    "key columns — route to int_merged__<entity> dbt pattern "
                    "(kairos-develop-dbt-transformation)"
                )
                warnings.setdefault(name_a, []).append(msg)
                warnings.setdefault(name_b, []).append(msg)
    return warnings


def run_plan_sources(
    ontology_path: Path,
    class_token: str,
    *,
    hub_root: Path,
    bindings_dir: Path | None,
    sources_dir: Path,
    source: str | None = None,
    key_columns: tuple[str, ...] = (),
) -> PlanSourcesResult:
    """Report existing bindings' grain/identity type-kinds for *class_token*.

    When *source* is given, additionally reports whether that candidate ``<system>.<table>``
    could satisfy the existing bindings' DD-133 3c identity contract -- comparing canonical
    type-kinds only (kernel.py's own conformance comparison is kind-based, not exact-type
    based). Comparison requires *key_columns* (the candidate's would-be identity columns);
    without them, only the candidate's available columns and types are listed.
    """
    loaded = load_ontology(
        ontology_path, identity_root=hub_root, profile=SemanticProfile.RDFS
    )
    class_uri = resolve_token_uri(loaded, ontology_path, class_token)
    if class_uri is None:
        raise PlanSourcesError(
            f"could not resolve --class {class_token!r} against {ontology_path}"
        )

    warnings: list[str] = []
    class_props = loaded.semantic_index.class_properties(class_uri)
    datatype_count = sum(1 for p in class_props if p.get("property_type") == "datatype")
    if datatype_count == 0:
        warnings.append(
            f"target class {class_uri} has zero datatype properties — "
            "bindings cannot map fields without datatype properties; "
            "enrich the ontology class before authoring bindings "
            "(kairos-design-domain)"
        )

    binding_paths: list[Path] = []
    if bindings_dir is not None and bindings_dir.is_dir():
        binding_paths = _find_bindings_for_class(loaded, ontology_path, bindings_dir, class_uri)

    facts: list[BindingConformanceFact] = []
    for path in binding_paths:
        binding = load_entity_binding(path.read_text(encoding="utf-8"), path=str(path))
        columns = _relation_columns(binding, hub_root, sources_dir)
        source_ref = binding.source.relation or (
            f"dbt:{binding.source.dbt_model.name}" if binding.source.dbt_model else ""
        )
        conformance = binding.conformance
        facts.append(
            BindingConformanceFact(
                name=binding.name,
                source_path=str(path),
                source_ref=source_ref,
                grain=_typed_columns(binding.grain.columns, columns),
                identity_strategy=binding.identity.strategy,
                identity=_typed_columns(binding.identity.source_key, columns),
                conformance_group=conformance.group if conformance else None,
                source_precedence=conformance.source_precedence if conformance else None,
                conflict=conformance.conflict if conformance else None,
                union_mode=conformance.union.mode if conformance else None,
            )
        )

    nk_warnings = _detect_natural_key_mismatches(facts)
    if nk_warnings:
        facts = [
            replace(fact, warnings=tuple(nk_warnings.get(fact.name, ())))
            for fact in facts
        ]

    candidate: CandidateSourceFact | None = None
    if source is not None:
        if "." not in source:
            raise PlanSourcesError(f"--source must be '<system>.<table>', got {source!r}")
        source_system, source_table = source.split(".", 1)
        catalog = build_source_catalog(sources_dir)
        table_columns = catalog.analysis_tables().get(source_system, {}).get(source_table)
        if table_columns is None:
            candidate = CandidateSourceFact(
                source_system=source_system,
                source_table=source_table,
                key_columns=(),
                compatible=None,
                notes=(f"no source vocabulary found for {source} under {sources_dir}",),
            )
        else:
            column_types = {
                item["name"]: item.get("data_type", "unknown") for item in table_columns
            }
            if key_columns:
                typed_keys = _typed_columns(key_columns, column_types)
                notes = [
                    f"column {col.name!r} not found in {source}'s vocabulary"
                    for col in typed_keys
                    if not col.data_type
                ]
                compatible: bool | None = None
                reference = next((fact for fact in facts if fact.identity), None)
                if reference is not None and not notes:
                    ref_kinds = tuple(col.kind for col in reference.identity)
                    candidate_kinds = tuple(col.kind for col in typed_keys)
                    compatible = ref_kinds == candidate_kinds
                    if not compatible:
                        notes.append(
                            f"identity type-kinds {candidate_kinds} do not match existing "
                            f"binding '{reference.name}' identity type-kinds {ref_kinds} — "
                            "raw multi-source conformance would fail; route to "
                            "int_merged__<entity> instead (kairos-develop-dbt-transformation)"
                        )
                elif reference is None:
                    notes.append("no existing binding's identity to compare against yet")
                candidate = CandidateSourceFact(
                    source_system=source_system,
                    source_table=source_table,
                    key_columns=typed_keys,
                    compatible=compatible,
                    notes=tuple(notes),
                )
            else:
                candidate = CandidateSourceFact(
                    source_system=source_system,
                    source_table=source_table,
                    key_columns=tuple(
                        TypedColumn(
                            name=item["name"],
                            data_type=item.get("data_type", "unknown"),
                            kind=_kind(item.get("data_type", "")),
                        )
                        for item in table_columns
                    ),
                    compatible=None,
                    notes=(
                        "pass --key-column to compare identity type-kinds against "
                        "existing bindings",
                    ),
                )

    return PlanSourcesResult(
        class_token=class_token,
        class_uri=class_uri,
        bindings=tuple(facts),
        candidate=candidate,
        warnings=tuple(warnings),
    )
