# DD-252: A single-valued value object's scalars are fields of its parent, named through via

**Status:** Accepted
**Date:** 2026-09-27
**Affects:** the EntityBinding `fields:` grammar (`via`), `core/compiler/bindings.py`,
`core/compiler/adapter.py`, `core/compiler/kernel.py` (`_ontology_symbols`,
`resolve_scope`, the field safety checks), `core/compiler/contract_conformance.py`,
`core/projections/dbt/mapping_specs.py`, `mapping_normalize.py`, `normalize.py`,
`core/fit_report.py`, the `kairos-design-mapping` skill
**Issue:** #811 (amends DD-133 §5 rule 3; reads the bound DD-241 declares)

### Context

Reference models express most of their richness through object properties whose range is a
value object: `cargo:hasWeight` → `Weight{weightValue, weightUnit}`, `imo:hasFlagState` →
`FlagState{flagStateCountryCode}`. `fields:` materializes scalars only, and
`binding.object-property-in-fields` rejects an object property there (DD-133 §5 rule 3,
#280). The only route was a companion binding on the range class plus a `relationships:`
entry. That produces one Silver table per value object, for example a `cargo_weight` table
with exactly one row per cargo, to carry one number. Authors took the other exit instead:
`technicalFields` with `purpose: carried`. On one hub that was 24 carried columns with no
ontology property behind them. The Silver columns looked canonical and were not.

Inlining a value object's scalar onto the parent is only sound when the parent has **at
most one** value object through that property. Otherwise one parent row would have to
hold several weights. DD-241 makes OWL the one place that bound is declared. A probe of
every current reference ontology on 2026-09-27 found that of the value objects #811 names,
only `imo:hasFlagState` carries a max-1 restriction. `cargo:hasWeight`, `hasDimension`,
`hasMeasurement`, `imo:hasVesselType` and `hasIMONumber` carry no bound in OWL or in SHACL.
A rule that reads the bound therefore rejects the lead example unless something declares
it.

### Decision

**A `fields:` entry may name a datatype property of a value object, reached through a
single-valued object property named in `via`:**

```yaml
fields:
  - property: cargo:weightValue      # a datatype property of the range class
    via: cargo:hasGrossWeight         # an object property of the bound class
    expression: GROSSWEIGHT
```

- **`property` stays a real property token.** The path is not encoded in it: a `/`-joined
  path would collide with full IRIs, and about ten readers key on the token as it is.
- **`via` is one hop.** It must be an object property the bound class exposes, and the
  `property` must be a datatype property its named range exposes. A value object inside a
  value object is out of scope.
- **The bound is read from OWL, never from the binding.** `via` must be bounded to at most
  one on the bound class or an ancestor: `owl:FunctionalProperty`, or an `owl:maxCardinality`,
  `owl:cardinality` or qualified restriction of 1. It is read by the same
  `edge_multiplicities` the class diagram and the DD-241 compile cross-check use. When no
  bound is declared, `binding.value-object-not-single-valued` blocks the binding. Its
  message prints the restriction to add to the hub's own class, where DD-241 says the claim
  belongs:

  ```turtle
  :RoRoCargoUnit rdfs:subClassOf [ a owl:Restriction ;
      owl:onProperty cargo:hasGrossWeight ; owl:maxCardinality 1 ] .
  ```

  The bound should also be filed upstream against the reference model, after which the
  local restriction is redundant.
- **The column is named from both hops.** The stem is `via`'s local name without a
  leading `has`, the rest is `property`'s local name, and a word the two share at the seam
  is written once. `hasGrossWeight` and `weightValue` give `gross_weight_value`.
  `hasWeight` and `weightUnit` give `weight_unit`. `hasFlagState` and
  `flagStateCountryCode` give `flag_state_country_code`. So two value objects of the same
  class, such as gross and net weight, produce two columns.
- **The canonical annotation keeps both.** The mapping keeps the leaf as
  `target_property_uri` and adds `via_property_uri`. The Silver column's provenance
  carries `property:<leaf>` and `via:<object property>`. A field without `via` produces
  byte-identical specs and hashes (`optional_field`). "One mapping per target property per
  source table" is keyed on `(via, property)`.

### Consequences

- **The companion route stays valid** and is still the answer for a multi-valued range, a
  value object with its own identity, or a range an author wants as its own table.
- **fit-report** counts a `via` field as populating the `via` object property on the
  parent. It is the property the parent's universe lists, and the leaf lives on the range
  class.
- **Out of scope in this slice, each with a diagnostic rather than silence:**
  - A class governed by a Silver contract (DD-213). The contract's `termRef` cannot
    express a path, so `contract.value-object-field-unsupported` blocks it until contracts
    gain one.
  - Multi-hop paths, and a `via` whose range is not a named class.
- **Rejected: a binding-side assertion** such as `single: true` on the field. That makes
  the binding a second place where cardinality is declared, which DD-241 rejected for
  contracts.
- **Rejected: a dotted token** such as `cargo:hasWeight.weightValue` or a `/` path. It
  breaks every reader that parses a token (`_token_uri`, `default_column_name`, the
  contract `termRef` pattern), and it hides the object property from the resolution that
  checks it.
- **Rejected: inferring single-valuedness** from the absence of a restriction, or from
  source data. The first reads silence as a claim, and the second makes the meaning depend
  on a sample.
- **Fan-out** (one row carrying N sibling columns that should become N child rows) is a
  different construct, with its own grain and identity. #811 keeps it out, and a
  hand-written dbt model remains the answer.
