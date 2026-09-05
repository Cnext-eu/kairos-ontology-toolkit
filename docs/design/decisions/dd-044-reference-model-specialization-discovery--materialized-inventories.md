# DD-044: Reference Model Specialization Discovery & Materialized Inventories

**Status:** Proposed
**Date:** 2026-06-12
**Affects:** `analyse_sources.py`, `propose_alignment.py`, `coverage_report.py`, `inventory.py` (new), `cli/main.py`, DD-032 (amended)
**Implementation:** `src/kairos_ontology/inventory.py`, `src/kairos_ontology/analyse_sources.py`

### Context

Design-time tools (`analyse-sources`, `propose-alignment`, `coverage-report`) only collect
properties where `rdfs:domain` directly equals a class URI. Properties defined on
**subclasses** of a reference model class are invisible to designers, preventing them from
discovering specialization patterns (e.g., that `registrationNumber` belongs to
`Organisation`, a subclass of `Party`).

Additionally, multiple LLM-based tools re-parse the same reference model TTL files
independently, which is wasteful and opaque.

### Decision

1. **Enforced as default strategy** (amends DD-032): `owl:imports` + `silverInclude`
   whitelisting becomes the default for all reference models. Inspired (`rdfs:seeAlso`)
   becomes an opt-in override. This is safe because `silverInclude` (DD-021) prevents
   projection noise from unused imported classes.

2. **Materialized YAML inventories**: A `generate-inventory` CLI command produces YAML
   files in `model/inventory/` containing classes, properties, and specialization trees.
   These are committed to git and consumed by LLM tools.

3. **Specialization semantics**: Descendant properties are **specialization evidence**,
   not inherited properties. In OWL/RDFS, `rdfs:domain ref:Organisation` does not mean
   Party has that property. Specializations produce refinement suggestions
   ("consider aligning to Organisation") but do NOT inflate coverage percentages.

4. **Validation warnings**: Two new checks — "mapped but not whitelisted" and
   "whitelisted but not mapped" — catch mismatches between `silverInclude` annotations
   and SKOS source mappings.

### Rationale

| Alternative | Why rejected |
|-------------|-------------|
| Treat descendant properties as inherited | Semantically wrong in OWL; inflates coverage |
| PropertyIndex + projector refactor | Over-engineered; projectors work correctly |
| Implicit projection from mappings | Risk of "surprise tables" undermines shift-left |
| On-the-fly computation only | Wasteful re-parsing; no designer visibility |

### Consequences

- `parse_reference_model()` gains an `include_specializations` parameter
- `resolve_reference_models()` gains an `include_specializations` parameter
- `coverage-report` has a new "specialization" alignment category (not counted in coverage %)
- `propose-alignment` prompt includes specialization properties for better LLM matching
- `validate_whitelist_mapping()` function added to `validator.py`
- Hub scaffold should include `model/inventory/` directory
- Skills guidance should default to Enforced strategy
