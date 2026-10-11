# 04 — DDD, bounded contexts and data product standards

Status: analysis, 2026-10-11. No decision record yet. Builds on
[02 — Open standards and vendor alignment](02-standards-and-vendor-alignment.md), alignment A4.

## Question

Is there an emerging standard for domain-driven design: bounded contexts, context maps and the
ubiquitous language? Which technical standards for data products and data contracts are actually
being adopted? Where should the Kairos DDD layer (DD-229..232) and the Silver contract (DD-213)
align?

## 1. DDD and bounded contexts: no standard, but a new reason to care

### No machine-readable standard exists

No W3C, ISO, OMG or Linux Foundation specification covers bounded contexts or context maps, and
none is forming. What exists is tooling, each tool with its own format:

| Candidate | What it is | State (Oct 2026) |
|---|---|---|
| **Context Mapper (CML)** | Academic textual DSL for strategic DDD (context maps, relationship patterns) and tactical DDD (aggregates, entities), with diagram and service-decomposition generators | Last release v6.12.0, **August 2024**. Effectively stalled. |
| **DDD Context Mapper** (Florian Krämer) | Single-file browser editor for context maps; plain JSON format | New, April 2026; small project |
| **ContextFlow** | Visual context mapper (value stream, distillation, strategic views) | Small open-source project |
| **DDD Crew canvases** (Bounded Context Canvas and others) | Templates for workshops | Not a machine-readable format |

The Kairos DDD vocabulary (`kairos-ddd.ttl`: `BoundedContext`, context relationships,
`SubdomainType`, `invariant`) is RDF with SHACL validation (DD-229). It is already more formal
than any of these, and linked to the ontology IRIs, which none of them are.

### What is changing is the reason DDD matters

The 2026 practitioner writing agrees on one shift: DDD is back because of AI agents.

- The **bounded context** is treated as the semantic boundary, and so the prompt boundary,
  within which a term has exactly one meaning.
- The **ubiquitous language** becomes operational. Humans patch over a fuzzy term from context;
  an agent turns it into repeatable wrong actions.
- **Aggregates** map naturally onto agent tool surfaces: one entry point, clear inputs, and
  invariants the aggregate enforces itself.

This is the reasoning behind the Kairos DDD layer and the "context engineer" persona
(DD-229..232). The market argument for that layer is getting stronger even though no standard is
forming.

### In data, the bounded context shrinks to a "domain" label

Data mesh has moved from hype to practice. In the data tools, though, the bounded context is
reduced to an ownership label:

| Where | What a "domain" is |
|---|---|
| Microsoft Purview Unified Catalog | A *governance domain* that owns data products, terms, OKRs and critical data elements |
| Bitol ODCS / ODPS | A `domain` string on a contract or product |
| Databricks Labs Ontos | A parent/child domain tree |

None of these models context-map relationships: customer/supplier, anti-corruption layer, shared
kernel, conformist. The nearest equivalent is ODPS input and output ports. They record upstream
and downstream, but not how meaning is translated between contexts.

**Conclusion.** There is no DDD standard to align with. Kairos should keep its own vocabulary and
say so in its positioning. The useful move is to **project** DDD into the data product standards
below: a bounded context onto an ODPS product and its `domain`, context-map edges onto ports.
Exporting to CML is not worth the effort given that project's state.

## 2. Data product and contract standards

### Bitol ODCS v3.2 and ODPS v1.1: the clear leader

Bitol (LF AI & Data) released **ODCS v3.2.0** (Open Data Contract Standard) and **ODPS v1.1.0**
(Open Data Product Standard) together on 2026-09-08. An ODCS contract describes one dataset: its
schema, quality rules, SLA, team, roles and servers. An ODPS product groups contracts behind input
and output ports.

The v3.2 additions line up almost one to one with things Kairos already authors:

| ODCS 3.2 addition | Kairos equivalent |
|---|---|
| `context` block for AI agents: "instructions, verified statements, and constraints" | DDD invariants and business rules, `rdfs:comment` |
| `synonyms` on schemas and properties, each with locale and source | `skos:altLabel`; the generated ubiquitous language (DD-232) |
| `semanticType`: column, measure or dimension | Gold measures and dimensions |
| Enums whose values carry a label, description and tags | SKOS concept schemes, reference data |
| `deprecated` flag | DD-213 `lifecycle.deprecated` |
| Stable ids that may be namespaced identifiers or URNs | Ontology IRIs (alignment A5 in topic 02) |
| Ten new server types, including Apache Iceberg | — |

ODPS 1.1 adds a top-level product `type`, the same `context` and `synonyms` blocks, deprecation
on products and ports, and stable ids on array entries.

**Adoption.** It is real, but in the tool ecosystem rather than in the platforms:

| Adopter | Support |
|---|---|
| Data Contract CLI (v1.2.0), Data Contract Editor, Entropy Data | ODCS 3.2 and ODPS 1.1 from release day. The CLI lints contracts, tests them live against Databricks, Snowflake, BigQuery and others, and imports from dbt manifests and Unity Catalog. |
| Egeria | Open PR adding ODCS and ODPS support to its integration framework |
| Great Expectations | Open feature request to import ODCS contracts as executable suites |
| Databricks Labs Ontos | Implements ODCS v3.1 (see §3) |

### OpenDataProducts.org ODPS v4.x: same acronym, different standard

The *Open Data Product **Specification*** is a separate Linux Foundation project
(opendataproducts.org) that has nothing to do with Bitol's ODPS. It is oriented to business and
marketplaces:

- v4.1 adds `productStrategy`, which links a product to objectives, product KPIs and business KPIs.
- v4.2 is at release candidate.
- Two companion specifications are planned for 2026: ODPC (catalogs) and ODPG (product graphs).

Data-engineering tooling mostly targets Bitol's ODPS. When a vendor says it "supports ODPS",
check which one it means.

### The platforms do not implement either natively

| Platform | Data products | Contract standard |
|---|---|---|
| Microsoft Purview Unified Catalog | Native governance domains and data products, in a proprietary model | None found. Its terms-of-use attestation is weaker than a data contract. |
| Microsoft Fabric | Through Purview | None found |
| Databricks Unity Catalog | No native contract object. Databricks recommends keeping contracts as YAML outside the platform. | Only through Databricks Labs Ontos |

This corrects topic 02: the reported claim that "Unity Catalog embeds ODCS" has no support. Its
likely source is Ontos, which is an experimental Databricks Labs project, not part of Unity
Catalog.

## 3. Databricks Labs Ontos: the nearest peer

Ontos is a business catalog on top of Unity Catalog (databrickslabs, experimental, actively
developed). It is the closest thing to Kairos found so far:

- Data products and ODCS v3.1 contracts, plus an MCP server.
- An asset model derived from an OWL ontology.
- **Semantic links at three levels:** a contract to a business-domain concept, a table to a
  business entity, a column to a business property.

The difference is where the concepts come from. In Ontos they are RDF/RDFS taxonomy files copied
into a folder and loaded on restart. There is no `owl:imports` closure, no review, no SHACL and no
compilation into dbt or Power BI. Ontos shows that the pattern Kairos implements, ontology-linked
contracts, is being adopted near Databricks, and that the governed authoring side is still
missing there. Kairos could serve as an upstream source for a tool like Ontos.

## 4. Where we align

| # | Alignment | Standard | Effort | V6 candidate |
|---:|---|---|---|---|
| B1 | **Silver contract → ODCS v3.2** export. DD-213 stays the authority. Ontology IRIs become ids and `authoritativeDefinitions`; `skos:altLabel` becomes `synonyms`; `lifecycle.deprecated` becomes `deprecated`; Kairos-only fields (`requirement`, `stability`, `closed`) go in `customProperties`. | Bitol ODCS | Medium | **Yes.** Replaces A4 in topic 02 with a concrete target. |
| B2 | **Gold product → ODCS** with `semanticType` measure/dimension, alongside the Ossie projection (A2) | Bitol ODCS | Small after B1 | Yes, after B1 |
| B3 | **Bounded context → ODPS v1.1 product.** `domain` from the context; output ports reference the B1 contracts; `context` carries invariants; context-map edges become input ports | Bitol ODPS | Medium | Investigate. Decide whether a product is a bounded context or a Gold product. |
| B4 | Verify the export with `datacontract lint` and `datacontract test` against a Fabric warehouse | — | Small | **Yes**, as the acceptance test for B1 |
| B5 | Export to Context Mapper (CML) | — | Medium | **No.** The project is stalled and no consumer asks for it. |
| B6 | OpenDataProducts.org ODPS v4.x / `productStrategy` | ODPS (LF, other) | — | Watch only |

## 5. Position statement

> **Kairos is where the bounded context and the ubiquitous language become machine-readable,
> and linked to governed meaning.** No DDD standard exists; Kairos carries DDD in RDF over the
> OWL closure. It publishes that meaning into the data product standard the tool ecosystem is
> adopting: Bitol ODCS for each contract and ODPS for each product, with ontology IRIs, synonyms
> and agent context filled in from authored sources rather than retyped.

## 6. Open questions

1. Is an ODPS product a **bounded context** or a **Gold product**? A bounded context can span
   several Gold products, and a Gold product can draw on several contexts.
2. Should B1 be one ODCS contract per domain (matching `<domain>.contract.yaml`) or one per
   entity? ODCS allows several schema objects in one contract.
3. Can ODCS `authoritativeDefinitions` carry the ontology IRI unambiguously, or is the new
   namespaced `id` the better carrier? This needs to be tested against Data Contract CLI and
   Ontos.
4. Does Purview Unified Catalog have an import path (API or Atlas types) that an ODCS or ODPS
   document could feed? Nothing was found.

## Sources

- [Entropy Data: ODCS v3.2.0 and ODPS v1.1.0 released (2026-09-08)](https://www.entropy-data.com/news/2026-09-08-odcs-3-2-odps-1-1)
- [Bitol](https://bitol.io/), [Bitol on GitHub](https://github.com/bitol-io),
  [ODCS v3.1.0](https://bitol.io/bitol-announces-odcs-v3-1-0-stronger-smarter-and-stricter/),
  [ODPS v1.0.0](https://bitol.io/announcing-odps-v1-0-0-building-the-language-of-data-products/)
- [Egeria PR #9298: Bitol ODCS and ODPS support](https://github.com/odpi/egeria/pull/9298)
- [Data Contract CLI](https://github.com/datacontract/datacontract-cli),
  [release notes](https://docs.datacontract.com/release-notes)
- [Great Expectations issue #12310](https://github.com/fivetran/great_expectations/issues/12310)
- [Databricks Labs Ontos](https://github.com/databrickslabs/ontos)
- [Databricks: building trusted data products](https://www.databricks.com/blog/building-high-quality-and-trusted-data-products-databricks),
  [Atlan: Databricks data contracts](https://atlan.com/know/databricks/data-contracts/)
- Microsoft Learn: [Purview Unified Catalog](https://learn.microsoft.com/en-us/purview/unified-catalog),
  [data products](https://learn.microsoft.com/en-us/purview/unified-catalog-data-products-create-manage);
  [Atlan: Purview and the context layer](https://atlan.com/know/ai-agent/microsoft/purview-unified-catalog/)
- [OpenDataProducts.org ODPS v4.1](https://opendataproducts.org/v4.1/),
  [v4.2 RC](https://github.com/Open-Data-Product-Initiative/v4.2),
  [standards family expansion](https://blog.opendataproducts.org/opendataproducts-org-is-expanding-into-a-standards-family-21d3aee4c796)
- [Context Mapper](https://contextmapper.org/),
  [CML releases](https://github.com/ContextMapper/context-mapper-dsl/releases),
  [DDD Context Mapper (2026)](https://florian-kraemer.net/software-architecture/2026/04/01/DDD-Context-Mapper.html),
  [ContextFlow](https://github.com/virtualgenius/contextflow)
- [Thoughtworks: the state of data mesh in 2026](https://www.thoughtworks.com/en-us/insights/blog/data-strategy/the-state-of-data-mesh-in-2026-from-hype-to-hard-won-maturity)
- [Three Dots Labs: DDD matters more when AI writes your code](https://threedots.tech/post/ddd-and-ai-coding/),
  [Intré: DDD and AI](https://www.intre.it/en/2026/06/16/domain-driven-design-ai/),
  [AWS: rediscovering DDD one MCP server at a time](https://dev.to/aws/rediscovering-domain-driven-design-one-mcp-server-at-a-time-1i79)
