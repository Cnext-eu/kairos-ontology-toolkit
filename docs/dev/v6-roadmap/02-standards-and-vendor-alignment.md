# 02 — Open standards and vendor alignment (Microsoft, Databricks, dbt)

Status: analysis, 2026-10-11. No decision record yet. Builds on
[01 — Apache Ossie](01-apache-ossie-positioning.md).

## Question

Which open standards cover what Kairos does? Which ones do our delivery vendors (Microsoft
Fabric and Power BI, Databricks, dbt) actually implement? Where should V6 align?

## 1. The standards landscape

Kairos covers five concerns. Each row lists the open standard or foundation project that
covers that concern today.

| Kairos concern | Open standard / project | Foundation | Status (Oct 2026) | Kairos today |
|---|---|---|---|---|
| Canonical meaning (classes, properties, hierarchy, labels, synonyms) | **W3C OWL / RDFS / SKOS / SHACL** | W3C | Stable | Native: OWL closure (DD-243), rdflib, pySHACL |
| Ontology repository and SPARQL serving | **Apache Jena / Fuseki** | ASF | Active top-level project, Fuseki 6.0 (Jan 2026) | Not used. The hub is files in Git. |
| Semantic layer (metrics, dimensions, relationships) | **Apache Ossie** (formerly OSI); MetricFlow is its reference implementation | ASF incubator | Spec `0.2.0.dev0` | Gold spec → TMDL only |
| Data contracts and data products | **Bitol ODCS v3.x / ODPS** | LF AI & Data (graduated) | Stable, v3.2 | Own `SilverContract` (DD-213) |
| Metadata federation | **Egeria**; Apache Atlas (legacy); Apache Gravitino | LF AI & Data; ASF | Active | None |
| Table catalog | **Apache Polaris** (Iceberg REST); Unity Catalog OSS | ASF (top-level project since Feb 2026); LF AI & Data | Active | None |
| Lineage | **OpenLineage** | LF AI & Data | Active | None, but dbt emits it |
| Run telemetry | **OpenTelemetry** semantic conventions | CNCF | Active | Opt-in OTel export (DD-151, DD-242) |
| Agent context | **MCP**, `AGENTS.md` | Agentic AI Foundation (Linux Foundation) | Active | MCP server and `AGENTS.md` (DD-243, DD-246) |

Two observations:

- **The CNCF has no ontology or semantic-model project.** Its relevance to Kairos is limited
  to OpenTelemetry, which we already follow. The data standards live in the Linux Foundation's
  **LF AI & Data** foundation (Bitol, OpenLineage, Egeria, Unity Catalog OSS) and its new
  **Agentic AI Foundation** (MCP, `AGENTS.md`; Gravitino joined in early 2026).
- **No vendor-neutral standard for the ontology layer exists apart from W3C OWL.** Ossie's
  ontology working group has no spec yet, Databricks's "Genie Ontology" is proprietary and
  learned rather than authored, and Microsoft's Fabric IQ ontology uses its own metamodel but
  imports and exports OWL. **Authoring in OWL keeps Kairos on the only open standard for
  meaning.**

## 2. Vendor by vendor

### Microsoft (Fabric, Power BI)

| Fact | Source |
|---|---|
| **Fabric IQ ontology item (preview).** Entity types, properties, relationships, inheritance, namespaces, natural-language rules, metrics (taken from Power BI DAX measures) and **data bindings** to lakehouses, warehouses and semantic models. An ontology agent and optional graph materialisation. The old experience retires on 2027-01-31. | [Learn: ontology overview](https://learn.microsoft.com/en-us/fabric/iq/ontology/overview) |
| **Imports TTL, RDF/RDFS and OWL into an empty item. Exports TTL and RDF.** `owl:Class` → entity type, `owl:DatatypeProperty` → property, `owl:ObjectProperty` → relationship, `rdfs:label` → display name, `rdfs:comment` → description, **`skos:altLabel` → synonym**, single-parent `rdfs:subClassOf` → inheritance. Restrictions, cardinalities, property characteristics and non-default-language labels are dropped or logged. Multiple inheritance keeps only the first parent. | [Learn: import/export](https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-import-export) |
| Can generate an ontology from a Power BI semantic model. The measures become metrics, and the semantic model keeps ownership of the DAX. | same |
| **Microsoft has joined Apache Ossie.** It contributed the bidirectional Power BI ↔ Ossie converter (TMSL and TMDL), wants DAX recognised as an Ossie query language, and says it will "help advance Ossie support for ontologies". | [Snowflake engineering blog, 2026-09-30](https://www.snowflake.com/en/blog/engineering/apache-ossie-microsoft-ecosystem-support/); [CIO](https://www.cio.com/article/4229751/microsoft-google-back-apache-ossie-to-make-enterprise-data-and-ai-platforms-more-interoperable.html) |

**Alignment: strong and direct.** Fabric IQ's metamodel matches the Kairos stack layer for
layer:

| Kairos | Fabric IQ |
|---|---|
| OWL closure (classes, datatype and object properties, labels, comments, `skos:altLabel`) | Ontology item via TTL import |
| EntityBinding + Silver tables | Data bindings (entity → lakehouse or warehouse table) |
| Gold measures emitted as TMDL | Metrics (the semantic model owns the DAX) |
| Business rules in the DDD layer (DD-229..232) | Rules in natural language |

Our annotation discipline (label, comment, altLabel) is exactly what the Fabric importer
reads. Kairos can **author** the ontology, with review, closure, SHACL and Git history, and
**publish** it into Fabric IQ, where agents consume it. Fabric IQ alone offers none of that
governance: import works only into an empty item, and versions are manual.

Gaps to handle in a projection:

- Fabric's importer does not follow `owl:imports`. **Flatten the closure** into one TTL file
  through `load_ontology`.
- Multi-parent classes lose their extra parents. Lint for this before publishing.
- OWL restrictions and SHACL shapes are not carried. They stay in Kairos, which is acceptable
  because those rules are already enforced in Silver.
- Import requires an empty item, so a release means recreating the item and rebinding. Check
  whether the ontology item definition API or Fabric CI/CD (Git integration) allows in-place
  updates. If it does, emit the item definition directly instead of TTL.

### Databricks

| Fact | Source |
|---|---|
| **Unity Catalog Metric Views** are generally available (2026-04-02). They support multi-fact relationships and level-of-detail calculations, with materialisation in preview. Open source in Apache Spark and Unity Catalog OSS, described as "OSI ready". | [Databricks DAIS 2026 blog](https://www.databricks.com/blog/whats-new-unity-catalog-data-ai-summit-2026) |
| **Unity Catalog Glossary** (terms, concepts, taxonomies; preview "coming soon" as of June 2026). **Genie Ontology** is a "continuously learned" context layer: inferred, not authored, and proprietary. | same |
| An Ossie ↔ Metric View converter exists (`converters/databricks`, PR #152). | [apache/ossie#152](https://github.com/apache/ossie/pull/152) |
| Reported: Unity Catalog embeds ODCS and ODPS. *Unverified, from a secondary source.* | [Bitol](https://bitol.io/bitol-graduates/) |

**Alignment: at the semantic layer and contract level, not at the ontology level.** I found no
OWL or RDF import. The Databricks route for a Kairos Gold product is **Gold spec → Ossie →
Metric View** through the existing converter, with no Databricks-specific emitter of our own.
The Glossary is a candidate target for our ubiquitous language (label, comment, synonyms)
once its API exists. Genie Ontology competes with an authored ontology on the "learned versus
governed" axis, and Kairos sits on the governed side.

### dbt

| Fact | Source |
|---|---|
| **MetricFlow** has been open-sourced under Apache-2.0 (Coalesce, Oct 2025) and contributed as **the reference implementation for OSI/Ossie**, including its JSON metadata schema. | [dbt blog](https://www.getdbt.com/blog/dbt-labs-affirms-commitment-to-open-semantic-interchange-by-open-sourcing-metricflow); [Ossie update](https://ossie.apache.org/updates/announcing-open-source-metricflow-governed-metrics-for-ai-and-agents/) |
| Ossie has a dbt converter (`converters/dbt`). dbt Labs is a founding Ossie member. | [apache/ossie](https://github.com/apache/ossie) |
| dbt has no ontology layer. Its "semantic models" are MetricFlow entities, dimensions and measures over dbt models. | — |

**Alignment: dbt is already our delivery runtime.** We emit dbt Silver and Gold models today.
The missing piece is a **dbt semantic model / metrics YAML** beside the Gold dbt models. That
would give non-Power BI consumers (and dbt's own Semantic Layer and agents) the same governed
measures that TMDL gives Power BI. It can come either directly or through Ossie plus the dbt
converter. dbt also emits **OpenLineage** natively, so lineage costs us nothing if we keep
ontology IRIs in `meta.kairos`.

## 3. Where we align

| # | Alignment | Standard | Vendors served | Effort | V6 candidate |
|---:|---|---|---|---|---|
| A1 | **Publish the OWL closure to Fabric IQ** as a flattened TTL or item definition, with bindings generated from EntityBindings | W3C OWL/SKOS | Microsoft | Medium | **Yes, top priority.** Microsoft is our primary platform. |
| A2 | **Gold spec → Ossie** projection (topic 01, option B) | Apache Ossie | Databricks, Snowflake, dbt, Tableau, and Microsoft through its converter | Small | **Yes** |
| A3 | **Gold spec → dbt semantic models (MetricFlow)**, directly or through A2 | MetricFlow (Ossie reference implementation) | dbt, plus any MetricFlow consumer | Small after A2 | **Yes, after A2.** Decide between direct and via-Ossie output. |
| A4 | **Silver contract ↔ ODCS v3** export, keeping DD-213 as the authority | Bitol ODCS | Databricks (reported), Egeria, data-contract tooling | Medium | Investigate |
| A5 | Ontology IRIs in `meta.kairos` and Ossie `custom_extensions`, so OpenLineage and catalogs can trace a column back to its concept | OpenLineage, Ossie | All | Small | **Yes.** It is a prerequisite for A1 to A3. |
| A6 | Optional Jena/Fuseki SPARQL endpoint over released closures | W3C SPARQL, Apache Jena | Vendor-neutral agents | Medium | Later. The MCP server covers agents today. |
| A7 | Align our OTel span attributes with the OpenTelemetry GenAI semantic conventions | CNCF OpenTelemetry | Observability back ends | Small | Housekeeping |

## 4. Position statement

> **Kairos authors governed meaning in the only open ontology standard (W3C OWL) and
> compiles it into each vendor's native semantic surface:** Fabric IQ ontology and Power BI
> TMDL for Microsoft, Metric Views through Ossie for Databricks, and MetricFlow semantic
> models for dbt. Vendors are converging on Ossie for the metric layer and on proprietary,
> often *learned*, context layers above it. Kairos is the authored, reviewable and
> version-controlled source those layers lack.

## 5. Open questions

1. Does the Fabric IQ ontology item have a public item definition format (Git integration or
   REST API) that allows in-place updates and bindings, or only UI import into an empty item?
2. Does the Fabric importer honour our `rdfs:label` language tags, or only one "default
   language"?
3. Has Microsoft published how Fabric IQ ontology and Ossie ontology support will relate? Its
   commitment to "advance Ossie support for ontologies" suggests Fabric IQ's metamodel may
   become the Ossie ontology proposal. If so, Kairos should engage with Ossie WG3 early
   (topic 01, option E).
4. Is the claim that Unity Catalog embeds ODCS accurate? Is the Unity Catalog Glossary API
   available yet?

## Sources

- Microsoft Learn: [ontology overview](https://learn.microsoft.com/en-us/fabric/iq/ontology/overview),
  [import/export](https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-import-export)
- [Snowflake: Apache Ossie Microsoft ecosystem support](https://www.snowflake.com/en/blog/engineering/apache-ossie-microsoft-ecosystem-support/)
- [CIO: Microsoft, Google back Apache Ossie](https://www.cio.com/article/4229751/microsoft-google-back-apache-ossie-to-make-enterprise-data-and-ai-platforms-more-interoperable.html)
- [Databricks: Unity Catalog at DAIS 2026](https://www.databricks.com/blog/whats-new-unity-catalog-data-ai-summit-2026)
- [apache/ossie PR #152 (Databricks converter)](https://github.com/apache/ossie/pull/152)
- [dbt Labs: open-sourcing MetricFlow](https://www.getdbt.com/blog/dbt-labs-affirms-commitment-to-open-semantic-interchange-by-open-sourcing-metricflow)
- [Bitol graduates](https://bitol.io/bitol-graduates/), [OpenLineage](https://github.com/OpenLineage/OpenLineage)
- [Apache Jena Fuseki](https://jena.apache.org/documentation/fuseki2/), [Apache Attic](https://attic.apache.org/projects.html)
