# 05 — Ontology-governed graph memory (FalkorDB + Graphiti)

Status: analysis, 2026-10-11. No decision record yet. Builds on
[02](02-standards-and-vendor-alignment.md) and [03](03-agentic-ontology-backend-mcp.md).

## Assumption and question

V6 assumes we will build two runtime knowledge stores with **Graphiti** (the temporal
knowledge-graph library from Zep) on **FalkorDB**:

- **Personal memory store**, one per user: preferences, commitments, decisions, people and
  projects that an assistant remembers across sessions.
- **Client fact store**, one per client: facts about the client's business, extracted from
  meetings, mails, documents and agent conversations, and typed by that client's hub
  ontology.

**Question:** does the toolkit already have the concepts needed (projectors, vocabulary,
identity, temporal, privacy), and what is missing?

**Short answer:** about half. The *schema source* is strong: the OWL closure, the semantic
index, labels, comments and synonyms, domain and range, identity, MDM match rules, temporal
vocabulary, and a projector registry to plug into. Six things are missing:

1. a Graphiti or Pydantic projector;
2. instance seeding (ABox);
3. a privacy and sensitivity vocabulary;
4. a tenancy model;
5. a memory ontology for the personal store;
6. a provenance vocabulary for extracted facts.

## Graphiti and FalkorDB in brief

| | Facts that matter for us |
|---|---|
| **Graphiti** (Apache-2.0, `graphiti-core`, v3 docs) | Ingests **episodes** (text, messages, JSON). An LLM extracts entities and edges ("facts"). Facts are **bi-temporal**: `valid_at` and `invalid_at` for business time, `created_at` and `expired_at` for system time. A contradiction invalidates an edge rather than deleting it. Hybrid search combines vectors, BM25 and graph distance. Back ends: Neo4j, FalkorDB, Neptune. LLMs include Azure OpenAI and Anthropic. `group_id` namespaces the data. It ships an MCP server. |
| **Graphiti custom types** | `entity_types` and `edge_types` are **Pydantic `BaseModel` classes**. The docstring describes the type, and each attribute is an `Optional` field with a description. `edge_type_map` maps a pair `(SourceType, TargetType)` to a list of allowed edge types, with `("Entity","Entity")` as the wildcard; an unmapped pair keeps the free-text predicate. `excluded_entity_types` suppresses extraction of a type. **Protected attribute names:** `uuid`, `name`, `group_id`, `labels`, `created_at`, `summary`, `attributes`, `name_embedding`. |
| **FalkorDB** | A Redis-based graph database (OpenCypher, GraphBLAS) with vector and full-text indexes. **Multi-graph by design:** one instance serves thousands of isolated graphs, so one graph per tenant or user is natural. It has its own GraphRAG SDK (1.0, Apr 2026) and an MCP server. **Licence: SSPLv1**, which is not OSI-approved. See the risks section. |

## The core idea: the ontology types the memory

```
 Kairos hub (design time, Git)                Runtime (per tenant)
 ─────────────────────────────                ─────────────────────────────────────
 OWL closure + semantic index ──projector──►  Graphiti entity_types / edge_types /
   labels, comments, altLabels                edge_type_map (generated Python module)
   domain/range, hierarchy                          │
   identity, reference data                         ▼
   sensitivity (new)               episodes ──► Graphiti extraction (LLM) ──► FalkorDB
                                                    ▲                        graph per
 Reference data + MDM golden ──seed loader──────────┘                        client/user
 records (Silver)                  (new; anchors canonical nodes)
```

Without our types, Graphiti invents labels and predicates per episode, and the graph drifts:
`Customer`, `Client`, `Account` and `Shipper` all end up meaning the same thing. With our
types, every extracted fact lands on a governed class and an allowed relationship, carrying
the client's ubiquitous language. This is the same position as topics 02 and 03, applied to
memory. **Kairos authors the meaning, and the runtime store is one more surface it compiles
into.**

## Gap analysis

| # | Concept needed | Toolkit today | Gap | Size |
|---:|---|---|---|---|
| 1 | **Schema projection** to Pydantic entity and edge types plus `edge_type_map` | Projector registry (`core/projector.py:235-263`, `project --target`). `a2ui` emits JSON Schema for datatype properties only, with no edges and an empty `required` list. The live `neo4j` path emits uniqueness constraints only: no relationship types and no properties. **No Pydantic generation anywhere.** | New `graphiti` target | **M** |
| 2 | **Closure as projector input** (DD-243) | Projectors read the single domain graph, filtered to the domain namespace (`projector.py:2073-2110`). Only `prompt` uses `semantic_index`. | The `graphiti` target must use the closure. Graphiti has no inheritance, so inherited properties are flattened into each type. | S, within #1 |
| 3 | **Edge typing** from `rdfs:domain` and `rdfs:range` | Available in the closure and index | Map each object property to an edge type keyed by its domain and range pair. A superclass pair expands to its subclass pairs, or uses the parent pair. Cardinality (`silverForeignKeyCardinality`) can't be expressed in Graphiti, so it goes into the docstring as guidance only. | S, within #1 |
| 4 | **Naming policy** | Labels are local names (neo4j). `sales:Customer` and `crm:Customer` would collide. | Deterministic type names (prefix plus local name when ambiguous), with the class IRI kept as a type attribute and in the docstring. **Lint for protected names**: an ontology property called `name` or `summary` collides with Graphiti's. | S |
| 5 | **Instance seeding (ABox)** | `owl:NamedIndividual` is used nowhere. `kairos-ext:isReferenceData` marks code-list classes. SKOS concept schemes exist only for the glossary and for azure-search synonyms. **No graph-DB writer exists.** | A seed loader that writes reference data (countries, incoterms, statuses) and **MDM golden records** as canonical nodes, so that extraction resolves "Acme" to the governed `Customer` node with its Silver key, instead of creating a duplicate. | **M–L** (runtime) |
| 6 | **Entity resolution** | `IdentitySpec`, `naturalKey`, `entityInstanceIriPolicy`, and MDM `MatchAttribute`, `MatchRule` and `SurvivorshipRule` (`mdm/model.py`) | Graphiti deduplicates with an LLM. Project the identifiers (`naturalKey` and MDM identifier attributes) as **typed key fields** on the Pydantic models, and resolve on them in the seed loader. Whether Graphiti exposes a deterministic dedupe hook needs checking. | M |
| 7 | **Temporal semantics** | Rich at table level: `scdType`, `scd2TimeBasis`, and `source_updated_at`, `business_effective_at` and `ingested_at` in `IncrementalPolicy`, plus `core/compiler/temporal.py` | The concepts map cleanly (`business_effective_at` ↔ `valid_at`, `ingested_at` ↔ `created_at`). What is missing is an ontology-level flag for **which relationships are time-varying facts and which are static**, so the docstring can tell the extractor to date them. | S |
| 8 | **Provenance of facts** | Run provenance, decision, evidence and feedback records (`core/decision_records.py`, etc.). No W3C PROV. | Graphiti episodes already carry provenance. Add a small episode-source taxonomy (meeting, mail, document, agent chat, system) and a policy for which sources may assert which classes. | S |
| 9 | **Privacy and sensitivity** | **No PII or sensitivity annotation in `kairos-ext.ttl`.** Privacy is design-time only (`source_privacy.py` sample sanitising, log redaction). Gold has RLS-style `securityPolicy`. | **Must-have.** A personal memory store *is* personal data. Add `kairos-ext:sensitivity` (public, internal, confidential, personal, special-category) on classes and properties. The projector drives `excluded_entity_types` and field omission from it. Add retention and erasure policy per class (GDPR art. 17). | **M**, a gate |
| 10 | **Tenancy and isolation** | None. Only heuristics that treat tenant columns as non-key. | A design decision more than code: **one FalkorDB graph per client and one per user**, with `group_id` equal to the graph, mapped to Entra identity. Never mix personal and client facts in one graph. Cross-links go by reference only (user X attended meeting Y in client graph Z). | S (design) |
| 11 | **Ontology for the personal store** | None. Hub ontologies describe the client's business, not the assistant's user. | A toolkit-shipped **reference model** (for example `kairos-memory`: Person, Organisation, Project, Commitment, Decision, Preference, Meeting, Topic), authored and released like any reference model, so the same projector serves both stores. It aligns with `decision_records` and the DDD layer (`Decision` and ownership). | M |
| 12 | **Validation of extracted facts** | SHACL shapes and `validate_content()` for the ontology. Pydantic validation in Graphiti covers datatypes only. | Optional later: export a slice of the client graph as RDF and run the hub's SHACL shapes to report conformance drift (an extraction-quality metric). | M, later |
| 13 | **Serving to agents** | Local MCP (DD-245). A hosted read-only backend is proposed in topic 03. | Keep **two MCP servers**: Kairos serves *meaning* (immutable releases, no PII) and Graphiti or FalkorDB serves *facts* (live, mutable, PII). Different lifecycle and different security. The agent composes the two. | S (design) |
| 14 | **Schema evolution** | Release discipline, immutable pins (DD-206) | A release regenerates the types module. Graphiti keeps old attributes on existing nodes. Renamed classes need a mapping, which the stable IRI attribute from #4 provides. | S |

## Where the code lives

- **Toolkit (design time, Apache-2.0, no FalkorDB dependency):**
  - the `graphiti` projector, emitting a generated Python module with Pydantic types,
    `EDGE_TYPE_MAP`, `EXCLUDED` and a manifest with release and closure hash;
  - the `sensitivity` and temporal-fact annotations in `kairos-ext.ttl`;
  - the protected-name and naming lints;
  - the `kairos-memory` reference model.

  The projector targets **Graphiti's abstraction, not FalkorDB**, so Neo4j or Neptune remain
  possible.
- **Runtime service (not the toolkit):** the ingestion service (Graphiti plus FalkorDB), the
  seed loader and the memory MCP server. These go in a separate repository or the
  dataplatform scaffold, consuming the generated types module and the topic 03 release
  bundle. The toolkit stays a design-time compiler, consistent with "meaning, never data"
  (topic 03).

## Risks

- **FalkorDB is SSPLv1.** The toolkit must never bundle or depend on the server. AGENTS.md
  requires Apache-compatible dependencies. Check the licence of the Python client
  (`falkordb-py`) before adding even an optional extra. Running FalkorDB internally is fine,
  but **offering a hosted memory service to clients may trigger SSPL §13**. That needs legal
  review, or FalkorDB Cloud, or a commercial licence. Keeping the projector back-end-neutral
  preserves the exit to Neo4j or Neptune.
- **LLM extraction is probabilistic.** Types constrain but don't guarantee. Measure
  conformance (gap #12) before trusting the client fact store for decisions. This repeats our
  `anchor-tables` lesson: pin what humans confirmed.
- **Personal data.** The personal store needs consent, retention, erasure and per-user
  isolation before the first pilot. Gap #9 is a gate, not a follow-up.
- **Duplicated truth.** A client fact store holding "Acme's credit limit is X" competes with
  Silver. Policy: **the memory holds what was said and decided. Silver holds what the systems
  record.** Seeded golden records link the two but do not get copied as mutable facts.

## Proposed phases

| Phase | Deliverable | Acceptance |
|---|---|---|
| P0 | Spike in a scratchpad: hand-write Graphiti types from one hub's closure, run local FalkorDB in Docker, ingest about 20 synthetic episodes, compare typed against untyped extraction | Measured duplicate and drift rate, typed against untyped. Settle whether Graphiti has a dedupe hook. Legal answer on SSPL. |
| P1 | `graphiti` projector: closure-based, deterministic, with namespaced names, a protected-name lint and a manifest | Byte-stable output. Golden tests. An ambiguous local name and a protected name are both handled and diagnosed. |
| P2 | `kairos-ext:sensitivity` and temporal-fact annotations. Projector honours them (exclusion, omission, docstring guidance). | A personal-category class is excluded by default. Test for the omission. |
| P3 | `kairos-memory` reference model, released like other reference models | It projects cleanly. A personal store pilot runs on it. |
| P4 | Seed loader spec (runtime repository): reference data and MDM golden records as anchor nodes with Silver keys | A re-run is idempotent. Extraction links to seeded nodes instead of duplicating them. |
| P5 | Conformance report: export from the client graph, then SHACL check against the hub | Conformance rate per class, reported in insights |

## Open questions

1. Is there a Graphiti hook for deterministic entity resolution, or only the LLM dedupe step?
2. Does Graphiti accept Pydantic inheritance for entity types, so we could keep the class
   hierarchy instead of flattening it?
3. What licence does `falkordb-py` have? Does Cnext's intended hosting model fall under SSPL
   §13?
4. Is the personal store per consultant (Cnext-internal) or per client end-user? This decides
   the data controller and the consent model.
5. Should client facts that a steward confirms flow *back* into the hub (as evidence for
   domain design or the business validation document), and through which review gate?

## Sources

- [Graphiti overview (Zep docs)](https://help.getzep.com/graphiti/getting-started/overview)
- [Graphiti custom entity and edge types](https://help.getzep.com/graphiti/core-concepts/custom-entity-and-edge-types)
- [graphiti-core on PyPI](https://pypi.org/project/graphiti-core)
- [Graphiti + FalkorDB integration](https://www.falkordb.com/blog/graphiti-falkordb-multi-agent-performance/)
- [FalkorDB on GitHub](https://github.com/falkordb/falkordb), [FalkorDB docs](https://docs.falkordb.com/)
- [FalkorDB architecture and licence overview (Atlan)](https://atlan.com/know/ai-agent/knowledge-graph/falkordb-graph-database-for-graphrag/)
- [FalkorDB GraphRAG SDK](https://github.com/FalkorDB/GraphRAG-SDK/)
