# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Pure Gold profile shaping against the materialized Silver registry."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ..uri_utils import camel_to_snake
from .gold_specs import (
    DimensionalGoldSpec,
    GoldCalendarRoleSpec,
    GoldCalendarSpec,
    GoldColumnSpec,
    GoldContractError,
    GoldMeasureSpec,
    GoldProductLogicalSpec,
    GoldRelationshipSpec,
    GoldSecurityBindingSpec,
    GoldSecurityKind,
    GoldSecuritySpec,
    GoldTableSpec,
)
from .policy_specs import (
    CanonicalTypeKind,
    DimensionExposure,
    DimensionVersionBinding,
    GoldProfileName,
    GoldTableRole,
    MeasureLifecycle,
    MedallionPolicySpec,
    ScdType,
    SilverColumnRole,
)
from .specs import (
    ForeignKeyDescriptorSpec,
    ForeignKeyPolicy,
    SilverForeignKeySpec,
    SilverModelSpec,
    SilverRegistry,
)


@dataclass(frozen=True, slots=True)
class GoldDomainInput:
    """One participating domain's compiled inputs for a Gold product (#744).

    A Gold product is assembled from one compile plan per participating domain, because
    Silver compilation stays per domain -- only Gold shaping spans them.
    """

    policy: MedallionPolicySpec
    registry: SilverRegistry
    silver_models: tuple[SilverModelSpec, ...]
    foreign_keys: ForeignKeyPolicy
    ontology_name: str
    ontology_version: str


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECURITY_BINDING = re.compile(
    r"^(?P<table>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<column>[A-Za-z_][A-Za-z0-9_]*)="
    r"(?P<role>[A-Za-z_][A-Za-z0-9_]*):(?P<kind>RLS|OLS)$"
)
_CALENDAR_ROLE = re.compile(
    r"^(?P<role>[A-Za-z_][A-Za-z0-9_]*)="
    r"(?P<table>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<column>[A-Za-z_][A-Za-z0-9_]*)$"
)
_DAX_REFERENCE = re.compile(r"\[([^\]]+)\]")
# #619 Bug 11: a DAX table reference is either a single-quoted name (DAX never uses single
# quotes for string literals, only table names -- e.g. COUNTROWS('dim_acmeparty')) or a
# bare identifier immediately before a column bracket (e.g. Sales[Amount]). This is a
# heuristic over the expression text, not a full DAX parser, but it catches the exact
# failure mode reported: a measureExpression naming a table that was never emitted.
_DAX_QUOTED_TABLE_REFERENCE = re.compile(r"'([^']+)'")
_DAX_BARE_TABLE_REFERENCE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\[")


def _fail(
    code: str,
    message: str,
    *,
    rule_id: str,
    resource_uri: str = "",
) -> None:
    raise GoldContractError(
        code,
        message,
        rule_id=rule_id,
        resource_uri=resource_uri,
    )


def _local_name(uri: str) -> str:
    return re.split(r"[/#]", uri.rstrip("/#"))[-1]


def _primary_key(model: SilverModelSpec) -> str:
    priorities = (
        "surrogate-join-key",
        "integration-identity",
        "business-natural-key",
        "source-identity",
    )
    for role in priorities:
        for column in model.columns:
            if column.role == role:
                return column.name
    for column in model.columns:
        if column.nullable is False:
            return column.name
    return model.columns[0].name if model.columns else ""


#: Silver column roles always hidden from a report author's field list (#744).
#:
#: The columns a dimensional model needs but nobody browses: the surrogate key, the
#: source-identity and entity-IRI plumbing, load audit columns, and SCD history flags.
#: Hiding is presentation only -- a hidden column still carries its relationships, still
#: answers DAX, and can still be granted or denied by a security role.
#:
#: Matching on the role rather than the name is deliberate. The history flag is
#: authorable and defaults to `is_current` with no leading underscore, and a business
#: column may legitimately end in `_sk`, so a name heuristic would both miss real
#: technical columns and hide real business ones.
#:
#: `business`, `business-natural-key`, `integration-identity` and `mastered-identifier`
#: stay visible: those are the values a business user recognises and filters on.
#: `foreign-key` is deliberately absent -- see `_is_hidden_by_role`.
_HIDDEN_COLUMN_ROLES = frozenset(
    {
        SilverColumnRole.SOURCE_IDENTITY.value,
        SilverColumnRole.SURROGATE_JOIN_KEY.value,
        SilverColumnRole.ENTITY_IRI.value,
        SilverColumnRole.AUDIT.value,
        SilverColumnRole.HISTORY.value,
    }
)


def _is_hidden_by_role(column) -> bool:
    """Return whether *column* is technical enough to hide by default (#744).

    `foreign-key` cannot be decided on the role alone, because the compiler gives that
    one role to two different kinds of column on the same table:

    * the **generated** join column -- the DD-133 `{target}_sk` surrogate and its
      DD-109 `_kairos_fk_*_match_count` sibling. Machinery; hide it.
    * the **mapped** column the join reads from -- e.g. `country_code`, bound to an
      ontology property under DD-107. That is business data a report author will
      legitimately want to slice by, and hiding it was the over-reach this check exists
      to prevent.

    A mapped column carries a `property:` provenance tag and a generated one never does,
    so provenance separates them exactly, with no name matching.
    """
    if column.role in _HIDDEN_COLUMN_ROLES:
        return True
    if column.role != SilverColumnRole.FOREIGN_KEY.value:
        return False
    return not any(item.startswith("property:") for item in column.provenance)


def _qualified_column_names(values: tuple[str, ...], table_name: str) -> frozenset[str]:
    """Return the column part of every ``"Table.column"`` value naming *table_name*.

    Matching is case-insensitive on the table, mirroring `_table_aliases`.
    """
    prefix = f"{table_name.casefold()}."
    return frozenset(
        value.split(".", 1)[1]
        for value in values
        if value.casefold().startswith(prefix) and "." in value
    )


def _hidden_column_names(policy, table_name: str) -> frozenset[str]:
    """Return the column names ``goldHideColumn`` hides on *table_name* (#744).

    The authored companion to the `_HIDDEN_COLUMN_ROLES` default: a column whose role
    reads as business data but which this product does not want in the field list. It
    hides, never removes -- `goldExcludeColumn` (DD-217) is the tool for removal, and the
    two are deliberately separate because hiding is presentation and excluding is a
    projection boundary.
    """
    return _qualified_column_names(
        tuple(getattr(policy.gold, "hidden_columns", ()) or ()), table_name
    )


def _excluded_column_names(policy, table_name: str) -> frozenset[str]:
    """Return the column names ``goldExcludeColumn`` keeps out of *table_name*.

    ``kairos-ext:goldExcludeColumn`` is the column-level projection control a Gold
    product had no way to express (#703): `_columns` mirrored the Silver model's full
    set, so `contact_email`/`contact_phone` reached a Power BI semantic model with no
    authorable way to stop them. Every alternative was worse -- unbinding the fields
    removes them from Silver too, dropping the dimension loses everything else in it, and
    a `securityPolicy` is the right tool for role-based hiding, not for "this column
    should never leave Silver".

    Matching is case-insensitive on the table, mirroring `_table_aliases`.
    """
    return _qualified_column_names(
        tuple(getattr(policy.gold, "excluded_columns", ()) or ()), table_name
    )


def _columns(
    model: SilverModelSpec,
    resource_uri: str,
    excluded: frozenset[str] = frozenset(),
    hidden: frozenset[str] = frozenset(),
) -> tuple[GoldColumnSpec, ...]:
    result: list[GoldColumnSpec] = []
    for column in model.columns:
        if column.name in excluded:
            continue
        if column.canonical_type is None or column.nullable is None:
            _fail(
                "gold.silver-column-contract-incomplete",
                (
                    f"{model.identity.model_name}.{column.name} lacks canonical type "
                    "or nullability in the actual Silver registry"
                ),
                rule_id="DD-112-silver-binding",
                resource_uri=resource_uri,
            )
        result.append(
            GoldColumnSpec(
                source_name=column.name,
                name=column.name,
                canonical_type=column.canonical_type,
                nullable=column.nullable,
                role=column.role,
                comment=column.description,
                provenance=column.provenance,
                hidden=_is_hidden_by_role(column) or column.name in hidden,
            )
        )
    if not result:
        _fail(
            "gold.empty-silver-model",
            f"Silver model {model.identity.model_name!r} has no materialized columns",
            rule_id="DD-112-silver-binding",
            resource_uri=resource_uri,
        )
    return tuple(result)


def _column_by_property(
    tables: tuple[GoldTableSpec, ...],
    dependency: str,
) -> tuple[str, str] | None:
    exact = [
        (table.name, column.name)
        for table in tables
        for column in table.columns
        if f"property:{dependency}" in column.provenance
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        _fail(
            "measure.ambiguous-column-dependency",
            f"column dependency {dependency!r} resolves to multiple emitted columns",
            rule_id="DD-113-measure-dependencies",
            resource_uri=dependency,
        )
    if "." in dependency and not dependency.startswith(("http://", "https://", "urn:")):
        table_name, column_name = dependency.rsplit(".", 1)
        if any(
            table.name == table_name and any(column.name == column_name for column in table.columns)
            for table in tables
        ):
            return table_name, column_name
    local = camel_to_snake(_local_name(dependency))
    local_matches = [
        (table.name, column.name)
        for table in tables
        for column in table.columns
        if column.name == local
    ]
    return local_matches[0] if len(local_matches) == 1 else None


def _shape_measures(
    policy: MedallionPolicySpec,
    tables: tuple[GoldTableSpec, ...],
    *,
    has_calendar: bool | None = None,
) -> tuple[GoldMeasureSpec, ...]:
    """Shape *policy*'s measures against the product's emitted tables.

    *has_calendar* is the product's answer, not this domain's: in a multi-domain product
    one domain declares the calendar and every domain's DAX may reference `dim_date`
    (#744). It defaults to this policy's own declaration for single-domain callers.
    """
    if has_calendar is None:
        has_calendar = policy.gold.calendar is not None
    by_resource = {item.resource_uri: item for item in policy.gold.measures}
    shaped: dict[str, GoldMeasureSpec] = {}
    visiting: set[str] = set()

    def shape(resource_uri: str) -> GoldMeasureSpec:
        if resource_uri in shaped:
            return shaped[resource_uri]
        if resource_uri in visiting:
            _fail(
                "measure.dependency-cycle",
                f"measure dependency cycle contains {resource_uri!r}",
                rule_id="DD-113-measure-dependencies",
                resource_uri=resource_uri,
            )
        source = by_resource.get(resource_uri)
        if source is None:
            _fail(
                "measure.unknown-dependency",
                f"measure dependency {resource_uri!r} is not part of this Gold product",
                rule_id="DD-113-measure-dependencies",
                resource_uri=resource_uri,
            )
        visiting.add(resource_uri)
        measure_dependencies = tuple(shape(item) for item in source.dependencies.measures.value)
        column_dependencies: list[tuple[str, str]] = []
        for dependency in source.dependencies.columns.value:
            resolved = _column_by_property(tables, dependency)
            if resolved is None:
                _fail(
                    "measure.missing-column-dependency",
                    (
                        f"measure {source.measure_id.value!r} references unavailable "
                        f"Silver/Gold column {dependency!r}"
                    ),
                    rule_id="DD-113-measure-dependencies",
                    resource_uri=source.resource_uri,
                )
            column_dependencies.append(resolved)
        home_tables = {table_name for table_name, _ in column_dependencies} | {
            item.home_table for item in measure_dependencies if item.home_table
        }
        if len(home_tables) > 1:
            _fail(
                "measure.ambiguous-home-table",
                (
                    f"measure {source.measure_id.value!r} dependencies span multiple "
                    f"home tables: {tuple(sorted(home_tables))!r}"
                ),
                rule_id="DD-113-measure-dependencies",
                resource_uri=source.resource_uri,
            )
        home_table = next(iter(home_tables), "")
        expression = source.expression.value if source.expression is not None else ""
        if source.lifecycle.value is not MeasureLifecycle.INTENT:
            allowed = {column for _, column in column_dependencies}
            allowed.update(item.measure_id for item in measure_dependencies)
            allowed.update(_local_name(item.measure_id) for item in measure_dependencies)
            missing_dax = tuple(
                sorted(
                    {
                        reference
                        for reference in _DAX_REFERENCE.findall(expression)
                        if reference not in allowed
                    }
                )
            )
            if missing_dax:
                _fail(
                    "measure.unresolved-dax-reference",
                    (
                        f"measure {source.measure_id.value!r} has undeclared DAX "
                        f"references: {missing_dax!r}"
                    ),
                    rule_id="DD-113-measure-dependencies",
                    resource_uri=source.resource_uri,
                )
            if not home_table:
                _fail(
                    "measure.home-table-missing",
                    (f"measure {source.measure_id.value!r} has no resolvable emitted home table"),
                    rule_id="DD-113-measure-dependencies",
                    resource_uri=source.resource_uri,
                )
            known_tables = {item.name for item in tables} | (
                {"dim_date"} if has_calendar else set()
            )
            referenced_tables = {
                *_DAX_QUOTED_TABLE_REFERENCE.findall(expression),
                *_DAX_BARE_TABLE_REFERENCE.findall(expression),
            }
            unknown_tables = tuple(sorted(referenced_tables - known_tables))
            if unknown_tables:
                _fail(
                    "measure.unresolved-dax-table-reference",
                    (
                        f"measure {source.measure_id.value!r} DAX references table(s) "
                        f"{unknown_tables!r} that are not emitted in this Gold product "
                        "(check for a stale prefix such as 'dim_' on an entity whose "
                        "goldTableName does not use one)"
                    ),
                    rule_id="DD-113-measure-dependencies",
                    resource_uri=source.resource_uri,
                )
        result = GoldMeasureSpec(
            resource_uri=source.resource_uri,
            measure_id=source.measure_id.value,
            definition=source.definition.value,
            expression=expression,
            lifecycle=source.lifecycle.value,
            home_table=home_table,
            column_dependencies=tuple(column_dependencies),
            measure_dependencies=tuple(item.measure_id for item in measure_dependencies),
            data_type=source.data_type.value if source.data_type is not None else "",
            format_string=(source.format_string.value if source.format_string is not None else ""),
            folder=source.folder.value if source.folder is not None else "",
            owner_role=(source.owner_role.value if source.owner_role is not None else ""),
            tests=source.validation_tests.value,
            evidence=source.validation_evidence.value,
            emitted=source.lifecycle.value is not MeasureLifecycle.INTENT,
        )
        visiting.remove(resource_uri)
        shaped[resource_uri] = result
        return result

    for resource_uri in sorted(by_resource):
        shape(resource_uri)
    return tuple(sorted(shaped.values(), key=lambda item: item.measure_id))


def _table_aliases(tables: tuple[GoldTableSpec, ...]) -> dict[str, GoldTableSpec]:
    aliases: dict[str, GoldTableSpec] = {}
    for table in tables:
        for alias in {
            table.name,
            table.source_model,
            _local_name(table.resource_uri),
        }:
            existing = aliases.get(alias.casefold())
            if existing is not None and existing != table:
                continue
            aliases[alias.casefold()] = table
    return aliases


def _shape_calendar(
    policy: MedallionPolicySpec,
    tables: tuple[GoldTableSpec, ...],
) -> GoldCalendarSpec | None:
    source = policy.gold.calendar
    if source is None:
        return None
    aliases = _table_aliases(tables)
    roles: list[GoldCalendarRoleSpec] = []
    names: set[str] = set()
    for value in source.role_playing_dates.value:
        match = _CALENDAR_ROLE.fullmatch(value)
        if match is None:
            _fail(
                "calendar.invalid-role-binding",
                (f"rolePlayingDate {value!r} must use RoleName=GoldOrSilverTable.date_column"),
                rule_id="DD-113-calendar",
                resource_uri=source.resource_uri,
            )
        role_name = match.group("role")
        if role_name.casefold() in names:
            _fail(
                "calendar.duplicate-role",
                f"calendar role {role_name!r} is duplicated",
                rule_id="DD-113-calendar",
                resource_uri=source.resource_uri,
            )
        names.add(role_name.casefold())
        table = aliases.get(match.group("table").casefold())
        column_name = match.group("column")
        column = (
            next(
                (item for item in table.columns if item.name == column_name),
                None,
            )
            if table is not None
            else None
        )
        if column is None:
            _fail(
                "calendar.missing-role-column",
                f"calendar role {value!r} does not bind an emitted Gold column",
                rule_id="DD-113-calendar",
                resource_uri=source.resource_uri,
            )
        if column.canonical_type.kind not in {
            CanonicalTypeKind.DATE,
            CanonicalTypeKind.TIMESTAMP,
        }:
            _fail(
                "calendar.non-date-role-column",
                f"calendar role {value!r} must bind a date or timestamp column",
                rule_id="DD-113-calendar",
                resource_uri=source.resource_uri,
            )
        roles.append(GoldCalendarRoleSpec(role_name, table.name, column_name))
    return GoldCalendarSpec(
        resource_uri=source.resource_uri,
        start_date=source.start_date.value,
        end_date=source.end_date.value,
        fiscal_year_start_month=source.fiscal_year_start_month.value,
        week_pattern=source.week_pattern.value,
        locale=source.locale.value,
        holiday_source=source.holiday_source.value,
        time_zone=source.time_zone.value,
        period_closure=source.period_closure.value,
        roles=tuple(sorted(roles, key=lambda item: item.role_name.casefold())),
        approved=source.approved,
    )


def _check_excluded_columns(policy, matched: frozenset[str]) -> None:
    """Reject a ``goldExcludeColumn`` value that names nothing (#703).

    Fail-closed on purpose, mirroring ``security.missing-column-binding``: the whole
    value of the term is that a column stays out of Gold, so a stale entry -- after a
    Silver rename, or a typo -- must not read as "successfully excluded" while the column
    is being emitted again.

    *matched* is every authored value that actually removed a column, collected while the
    tables were built. The emitted set cannot answer this on its own: a correctly excluded
    column is absent from it for exactly the same reason a misspelt one is.
    """
    _check_authored_columns(
        tuple(getattr(policy.gold, "excluded_columns", ()) or ()),
        matched,
        code="gold.unknown-excluded-column",
        term="goldExcludeColumn",
        verb="excluded",
        rule_id="DD-217-gold-column",
        ontology_uri=policy.gold.ontology_uri,
    )


def _check_hidden_columns(policy, matched: frozenset[str]) -> None:
    """Reject a ``goldHideColumn`` value that names nothing (#744).

    Fail-closed for the same reason as `_check_excluded_columns`: a stale value must not
    read as "successfully hidden" while the column is back in the field list. The failure
    mode is milder than an exclusion's -- a visible column, not a leaked one -- but the
    silence is identical, and a Silver rename is exactly when an author needs to hear it.
    """
    _check_authored_columns(
        tuple(getattr(policy.gold, "hidden_columns", ()) or ()),
        matched,
        code="gold.unknown-hidden-column",
        term="goldHideColumn",
        verb="hid",
        rule_id="DD-221-gold-column-visibility",
        ontology_uri=policy.gold.ontology_uri,
    )


def _check_authored_columns(
    values: tuple[str, ...],
    matched: frozenset[str],
    *,
    code: str,
    term: str,
    verb: str,
    rule_id: str,
    ontology_uri: str,
) -> None:
    """Reject every authored ``"Table.column"`` value that matched no emitted column."""
    if not values:
        return
    # Compared case-insensitively, because `_qualified_column_names` folds the table part
    # (mirroring `_table_aliases`) while `matched` is rebuilt from the emitted table name.
    seen = {item.casefold() for item in matched}
    for value in sorted({item for item in values if item.casefold() not in seen}):
        _fail(
            code,
            (
                f"{term} {value!r} {verb} no emitted column "
                '(expected "Table.column", naming a Gold table and one of its '
                "Silver columns)"
            ),
            rule_id=rule_id,
            resource_uri=ontology_uri,
        )


def _shape_security(
    policy: MedallionPolicySpec,
    tables: tuple[GoldTableSpec, ...],
) -> GoldSecuritySpec | None:
    source = policy.gold.security
    if source is None:
        return None
    aliases = _table_aliases(tables)
    roles = frozenset(source.role_policies.value)
    bindings: list[GoldSecurityBindingSpec] = []
    for value in source.bindings.value:
        match = _SECURITY_BINDING.fullmatch(value)
        if match is None:
            _fail(
                "security.invalid-binding",
                (f"securityBinding {value!r} must use Table.column=Role:RLS|OLS"),
                rule_id="DD-113-security",
                resource_uri=source.resource_uri,
            )
        role = match.group("role")
        if role not in roles:
            _fail(
                "security.unknown-role",
                f"security binding references undeclared role {role!r}",
                rule_id="DD-113-security",
                resource_uri=source.resource_uri,
            )
        table = aliases.get(match.group("table").casefold())
        column_name = match.group("column")
        if table is None or not any(column.name == column_name for column in table.columns):
            _fail(
                "security.missing-column-binding",
                f"security binding {value!r} does not bind an emitted Gold column",
                rule_id="DD-113-security",
                resource_uri=source.resource_uri,
            )
        bindings.append(
            GoldSecurityBindingSpec(
                table_name=table.name,
                column_name=column_name,
                role_name=role,
                kind=GoldSecurityKind(match.group("kind")),
            )
        )
    return GoldSecuritySpec(
        resource_uri=source.resource_uri,
        entitlement_source=source.entitlement_source.value,
        identity_mapping=source.identity_mapping.value,
        roles=tuple(sorted(roles)),
        filter_direction=source.filter_direction.value,
        bindings=tuple(
            sorted(
                bindings,
                key=lambda item: (
                    item.role_name,
                    item.kind.value,
                    item.table_name,
                    item.column_name,
                ),
            )
        ),
        positive_tests=source.positive_tests.value,
        negative_tests=source.negative_tests.value,
        test_evidence=source.test_evidence.value,
        fail_closed=source.fail_closed.value,
    )


def _relationship_column(
    table: GoldTableSpec,
    property_uri: str,
    explicit: str,
    foreign_keys: tuple[SilverForeignKeySpec, ...] = (),
    *,
    resource_uri: str = "",
) -> str:
    # #625: the generated surrogate FK column and its `_kairos_fk_*_match_count`
    # sibling both carry the exact same provenance tag `relationship:{property_uri}`
    # on the same Silver table (kernel.py DD-133 and DD-109-temporal-fk respectively),
    # so a provenance search over emitted columns can no longer tell them apart. The
    # typed, already-materialized `SilverModelSpec.foreign_keys` is the sole authority
    # now: a match-count column is never recorded there, so it can never displace the
    # real surrogate FK the way the old provenance heuristic allowed (#619 Bug 12
    # regressed by #625).
    typed = [item for item in foreign_keys if item.property_uri == property_uri]
    if len(typed) > 1:
        _fail(
            "gold.relationship-fk-ambiguous",
            (
                f"Silver relationship {property_uri!r} resolves to {len(typed)} "
                f"foreign-key specs on {table.source_model!r}"
            ),
            rule_id="DD-112-silver-binding",
            resource_uri=resource_uri or property_uri,
        )
    if typed:
        descriptor = typed[0]
        if len(descriptor.columns) != 1 or len(descriptor.referenced_columns) != 1:
            _fail(
                "gold.relationship-composite-key-unsupported",
                (
                    f"Silver relationship {property_uri!r} on {table.source_model!r} is "
                    "a composite-key foreign key, which Gold relationship projection "
                    "does not support yet"
                ),
                rule_id="DD-112-silver-binding",
                resource_uri=resource_uri or property_uri,
            )
        column_name = descriptor.columns[0]
        if not any(column.name == column_name for column in table.columns):
            _fail(
                "gold.relationship-column-not-emitted",
                (
                    f"Silver relationship {property_uri!r} names foreign-key column "
                    f"{column_name!r}, which {table.name!r} does not emit"
                ),
                rule_id="DD-112-silver-binding",
                resource_uri=resource_uri or property_uri,
            )
        return column_name
    # No typed Silver FK spec exists for this property (it was never wired as a real
    # join) -- fall back to a plain denormalized natural-key column, either tagged by
    # property or explicitly named by policy.
    candidates = [
        column.name for column in table.columns if f"property:{property_uri}" in column.provenance
    ]
    if explicit and any(column.name == explicit for column in table.columns):
        candidates.append(explicit)
    candidates = list(dict.fromkeys(candidates))
    return candidates[0] if len(candidates) == 1 else ""


def _shape_relationships(
    tables: tuple[GoldTableSpec, ...],
    descriptors: tuple[ForeignKeyDescriptorSpec, ...],
    silver_models: dict[str, SilverModelSpec],
) -> tuple[tuple[GoldRelationshipSpec, ...], tuple[tuple[str, str, str], ...]]:
    """Shape every relationship both of whose endpoints are tables in this product.

    Returns the shaped relationships and the *unresolved* ones: a foreign key whose
    source table is in the product, whose join column was materialized, and whose target
    is not here. That is a dead column in the emitted model -- the fact carries
    `customer_sk` and nothing joins it -- and before #744 it vanished with no diagnostic
    at all, which is how a cross-domain product silently lost half its star.

    A descriptor whose *source* is outside the product is not reported: that relationship
    belongs to some other product and is none of this one's business.
    """
    by_resource = {table.resource_uri: table for table in tables}
    relationships: list[GoldRelationshipSpec] = []
    unresolved: list[tuple[str, str, str]] = []
    for descriptor in descriptors:
        source = by_resource.get(descriptor.source_class)
        target = by_resource.get(descriptor.target_class)
        if source is None:
            continue
        source_model = silver_models.get(source.source_model)
        column_name = _relationship_column(
            source,
            descriptor.property_uri,
            descriptor.silver_column_name or "",
            source_model.foreign_keys if source_model is not None else (),
            resource_uri=descriptor.property_uri,
        )
        if not column_name:
            continue
        if target is None:
            unresolved.append((descriptor.property_uri, source.name, descriptor.target_class))
            continue
        if (
            source.version_binding is not None
            and source.version_binding is not DimensionVersionBinding.CURRENT
            and target.role is GoldTableRole.DIMENSION
            and target.dimension_exposure is DimensionExposure.CURRENT_ONLY
        ):
            _fail(
                "gold.incompatible-dimension-version",
                (
                    f"{source.name} uses {source.version_binding.value} but "
                    f"{target.name} exposes current rows only"
                ),
                rule_id="DD-112-dimension-version",
                resource_uri=descriptor.property_uri,
            )
        if not target.primary_key:
            _fail(
                "gold.relationship-target-key-missing",
                f"relationship target {target.name!r} has no materialized key",
                rule_id="DD-112-silver-binding",
                resource_uri=descriptor.property_uri,
            )
        relationships.append(
            GoldRelationshipSpec(
                name=camel_to_snake(_local_name(descriptor.property_uri)),
                source_table=source.name,
                source_column=column_name,
                target_table=target.name,
                target_column=target.primary_key,
                cardinality="many-to-one",
                version_binding=source.version_binding,
            )
        )
    for bridge in tables:
        if bridge.role is not GoldTableRole.BRIDGE:
            continue
        for endpoint_uri, column_name in bridge.bridge_endpoint_bindings:
            target = by_resource[endpoint_uri]
            relationships.append(
                GoldRelationshipSpec(
                    name=f"{bridge.name}_{target.name}",
                    source_table=bridge.name,
                    source_column=column_name,
                    target_table=target.name,
                    target_column=target.primary_key,
                    cardinality=(
                        bridge.bridge_cardinality.value
                        if bridge.bridge_cardinality is not None
                        else ""
                    ),
                    version_binding=None,
                )
            )
    return (
        tuple(
            sorted(
                relationships,
                key=lambda item: (
                    item.source_table,
                    item.source_column,
                    item.target_table,
                ),
            )
        ),
        tuple(sorted(set(unresolved))),
    )


def _shape_tables(
    policy: MedallionPolicySpec,
    registry: SilverRegistry,
    silver_models: tuple[SilverModelSpec, ...],
    ontology_name: str,
    ontology_version: str,
) -> tuple[GoldTableSpec, ...]:
    """Shape one domain's authored Gold tables against its own compiled Silver registry.

    Split out of the product assembly for #744. Tables are the only part of a Gold product
    that is genuinely per-domain: a table is materialized by the compile of the domain that
    binds it, so this runs once per participating domain. Everything that *spans* tables --
    relationships, measures, the calendar, security, perspectives -- is assembled afterwards
    over the union, because crossing the domain boundary is the whole point of a product.
    """
    profile_value = policy.gold.profile
    if profile_value is None or policy.gold.schema is None:
        _fail(
            "gold.profile-missing",
            "Gold projection requires an explicit registered product profile and schema",
            rule_id="DD-112-profile",
        )
    # Called for its fail-closed side effect, not its value: `get` raises on a profile
    # this build does not register, and this domain's tables must not be shaped under a
    # profile the product assembler would then reject.
    policy.gold_registry.get(profile_value.value)
    names = dict(registry.names)
    registry_columns = dict(registry.columns)
    versions = dict(registry.versions)
    models = {model.identity.model_name: model for model in silver_models}
    incremental = {item.resource_uri: item for item in policy.incremental}
    perspective_by_table = {
        resource_uri: tuple(
            perspective.name
            for perspective in policy.gold.perspectives
            if resource_uri in perspective.table_uris
        )
        for resource_uri in names
    }
    tables: list[GoldTableSpec] = []
    used_names: set[str] = set()
    #: Authored `goldExcludeColumn` values that actually removed a column (#703).
    excluded_matched: set[str] = set()
    #: Authored `goldHideColumn` values that actually hid a column (#744).
    hidden_matched: set[str] = set()
    for authored in policy.gold.tables:
        if not _IDENTIFIER.fullmatch(authored.table_name.value):
            _fail(
                "gold.invalid-table-name",
                f"invalid Gold table identifier {authored.table_name.value!r}",
                rule_id="DD-112-table-role",
                resource_uri=authored.resource_uri,
            )
        if authored.table_name.value.casefold() in used_names:
            _fail(
                "gold.duplicate-table-name",
                f"duplicate Gold table name {authored.table_name.value!r}",
                rule_id="DD-112-table-role",
                resource_uri=authored.resource_uri,
            )
        used_names.add(authored.table_name.value.casefold())
        actual_name = names.get(authored.resource_uri)
        if actual_name is None:
            _fail(
                "gold.unmaterialized-silver-source",
                (
                    f"Gold table {authored.table_name.value!r} has no actual "
                    f"materialized Silver registry entry in domain {ontology_name!r}. "
                    "A Gold table is only materialized by the compile of the domain that "
                    "actually binds it -- an owl:imports of a sibling domain resolves that "
                    "domain's classes but does not carry its compiled Silver bindings. If "
                    "this table belongs to another domain, author it in a separate Gold "
                    f"extension on that domain (model/extensions/<domain>-gold-ext.ttl) and "
                    "emit it with its own `emit-gold <domain>`; a Gold product spanning a "
                    "cross-domain relationship needs one extension per owning domain."
                ),
                rule_id="DD-112-silver-binding",
                resource_uri=authored.resource_uri,
            )
        if authored.source_model.value != actual_name:
            _fail(
                "gold.source-model-drift",
                (
                    f"authored source model {authored.source_model.value!r} does not "
                    f"match Silver registry model {actual_name!r}"
                ),
                rule_id="DD-112-silver-binding",
                resource_uri=authored.resource_uri,
            )
        actual_version = versions.get(actual_name, ontology_version)
        if not actual_version or authored.source_version.value != actual_version:
            _fail(
                "gold.source-version-drift",
                (
                    f"gold table {authored.table_name.value!r} (silver model "
                    f"{actual_name!r}, domain {ontology_name!r}) pins goldSourceVersion "
                    f"{authored.source_version.value!r} but the domain's owl:versionInfo "
                    f"is {actual_version!r}; update kairos-ext:goldSourceVersion in "
                    f"model/extensions/{ontology_name}-gold-ext.ttl after re-validating "
                    "the Gold table"
                ),
                rule_id="DD-112-silver-binding",
                resource_uri=authored.resource_uri,
            )
        model = models.get(actual_name)
        if model is None:
            _fail(
                "gold.silver-model-plan-missing",
                f"Silver registry model {actual_name!r} has no logical materialization",
                rule_id="DD-112-silver-binding",
                resource_uri=authored.resource_uri,
            )
        actual_columns = frozenset(column.name for column in model.columns)
        if actual_columns != registry_columns.get(actual_name, frozenset()):
            _fail(
                "gold.silver-registry-drift",
                f"Silver registry columns drifted for model {actual_name!r}",
                rule_id="DD-110-parity",
                resource_uri=authored.resource_uri,
            )
        authority = model.authority
        history = authority.history if authority is not None else None
        scd_type = history.scd_type.value.value if history is not None else ""
        if (
            authored.dimension_exposure
            and authored.dimension_exposure.value
            in {DimensionExposure.HISTORY_ONLY, DimensionExposure.DUAL}
            and history is not None
            and history.scd_type.value is not ScdType.TYPE_2
        ):
            _fail(
                "gold.dimension-history-unavailable",
                (
                    f"dimension {authored.table_name.value!r} requests history "
                    "exposure but its Silver authority is not SCD2"
                ),
                rule_id="DD-112-dimension",
                resource_uri=authored.resource_uri,
            )
        unique_key: tuple[str, ...] = ()
        updated_at = ""
        if authored.role.value is GoldTableRole.FACT:
            runtime = incremental.get(authored.incremental_policy_ref or "")
            if runtime is not None:
                unique_key = runtime.merge_identity.value
                updated_at = runtime.ordering.source_updated_at.value
                missing_runtime_columns = tuple(
                    value for value in (*unique_key, updated_at) if value not in actual_columns
                )
                if missing_runtime_columns:
                    _fail(
                        "gold.fact-runtime-column-missing",
                        (
                            f"fact {authored.table_name.value!r} runtime policy references "
                            f"unmaterialized Silver columns {missing_runtime_columns!r}"
                        ),
                        rule_id="DD-112-fact",
                        resource_uri=authored.resource_uri,
                    )
        weight = authored.bridge_weight_column.value if authored.bridge_weight_column else ""
        if weight and weight not in actual_columns:
            _fail(
                "gold.bridge-weight-column-missing",
                f"bridge weight column {weight!r} is not materialized by Silver",
                rule_id="DD-112-bridge",
                resource_uri=authored.resource_uri,
            )
        endpoint_bindings: list[tuple[str, str]] = []
        if authored.bridge_endpoint_bindings is not None:
            endpoints = authored.bridge_endpoints.value if authored.bridge_endpoints else ()
            for value in authored.bridge_endpoint_bindings.value:
                if "=" not in value:
                    _fail(
                        "gold.invalid-bridge-endpoint-binding",
                        (
                            f"bridge endpoint binding {value!r} must use "
                            "EndpointResource=column_name"
                        ),
                        rule_id="DD-112-bridge",
                        resource_uri=authored.resource_uri,
                    )
                endpoint_name, column_name = value.rsplit("=", 1)
                matching = tuple(
                    endpoint
                    for endpoint in endpoints
                    if endpoint == endpoint_name or _local_name(endpoint) == endpoint_name
                )
                if len(matching) != 1 or column_name not in actual_columns:
                    _fail(
                        "gold.invalid-bridge-endpoint-binding",
                        (
                            f"bridge endpoint binding {value!r} does not resolve "
                            "one endpoint and one emitted Silver column"
                        ),
                        rule_id="DD-112-bridge",
                        resource_uri=authored.resource_uri,
                    )
                endpoint_bindings.append((matching[0], column_name))
            if {item[0] for item in endpoint_bindings} != set(endpoints):
                _fail(
                    "gold.incomplete-bridge-endpoint-bindings",
                    "each bridge endpoint requires exactly one column binding",
                    rule_id="DD-112-bridge",
                    resource_uri=authored.resource_uri,
                )
        table_excluded = _excluded_column_names(policy, authored.table_name.value)
        excluded_matched.update(
            f"{authored.table_name.value}.{name}"
            for name in table_excluded
            if any(column.name == name for column in model.columns)
        )
        table_hidden = _hidden_column_names(policy, authored.table_name.value)
        hidden_matched.update(
            f"{authored.table_name.value}.{name}"
            for name in table_hidden
            # An excluded column is not in the product at all, so hiding it matched
            # nothing -- the author has two annotations fighting over one column and
            # should hear about it.
            if name not in table_excluded and any(column.name == name for column in model.columns)
        )
        tables.append(
            GoldTableSpec(
                resource_uri=authored.resource_uri,
                name=authored.table_name.value,
                schema_name=policy.gold.schema.value,
                role=authored.role.value,
                source_model=actual_name,
                source_version=actual_version,
                columns=_columns(model, authored.resource_uri, table_excluded, table_hidden),
                primary_key=_primary_key(model),
                fact_grain=(authored.fact_grain.value if authored.fact_grain is not None else ""),
                fact_type=(authored.fact_type.value if authored.fact_type is not None else None),
                version_binding=(
                    authored.version_binding.value if authored.version_binding is not None else None
                ),
                correction=(authored.correction.value if authored.correction is not None else None),
                late_arrival=(
                    authored.late_arrival.value if authored.late_arrival is not None else None
                ),
                incremental_policy_ref=authored.incremental_policy_ref or "",
                incremental_unique_key=unique_key,
                incremental_updated_at=updated_at,
                dimension_exposure=(
                    authored.dimension_exposure.value
                    if authored.dimension_exposure is not None
                    else None
                ),
                silver_scd_type=scd_type,
                bridge_grain=(
                    authored.bridge_grain.value if authored.bridge_grain is not None else ""
                ),
                bridge_endpoints=(
                    authored.bridge_endpoints.value
                    if authored.bridge_endpoints is not None
                    else None
                ),
                bridge_endpoint_bindings=tuple(endpoint_bindings),
                bridge_cardinality=(
                    authored.bridge_cardinality.value
                    if authored.bridge_cardinality is not None
                    else None
                ),
                bridge_weight_column=weight,
                bridge_allocation=(
                    authored.bridge_allocation.value
                    if authored.bridge_allocation is not None
                    else ""
                ),
                perspectives=tuple(sorted(perspective_by_table.get(authored.resource_uri, ()))),
            )
        )
    _check_excluded_columns(policy, frozenset(excluded_matched))
    _check_hidden_columns(policy, frozenset(hidden_matched))
    return tuple(sorted(tables, key=lambda item: (item.role.value, item.name)))


def _sole(
    members: tuple["GoldDomainInput", ...],
    pick,
    *,
    code: str,
    what: str,
) -> "GoldDomainInput | None":
    """Return the one member that declares *what*, or fail if several do.

    A Gold product has exactly one calendar and one security policy. Both are naturally
    hub-wide concerns that happen to be authored per domain, so the rule is that one
    participating domain declares it and the product inherits it -- which is what makes a
    hub-wide calendar possible at all (#744). Two competing declarations have no defensible
    merge, so they fail rather than silently picking one.
    """
    declaring = [member for member in members if pick(member) is not None]
    if len(declaring) > 1:
        names = ", ".join(sorted(member.ontology_name for member in declaring))
        _fail(
            code,
            (
                f"{len(declaring)} domains declare a {what} for this Gold product "
                f"({names}); exactly one participating domain may declare it"
            ),
            rule_id="DD-112-profile",
        )
    return declaring[0] if declaring else None


def _shape_dimensional_product(
    members: tuple["GoldDomainInput", ...],
    product_name: str,
) -> DimensionalGoldSpec:
    """Assemble one Gold product from one or more compiled domains (#744).

    A single-domain product is the N=1 case of this rather than a separate path, so a hub
    that declares no product keeps emitting exactly what it emitted before.
    """
    primary = members[0]
    profile_value = primary.policy.gold.profile
    if profile_value is None or primary.policy.gold.schema is None:
        _fail(
            "gold.profile-missing",
            "Gold projection requires an explicit registered product profile and schema",
            rule_id="DD-112-profile",
        )
    profile = primary.policy.gold_registry.get(profile_value.value)

    tables: list[GoldTableSpec] = []
    owner_of: dict[str, str] = {}
    for member in members:
        for table in _shape_tables(
            member.policy,
            member.registry,
            member.silver_models,
            member.ontology_name,
            member.ontology_version,
        ):
            owner = owner_of.get(table.name.casefold())
            if owner is not None:
                _fail(
                    "gold.product-table-name-collision",
                    (
                        f"Gold table {table.name!r} is authored in both {owner!r} and "
                        f"{member.ontology_name!r}; one semantic model cannot carry two "
                        "tables under one name -- rename one with kairos-ext:goldTableName"
                    ),
                    rule_id="DD-112-table-role",
                    resource_uri=table.resource_uri,
                )
            owner_of[table.name.casefold()] = member.ontology_name
            tables.append(table)
    ordered = tuple(sorted(tables, key=lambda item: (item.role.value, item.name)))

    # Checked over the union, not per domain: a bridge may span two domains' tables.
    included = {table.resource_uri for table in ordered}
    for table in ordered:
        if table.role is GoldTableRole.BRIDGE and (
            table.bridge_endpoints is None or not set(table.bridge_endpoints).issubset(included)
        ):
            _fail(
                "gold.bridge-endpoint-not-materialized",
                f"bridge {table.name!r} endpoints must both be explicit Gold tables",
                rule_id="DD-112-bridge",
                resource_uri=table.resource_uri,
            )

    models: dict[str, SilverModelSpec] = {}
    descriptors: list[ForeignKeyDescriptorSpec] = []
    for member in members:
        models.update({model.identity.model_name: model for model in member.silver_models})
        descriptors.extend(member.foreign_keys.descriptors)
    relationships, unresolved = _shape_relationships(ordered, tuple(descriptors), models)

    calendar_owner = _sole(
        members,
        lambda member: member.policy.gold.calendar,
        code="gold.product-calendar-conflict",
        what="calendar profile",
    )
    calendar = (
        _shape_calendar(calendar_owner.policy, ordered) if calendar_owner is not None else None
    )
    security_owner = _sole(
        members,
        lambda member: member.policy.gold.security,
        code="gold.product-security-unsupported",
        what="security policy",
    )
    security = (
        _shape_security(security_owner.policy, ordered) if security_owner is not None else None
    )

    measures: list[GoldMeasureSpec] = []
    measure_owner: dict[str, str] = {}
    for member in members:
        for measure in _shape_measures(member.policy, ordered, has_calendar=calendar is not None):
            owner = measure_owner.get(measure.measure_id.casefold())
            if owner is not None:
                _fail(
                    "gold.product-measure-id-collision",
                    (
                        f"measure {measure.measure_id!r} is authored in both {owner!r} and "
                        f"{member.ontology_name!r}; a measure name is unique in one model"
                    ),
                    rule_id="DD-113-measure-lifecycle",
                    resource_uri=measure.resource_uri,
                )
            measure_owner[measure.measure_id.casefold()] = member.ontology_name
            measures.append(measure)

    perspectives: list[tuple[str, tuple[str, ...]]] = []
    perspective_owner: dict[str, str] = {}
    for member in members:
        for item in member.policy.gold.perspectives:
            owner = perspective_owner.get(item.name.casefold())
            if owner is not None:
                # One `perspectives.tmdl` per model, so two blocks under one name is not a
                # merge the projector may guess at. Caught here rather than left to the
                # TOM gate, which `--skip-tmdl-validation` turns off.
                _fail(
                    "gold.product-perspective-collision",
                    (
                        f"perspective {item.name!r} is authored in both {owner!r} and "
                        f"{member.ontology_name!r}; a perspective name is unique in one "
                        "semantic model"
                    ),
                    rule_id="DD-112-profile",
                )
            perspective_owner[item.name.casefold()] = member.ontology_name
            perspectives.append(
                (
                    item.name,
                    tuple(
                        sorted(
                            table.name for table in ordered if table.resource_uri in item.table_uris
                        )
                    ),
                )
            )
    registry_names: list[tuple[str, str]] = []
    registry_columns: list[tuple[str, frozenset[str]]] = []
    for member in members:
        registry_names.extend(member.registry.names)
        registry_columns.extend(member.registry.columns)

    return DimensionalGoldSpec(
        profile=profile.name,
        profile_version=profile.version,
        ontology_name=product_name,
        ontology_version=primary.ontology_version,
        schema_name=primary.policy.gold.schema.value,
        adapter=primary.policy.target_adapter.value.value,
        tables=ordered,
        relationships=relationships,
        measures=tuple(sorted(measures, key=lambda item: item.measure_id)),
        calendar=calendar,
        security=security,
        perspectives=tuple(sorted(perspectives)),
        silver_registry_names=tuple(sorted(set(registry_names))),
        silver_registry_columns=tuple(sorted(set(registry_columns))),
        domains=tuple(member.ontology_name for member in members),
        unresolved_relationships=unresolved,
    )


def _shape_dimensional(
    policy: MedallionPolicySpec,
    registry: SilverRegistry,
    silver_models: tuple[SilverModelSpec, ...],
    foreign_keys: ForeignKeyPolicy,
    ontology_name: str,
    ontology_version: str,
) -> DimensionalGoldSpec:
    """The single-domain product: one member, named after its own domain."""
    return _shape_dimensional_product(
        (
            GoldDomainInput(
                policy=policy,
                registry=registry,
                silver_models=silver_models,
                foreign_keys=foreign_keys,
                ontology_name=ontology_name,
                ontology_version=ontology_version,
            ),
        ),
        ontology_name,
    )


GoldProfileBuilder = Callable[
    [
        MedallionPolicySpec,
        SilverRegistry,
        tuple[SilverModelSpec, ...],
        ForeignKeyPolicy,
        str,
        str,
    ],
    GoldProductLogicalSpec,
]

_PROFILE_BUILDERS: dict[GoldProfileName, GoldProfileBuilder] = {
    GoldProfileName.DIMENSIONAL_POWERBI_V1: _shape_dimensional,
}


def shape_gold_product(
    policy: MedallionPolicySpec,
    registry: SilverRegistry,
    silver_models: tuple[SilverModelSpec, ...],
    foreign_keys: ForeignKeyPolicy,
    *,
    ontology_name: str,
    ontology_version: str,
    required: bool = False,
) -> GoldProductLogicalSpec | None:
    """Dispatch one exact registered profile; no generic dimensional fallback exists."""
    profile = policy.gold.profile
    if profile is None:
        if required:
            _fail(
                "gold.profile-missing",
                "Gold projection requires goldProductProfile",
                rule_id="DD-112-profile",
            )
        return None
    registered = policy.gold_registry.get(profile.value)
    builder = _PROFILE_BUILDERS.get(registered.name)
    if builder is None:
        _fail(
            "gold.profile-not-implemented",
            f"registered Gold profile {registered.name.value!r} has no implementation",
            rule_id="DD-112-profile",
        )
    return builder(
        policy,
        registry,
        silver_models,
        foreign_keys,
        ontology_name,
        ontology_version,
    )


def shape_gold_products(
    members: tuple[GoldDomainInput, ...],
    *,
    product_name: str,
    required: bool = False,
) -> GoldProductLogicalSpec | None:
    """Dispatch one registered profile over every domain participating in a product.

    Every participating domain must author the same profile: the product is one semantic
    model, and a profile decides how that model is shaped, so two answers would have no
    meaning. Only ``dimensional-powerbi-v1`` exists today, which makes the check cheap now
    and load-bearing the moment a second profile is registered.
    """
    if not members:
        _fail(
            "gold.product-without-domains",
            f"Gold product {product_name!r} has no participating domain",
            rule_id="DD-222-gold-product-scope",
        )
    unprofiled = [member.ontology_name for member in members if member.policy.gold.profile is None]
    if unprofiled:
        if required:
            _fail(
                "gold.profile-missing",
                (
                    f"Gold product {product_name!r} includes domain(s) "
                    f"{', '.join(sorted(unprofiled))} that author no goldProductProfile; "
                    "every participating domain must author its own Gold extension"
                ),
                rule_id="DD-112-profile",
            )
        return None
    profiles = {member.policy.gold.profile.value for member in members}
    if len(profiles) > 1:
        _fail(
            "gold.product-profile-conflict",
            (
                f"Gold product {product_name!r} spans domains authoring different product "
                f"profiles ({', '.join(sorted(str(item) for item in profiles))}); one "
                "product is one semantic model and takes one profile"
            ),
            rule_id="DD-112-profile",
        )
    primary = members[0]
    registered = primary.policy.gold_registry.get(primary.policy.gold.profile.value)
    if _PROFILE_BUILDERS.get(registered.name) is None:
        _fail(
            "gold.profile-not-implemented",
            f"registered Gold profile {registered.name.value!r} has no implementation",
            rule_id="DD-112-profile",
        )
    return _shape_dimensional_product(members, product_name)
