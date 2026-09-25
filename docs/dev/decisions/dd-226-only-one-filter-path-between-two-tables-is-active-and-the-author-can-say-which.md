# DD-226: Only one filter path between two tables is active, and the author can say which

**Status:** Accepted
**Date:** 2026-09-16
**Affects:** `core/projections/dbt/gold_specs.py` (`GoldRelationshipSpec.is_active`,
`.guid_seed`), `core/projections/dbt/gold_shape.py` (`_calendar_relationships`,
`_resolve_ambiguous_paths`, `_primary_relationship_keys`, `_column_by_property`,
`_shape_dimensional_product` ordering), `core/projections/dbt/gold_render.py`
(`_relationships_tmdl`, `_erd`, `gold_product_report`),
`core/projections/dbt/policy_{specs,bind,normalize}.py`, `scaffold/kairos-ext.ttl`
(new `kairos-ext:goldPrimaryRelationship`), new `tests/test_gold_relationship_activation.py`
**Issue:** #792

### Context

Power BI allows exactly one **active** filter path between any two tables. The projector
emitted every relationship active — not one carried `isActive: false` — while routinely
emitting role-playing dimensions (several date roles on one fact) and snowflake shortcuts
(a direct edge alongside the two-hop path it duplicates). The resulting model is unloadable
in Fabric and in Desktop.

On the product that surfaced this, **21 of 50 relationships closed a cycle**. The service
reports one offending pair per attempt, so discovering them by publishing costs 21 round
trips. Both offline gates passed: one never reads TMDL, the other only proves it
deserializes.

Worse, the role-playing edges were **invented in the renderer**, one per calendar role,
straight into `relationships.tmdl`. They never existed in `spec.relationships`, so nothing
that reasoned over the relationship set could see the edges causing most of the ambiguity.

### Decision

**Calendar role edges are shaped, not invented.** `_calendar_relationships` builds a
`GoldRelationshipSpec` per role and `_relationships_tmdl` becomes a pure renderer. This is
also what DD-110 already required: render may not choose deviations, and inventing an edge
is a shape concern.

**Every edge beyond a spanning forest is emitted `isActive: false`.** Union-find over the
undirected relationship graph, in a fixed priority order. Cycle is an over-approximation of
ambiguity in general, but every edge emitted here is single-direction many-to-one, and for
those the two coincide.

> **Superseded (#1012).** They do not coincide. Two facts related many-to-one to the same
> two dimensions form an undirected cycle, yet a filter only flows from a dimension to a
> fact, so no table reaches another by two routes and Power BI loads all four edges. This
> is the ordinary bus matrix, and the forest deactivated one edge of every such square.
> On a multi-fact product it cut the core fact off its main dimensions. An edge is now
> deactivated only if it would give some table a second *directed* filter route to
> another table, or a route back to itself. A filter crosses an edge from its one side to
> its many side, and also back when the edge filters both ways. Edges are still taken in
> the priority order below. Bridge directions depend on which edges are active, so the
> product resolves once, decides the bridge directions (DD-238), and then resolves again
> with them. A default two-way filter on an edge that ends up inactive is cleared. The
> `gold.ambiguous-path` message names the table that would reach another twice and both
> routes. **Consequence:** a hub with a bus-matrix square gets edges re-activated in
> `relationships.tmdl`. The "byte-identical" promise below still holds for a hub whose
> ambiguity was only same-pair duplicates, snowflake shortcuts or date roles on one fact,
> and for every scenario fixture.

**The priority order is: authored primary, then ordinary foreign-key and bridge edges, then
calendar roles.** Keeping role edges last means a business relationship is never deactivated
in favour of a date role. Within a group the existing deterministic sort applies.

**When several roles are undeclared, pick deterministically and report loudly — do not fail
closed.** Which date role is active is load-bearing: `DATESYTD('dim_date'[full_date])`
follows the active edge, so the choice is the product's fiscal semantics. Failing closed
would block every existing multi-role hub; picking silently would change a report's meaning
with nothing to review. So the projector picks, and lists every deactivated relationship in
`gold_product_report` under `deactivated_relationships`.

**The author overrides with `kairos-ext:goldPrimaryRelationship`, an edge-level term.**
`"Table.column -> Table.column"`, repeatable on the `owl:Ontology` resource, fail-closed on
a value matching no emitted relationship (`gold.unknown-primary-relationship`), mirroring
`goldExcludeColumn` (DD-217). One term covers both ambiguity sources — a primary date role
and a snowflake shortcut between two arbitrary tables.

Deliberately **not** in `kairos.yaml`'s `gold.products` block (DD-222). That block is
product *scope*, a delivery concern, and `GoldProductConfig` never reaches the shaper:
`shape_gold_products` takes a product *name*, and `shape.py`'s `shape_gold_product` is a
pure function over the `ProjectionContract` with no `hub_root`. Authoring it there would
make `compile --emit` compute a different forest than `emit-gold` — precisely the two-path
divergence DD-225 was about.

**`guid_seed` preserves the emitted relationship names.** Calendar edges were seeded
`calendar.<role>` in the renderer and ordinary edges `name + source_table`. In Fabric a
renamed relationship is a *new object*, not an edit, so moving role edges into the shaper
must not silently re-identify every date relationship in every hub.

**`dim_date` becomes resolvable as a measure column dependency.** Deactivating an edge
forces report authors onto `USERELATIONSHIP`, which needs `dim_date[full_date]` as a
declared dependency — and `_column_by_property` resolved only against `spec.tables`, which
never contains the synthesized calendar. Without this, #792 would deactivate edges and
simultaneously make the only DAX workaround uncompilable.

### Consequences

- A hub with no ambiguity emits **byte-identical** output. Verified across every artifact of
  both scenario fixtures: 55 artifacts, zero differences.
- A hub *with* ambiguity gets a model that loads. Its `relationships.tmdl` gains
  `isActive: false` lines, and its ERD labels the edge `(inactive)`.
- An inactive relationship is still in the model: it carries its endpoints, is reachable
  from DAX with `USERELATIONSHIP`, and is reported so the choice can be reviewed.
- The spanning forest is stable for a given relationship set, but adding a new dimension can
  change which of two pre-existing edges is active. That is why the deactivated set is
  reported and why the authored override exists — a hub that cares should declare it rather
  than depend on the tie-break.
- `GoldRelationshipSpec.cardinality` is still computed and still unread by any renderer.
  Emitting `fromCardinality`/`toCardinality` would change bytes for every existing hub for
  no correctness gain today, so it stays out of this change.
- **Amended by DD-240**: a deactivated edge that no measure activates with
  `USERELATIONSHIP` is reported as `gold.ambiguous-path` by `compile --check` and
  `emit-gold`, so BPA `INACTIVE_RELATIONSHIPS_THAT_ARE_NEVER_ACTIVATED` is checked rather
  than rejected. The deactivation itself is unchanged.
- **Amended (#1012)**: `kairos-ext:goldExcludeRelationship "Table.column -> Table.column"`
  leaves one foreign-key or bridge edge out of a product. It is the Gold term for "remove
  the redundant route", which before could only be done by deleting a true relationship from
  the Silver binding. It is fail-closed like `goldExcludeColumn` (DD-217): a malformed value
  fails every compile, and a stale value fails where both tables are in scope. It is matched
  on the foreign key's own column name before the emitted-column check, so the column can be
  excluded as well. `goldPrimaryRelationship` and `goldExcludeRelationship` values that name
  another domain's table are deferred on the single-domain compile and checked at product
  level, the #763 bridge contract (see the DD-222 amendment).
