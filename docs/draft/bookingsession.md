# Booking design session — toolkit findings and DX improvements

**Date:** 2026-07-26  
**Status:** Draft session notes  
**Scope:** Toolkit v4.7.0rc6, Booking domain design, claim generation, validation,
and Party dbt projection pre-flight

This document records toolkit bugs, workflow friction, and design-experience
improvements observed while starting the CLdN Booking domain. It is advisory and
does not replace formal issues or design decisions.

## Executive summary

The reference-model-first flow worked, but several deterministic gates and generated
artifacts disagreed about the same evidence. The highest-impact findings are:

1. dbt projection has a bootstrap deadlock: warehouse evidence is required before the
   dbt project needed to produce that evidence can be generated;
2. `propose-alignment` can report success and write a large registry after every LLM
   call failed;
3. business aliases from discovery conformance are not used to resolve reference
   classes, causing `TransportOrder` to be incorrectly merged into `Booking`;
4. relationship candidates are emitted per column rather than per semantic cluster,
   creating 50 decisions from roughly six actual relationships; and
5. the fresh-domain scaffold omits ontology metadata required by the toolkit's own
   modeling conventions; and
6. managed-import synchronization and strict checking disagree about imports referenced
   only by deferred claims;
7. `check-claims --strict` reports downstream mapping failures after claim curation is
   complete; and
8. the mandatory unscoped Mapping-readiness gate blocks Booking on unrelated Party
   transformation contracts even though the Booking table scope is green.

## What worked well

- `check-inventory --domains booking --explain-scope` kept unrelated inventory
  failures non-blocking.
- Qargo affinity analysis clearly identified `bookings` and `orders` as Booking-domain
  evidence.
- The discovery conformance artifact preserved the prior business decision that
  `dcsa:Shipment` is called "Transport Order / Order / Dossier" at CLdN.
- `decide-claims` provided a safe dry-run and canonical write path for claim decisions.
- `claims-to-silver-ext` created managed import and `silverInclude` blocks without
  overwriting authored TTL.
- Quick validation passed managed-import completeness, Turtle syntax, and SHACL after
  the accelerator and catalog were supplied explicitly.

## 1. Projection bootstrap deadlock for contract identity evidence — BLOCKER

### What happened

Party dbt projection was blocked by:

```text
identity.contract-unverified:
no actual passing uniqueness/non-null evidence matches the current canonical
contract content hash
```

The required `manifest.json` and `run_results.json` can only be produced by running
the relevant dbt models and tests. The generated dbt project is itself unavailable
because `check-projection` blocks generation on the missing evidence.

### Why this is a problem

This reverses the dependency order:

```text
generate dbt project -> run tests -> capture runtime evidence -> release
```

becomes:

```text
runtime evidence -> generate dbt project
```

There is no safe rc6 override, and inventing evidence would violate the identity
contract.

### Recommended fix

- Permit ordinary, non-strict dbt generation with contract identity marked
  `unverified` and all output explicitly `review-only`.
- Keep `project --strict`, runtime validity, and release eligibility blocked until
  matching warehouse evidence is captured.
- Ensure generated manifests and reports clearly distinguish:
  `schema-valid`, `bound`, `data-valid`, and `release-eligible`.
- Add a regression test for the clean bootstrap path from authored contracts to the
  first runnable dbt package.

## 2. `propose-alignment` writes success-shaped output after total LLM failure — BUG

### What happened

Both Booking table calls failed because the configured `gpt-5.5` endpoint rejected
`temperature=0.1`. The command still:

- exited with code `0`;
- printed `Proposal complete`;
- wrote `booking-claims.yaml`; and
- produced 200 proposed fallback claims.

`check-claims` then described the registry as valid, complete, and current.

### Why this is a problem

Transport/provider failure is converted into plausible governance output. A designer
could curate a registry that never received semantic alignment.

### Recommended fix

- Exit non-zero when every table-level LLM call fails.
- Never print `Proposal complete` when no semantic call succeeded.
- Persist table-level generation status and provider errors in registry metadata.
- Make `check-claims` distinguish structural completeness from semantic-generation
  completeness.
- Require an explicit `--allow-fallback-registry` flag if fallback-only output is ever
  desirable.

## 3. Model/provider capability mismatch is discovered after billing starts — BUG/DX

### What happened

The configured alignment model was `gpt-5.5`, but the provider supports only its
default temperature. The toolkit sent `temperature=0.1`, causing every request to fail.
A forced rerun with `gpt-5.4-mini` succeeded.

### Recommended fix

- Maintain model capability metadata for temperature, reasoning controls, and other
  request parameters.
- Omit unsupported parameters instead of sending hard-coded values.
- Run a cheap provider/model capability check before the cost banner and table fan-out.
- Print the effective role-specific model and why it was selected.
- Treat provider incompatibility as a pre-flight failure, not a table alignment result.

## 4. Discovery rename/conformance evidence is not used for class anchoring — HIGH

### What happened

The affinity report used the business entity name `TransportOrder`. No installed class
has that exact name, so alignment fell back to the nearest class, `Booking`, and fused:

- `qargo.bookings` with candidate entity `Booking`; and
- `qargo.orders` with candidate entity `TransportOrder`.

The existing discovery conformance artifact already stated:

```text
dcsa:Shipment -> conforms-with-rename -> Transport Order / Order / Dossier
```

After manually correcting the affinity anchor to `Shipment`, the grain conflict
disappeared.

### Recommended fix

- Load `integration/discovery/core-concepts-conformance.yaml` before alignment.
- Resolve `rename_to` values and glossary aliases to canonical class URIs.
- Store `likely_entity_uri` alongside the human-readable `likely_entity`.
- Prefer URI anchors over nearest-name fallback.
- When a rename is user-confirmed, treat it as higher authority than a new LLM class
  guess.

## 5. Nearest-anchor fallback fused distinct source grains — HIGH

### What happened

The first successful Booking registry mapped both source tables to `dcsa:Booking`.
`check-claims` correctly detected the grain conflict afterward.

### Recommended fix

- Detect multiple candidate entities before emitting a shared class claim.
- Fail the alignment table as unresolved instead of silently choosing the nearest class.
- Surface a compact class-resolution checkpoint:

| Source table | Business entity | Candidate URI | Resolution |
|---|---|---|---|
| `bookings` | Booking | `dcsa:Booking` | exact |
| `orders` | Transport Order | `dcsa:Shipment` | discovery rename |

- Do not create property claims until the table-level class anchor is resolved.

## 6. Imported claims can be emitted without resolvable URIs — BUG

### What happened

After correcting the class anchor, the registry emitted:

- `booking-shipment` without `class_uri`;
- `booking-shipment-hastransportdocument` without `property_uri`; and
- three cross-domain property claims without `property_uri`.

The rationale named valid reference-model resources, but the machine identifier was
absent. These claims could not be approved until repaired or deferred.

### Recommended fix

- If `origin: imported`, require a resolvable URI before writing the claim.
- Resolve the class/property name against the selected inventory deterministically.
- Emit unresolved suggestions as a separate `unresolved_anchor` record, not a claim.
- Make `check-claims` fail structural validity for imported `claim`/`specialize`
  records missing their URI, even before `--strict`.

## 7. Cross-domain property suggestions ignore domain ownership — QUALITY

### What happened

Booking alignment proposed claims for:

- `CargoItem.hasCommodity`;
- `Commodity.commodityDescription`; and
- `CustomsDeclaration.declarationType`.

The evidence columns exist in `qargo.orders`, but Cargo and Customs own those concepts.
They were explicitly deferred.

### Recommended fix

- Use accelerator `owns` / `does_not_own` boundaries during property proposal.
- Label cross-domain evidence as a handoff rather than a Booking claim.
- Generate a reusable evidence link for the owning domain so the column is not lost.
- Show cross-domain recommendations separately from in-domain claim candidates.

## 8. Relationship candidates are emitted per column, not per relationship — DX

### What happened

The Booking registry emitted 50 relationship candidates, but they represented roughly
six semantic decisions:

1. creator/user audit field;
2. order customer;
3. connection-start location;
4. connection-end location;
5. warehouse location; and
6. customs pre-notification location.

For example, every address component received a separate `hasLocation` candidate.

### Why this is a problem

The designer must review dozens of duplicate rows, obscuring the actual role and
cardinality decision.

### Recommended fix

- Cluster candidates by source table, column prefix/role, target class, and cardinality.
- Emit one candidate with all contributing columns.
- Preserve the scalar claims underneath for mapping and passthrough decisions.
- Give each cluster a stable ID so decisions survive alignment refreshes.
- Show changed columns on refresh instead of regenerating the whole decision.

## 9. Relationship semantics contained avoidable false positives — QUALITY

### What happened

- `created_by_user` was proposed as `hasBookingParty`.
- `created_by_customer` was proposed as `hasBookingParty`.
- generic connection-end address fields were proposed as `hasPortOfDischarge`, even
  though no port evidence existed.

The approved decisions were:

- keep creator fields as audit/passthrough evidence;
- use `orders.customer/customer_id` for the governed Party relationship;
- use `hasPlaceOfReceipt` for connection start;
- use `hasPlaceOfDelivery` for connection end;
- keep warehouse and customs locations as distinct roles; and
- use local `hasCustomsPreNotificationLocation` as a sub-property of `hasLocation`.

### Recommended fix

- Treat `created_by_*`, `updated_by_*`, and similar fields as audit actors by default.
- Require an entity identifier before proposing an object relationship.
- Make typed location relationships role-aware:
  `origin/start -> receipt`, `destination/end -> delivery`;
  use port-specific properties only with explicit port evidence.

## 10. Fresh-domain scaffold omits required ontology metadata — BUG

### What happened

`claims-to-silver-ext` scaffolded `booking.ttl` with an ontology label and foundation
import, but without:

- `rdfs:comment`; and
- `owl:versionInfo`.

Both are mandatory under the toolkit modeling conventions. They had to be added by hand.

### Recommended fix

- Make the generated skeleton valid against the toolkit's own ontology checklist.
- Include namespace prefixes, label, comment, and initial version.
- Add a packaging/regression test asserting every scaffolded ontology passes the same
  metadata checks as a hand-authored ontology.

## 11. Scaffold output says "in sync" when files were newly created — DX

### What happened

The first `claims-to-silver-ext` run created the Booking ontology, Silver extension,
and activation inventory, but output only:

```text
booking: in sync
```

Because the files were untracked, `git diff -- <files>` also showed nothing.

### Recommended fix

- Report `created`, `updated`, and `unchanged` separately.
- List every created/updated path.
- Include counts and a concise managed-versus-authored explanation.
- Suggest `git status --short` when files are newly created.

## 12. Accelerator ambiguity recurs across otherwise scoped commands — DX

### What happened

Both `check-projection` and `validate` failed until `--accelerator logistics` was
supplied, despite the hub using the logistics blueprint and Booking inventory.

### Recommended fix

- Persist `accelerator = "logistics"` under `[tool.kairos]`.
- Let commands use that setting consistently.
- If the active domain maps unambiguously to one accelerator, show the inferred choice.
- Keep ambiguity as an error only when multiple accelerators genuinely remain possible.

## 13. `check-inventory` reports "(none matched)" and then says the domain is ready — DX

### What happened

The Booking scoped check printed:

```text
Active-domain readiness: (none matched)
...
Active-domain inventories are ready
```

The exit code was green because the required accelerator inventories were current, but
the text makes it unclear whether Booking was actually evaluated.

### Recommended fix

- Print the resolved domain profile and inventory set.
- Distinguish:
  `matched direct inventory`, `matched accelerator profile`, and `no profile found`.
- Do not use `(none matched)` in a successful scoped result.

## 14. Registry ownership warning disagrees with the accelerator registry — BUG/DX

### What happened

`check-claims --domains booking` warned:

```text
registry domain not found in data-domains.yaml (ownership unverified)
```

The logistics `data-domains.yaml` clearly contains `id: booking`.

### Recommended fix

- Use the same accelerator resolution path as inventory and managed-import planning.
- Include the actual `data-domains.yaml` path in diagnostics.
- Add a test for nested `groups[].domains[]` registries.

## 15. Validation requires manual report duplication — DX

### What happened

The validator writes JSON, while the skill separately reconstructs Markdown, saves it,
and updates a phase log. This duplicates result formatting and can drift.

### Recommended fix

- Add `validate --format markdown --output <path>`.
- Include exact command options, toolkit version, catalog, accelerator, and scope.
- Optionally emit a state-update proposal fragment for the phase skill to append.

## 16. Toolkit synchronization and toolkit upgrade are easy to confuse — DX

### What happened

`sync-dbt-contracts` regenerated managed vocabularies with an rc6 provenance stamp.
This looked like a toolkit upgrade, but it only synchronized artifacts using the already
pinned rc6 environment.

### Recommended fix

- Use distinct language:
  - `toolkit upgrade`: dependency version changed;
  - `managed-file refresh`: skills/instructions changed;
  - `contract synchronization`: generated vocabulary changed.
- Print both `running toolkit` and `artifact previous generator` when rewriting.

## 17. Managed-import planner and checker disagree on deferred claims — BUG

### What happened

After all Booking claims were decided, `claims-to-silver-ext --domains booking
--accelerator logistics` reported:

```text
booking: in sync
```

The immediately following `check-claims --domains booking --strict` reported sync drift
because the managed block still imported BSP Documents. All BSP Documents claims were
deferred, not approved.

### Why this is a problem

The generator and checker apply different activation semantics to deferred claims. The
owning command cannot repair the condition it reports as synchronized, leaving users
tempted to hand-edit a managed block.

### Recommended fix

- Define one shared predicate for whether a claim activates a reference module.
- Use that predicate in both `claims-to-silver-ext` and `check-claims`.
- Exclude deferred claims from projection imports unless deferred evidence explicitly
  requires a non-projecting documentation import.
- Add a regression test for a domain whose only claims against a module are deferred.
- When disagreement occurs, print the claim IDs that retained the disputed module.

## 18. Strict claim checking conflates curation with downstream mapping — DX/BUG

### What happened

After Booking reached 0 proposed claims, `check-claims --domains booking --strict`
continued to exit non-zero because:

```text
booking: 0/2 tables mapped
qargo.bookings
qargo.orders
```

The unmapped-table result is the expected handoff to `kairos-design-mapping`; it does not
mean claim governance is unfinished. The same command also included claim/projection sync
diagnostics, making three lifecycle concerns look like one failed curation gate.

### Why this is a problem

The domain skill defines `check-claims --strict` as its completion gate, but the command
can fail after every claim decision is complete because later Mapping work has not started.
Designers cannot distinguish “claim curation incomplete” from “next lifecycle phase
pending” using the exit code.

### Recommended fix

- Split the command into independently reported sections and exit decisions:
  `registry-valid`, `curation-complete`, `source-mapped`, and `projection-sync`.
- Make the domain claim-curation gate evaluate only registry validity, freshness, and
  undecided claims.
- Keep source-table coverage as a Mapping readiness result with
  `owner_skill: kairos-design-mapping`.
- Keep managed import drift as a synchronization result with its own owner.
- Add a machine-readable `curation_complete: true` field even when later sections block.

## 19. Unscoped transformation readiness blocks unrelated Booking mapping — BLOCKER

### What happened

The Booking-specific readiness check was green:

```text
check-transformation-readiness --stage mapping
  --table qargo.bookings
  --table qargo.orders

status: ready
assessment_required: false
candidates: []
```

The Mapping skill then required the same command without table scope. That unscoped check
failed on two Party-only virtual-source contracts:

```text
contract:int_qargo_billing_address_conformed
contract:int_qargo_contact_conformed
identity.contract-unverified
```

Neither contract supplies or replaces `qargo.bookings` or `qargo.orders`, but the hard
gate prohibited creating `qargo-to-booking.ttl`.

### Why this is a problem

Readiness is computed hub-wide while the Mapping workflow is explicitly scoped to one
source system and selected tables. An unrelated domain's warehouse evidence can therefore
block independent direct mappings. The CLI supports repeatable `--table`, but the skill
mandates an unscoped invocation, creating a policy/tool mismatch.

### Recommended fix

- Require Mapping to pass the selected source tables via repeatable `--table`.
- Derive that scope from the confirmed table-alignment agenda and persist it in the phase
  log.
- Evaluate only transformation candidates whose replacement or dependency closure
  intersects those tables.
- Report unrelated blocked contracts as non-blocking visibility diagnostics.
- Add a regression test where Party contracts are blocked while direct Booking tables are
  mapping-ready.
- Reserve an unscoped gate for hub-wide release checks, not a single-domain mapping edit.

## Design-experience recommendations

### A. Add one deterministic `design preflight` command

Return a machine-readable packet containing:

- active domain and accelerator;
- reference inventory freshness;
- discovery/conformance status;
- source and TMDL evidence;
- claims state and unresolved anchors;
- relationship clusters;
- source-completeness questions; and
- exact owner skill for every blocker.

This would replace repeated filesystem scans and reduce inconsistent routing.

### B. Separate observation, proposal, and approval in every artifact

Every generated registry item should explicitly state:

- machine observation;
- LLM proposal status and model result;
- deterministic URI resolution;
- human/AI approval;
- evidence hash; and
- owning domain.

Provider failure must never become approval-shaped output.

### C. Make checkpoints cluster-oriented

Present decisions at business scale:

- one table-to-entity decision;
- one location-role cluster;
- one Party relationship;
- one technical/audit group; and
- one cross-domain handoff group.

Keep column-level evidence available behind each cluster, but do not force one chat
decision per address component.

### D. Use discovery conformance as a first-class alias registry

The confirmed mapping:

```text
Transport Order / Order / Dossier -> dcsa:Shipment
```

should flow automatically through affinity analysis, alignment, claims, mappings,
reports, and BI labels. Designers should not repeatedly rediscover or manually repair it.

### E. Support safe incremental domain scaffolding

A fresh-domain action should atomically and visibly:

1. create the phase log;
2. create the ontology skeleton with complete metadata;
3. create the managed Silver extension;
4. update `_master.ttl`;
5. update the README domain table;
6. validate syntax; and
7. report created/updated paths.

Authored content must remain outside managed blocks and survive all refreshes.

### F. Decouple generation readiness from release readiness

The design loop needs runnable artifacts before runtime proof exists. Generation should
be allowed with explicit review-only status; strict publication must remain fail-closed.
This preserves governance without creating bootstrap deadlocks.

## Suggested issue priority

| Priority | Finding |
|---|---|
| P0 | Projection bootstrap deadlock for contract identity evidence |
| P0 | Success-shaped alignment output after total LLM failure |
| P1 | Discovery aliases not used for class anchoring |
| P1 | Imported claims emitted without resolvable URIs |
| P1 | Fresh-domain scaffold violates required ontology metadata |
| P1 | Registry ownership lookup misses Booking |
| P1 | Managed-import planner/checker disagreement for deferred claims |
| P1 | Unscoped transformation gate blocks unrelated Booking mapping |
| P2 | Relationship candidates need semantic clustering |
| P2 | Model/provider capability pre-flight |
| P2 | Persistent accelerator configuration |
| P2 | Strict claim check conflates curation with downstream mapping |
| P3 | Clearer synchronization, scaffold, inventory, and validation output |

## Session outcome

The Booking session successfully established:

- `qargo.bookings -> dcsa:Booking`;
- `qargo.orders -> dcsa:Shipment`, using the CLdN business term "Transport Order";
- local Shipment extensions `orderNumber`, `orderStatus`, and `orderDate`;
- local Shipment-to-Party relationship `hasCustomer`;
- a customs pre-notification Location relationship;
- managed Booking imports and Silver inclusion;
- master ontology and README registration; and
- passing Turtle syntax and SHACL validation.

Claim governance is complete: 151 claims are approved, 16 cross-domain or unresolved
claims are deferred, 9 claims are rejected, and no proposed claims remain. Booking
mapping remains the next lifecycle step, but its current skill gate is blocked by
unrelated Party contract identity evidence despite a green Booking table-scoped check.
