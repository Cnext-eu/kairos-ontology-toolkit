# Customer Tech Demo — Agenda (Tell-Show-Tell)

## Demo objective
Show the **end-to-end ontology-driven operating model**: from domain design to generated runtime artifacts across data, integration, UX, and analytics — including **Power BI TMDL semantic model projection in Microsoft Fabric**.

## Audience outcome
By the end, stakeholders understand:
1. Why ontology-first design reduces rework and increases cross-platform consistency.
2. How Kairos projections turn one semantic contract into deployable outputs (MS Fabric Medaillon warehouse, AI Search, Integration platforms, ...).
3. How **extensions** and **SKOS mappings** control behavior without custom code rewrites.
4. How **SHACL** provides semantic data quality guardrails before deployment.
5. How the same ontology supports both **design-time governance** and **runtime delivery** in platform repos.
6. How a **vendor-abstraction projection layer** reduces lock-in and keeps architecture options open.
7. How keeping all semantic context in the ontology hub enables **AI-assisted reasoning** in Navigator over models, concepts, and design decisions.

---

## Agenda (90 minutes)
| Time | Segment | Mode | Outcome |
|---|---|---|---|
| 0-10 | Context, business pain, target operating model | **Tell** | Shared business and architecture goals |
| 10-22 | Core concepts: ontology, projections, extensions, SKOS, SHACL | **Tell** | Common vocabulary for the demo |
| 22-55 | Live modeling-to-projection walkthrough (`silver`, `dbt`, `powerbi`, `a2ui`) | **Show** | One ontology, many generated outputs |
| 55-70 | Fabric focus: TMDL semantic model packaging + publish path | **Show** | Practical BI deployment flow |
| 70-80 | Navigator: visual graph + AI guidance for model exploration and review | **Show** | Better collaboration and decision support |
| 80-90 | Recap, governance model, pilot scope, Q&A | **Tell** | Clear next steps and ownership |

---

## Core concepts to introduce (Tell section)

### Ontology as executable contract
- Domain classes/properties represent business meaning once.
- The ontology is not just documentation; it is the **source for generation**.

### Projections
- Kairos projects the same model into multiple technical outputs:
  - **silver**: physical warehouse-oriented structures
  - **dbt**: transformation pipeline artifacts
  - **powerbi**: gold + TMDL semantic model
  - **a2ui**: UI-oriented schemas/contracts
  - **integration projection patterns**: event/API contract alignment for platforms such as **Dapr** and Logic Apps
  - (and other targets like neo4j, azure-search, prompt/report)

### Tech-agnostic by design (vendor abstraction)
- Projections are designed as a semantic-to-technical translation layer, not a hard vendor binding.
- Same ontology can be projected toward multiple modern runtime stacks.
- This creates more delivery options with less dependency on one vendor stack.

Examples:
- **Data platforms**: Microsoft Fabric Warehouse, Azure Databricks, PostgreSQL, ...
- **Reporting/semantic consumption**: Power BI, Tableau, Looker, Qlik Sense, ...
- **Integration runtimes**: Dapr, Logic Apps, ...

### AI-ready semantic context (Navigator)
- The ontology hub centralizes model, mapping, extension, and quality context in one place.
- Because this context is explicit and structured, Navigator can use AI guidance to reason over:
  - domain concepts and relationships
  - design choices and impact analysis
  - model comprehension and stakeholder communication

### Why this is unique
- Many vendors are adding “ontology” or “context intelligence” capabilities, but often within a single platform ecosystem or a narrow theme (for example only data governance).
- Kairos is grounded in **open semantic web standards** and **industry data models**, and is released under an **Apache 2.0 open-source license**.
- This gives customers long-term portability and avoids locking semantic design into one vendor stack (for example only Microsoft Fabric).
- The approach is forward-looking for **agentic AI** scenarios, with native projection paths that also support AI-centric use cases such as:
  - **RAG** enablement via search-oriented projections (e.g., Azure AI Search target)
  - **A2UI** projection for AI-assisted user experiences
  - cross-platform integration and analytics projections from the same semantic core

### Extensions
- `*-silver-ext.ttl` and `*-gold-ext.ttl` capture implementation intent (SCD, FK behavior, table typing, measures, hierarchy hints, RLS/OLS hints, etc.).
- Keeps core business ontology clean while enabling platform-specific control.

### SKOS mappings
- SKOS connects source columns to ontology properties (semantic traceability).
- Provides explainable lineage from source systems to semantic model.

### SHACL for quality
- SHACL validates model constraints before projection/runtime usage.
- Prevents semantic drift and catches quality/design issues early.

---

## Logistics blueprints positioning
- Use the logistics blueprint as a **reference domain accelerator**:
  - reusable domain patterns (party, shipment, route, events, sustainability, etc.)
  - faster onboarding and consistent naming/structure
- Demonstrate how blueprint-aligned domains can be adapted per customer while preserving interoperability.

---

## Full end-to-end scenario (Tell-Show-Tell script)

### 1) Tell (before live demo)
- Current pain points:
  - fragmented mappings and duplicated logic per platform
  - BI and integration models diverge over time
  - changes are slow and expensive to propagate
- Proposed approach:
  - ontology-hub as design-time contract
  - projection engine as implementation automation
- Expected outputs today:
  - silver artifacts
  - dbt package
  - powerbi/TMDL semantic model
  - a2ui projection to show non-BI reuse
  - integration projection view (Dapr-oriented contract pattern)

### 2) Show (live)
1. Start in `ontology-hub/model/`:
   - ontologies, extensions, mappings, shapes.
2. Highlight SKOS mapping and SHACL shape examples.
3. Run projection pipeline focused on:
   - `silver`, `dbt`, `powerbi`, `a2ui`, and integration projection pattern (Dapr).
4. Inspect generated outputs under `ontology-hub/output/`.
5. Show Power BI structure:
   - `output/medallion/powerbi/<domain>/<Domain>.SemanticModel/definition/`
   - consolidated semantic model:
     `output/medallion/powerbi/consolidated/Consolidated.SemanticModel`
6. Show Fabric publish/import readiness path.
7. Show Navigator:
   - visual model graph navigation
   - AI-guided support for understanding relationships, impact, and modeling decisions.

### 3) Tell (after live demo)
- Value delivered vs manual:
  - one semantic source, multi-target consistency
  - faster change propagation
  - traceability from source to KPI/UI
  - reduced vendor lock-in through technology-agnostic projection options
- Governance and operating model:
  - model + extension + mapping reviews
  - SHACL validation gates
  - versioned releases for consumer repos
- Pilot recommendation:
  - one logistics process, one source, one semantic model + one integration flow.

---

## Design-time vs Runtime responsibilities

| Area | Ontology Hub (Design-time) | Tech/Data Platform Repos (Runtime) |
|---|---|---|
| Purpose | Semantic design authority | Execution and operations |
| Owns | Ontologies, extensions, SKOS mappings, SHACL, projections | Environment config, deployment pipelines, platform integration |
| Output | Versioned generated artifacts | Running data products, BI models, APIs/UI integration |
| Change control | Semantic review + versioning | Release consumption + environment rollout |
| Cadence | Domain-driven evolution | Continuous deployment / operational updates |

---

## Demo to-do checklist
- [ ] Freeze demo source inputs.
- [ ] Verify domain ontologies + logistics blueprint scope for selected scenario.
- [ ] Ensure required `*-silver-ext.ttl` and `*-gold-ext.ttl` files are present.
- [ ] Validate SHACL and syntax before demo run.
- [ ] Run projections and verify freshness for `silver`, `dbt`, `powerbi`, `a2ui`.
- [ ] Validate consolidated semantic model package and Fabric publish path.
- [ ] Prepare Navigator walkthrough (graph + AI guidance prompts).
- [ ] Prepare fallback screenshots/videos.
- [ ] Assign speaking roles (business, architecture, live ops, governance/Q&A).

---

## Demo artifacts
- Agenda and storyline: `.docs/demo/demo.md`
- Slide outline: `.docs/demo/ppt-outline.md`
- Optional appendix: projection target cheat sheet + design-time/runtime RACI
