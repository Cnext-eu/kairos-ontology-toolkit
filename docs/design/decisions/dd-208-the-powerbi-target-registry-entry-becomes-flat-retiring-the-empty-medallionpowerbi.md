# DD-208: The `powerbi` target registry entry becomes flat, retiring the empty `medallion/powerbi` placeholder

**Status:** Accepted
**Date:** 2026-08-29
**Affects:** `core/projector.py` (`TargetSpec("powerbi", ...)`, master-Gold-ERD path), `cli/
shared.py` (`_V5_OUTPUT_DIRECTORIES`), `cli/setup.py` (`migrate` scaffold `new_dirs`),
`tests/test_target_registry.py`, `tests/test_init.py`

### Context

DD-140 originally placed the Gold/Power BI projection slot at `output/medallion/powerbi/<product>`,
and DD-099's `TargetSpec` registry (`core/projector.py`) carried that nesting forward as
`TargetSpec("powerbi", "medallion/powerbi", OutputCategory.MEDALLION, ...)`. In practice, `emit-gold`
(`cli/emit_gold.py`, `_POWERBI_EMIT_SUBPATH`) never wrote there: it always wrote real Gold PBIP
content — TMDL, PBIP, DAX, `.mmd` ERDs — to the flat, top-level `<publish_root>/powerbi/`, a sibling
of `medallion/dbt` rather than a child of `medallion/`. The `project --target powerbi` graph-projection
path is separately rejected at runtime (`COMPILE_PLAN_ONLY_TARGETS`, "gold and MDM consumers must
receive that compiler-produced CompilePlan through the typed downstream registry"), so the registry's
`medallion/powerbi` subdir was never actually populated by anything. The scaffold (`_V5_OUTPUT_DIRECTORIES`,
`migrate`) mirrored the unused nested path, so every freshly scaffolded or migrated hub grew a stray
empty `medallion/powerbi/.gitkeep` sitting beside the real, populated `powerbi/` one level up — read as
accidental scaffold drift rather than an intentional layout (issue #629).

### Decision

Make the registry agree with what already ships: `TargetSpec("powerbi", "powerbi", OutputCategory.
STANDARD, ...)`, flat at the publish root, matching `neo4j`, `azure-search`, `a2ui`, and `prompt`.
The dead master-Gold-ERD path computation in `run_projections` is updated to the same flat path for
consistency, even though it is unreachable while `powerbi` remains compile-plan-only. `cli/shared.py`'s
`_V5_OUTPUT_DIRECTORIES` and `cli/setup.py`'s `migrate` scaffold both drop the nested placeholder in
favor of a flat `powerbi` entry. `dbt`'s `medallion/dbt` nesting is intentionally left alone — it is
the one target this decision does not re-litigate, since dbt is a retired compiler target (not routed
through this registry for output routing) and changing its layout has a much larger blast radius across
dbt-specific tests and downstream dataplatform consumption (DD-150-era `publish_root` contract).

### Consequences

A fresh or migrated hub now scaffolds exactly one `powerbi/` placeholder, and it is the same directory
`emit-gold` populates — no duplicate, no empty sibling one level down. `gold.output_category` changes
from `OutputCategory.MEDALLION` to `OutputCategory.STANDARD` (metadata only; it does not drive path
resolution). No other target's path changes.
