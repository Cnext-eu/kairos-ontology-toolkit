# Design Draft — OpenAPI Projector (`openapi` target)

> **Status:** Draft / exploratory. Not accepted, not scheduled. Archived design note.
> **Author context:** requested 2026-07-12. Prompted by the `kairos-mdm-runtime` contract
> work and the question "how easy would it be to generate an OpenAPI contract for a specific
> ontology data domain?"
> **Scope:** proposes a new **projection target** that emits an OpenAPI 3.1 contract from a
> domain ontology. This is a design sketch only — no code is committed by this document.

---

## 1. Motivation

A domain `.ttl` already encodes almost everything an API **data contract** needs: entities,
typed attributes, relationships, cardinality, enums (reference lists), and human-readable
documentation. Today the toolkit projects that structure to dbt, neo4j, azure-search, a2ui,
prompt, silver/gold and report. An **`openapi`** target would let a domain publish a
**versioned, framework-neutral REST contract** the same way the `mdm-profile` target
publishes a runtime-neutral policy contract.

Consumers: dataplatform API layers, the `kairos-mdm-runtime` MDM API surface, downstream
service teams, and API-gateway / SDK-generation tooling (openapi-generator, Swagger UI, etc.).

### Why OpenAPI, not RAML

RAML (RESTful API Modeling Language) is a YAML API spec **originated by MuleSoft** and closely
tied to their Anypoint ecosystem. It is an open format but effectively eclipsed by **OpenAPI**,
which is vendor-neutral (OpenAPI Initiative / Linux Foundation) and has far broader tooling for
codegen, validation, mocking and docs. **OpenAPI 3.1** is recommended because its schema object
is a proper superset of **JSON Schema 2020-12** — the exact dialect already used by the MDM
profile contract (`kairos-mdm-runtime/contracts/mdm-profile.schema.json`), so schema-generation
logic is reusable.

---

## 2. What maps cleanly (RDF → OpenAPI)

| Ontology construct | OpenAPI 3.1 output |
|---|---|
| `owl:Class` | `components/schemas/{ClassName}` (a JSON Schema object) |
| `rdfs:label` / `rdfs:comment` on a class | schema `title` / `description` |
| Datatype property (`owl:DatatypeProperty`, `rdfs:range xsd:*`) | typed `property` (see XSD→JSON-Schema map below) |
| Object property (`owl:ObjectProperty`) | `$ref` to the target schema, or an id field + link |
| `owl:minCardinality ≥ 1` / `owl:someValuesFrom` | field added to `required` |
| `owl:maxCardinality 1` vs unbounded | scalar vs `type: array` |
| Reference list / SKOS `ConceptScheme` / enumerated individuals | `enum` (or a referenced code-list schema) |
| `rdfs:label` / `rdfs:comment` on a property | property `description` |
| Ontology IRI + `owl:versionInfo` | `info.title`, `info.version`, `info.description` |

### XSD → JSON Schema type map (reuse from azure-search / MDM work)

`xsd:string`→`string`; `xsd:integer/int/long`→`integer`; `xsd:decimal/float/double`→`number`;
`xsd:boolean`→`boolean`; `xsd:date`→`string` + `format: date`; `xsd:dateTime`→`string` +
`format: date-time`; `xsd:anyURI`→`string` + `format: uri`. Unknown ranges → `string` with a
`description` note (fail-soft, mirrors existing projectors).

---

## 3. What needs design decisions (the non-mechanical part)

Schema-component generation is low-effort and largely deterministic. The **opinionated** parts
are where design input is required:

1. **Resource & path design.** Which classes become top-level REST resources vs
   embedded/nested schemas? Default proposal: every non-abstract `owl:Class` with an identity
   key becomes a collection resource `/{plural}`; reference lists become read-only `/{plural}`.
2. **Operation set.** CRUD by default, or read-only contract? Proposal: emit **read paths**
   (`GET /x`, `GET /x/{id}`) by default; write paths (`POST/PUT/PATCH/DELETE`) gated by an
   opt-in extension annotation, because write semantics are governance-sensitive (esp. mastered
   entities).
3. **Identity / path keys.** Which property is the resource id? Reuse silver `naturalKey` /
   MDM `is_identifier` annotations where present; otherwise require an explicit annotation.
4. **Pagination, filtering, sorting.** Standard envelope (e.g. `page`/`pageSize` + `items`
   wrapper) declared once as shared components. Which fields are filterable — annotation-driven.
5. **Open-world → closed REST.** RDF is open-world (absence ≠ prohibition); REST resources are
   closed. The projector must decide `additionalProperties: false` vs `true` per schema
   (proposal: `false` for a published contract, overridable by annotation).
6. **Errors, auth, versioning.** Shared error schema; security schemes left as a placeholder
   (`components/securitySchemes`) since auth is deployment-owned (mirrors the MDM runtime
   boundary — the toolkit describes the contract, not the environment binding).

These are exactly the kinds of choices that should be captured as **`kairos-ext:` /
`kairos-api:` annotations** in a `{domain}-api-ext.ttl` extension, so the ontology stays the
source of truth and the projector stays deterministic.

---

## 4. Proposed extension vocabulary (`{domain}-api-ext.ttl`)

Additive, opt-in, following the established extension pattern (like `-silver-ext.ttl`,
`-mdm-ext.ttl`). Illustrative terms (names TBD):

- `kairos-api:exposeAsResource` (bool) — promote a class to a top-level REST resource.
- `kairos-api:resourcePath` (string) — override the collection path segment.
- `kairos-api:identifier` (property) — id used in `/{plural}/{id}`.
- `kairos-api:operations` (`read` | `crud` | list) — which operations to emit.
- `kairos-api:filterable` / `kairos-api:sortable` (on a property).
- `kairos-api:readOnly` / `kairos-api:writeOnly` (on a property).
- `kairos-api:additionalProperties` (bool) — per-schema open/closed override.

Absence of an api-ext file ⇒ **no OpenAPI output** for that domain (opt-in, exactly like
`mdm-profile`). This keeps `--target all` unaffected unless explicitly requested.

---

## 5. Integration with the toolkit (how it plugs in)

The codebase already supports two integration styles; either works:

- **Core projector (like `azure-search`/`neo4j`):** add
  `core/projections/openapi_projector.py`, wire a `target == 'openapi'` branch in
  `core/projector.py` (`_project_single`/dispatch), add `openapi` to `VALID_TARGETS`, and add a
  template dir under the projector template base.
- **External registered target (like `mdm-profile`, MDM-DD-002):** if OpenAPI generation grows
  its own package/optional-dependency footprint, register via
  `register_target("openapi", discover_ext=…, project=…, output_subdir="openapi")` so core stays
  agnostic. Given OpenAPI is a **pure ontology→spec** projection (no runtime concerns), the
  **core projector** style is the natural fit; the registry is only warranted if it pulls heavy
  optional deps.

**Output:** `output/openapi/{domain}-openapi.json` (+ optional `.yaml` and a `.md` summary),
mirroring the `{domain}-mdm-profile.json` convention. Deterministic output (sorted keys) so the
same reviewed hub state reproduces the same contract; a `content_digest` could be added for
parity with MDM if pinning is wanted.

**CLI / skills:** exposed through the existing `project` command and the
**kairos-execute-project** skill (skill-first rule). A `--target openapi` selector; not part of
`all` (opt-in).

**Validation:** self-check the emitted document against the OpenAPI 3.1 schema (a lightweight
`jsonschema` check, exactly like the MDM fixture validation) and optionally lint with an
external tool in CI.

---

## 6. Synergy with `kairos-mdm-runtime`

The MDM runtime already needs a **versioned domain API** (`services/`, see
`docs/mdm/kairos-mdm-runtime.md` §2). An `openapi` projection of the mastered domain could seed
that API's **data-schema contract** (the resource shapes), while the runtime still owns
operation semantics, auth and versioning policy. This keeps a single semantic source (the
ontology) behind both the MDM **policy** contract and the API **data** contract — no schema
drift between them. The two contracts stay separate artifacts with separate lifecycles.

---

## 7. Effort estimate

| Piece | Effort | Notes |
|---|---|---|
| Class → `components/schemas` (datatype props, cardinality, enums, docs) | **Low** | Deterministic; reuses XSD map + JSON-Schema logic already written for MDM |
| Object properties → `$ref` / link fields | Low–Med | Needs a nested-vs-referenced rule |
| `{domain}-api-ext.ttl` vocabulary + parsing | Med | New vocab + SHACL + docs |
| Path/operation generation (read; opt-in write) | Med | The opinionated core; annotation-driven |
| Pagination/filter/error/security shared components | Low–Med | Boilerplate, declared once |
| Wiring (projector, VALID_TARGETS, templates, CLI, skill) | Low | Follows an existing projector nearly verbatim |
| Tests (unit + `tests/scenarios/acme-hub`) | Med | Scenario coverage required per repo rules |

**Bottom line:** a **schema-only** OpenAPI contract (components/schemas, no paths) is a small,
low-risk projector — arguably a day-scale spike. A **full REST contract** (paths, operations,
pagination, auth placeholders, write gating) is a larger, design-heavy effort dominated by the
Section 3 decisions, not the RDF traversal.

---

## 8. Recommended next steps

1. Decide **schema-only vs full-REST** first slice. Recommendation: ship **schema-only**
   (`components/schemas`) as a spike to prove the RDF→OpenAPI mapping on the `acme-hub`
   scenario domains, defer paths/operations to a second slice.
2. If pursued, promote this draft into a proper **DD-NNN** entry in
   `docs/design/toolkit-design-decisions.md` (target registration style, output layout,
   extension vocab, opt-in behavior) and add scenario tests.
3. Confirm the extension-vocab namespace/prefix (`kairos-api:`) and whether OpenAPI output
   should carry a `content_digest` for pinning like the MDM profile.

---

## 9. Open questions

- Read-only contract by default, or CRUD? (Governance-sensitive for mastered entities.)
- YAML, JSON, or both as output serialization?
- One document per domain, or a combined multi-domain contract with shared components?
- Reuse silver `naturalKey` / MDM `is_identifier` for path keys, or a dedicated `kairos-api:`
  identifier annotation?
- Should reference lists become inline `enum`s or standalone code-list schemas + a lookup path?

---

## 10. Worked example — acme-hub `invoice` domain

This section walks a concrete slice of the synthetic scenario hub
(`tests/scenarios/acme-hub/model/ontologies/invoice.ttl`) through the projector to show exactly
what an `openapi` target would emit. It uses the real classes and properties from that domain:
`Invoice`, `InvoiceLine`, `InvoiceTag` (+ the cross-domain `issuedTo → client:Client` link and
the derived `lineTotal`).

### 10.1 Source ontology (excerpt, verbatim from acme-hub)

```turtle
acme-inv:Invoice a owl:Class ;
    rdfs:label "Invoice" ;
    rdfs:comment "A billing invoice issued to a client." ;
    kairos-ext:naturalKey "invoiceNumber" .

acme-inv:invoiceNumber a owl:DatatypeProperty ;
    rdfs:domain acme-inv:Invoice ; rdfs:range xsd:string ;
    rdfs:label "invoice number" ; rdfs:comment "Unique invoice reference number." .
acme-inv:invoiceDate   a owl:DatatypeProperty ; rdfs:domain acme-inv:Invoice ; rdfs:range xsd:date .
acme-inv:totalAmount   a owl:DatatypeProperty ; rdfs:domain acme-inv:Invoice ; rdfs:range xsd:decimal .
acme-inv:currency      a owl:DatatypeProperty ; rdfs:domain acme-inv:Invoice ; rdfs:range xsd:string .

acme-inv:issuedTo a owl:ObjectProperty, owl:FunctionalProperty ;   # cross-domain FK
    rdfs:domain acme-inv:Invoice ; rdfs:range acme:Client .
acme-inv:hasTag   a owl:ObjectProperty ;                            # many-to-many
    rdfs:domain acme-inv:Invoice ; rdfs:range acme-inv:InvoiceTag ;
    kairos-ext:junctionTableName "invoice_tag_bridge" .

acme-inv:lineTotal a owl:DatatypeProperty ;                         # derived → read-only
    rdfs:domain acme-inv:InvoiceLine ; rdfs:range xsd:decimal ;
    kairos-ext:derivationFormula "source.Quantity * source.UnitPrice" .
```

### 10.2 API extension the modeller would add (`invoice-api-ext.ttl`)

Nothing above is API-specific; the opt-in decisions from §3–§4 live in a separate extension so
the domain ontology stays clean:

```turtle
@prefix acme-inv:   <https://acme.example/ontology/invoice#> .
@prefix kairos-api: <https://kairos.cnext.eu/api#> .

acme-inv:Invoice     kairos-api:exposeAsResource true ;
                     kairos-api:resourcePath "invoices" ;
                     kairos-api:identifier acme-inv:invoiceNumber ;
                     kairos-api:operations "read" .          # GET only for this slice
acme-inv:InvoiceLine kairos-api:exposeAsResource true ;
                     kairos-api:resourcePath "invoice-lines" ;
                     kairos-api:identifier acme-inv:lineId ;
                     kairos-api:operations "read" .

acme-inv:invoiceDate kairos-api:filterable true .
acme-inv:currency    kairos-api:filterable true .
acme-inv:lineTotal   kairos-api:readOnly true .              # derived — never client-writable
```

> No `-api-ext.ttl` ⇒ no OpenAPI output (opt-in, like `mdm-profile`).

### 10.3 Generated contract — `output/openapi/invoice-openapi.yaml`

The projector walks the merged graph and emits an OpenAPI 3.1 document. Abridged but
representative:

```yaml
openapi: 3.1.0
info:
  title: Acme Invoice Domain API
  version: 1.0.0                       # from owl:versionInfo
  description: Synthetic invoice domain for scenario testing.   # from rdfs:comment
servers:
  - url: /api/v1
paths:
  /invoices:
    get:
      summary: List invoices
      operationId: listInvoices
      parameters:
        - { name: invoiceDate, in: query, required: false, schema: { type: string, format: date } }
        - { name: currency,    in: query, required: false, schema: { type: string } }
        - { name: page,        in: query, required: false, schema: { type: integer, minimum: 1, default: 1 } }
        - { name: pageSize,    in: query, required: false, schema: { type: integer, minimum: 1, maximum: 200, default: 50 } }
      responses:
        "200":
          description: A page of invoices
          content:
            application/json:
              schema:
                type: object
                required: [items, page]
                properties:
                  items: { type: array, items: { $ref: "#/components/schemas/Invoice" } }
                  page:  { $ref: "#/components/schemas/PageMeta" }
        "400": { $ref: "#/components/responses/Error" }
  /invoices/{invoiceNumber}:
    get:
      summary: Get an invoice by natural key
      operationId: getInvoice
      parameters:
        - { name: invoiceNumber, in: path, required: true, schema: { type: string } }
      responses:
        "200":
          description: The invoice
          content:
            application/json:
              schema: { $ref: "#/components/schemas/Invoice" }
        "404": { $ref: "#/components/responses/Error" }
components:
  schemas:
    Invoice:
      type: object
      title: Invoice
      description: A billing invoice issued to a client.
      additionalProperties: false
      required: [invoiceNumber]                       # from kairos-ext:naturalKey
      properties:
        invoiceNumber: { type: string,  description: Unique invoice reference number. }
        invoiceDate:   { type: string,  format: date }        # xsd:date  → string/date
        totalAmount:   { type: number }                       # xsd:decimal → number
        currency:      { type: string,  description: "ISO currency code (e.g. EUR, USD)." }
        issuedTo:      { $ref: "#/components/schemas/ClientRef" }   # functional obj prop → single $ref
        tags:                                                 # hasTag (unbounded) → array
          type: array
          items: { $ref: "#/components/schemas/InvoiceTag" }
    InvoiceLine:
      type: object
      title: Invoice Line
      description: A single line item on an invoice.
      additionalProperties: false
      required: [lineId]
      properties:
        lineId:      { type: string }
        description: { type: string }
        quantity:    { type: integer }                        # xsd:integer → integer
        unitPrice:   { type: number }
        lineTotal:   { type: number, readOnly: true,
                       description: "Computed total (quantity × unitPrice)." }  # derived → readOnly
        belongsToInvoice: { type: string, description: "invoiceNumber of the parent Invoice." }
    InvoiceTag:
      type: object
      title: Invoice Tag
      additionalProperties: false
      required: [tagCode]
      properties:
        tagCode:  { type: string }
        tagLabel: { type: string }
    ClientRef:                                                # cross-domain link (client domain)
      type: object
      description: "Reference to a client:Client by its natural key (see client-openapi.yaml)."
      properties:
        clientId: { type: string }
    PageMeta:
      type: object
      properties:
        number:     { type: integer }
        size:       { type: integer }
        totalItems: { type: integer }
  responses:
    Error:
      description: Error
      content:
        application/json:
          schema:
            type: object
            required: [code, message]
            properties:
              code:    { type: string }
              message: { type: string }
```

### 10.4 How each construct was resolved

| From the ontology | Became | Rule (from §2–§4) |
|---|---|---|
| `acme-inv:Invoice` (`owl:Class`) | `components/schemas/Invoice` | class → schema |
| `rdfs:comment` on the class | schema `description` | doc mapping |
| `kairos-ext:naturalKey "invoiceNumber"` | `required: [invoiceNumber]` + path key `/invoices/{invoiceNumber}` | identity reuse (§3.3) |
| `invoiceDate` (`xsd:date`) | `type: string, format: date` | XSD map |
| `totalAmount` (`xsd:decimal`) | `type: number` | XSD map |
| `issuedTo` (functional `owl:ObjectProperty`) | single `$ref: ClientRef` (not array) | functional → scalar |
| `hasTag` (unbounded `owl:ObjectProperty`) | `tags: array of $ref InvoiceTag` | unbounded → array |
| cross-domain range `acme:Client` | a slim `ClientRef` by natural key | cross-domain $ref rule |
| `lineTotal` + `derivationFormula` | `readOnly: true` | derived fields are not client-writable |
| `kairos-api:filterable` (ext) | `invoiceDate` / `currency` query params | filter annotation (§4) |
| (no api-ext) | no output | opt-in (§4) |

### 10.5 Notes this example surfaces

- **Cross-domain references** (`issuedTo → client:Client`) need a policy: emit a slim
  `…Ref`-by-natural-key schema (shown) vs a full inlined `$ref` into a shared components file vs
  a combined multi-domain document. This is Open Question §9 made concrete.
- **`junctionTableName` on `hasTag`** is a *silver/storage* concern; for the API it is invisible
  — the projector just sees an unbounded object property and emits an array. Good separation.
- **Derived properties** map naturally to `readOnly: true`, so a future write slice can reuse the
  same schema for request bodies by dropping `readOnly` fields.
- Running this on `acme-hub` would be the natural **scenario test** (§7): assert the emitted
  document validates against the OpenAPI 3.1 meta-schema and that `Invoice.required` contains the
  natural key.
