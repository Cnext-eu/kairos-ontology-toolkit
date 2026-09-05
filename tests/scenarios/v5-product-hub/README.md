# `v5-product-hub` — a Gold product that spans two domains

The fixture behind issue #744. Two domains, one analytical product:

- **`party`** owns `Customer` and `Country`. The conformed dimension side.
- **`billing`** owns `Invoice`, a fact whose `billedTo` relationship targets
  `party:Customer` through a **DD-138 `externalReference`** in
  `integration/bindings/invoice.binding.yaml`.

That external reference is the precondition for everything this fixture tests. Without
it the compiler blocks the cross-domain endpoint with `safety.relationship-endpoint`, so
the relationship never reaches a compile plan and there is nothing for Gold to resolve.
With it, compiling `billing` materializes a `customer_sk` column on the `invoice` Silver
model — but `customer` is not in the `billing` Silver registry, because a Silver model is
only materialized by the compile of the domain that binds it.

Before #744 that was the end of the story: `_shape_relationships` found no `dim_customer`
among the `billing` product's tables, skipped the descriptor, and emitted a semantic model
whose fact carried a dead `customer_sk` and joined to nothing. No diagnostic.

Now `emit-gold` builds one compile plan per participating domain and shapes the product
over the union, so the relationship resolves. `party:Country` is deliberately left
*without* a Gold table, so the same fixture also covers the reverse case: a foreign key
whose target is outside the product is reported in `unresolved_relationships` rather than
vanishing.

`catalog-v001.xml` maps both ontology IRIs to their files; `billing.ttl`'s `owl:imports`
of `party` cannot resolve without it.

Gold extensions are **not** committed here. Each test writes the ones it needs, so a
single fixture serves the multi-domain product, the single-domain fallback, and the
collision cases.
