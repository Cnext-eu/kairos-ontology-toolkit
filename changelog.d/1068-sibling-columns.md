### Added
- **The deferred backlog puts sibling columns of bound fields first.** A deferred column
  often completes a field its table already binds: the unit of a bound weight
  (`JZ_WeightUQ` next to `JZ_Weight`), the currency of a bound amount, the description of
  a bound code, or a measure, amount or date next to a bound one. These are the cheapest next
  step into Silver, and until now a reviewer had to find them by hand among thousands of rows.
  Now each backlog column is related to the `fields:` a `source.relation` binding maps on the
  same table, and:
  - the backlog ranks by BI demand, then puts empty or constant columns last (from the
    DD-189 profile), then siblings first, then table size;
  - `alignment-report` opens its "Deferred backlog" section with "Sibling candidates": the
    column, the bound field it completes, the kind, and the closure property the alignment
    suggests;
  - `kairos-ontology next` says how many siblings there are and which tables hold them, in
    `review-deferred-columns`. JSON output moves to `schema_version: 10`;
  - `draft-gap-decisions --include-deferred` marks `siblings` on a re-listed name, and
    `sibling_members` on a family.

  A sibling is a suggestion for the binding author, never a decision. The sheet does not
  propose `bound` for it, because only a binding that maps the column can state that. The
  rules are narrow, because name matching was measured at 62% precision on real data. A
  unit, currency or description must pair by exact stem. A currency with no stem pairs only
  when the table binds exactly one amount. The profile vetoes a shape mismatch, so a
  `code-like` "amount" such as `JR_A9_CostVATClass` is not paired. A date next to a bound
  date is a "sibling date", not a claimed temporal-quartet member.
