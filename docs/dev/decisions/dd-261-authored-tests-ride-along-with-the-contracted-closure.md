# DD-261: Authored tests ride along with the contracted closure

**Status:** Accepted
**Date:** 2026-10-18
**Affects:** `core/compiler/kernel.py` (`resolve_scope`, `_planned_dbt_dependencies`),
`cli/compile.py` (dependency kind registry). Amends
[DD-140](dd-140-canonical-emit-layout-and-dbt-package-topology.md) and restores a promise of
[DD-092](dd-092-contracted-custom-dbt-transformation-boundary.md).
**Issue:** #1152

### Context

A contracted binding publishes its hand-authored dbt closure into the dataplatform project.
Before this decision the v5 emit (DD-140, #580/#586) selected only:
- the `.sql` of every model in the binding's `ref()` closure;
- the seeds in that closure and their column docs;
- the one properties file named by the binding's `contractPath`, copied whole.

Two kinds of authored test were dropped, and nothing reported it:
- **The properties file of a closure model no binding selects.** An `int_<source>__*` or
  `stg_*` model's `.sql` was published, but its own `.yml`, with every `data_tests` entry,
  was not.
- **Singular tests** under `integration/transforms/dbt/tests/`, even when they `ref()` only
  published models.

`validate-dbt-contracts` and `compile --check` passed, and the test never ran. A production
logistics hub merged a warning-level `relationships` test meant to "report non-Rec-21 codes
on every dbt run". It was never published.

DD-092 had promised that "schema/unit-test YAML, singular tests … follow that closure". The
v4 bundler (`core/dbt_bundle.py`) kept that promise, but the v5 CompilePlan emit never called
it. Its last call site is commented out in `projector.py`.

### Decision

1. **The scope carries the closure's authored tests.** `resolve_scope` adds three kinds of
   file to a domain's provenance inputs, next to the closure SQL and seeds:
   - every properties file under `models/` that declares a closure model under `models:`;
   - every `tests/**/*.sql` that `ref()`s a closure model or seed;
   - every generic test definition (`{% test name(...) %}`) under `tests/` that one of those
     properties files applies by name.

   Only closure-relevant files join the scope. Editing an unrelated test or properties file
   leaves the domain's provenance hash unchanged.
2. **Selected whole, byte for byte.** A closure model's properties file is published like a
   `contractPath` file: unchanged, as kind `properties`. It is not filtered to the published
   entries. Filtering would re-serialize the YAML, drop its comments, and give one file
   different bytes per domain. dbt ignores a properties entry whose model is absent, with a
   warning.
3. **A singular test is published when every `ref()` resolves** to a model or seed this
   domain publishes, generated or authored, and every `source()` is one the closures
   declare. It is emitted at its authored path under `tests/`, as the new dependency kind
   `test`. A test is not in dbt's `ref()` namespace, so, like a properties document, it
   carries no `model_name`.
4. **A generic test definition is published when a published properties file applies it.**
5. **A test that cannot be published is reported.** A singular test that reads the closures
   but also reads an unpublished model or an undeclared source is
   `dbt-source.test-not-published`, a warning on the binding whose closure it reads. A test
   that reads none of a domain's closures is not that domain's and is not reported.

### Consequences

- On upgrade, a hub's emit publishes tests it has dropped until now. A test that was wrong
  all along now runs in the dataplatform and can fail its build. That is the point, but it
  belongs in the release notes.
- The dependency state files gain kind `test`. An older toolkit reading a publish tree
  written by this one rejects the entry as an unknown kind and fails closed. The kind
  registry is designed to fail that way.
- Tests read only through the hub's own macros still need those macros published. Macros are
  not a dependency kind yet, the same limit models already have.
- A singular test that reads only generated Silver models, with no contracted closure model
  or seed, does not join the scope and is still not published.
- A test that reads closures in two domains is published by neither and warns in both.
- `dbt_bundle.py` stays as it is. Reviving it would add a second selection path beside the
  CompilePlan, which DD-140 rules out.

### Alternatives rejected

| Option | Why rejected |
|---|---|
| Call `dbt_bundle.assemble_dbt_bundle` from the emit | A second resolution path beside the CompilePlan, against DD-140's single authority for emitted bytes. |
| Filter a closure model's properties file to its published entries | Re-serializes authored YAML, loses comments, and makes one source file emit different bytes per domain, which the cross-domain reconciliation rejects as a collision. |
| Only warn (`dbt-contract.test-not-published` in the lint) | The lint cannot see the plan, so it cannot tell what is published. And the test would still never run. |
| Pull every authored test into every domain's scope | Every unrelated edit would change every domain's provenance hash and sidecar. |
