# DD-155: Managed Import Completeness is mode-independent and gates registration

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** `run_validation` (all modes), `init --domain` registration, kairos-design-domain skill
**Implementation:** `src/kairos_ontology/core/validator.py` (managed-import preflight),
`cli/validation.py` (`--syntax` help), `cli/setup.py` (`_registration_import_gate`, init `--degraded`),
`.github/skills/kairos-design-domain/SKILL.md` + scaffold copy

### Context

Issue #426: a domain missing a blueprint-required managed `owl:imports` sailed through four green gates and
was registered anyway — silently unactivated. Two structural causes: (1) the validator's Managed Import
Completeness check was gated on `if do_shacl or do_consistency:`, so Gate 5's inner-loop
`validate --syntax` never ran it — an accidental mode split (the check is static rdflib parsing, no
pyshacl), while the sibling `_master.ttl` import-sync check (#393) is deliberately unconditional; and
(2) `init --domain` — the only registration path — performed no import check at all before writing the
catalog entry and syncing `_master.ttl`.

### Decision

Three coordinated parts:

1. **Validator (mode-independent check).** The managed-import preflight runs in every mode, including
   `--syntax`, mirroring the unconditional `_master.ttl` check's precedent. The only remaining gate is
   *resolvability*: when reference models cannot be resolved (no ref-models dir, or no accelerator module
   config — every case where `build_reference_module_context` returns `None`), the parse pre-pass, the
   section header, and the per-file loop are all skipped, so a run on a no-refmodels hub produces
   byte-identical output to before. `--degraded` semantics are unchanged and now also apply to `--syntax`
   runs. **Knowingly accepted:** catalog/module infrastructure errors (e.g. `module_unresolved`) now fail
   `--syntax` on misconfigured refmodels-present hubs.

2. **Registration gate.** `init --domain` refuses to register a **pre-existing** domain TTL whose Managed
   Import Completeness diagnostics contain hard errors, or degradable `missing_managed_import` errors
   without the new `--degraded` flag — exiting 1 *before* the catalog write and the `_master.ttl` sync, so
   a refused run changes neither. Rules that bound the gate:
   - **Pre-existing files only.** A TTL `init` itself just scaffolded (fresh, or overwritten via `--force`)
     is never gated — the starter template has no `owl:imports`, so gating it would refuse init's own
     output on every refmodels-present hub. The fresh path gets an advisory pointing at
     `validate --all --domain <domain>`.
   - **Resolvability short-circuit.** No refmodels dir (or it fails `_looks_like_refmodels_root`), or no
     module config → no gate. An *ambiguous* accelerator warns, skips the gate, and points at
     `validate --all --accelerator <pack>`. Toolkit-owned infrastructure exceptions (context build crash,
     unreadable TTL) warn and proceed — they must never block a user's registration.
   - **Lower bound, not a replacement.** The gate builds a scoped single-domain module context, which is a
     LOWER BOUND versus `validate --all`'s full context: the scoped check can pass where `--all` fails,
     never the reverse of practical concern. The skill's pre-registration `validate --all --domain
     <domain>` run therefore remains necessary, not belt-and-braces.
   - **Fleet mode (DD-088).** The gate blocks identically in fleet mode; an explicit `--degraded` is the
     only bypass, and fleet invocations must record that bypass.
   - Accepted wart: `kairos.yaml`'s `default_domain` is written before the gate, so a refused run can still
     have set it.

3. **Skill.** Gate 5 documents that `validate --syntax` now also reports Managed Import Completeness when
   reference models are present (`missing_managed_import` blocking, degradable only via `--degraded`), and
   step 9 inserts a full-coverage `uv run kairos-ontology validate --all --domain <domain>` run before the
   registration command. Both skill copies stay byte-identical.

### Open sibling dependency

`Cnext-eu/kairos-ontology-referencemodels#64`: the logistics blueprint assigns the `equipment` domain both
`mmt/equipment` and `dcsa/equipment` with no precedence. The hard gate makes such dual-assigned domains
require BOTH overlapping imports — on existing hubs this surfaces as one required import edit per
dual-assigned domain on the first post-upgrade registration (the dogfooding hub's `equipment` domain hits
this immediately). Tracked there; not a toolkit defect.

### Rejected alternatives

- **Skill-text-only fix.** Prose doesn't gate: the transcript that motivated #426 followed the skill and
  still registered an unactivated domain. Only a deterministic check closes the gap.
- **Keeping the check SHACL-gated.** The mode split was accidental, not designed — no DD ever specified it,
  the check needs no pyshacl, and the in-file precedent (the deliberately unconditional `_master.ttl`
  check, validator.py's "Deliberately unconditional" comment) already establishes that structural import
  checks are mode-independent.
- **Reordering the refmodels fetch before registration** so a fresh `init` could always gate. The fetch is
  deliberately offline-safe and network-touching; moving it ahead of registration couples registering a
  domain to network availability and does not help the actual failure mode (pre-existing authored domains
  on hubs that already have reference models).

### Consequences

- Gate 5's inner-loop `validate --syntax` now catches a missing managed import at authoring time, between
  edits — the cost is `build_reference_module_context` loading the activated modules' closures once per
  run on refmodels-present hubs (scoped to requested domains, not all modules).
- `init --domain` on an import-incomplete pre-existing domain exits 1 with the diagnostics and leaves the
  catalog and `_master.ttl` untouched; `--degraded` registers with warnings.
- No-refmodels hubs (including every `--syntax` test fixture) see byte-identical validator output.
