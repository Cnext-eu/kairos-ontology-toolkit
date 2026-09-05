# DD-215: The target platform names the engine, and boolean-ness is rendered per adapter

**Status:** Accepted
**Date:** 2026-09-03
**Affects:** `compile`, `init`, `new-repo`, `init-dataplatform`, `validate-dbt`,
`validate-dbt-contracts`, hub and dataplatform scaffolds, kairos-develop-dbt-transformation,
kairos-setup-config, kairos-execute-validate
**Implementation:** `core/adapters.py`, `core/hub_config.py`,
`core/projections/dbt/{policy_specs,capabilities,mapping_renderers,model_renderers}.py`,
`core/compiler/kernel.py`, `core/dbt_contract_lint.py`, `cli/{setup,validation,projections}.py`
**Amends:** DD-002 (adds the boolean-position rule its own table already implied)
**Supersedes:** DD-009 (Fabric-First Default Platform)

### Context

A client hub's first real warehouse run failed. `silver.partyrole` could not build because a
hand-authored model aliased a T-SQL `bit` column and then filtered on it bare:

```sql
OB_IsDebtor as is_debtor,
...
where is_debtor          -- An expression of non-boolean type specified in a
                         -- context where a condition is expected
```

Fabric has no boolean type. Postgres, Snowflake and Databricks all accept the bare form, which is
where the habit comes from. Investigating it surfaced three problems, of which the authored SQL was
the least important.

**1. The compiler could emit the same thing.** `mapping_normalize` requires a CASE condition, a
logical operand and a `rowFilter` to be canonically `BOOLEAN` — and a bare source column bound to a
Fabric `BIT` column satisfies that, so it passed the type gate and `mapping_renderers` emitted it
unwrapped. The mirror case was equally broken: a native predicate such as `(a IS NULL)` in a select
list, which T-SQL also rejects. The guard had been placed in *typing*, but boolean-in-predicate is a
*rendering* concern.

**2. `adapter: fabric` could not say which engine it meant.** Fabric Warehouse is T-SQL and Fabric
Lakehouse is Spark SQL. Both `fabric-lakehouse` and `fabric-warehouse` collapsed to `fabric` and
received the T-SQL profile. The scaffold's own `fabric-lakehouse` profile block was in fact a
Warehouse connection (`type: fabric` against `datawarehouse.fabric.microsoft.com`) under a Lakehouse
label, which is also why `extract-schema` could never round-trip the slug.

**3. Nothing made the target easy to declare, or consistent.** `init` had no `--adapter`, so every
hub was born `fabric` from a template line. The two-value set was redeclared in eight places, none of
which imported `AdapterName`. Seven call sites each parsed `kairos.yaml` themselves.

### Decision

**Canonical ids name the engine.** `fabric-warehouse` and `databricks` are supported;
`fabric-lakehouse` is *recognised and rejected* with its own reason rather than falling back. `fabric`
resolves as a deprecated alias and says so once, where `kairos.yaml` is read — hubs are client
repositories and an upgrade must not break one outright. `core/adapters.py` is the single
declaration, and makes explicit two mappings that were previously inlined assumptions: canonical id
to dbt's `profiles.yml` `type:` key, and to the pip package. dbt's vocabulary is not ours —
`dbt-fabric` calls itself `fabric` whichever engine it points at.

**Rendering is position-aware.** `AdapterSpec.dialect.native_boolean` states whether the adapter has a
first-class boolean. When it does not, a canonically-BOOLEAN value in predicate position renders
`(x = 1)`, and a native predicate in value position renders a `CASE`, three-valued when the predicate
can itself be NULL. This follows the adapter split `canonical_hash.py` already used and the `= 1`
convention every hand-written predicate in the repo already followed.

**Hand-authored SQL is written for one declared target, not made portable by hand.** The client's own
fix, `where is_debtor = 1`, is Fabric-only: Spark rejects `boolean = int`. The two targets' correct
spellings are mutually exclusive, so hand-portable SQL is reliably correct on neither. Anything that
must be portable belongs in the mapping AST, which renders per adapter — that is now an explicit
routing criterion alongside DD-092/DD-107's grain, joins and windows.

### Consequences

**One-time re-emit.** The adapter is part of `BuildScope`, so it feeds `provenance_hash`. Adopting
the canonical id changes that hash for every hub, and each one's `pr-validate.yml` drift check fails
until it re-emits. This is the same re-emit a toolkit bump already requires, but it must be
communicated rather than discovered.

### Out of scope

**A SQL parser.** Identifying a bare bit column in *authored* SQL requires knowing predicate
position, which requires a real parser (sqlglot). It was considered and deliberately deferred: one
confirmed occurrence across 67 emitted models does not yet earn the dependency, dbt models are Jinja
so a parser must lint compiled output or stub the templating, and parse failures on constructs a
dialect does not model become their own false-positive source. The `dbt-contract.dialect-*` family
therefore holds only rules that are deterministic from the text — today, `dbt-fabric`'s
substring-counting nested-CTE detector. Revisit if hand-authored dialect defects recur.

**The complete gate lives downstream.** `dbt build --empty` runs every model at `limit 0`, so the
warehouse parses and binds real SQL for essentially no compute. It is the only check that catches
every dialect error rather than the ones a rule anticipated, it needs credentials, and it therefore
belongs on the dataplatform's `bump/hub-*` PRs, not in the hub's offline CI.

**A hub↔dataplatform adapter handshake.** Nothing yet compares the adapter a hub compiled for
against the dbt adapter the dataplatform installs, and `bump-hub` does not check it even though
`metadata/<domain>-release-review.json` already carries `adapter.name`. Likewise the v4 check of a
contracted model's `supported_adapters` against the hub's own adapter, dropped in v5, is not
reinstated here.
