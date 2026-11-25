# DD-262: Report parameters and calculation groups are authored in the hub

**Status:** Accepted
**Date:** 2026-11-25
**Affects:** `scaffold/kairos-ext.ttl` and its SHACL shapes (`Parameter`, `CalculationGroup`,
`CalculationItem`, `measureParameterDependency`, `measureFormatStringExpression`),
`core/projections/dbt/policy_bind.py`, `policy_normalize.py`, `gold_shape.py`,
`gold_render.py`, `gold_assert.py`, `bpa_profile.py` (profile version 3). Narrows the
"no calculated tables" construction of [DD-238](dd-238-kairos-owns-a-curated-bpa-profile-and-the-semantic-model-is-best-practice-by-design.md).
**Issue:** #1113

### Context

Report authors need a viewer to switch what a visual shows: a field parameter (which column or
measure), a selector (a label measures react to: YoY of the selected measure, share of total,
a dynamic title), a numeric range (Top N, a tolerance), and a calculation group that changes
how every measure is evaluated (a date basis: created, ETD, ETA). Each is a table of the
semantic model. A thin report live-connected to a deployed model cannot add one, so it has to
come from the hub, and the Gold vocabulary had no term for any of them. A client's legacy
estate builds the selector by hand -- a disconnected table plus a `SWITCH` measure, its
most-placed measure, with companion "Format ..." measures for the format string.

The emitter wrote no calculated tables at all, on the stated ground that Direct Lake does not
support them. Microsoft's Direct Lake overview says otherwise for these shapes: calculation
groups, what-if and field parameters, and calculated tables that reference no Direct Lake
column or table "are supported in all scenarios".

### Decision

A Gold extension authors report objects as first-class resources linked from the product, the
way it authors measures:

- **`kairos-ext:Parameter`** with `parameterKind` `field`, `selector` or `range`. Each is
  emitted as a disconnected calculated table, in the shape Power BI Desktop writes for it (read
  back through the TOM serializer): a field parameter with its `ParameterMetadata` extended
  property and hidden Fields/Order columns; a selector as `DATATABLE` with a hidden order
  column and a hidden `<name> Value` measure; a range as `GENERATESERIES` with its what-if
  metadata and a `<name> Value` measure. Ordered lists are Turtle collections, because
  repeated RDF values are a set.
- **`kairos-ext:CalculationGroup`** with `CalculationItem`s, emitted beside Time Intelligence
  with the same TOM shape and an authored precedence, unique in the model (Time Intelligence
  holds 0).
- A measure reading a parameter declares **`measureParameterDependency`**, exactly as it
  declares a column dependency; only then may its DAX name the parameter's objects. A measure
  with no other dependency is homed on the parameter's table. **`measureFormatStringExpression`**
  gives any measure a dynamic format string.

Everything a report object names fails closed, like `goldHideColumn`: field items resolve to
emitted columns or measures, dependencies to parameters of the product, item columns to
emitted Gold columns; ids and names are unique among the model's tables, and the range and
selector defaults lie within what they select from. A reference that may belong to another
domain of the product (a field item) is deferred on a single-domain compile and checked when
the product is shaped (#763).

The BPA profile narrows rather than drops the rule: `REDUCE_USAGE_OF_CALCULATED_TABLES` becomes
a render assertion. A calculated partition is allowed only on a table carrying
`Kairos_ParameterKind`, and each such table records the exception per shape in its
`BestPracticeAnalyzer_IgnoreRules` annotation -- with `ENSURE_TABLES_HAVE_RELATIONSHIPS`, since
a parameter is disconnected by design.

### Consequences

- A hub can deliver the switching a legacy model built by hand, governed and reviewed like a
  measure, and the post-deploy BPA run does not report it as debt.
- The construction "the emitter never writes calculated tables" is gone; what replaces it is an
  assertion over the emitted bytes, so a calculated table that is not a parameter still cannot
  ship.
- A parameter belongs to one product and every report on it sees it, so it is named for the
  product (`semantic-model.parameter-belongs-to-the-product`).
- A selector's `<name> Value` measure is text and hidden, so the render assertion that every
  measure has a format string now skips hidden measures -- as BPA's own rule does.
- Parameters are not listed in perspectives: `perspective` is authored on Gold tables only.
- **Rejected:** a calculation-group selector or a seeded Gold table as the Direct Lake fallback
  the issue first proposed -- unnecessary once the shapes are supported, and a seeded table
  would be Direct Lake data, which is exactly what a parameter avoids. Reusing
  `measureColumnDependency` on calculation items (its `rdfs:domain` is `Measure`) in favour of
  `calculationItemColumnDependency`. An unordered `parameterValue` read in sorted order:
  silently reordering a list the author wrote is worse than refusing it.
