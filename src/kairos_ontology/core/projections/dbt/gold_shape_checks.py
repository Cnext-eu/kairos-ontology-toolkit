# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Model-shape checks over a shaped Gold product (DD-240, issue #996).

The BPA checks in ``gold_bpa_checks`` judge objects one at a time. These judge how the
tables fit together -- whether facts reference only dimensions, whether a dimension chain
duplicates a direct edge, which relationships the projector deactivated and what route
they lost to. Each finding is a catalogued practice (``practices/semantic-model``).

They run only on the whole product. On a single-domain compile the other domains' tables
are missing, so a route may look ambiguous, or unambiguous, only because half the model is
absent; ``compile --check`` therefore runs them in a product pass after the domains
compile, and ``emit-gold`` runs them on the product it emits.

Every finding is a warning or an advisory, never blocking: each is a design question with
a legitimate "yes, deliberately" answer, recorded as a ``kairos-ext:practiceException``.
"""

from __future__ import annotations

from collections import deque

from .bpa_profile import BpaIgnore
from .gold_bpa_checks import GoldAdvisory
from .gold_specs import GoldContractError, GoldRelationshipSpec, GoldTableSpec
from .policy_specs import GoldTableRole

_RULE = "DD-240-practices"

AMBIGUOUS_PATH = "semantic-model.ambiguous-path"
FACT_TO_FACT = "semantic-model.fact-to-fact"
SNOWFLAKE_CHAIN = "semantic-model.snowflake-chain"
ROLE_PLAYING = "semantic-model.role-playing-dimension"

#: Practice -> the diagnostic code that reports it.
CODES = {
    AMBIGUOUS_PATH: "gold.ambiguous-path",
    FACT_TO_FACT: "gold.fact-to-fact",
    SNOWFLAKE_CHAIN: "gold.snowflake-chain",
    ROLE_PLAYING: "gold.role-playing-dimension",
}


def edge_label(item: GoldRelationshipSpec) -> str:
    """The ``Table.column -> Table.column`` form an exception names an edge by."""
    return f"{item.source_table}.{item.source_column} -> {item.target_table}.{item.target_column}"


def active_route(
    relationships: tuple[GoldRelationshipSpec, ...], start: str, end: str
) -> list[str]:
    """The tables on the active path from *start* to *end*, or ``[]`` when none.

    The active edges form a forest (``_resolve_ambiguous_paths``), so there is at most
    one such path; a breadth-first search over the undirected active graph finds it.
    """
    neighbours: dict[str, list[str]] = {}
    for item in relationships:
        if item.is_active:
            neighbours.setdefault(item.source_table, []).append(item.target_table)
            neighbours.setdefault(item.target_table, []).append(item.source_table)
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


def _how_to_excuse(practice_id: str, item: GoldRelationshipSpec) -> str:
    return (
        f'or record kairos-ext:practiceException "{practice_id} on relationship '
        f'{edge_label(item)}: <reason>"'
    )


def check_model_shape(
    tables: tuple[GoldTableSpec, ...],
    relationships: tuple[GoldRelationshipSpec, ...],
    exceptions: tuple[BpaIgnore, ...],
    *,
    extra_dimensions: frozenset[str] = frozenset(),
) -> tuple[GoldAdvisory, ...]:
    """Return the shape findings; fail an exception to a shape rule that excuses nothing.

    *extra_dimensions* names emitted tables that are not in *tables* -- ``dim_date``,
    which the calendar contributes.
    """
    role = {table.name: table.role for table in tables}
    role.update({name: GoldTableRole.DIMENSION for name in extra_dimensions})
    resource = {table.name: table.resource_uri for table in tables}
    excused = {
        (item.rule_id, item.target.casefold()) for item in exceptions if item.rule_id in CODES
    }
    used: set[tuple[str, str]] = set()
    findings: list[GoldAdvisory] = []

    def report(practice_id: str, item: GoldRelationshipSpec, message: str) -> None:
        key = (practice_id, edge_label(item).casefold())
        if key in excused:
            used.add(key)
            return
        findings.append(
            GoldAdvisory(CODES[practice_id], message, resource.get(item.source_table, ""))
        )

    for item in relationships:
        if item.inactive_reason != "ambiguous-path":
            continue
        active_sibling = next(
            (
                other
                for other in relationships
                if other.is_active
                and other.source_table == item.source_table
                and other.target_table == item.target_table
            ),
            None,
        )
        if active_sibling is not None:
            report(
                ROLE_PLAYING,
                item,
                (
                    f"{edge_label(item)} is an inactive role of {item.target_table}: "
                    f"{edge_label(active_sibling)} is the active one, so this role filters "
                    "nothing unless a measure calls USERELATIONSHIP. Decide per role between "
                    f"that and a separate copy of {item.target_table}, "
                    + _how_to_excuse(ROLE_PLAYING, item)
                ),
            )
            continue
        route = active_route(relationships, item.source_table, item.target_table)
        via = " -> ".join(route) if route else "another active path"
        # Several roles of one dimension, none of them active: the dimension reaches the
        # fact by another route entirely, which is a shape problem, not a role choice.
        roles = sum(
            1
            for other in relationships
            if (other.source_table, other.target_table) == (item.source_table, item.target_table)
        )
        role_note = (
            f" None of the {roles} edges from {item.source_table} to {item.target_table} is active."
            if roles > 1
            else ""
        )
        report(
            AMBIGUOUS_PATH,
            item,
            (
                f"{edge_label(item)} is inactive (ambiguous-path): {item.target_table} "
                f"already filters {item.source_table} through {via}, so this edge filters "
                f"nothing unless a measure calls USERELATIONSHIP.{role_note} Keep it active with "
                "kairos-ext:goldPrimaryRelationship, remove the redundant route, "
                + _how_to_excuse(AMBIGUOUS_PATH, item)
            ),
        )

    for item in relationships:
        if role.get(item.source_table) is role.get(item.target_table) is GoldTableRole.FACT:
            report(
                FACT_TO_FACT,
                item,
                (
                    f"{edge_label(item)} relates two facts; a fact should reference "
                    "dimensions only, or its totals change with the grain of the other "
                    "fact. Share a dimension instead, model the header as a dimension, "
                    + _how_to_excuse(FACT_TO_FACT, item)
                ),
            )

    targets: dict[str, set[str]] = {}
    for item in relationships:
        if role.get(item.source_table) is GoldTableRole.FACT:
            targets.setdefault(item.source_table, set()).add(item.target_table)
    for item in relationships:
        if not (
            role.get(item.source_table) is role.get(item.target_table) is GoldTableRole.DIMENSION
        ):
            continue
        facts = sorted(
            fact
            for fact, reached in targets.items()
            if item.source_table in reached and item.target_table in reached
        )
        if facts:
            report(
                SNOWFLAKE_CHAIN,
                item,
                (
                    f"{edge_label(item)} chains {item.source_table} into "
                    f"{item.target_table}, which {', '.join(facts)} also reference(s) "
                    f"directly, so a filter on {item.target_table} has two routes into the "
                    "fact and one is deactivated. Flatten the chain, drop the direct edge, "
                    + _how_to_excuse(SNOWFLAKE_CHAIN, item)
                ),
            )

    stale = sorted(
        (
            item
            for item in exceptions
            if item.rule_id in CODES and (item.rule_id, item.target.casefold()) not in used
        ),
        key=lambda item: (item.rule_id, item.target),
    )
    if stale:
        item = stale[0]
        raise GoldContractError(
            "gold.bpa-ignore-unused",
            (
                f"practiceException {item.source!r} excuses a finding the compiler does not "
                f"make: relationship {item.target!r} does not break {item.rule_id}. Remove "
                "it, so the exception cannot outlive the reason it was written"
            ),
            rule_id=_RULE,
        )
    return tuple(findings)
