---
name: kairos-execute-validate
description: Validate ontology syntax, SHACL, bindings, and canonical compile diagnostics.
---

# Execute Validation

Validation is read-only unless the user explicitly requests an output file.

1. Resolve hub, ontology, catalog, and optional SHACL scope.
2. Set `KAIROS_SKILL_CONTEXT=1` and run `kairos-ontology validate` with the requested
   syntax, SHACL, or consistency options. Report exact findings.
3. Parse each closed `integration/bindings/*.binding.yaml` against the packaged EntityBinding
   schema by running `kairos-ontology compile <domain> --check --format json`.
4. Preserve ordered, source-located compiler diagnostics without changing their severity.
5. Distinguish ontology validity, binding compilation, and runtime dbt/platform testing.
6. Route fixes to the owning source, ontology, mapping, Gold, or MDM skill.
7. Never read a raw ontology serialization (`.ttl`/`.rdf`/`.owl`) as text; treat
   `validate`/`compile` diagnostics, or `resolve-ontology`/`show-class-inventory`/
   `list-class-properties`/`explain-term` output, as authoritative.

## Three distinct "dbt check" tiers — do not conflate them

"Run a dbt check" is ambiguous. There are three separate mechanisms; this skill's default hub
scope performs tier 1 always and tier 2 only on explicit opt-in. **Tier 3 is out of scope for
this skill** — it belongs to the dataplatform, not the hub.

| Tier | Command | What it validates | Runs in | Credentials? | In scope here? |
|---|---|---|---|---|---|
| **1. Canonical compile check** | `kairos-ontology compile <domain> --check --format json` | EntityBinding/OWL correctness → produces the CompilePlan. Not dbt. | The hub | No | ✅ Always (step 3 above) |
| **2. Offline dbt gate** | `kairos-ontology validate-dbt --platform <fabric\|databricks>` | The compiler-emitted dbt project actually parses/compiles (`dbt deps → parse → manifest → compile`) and satisfies DD-110 column parity. No models run, no data touched. | The hub, once for the whole `ontology-hub-publish/medallion/dbt`, after all domains emit | `dbt deps` needs package/network only; a synthetic offline profile is used, no real warehouse | ⚠️ Opt-in only — offer it, never run it silently |
| **3. Runtime dbt build/test** | Plain `dbt parse` / `dbt build` / `dbt test` | Whether real models build and real data passes tests against a live warehouse | The **dataplatform repo** (`kairos-setup-dataplatform` / `kairos-package-dataplatform`), never the hub | Yes — real connection/credentials required | ❌ Not performed by this skill; route the user there |

Passing tier 1 diagnostics do not parse the emitted dbt project — that's what tier 2 is for.
Passing tier 2 does not mean data is correct — that's tier 3, which requires a real warehouse
connection and lives entirely outside the hub.

### Ask which platform to target before the first tier-2 run

`--platform` is required and has no default — the CLI will not guess it. Currently only two
platforms are supported: **Microsoft Fabric** and **Databricks**. The hub's `kairos.yaml`
`adapter:` field is a hint (the platform the compiler emits for), but on the first `validate-dbt`
invocation in a session, confirm the target with the user rather than assuming — a hub can be
configured for one adapter while the user actually wants to validate against another, or may not
have set one yet. Ask once (e.g. "Which dataplatform should I validate the dbt project against —
Microsoft Fabric or Databricks?"), then reuse that answer for the rest of the session; do not
re-ask on every subsequent tier-2 run unless the user changes scope or `kairos.yaml` disagrees.

### Prerequisites for tier 2 (`validate-dbt`)

`dbt` is **not** installed by default in the hub. It ships only as opt-in `uv` extras in the
hub's `pyproject.toml` (pinned `dbt-core>=1.9,<1.10` plus the matching adapter). Once the
platform is confirmed, check whether it is already synced; if `kairos-ontology validate-dbt`
fails preflight with "not installed", the fix is always one of:

```powershell
uv sync --extra dbt-validate-fabric      # dbt-core + dbt-fabric
uv sync --extra dbt-validate-databricks  # dbt-core + dbt-databricks
uv sync --extra dbt-validate             # dbt-core + dbt-fabric (generic/default)
```

Never suggest a global `pip install dbt-core` — the pinned extra keeps the dbt-core version
aligned with the adapter the hub actually emits for.

The canonical compiler is the authority for entity resolution, typed expressions, contracts,
relationships, adapters, and artifact planning. Do not edit Turtle without the ontology skill.
