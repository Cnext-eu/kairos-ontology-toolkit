# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Gate A: per-binding conformance to a declared Silver contract (DD-213 §4).

These rules invert the v5 default. Without a contract the bindings *constitute* the Silver
shape, so an ordinary authoring action -- deleting a ``fields:`` entry, reordering it,
onboarding a second source -- silently changes a published contract. With one, the contract
constrains the bindings and a binding either conforms or is reported.

Every rule here is stateless and needs no Git history: it compares one authored binding with
one authored contract, so ``compile --check`` statelessness is preserved (DD-213 §2).

Severity is a parameter, not a constant. The rules shipped at ``warning`` alongside the
advisory slice and are now raised to ``error``: once the contract actually drives emission,
a binding that diverges from it would otherwise emit a shape nobody declared.
"""

from __future__ import annotations

from ..projections.dbt.policy_specs import SilverColumnRole
from ..projections.dbt.silver_contract import canonical_type_label
from ..projections.dbt.specs import SilverModelKind, SilverModelSpec
from .bindings import EntityBinding, ExprColumn
from .contracts import ContractEntity, SilverContract, resolved_column_name
from .result import CompileDiagnostic, DiagnosticSeverity, SourceLocation

#: Column roles the contract governs. Everything else in ``SilverModelSpec.columns`` is
#: compiler-owned (generated keys, entity IRI, DD-104 audit envelope) and is emitted
#: unconditionally, outside the ``closed`` scope.
AUTHORED_ROLES = frozenset(
    {SilverColumnRole.BUSINESS.value, SilverColumnRole.BUSINESS_NATURAL_KEY.value}
)

#: Model kinds that carry the consumer-facing contract. A ``SOURCE_BRANCH`` is an internal
#: implementation detail of a conformance group.
CONTRACT_MODEL_KINDS = frozenset({SilverModelKind.ENTITY, SilverModelKind.UNION})


def models_by_class(models) -> dict[str, SilverModelSpec]:
    """Return ``class URI -> consumer-facing Silver model`` from a shaped project.

    A conformance group emits one ``SOURCE_BRANCH`` per binding plus a ``UNION``; the union
    is what downstream consumers read, so it wins. Both the scaffolder and Gate A go through
    here: if they read different model kinds -- or different pipeline stages -- a generated
    contract would fail the very check that is supposed to accept it.
    """
    result: dict[str, SilverModelSpec] = {}
    for model in models:
        if model.kind not in CONTRACT_MODEL_KINDS:
            continue
        existing = result.get(model.identity.class_uri)
        if existing is None or model.kind is SilverModelKind.UNION:
            result[model.identity.class_uri] = model
    return result


def source_columns_to_properties(
    binding: EntityBinding, source_columns: tuple[str, ...]
) -> list[str]:
    """Map authored SOURCE columns to the canonical property tokens that carry them.

    Reuses the DD-133 §8b rule: a key column is meaningful only through the field whose
    expression is *exactly* that source column. A column buried in a multi-column
    expression, or with no field at all, yields nothing here -- the existing ``identity.*``
    diagnostics already reject that binding, so this must not invent a mapping to paper
    over it.
    """
    result: list[str] = []
    for column in source_columns:
        for field in binding.fields:
            if isinstance(field.expression, ExprColumn) and field.expression.column == column:
                if field.property not in result:
                    result.append(field.property)
                break
    return result


def source_columns_to_emitted(
    binding: EntityBinding, source_columns: tuple[str, ...], entity: ContractEntity
) -> list[str]:
    """Map authored SOURCE key columns to the EMITTED column names carrying them.

    Mirrors the scaffolder's ``_key_columns`` exactly -- both must agree or a generated
    contract would fail the check meant to accept it.
    Three routes, because real bindings use all three: a semantic ``fields:`` entry whose
    expression is exactly that source column; a DD-139 ``technicalFields:`` entry whose
    expression is exactly that source column (its emitted name often differs -- fracht
    grains on ``BL_PK`` through a technical column named ``source_record_id``); or a
    technical entry whose name simply equals the source column.
    """
    technical = {item.name for item in binding.technical_fields}
    result: list[str] = []
    for source_column in source_columns:
        emitted: str | None = None
        for field in binding.fields:
            if (
                isinstance(field.expression, ExprColumn)
                and field.expression.column == source_column
            ):
                item = entity.property_for(field.property)
                emitted = resolved_column_name(item) if item is not None else None
                break
        if emitted is None:
            for item in binding.technical_fields:
                if (
                    isinstance(item.expression, ExprColumn)
                    and item.expression.column == source_column
                ):
                    emitted = item.name
                    break
        if emitted is None and source_column in technical:
            emitted = source_column
        if emitted is not None and emitted not in result:
            result.append(emitted)
    return result


def _emitted_types(model: SilverModelSpec | None) -> dict[str, tuple[str, bool]]:
    """Return ``column name -> (canonical type label, nullable)`` for every emitted column.

    Indexed by name rather than filtered by ``role``: this runs on the adapter's
    ``BoundSources`` candidates, where roles are not assigned yet (shape assigns them), so a
    role filter here would silently match nothing. Only names the *contract* declares are
    ever looked up, and the contract-load rules already reject the reserved shapes
    (``_`` prefix, ``_sk`` suffix) and duplicate names, so a compiler-owned column cannot
    be mistaken for a declared one.
    """
    if model is None:
        return {}
    result: dict[str, tuple[str, bool]] = {}
    for column in model.columns:
        label = (
            canonical_type_label(column.canonical_type)
            if column.canonical_type is not None
            else (column.data_type or "")
        )
        result[column.name] = (label, bool(column.nullable))
    return result


def _diagnostic(
    binding: EntityBinding,
    code: str,
    message: str,
    pointer: str,
    severity: DiagnosticSeverity,
) -> CompileDiagnostic:
    return CompileDiagnostic(
        code=code,
        message=message,
        location=SourceLocation(path=binding.source_path or "<binding>", pointer=pointer),
        severity=severity,
    )


def contract_binding_diagnostics(
    binding: EntityBinding,
    contract: SilverContract | None,
    *,
    model: SilverModelSpec | None = None,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
) -> list[CompileDiagnostic]:
    """Return Gate A diagnostics for one binding against its domain's contract.

    A domain with no contract is ungoverned and yields nothing -- adoption is incremental
    by construction, so an existing hub compiles exactly as it did before (DD-213 §6).
    """
    if contract is None:
        return []

    def report(code: str, message: str, pointer: str) -> None:
        diagnostics.append(_diagnostic(binding, code, message, pointer, severity))

    diagnostics: list[CompileDiagnostic] = []
    entity = contract.entity_for(binding.target_class)
    if entity is None:
        report(
            "contract.class-not-declared",
            (
                f"class '{binding.target_class}' is not declared in "
                f"{contract.source_path or 'the domain contract'}; a governed domain cannot "
                "silently regrow ungoverned entities"
            ),
            "/target/class",
        )
        return diagnostics

    declared = {item.property: item for item in entity.properties}
    mapped = {field.property: index for index, field in enumerate(binding.fields)}
    unmapped = list(binding.unmapped)
    unmapped_set = set(unmapped)

    _check_property_coverage(entity, binding, declared, mapped, unmapped_set, report)
    _check_unmapped_declarations(entity, declared, mapped, unmapped, report)
    _check_types(entity, binding, declared, mapped, model, report)
    _check_grain_and_identity(entity, binding, report)
    _check_closed_surface(entity, binding, report)
    _check_hash_inputs(entity, binding, unmapped_set, report)
    return diagnostics


def _check_property_coverage(entity, binding, declared, mapped, unmapped_set, report) -> None:
    for item in entity.properties:
        if item.property in mapped:
            continue
        if item.required:
            report(
                "contract.required-property-unmapped",
                (
                    f"contract property '{item.property}' is required but this binding maps "
                    "no field to it"
                ),
                "/fields",
            )
        elif item.property not in unmapped_set:
            report(
                "contract.optional-property-undeclared",
                (
                    f"contract property '{item.property}' is optional and unmapped; declare "
                    "it under unmapped: so the gap is reviewed rather than silent"
                ),
                "/fields",
            )

    if entity.closed:
        for index, field in enumerate(binding.fields):
            if field.property not in declared:
                report(
                    "contract.property-not-declared",
                    (
                        f"property '{field.property}' is not declared by the contract for "
                        f"'{entity.target_class}', which is closed"
                    ),
                    f"/fields/{index}/property",
                )


def _check_unmapped_declarations(entity, declared, mapped, unmapped, report) -> None:
    for index, qname in enumerate(unmapped):
        pointer = f"/unmapped/{index}"
        item = declared.get(qname)
        if item is None:
            report(
                "contract.unmapped-property-required",
                f"unmapped property '{qname}' is not declared by the contract",
                pointer,
            )
        elif item.required:
            report(
                "contract.unmapped-property-required",
                (
                    f"unmapped property '{qname}' is declared requirement: required; every "
                    "binding must map it"
                ),
                pointer,
            )
        if qname in mapped:
            report(
                "contract.unmapped-property-required",
                f"property '{qname}' is listed under unmapped: but is also mapped in fields:",
                pointer,
            )


def _check_types(entity, binding, declared, mapped, model, report) -> None:
    emitted = _emitted_types(model)
    if not emitted:
        return
    for item in entity.properties:
        index = mapped.get(item.property)
        if index is None:
            continue
        column = resolved_column_name(item)
        actual = emitted.get(column)
        if actual is None:
            continue
        actual_type, actual_nullable = actual
        if actual_type and actual_type != item.type:
            report(
                "contract.type-mismatch",
                (
                    f"column '{column}' resolves to canonical type '{actual_type}' but the "
                    f"contract declares '{item.type}'. Canonical type is inferred from the "
                    "source column, and cast is excluded from the mapping grammar (DD-133 "
                    "§4), so a diverging source type needs a contracted dbt model via "
                    "source.dbtModel"
                ),
                f"/fields/{index}",
            )
        if actual_nullable != item.nullable:
            report(
                "contract.nullability-mismatch",
                (
                    f"column '{column}' resolves to nullable={actual_nullable} but the "
                    f"contract declares nullable={item.nullable}"
                ),
                f"/fields/{index}",
            )


def _check_grain_and_identity(entity, binding, report) -> None:
    grain = source_columns_to_emitted(binding, binding.grain.columns, entity)
    if grain and tuple(grain) != entity.grain:
        report(
            "contract.grain-mismatch",
            (
                f"binding grain resolves to {tuple(grain)} but the contract declares "
                f"{entity.grain}"
            ),
            "/grain/columns",
        )
    if binding.identity.strategy != entity.identity.strategy:
        report(
            "contract.identity-mismatch",
            (
                f"identity strategy '{binding.identity.strategy}' differs from the contract's "
                f"'{entity.identity.strategy}'"
            ),
            "/identity/strategy",
        )
    business_key = source_columns_to_emitted(
        binding, binding.identity.business_key, entity
    )
    if business_key and tuple(business_key) != entity.identity.business_key:
        report(
            "contract.identity-mismatch",
            (
                f"binding businessKey resolves to {tuple(business_key)} but the contract "
                f"declares {entity.identity.business_key}"
            ),
            "/identity/businessKey",
        )


def _check_closed_surface(entity, binding, report) -> None:
    if not entity.closed:
        return
    declared_technical = {item.name for item in entity.technical_columns}
    for index, technical in enumerate(binding.technical_fields):
        if technical.name not in declared_technical:
            report(
                "contract.technical-field-not-declared",
                (
                    f"technical field '{technical.name}' is not declared under "
                    "technicalColumns: for a closed entity"
                ),
                f"/technicalFields/{index}",
            )
    declared_relationships = {
        (item.property, item.target) for item in entity.relationships
    }
    for index, relationship in enumerate(binding.relationships):
        if (relationship.property, relationship.target) not in declared_relationships:
            report(
                "contract.relationship-not-declared",
                (
                    f"relationship '{relationship.property}' -> '{relationship.target}' is "
                    "not declared by the contract for a closed entity"
                ),
                f"/relationships/{index}",
            )


def _check_hash_inputs(entity, binding, unmapped_set, report) -> None:
    """Reject an unmapped property whose source column feeds the SCD2 canonical hash.

    A padded NULL must never participate in change detection: the day the source begins
    supplying the column, every row's hash would change at once and the whole entity would
    re-version (DD-213 §4).
    """
    incremental = getattr(binding.load, "incremental", None)
    if incremental is None or not unmapped_set:
        return
    hash_inputs = set(getattr(incremental, "canonical_hash_inputs", ()) or ())
    if not hash_inputs:
        return
    for qname in sorted(unmapped_set):
        item = entity.property_for(qname)
        if item is None:
            continue
        column = resolved_column_name(item)
        if column in hash_inputs or qname in hash_inputs:
            report(
                "contract.unmapped-in-hash-inputs",
                (
                    f"unmapped property '{qname}' feeds load.incremental.canonicalHashInputs; "
                    "a padded NULL must not participate in change detection or the entity "
                    "re-versions wholesale once the source starts supplying it"
                ),
                "/load/incremental/canonicalHashInputs",
            )


def contract_resolution_diagnostics(
    contract: SilverContract | None,
    context,
    *,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
) -> list[CompileDiagnostic]:
    """Return the contract-load rules that need the ontology closure (DD-213 §4).

    Split from ``contracts.py`` deliberately: those rules are pure document checks, while
    these need the DD-103 semantic index under the ``rdfs`` profile, which only the kernel
    has. Resolution uses the same ``context.klass``/``context.property`` helpers the binding
    path uses, so a contract cannot declare a symbol a binding would be unable to bind.
    """
    if contract is None:
        return []
    diagnostics: list[CompileDiagnostic] = []
    for entity in contract.entities:
        if context.klass(entity.target_class) is None:
            diagnostics.append(
                CompileDiagnostic(
                    code="contract.class-unresolved",
                    message=(
                        f"contract class '{entity.target_class}' does not resolve in the "
                        "ontology import closure, or resolves ambiguously"
                    ),
                    location=SourceLocation(
                        path=contract.source_path or "<contract>",
                        pointer=f"{entity.pointer}/class",
                    ),
                    severity=severity,
                )
            )
        for item in entity.properties:
            if context.property(item.property) is None:
                diagnostics.append(
                    CompileDiagnostic(
                        code="contract.property-unresolved",
                        message=(
                            f"contract property '{item.property}' does not resolve in the "
                            "ontology import closure, or resolves to more than one property "
                            "URI; qualify it with the owning namespace to disambiguate"
                        ),
                        location=SourceLocation(
                            path=contract.source_path or "<contract>",
                            pointer=item.pointer,
                        ),
                        severity=severity,
                    )
                )
    return diagnostics
