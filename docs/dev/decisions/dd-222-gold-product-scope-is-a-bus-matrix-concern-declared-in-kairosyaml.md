# DD-222: Gold product scope is a bus-matrix concern, declared in kairos.yaml

**Status:** Accepted
**Date:** 2026-09-05
**Affects:** `core/projections/dbt/gold_connection.py` (new `gold.products` block,
`GoldProductConfig`, `resolve_gold_product`), `core/projections/dbt/gold_shape.py`
(`_shape_tables` / `_shape_dimensional_product` split, `_sole`, unresolved relationships),
`core/projections/dbt/gold_specs.py`, `core/projections/dbt/gold_render.py`,
`core/projections/medallion_gold_projector.py` (`plan_gold_from_compile_plans`),
`cli/emit_gold.py`, `cli/package_powerbi_release.py`,
`scaffold/ontology-hub/kairos.yaml.template`, new `tests/scenarios/v5-product-hub/`,
new `tests/test_gold_product_scope.py`, new `tests/test_cli_emit_gold_product.py`
**Issue:** #744 (part 1). **Supersedes the position taken in #661.**

### Context

A Gold product was one ontology domain, and nothing in `kairos.yaml` or `kairos-ext` could
change that. Product identity was `spec.ontology_name`, taken from a single-domain
`CompilePlan`; every emitted path was derived from it; and `_shape_relationships` skipped
any foreign key whose target class lived in another domain.

That skip was not an oversight. It was the fix for #207, where per-domain models emitted
relationships to dimension tables that did not exist locally and failed validation. #661
then closed as "the compiler's behavior here is correct", and the
`gold.unmaterialized-silver-source` message still tells authors that a cross-domain product
needs one extension per owning domain, emitted separately.

The consequence on a real reporting hub: a `party` product with three dimensions and one
role-assignment fact, whose `legalentity_sk` pointed at a class in a sibling `company`
domain. `relationships.tmdl` carried only the two intra-domain relationships. The
legal-entity join was a dead column, and there was no diagnostic — the only way to slice
roles by legal entity was a hand edit in Desktop that the next emit overwrote.

Ontology domains are a *modelling* boundary. Analytical products follow *business
processes* and are built from a bus matrix: facts from consignment, booking or financial,
conformed dimensions from party, company, reference-data and a date table. A
dimension-only domain such as `party` has no natural fact, so a per-domain "Party" model is
thin by construction, and a workspace of N narrow models per domain is the stovepipe data
mart the bus matrix exists to prevent. The platform does not force the split either: since
Direct Lake on OneLake, one model reads tables from several schemas and several lakehouses.

### Decision

**Product scope is declared in `kairos.yaml`, not in TTL.** A `gold.products` list names
the product and the domains it is built from. It is a delivery and packaging concern —
which tables ship as one Fabric item — not a semantic claim about the ontology, and the
hub already keeps that class of decision (adapter, connections, publish layout) in
`kairos.yaml`. Putting it in TTL would have meant new vocabulary, new SHACL and a new
authoring surface for a list of names.

**A hub that declares nothing is unchanged.** Every Gold-configured domain that no product
claims stays its own implicit product under its own name, and a single-domain product is
the N=1 case of the multi-domain path rather than a second code path. Emitted paths,
manifest names and the `.SemanticModel` layout are byte-identical, and the product report
gains no keys.

**Silver compilation stays per domain; only Gold shaping spans them.** `emit-gold
<product>` builds one `CompilePlan` per participating domain — exactly as before, each with
its own provenance sidecar — and shapes tables per domain before assembling relationships,
measures, calendar, security and perspectives over the union. Tables are the only genuinely
per-domain part: a Silver model is materialized by the compile of the domain that binds it.

Splitting shaping this way rather than merging finished per-domain products is
load-bearing, not stylistic: `_shape_measures` raises on a DAX reference to a table in
another domain, and `_shape_calendar` and `_shape_security` raise on a binding to a column
in one. Every one of those would have fired before a merge could see the union.

**A dangling foreign key is reported, not dropped.** Where #207's fix skipped silently,
`unresolved_relationships` now records `(property, source_table, target_class)` for any
foreign key whose join column was materialized but whose target is not in the product. It
lands in the product report and `emit-gold` prints it. It is a warning, not an error: the
model is valid and useful without the join, and the fix is an authoring decision — add the
owning domain to the product, or accept the column.

**One calendar and one security policy per product**, declared by exactly one participating
domain and inherited by the product. Two competing declarations have no defensible merge,
so they fail closed. This is also what makes a hub-wide calendar possible at all: one
domain declares it, every product that includes that domain gets it.

**Cross-domain relationships still require a DD-138 `externalReference`** in the child's
EntityBinding. Nothing here relaxes that: without one the compiler blocks the endpoint with
`safety.relationship-endpoint` and the relationship never reaches a plan. What changed is
only that a descriptor which *does* reach the plan can now resolve its target.

**Moving a domain into a product retires its previous per-domain emit.** `emit_artifacts`
only removes files its own manifest owns, so the superseded `<Domain>.SemanticModel` tree
would otherwise survive on disk, be merged into the master ERD by its disk scan, and be
deployed by fabric-cicd beside the product it was replaced by.

### Consequences

A bus-matrix product is authorable. The dbt side is untouched: Gold models stay under
`models/gold/<domain>/`, exposures stay per domain, and the physical tables keep the schema
of the domain that binds them — a product spanning two domains emits one `CREATE SCHEMA`
per domain, which is correct, because the product is a semantic-model boundary and not a
storage one.

`package-powerbi-release` iterates products; a hub with no declared product packages
exactly what it packaged before, one item per Gold-configured domain.

Deliberately **not** decided here: whether two products may share a domain. They may not,
because one Gold table would then be emitted twice under two model names with no way for a
report author to tell which is authoritative. If a genuinely shared conformed dimension
needs to appear in several products, that is a real requirement and gets its own decision.

DD-112's per-domain framing is superseded for *scope only*; its profile, role and grain
rules are unchanged.
