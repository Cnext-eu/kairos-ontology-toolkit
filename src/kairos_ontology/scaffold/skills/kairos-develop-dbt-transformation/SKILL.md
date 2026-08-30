---
name: kairos-develop-dbt-transformation
description: >
  Interactive v5 workflow for ordinary dbt SQL and properties YAML when an
  EntityBinding needs a contracted relational or grain-changing source model.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# Develop a Contracted dbt Transformation

Use this skill only when a direct relation plus closed scalar binding expressions
cannot express the required result. The outputs are ordinary dbt SQL and
properties YAML under `integration/transforms/dbt/models/`, plus — when the logic
needs small static reference data — a seed CSV under
`integration/transforms/dbt/seeds/`.

## Design fleet mode (DD-088)

Default is interactive. Confirm source relations, business meaning, output grain,
key columns, relational logic, fallback behavior, output columns/types, adapter
scope, tests, and the exact patch before writing.

An explicit AI-approved override applies only to this skill invocation and is
never inherited. Record rationale, confidence, and evidence for every AI-approved
checkpoint. Stop for ambiguity, low confidence, policy-sensitive choices,
destructive changes, or proprietary/PII risk.


## Model naming and layering

Use these conventions for hand-authored contracted transforms:

- Single-source model: `int_<source>__<entity>`, for example
  `int_qlik__transport_routes`.
- Multi-source survivorship model: `int_merged__<entity>`.
- Multi-source layering: `stg_<source>__<entity>` models do atomic per-source
  cleaning, then feed one `int_merged__<entity>` model for union and survivorship.
  Prefer the toolkit macros `kairos_clean_sentinel`, `kairos_normalize_key`,
  `kairos_survivor`, and `kairos_source_system_label` for portable cleanup,
  key normalization, deterministic survivor ranking, and source labels.

`stg_*` is internal to a hand-authored contracted transform and does not
contradict the generated-Silver "no staging layer" rule. The EntityBinding
references the final `int_*` model via `source.dbtModel`. These are conventions,
not enforced or linted invariants.

**`scaffold-staging` generates this layering (issue #399).**
`kairos-ontology scaffold-staging --entity <entity> --domain <domain> --source
<system>.<table> --source <system>.<table> [...]` writes one
`stg_<source>__<entity>.sql` + properties YAML per `--source` (reusing the same
per-table staging SELECT `scaffold-binding`'s passthrough archetype already
generates, each independently contracted with `config.contract.enforced: true`
and no `meta.kairos` — a stage is never itself a bindable virtual source) plus
one `int_merged__<entity>.sql` + properties YAML with the full `meta.kairos`
block. The merged model's SQL unions only the columns common to every source
stage and leaves `<CONFIRM_NATURAL_KEY_COLUMN>`/`<CONFIRM_PRIORITY_COLUMN>`
sentinels for `kairos_survivor` (irreducible modeling judgment, not something a
scaffold can infer); its YAML leaves `<CONFIRM_TARGET_CLASS>`/
`<CONFIRM_VIRTUAL_SOURCE_IRI>`/`<CONFIRM_GRAIN_KEY_COLUMN>`/
`<CONFIRM_SUPPORTED_ADAPTER>` sentinels, so `compile --check` rejects the
contract until a human confirms them — the same sentinel-skeleton philosophy
`scaffold-binding` already uses for grain and identity. Prefer this over
hand-authoring the layering from scratch; only fall back to the plain SQL
pattern above for the attribute-level outer-join strategy, which the scaffold
does not attempt to generate (it always starts from the survivorship shape).

### Two reconciliation strategies for `int_merged__<entity>`

Sources feeding a merged model either compete for the same attributes or
complement each other. Pick the strategy that matches the actual relationship
between the sources, not the pattern that happens to be more familiar:

- **Survivorship (competing sources).** Two or more sources supply the same
  attributes for overlapping keys and only one row per key may win. Union the
  cleaned `stg_*` models, rank with `kairos_survivor` over a mandatory total
  order (`priority_column` plus deterministic tiebreaks), and keep the rank-1
  row per natural key. This is the existing pattern the toolkit macros above
  already support.

- **Attribute-level outer join (complementary sources).** Two or more sources
  supply *different*, non-overlapping attributes at the same key grain — for
  example one source has commercial/order attributes and another has
  operational/routing attributes for the same order key. No row is discarded;
  instead `full outer join` the sources on the shared natural key, select each
  source's own non-overlapping columns directly (or `coalesce` any columns
  that legitimately exist on both sides), and add an explicit boolean
  presence flag per source (for example `in_<source_a>`, `in_<source_b>`) so
  downstream consumers can tell which source(s) contributed to each row and
  scope reports accordingly:

  ```sql
  select
      coalesce(a.order_id, b.order_id) as order_id,
      a.commercial_terms,
      b.route_code,
      a.order_id is not null as in_source_a,
      b.order_id is not null as in_source_b
  from {{ ref('stg_source_a__orders') }} as a
  full outer join {{ ref('stg_source_b__orders') }} as b
      on a.order_id = b.order_id
  ```

  A dedicated merge macro is optional; prefer authoring the plain SQL pattern
  above unless the same shape repeats across several models.

Both strategies still author a single contracted `int_merged__<entity>` model
with one output grain and one properties YAML — the choice only changes the
SQL between the `stg_*` union and the final select.

## Seeds for static reference data (issue #586)

Some contracted logic needs a lookup table that has no upstream system: ISO
country codes, currency lists, a hand-curated status or code mapping. Author
these as a dbt **seed** instead of inventing a source vocabulary for data nobody
extracts:

```text
integration/transforms/dbt/seeds/<name>.csv        # the data
integration/transforms/dbt/seeds/<name>.yml        # optional column docs
```

Author a seed when the data is **small, static, hand-maintained, and belongs in
version control** — a maintainer edits it in a pull request, not a pipeline. If
the data comes out of a real system, or changes often enough that a human editing
CSV is the wrong loop, it is a source, not a seed: import it and bind it normally.

Rules that matter while authoring:

- **The file stem is the dbt resource name.** `seeds/country_codes.csv` is reached
  by `{{ ref('country_codes') }}` from any authored model — a seed is a `ref()`
  target exactly like a model is, and needs no `source()` declaration.
- **The stem must not collide with any model stem**, authored or generated. dbt
  resolves `ref()` in one resource namespace; a collision is a hard failure in the
  compiler, in the bundle, and in `validate-dbt-contracts`
  (`dbt-contract.seed-model-collision`). Rename one of the two.
- **The CSV must be UTF-8 with a non-empty header row.** A cp1252 export from
  Excel fails the compile as an unresolved dependency.
- **The sibling YAML is dbt's plain `seeds:` properties form and must not carry
  `meta.kairos`.** A seed is not a bindable virtual source, so it declares no
  output contract — the CSV owns the resource name and the YAML only describes it:

  ```yaml
  version: 2
  seeds:
    - name: country_codes
      description: ISO 3166-1 alpha-2 reference list.
      columns:
        - name: alpha_2
          description: Two-letter country code.
  ```

A seed reached by a selected model's `ref()` closure joins the `CompilePlan` as a
leaf and is emitted under `seeds/` alongside its properties YAML, so the generated
project stays self-contained. Seeds are never text-scanned for `ref()`/`source()`.

**On an existing hub, create the directory first.** `update` does not backfill hub
directories — only `init`/`new-repo` create them. Run
`mkdir integration/transforms/dbt/seeds` before authoring the first seed; this is
expected behavior, not a bug.

## Alternative entry path: author outside the hub, then promote (issue #634)

Steps 1-6 below assume authoring directly inside the ontology hub. An engineer who
prefers to iterate in their own dataplatform repo instead may develop and test the
`int_merged__<entity>`/`int_<source>__<entity>` model there as an ordinary local dbt
model -- same naming convention, same `contract: {enforced: true}`, same `meta.kairos`
block, validated with plain `dbt build`/`dbt test` against seed data, with zero hub
involvement during active development. Once the model is stable, run:

```powershell
uv run kairos-ontology promote-transform <path-to-model.sql> --domain <domain>
```

from inside the dataplatform repo (or pass `--hub-root` explicitly). This copies
(never moves -- the dataplatform-authored SQL and properties YAML are left untouched)
the model's SQL and just its own properties-YAML entry into
`integration/transforms/dbt/models/intermediate/<domain>/` in the hub, then runs the
same offline `validate-dbt-contracts` check step 6 below documents. A validation
failure rolls back (deletes both just-written files) so an invalid model is never left
in the hub tree. Pass `--dry-run` to preview the destination paths first, and
`--force` to overwrite an already-promoted copy.

`promote-transform` only replaces steps 1-6's *authoring location* -- it does not wire
the EntityBinding or record a Decision Log entry. Steps 7 and 8 below (the Decision Log
entry for an `int_merged__` model, and returning to kairos-design-mapping to wire
`source.dbtModel`) are still required either way, whichever entry path was used.

## Workflow

1. Read the target ontology, source vocabulary, PII-safe samples, current binding,
   and existing dbt project files.
2. Confirm one output row grain and its physical key columns.
3. Present the proposed `source()`/`ref()` graph, relational operations, null and
   error behavior, deterministic ordering, and adapter assumptions. Obtain the
   active mode's checkpoint decision.
4. Author SQL with `source()` and `ref()`; do not hard-code physical relation names.
5. Author `version: 2` properties YAML with `config.contract.enforced: true`, every
   output column name/type, focused dbt tests, and `meta.kairos` containing grain,
   `grain_key`, target class, `virtual_source_iri`, and supported adapters. The
   legacy-named IRI identifies the contracted model output only; do not generate a
   separate virtual-source artifact or registry.
6. Validate the contract you just authored, **before** binding it:

   ```powershell
   $env:KAIROS_SKILL_CONTEXT = "1"
   uv run kairos-ontology validate-dbt-contracts --format json
   ```

   This is offline (no dbt install, no adapter, no warehouse) and checks the whole
   hand-authored tree at once: `meta.kairos` completeness, `grain_key` against the
   declared output columns, `config.contract.enforced`, that `target_class` resolves
   to a real class in the hub's import closure, that `virtual_source_iri` is unique
   hub-wide, and that no `<CONFIRM_...>` sentinel is left unreplaced. It also warns
   when a `stg_*` model declares a `meta.kairos` block or an `int_*` model lacks one.
   It is seed-aware too (issue #586): a seeds-only transforms tree is linted rather
   than reported as having no transforms, seed docs naming no authored CSV
   (`dbt-contract.seed-docs-unmatched`) and unreadable or header-less CSVs
   (`dbt-contract.seed-unreadable`) are warnings, and a seed/model name collision
   (`dbt-contract.seed-model-collision`) is an error because dbt cannot parse it.
   Before issue #504 none of this was checkable until a binding existed and
   `compile --check` ran for its domain — which is one step too late to be useful here.

   Then validate with the dbt commands already configured by the project. Fix parse,
   contract, compile, and focused test failures before handoff.
7. When the model authored in this pass is an `int_merged__<entity>`
   (survivorship or attribute-level outer-join) model, persist a Decision Log
   entry with `kairos-ontology decision new`, not ad hoc markdown, capturing
   the grain, the natural key, which reconciliation strategy was chosen and
   why, and any sample-evidence/row-count reconciliation performed.
8. Return to **kairos-design-mapping**. Set `source.dbtModel.name`, `sqlPath`, and
   `contractPath`; make binding grain and source key exactly match the contracted
   `grain_key`, and make `target.class` resolve to the same IRI as the contract's
   `meta.kairos.target_class`. All three are compiler-enforced (issue #503):
   `dbt-source.grain-mismatch`, `dbt-source.identity-mismatch`, and
   `dbt-source.target-mismatch` respectively — "make them match" is no longer an
   unchecked manual step.
9. Run the stateless binding feedback loop:

   ```powershell
   $env:KAIROS_SKILL_CONTEXT = "1"
   uv run kairos-ontology compile <domain> --check --format text
   uv run kairos-ontology compile <domain> --explain --format text
   ```

The dbt output contract is physical source authority. It does not define canonical
ontology meaning, and this skill does not emit generated Kairos artifacts.
