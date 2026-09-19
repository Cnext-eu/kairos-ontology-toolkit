### Fixed
- **A cross-domain Gold bridge can now be authored (issue #763).** `gold_shape` documents
  its bridge-endpoint check as running "over the union, not per domain: a bridge may span
  two domains' tables" — but `compile <domain> --check` reaches that code through
  `_shape_dimensional`, which wraps a single domain in a 1-tuple. The union was a union of
  one, so `gold.bridge-endpoint-not-materialized` fired for every cross-domain bridge, and
  `emit-gold` failed too because it compiles each member domain first.

  Net effect: the one construct that gives Power BI a slicer across two facts — the reason
  `bridge` exists — could not be authored on a multi-domain product at all, and the error
  pointed at a binding that was correct.

  The check is now deferred on the single-domain path, where the other endpoint is out of
  scope by construction, and reported as `unresolved_bridges` on the compile plan, in the
  product JSON, and by `emit-gold`. At product level the union is real, so an endpoint
  genuinely outside it still fails closed — deferring does not become "never check".
