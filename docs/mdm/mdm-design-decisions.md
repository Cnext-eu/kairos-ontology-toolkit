# MDM Design Decisions

This log records architectural decisions for the **design-time Master Data
Management (MDM) layer** of the Kairos toolkit. It is kept **separate** from the
ontology-core log (`docs/design/toolkit-design-decisions.md`) so MDM policy evolves
on its own cadence and the ontology↔MDM boundary stays explicit.

The `MDM-DD-NNN` numbers below build on, and cross-reference, the architecture ADRs
in `mdmhubdesignv2.md` (ADR-1..12). The ADRs describe the *whole* MDM
architecture (including the runtime); the MDM-DD entries record how the **toolkit
repo** realizes the design-time half.

> Increment `MDM-DD-NNN` sequentially. Use the template at the bottom for new entries.

---

## MDM-DD-001 — MDM is an ontology extension + projection target, not a new toolkit

**Status:** Accepted · **Refs:** ADR-1

MDM mastering/governance policy is expressed as an **additive ontology extension**
(`model/extensions/{domain}-mdm-ext.ttl`, `kairos-mdm:` vocabulary) and projected by a
new projection target (`mdm-profile`) inside the existing toolkit. We rejected standing
up a separate "MDM toolkit": policy is stable, reviewable design intent that belongs
alongside the semantics it governs, and it reuses the toolkit's validation, catalog
resolution, extension-merge and projection machinery.

**Consequence — naming overlap.** The claim registry already carries `mdm_anchor` and
`OwnershipOverride` gates (`core/claim_registry.py`, `core/claim_coverage.py`). Those are
*ontology-modeling* governance (reference-data anchoring, ownership conflict during claim
decisions) and are **kept in `core`**. The new `kairos_ontology.mdm` package is *MDM
profile policy* (how entities are mastered at runtime). They are distinct concerns that
share the letters "MDM"; the `mdm` package **consumes** core but does not absorb the claim
gates. This entry documents the overlap so future contributors don't conflate them.

---

## MDM-DD-002 — One-way `core → (never) mdm` boundary via a projector registry

**Status:** Accepted · **Refs:** ADR-2

To keep the split structural (not merely conventional), `kairos_ontology.core` must
**never** import `kairos_ontology.mdm`. But the projector dispatch table lives in core and
must invoke the MDM profile projector. We resolve this with a **registry**:

- `core/projector.py` exposes `register_target(name, *, discover_ext, project, output_subdir)`
  and an `_EXTERNAL_TARGETS` map; core stays agnostic of any contributing package.
- `kairos_ontology.mdm.__init__` calls `register_target("mdm-profile", …)` at import time.
- The **CLI** (`cli/main.py`), which legitimately depends on both layers, imports the `mdm`
  package — that import triggers registration before projections run.

`tests/test_layering.py` statically scans every `core/*.py` and fails on any
`from ..mdm` / `import kairos_ontology.mdm`. This makes the `mdm` subpackage cleanly
additive: ontology core remains usable without depending on optional MDM policy concerns,
while the MDM profile producer can consume stable core projection and RDF functionality.

**Rejected:** a static `from ..mdm import …` in core (couples the layers); moving the whole
dispatch loop out of core (duplicates the domain loop, extension discovery and output
routing).

---

## MDM-DD-003 — The `mdm-profile` release is immutable and content-addressed

**Status:** Accepted · **Refs:** ADR-5, ADR-11, ADR-12

The `mdm-profile` target emits `output/mdm/{domain}-mdm-profile.json` (runtime-neutral
policy) plus a `{domain}-mdm-profile.md` review summary. The JSON carries a
`content_digest` = `sha256` over the policy **excluding** the volatile
`generated_at`/`toolkit_version` provenance fields, so **the same reviewed hub state
reproduces the same digest**. Downstream (`kairos-mdm-runtime`, dataplatform
`contracts/mdm/`) pins that digest and records which hub+profile version made each decision.

Probabilistic matching **weights are never authored in Turtle** (ADR-5): the extension
declares only a content-addressed reference (`kairos-mdm:probabilisticArtifact` with an
`artifactDigest`) to an owned, versioned artifact. `mdm-validate` fails a reference that
lacks a digest.

**Opt-in.** `mdm-profile` is **not** part of `project --target all`; it runs only when a
domain has an `*-mdm-ext.ttl` and is explicitly requested. Domains without MDM policy
produce no MDM output. Policy changes reach runtime **only** through the reviewed hub loop
(ADR-12) — never by editing generated artifacts.

---

## MDM-DD-004 — Operational MDM starts in a separate private repository

**Status:** Accepted · **Refs:** ADR-2, ADR-11, ADR-12

The operational MDM product starts in the private `Cnext-eu/kairos-mdm-runtime` repository.
It owns APIs, mastering and workflow services, normalization, operational schema and
migrations, deploy modules, runtime compatibility checks and the Stewardship UI. These
concerns do not live in this public Apache-2.0 toolkit repository.

The runtime and Stewardship UI remain one product and one repository initially; this decision
does not introduce per-service repositories. The boundary is the immutable, content-addressed
MDM profile emitted here and pinned by the dataplatform. Runtime/profile compatibility must
therefore be explicit and tested rather than inferred from source co-location.

**Rejected:** starting proprietary runtime or UI source inside this toolkit and extracting it
later; splitting each runtime service into its own repository.

---

## Template

```markdown
## MDM-DD-NNN — <short imperative title>

**Status:** Proposed | Accepted | Superseded · **Refs:** <ADR-n, MDM-DD-n, DD-n>

**Context.** <forces at play>

**Decision.** <what we chose>

**Consequences.** <trade-offs, follow-ups, what this rejects>
```
