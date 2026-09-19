# DD-228: A domain may be declared shared, and is then read by several products rather than built by them

**Status:** Accepted
**Date:** 2026-09-19
**Affects:** `core/projections/dbt/gold_connection.py` (new `gold.shared_domains` block,
`GoldProductConfig.shared_domains`/`owns`, `parse_gold_products`, `resolve_gold_product`),
`core/projections/dbt/gold_specs.py` (`GoldTableSpec.shared`/`owner_domain`),
`core/projections/dbt/gold_shape.py` (`GoldDomainInput.shared`,
`_shape_dimensional_product`), `core/projections/dbt/gold_render.py` (DDL annotation,
product report `materialized_by`), `core/projections/medallion_gold_projector.py`,
`cli/emit_gold.py` (`_shared_domain_artifacts`, `_report_shared_tables`),
`scaffold/ontology-hub/kairos.yaml.template`, `tests/test_gold_shared_domains.py`
**Issue:** #829 (split from #744). **Answers the question DD-222 deferred.**

### Context

DD-222 closed with an explicit deferral: *"whether two products may share a domain. They
may not… If a genuinely shared conformed dimension needs to appear in several products,
that is a real requirement and gets its own decision."*

It is a real requirement. On a 14-domain logistics hub, harvested across 18 PBIP exports
and 2,058 visual containers (DD-223), the most-placed attributes are `Shipment ID` (80
placements, 11 reports), `Carrier Name` (61 / 11), `Destination` and `Origin` (53 each),
`Customer Name` (43 / 8). They come from `party`, `reference-data` and `fracht-company`,
and they carry **both** the volume cluster and the financial cluster. That is the textbook
definition of a conformed dimension, and the bus matrix DD-222 invokes exists precisely to
share them.

The rule that blocked it reads:

> domain 'party' is claimed by both 'shipment-performance' and 'financial-performance'; a
> domain belongs to exactly one Gold product

DD-222's reasoning for it was sound — two products over one domain would emit its tables
twice under two model names, with no way for a report author to tell which is
authoritative. **But the rule is enforced on _domains_, while the thing that must not be
duplicated is a _table_.** Those coincide for a fact-bearing domain and diverge for a
dimension-only one, which is exactly what a conformed dimension is.

The two options a hub had were both bad. One product containing everything works, and is
what that hub chose, but the product then no longer follows a business process — it
follows *whatever shares a dimension*, which on a logistics hub is everything, and each
newly bound domain gets absorbed. Splitting by process leaves whichever product lost
`party` emitting customer join keys with no customer table; `emit-gold` reports those
honestly as `unresolved_relationships`, so nothing is silently wrong, but the model is not
shippable.

### Decision

**A domain may be declared shared, in `kairos.yaml`, beside the products that read it.**

```yaml
gold:
  shared_domains: [party, reference-data]
  products:
    - name: shipment-performance
      domains: [consignment, party, reference-data]
    - name: financial-performance
      domains: [billing, party, reference-data]
```

**Declared, never inferred.** Sharing could be guessed from a domain authoring only
dimensions and no facts. It is not, because then adding the first fact to that domain would
silently re-materialize every one of its tables in every consuming product — a change in
physical layout with no edit anywhere to say so. An explicit list makes it a decision
somebody wrote down.

**The one-owner rule survives verbatim for an undeclared domain.** DD-222's reasoning still
holds wherever sharing was not declared, so the error is unchanged apart from naming
`gold.shared_domains` as the way to say otherwise.

**Nothing changes about materialization, because nothing had to.** A Gold dbt model is
already emitted per *domain*, to `models/gold/<domain>/<table>.sql`, by that domain's own
`compile --emit`; products exist only in the Power BI lane. So a conformed dimension was
always built exactly once. What a shared domain changes is only that several products may
*read* it. This is why the change is as small as it is, and it is worth stating plainly
because the issue — and an earlier draft of this decision — assumed a per-product
materialization that does not exist.

**A shared table keeps its own domain's schema.** `GoldTableSpec.schema_name` is already
per-table, so a product's TMDL partition names `gold_party` for the shared table and the
product's own schema for the rest, and both products' semantic models point at the one
physical relation. Verified end-to-end rather than assumed: this is the assumption that
would otherwise produce a model silently pointing at the wrong schema, discovered in
Fabric.

**A shared table is reported as read, not built, everywhere a reader might assume
otherwise.** The product report carries `materialized_by: {domain, shared: true}`, the DDL
block carries a comment naming the owning domain, and `emit-gold` prints the owned/shared
split. The DDL still *declares* the table, as it already does for `dim_date` — it
documents the shape the product reads — but never presents it as something this product's
emit creates.

**A shared domain's own name no longer resolves to a product.** `emit-gold party` where
`party` is shared by two products is ambiguous, and picking one would emit a model whose
name says nothing about which it is. It fails with `gold.domain-shared-across-products`,
naming every product that reads it.

**Artifacts a shared domain writes per participating domain are declared mergeable.** The
provenance sidecar is emitted once per participating domain, so a shared domain writes
`metadata/<domain>-gold.provenance.json` from several products. The document is a pure
function of that domain's build scope — `build_provenance_document` reads nothing about
the product — so every product writes byte-identical content, and declaring it in
`replace_unowned_paths` is the same treatment `parameter.yml` already gets (#664).

### Consequences

A hub can follow the bus matrix DD-222 invoked: facts per business process, conformed
dimensions shared across them, one physical copy of each dimension.

A genuine table-name collision still fails. `_shape_dimensional_product`'s `owner_of` check
is intra-product and unchanged: sharing relaxes *who materializes* a table, not whether two
different tables may carry one name.

A product may now consist entirely of shared domains and build nothing itself. That is
reported (`0 table(s) built by this product`) rather than rejected — it is a legitimate
shape for a model that only slices conformed dimensions, and an authoring stage on the way
to a product that will have its own fact.

Deliberately **not** decided here: which product is the governance owner of a shared table.
The emit reports the owning *domain*, which is where the table is built and where its
authoring lives; a separate stewardship concept would need a real requirement behind it.

Related: #849, which made `models/gold/shared/` hub-owned so that the calendar — the
original shared Gold table, and the proof this shape works — could be authored by more than
one domain.
