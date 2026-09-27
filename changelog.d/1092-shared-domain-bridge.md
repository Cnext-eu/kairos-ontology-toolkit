### Fixed
- **A shared domain that owns a bridge can be read by a product without the bridge's other
  endpoint.** A domain in `gold.shared_domains` contributed every table to each product that
  read it, including a bridge to a fact only the building product has, so the consuming
  product failed with `gold.bridge-endpoint-not-materialized`. The only way out was to stop
  sharing the domain and lose its conformed dimensions. In a product that reads the domain
  as shared, such a bridge is now left out and reported under `unresolved_bridges`, together
  with the measures that read it and the authored choices and practice exceptions that name
  it. The product that builds the domain still fails closed on a missing endpoint.
