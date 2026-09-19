### Fixed
- **`compile --check` reports a deferred cross-domain bridge endpoint.** #763 deferred the
  endpoint check on the single-domain path and recorded the result on the plan, but
  nothing printed it: `compile party --check` was green and `emit-gold` on the product
  then failed on the same endpoint. The check output and the JSON payload
  (`unresolved_bridges`) now name the bridge and the endpoint the domain cannot see.
- **A declared workflow customization is honoured in every state.** #772 exempted a
  declared workflow from the `customized` failure, but one pinned to an older shipped
  generation (`outdated`) still failed `update --check` and was overwritten by
  `update --refresh-workflows`, contrary to what `CICD.md` promises. Declared workflows
  are now skipped by the refresh and excluded from the outdated count.
- **The master ERD headers carry the hub's declared name, not the checkout directory.**
  All three masters (canonical, Silver, Gold) stamped `hub_root.name`, so two clones of
  one hub under different directory names regenerated a one-line header difference and
  failed the drift gate on it. They read `name:` from `kairos.yaml` and fall back to the
  directory only when it is absent. **The headers change bytes once on your next run.**
- **`validation-report.json` anchors on the repository root, not the hub's parent.**
  #822 approximated the repo root as `hub_root.parent`, which is right for the scaffolded
  layout and wrong for a flat-layout hub or a hub nested deeper: paths began with the
  checkout's directory name and still differed between contributors. The nearest ancestor
  carrying `.git` is used, with the parent as fallback.
- **The reference rollup credits an ambiguous anchor to the copy the table's columns
  align to.** #523 keyed the rollup on the class URI, but a table anchored to a bare
  name declared by two modules was still credited -- with every custom column -- to both
  copies, and `custom_extensions_count` summed twice over the hub.
- **A `candidate` concept-mapping match does not name a draft-model node.** #762's lexical
  proposal became the node label and could acquire glossary evidence under that name
  before anyone confirmed it; the node keeps the TMDL table's own name until then.
- **`import-tmdl` finds the hub catalog from inside the hub.** The match proposer located
  the hub with a helper that does not walk parent directories, unlike the one that
  places the output, so a run from `ontology-hub/integration/` wrote its artifacts and
  proposed nothing.
- **`--model` typed as the default is recorded as `explicit-model`.** #545's provenance
  label used the default model's name as the "not passed" sentinel, so `--model
  gpt-5.4-mini` was indistinguishable from the option's absence.
- **Name tokens split an acronym run before a capitalised word.** `ETLLoadDate` tokenised
  to `etlload`, `date` and matched nothing after #522; it is `etl`, `load`, `date`.
- **A hand-edited alignment without a `domain` key no longer reads as
  `<domain>-alignment-alignment.yaml` in the staleness message.**
- **`scripts/collect_changelog.py` prints on a Windows console** whose code page cannot
  encode a fragment's characters.

### Documentation
- `alignment_closure` states what #518 compares -- the blueprint's activated module list,
  not a resolved `owl:imports` closure -- and what that does not detect.
- `update --check`'s exit-code help names undeclared workflow divergence as a failure
  cause; the lane test pins `full-validate.yml` as well as `pr-validate.yml`.
