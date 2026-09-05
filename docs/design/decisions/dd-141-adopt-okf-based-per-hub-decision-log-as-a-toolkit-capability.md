# DD-141: Adopt OKF-based per-hub Decision Log as a toolkit capability

**Status:** Accepted
**Date:** 2026-07-29
**Affects:** hub scaffold decisions bundle, `decision` CLI, validation, `kairos-help`
skill, and documentation
**Implementation:** `kairos-ontology decision new`, decision-bundle scaffold files under
`ontology-hub/decisions/`, and the decision-profile validation path in
`kairos-ontology validate`

### Context

Material ontology-design decisions were being made during Copilot-assisted design, but their
rationale lived only in ephemeral conversation memory. The authored TTL states *what is true*;
it does not durably explain *why* a maintainer accepted a genuine modeling tension, real gap,
or rejected alternative. The `kairos-design-domain` workflow even described its rationale matrix
as ephemeral, so refreshes and later reviews could preserve classes and properties while losing
the evidence and trade-offs that justified them.

DD-080 and DD-085 previously used OKF-shaped `.kairos-state` phase logs for interactive session
continuation, but DD-135 retired that state structure for v5. The Decision Log is intentionally
separate from that retired session state: it is durable, human-reviewed hub documentation for
material decisions, not a lifecycle or continuation store.

### Decision

Adopt a per-hub **Decision Log** as a toolkit capability. Each v5 hub may carry a Google Cloud
Open Knowledge Format (OKF) v0.2 Markdown + YAML-frontmatter bundle at
`<hub_root>/decisions/` (for scaffolded hubs, `ontology-hub/decisions/`). Decision records are
named `HUB-DD-*.md`; `index.md` is generated; the README and
`HUB-DD-template.md.template` are managed scaffold files.

Authors create records with `kairos-ontology decision new`. `kairos-ontology validate` now lints
an existing bundle with the Kairos decision profile and reports two diagnostic classes:
OKF-conformance findings and Kairos-decision-profile findings. An absent bundle is skipped.

The materiality threshold is strict: log genuine tensions, real gaps, intentional standard
divergence, evidence conflicts, or decisions with persistent consequences and rejected
alternatives. Never log routine confirmations, obvious field additions, or decisions whose
rationale is already fully expressed by the authored model.

### Alternatives rejected

| Option | Why rejected |
|---|---|
| Single hand-rolled hub file like the old `docs/draft/specs.md` pattern | Does not scale beyond one or two decisions, has no machine-checkable structure, and cannot be validated as a bundle. |
| Store rationale in TTL comments | Conflates canonical facts with review rationale, is easy to drop during ontology refresh, and cannot clearly carry rejected alternatives or lifecycle metadata. |
| ADRs only under repository `docs/` | Documents toolkit choices, not per-hub modeling choices, and is not shipped with scaffolded hubs where future maintainers need the rationale. |

### Rationale

OKF gives the hub a familiar, document-oriented record format without inventing a bespoke file
syntax. A Kairos-specific decision profile can enforce the fields that make ontology rationale
reviewable — materiality, sources, status, accepted/rejected state, and rejected alternatives —
while keeping the actual record readable in any Markdown viewer.

Scaffolding the README and template makes the capability discoverable in every new hub. Generating
`index.md` avoids hand-maintained navigation drift, and validating the bundle during
`validate` puts decision quality beside ontology syntax, SHACL, binding, and compile diagnostics.

### Consequences

- Every hub can keep durable rationale for material ontology-design decisions beside its authored
  inputs.
- `kairos-ontology validate` now also lints the decision bundle when it exists; an absent bundle
  remains a compatible skip.
- PR review is the materiality backstop: reviewers should reject routine confirmations and require
  records for consequential design tensions or standard divergences.
- The Decision Log does not revive `.kairos-state`; it is a separate, durable, human-reviewed
  artifact rather than session state.

> **Amendment (2026-08-15, #420):** the resolution base for local `sources[].resource`
> citations is now documented and slightly widened. The base is the **hub root** — the
> convention every other hub path citation follows, chosen (over the `decisions/`
> directory) in issue #349 but stated nowhere until now. On a **nested** hub (a hub
> inside a toolkit-managed repository root, detected via
> `hub_utils.resolve_repo_root` = `find_managed_root(hub_root) or hub_root`),
> citations whose first segment is `.import/` or `ontology-reference-models/` — the
> two repo-root siblings a hub-root join can never reach — additionally fall back to
> the **repository root**. No other path ever probes the repo root, so a rotted hub
> citation cannot be silently satisfied by the repo's own same-named file. Bare/test
> hubs without a toolkit pin degrade to hub-root-only resolution. `_is_local_path`
> is widened to recognize `.import/` citations (either separator; backslashes are
> normalized before joining) and the binary evidence extensions
> `.pdf`/`.docx`/`.xlsx`/`.pptx`, all extensions matched case-insensitively.
> Accepted consequence: a prose citation that merely *ends* in `.pdf` now warns as
> unresolved — the same class of behavior `.md`-suffixed prose already had.
