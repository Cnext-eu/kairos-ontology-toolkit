# DD-008: Generated Macros Alongside Models

**Status:** Accepted
**Date:** 2026-04-30
**Affects:** dbt output structure, `macros/` folder generation
**Implementation:** `templates/dbt/macros/kairos_*.sql`

### Context

Silver models need platform-abstraction macros. How to deliver them?

### Decision

Generate a `macros/` folder inside the dbt output directory with:
- `kairos_safe_cast(column, type)` — platform-aware TRY_CAST
- `kairos_json_extract(column, path)` — JSON_VALUE vs GET_JSON_OBJECT
- `kairos_surrogate_key(columns)` — dbt_utils wrapper
- `kairos_concat(values)` — string concatenation

Macros use `{% if target.type == '...' %}` for platform dispatch.

### Rationale

- No external package dependency beyond dbt-utils
- Macros versioned with generated output
- Hub repos don't need separate dbt package installs
- Regenerated with `kairos-ontology project`
