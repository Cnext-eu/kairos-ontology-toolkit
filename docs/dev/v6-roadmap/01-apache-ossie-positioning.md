# 01 — Positioning Apache Ossie in the Kairos stack

Status: analysis, 2026-10-11. No decision record yet.

## What Ossie is

[Apache Ossie](https://github.com/apache/ossie) (incubating, Apache-2.0) is the renamed
Open Semantic Interchange (OSI). The repository opened in November 2025 and entered the
Apache Incubator in July 2026. Snowflake, Databricks, dbt Labs, Salesforce, Dremio,
RelationalAI, GoodData and Honeydew are among its backers, and it claims more than 50
organisations. Microsoft joined later (announced by September 2026): it contributed the
Power BI converter, wants DAX recognised as an Ossie query language, and has said it will help
advance Ossie's ontology support. See [02](02-standards-and-vendor-alignment.md).

The project describes itself as "an open specification for semantic layer **and ontology**".
In practice the core specification (`core-spec/spec.md`, version `0.2.0.dev0`, unreleased)
covers only the semantic layer:

| Ossie object | Content |
|---|---|
| semantic model | one per document: `version`, `name`, `datasets`, `relationships`, `metrics`, `ai_context`, `custom_extensions` |
| dataset | a fact or dimension table: `source` (`db.schema.table`), `primary_key`, `unique_keys`, `fields` |
| field | `expression` (per SQL dialect), `datatype`, `dimension.is_time`, `description`, `ai_context` |
| relationship | many-to-one only: `from`, `to`, `from_columns`, `to_columns` |
| metric | an aggregate `expression` per dialect (ANSI SQL, DAX, MDX, Snowflake and others), which may span datasets |
| `ai_context` | `instructions`, `synonyms`, `examples` for LLM grounding |
| `custom_extensions` | `vendor_name` plus an opaque JSON `data` string |

The specification has nothing on OWL, RDF, class hierarchies, business rules or data quality.
The "ontology" claim currently rests on two things:

- **Working group 3, "Ontology & Semantic Interoperability"** (in `ROADMAP.md`) wants
  "business concept mapping independent of physical data layout". This is planned work with
  no specification text yet.
- **`converters/ontology`** converts a Palantir ontology export to and from Ossie and a
  "Spec YAML". It is a Palantir bridge, not an OWL bridge.

Converters are bidirectional and live in `converters/<vendor>`: dbt, Snowflake, Databricks,
Salesforce/Tableau, ThoughtSpot, Cube, GoodData, Sigma, Omni, Hex, Holistics, Polaris,
NVIDIA, Microsoft and a few more. The Microsoft converter reads and writes TMSL `model.bim`
and TMDL offline, and it never rewrites DAX or SQL expressions. The main repository no longer
accepts new converters, so a Kairos converter would live in our own repository.

## Where it sits relative to Kairos

```
  Kairos authority                     Ossie's layer
  ────────────────                     ─────────────
  OWL canonical ontology (closure)  ◄── WG3 "ontology" aims here; no spec yet
  EntityBinding / Silver contract
  dbt Silver models
  Gold product (DimensionalGoldSpec) ◄── Ossie core spec = this layer
     ├─ TMDL / Power BI semantic model  (what we emit today)
     └─ Ossie YAML                      (possible new projection)
```

Ossie's semantic model is one Kairos **Gold product** under another name. The fields of
`DimensionalGoldSpec` (`core/projections/dbt/gold_specs.py`) line up almost one to one:

| Kairos Gold | Ossie | Fit |
|---|---|---|
| `GoldTableSpec` (fact, dimension) | `dataset` + `source` + `primary_key` | direct |
| `GoldColumnSpec` | `field` (ANSI_SQL column expression, `datatype`) | direct |
| `GoldRelationshipSpec` | `relationship` (many-to-one) | direct for many-to-one; inactive or role-playing edges need an extension |
| `GoldMeasureSpec` (DAX) | `metric` with a `DAX` dialect expression | direct; `lifecycle` and `measure_dependencies` need an extension |
| `GoldCalendarSpec` / calendar roles | `dimension.is_time` | partial: Ossie has no calendar hierarchy until the "Dimensions, Hierarchies, Time" working group exists |
| `GoldSecuritySpec` (RLS) | none | `custom_extensions` only |
| `measureDisplayName` (DD-238) | `name` versus `description` | needs a naming convention |
| ontology `rdfs:label`, `rdfs:comment`, `skos:altLabel` | `description`, `ai_context.synonyms` | **a strong fit**, see below |
| ontology class or property IRI | none | `custom_extensions` (vendor `KAIROS`) until working group 4 delivers "stable identifiers" |

The last two rows are where Kairos adds something Ossie lacks. Ossie wants AI-ready synonyms
and stable concept identity, and its ontology working group has not yet said where they come
from. A Kairos hub already holds both in a governed ontology: the closure, the ubiquitous
language from DD-229 to DD-232, and the confirmed glossary. A Gold-to-Ossie projection can
fill them in deterministically, with no LLM involved.

## Options

| | Option | Value | Cost | Verdict |
|---|---|---|---|---|
| A | Ignore | none | none | No. The backers are the warehouses our clients run next to Fabric. |
| B | **Emit Ossie as a Gold projection** next to TMDL | One Gold product reaches Snowflake, Databricks, dbt, Tableau and ThoughtSpot through their own converters. Synonyms and IRIs carry ontology meaning to AI tools. | Small: a new renderer over the existing `DimensionalGoldSpec`. Golden tests. Pin a spec version. | **Yes, V6** |
| C | **Import Ossie as demand evidence**, like `import-tmdl` | A non-Power BI client's existing semantic layer becomes Gold demand and domain-design evidence. Sources like dbt and Snowflake work through Ossie without a converter of our own for each. | Medium: reuse the `bi_demand` / `import_evidence` path. Ossie has no report-usage counts, so demand is presence-only. | **Yes, V6** |
| D | Adopt Ossie as the Gold authoring format | Fewer formats | Gives up DD-243 closure semantics, RLS, BPA, calendars and the Silver contract linkage. The spec is pre-1.0 and already broke the 0.1.1 `semantic_model` array. | **No** |
| E | Engage the Ontology working group with an OWL ↔ Ossie mapping | Positions Kairos as the reference "ontology behind the semantic layer". It shapes WG3 and WG4 before they settle on Palantir-style JSON. | Community time and no direct deliverable | **Watch now, engage after B** |
| F | Replace our TMDL emitter with Ossie plus `ossie-microsoft export` | One emitter | Loses perspectives, RLS, display folders, BPA conformance and the TMDL validator gate. A dependency on an incubating converter. | **No.** TMDL stays first-class. |

## Recommended position

**Ossie is an interchange format at the Gold boundary. It is never an authority.** The OWL
closure keeps the meaning, the Silver contract keeps the structure, and the Gold spec keeps
the dimensional design. Ossie is a deterministic projection of the Gold spec, and also an
evidence format we can read.

The message for clients: "Kairos authors the governed ontology. Your semantic layer, whether
it is Power BI, Snowflake, Databricks or dbt, is generated from it. Ossie is how we hand it to
the tools we don't target natively."

## Risks and constraints

- **Spec churn.** The spec is at `0.2.0.dev0` and has had one breaking change already. Pin
  one spec version per toolkit release, validate the output against the published
  `ossie-schema.json`, and keep the renderer behind a capability flag until Ossie 1.0.
- **Dialect semantics.** Only `OSSIE_SQL_2026` has defined semantics, and Ossie treats every
  other dialect as opaque. Our DAX measures pass through as `DAX` text. A consumer without a
  DAX engine cannot run them. Emitting `ANSI_SQL` for simple additive measures would be extra
  scope; decide this explicitly.
- **Extension discipline.** RLS, IRIs and measure lifecycle can only travel in
  `custom_extensions`. Check whether `vendor_name` is a closed enum or free text before
  choosing `KAIROS`.
- **Microsoft's backing is recent.** Microsoft now backs Ossie and contributed the Power BI
  converter, but its native ontology surface is Fabric IQ, which imports OWL. For a
  Fabric-first client, Ossie is additive and never a replacement for TMDL or a Fabric IQ
  publication (topic 02, A1).
- **Byte determinism.** The projection must be byte-stable like every other emit (the
  `optional_field()` discipline from #998/#999).

## Open questions before a decision record

1. Is `custom_extensions.vendor_name` free text? Can `data` hold structured JSON, or only a
   string?
2. How do role-playing and inactive relationships (ours exist in `GoldRelationshipSpec`) map,
   given that Ossie allows many-to-one only?
3. Should one hub emit one Ossie model per Gold product (matching one TMDL model per product),
   or one per domain?
4. Does Ossie's dbt converter target MetricFlow semantic models? That would let our emitted
   dbt package carry a semantic layer for non-Power BI consumers at no extra cost.
5. What is WG3's current direction in GitHub Discussions and Slack? Is anyone proposing
   OWL/SHACL alignment?

## Proposed next steps

1. **Spike (1–2 days, scratchpad only):** take one real hub's `DimensionalGoldSpec`, render
   it to Ossie YAML, validate it against `ossie-schema.json`, and round-trip it through
   `ossie-microsoft export`. Diff the result against our own TMDL emit. The diff measures
   what Ossie loses and settles questions 1–3.
2. Raise a V6 issue and decision record for option B (Gold → Ossie projection), with the
   spec-pin policy.
3. Raise a V6 issue for option C (`import-ossie` as demand and design evidence), reusing the
   `import-tmdl` evidence path.
4. Read WG3 and WG4 discussions, then decide on option E.

## Sources

- <https://github.com/apache/ossie> (README, `core-spec/spec.md`, `ROADMAP.md`,
  `converters/microsoft`, `converters/ontology`)
- <https://ossie.apache.org/updates/ossie-enters-apache-incubator/>
- <https://incubator.apache.org/projects/ossie.html>
- <https://www.getdbt.com/blog/osi-is-now-apache-ossie>
