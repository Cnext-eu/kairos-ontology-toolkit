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
| 04 | [DDD, bounded contexts and data product standards](04-ddd-and-data-product-standards.md) | Analysis | No DDD standard exists; keep the Kairos DDD vocabulary. Export the Silver contract to Bitol ODCS v3.2 and bounded contexts to ODPS v1.1, the standards the tool ecosystem is adopting. |
| 05 | [Ontology-governed graph memory (FalkorDB + Graphiti)](05-graph-memory-falkordb-graphiti.md) | Analysis | We have about half the concepts. Add a closure-based `graphiti` projector (Pydantic types and `edge_type_map`), sensitivity annotations, a `kairos-memory` reference model and a runtime seed loader. FalkorDB's SSPL keeps it out of the toolkit's dependencies. |
| 06 | [The Power BI authoring boundary](06-power-bi-authoring-boundary.md) | Analysis | Reports are already authored (DD-236/253). V6: declarative field and numeric parameters, calculation groups and UDFs; generated dynamic RLS; a report reference check; a live GUID-stability test for embedding. Ossie doesn't cover any of it. |
