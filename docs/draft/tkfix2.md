# Toolkit fix 2: managed-import planner and Silver sync evaluator disagree

**Severity:** High  
**Confidence:** High  
**Toolkit:** `4.7.0rc8`  
**Owner:** `kairos-design-silver` / claim projection sync  
**Impact:** Blocks Consignment `bound-valid`

## Summary

The claim-managed import writer and the Silver-scoped projection evaluator do not
use one stable import authority. The Consignment ontology contains semantic
dependencies selected during governed domain design:

- `https://www.kairosflow.ai/ont/dcsa/shipment-journey`
- `https://www.kairosflow.ai/ont/mmt/consignment`
- `https://www.kairosflow.ai/ont/mmt/party`

The managed planner previously wrote these imports. The Silver sync evaluator now
accepts MMT Consignment but classifies DCSA Shipment Journey and MMT Party as extra.
A second diagnostic also classifies transitive IMO Party and MMT Party as extra.
This blocks the non-writing Silver bound gate even though all three assigned source
tables are mapped.

Removing the imports is not an acceptable workaround. MMT Party provides the
`mmt-party:Carrier` range used by the approved local `operatedByCarrier`
relationship. DCSA Shipment Journey was an explicitly approved contextual
dependency during Consignment domain design.

## Reproduction

From `ontology-hub/`:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"

uv run kairos-ontology check-claims --domains consignment

uv run kairos-ontology check-projection `
  --ontology model\ontologies\consignment.ttl `
  --catalog catalog-v001.xml `
  --accelerator logistics `
  --target silver `
  --platform fabric `
  --scope silver
```

Observed source-coverage result:

```text
consignment: 3/3 tables mapped (100%)
```

Observed blocking diagnostics after canonicalizing the managed block:

```text
Status: BLOCKED
Blocker (silver_sync): extra import
https://www.kairosflow.ai/ont/dcsa/shipment-journey; extra import
https://www.kairosflow.ai/ont/mmt/party

[silver_sync] claims.projection-sync: extra import
https://www.kairosflow.ai/ont/imo/party; extra import
https://www.kairosflow.ai/ont/mmt/party
```

The first run also reported `silverIncludeImports` outside the managed block.
Moving that claim-controlled triple into the final managed block correctly removed
the layout diagnostic, proving that layout and import-authority disagreement are
separate problems.

## Relevant hub evidence

- `ontology-hub/model/ontologies/consignment.ttl`
  - managed DCSA Shipment Journey, MMT Consignment, and MMT Party imports
  - local `operatedByCarrier` range is `mmt-party:Carrier`
- `ontology-hub/model/claims/consignment-claims.yaml`
  - approved carrier relationship decision targets `mmt-party:Carrier`
- `ontology-hub/model/extensions/consignment-silver-ext.ttl`
  - canonical final managed block
  - three approved imported MMT classes are Silver-included
- `ontology-hub/model/mappings/qargo-to-consignment.ttl`
  - three table mappings and eleven direct column mappings

## Root-cause area

Installed source:
`.venv/Lib/site-packages/kairos_ontology/core/claim_projection_sync.py`

`evaluate_domain_projection_sync()` builds a managed import plan and then computes:

```python
expected_imports = set(plan.expected_imports)
managed_imports = actual_imports - authored_imports
status.extra_imports = sorted(managed_imports - expected_imports)
```

See approximately lines 284-355 in `4.7.0rc8`.

This arithmetic is deterministic only when every caller constructs the same
`ReferenceModuleContext` and the plan retains all governed semantic dependencies.
The two different diagnostic sets show that the Silver readiness path evaluates
the same domain with inconsistent expected-import closures or contexts.

There is also an ownership problem in `_is_managed_import()`:

```python
return (
    predicate == OWL.imports
    and iri.rstrip("/") not in hub_domain_bases
    and iri in expected_imports
)
```

An import is treated as managed only when it is still expected by the current
plan. A previously managed import that falls out of a differently scoped plan
therefore loses its managed provenance while simultaneously being reported as
extra. The evaluator cannot distinguish:

1. a stale generated import;
2. an approved authored semantic dependency; and
3. a transitive dependency required by an approved module.

## Required fix

1. **Use one canonical managed-import plan everywhere.**
   `claims-to-silver-ext`, `check-claims`, Silver-scoped `check-projection`, and
   projection must receive the same domain scope, accelerator, catalog, approved
   claims, authored external-term evidence, and activation profile.

2. **Preserve explicit semantic dependency authority.**
   External ontology imports needed by approved relationship targets or explicitly
   approved contextual modules must be included in `plan.expected_imports`.
   Transitive dependencies accepted by the selected module profile must not be
   independently reported as extra.

3. **Track managed provenance independently from current expectation.**
   Determine whether an import is managed from the managed block itself, not from
   membership in the newly computed expected set. Then compare:
   - managed block imports against the canonical plan;
   - authored imports against external-term validity rules.

4. **Emit one diagnostic per domain and cause.**
   The Silver gate should not report contradictory direct and transitive
   `extra import` sets from separate evaluator contexts.

5. **Fail with actionable ownership.**
   If an import truly lacks authority, identify whether the remedy is:
   - approve/register a missing claim;
   - add an explicit contextual-module decision;
   - remove a stale managed import; or
   - repair the accelerator module profile.

## Suggested implementation shape

Introduce a canonical immutable result, for example:

```python
@dataclass(frozen=True)
class ManagedImportAuthority:
    direct_expected: frozenset[str]
    accepted_transitive: frozenset[str]
    authored_semantic: frozenset[str]
    selected_class_uris: frozenset[str]
    diagnostics: tuple[ModuleDiagnostic, ...]
```

Build it once for the requested domain and pass it into every sync/readiness
evaluation. The sync comparison should use:

```python
allowed_imports = (
    authority.direct_expected
    | authority.accepted_transitive
    | authority.authored_semantic
)
extra_managed_imports = managed_block_imports - allowed_imports
```

Do not infer managed ownership from `iri in expected_imports`.

## Regression tests

Add focused tests around `claim_projection_sync.py` and the Silver readiness
composition:

1. An approved imported class claim requires its owning ontology import.
2. An approved object-property relationship to an external range requires the
   range module import even when the target class is not yet Silver-materialized.
3. An explicitly approved contextual module remains allowed without creating a
   Silver table.
4. Accepted transitive imports are not reported as direct extras.
5. A genuinely stale line inside the managed block is reported as extra.
6. A genuinely authored external import is not silently reclassified as managed.
7. `check-claims --domains consignment` and Silver-scoped `check-projection` expose
   the same expected/extra import sets.
8. Repeated evaluation with identical inputs is byte-for-byte deterministic and
   produces one diagnostic per cause.

Use a synthetic Consignment fixture with:

- MMT Consignment as the projected class module;
- MMT Party as an object-property range module;
- IMO Party as an accepted transitive dependency;
- DCSA Shipment Journey as an approved contextual dependency.

## Acceptance criteria

- Consignment keeps all approved semantic imports.
- `check-claims --domains consignment` reports import/include sync.
- Silver-scoped `check-projection` reports no `silver_sync` blocker.
- The three Consignment classes become `bound-valid`.
- A deliberately stale managed import still fails closed with one precise
  remediation.
- No generated dbt SQL needs manual edits.

---

# Toolkit fix 2b: focused Silver validator treats a Windows drive as a URL scheme

**Severity:** High  
**Confidence:** High  
**Toolkit:** `4.7.0rc8`  
**Owner:** `kairos-design-silver` / focused design validation  
**Impact:** Prevents DD-108/DD-109 semantic validation from starting on Windows

## Summary

`validate-silver-ext` hardcodes the expected shape path to:

```text
<hub>\model\shapes\kairos-ext-shapes.shacl.ttl
```

In this hub that managed shape file is absent. The command does not check for the
missing file and offers no `--shapes` option. It passes the absolute Windows
`Path` directly to `rdflib.Graph.parse()`, which interprets `G:\...` as URI scheme
`g`. Shape loading fails before SHACL execution, so the command cannot establish
Silver `design-valid`.

The toolkit's packaged canonical shape exists at:

```text
.venv\Lib\site-packages\kairos_ontology\scaffold\kairos-ext-shapes.shacl.ttl
```

Loading that exact shape content into an in-memory graph and invoking the same
DD-108/DD-109 validation logic passed with zero diagnostics. This proves the
authored Consignment policy is valid and isolates the defect to shape discovery
and Windows path transport.

## Reproduction

From `ontology-hub/` on Windows:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology validate-silver-ext `
  --domain consignment `
  --catalog catalog-v001.xml
```

Preconditions:

- `model\extensions\consignment-silver-ext.ttl` exists;
- `model\ontologies\consignment.ttl` exists;
- `model\shapes\kairos-ext-shapes.shacl.ttl` is absent;
- the packaged canonical shape exists.

Observed behavior:

```text
G:\... is interpreted as URL scheme g
```

No SHACL validation results are produced.

## Root-cause area

Installed CLI source:
`.venv/Lib/site-packages/kairos_ontology/cli/main.py`

`validate_silver_ext_cmd()` hardcodes the hub-local shape at approximately
lines 1963-1993:

```python
result = validate_silver_extension(
    extension_path=hub / "model" / "extensions" / f"{domain}-silver-ext.ttl",
    ontology_path=hub / "model" / "ontologies" / f"{domain}.ttl",
    shapes_path=hub / "model" / "shapes" / "kairos-ext-shapes.shacl.ttl",
    catalog_path=catalog_path,
)
```

Installed validator source:
`.venv/Lib/site-packages/kairos_ontology/core/design_validation.py`

At approximately lines 369-383:

```python
shapes = Graph()
try:
    shapes.parse(shapes_path, format="turtle")
except Exception as exc:
    ...
```

There are two coupled defects:

1. **Shape discovery:** the command assumes the hub-local managed shape exists and
   has no explicit fallback or override.
2. **Path transport:** a missing absolute Windows path reaches rdflib, producing a
   misleading URL-scheme error instead of a precise missing-file diagnostic.

## Required fix

1. **Resolve the shape source before parsing.**
   - Prefer the hub-local managed shape when present.
   - Otherwise use the version-matched packaged canonical shape.
   - Report which source was selected.

2. **Expose an explicit `--shapes` override.**
   Use `click.Path(exists=True, dir_okay=False, path_type=Path)` so an invalid
   caller-supplied path fails before rdflib.

3. **Check all internally constructed paths explicitly.**
   Return a dedicated `silver.shapes-missing` diagnostic when neither hub-local
   nor packaged shapes exist. Do not let a missing filesystem path reach
   `Graph.parse()`.

4. **Use Windows-safe parsing.**
   Parse a resolved file URI or an opened binary stream, for example:

   ```python
   resolved = shapes_path.resolve(strict=True)
   shapes.parse(location=resolved.as_uri(), format="turtle")
   ```

   Alternatively:

   ```python
   resolved = shapes_path.resolve(strict=True)
   with resolved.open("rb") as stream:
       shapes.parse(
           source=stream,
           format="turtle",
           publicID=resolved.as_uri(),
       )
   ```

5. **Keep scaffold/update behavior aligned.**
   New and updated hubs should still receive
   `model/shapes/kairos-ext-shapes.shacl.ttl`; packaged fallback supports older or
   partially migrated hubs without weakening validation.

## Regression tests

1. `validate-silver-ext` loads an existing hub-local shape on Windows.
2. A drive-letter path is converted to a `file:///G:/...` URI or opened directly;
   it is never parsed as scheme `g`.
3. A missing hub-local shape falls back to the packaged canonical shape.
4. `--shapes` accepts an existing absolute Windows path.
5. `--shapes` rejects a missing path at Click validation with a clear message.
6. Missing hub-local and packaged shapes produce `silver.shapes-missing`.
7. Malformed shape Turtle still produces `silver.shapes-load-error`.
8. The Consignment fixture reaches SHACL execution and returns the same result for
   hub-local, packaged-fallback, and explicit shape sources.

## Acceptance criteria

- `validate-silver-ext --domain consignment --catalog catalog-v001.xml` runs on
  Windows when the hub-local managed shape is absent but the packaged shape exists.
- The command reports the selected shape source.
- A missing file never appears as URL scheme `g`.
- The canonical DD-108/DD-109 checks execute unchanged.
- Consignment returns zero focused semantic diagnostics with the packaged shape.
