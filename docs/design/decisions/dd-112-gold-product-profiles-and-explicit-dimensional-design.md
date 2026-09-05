# DD-112: Gold Product Profiles and Explicit Dimensional Design

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** Gold/dbt/Power BI projection, target registry, Gold extensions, skills and
scenario models
**Implementation:** `dbt/gold_specs.py`, `gold_shape.py`, `gold_materialize.py`, and
`gold_render.py`; authoritative registry with only `dimensional-powerbi-v1`

### Context

Gold is currently defined as a star-schema/Power BI layer and classifies a class with two
outgoing FKs as a fact. Gold should represent consumption-oriented data products, while
dimensional analytics is one explicit product profile.

### Decision

Every Gold product declares a named, versioned profile. The first and only profile in
this redesign is `dimensional-powerbi-v1`; future profiles require separate decisions
and implementations.

Within the dimensional profile, every materialized class explicitly declares `fact`,
`dimension`, or `bridge`. FK counts never control materialization. Zero-dimension facts
are valid. Facts declare grain and type: transaction, periodic snapshot, or accumulating
snapshot. They also declare correction, late-arrival, dimension-version binding, and
incremental policy. Dimensions state current-only, history-only, or dual exposure.

DD-001 inheritance applies only inside this dimensional profile. The actual generated
Silver registry is mandatory profile input; Gold cannot select unavailable columns.

### Rationale

Explicit profiles preserve dimensional guarantees while allowing other data-product
types later without redefining Gold.

### Consequences

- Remove automatic fact inference and implicit default dimensions.
- Amend DD-001 and DD-029.
- Generic Gold orchestration is separated from Power BI profile rendering.
- Wide tables, feature sets, API/search products, regulatory extracts, and visuals are
  out of scope.
