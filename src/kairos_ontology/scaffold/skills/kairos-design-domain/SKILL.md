---
name: kairos-design-domain
description: >
  Interactive v5 workflow for designing a bounded, source-grounded OWL/Turtle
  canonical model patch. Uses confirmed business context, selected industry
  references, PII-safe source evidence, and optional downstream demand. NOT for
  authoring EntityBinding YAML or generating dbt artifacts.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# V5 Canonical Domain Design

Use this skill to create or amend `model/ontologies/<domain>.ttl`. OWL/Turtle is
the authority for canonical classes, properties, relationships, labels, and
definitions. Produce the **smallest useful canonical slice** as a reviewable
ontology patch; do not design an entire enterprise model in one pass.

This is the DD-133 v5 clean break. Work only with the authoritative inputs listed
below and persist only the accepted ontology patch. Existing v4 hubs must be
rebuilt as v5 hubs rather than migrated or dual-authored.

## Design fleet mode (DD-088)

Default is interactive. Ask the user to confirm source completeness, business
terminology, reference-model choices, the bounded slice, and the ontology patch
before writing it.

If the user explicitly requests design fleet mode for this invocation:

- announce that AI will make checkpoint decisions;
- apply every evidence, privacy, scope, and validation gate below;
- mark decisions **AI-approved**, not user-confirmed;
- record rationale, confidence, and evidence references in the in-session review;
- stop for low confidence, missing source evidence, naming ambiguity,
  policy-sensitive choices, proprietary/PII risk, or destructive changes.

The override applies only to this skill invocation. It expires when the skill
ends or pauses, is never inherited by another skill or later resume, and does
not authorize decisions in any other skill.

## Authoritative inputs

Read only the inputs relevant to the requested domain:

1. `integration/discovery/` — confirmed business context and glossary.
2. `integration/sources/<source>/*.ttl` — Bronze schema and already-redacted
   representative samples.
3. Selected ontology-reference modules and their catalog-resolved import closure.
4. Existing `model/ontologies/<domain>.ttl`, when amending a domain.
5. Optional TMDL/PBIP or Gold demand supplied by the user.

Keep the four evidence roles distinct:

| Role | Meaning |
|---|---|
| Business authority | Confirmed concepts, meaning, terminology, and boundaries |
| Industry inspiration | Reusable classes/properties and alignment patterns |
| Source feasibility | Relations, columns, types, nullability, and masked examples |
| Downstream demand | Optional analytical fields or relationships; never business authority |

An input may support more than one role, but never silently promote source shape
or downstream demand into a business fact.

## Hard gates

### Gate 0: Scoped reference-inventory freshness

Before proposing or editing a class/property, run the scoped pre-flight:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology check-inventory --domains <active-domain> --explain-scope
```

If the hub installs more than one accelerator pack and pins none, this aborts with
`Accelerator selection is ambiguous`; pass `--accelerator <pack>` or pin
`[tool.kairos].accelerator` in the hub `pyproject.toml` (see **kairos-setup-config**).

This is the only freshness authority for selected reference inventories. Missing
or stale in-scope inventories are blocking: **STOP**. Unrelated repository-wide
failures are non-blocking when the scoped command exits zero. Report the
installed/current local reference-model version from
`ontology-reference-models/VERSION`, or `unknown` when absent. Never silently
update reference models. Route an approved update through **kairos-toolkit-ops**
and rerun the same check.

### Gate 1: Source completeness

Run this gate on every modeling pass, including the first:

1. list imported and analysed sources under `integration/sources/`;
2. identify which sources appear relevant to the requested domain;
3. ask whether additional or newer sources must be imported first.

If no relevant source vocabulary exists, or the user says more evidence is
needed, stop and invoke **kairos-design-source**. Return here only after the
evidence is available. Never model against an empty source set.

Discovery is no longer optional (DD-148): if there is neither a `businessdiscovery/`
narrative (DD-048) nor a discovery conformance artifact at
`integration/discovery/core-concepts-conformance.yaml` (DD-090), STOP and invoke
**kairos-design-discovery** first — do not proceed on inferred business terms. The
two are independent; either is enough to pass this baseline check. If a conformance
artifact exists, additionally read its `mode` field. When `mode: fleet`, check for
unresolved AI-decided concept judgments (`needs_confirmation: true`, or no recorded
`confidence`); if any exist, STOP and invoke **kairos-design-discovery** so a human
confirms them before design proceeds — this check applies regardless of whether a
`businessdiscovery/` narrative exists. `kairos-ontology compile`/`validate` enforce
both checks and hard-fail otherwise — this gate only lets you catch it earlier.

### Gate 2: PII-safe, source-grounded evidence

Read relevant source relations and columns before proposing classes or
properties. If TMDL/PBIP input is present, read its relevant tables, columns, and
relationships too.

Expose only masked, redacted, aggregated, or synthetic examples to the model.
Never reveal or persist raw names, emails, addresses, identifiers, free text, or
other sensitive values. Treat an unredacted sample as blocking and route it back
through the source privacy/redaction workflow.

Every proposed class/property must cite one or more of:

- confirmed business context or user statement;
- a selected reference-model term;
- a specific source relation/column and type;
- optional downstream demand.

General domain knowledge may appear only as a clearly labeled low-confidence
suggestion and cannot enter the accepted patch without confirmation.

### Gate 3: Bounded ontology patch

One invocation works on one domain and one coherent canonical slice:

- one primary entity or one tightly related amendment;
- only directly required reference/value classes and relationships;
- only source-feasible or explicitly confirmed properties;
- no speculative neighboring domains or bulk ontology generation.

If the request spans multiple slices, propose an order and complete one slice
before starting the next.

### Gate 4: Explicit confirmation

Interactive mode requires explicit confirmation of:

1. business term and technical class/property names;
2. reuse, specialization, or local-definition choices;
3. class boundaries and relationships;
4. the exact bounded patch.

Whenever presenting modeling options for confirmation, briefly compare the
options side by side: how their semantics differ, what evidence supports each,
and the trade-offs for reuse, specialization, source feasibility, downstream
usability, and future mapping work. Include a concrete worked example when it
would clarify the choice. Prefer a small visual such as a Mermaid class sketch,
ERD fragment, or before/after hierarchy; alternatively use PII-safe source
evidence already available in the design context, such as masked
`kairos-bronze:sampleValues` or already-redacted `.samples.yaml` rows. Never
show source-derived examples unless the sample evidence is confirmed
PII-safe; if it is unavailable, unclear, or unredacted, use a generic synthetic
example and keep the source privacy/redaction workflow blocking.

Silence is not approval. Do not write draft TTL for review before these
checkpoints. Fleet mode may make these decisions only under its invocation-scoped
rules.

### Gate 5: Ontology integrity

Before applying a patch, run `kairos-ontology validate --syntax` (or the
hub's effective `validate` invocation) against the candidate file and treat
its `syntax` and `naming` findings as authoritative. Pass the active domain with
`validate --syntax --domain <active-domain>` (parity with `compile`, resolves the
accelerator); on a multi-pack hub that pins no accelerator, add `--accelerator
<pack>` (same ambiguity as Gate 0). The CLI deterministically
enforces: one `owl:Ontology` declaration with `rdfs:label` and
`owl:versionInfo`; every class has `rdfs:label` and `rdfs:comment`; every
property has `rdfs:label` and `rdfs:domain`; every `owl:DatatypeProperty` has
`rdfs:range`; PascalCase classes
and camelCase properties; no term declared as more than one of
{Class, DatatypeProperty, ObjectProperty}. Do not hand-write rdflib checks for
any of these — the CLI check is the authority.

An `owl:ObjectProperty` with no `rdfs:range` is a naming **warning**, not an
error: DD-133 §7 lets a `relationships:` entry defer the range and validates the
relationship on its authored `target:`/`on:` endpoint alone — the reference-model
`deferred-relationship` shape. Never patch that warning away with `rdfs:range
owl:Thing`; that is worse than omitting the range, because the compiler rejects a
declared range that differs from the authored `target:` class
(`safety.relationship-endpoint`) while an omitted range compiles. It is warned
separately. Declare the real target class, or leave the range off.

Still confirm manually, since these require judgment the CLI cannot supply:

- catalog-resolved imports and terms;
- no accidental reference-model specialization;
- source types can feasibly populate proposed property ranges.

Do not apply a candidate with syntax, naming, or convention errors.

## Canonical design loop

### 1. Establish scope and mode

Identify the hub root from `kairos.yaml`, domain, requested slice, and whether
this invocation is interactive or fleet. If the request is ambiguous, remain
interactive.

### 2. Complete source pre-flight

Run Gate 1 and wait for the user's source-completeness answer in interactive
mode. Read all relevant source vocabularies, optional TMDL/PBIP demand, and
confirmed discovery context. Never infer completeness from filenames alone.

### 3. Inspect selected industry references

Run Gate 0. Read the relevant import closure and surface the specialization tree,
including SUBCLASSES of the parent and subclass-specific properties. Mark
specializations as `(subclass)` in proposals. Prefer justified reuse over
accidental local duplication, while keeping business meaning authoritative.
When there are plausible reuse, subclass, or local-definition alternatives,
show how the alternatives compare and illustrate the shape with a compact visual
or PII-safe sample-grounded example when relevant.

### 4. Build an in-session evidence matrix

Present only PII-safe evidence:

| Candidate term | Business authority | Industry inspiration | Source feasibility | Downstream demand | Confidence |
|---|---|---|---|---|---|

Use relation/column identifiers and types; examples must remain masked. State
conflicts and missing evidence explicitly. This matrix is an in-conversation
working scratchpad; material rationale belongs in the hub Decision Log under
`decisions/` when it meets the materiality threshold below.

### 5. Propose the smallest useful slice

Present:

- primary class and any required superclass;
- properties with domain, range, definition, and evidence;
- object relationships with target and intended cardinality;
- terms deliberately excluded from this slice;
- unresolved questions and confidence.

If more than one bounded-slice option is viable, present an options comparison
instead of a bare list. Explain the meaning and trade-offs of each option, cite
the evidence matrix, and include a concrete example: preferably a small Mermaid
diagram/ERD or a PII-safe example drawn from masked source samples. Use a
generic worked example when source samples are unavailable or cannot be shown
safely.

Keep source representation details out of the canonical model. Source keys,
grain, load policy, expressions, and relationship failure actions belong in the
v5 EntityBinding authored by **kairos-design-mapping**.

### 6. Review naming and structure

Before finalising property and relationship names, consult the reference-models
**pattern library** — sector-neutral naming conventions and anti-patterns
harvested from prior hubs (#262 §3):

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology list-patterns --format json
```

This is advisory, authoring-time craft, not a hard gate. Treat each pattern's
`normativity` block per section: naming ships normative, structural guidance
ships advisory. An absent or empty library is a silent no-op — never block on it.
Read `naming_conventions` as-is: each pattern uses its own key set, so there is no
fixed table to fill in.

For a pattern whose `applicability` matches the slice, consult **all four** of its
surfaces — the structural guidance is the part that cost the most to derive, so do
not stop at the naming table:

- **`naming_conventions`** — prefer these normative names (e.g. the
  requested/planned/estimated/actual timestamp quartet) over inventing a synonym.
- **`anti_patterns`** — reject these on **structure as well as names**, citing the
  pattern `id` and `rejection_reason`. The structural ones are the high-value
  rejections: mode-typed subclasses of an aggregate (`OceanOrder`/`RoadOrder`),
  subclassing a mode-bound standard class at the wrong grain, a shortcut link that
  bypasses a reified intermediate, or a document standing in for a reservation.
- **`mode_bindings`** — when a pattern declares them, they decide the binding
  target per mode. `status: modelled` → bind to the named `target`;
  `status: extension-point` → the standard exists but is not modelled here, so
  **do not invent a class** — record it as an extension point;
  `status: pattern-only` → no standard forces a shape, follow the pattern alone.
  The status list is **not closed** — the library evolves, so for any value you do
  not recognise, treat the binding as advisory, state what the entry says, and ask
  rather than guessing. Independently, honour an `import_policy` when present:
  `reference-only` means resolve and cite the IRI but **never add it to an
  accelerator pack's includes**, even though the status is `modelled`.
- **`grain_collisions`** — read each as an explicit *do not subclass and do not
  merge* boundary. Entries ship in **two shapes** and you must handle both: a
  mapping with `against` (the class IRI not to collapse into) plus `reason`, or a
  bare prose string describing the collision. Quote whichever you find when you
  explain the boundary to the user; never assume the `against`/`reason` keys are
  present.

Obtain explicit decisions for every item in Gate 4. When evidence conflicts,
prefer confirmed business meaning, explain the trade-off, and do not hide
source-feasibility limitations. For each user-facing choice, summarize the
recommended option and why the other options were not selected, using visuals or
PII-safe examples when they help the user compare the consequences.

### 7. Persist material decisions

After a modeling choice is accepted, persist it only when it resolved a genuine
tension or real gap: conflicting source or reference evidence, intentional
divergence from an industry standard, or a modeling choice with viable rejected
alternatives. This is a strict materiality threshold.

Anti-pattern: never log routine confirmations, successful validations, or
mechanical choices. If it was not a real decision with at least one rejected
alternative, do not create a record.

For a material decision, run:

```powershell
kairos-ontology decision new --title "<concise>" --domain <domain> --source <evidence-resource> ...
```

Then fill the generated record body with Context/Finding, Decision, an
`Alternatives rejected` table with at least one row, Consequences, and
`Why future maintainers need this`. Set a `materiality` tag and `confidence`.
Move `decision_state` to `Accepted`, with sources, once the decision is
confirmed.

In interactive mode, propose the decision and its materiality, then confirm with
the user before writing. In fleet mode, write with `generated.by` set to the
agent actor, recording rationale, confidence, and evidence references.

The PR human-review gate is the real materiality backstop: Decision Log records
are reviewed like code.

### 8. Prepare and validate the patch

Before writing anything, snapshot the workspace scope:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology guard-scope --snapshot
```

Keep the printed token — it is compared at step 9.

Create a reviewable unified diff limited to `model/ontologies/<domain>.ttl`
and run Gate 5. Summarize added, changed, and intentionally omitted terms plus
their evidence.

In interactive mode, show the validated diff and wait for final approval. In
fleet mode, record the AI approval with rationale, confidence, and evidence.

### 9. Apply, register, and verify

Apply only the approved diff. Reread and parse the saved ontology and repeat
Gate 5.

Then register the domain in the hub catalog — **only after the patch is on disk,
never before**:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology init --domain <domain> --company-domain <company-domain>
```

This is the registration step, and nothing else performs it: `init --domain` is
the only command that maps a domain ontology in `ontology-hub/catalog-v001.xml`.
Skip it and the patch parses and validates while remaining unresolvable through
the catalog. Run it from the repo root — the directory that contains
`ontology-hub/`.

The ordering is load-bearing. When `model/ontologies/<domain>.ttl` is absent this
command *creates a starter ontology* in its place, so running it first hands you
a scaffold you would then have to overwrite. Once the file exists it is left
untouched.

`--company-domain` is required by the command but is a fallback, not a free-text
parameter: the catalog entry uses the IRI declared by the `owl:Ontology` in the
`.ttl` whenever one is declared, and `--company-domain` only supplies
`https://<company-domain>/ont/<domain>` when none is. Take the value from the
hub's own existing ontology IRIs — the `uri name=` entries already in
`catalog-v001.xml`, or the `owl:Ontology` line of a sibling
`model/ontologies/*.ttl`. Never invent one.

On an already-initialized hub the command is idempotent. Every scaffold write is
guarded by an "already exists, and no `--force`" check, so the one file it
changes is `catalog-v001.xml`. Expect roughly fifteen `⏭  … already exists` lines
closing with `✅ Ontology hub initialized!` — that is the guarded no-op reporting
itself, not setup being re-run. Never add `--force` to make the output look
busier: that overwrites the patch you just applied.

Finally confirm the workspace guard passes:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology guard-scope --check-since <token> --allow "*model/ontologies/<domain>.ttl" --allow "*catalog-v001.xml" --allow "*model/ontologies/_master.ttl"
```

Those three globs are the whole legitimate footprint of one domain: the ontology
patch, the catalog entry the registration step writes, and `_master.ttl` when the
hub lists its domain imports there. Each one carries a leading `*` because
`guard-scope` reports paths relative to the **git repo root**; a hub-relative
glob matches nothing in the standard `ontology-hub/` layout.

A non-zero exit names every path that changed outside that scope — treat that as
blocking, not a self-report. If validation, registration, or the guard fails,
restore the pre-patch content and report the failure.

### 10. Hand off

Report the accepted slice and remaining questions. The next step is
**kairos-design-mapping**, which authors one closed YAML `EntityBinding` per
source relation or contracted dbt model and canonical entity. Do not generate
bindings or dbt artifacts in this skill.

## Quick amendments

A minor amendment may use a shortened loop only when it changes at most three
existing properties, introduces no class or import, and does not alter domain
boundaries. Source completeness, PII safety, confirmation/fleet rules, bounded
diff review, and ontology integrity still apply.

## Anti-patterns

- Designing from general knowledge before reading source evidence.
- Treating a physical table as proof of a canonical class.
- Copying source columns wholesale into the ontology.
- Treating TMDL or Gold demand as business authority.
- Exposing raw sample values to the LLM or committed files.
- Writing unconfirmed or unparsed Turtle.
- Combining ontology design with EntityBinding or generated SQL authoring.
- Writing any file outside the guarded scope of step 9: the approved ontology
  patch, the catalog entry `init --domain` registers, and `_master.ttl`.
- Leaving a new domain unregistered — a `.ttl` with no `catalog-v001.xml` entry
  is invisible to every catalog-resolved import.

## Related skills

- **kairos-design-discovery** — confirm business context and terminology.
- **kairos-design-source** — import/analyse source vocabularies and redact samples.
- **kairos-design-mapping** — author v5 YAML entity bindings.
- **kairos-develop-dbt-transformation** — author ordinary contracted dbt models
  for relational or grain-changing logic.
- **kairos-toolkit-ops** — explicitly update selected reference models.
