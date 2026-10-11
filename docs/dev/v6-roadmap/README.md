# V6 roadmap — working analyses

Working notes for scoping toolkit V6. Nothing here describes shipped behaviour or is a
committed plan. A topic that leads to a change gets its own decision record under
[../decisions/](../decisions/) when it is accepted, and its delivery phases move into
[../roadmap.md](../roadmap.md).

| # | Topic | Status | Recommendation in one line |
|---:|---|---|---|
| 01 | [Apache Ossie (Open Semantic Interchange)](01-apache-ossie-positioning.md) | Analysis | Treat Ossie as a Gold-layer projection and a demand-evidence import. It never becomes the model's authority. |
| 02 | [Open standards and vendor alignment](02-standards-and-vendor-alignment.md) | Analysis | OWL is the only open ontology standard. Publish the closure to Fabric IQ, and reach Databricks and dbt through Ossie and MetricFlow. |
| 03 | [A served ontology backend for agentic AI (MCP 2026-07-28)](03-agentic-ontology-backend-mcp.md) | Analysis | Serve released hub bundles (meaning, never data) over stateless Streamable HTTP MCP with Entra auth. One package (`kairos-ontology serve`) with embedded Oxigraph and MCP, SPARQL and IRI-dereferencing endpoints. Gated on a named consumer (DD-245 §5). |
