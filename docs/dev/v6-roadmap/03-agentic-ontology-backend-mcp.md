# 03 — A served ontology backend for agentic AI (MCP 2026-07-28)

Status: analysis, 2026-10-11. No decision record yet. If accepted, this amends
[DD-245](../decisions/dd-245-ontology-semantics-are-served-through-one-interface-and-a-raw-read-corrects-itself.md) §5.
Builds on [01](01-apache-ossie-positioning.md) and [02](02-standards-and-vendor-alignment.md).

## Question

Should V6 provide a real backend that lets agents outside a hub repository query the
ontology over MCP? Examples are a Fabric data agent, Copilot Studio, Databricks Genie, a
client chatbot, a dataplatform pipeline agent, or another team. If so, what does it serve,
on which store, and with which protocol features?

## Where we are

DD-245 built a **local, stdio, per-hub** MCP server (`kairos-ontology mcp serve`, in
`cli/mcp_server.py`). It runs on the official `mcp` SDK (`>=2.2.0,<3.0.0`) and is registered
in `.mcp.json` and `.vscode/mcp.json`.

- **Tools.** It exposes eight tools: `show_class_inventory`, `list_class_properties`,
  `explain_term`, `find_term` (added by DD-248), `resolve_ontology`, `compile_check`,
  `compile_explain` and `logs_show`. There are no resources and no prompts.
- **Behaviour.** It is stateless: every call reloads the closure through `load_ontology`,
  with in-process caches. It is read-only, has no authentication, and serves the **working
  tree** of the one hub it runs in.
- **Purpose.** It exists so that the *authoring* agent in the IDE reads the closure instead of
  the raw `.ttl` file.
- **No SPARQL.** No query surface exists. rdflib SPARQL is used only inside the toolkit's own
  code: the validator, the projector, and the `neo4j`, `azure_search` and `a2ui` projectors.

DD-245 §5 deliberately stopped there: *"The tool signatures are the interface a hosted
service would serve. That step waits for a consumer outside the repository."* **This topic
argues that V6 has that consumer.**

## Why now: the consumers exist

| Consumer | What it asks | Today |
|---|---|---|
| Runtime analytics agents (Fabric data agent, Genie, Copilot) | "What is an *active shipment*? Which table and column hold it? Which governed measure answers *revenue*?" | Each one guesses from table names, or from Fabric IQ if the client imported it by hand |
| Dataplatform CI and pipeline agents | "Which concept does this Silver column carry? Did the contract change?" | They clone the hub and run the CLI |
| Business users and analysts through a chat surface | Glossary questions, context map, "who owns *Customer*?" | They read the business validation document (DD-254) |
| Other hubs and reference models | Cross-domain alignment and reuse | Manual |
| Vendor context layers (Fabric IQ, Unity Catalog Glossary, Ossie) | A governed source to sync from | Topic 02, A1 to A3 |

Topic 02's position ("Kairos is the authored source the vendors' context layers lack") is
only credible if an agent can reach that source at runtime, not just at design time.

## What MCP 2026-07-28 changes

The current specification (2026-07-28, the largest revision since launch, sometimes called
"MCP 2.0") reshapes MCP around exactly this deployment:

| Spec change | Consequence for a Kairos backend |
|---|---|
| **Stateless core.** No `initialize` handshake and no `Mcp-Session-Id`; version and capabilities travel in each request's `_meta`; there is a new `server/discover`. | Our server is already stateless. A hosted instance can sit behind a load balancer or run serverless (Azure Container Apps or Functions) with no sticky sessions. |
| **Cacheable list and read results** (`ttlMs`, `cacheScope`); deterministic `tools/list` order | A released ontology is immutable, so its answers can carry long TTLs keyed to the release. This fits DD-206's immutable pins and our byte-determinism discipline. |
| **Multi Round-Trip Requests** (`input_required`), replacing server-initiated elicitation | Ambiguity resolution: "`Customer` matches `sales:Customer` and `crm:Party`. Which one?" The server asks once and the client retries with the answer. No open stream is needed. |
| **JSON Schema 2020-12** for `inputSchema` and `outputSchema`; `structuredContent` can be any JSON | Our payloads are already typed dataclasses. Publish output schemas so that agents and gateways can validate them. |
| **OpenTelemetry trace context in `_meta`** (`traceparent`) | Joins the DD-242 run spans, giving one trace from the agent's question to our closure lookup. |
| **Header routing** (`Mcp-Method`, `Mcp-Name`) | API gateways (Azure API Management) can authorise and rate-limit per tool without parsing the body. |
| **Authorization hardening.** Client ID Metadata Documents replace Dynamic Client Registration; RFC 9207 `iss` check; **Enterprise Managed Authorization** extension. | Entra ID sign-in for client tenants and per-hub audiences are the mechanisms our Microsoft-first clients expect. |
| **Extensions:** Tasks, **MCP Apps**, Enterprise Managed Authorization | Optional. MCP Apps could render a class diagram or context map inline. Tasks are not needed for a read-only server. |
| **Deprecated:** Roots, Sampling, Logging, HTTP+SSE | Don't adopt them. Use Streamable HTTP and log through OTel. |

**Open check:** does `mcp` 2.2.0 (our pin) implement 2026-07-28 on the server side? The
release notes say all Tier 1 SDKs, Python included, support it, but they don't give a version
number. The answer decides whether the backend needs an SDK bump first.

## Design principles

1. **Serve releases, not working trees.** The hosted backend answers from a **released hub
   bundle** identified by commit SHA and tag (DD-206). The authoring agent keeps the local
   stdio server over the working tree. Two deployments share one tool interface, as DD-245 §5
   intended.
2. **Serve meaning, never data.** The backend answers what things mean, where they live, and
   which governed calculation answers a question. Running the query stays with the vendor
   engine (Fabric, Databricks, dbt Semantic Layer). This keeps the backend free of PII,
   cheap, and outside the data-access security path. **Source evidence (samples, profiling)
   is never in a bundle.**
3. **The ontology stays authoritative in Git.** The store is a read replica built from the
   release. Nothing writes back through the server. Proposals go through a pull request.
4. **Same core functions as the CLI.** The tools stay thin wrappers over `load_ontology` and
   `semantic_index`, so the CLI, local MCP and hosted MCP cannot drift apart.
5. **Deterministic answers.** The same release and the same call give the same bytes. That
   makes results cacheable and testable.

## What the backend serves

The release bundle is a new emit artefact produced by the hub release workflow:

| Bundle part | Content | Source in the toolkit |
|---|---|---|
| `closure.ttl` | The flattened `owl:imports` closure, one graph per release | `load_ontology` |
| `semantic-index.json` | The precomputed index (ancestors, inherited properties, provenance, coverage) for each profile | `semantic_index` |
| `compile-plan.json` | Concept → Silver model and column, grain, identity, relationships | `compile --explain` |
| `gold.json` | Gold products, measures, display names, calendars | `DimensionalGoldSpec` |
| `architecture.json` | Bounded contexts, context map, ubiquitous language, rules (DD-229..232) | DDD layer |
| `manifest.json` | Hub, commit SHA, toolkit version, closure hash, profile coverage | release metadata |

The same bundle feeds the topic 02 projections: Fabric IQ (A1), Ossie (A2) and MetricFlow
(A3). **One release artefact has many consumers.**

### Tool surface (v1)

The DD-245 tools stay. Each takes an optional `release` argument (default: latest) and drops
`domain` where the bundle makes it unambiguous. The authoring-only tools (`compile_check`,
`logs_show`) are **not** served remotely.

| Tool | New? | Purpose |
|---|---|---|
| `search_terms(query, lang?, kind?)` | new | Search over labels, `skos:altLabel` and comments, in several languages. This is the entry point for an agent working from natural language. |
| `explain_term`, `list_class_properties`, `show_class_inventory`, `resolve_ontology`, `find_term` | existing | As in DD-245 and DD-248 |
| `locate(term)` | new | Concept or property → Silver and Gold table and column, with the binding that produced it and its grain. This is the key runtime question. |
| `list_measures(concept?)`, `explain_measure(id)` | new | Governed Gold measures with DAX or SQL text, dependencies and the concepts they cover |
| `context_map()`, `explain_context(name)` | new | DDD layer: owners, relationships, ubiquitous language |
| `sparql(query)` | new, gated | Read-only `SELECT`, `ASK` or `CONSTRUCT` over the closure graph. No `SERVICE`, no updates. Timeout and row cap. Enabled per deployment. |

Resources: `kairos://<hub>/<release>/term/<curie>` as a resource template, so that clients
able to attach context can pin a term without a tool call.

## Store options

| Option | Fit | Notes |
|---|---|---|
| **In-memory rdflib + precomputed index (today's engine)** | Good for tests and the local stdio server | Zero new dependencies. Too slow for SPARQL under concurrent load. **The test backend and local fallback.** |
| **Oxigraph (`pyoxigraph`)**, embedded | Good fit: a real triple store inside the server process | Rust SPARQL 1.1 store with Python bindings, dual MIT/Apache-2.0 licensed, with named graphs. It runs in memory or on disk (RocksDB), in-process, with no separate server. **The default store of the server package.** See "Package architecture" below. |
| **Apache Jena Fuseki**, as a separate server | Good for a client that wants a standing SPARQL endpoint, OWL reasoning or SHACL at query time | A Java service to operate. Expose it as an *alternative backend* behind the same tools, not as the default. |
| **Fabric IQ** as the store for Microsoft-native agents | Good inside Fabric | Fabric's agents read Fabric IQ, not our MCP. Feed it from the bundle (topic 02, A1). Our backend still serves what Fabric IQ drops: restrictions, SHACL, multiple parents, provenance and DDD. |
| Property graph (Neo4j; a `neo4j` projector already exists) | Poor as the authority | Loses OWL semantics. Keep it as a projection for graph exploration only. |
| Vector index (an `azure_search` projector already exists) | Complements `search_terms` | Use it for semantic recall over labels and comments. The answers still come from the closure. |

## Package architecture: one server, triple store embedded

**One deployable, `kairos-ontology serve`**, combines the triple store and MCP. The store is
**embedded** (Oxigraph, in-process) rather than a separate TTL or SPARQL server beside the MCP
process. The reasons:

- **One process, one image, one health check.** There is no JVM (Fuseki) to operate and no
  network hop between MCP and the store. That suits a stateless, scale-out MCP deployment:
  every replica loads the same immutable bundle.
- **Consistency by construction.** The store and the semantic index load from the same
  bundle in the same process. They cannot drift onto different releases.
- **Still a real TTL and SPARQL server to the outside.** The package exposes the standard
  SPARQL 1.1 Protocol endpoint and dereferenceable IRIs, so RDF tools (Protégé, TopBraid,
  GraphDB federation, Fabric IQ import) see a normal triple store.

```
                    kairos-ontology serve  (one container / one process)
 ┌───────────────────────────────────────────────────────────────────────────┐
 │  Faces (one ASGI app, Starlette — already a dependency of the mcp SDK)    │
 │   /mcp            MCP 2026-07-28, Streamable HTTP, stateless              │
 │   /sparql         SPARQL 1.1 Protocol, read-only, timeout + row cap       │
 │   /id/{path}      IRI dereferencing, conneg: text/turtle, JSON-LD, HTML   │
 │   /bundles        manifest list: hub, release SHA, closure hash           │
 │   /healthz        liveness + loaded-bundle identity                       │
 ├───────────────────────────────────────────────────────────────────────────┤
 │  Cross-cutting: Entra JWT auth · per-hub audience · OTel (traceparent)    │
 │                 ETag = closure hash · MCP ttlMs/cacheScope                │
 ├───────────────────────────────────────────────────────────────────────────┤
 │  Ontology query service (one implementation)                              │
 │   explain_term · list_class_properties · show_class_inventory ·           │
 │   find_term · search_terms · locate · list_measures · context_map         │
 │   — the same functions the CLI and the local stdio server call            │
 ├───────────────────────────────────────────────────────────────────────────┤
 │  Store port (interface)                                                   │
 │   OxigraphStore (default, embedded) │ RdflibStore (tests, stdio)          │
 │   RemoteSparqlStore (optional: Fuseki, GraphDB, an existing client store) │
 ├───────────────────────────────────────────────────────────────────────────┤
 │  Bundle loader: release bundle (per SHA) → named graphs + JSON indexes    │
 └───────────────────────────────────────────────────────────────────────────┘
```

### Named-graph layout in the store

| Graph | Content | Why |
|---|---|---|
| `…/<release>/asserted/<module>` | One graph per closure module (domain, imported reference models) | Provenance: SPARQL can say where a triple came from, as `resolve_ontology` does today. |
| `…/<release>/entailed/<profile>` | The materialised `kairos-design` (or `rdfs`) entailments, such as inherited domains and subclass closure | **SPARQL answers must equal `explain_term` answers.** Materialising at bundle time guarantees that, instead of hoping the query writer reasons correctly. |
| `…/<release>/binding` | Concept → Silver/Gold model and column, in the `kairos-ext` vocabulary | Makes `locate` answerable by SPARQL too, not only by the JSON plan |
| `…/<release>/manifest` | Release metadata (hub, SHA, toolkit version, coverage) | Lets every answer cite its release |

The default graph is the union of the latest release's graphs, so simple queries just work.
To pin a release, select its graphs explicitly.

### Where the code lives

- **Same repository, new subpackage:** `kairos_ontology.server`, which imports `core` and
  never `mdm`, the same rule as today. It ships as an optional extra **`[server]`**
  (`pyoxigraph` plus the `mcp` HTTP stack). Hubs that don't serve pay nothing.
- `cli/mcp_server.py` (stdio) and the HTTP server call **the same query-service functions**.
  The stdio server keeps working on the working tree through `RdflibStore`. The HTTP server
  serves bundles through `OxigraphStore`. One test suite runs both against one fixture
  bundle and asserts identical payloads.
- A **container image** built by the toolkit's release CI (`ghcr.io/…/kairos-ontology-server:<version>`)
  so the dataplatform scaffold deploys an image rather than a Python environment.
- **Not a separate repository yet.** Splitting off makes sense only if the server gets its own
  release cadence or a non-Python consumer.

### What we deliberately don't build

- **No write API, and no SPARQL Update.** Changes go through hub pull requests.
- **No reasoning at query time.** Entailments are materialised at bundle time, which keeps
  answers deterministic and cheap.
- **No data queries.** The server holds meaning and mappings, never warehouse rows.
- **No in-process Fuseki or Jena.** Jena remains available through `RemoteSparqlStore` for a
  client that already runs one.

## Deployment shape

```
 hub release workflow ──► release bundle (immutable, per SHA)
                              │
            ┌─────────────────┼──────────────────────┐
            ▼                 ▼                      ▼
  Kairos MCP backend     Fabric IQ ontology     Ossie / MetricFlow
  (Streamable HTTP,      (topic 02 A1)          (topic 02 A2/A3)
   stateless, Entra)
            ▲
  agents: Copilot Studio, Foundry agents, Claude, Genie, dataplatform CI
```

- **Hosting.** Hosting goes in the dataplatform scaffold, next to the Fabric deploy
  workflows (DD-239): a container image, an Azure Container Apps template, and a GitHub
  Environment holding the bundle location. It is one deployment per client tenant. Hubs
  are client-confidential, so there is no shared multi-tenant instance by default.
- **Auth.** Entra ID through MCP's OAuth (Client ID Metadata Documents), with one audience
  per hub. The Enterprise Managed Authorization extension applies where the client's IdP
  supports it.
- **Observability.** The server continues the incoming `traceparent` into DD-242 spans and
  exports them through the existing opt-in OTel bridge.

## Proposed phases

| Phase | Deliverable | Acceptance |
|---|---|---|
| P0 | Name the first real consumer and client. Decide on the SDK bump. Draft the decision record amending DD-245 §5. | A named consumer exists. Without one, stop here, as DD-245 requires. |
| P1 | **Release bundle** emitted by the hub release workflow: deterministic, with a manifest and no source evidence | Same commit gives the same bundle bytes. A test proves no evidence or sample content is in it. |
| P2 | `kairos_ontology.server` with the `[server]` extra: bundle loader, store port, `OxigraphStore` with named graphs and materialised entailments, and `kairos-ontology serve --bundle <path>` exposing `/mcp` (Streamable HTTP, 2026-07-28), `/sparql` (read-only) and `/healthz` | CLI, stdio MCP and HTTP MCP give identical payloads for one fixture bundle. A SPARQL query for inherited properties equals `list_class_properties`. Update queries and `SERVICE` are rejected. |
| P3 | New tools: `search_terms`, `locate`, `list_measures`, `explain_measure`, `context_map`. The `/id/` dereferencing face. Resource templates. MRTR disambiguation. | Golden tests per tool. An ambiguous term returns `input_required`. Turtle and JSON-LD content negotiation works. |
| P4 | Container image in the toolkit release CI. `RemoteSparqlStore` adapter (Fuseki) behind the same port. | The image starts from a bundle URL with no Python environment. The adapter passes the same store-port test suite. |
| P5 | Dataplatform scaffold: container, Container Apps template, Entra auth, OTel | An end-to-end check with one agent client (Copilot Studio or Foundry) against a real hub release |
| Later | Multi-release comparison tools (paired with roadmap Phase 5, Gate B); an MCP Apps diagram view; an optional Fuseki backend; publishing to the MCP registry | — |

## Risks

- **No consumer, no backend.** DD-245's rule still holds. P0 is a real gate, not a
  formality.
- **Leaking confidential models.** Mitigations: per-tenant deployment, per-hub audience, a
  bundle that excludes evidence by construction, and a test for that exclusion.
- **Fabric IQ overlap.** For Fabric-only agents, Fabric IQ may be enough. Position our
  backend as the vendor-neutral, lossless source that also feeds Fabric IQ, not a
  competitor to it.
- **Spec churn.** The 2026-07-28 revision broke stateful servers. Our server has no session
  state, so it is exposed only to SDK API changes. Pin the SDK major version.
- **`sparql` as an attack surface.** Gate it, cap it, keep it read-only, and default it off.

## Open questions

1. Does `mcp` 2.2.0 serve protocol 2026-07-28, or is a newer 2.x or 3.x release needed?
2. Who hosts the backend: Cnext per client, or the client in its own tenant? This decides
   which scaffold owns the deployment template, the dataplatform's or a new one.
3. Can Copilot Studio and Foundry agents call a remote MCP server with Entra auth today, and
   which spec revision do they speak?
4. Should `locate` answer at the Silver level only, or also return Gold and Power BI
   semantic-model objects (table, column, measure) so that a Power BI Copilot can act on
   them?
5. Should a bundle carry one domain or the whole hub, and how do cross-hub references
   resolve?

## Sources

- [MCP 2026-07-28 key changes](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- [MCP blog: the 2026-07-28 specification](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [WorkOS: MCP 2026 spec and agent authentication](https://workos.com/blog/mcp-2026-spec-agent-authentication)
- [Google Developers: MCP stateless updates](https://developers.googleblog.com/scaling-ai-agent-infrastructure-with-the-mcp-stateless-updates/)
- [DD-245](../decisions/dd-245-ontology-semantics-are-served-through-one-interface-and-a-raw-read-corrects-itself.md),
  [DD-248](../decisions/dd-248-a-hub-local-property-is-declared-only-after-a-closure-lookup-finds-no-candidate.md)
- [Apache Jena Fuseki](https://jena.apache.org/documentation/fuseki2/)
