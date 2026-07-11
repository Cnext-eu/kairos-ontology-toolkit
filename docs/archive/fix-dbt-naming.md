# Fix: dbt Projector Must Respect `silverColumnName` for Datatype Properties

## Problem Statement

The dbt projector (`medallion_dbt_projector.py`) derives silver column aliases for
**datatype properties** purely from the property URI local name converted to snake_case.
It ignores the `kairos-ext:silverColumnName` annotation for datatype properties, even
though the silver DDL projector (`medallion_silver_projector.py`) already respects it.

This means reference model silver-defaults (which declare standard column names via
`silverColumnName`) have **no effect** on the dbt SQL output for datatype properties —
defeating the purpose of having an ontology-driven naming convention.

### Example

Given a domain property:
```turtle
cargo:orderedTotalWeightValue a owl:DatatypeProperty ;
    rdfs:domain :GoodsItem ;
    rdfs:range xsd:decimal .
```

And a reference model silver-defaults file declaring:
```turtle
cargo:orderedTotalWeightValue
    kairos-ext:silverColumnName "ordered_weight" .
```

**Expected dbt output:**
```sql
TRY_CAST(ordered_total_weight_value AS DECIMAL(18,4)) as ordered_weight
```

**Actual dbt output (current behaviour):**
```sql
TRY_CAST(ordered_total_weight_value AS DECIMAL(18,4)) as ordered_total_weight_value
```

The silver DDL projector correctly outputs `ordered_weight` because it reads the
annotation. The dbt projector does not.

---

## Root Cause Analysis

### File: `src/kairos_ontology/projections/medallion_dbt_projector.py`

### Function: `_resolve_mapped_columns()` (line ~1393-1394)

```python
prop_name = extract_local_name(str(prop))
col_name = _camel_to_snake(prop_name)
```

The column name is always derived from the property URI fragment converted to snake_case.
There is no check for `kairos-ext:silverColumnName`.

### Contrast with silver projector

**File:** `src/kairos_ontology/projections/medallion_silver_projector.py` (line ~958-960)

```python
col_name_override = _str_val(graph, prop, KAIROS_EXT.silverColumnName)
col_name = col_name_override or (
    _camel_to_snake(prop_local) if naming_conv == "camel-to-snake" else prop_local.lower()
)
```

The silver projector checks `silverColumnName` first, and only falls back to
camelCase→snake_case if no override is declared.

### Why the annotation IS available in the graph

The dbt projector entry point (`generate_dbt_project()`, line ~2944) already merges
reference model defaults into the working graph:

```python
graph = merge_ext_graph(
    graph, silver_ext_path,
    fallback_paths=ref_model_defaults,   # ← ref model silver-defaults loaded here
    peer_ext_paths=peer_ext_paths,
)
```

So `silverColumnName` annotations from:
- The hub's own `*-silver-ext.ttl` (highest priority)
- Reference model `*-silver-defaults.ttl` files (fallback)

…are all present in the graph. They're simply never read for datatype properties.

---

## Proposed Fix

### Change 1 (Primary): `_resolve_mapped_columns()` — read `silverColumnName` override

**Location:** `src/kairos_ontology/projections/medallion_dbt_projector.py`, function
`_resolve_mapped_columns()`, approximately line 1393-1394.

**Current code:**
```python
prop_name = extract_local_name(str(prop))
col_name = _camel_to_snake(prop_name)
```

**Replace with:**
```python
prop_name = extract_local_name(str(prop))
col_name_override = graph.value(URIRef(str(prop)), KAIROS_EXT.silverColumnName)
col_name = str(col_name_override) if col_name_override else _camel_to_snake(prop_name)
```

**Note:** `URIRef` is already imported (used elsewhere in the file). `KAIROS_EXT` is
imported from `.shared`. No new imports needed.

---

### Change 2: Schema YAML generation — apply same override

The function that generates `_*__models.yml` schema files also derives column names
from property URIs. Search for all occurrences of this pattern in the file:

```python
_camel_to_snake(extract_local_name(str(prop)))
```

or:

```python
_camel_to_snake(extract_local_name(str(path)))
```

These occur around lines **697**, **717**, and **775** (in `_build_schema_models_yaml`
or related helper functions).

**At each site, apply the same pattern:**
```python
# Before (example):
col_name = _camel_to_snake(extract_local_name(str(path)))

# After:
_prop_local = extract_local_name(str(path))
_col_override = graph.value(URIRef(str(path)), KAIROS_EXT.silverColumnName)
col_name = str(_col_override) if _col_override else _camel_to_snake(_prop_local)
```

**Alternative (DRY):** Extract a helper function:

```python
def _resolve_column_name(graph: Graph, prop_uri: str) -> str:
    """Resolve the silver column name for a property.

    Uses kairos-ext:silverColumnName if declared (from silver-ext or ref-model
    defaults), otherwise falls back to camelCase→snake_case of the URI local name.
    """
    override = graph.value(URIRef(prop_uri), KAIROS_EXT.silverColumnName)
    if override:
        return str(override)
    return _camel_to_snake(extract_local_name(prop_uri))
```

Then replace all `_camel_to_snake(extract_local_name(str(prop)))` calls with
`_resolve_column_name(graph, str(prop))`.

---

### Change 3: Verify `naturalKey` compatibility

The `_get_natural_key()` function reads `kairos-ext:naturalKey` values which are
string literals (e.g., `"goods_item_id"`). These are used directly in SK/IRI
expressions.

**If a `silverColumnName` override renames a natural key column**, there would be a
mismatch — the naturalKey annotation says `"goods_item_id"` but the column in the
SELECT is now aliased as something else.

**Options:**
1. **Document the rule** (simpler): `naturalKey` values must always match the **final**
   column name (i.e., the overridden name if `silverColumnName` is declared).
2. **Add a resolution step** (more robust): After resolving all mapped columns, map
   naturalKey values through any `silverColumnName` overrides. This means building a
   lookup: `{default_snake_name → overridden_name}` and applying it to naturalKey.

**Recommended:** Option 1 for now (document), with Option 2 as a follow-up if users
find it confusing. The silver projector uses the same convention (naturalKey must match
the final column name).

---

### Change 4: Enum label columns

When generating `_label` columns for enum-typed source columns (line ~1484):

```python
columns.append({
    "expression": case_expr,
    "target_name": f"{col_name}_label",
})
```

This already uses the (now potentially overridden) `col_name`, so no additional change
needed here — it will naturally follow the override.

---

### Change 5: Tests

Add a scenario test that verifies the fix:

**File:** `tests/scenarios/test_scenario_dbt.py` (or new file)

**Test case:**
1. Add a `silverColumnName` annotation to a datatype property in the acme-hub
   silver extension (e.g., in `tests/scenarios/acme-hub/model/extensions/`).
2. Run the dbt projection.
3. Assert the generated SQL uses the overridden column name as the alias.
4. Assert the YAML schema also uses the overridden name.

**Example fixture addition** (in acme-hub silver-ext):
```turtle
client:registrationNumber
    kairos-ext:silverColumnName "reg_no" .
```

Then verify the dbt SQL contains `... as reg_no` instead of `... as registration_number`.

---

## All Affected Locations (for grep/search)

| File | Function/Section | Line(s) | Pattern to find |
|------|-----------------|---------|-----------------|
| `medallion_dbt_projector.py` | `_resolve_mapped_columns()` | ~1393-1394 | `col_name = _camel_to_snake(prop_name)` |
| `medallion_dbt_projector.py` | Schema YAML generation | ~697 | `col_name = _camel_to_snake(extract_local_name(str(path)))` |
| `medallion_dbt_projector.py` | Schema YAML generation | ~717 | `col_name = _camel_to_snake(extract_local_name(str(path)))` |
| `medallion_dbt_projector.py` | Schema YAML generation | ~775 | `tests_by_col[col_name] = tests` (uses col_name from above) |
| `medallion_dbt_projector.py` | `_build_sk_expression` / `_build_iri_expression` | ~1286-1308 | No change needed (uses naturalKey strings directly) |

---

## Imports Required

None — all required symbols (`URIRef`, `KAIROS_EXT`, `extract_local_name`, `Graph`) are
already imported at the top of `medallion_dbt_projector.py`.

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Breaking existing projections that have no override | No risk — without annotation, falls back to existing behaviour |
| naturalKey mismatch | Document that naturalKey must use final column name |
| Inconsistency with gold projector | Gold projector uses its own column naming — separate concern |
| Performance | Single `graph.value()` call per property — negligible |

---

## Verification

After implementing:
```bash
# Run all scenario tests
py -m pytest tests/scenarios/ -v

# Run full test suite
py -m pytest

# Manual check: project a domain that has silverColumnName on datatype props
uv run kairos-ontology project --target dbt --domain cargo
```

Inspect the generated SQL in `output/medallion/dbt/models/silver/` and confirm column
aliases match the `silverColumnName` values from the silver-ext or reference model defaults.
