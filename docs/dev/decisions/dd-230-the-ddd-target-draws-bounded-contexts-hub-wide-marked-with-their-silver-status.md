# DD-230: The ddd target draws bounded contexts hub-wide, marked with their Silver status

**Status:** Accepted
**Date:** 2026-09-20
**Affects:** new `core/projections/ddd_context_projector.py`, `core/projector.py` (post-domain
block for the `ddd` target, retired-file removal, output reconciliation),
`core/projections/ddd_projector.py` (per-domain context map retired), `scaffold` unchanged
(`architecture/**` already tracked and drift-gated since #774), `tests/test_ddd_context_projector.py`,
`tests/scenarios/test_scenario_ddd.py`
**Issue:** #846 (closes it — the "new target" it proposed is folded into `ddd` instead), #861 for
the `ddd` output directory

### Context

Every diagram target selects by *file*: `erd` draws one domain TTL, `ddd` one overlay,
`contract-erd` one contract. A bounded context deliberately cuts across domain ontologies — that
is what distinguishes it from the one-TTL-per-domain partition — so no target could draw one. The
`kairos-ddd:boundedContext` annotation was collected by the DDD projector and never read. On a
real hub (15 domains, 44 classes, 5 contexts over 4 domains) the per-domain context map was
misleading rather than partial: it rendered only the edges that domain's own overlay declared, so
one report showed the whole map and the other three said *"No context relationships declared"*.

The hub built a prototype that merged every domain TTL and overlay and emitted one `classDiagram`
per context. It proved the shape and surfaced four findings this decision designs in. It also
raised the placement question: the prototype wrote into the authored tree because, at rc1, the
publish tree was gitignored and unreviewable. That premise is gone — #774 (rc3) tracks
`ontology-hub-publish/architecture/**` and regenerates `erd` and `ddd` in the drift gate.

Silver ⊂ architecture is true by construction (the contract's entity set *is* the binding set, and
an unbound class never enters the plan), but nothing made it *visible*: a context engineer looking
at a context diagram could not tell which boxes Silver actually promises.

### Decision

**Hub-wide context artifacts are emitted by the existing `ddd` target**, in a post-domain step
beside the canonical ERD's master diagram (#753), into `architecture/ddd/contexts/`:

| File | Content |
|---|---|
| `context-map.mmd` | every context and every relationship, whichever overlay or strategic file declared it; border style by subdomain type |
| `all-contexts.mmd` | one `classDiagram`, one `namespace` per context — the subject-area view a context engineer draws by hand |
| `{context}.mmd` | one per non-empty context; neighbours drawn as stubs saying where they live |
| `design-notes.md` | per context: subdomain, classes, Silver status, invariants, language, design notes; then every hub class no context claims — the honest backlog |

**Not a new target.** #846 proposed `project --target ddd-context`. A new target name would have
to be added to both scaffolded workflows, which means a seventh `pr-validate.yml` generation and
every hub refreshing its workflows before the tracked lane is regenerated. Folding the artifacts
into `ddd` means no workflow change, no gitignore change, and any hub on rc3 gets them on the next
toolkit bump. The output directory is the same tracked, drift-gated lane.

**Publish tree, by `TargetSpec.hub_relative`'s own criterion.** That flag puts a diagram beside an
authored file only when it is a pure function of *one* such file. A context diagram is a function
of every domain TTL, every overlay, the strategic file and the contracts. There is no single file
to sit beside; it is derived output.

**The per-domain `{domain}-context-map.mmd` is retired.** Its report keeps a filtered table and
points at the hub-wide map. No hub has a manifest under `architecture/ddd/` yet, so a manifest
diff cannot remove the files an earlier toolkit wrote; the projector names them explicitly and
removes them once. From this release the `ddd` output directory is reconciled to exactly the
run's files through `.kairos-projection-manifest.json` (#861), written only for a hub that has DDD
output or already carries a manifest — `architecture/ddd` is created for every hub, and an
unconditional manifest would put a tracked dotfile in the publish lane of hubs that never
authored an overlay.

**Silver status is read from authored inputs, never the CompilePlan.** `contract` when a
`model/contracts/<domain>.contract.yaml` declares the class, `bound` when an EntityBinding targets
it, `unbound` otherwise. The contract is the promise, so a contract nothing fulfils must still
show as `contract` (DD-216's reasoning). Class tokens resolve through `fit_report.resolve_token_uri`
over the domain's load result — a loaded graph's namespace manager does not carry the source
`@prefix` bindings, and a union built triple by triple has none. A token that does not resolve is
listed under *Unresolved class references*, never guessed by local name. Direction is Silver →
documentation; the DD-091 firewall (DDD never drives emission) is untouched. In the class
diagrams the status is a **second stereotype** on every member (`<<silver: contract>>`,
`<<silver: bound>>`, `<<architecture only>>`), not a border style: `classDef` inside a
`classDiagram` fails the parse on mermaid-cli 11.12 (verified while building this), while an
annotation is plain text that every renderer draws. The context map, a flowchart, keeps
`classDef` borders for subdomain type; the flowchart grammar accepts them.

**The four prototype findings, designed in:**

1. A Mermaid `namespace` whose id equals a class inside it fails the render outright. Namespace
   ids and file names come from the context IRI local name, never `rdfs:label` (labels collide
   with class names routinely, are language-tagged, and two contexts can share one), and are
   suffixed `_context` when they still equal a member class id.
2. `note for` with two hundred characters of rationale drags a leader across the canvas. Design
   notes and invariants go to `design-notes.md`.
3. Membership is annotation-gated: an explicit `boundedContext`, else the aggregate root's
   context. A reference-model class appears only as a memberless stub on a member's edge, so the
   import closure never floods a namespace.
4. Multiplicities and node ids reuse the canonical ERD's helpers (`_effective_bounds`,
   `_multiplicity`, `_node_ids`) rather than a weaker reimplementation; the prototype rendered
   `1..*` for a functional property carrying `minCardinality 1`.

**Associations are the hub's own object properties.** At architecture altitude a context diagram
shows what the hub designed; the inherited reference-model surface is `project --target erd`'s job.

### Consequences

A context engineer sees the architecture as one picture and the Silver promise inside it; a data
engineer sees which boxes are theirs to fill. Both review the same tracked files in a pull request.

Upgrading hubs: the first `project --target ddd` after the upgrade removes `{domain}-context-map.mmd`
and adds `contexts/**` plus the manifest. `git diff --exit-code` does not see *untracked* additions,
so the new files pass the drift gate until `git add`ed — the changelog says so.

Rejected: a separate `ddd-context` target (workflow churn for every hub; the per-domain map stays
misleading meanwhile); the authored tree (fails the `hub_relative` criterion and needs an escape
hatch `register_target` does not expose); reading the CompilePlan for Silver status (a contract
nothing fulfils would disappear); Lucid as the rendering target (a Mermaid import produced a
zero-state block, and a board is a snapshot that disagrees with the hub the moment someone edits
it — a rendering may be published per occasion, never generated as a lane).

Companion to DD-229 (the strategic file this projector merges) and extension of DD-091.
