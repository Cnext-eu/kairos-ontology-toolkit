# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Model-shape checks over a shaped Gold product (DD-240, issue #996).

The BPA checks in ``gold_bpa_checks`` judge objects one at a time. These judge how the
tables fit together, against a Kimball dimensional design: facts reference dimensions
only, dimensions do not chain, every fact has a date, snapshots are summed the way a
snapshot can be, one product serves one business process. Each finding is a catalogued
practice (``practices/semantic-model``).

They run only on the whole product. On a single-domain compile the other domains' tables
are missing, so a route may look ambiguous, or a table unconnected, only because half the
model is absent; ``compile --check`` therefore runs them in a product pass after the
domains compile, and ``emit-gold`` runs them on the product it emits.

Every finding is a warning or an advisory, never blocking: each is a design question with
a legitimate "yes, deliberately" answer, recorded as a ``kairos-ext:practiceException``.
"""

from __future__ import annotations

import re
from collections import deque

from .bpa_profile import BpaIgnore
from .gold_bpa_checks import GoldAdvisory, _scannable
from .gold_specs import GoldContractError, GoldMeasureSpec, GoldRelationshipSpec, GoldTableSpec
from .policy_specs import BridgeCardinality, FactType, GoldTableRole

_RULE = "DD-240-practices"

AMBIGUOUS_PATH = "semantic-model.ambiguous-path"
FACT_TO_FACT = "semantic-model.fact-to-fact"
SNOWFLAKE_CHAIN = "semantic-model.snowflake-chain"
ROLE_PLAYING = "semantic-model.role-playing-dimension"
STAR_SCHEMA = "semantic-model.star-schema"
FACT_HAS_DATE = "semantic-model.every-fact-has-a-date"
SNAPSHOT_SHAPE = "semantic-model.snapshot-fact-shape"
SEMI_ADDITIVE = "semantic-model.semi-additive-snapshot-measure"
MEASURE_ON_FACT = "semantic-model.measures-live-on-facts"
BRIDGE_ALLOCATION = "semantic-model.bridge-allocation"
BRIDGE_WEIGHT = "semantic-model.bridge-weight-used"
CONFORMED = "semantic-model.conformed-dimension"
CONNECTED = "semantic-model.connected-tables"
ONE_PROCESS = "semantic-model.product-is-one-process"
NAME_ROLE = "semantic-model.table-name-matches-role"

#: Practice -> the diagnostic code that reports it.
CODES = {
    AMBIGUOUS_PATH: "gold.ambiguous-path",
    FACT_TO_FACT: "gold.fact-to-fact",
    SNOWFLAKE_CHAIN: "gold.snowflake-chain",
    ROLE_PLAYING: "gold.role-playing-dimension",
    STAR_SCHEMA: "gold.star-schema",
    FACT_HAS_DATE: "gold.fact-without-date",
    SNAPSHOT_SHAPE: "gold.snapshot-shape",
    SEMI_ADDITIVE: "gold.semi-additive-sum",
    MEASURE_ON_FACT: "gold.measure-on-dimension",
    BRIDGE_ALLOCATION: "gold.bridge-unweighted",
    BRIDGE_WEIGHT: "gold.bridge-weight-unused",
    CONFORMED: "gold.duplicate-dimension",
    CONNECTED: "gold.unconnected-table",
    ONE_PROCESS: "gold.product-spans-processes",
    NAME_ROLE: "gold.table-name-role",
}

#: ``USERELATIONSHIP(a[x], b[y])``, either argument order, table optionally quoted.
_REF = r"(?:'(?P<{0}t>(?:[^']|'')+)'|(?P<{0}u>[A-Za-z_][A-Za-z0-9_]*))\s*\[(?P<{0}c>[^\]]+)\]"
_USERELATIONSHIP = re.compile(
    r"USERELATIONSHIP\s*\(\s*" + _REF.format("a") + r"\s*,\s*" + _REF.format("b") + r"\s*\)",
    re.IGNORECASE,
)
_SUM = re.compile(r"\bSUMX?\s*\(", re.IGNORECASE)
#: What makes a snapshot measure semi-additive over time: it takes one date's value.
_SEMI_ADDITIVE = re.compile(
    r"\b(LASTNONBLANK|LASTNONBLANKVALUE|FIRSTNONBLANK|FIRSTNONBLANKVALUE|LASTDATE|"
    r"FIRSTDATE|CLOSINGBALANCE\w*|OPENINGBALANCE\w*|ENDOFMONTH|ENDOFQUARTER|ENDOFYEAR|"
    r"MAX|MIN)\s*\(",
    re.IGNORECASE,
)
_COUNT = re.compile(r"\b(COUNTROWS|DISTINCTCOUNT\w*|COUNTX?|COUNTA|COUNTBLANK)\s*\(", re.IGNORECASE)
_NAME_PREFIX = {
    GoldTableRole.FACT: ("fact_", "fct_"),
    GoldTableRole.DIMENSION: ("dim_",),
    GoldTableRole.BRIDGE: ("bridge_", "brg_"),
}


def edge_label(item: GoldRelationshipSpec) -> str:
    """The ``Table.column -> Table.column`` form an exception names an edge by."""
    return f"{item.source_table}.{item.source_column} -> {item.target_table}.{item.target_column}"


def active_route(
    relationships: tuple[GoldRelationshipSpec, ...],
    start: str,
    end: str,
    *,
    directed: bool = False,
) -> list[str]:
    """The tables on the shortest active path from *start* to *end*, or ``[]`` when none.

    *directed* follows filter direction only -- one side to many side, and back where an
    edge filters both ways -- which is the route a filter on *start* actually takes. The
    undirected search finds how two tables are connected at all.
    """
    neighbours: dict[str, list[str]] = {}
    for item in relationships:
        if item.is_active:
            neighbours.setdefault(item.target_table, []).append(item.source_table)
            if not directed or item.bidirectional:
                neighbours.setdefault(item.source_table, []).append(item.target_table)
    previous: dict[str, str] = {start: start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node == end:
            path = [end]
            while path[-1] != start:
                path.append(previous[path[-1]])
            return path[::-1]
        for other in sorted(neighbours.get(node, ())):
            if other not in previous:
                previous[other] = node
                queue.append(other)
    return []


def second_route(
    relationships: tuple[GoldRelationshipSpec, ...], item: GoldRelationshipSpec
) -> tuple[list[str], list[str]] | None:
    """Why *item* is ambiguous: the active filter route it duplicates, and its own.

    Returns ``(existing, added)``, two routes between the same two tables: one over the
    active edges, one that would cross *item*. The origin is not always *item*'s own one
    side -- in ``fact -> job -> branch`` next to ``fact -> branch``, it is ``branch``
    that would reach ``fact`` twice, not ``job`` (#1012). None when no active route
    explains it, which a caller reports generically.
    """
    arcs = [(item.target_table, item.source_table)]
    if item.bidirectional:
        arcs.append((item.source_table, item.target_table))
    tables = sorted(
        {other.source_table for other in relationships}
        | {other.target_table for other in relationships}
    )
    for tail, head in arcs:
        origins = [
            name
            for name in tables
            if name == tail or active_route(relationships, name, tail, directed=True)
        ]
        ends = [
            name
            for name in tables
            if name == head or active_route(relationships, head, name, directed=True)
        ]
        for origin in origins:
            for end in ends:
                existing = (
                    active_route(relationships, origin, end, directed=True) if origin != end else []
                )
                if origin != end and not existing:
                    continue
                into = active_route(relationships, origin, tail, directed=True) or [tail]
                out = active_route(relationships, head, end, directed=True) or [head]
                return existing or [origin], into + out
    return None


def activated_edges(measures: tuple[GoldMeasureSpec, ...]) -> set[frozenset[tuple[str, str]]]:
    """Every ``{(table, column), (table, column)}`` a measure names in USERELATIONSHIP."""
    edges: set[frozenset[tuple[str, str]]] = set()
    for measure in measures:
        if not measure.emitted:
            continue
        for match in _USERELATIONSHIP.finditer(_scannable(measure.expression)):
            ends = []
            for side in ("a", "b"):
                table = match.group(f"{side}t") or match.group(f"{side}u") or ""
                ends.append(
                    (table.replace("''", "'").casefold(), match.group(f"{side}c").casefold())
                )
            edges.add(frozenset(ends))
    return edges


def _is_activated(item: GoldRelationshipSpec, activated) -> bool:
    return (
        frozenset(
            {
                (item.source_table.casefold(), item.source_column.casefold()),
                (item.target_table.casefold(), item.target_column.casefold()),
            }
        )
        in activated
    )


def _excuse(practice_id: str, kind: str, target: str) -> str:
    return (
        f'or record kairos-ext:practiceException "{practice_id} on {kind}'
        + (f" {target}" if target else "")
        + ': <reason>"'
    )


def check_model_shape(
    tables: tuple[GoldTableSpec, ...],
    relationships: tuple[GoldRelationshipSpec, ...],
    exceptions: tuple[BpaIgnore, ...],
    *,
    measures: tuple[GoldMeasureSpec, ...] = (),
    calendar_table: str = "",
) -> tuple[GoldAdvisory, ...]:
    """Return the shape findings; fail an exception to a shape rule that excuses nothing.

    *calendar_table* names the calendar dimension when the product emits one
    (``dim_date``); it is not among *tables*.
    """
    role = {table.name: table.role for table in tables}
    if calendar_table:
        role[calendar_table] = GoldTableRole.DIMENSION
    by_name = {table.name: table for table in tables}
    excused = {
        (item.rule_id, item.kind, item.target.casefold())
        for item in exceptions
        if item.rule_id in CODES
    }
    used: set[tuple[str, str, str]] = set()
    findings: list[GoldAdvisory] = []

    def report(practice_id: str, kind: str, target: str, resource: str, message: str) -> None:
        key = (practice_id, kind, target.casefold())
        if key in excused:
            used.add(key)
            return
        findings.append(
            GoldAdvisory(
                CODES[practice_id], message + " " + _excuse(practice_id, kind, target), resource
            )
        )

    def on_edge(practice_id: str, item: GoldRelationshipSpec, message: str) -> None:
        resource = by_name[item.source_table].resource_uri if item.source_table in by_name else ""
        report(practice_id, "relationship", edge_label(item), resource, message)

    def on_table(practice_id: str, name: str, message: str) -> None:
        resource = by_name[name].resource_uri if name in by_name else ""
        report(practice_id, "table", name, resource, message)

    def is_(name: str, kind: GoldTableRole) -> bool:
        return role.get(name) is kind

    # --- Deactivated edges -----------------------------------------------------------
    activated = activated_edges(measures)
    for item in relationships:
        if item.inactive_reason != "ambiguous-path" or _is_activated(item, activated):
            # A measure that activates the edge is the design answering the question
            # (DD-240 amends DD-226's rejection of INACTIVE_RELATIONSHIPS_...).
            continue
        pair = (item.source_table, item.target_table)
        siblings = [
            other for other in relationships if (other.source_table, other.target_table) == pair
        ]
        active_sibling = next((other for other in siblings if other.is_active), None)
        if active_sibling is not None:
            on_edge(
                ROLE_PLAYING,
                item,
                (
                    f"{edge_label(item)} is an inactive role of {item.target_table}: "
                    f"{edge_label(active_sibling)} is the active one, so this role filters "
                    "nothing unless a measure calls USERELATIONSHIP. Decide per role between "
                    f"a USERELATIONSHIP measure and a separate copy of {item.target_table},"
                ),
            )
            continue
        routes = second_route(relationships, item)
        if routes is not None and routes[0][0] == item.target_table:
            already = f"{item.target_table} already filters {routes[0][-1]} through "
            via = " -> ".join(routes[0])
        elif routes is not None:
            already = (
                f"a filter on {routes[0][0]} would reach {routes[0][-1]} twice, "
                f"through {' -> '.join(routes[1])} and through "
            )
            via = " -> ".join(routes[0])
        else:
            already = f"{item.target_table} already reaches {item.source_table} through "
            via = "another active path"
        role_note = (
            f" None of the {len(siblings)} edges from {item.source_table} to "
            f"{item.target_table} is active."
            if len(siblings) > 1
            else ""
        )
        on_edge(
            AMBIGUOUS_PATH,
            item,
            (
                f"{edge_label(item)} is inactive (ambiguous-path): {already}{via}, and no measure "
                f"activates it with USERELATIONSHIP, so it filters nothing.{role_note} Keep "
                "it active with kairos-ext:goldPrimaryRelationship, remove the redundant "
                "route with kairos-ext:goldExcludeRelationship, add a USERELATIONSHIP "
                "measure,"
            ),
        )

    # --- Star schema -----------------------------------------------------------------
    for item in relationships:
        if is_(item.source_table, GoldTableRole.FACT) and is_(
            item.target_table, GoldTableRole.FACT
        ):
            on_edge(
                FACT_TO_FACT,
                item,
                (
                    f"{edge_label(item)} relates two facts; a fact should reference "
                    "dimensions only, or its totals change with the grain of the other "
                    "fact. Share a dimension instead, model the header as a dimension,"
                ),
            )

    direct: dict[str, set[str]] = {}
    for item in relationships:
        if is_(item.source_table, GoldTableRole.FACT):
            direct.setdefault(item.source_table, set()).add(item.target_table)
    for item in relationships:
        if not (
            is_(item.source_table, GoldTableRole.DIMENSION)
            and is_(item.target_table, GoldTableRole.DIMENSION)
        ):
            continue
        facts = sorted(
            fact
            for fact, reached in direct.items()
            if item.source_table in reached and item.target_table in reached
        )
        if facts:
            on_edge(
                SNOWFLAKE_CHAIN,
                item,
                (
                    f"{edge_label(item)} chains {item.source_table} into "
                    f"{item.target_table}, which {', '.join(facts)} also reference(s) "
                    f"directly, so a filter on {item.target_table} has two routes into the "
                    "fact and one is deactivated. Flatten the chain, drop the direct edge,"
                ),
            )
        else:
            on_edge(
                STAR_SCHEMA,
                item,
                (
                    f"{edge_label(item)} snowflakes {item.source_table} into "
                    f"{item.target_table}. A star schema denormalises the outrigger's "
                    f"attributes into {item.source_table}, so a report filters one table "
                    "per question. Flatten it, or keep it as a deliberate outrigger"
                ),
            )

    # --- Facts: dates and snapshots ----------------------------------------------------
    date_roles: dict[str, int] = {}
    if calendar_table:
        for item in relationships:
            if item.target_table == calendar_table:
                date_roles[item.source_table] = date_roles.get(item.source_table, 0) + 1
    for table in tables:
        if table.role is not GoldTableRole.FACT:
            continue
        roles = date_roles.get(table.name, 0)
        if calendar_table and roles == 0:
            on_table(
                FACT_HAS_DATE,
                table.name,
                (
                    f"{table.name} has no relationship to {calendar_table}; every fact "
                    "records when something happened, and without a date role it cannot "
                    "be sliced by time or used with time intelligence. Bind a role-playing "
                    "date in the calendar policy,"
                ),
            )
        if table.fact_type is FactType.PERIODIC_SNAPSHOT and not calendar_table:
            on_table(
                SNAPSHOT_SHAPE,
                table.name,
                (
                    f"{table.name} is a periodic snapshot but the product has no calendar; "
                    "a snapshot is read one snapshot date at a time. Approve a calendar and "
                    "bind the snapshot date,"
                ),
            )
        if table.fact_type is FactType.ACCUMULATING_SNAPSHOT and calendar_table and roles < 2:
            on_table(
                SNAPSHOT_SHAPE,
                table.name,
                (
                    f"{table.name} is an accumulating snapshot with {roles} date role(s); "
                    "it tracks a process through milestones, so each milestone date is a "
                    "role of the calendar. Bind every milestone date,"
                ),
            )

    # --- Measures --------------------------------------------------------------------
    snapshots = {
        table.name
        for table in tables
        if table.role is GoldTableRole.FACT and table.fact_type is FactType.PERIODIC_SNAPSHOT
    }
    for measure in measures:
        if not measure.emitted:
            continue
        expression = _scannable(measure.expression)
        reads = {table for table, _ in measure.column_dependencies} | {measure.home_table}
        if reads & snapshots and _SUM.search(expression) and not _SEMI_ADDITIVE.search(expression):
            report(
                SEMI_ADDITIVE,
                "measure",
                measure.measure_id,
                measure.resource_uri,
                (
                    f"measure {measure.measure_id!r} sums the periodic snapshot "
                    f"{', '.join(sorted(reads & snapshots))}. A balance summed across "
                    "snapshot dates counts it once per date; take one date's value "
                    "(LASTNONBLANK, CLOSINGBALANCEMONTH) over time. If the table records events rather "
                    'than balances, declare kairos-ext:factType "transaction" instead,'
                ),
            )
        if (
            is_(measure.home_table, GoldTableRole.DIMENSION)
            and measure.home_table != calendar_table
            and not _COUNT.search(expression)
        ):
            report(
                MEASURE_ON_FACT,
                "measure",
                measure.measure_id,
                measure.resource_uri,
                (
                    f"measure {measure.measure_id!r} lives on the dimension "
                    f"{measure.home_table}. Numbers that are aggregated belong on a fact at "
                    "a declared grain; a dimension carries descriptions, and counts of its "
                    "rows. Move the measure to the fact it aggregates,"
                ),
            )

    # --- Bridges ---------------------------------------------------------------------
    weights_read = {
        (table.casefold(), column.casefold())
        for measure in measures
        if measure.emitted
        for table, column in measure.column_dependencies
    }
    for table in tables:
        if table.role is not GoldTableRole.BRIDGE:
            continue
        if table.bridge_weight_column:
            if (table.name.casefold(), table.bridge_weight_column.casefold()) not in weights_read:
                on_table(
                    BRIDGE_WEIGHT,
                    table.name,
                    (
                        f"{table.name} declares the weight column "
                        f"{table.bridge_weight_column!r}, but no measure reads it, so totals "
                        "across the bridge are not allocated. Weight the measures that cross "
                        "it,"
                    ),
                )
        elif table.bridge_cardinality is BridgeCardinality.MANY_TO_MANY:
            on_table(
                BRIDGE_ALLOCATION,
                table.name,
                (
                    f"{table.name} is a many-to-many bridge with no weight column "
                    f"(allocation: {table.bridge_allocation or 'none stated'}). A total "
                    "across it counts a fact row once per endpoint, so the grand total is "
                    "not the sum of its rows. Add a weight, or confirm that is intended,"
                ),
            )

    # --- Conformed and connected -----------------------------------------------------
    first_by_class: dict[str, str] = {}
    first_by_model: dict[str, str] = {}
    for table in tables:
        if table.role is not GoldTableRole.DIMENSION:
            continue
        twin = first_by_class.get(table.resource_uri) or first_by_model.get(table.source_model)
        if twin is not None:
            on_table(
                CONFORMED,
                table.name,
                (
                    f"{table.name} and {twin} are built from the same "
                    + ("class" if first_by_class.get(table.resource_uri) else "Silver model")
                    + "; a product carries one conformed dimension per concept, or a filter "
                    "on one leaves the facts joined to the other unfiltered. Declare the "
                    "owning domain shared (gold.shared_domains) and reuse one table,"
                ),
            )
            continue
        first_by_class.setdefault(table.resource_uri, table.name)
        first_by_model.setdefault(table.source_model, table.name)

    neighbours: dict[str, set[str]] = {name: set() for name in role}
    for item in relationships:
        neighbours.setdefault(item.source_table, set()).add(item.target_table)
        neighbours.setdefault(item.target_table, set()).add(item.source_table)
    reached: set[str] = set()
    queue = deque(sorted(name for name in role if is_(name, GoldTableRole.FACT)))
    reached.update(queue)
    while queue:
        for other in sorted(neighbours.get(queue.popleft(), ())):
            if other not in reached:
                reached.add(other)
                queue.append(other)
    has_fact = any(item is GoldTableRole.FACT for item in role.values())
    for name in sorted(role):
        if is_(name, GoldTableRole.FACT) and not neighbours.get(name):
            on_table(
                CONNECTED,
                name,
                (
                    f"{name} has no relationships, so no dimension filters it; a fact is "
                    "analysed through its dimensions. Bind its foreign keys,"
                ),
            )
        elif has_fact and name not in reached:
            on_table(
                CONNECTED,
                name,
                (
                    f"{name} reaches no fact, so selecting it filters nothing in this "
                    "product. Relate it to a fact, or leave it out of the product,"
                ),
            )

    # --- One business process per product ---------------------------------------------
    # A fact with no relationships is already reported as unconnected; counting it as
    # a process of its own would only repeat that.
    facts = sorted(name for name in role if is_(name, GoldTableRole.FACT) and neighbours.get(name))
    shared_dims: dict[str, set[str]] = {
        fact: {
            target
            for target in direct.get(fact, set())
            if is_(target, GoldTableRole.DIMENSION) and target != calendar_table
        }
        for fact in facts
    }
    parent = {fact: fact for fact in facts}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for index, left in enumerate(facts):
        for right in facts[index + 1 :]:
            if shared_dims[left] & shared_dims[right]:
                parent[find(left)] = find(right)
    groups: dict[str, list[str]] = {}
    for fact in facts:
        groups.setdefault(find(fact), []).append(fact)
    if len(groups) > 1:
        described = "; ".join(
            ", ".join(members) for members in sorted(groups.values(), key=lambda item: item[0])
        )
        report(
            ONE_PROCESS,
            "model",
            "",
            "",
            (
                f"the facts fall into {len(groups)} groups that share no dimension other "
                f"than the calendar ({described}). Kimball's bus matrix gives each business "
                "process its own product joined by conformed dimensions; facts that share "
                "none cannot be analysed together. Split the product, or conform a dimension,"
            ),
        )

    # --- Naming ------------------------------------------------------------------------
    for table in tables:
        own = _NAME_PREFIX.get(table.role, ())
        others = [
            prefix
            for other_role, prefixes in _NAME_PREFIX.items()
            if other_role is not table.role
            for prefix in prefixes
        ]
        name = table.name.casefold()
        if any(name.startswith(prefix) for prefix in others) and not any(
            name.startswith(prefix) for prefix in own
        ):
            on_table(
                NAME_ROLE,
                table.name,
                (
                    f"{table.name} is a {table.role.value} whose name says otherwise; report "
                    "authors read the prefix to tell facts from dimensions. Rename it with "
                    "kairos-ext:goldTableName,"
                ),
            )

    stale = sorted(
        (
            item
            for item in exceptions
            if item.rule_id in CODES
            and (item.rule_id, item.kind, item.target.casefold()) not in used
        ),
        key=lambda item: (item.rule_id, item.kind, item.target),
    )
    if stale:
        item = stale[0]
        raise GoldContractError(
            "gold.bpa-ignore-unused",
            (
                f"practiceException {item.source!r} excuses a finding the compiler does not "
                f"make: {item.kind} {item.target!r} does not break {item.rule_id}. Remove "
                "it, so the exception cannot outlive the reason it was written"
            ),
            rule_id=_RULE,
        )
    return tuple(findings)


def bus_matrix(
    tables: tuple[GoldTableSpec, ...],
    relationships: tuple[GoldRelationshipSpec, ...],
    *,
    calendar_table: str = "",
) -> str:
    """Render the product's Kimball bus matrix: one row per fact, one column per dimension.

    A cell counts the fact's relationships to that dimension -- more than one is a
    role-playing dimension -- with ``*`` when none of them is active. Deterministic.
    """
    role = {table.name: table.role for table in tables}
    if calendar_table:
        role[calendar_table] = GoldTableRole.DIMENSION
    facts = sorted(name for name, kind in role.items() if kind is GoldTableRole.FACT)
    dimensions = sorted(name for name, kind in role.items() if kind is GoldTableRole.DIMENSION)
    if not facts or not dimensions:
        return ""
    cells: dict[tuple[str, str], list[GoldRelationshipSpec]] = {}
    for item in relationships:
        if item.source_table in facts and item.target_table in dimensions:
            cells.setdefault((item.source_table, item.target_table), []).append(item)
    lines = [
        "| Fact | " + " | ".join(f"`{name}`" for name in dimensions) + " |",
        "|---|" + "---|" * len(dimensions),
    ]
    for fact in facts:
        row = []
        for dimension in dimensions:
            edges = cells.get((fact, dimension), [])
            if not edges:
                row.append("")
                continue
            mark = "✓" if len(edges) == 1 else f"✓×{len(edges)}"
            row.append(mark + ("" if any(edge.is_active for edge in edges) else " *"))
        lines.append(f"| `{fact}` | " + " | ".join(row) + " |")
    shared = [
        name for name in dimensions if sum(1 for fact in facts if cells.get((fact, name))) > 1
    ]
    return "\n".join(
        [
            *lines,
            "",
            "✓ one relationship · ✓×N a role-playing dimension (N roles) · * no active "
            "relationship: the dimension does not filter that fact.",
            "",
            "Conformed across facts: "
            + (", ".join(f"`{name}`" for name in shared) if shared else "none"),
        ]
    )
