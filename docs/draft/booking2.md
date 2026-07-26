# Booking continuation session - toolkit improvements

**Date:** 2026-07-26  
**Status:** Draft session notes  
**Scope:** Toolkit v4.7.0rc7, Qargo-to-Booking mapping, strict validation, and
Booking Silver bound confirmation

This document records toolkit defects and workflow improvements observed while
continuing the Booking vertical slice after the initial `bookingsession.md`.
It focuses on new rc7 findings and does not repeat the earlier report unless the
behavior changed materially.

## Executive summary

The Booking and Transport Order mappings were completed successfully:

- `qargo.bookings` binds to `dcsa:Booking`;
- `qargo.orders` binds to `dcsa:Shipment`;
- focused mapping validation passes;
- mapping-scoped readiness reports `READY`; and
- the objective status scan reports both classes as bound and release-eligible.

The lifecycle still cannot advance through Silver bound confirmation because
different toolkit components disagree about managed imports, and the focused
Silver validator fails on Windows before it can evaluate the annotations.

Highest-priority improvements:

1. make managed-import planning, validation, claims checking, and projection use
   one activation decision;
2. fix Windows file-path handling in `validate-silver-ext`;
3. use the hub catalog consistently without requiring repeated `--catalog`;
4. make `status` agree with binding analysis about projected classes;
5. improve source-sample masking so UUIDs and datetimes are not classified as
   phone numbers; and
6. rank competing source-column candidates instead of suggesting several columns
   for one scalar target property.

## What worked well

- Table-scoped transformation readiness correctly treated unrelated Party
  contract-identity warnings as non-blocking for Booking mapping.
- `validate-mapping --domain booking` accepted the named v2 mapping structure and
  resolved all source and target IRIs.
- Mapping-scoped `check-projection` became green after the ontology closure and
  explicit catalog were supplied.
- Adding the direct BSP Party import correctly satisfied managed import
  completeness for local `booking:hasCustomer -> bsp:TradeParty`.
- The objective scan correctly changed Booking and Shipment from aspirational to
  bound after the Qargo mappings were authored.
- Runtime contract identity evidence is now a warning for ordinary mapping and
  Silver design rather than a bootstrap blocker. Strict projection and release
  can remain blocked until warehouse evidence exists.

## 1. Managed-import planner and Silver evaluator disagree - BLOCKER

### What happened

The managed planner reported:

```text
booking: in sync
```

It intentionally retained BSP Documents through the logistics Booking
data-domain profile. Party's IMO and MMT Party imports were also previously
required to complete its managed closure.

The Silver-scoped evaluator then blocked on:

```text
extra import https://www.kairosflow.ai/ont/bsp/documents
extra import https://www.kairosflow.ai/ont/imo/party
extra import https://www.kairosflow.ai/ont/mmt/party
```

The planner cannot remove these imports because it considers them required, while
the evaluator cannot pass because it considers them extra.

### Why this is a problem

- The owning synchronization command reports success but cannot produce a state
  accepted by the downstream gate.
- Hand-editing the managed block would violate ownership rules and may break the
  complete reference-model closure.
- The same hub is simultaneously "in sync" and blocked by sync drift.
- Silver bound confirmation cannot advance even though mappings are complete.

### Recommended fix

- Create one shared `ModuleActivationDecision` result used by:
  - `claims-to-silver-ext`;
  - `check-claims`;
  - managed import completeness;
  - `check-projection --scope silver`; and
  - `status`.
- Record activation reasons per module:
  `approved claim`, `data-domain profile`, `closure dependency`, or `authored
  local dependency`.
- Treat an import as extra only when no shared activation reason exists.
- Include the retaining reason and claim/profile IDs in every drift diagnostic.
- Add regression coverage for:
  - a module retained only by a data-domain profile;
  - a module referenced only by deferred claims;
  - a transitive closure dependency required by another active module; and
  - a local object property whose range belongs to an imported module.

## 2. `validate-silver-ext` treats a Windows drive letter as a URL scheme - BLOCKER

### What happened

Both Booking and Party focused Silver validation failed before semantic checks:

```text
G:\...\model\shapes\kairos-ext-shapes.shacl.ttl does not look like a valid URI
<urlopen error unknown url type: g>
```

Passing `--catalog catalog-v001.xml` did not change the result.

### Why this is a problem

- The validator cannot run on a normal Windows checkout outside drive `C:`.
- The diagnostic is unrelated to the actual Silver extension.
- Users may incorrectly attempt to modify valid SHACL or Silver TTL.
- The focused validator cannot provide `design-valid` evidence.

### Recommended fix

- Convert local `Path` values to `file://` URIs with `Path.as_uri()` before
  passing them to RDFLib or URL-loading APIs.
- Keep filesystem-path and ontology-IRI types distinct in validator interfaces.
- Never feed raw Windows paths into `Graph.parse()` as a public identifier.
- Add Windows tests for `C:\`, `G:\`, spaces, and non-ASCII path segments.
- Ensure diagnostics identify whether the failed value was a filesystem path,
  catalog URI, ontology IRI, or remote URL.

### Acceptance test

From a repository on `G:\work\hub`:

```powershell
uv run kairos-ontology validate-silver-ext --domain booking `
  --catalog catalog-v001.xml
```

must load the local shape file and return semantic validation results rather
than `unknown url type: g`.

## 3. Automatic catalog selection produces false incomplete-closure failures - HIGH

### What happened

After the missing BSP Party import was fixed, validation without an explicit
catalog still reported:

```text
Ontology closure is incomplete
```

The same command passed when run with:

```text
--catalog catalog-v001.xml
```

This matches the earlier Party finding that automatic resolution selected a
reference-model catalog before the hub catalog.

### Recommended fix

- Prefer the nearest hub-root `catalog-v001.xml`.
- Chain its delegated catalogs through the canonical resolver rather than
  replacing it with a reference-model catalog.
- Print the selected catalog and selection source in every validation and
  readiness command.
- If multiple catalogs are plausible, fail with an actionable ambiguity before
  attempting closure loading.
- Add parity tests proving explicit and automatically discovered hub catalogs
  resolve the same closure hash.

## 4. `status` says bound while warning that the same classes are not projected - BUG

### What happened

The status scan emitted warnings that `Address`, `Contact`, `TradeParty`,
`Booking`, and `Shipment` were not projected or claimed. In the same JSON scan:

- all five classes appeared in `facts.bound_classes`;
- both Silver domains were `done`; and
- both domains reported `release_eligible: true`.

Booking and Shipment are explicitly claimed in `booking-silver-ext.ttl`.

### Why this is a problem

The command gives mutually exclusive guidance:

- machine-readable facts say the classes are bound;
- console warnings say their mappings are ignored.

Humans and orchestration cannot know which result is authoritative.

### Recommended fix

- Generate console warnings from the same `BindingAnalysis` result used for
  `facts.bound_classes`, `aspirational_classes`, and `release_eligible`.
- Include domain, mapping resource, activation source, and binding authority in
  warning details.
- Suppress "not projected" warnings for classes classified as bound.
- Add an invariant test: a class cannot be both `bound_classes` and
  `mapping target ignored` in one scan.

## 5. Sample masking misclassifies UUIDs and datetimes as phone numbers - QUALITY/DX

### What happened

Bronze vocabulary examples included values such as:

```text
<redacted kind=phone source=bookings.booking_date datatype=datetime>
<redacted kind=phone source=bookings.booking_id datatype=varchar(max)>
<redacted kind=phone source=orders.date datatype=datetime>
```

The source metadata already identifies the first and third values as datetimes
and the identifier columns as UUID-like values.

### Why this is a problem

- Mapping evidence becomes less useful at the exact confirmation checkpoint where
  examples are mandatory.
- False PII classifications obscure real PII warnings.
- A user cannot distinguish a masking defect from sensitive source data.

### Recommended fix

- Apply declared datatype and format hints before value-shape PII heuristics.
- Classify ISO dates/datetimes and canonical UUIDs before phone detection.
- Require stronger phone evidence: digit density, plausible length, separators,
  and exclusion of date/UUID patterns.
- Preserve a non-sensitive masked structural example, such as
  `2026-**-**T**:**:**` or `********-****-****-****-************`.
- Add regression fixtures for UUIDs, timestamps, container numbers, order
  references, postal codes, and actual phone numbers.

## 6. Alignment claims suggest multiple source columns for one scalar property - QUALITY

### What happened

The migrated Booking claims suggested all of these as evidence for
`dcsa:carrierBookingReference`:

- `booking_id`;
- `booking_name`;
- `booking_reference`; and
- `orders.destination_reference_number`.

Profiling showed materially different semantics:

- `booking_name` is unique and business-facing;
- `booking_id` is a technical UUID;
- `booking_reference` has only four distinct values across 1,000 rows; and
- `destination_reference_number` contains PO/customer references.

The interactive mapping correctly selected only `booking_name`.

### Recommended fix

- Rank candidate source columns per target property instead of emitting an
  undifferentiated many-to-one suggestion.
- Use uniqueness, nullability, distinct ratio, format, table grain, description,
  and sample-shape compatibility in ranking.
- Mark competing candidates as `alternative`, `technical identity`, or
  `semantically conflicting`.
- Require an explicit composition rule before allowing several source columns to
  populate one scalar target.
- Flag a candidate when the source column comes from a table mapped to a class
  outside the target property's domain.

## 7. Phase-log drift does not understand contracted virtual sources - DX

### What happened

The objective status scan reported completed contracted transformations as
`not-started`, while their SQL, contract YAML, tests, and synchronized
vocabularies exist. It also reported stale xrefs from older source layouts.

The source phase remained `in-progress` because generated virtual vocabularies
are intentionally not affinity-analyzed, and Power BI planning packs are not
bronze source vocabularies.

### Recommended fix

- Give contracted virtual sources a dedicated objective status classifier based
  on discovered dbt contract, SQL, tests, synchronization hash, and evidence.
- Do not require source-affinity analysis for generated contract vocabularies.
- Distinguish physical sources, contracted virtual sources, and planning-only
  evidence in the status schema.
- Add an xref migration/normalization command for known layout changes.
- Report stale phase-log paths separately from current lifecycle readiness.

## 8. Optional MDM anchor warnings appear in an unrelated Silver path - DX

### What happened

`check-claims --domains booking` warned that Booking had broad approved class
claims but no `mdm_anchor`. The hub was running the ordinary Booking Silver
workflow, not the opt-in MDM profile.

### Recommended fix

- Emit MDM anchor diagnostics only when:
  - the MDM profile is requested;
  - MDM policy exists for the domain; or
  - a release profile explicitly requires MDM.
- Otherwise classify the message as an optional advisory section with no warning
  icon and no remediation pressure.
- Make `--no-mdm-anchor` unnecessary for ordinary medallion workflows.

## 9. Lifecycle evidence persistence lags successful scoped checks - DX

### What happened

Focused syntax, SHACL, mapping validation, and mapping readiness passed, but the
monotonic lifecycle remained:

```text
authored -> design-valid unknown -> bound-valid unknown
```

The checks are non-writing by design, so a successful result is not persisted as
versioned lifecycle evidence.

### Recommended fix

- Add an explicit `--evidence-output` option to deterministic checks.
- Persist schema version, toolkit version, command options, scope, catalog,
  accelerator, closure hash, artifact hashes, and result.
- Let `status` consume only current hash-matching evidence.
- Keep the default read-only behavior, but let skills request durable evidence
  without reconstructing reports manually.
- Never promote `bound-valid` from artifact presence or a phase-log checkbox.

## Suggested priority

| Priority | Finding | Impact |
|---|---|---|
| P0 | Managed-import planner/evaluator disagreement | Blocks Silver bound confirmation |
| P0 | Windows path handling in `validate-silver-ext` | Prevents focused Silver validation |
| P1 | Automatic catalog selection | Causes false closure failures |
| P1 | Status binding/warning contradiction | Produces mutually exclusive machine guidance |
| P1 | Sample masking false positives | Weakens evidence and privacy diagnostics |
| P1 | Competing scalar mapping candidates | Risks semantically incorrect mappings |
| P2 | Contracted virtual-source status model | Creates persistent lifecycle drift |
| P2 | Optional MDM warning scope | Adds unrelated governance noise |
| P2 | Durable lifecycle evidence output | Prevents successful checks advancing state |

## Recommended regression scenario

Add one Windows end-to-end scenario that:

1. checks out a hub on drive `G:`;
2. imports Booking, BSP Party, and the logistics profile through the hub catalog;
3. defines a local `hasCustomer` relationship to `bsp:TradeParty`;
4. maps physical `bookings` and `orders` tables to imported Booking and Shipment;
5. runs focused mapping and Silver validators;
6. runs mapping- and Silver-scoped readiness;
7. runs `status`; and
8. asserts:
   - no raw drive path is interpreted as a URL;
   - the automatic and explicit catalogs produce the same closure;
   - planner and evaluator agree on every active module;
   - bound classes do not emit "not projected" warnings; and
   - status facts match the scoped readiness result.

## Session outcome

The Booking mapping itself is complete and locally valid. Strict ontology syntax
and SHACL validation pass with the explicit hub catalog. The objective scan sees
Booking and Shipment as bound.

The hub is intentionally paused before Silver bound completion because weakening
the gate, removing planner-owned imports, or accepting degraded semantics would
hide toolkit defects rather than solve them.
