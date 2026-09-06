# Design a Gold product

**Skill:** `kairos-design-gold`

A Gold product is one Power BI semantic model. It follows a business process, not an
ontology domain: facts from one domain joined to conformed dimensions from several others.
Domains stay the unit of modelling and of Silver compilation; the product is the unit of
delivery.

Gold is optional. A hub that never authors a Gold extension emits nothing here.

## 1. Decide the scope

Declare the product in `kairos.yaml`. Without this block, every Gold-configured domain is
its own product under its own name — which is what a single-domain hub wants.

```yaml
gold:
  products:
    - name: bookings-overview        # lower-case, digits, hyphens: used in file paths
      display_name: Bookings Overview # optional; names the item in the Fabric workspace
      domains: [booking, party, reference-data]
```

A domain belongs to at most one product. One Gold table is emitted once, in one model, so
a report author is never asked which of two copies is authoritative.

## 2. Author each domain's tables

Every participating domain authors its own `model/extensions/<domain>-gold-ext.ttl`,
declaring the tables it owns. A table is materialized by the compile of the domain that
binds it, so this cannot be centralised.

Declare the calendar and the security policy in **exactly one** participating domain. The
product inherits them, which is how one calendar serves every product that includes that
domain. Two declarations fail closed.

**A cross-domain relationship needs a DD-138 `externalReference`** in the child's
EntityBinding. Without one the compiler blocks the endpoint long before Gold sees it, with
`safety.relationship-endpoint`.

## 3. Write down what people need to know

Before authoring measures, record who needs what. If the client has a legacy Power BI
estate, import it first — `import-tmdl` writes a usage summary that ranks measures by how
often a report actually places them on a visual, which is the demand signal a model
inventory cannot give.

```bash
kairos-ontology import-tmdl ../client-export.pbip
```

Then author `integration/discovery/bi/insights.yaml`:

```yaml
schema_version: "1"
personas:
  - id: ops-manager
    description: Runs the terminal day to day
insights:
  - id: on-time-departures
    persona: ops-manager
    question: How many departures left on time this week, by terminal?
    kpi: On-time departure rate
    comparison: prior week
    product: bookings-overview
    measures: [On Time Rate]
    dimensions: [dim_terminal.terminal_name, dim_date.week]
    status: confirmed
```

Only `confirmed` insights are checked. Keep a proposal at `draft` until someone has agreed
to it.

## 4. Emit

```bash
kairos-ontology emit-gold bookings-overview --confirm-emit
```

This compiles every participating domain, shapes them into one model, and writes the PBIP
project under `ontology-hub-publish/powerbi/<product>/`. Read two things in the output:

- **Unresolved relationships.** A foreign key whose join column is emitted but whose target
  table is not in the product. The column is dead until the owning domain joins the product
  or the target is authored as a Gold table.
- **Insight coverage.** Which confirmed insights the product cannot answer yet, and what is
  missing. A warning, not a failure: this is a backlog.

`<product>-insight-brief.md` lands beside the model, grouped by persona.

## 5. Hand off

Give the BI engineer the insight brief and the design guide that ships with the
`kairos-design-gold` skill. They build the report as a **separate Fabric item with its own
name**, bound to the deployed model. The generated `<Product>.Report` is a stub, republished
on every hub release, so edits to it are lost.

## 6. Harvest what they build

When the engineer has hidden columns or added measures in Desktop:

```bash
kairos-ontology harvest-gold bookings-overview --from ../edited/BookingsOverview.SemanticModel
```

This writes a diff and a ready-to-paste Turtle snippet under
`model/planning/gold-harvest/`. It applies nothing. Review it, merge what you agree with
into the owning domain's Gold extension, and re-emit — the edits are then governed, and the
next harvest reports no differences.

A Direct Lake model cannot be saved as a PBIP from Desktop. Export it through Fabric git
integration instead.

## Related

- [Compile and emit](compile-and-emit.md) — the Silver artifacts Gold consumes
- [Consume from a dataplatform](consume-from-a-dataplatform.md) — deploying the result
