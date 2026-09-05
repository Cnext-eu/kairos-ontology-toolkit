# DD-024: Hash-Tolerant Catalog Resolution

**Status:** Accepted
**Date:** 2026-05-26
**Affects:** `catalog_utils.py`, import resolution, projection pipeline
**Implementation:** `src/kairos_ontology/catalog_utils.py`

### Context

Ontology IRIs may or may not end with a `#` fragment separator. In RDF/OWL
practice, the ontology IRI (subject of `a owl:Ontology`) and the namespace
prefix used for classes/properties often differ by a trailing `#`:

```turtle
@prefix : <https://example.org/ont/booking#> .
: a owl:Ontology .  # IRI is https://example.org/ont/booking#
```

vs.

```turtle
<https://example.org/ont/cargo> a owl:Ontology .  # IRI without #
@prefix : <https://example.org/ont/cargo#> .       # But classes use #
```

When domain ontologies import reference models, the `owl:imports` URI may
or may not include the trailing `#`, and the XML catalog `name` attribute
may independently include or omit it. This creates silent resolution
failures where the catalog knows about the file but can't match the URI.

### Decision

1. **Convention:** `owl:imports` should reference the ontology IRI as
   declared in the target file. The catalog `name` attribute must exactly
   match the value used in `owl:imports`. Prefer ontology IRIs **without**
   trailing `#`.

2. **Defensive resolution:** `CatalogResolver` normalizes both `#` and `/`
   variants during catalog loading (storing bare, with-hash, and with-slash
   forms). The `resolve()` method tries all variants as fallback.

3. **Diagnostic warning:** When resolution succeeds only via hash fallback,
   a warning is logged advising the user to align their catalog and import
   URIs for clarity.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Strict exact match only | Simple, predictable | Breaks on common IRI variations |
| Normalize on load + fallback (this) | Resilient to real-world inconsistency | Slightly more mappings in memory |
| Always strip `#` | Simpler logic | Loses information, may create false matches |

The normalization approach was chosen because:
- Third-party reference models cannot always be edited
- The mismatch between ontology IRI and import URI is an extremely common
  real-world pattern (especially in hash-namespace ontologies)
- The warning provides a clear path to fix the root cause

### Consequences

- Existing catalogs with exact matches continue to work unchanged.
- Mismatched catalogs that previously caused silent "No catalog mapping"
  failures will now resolve correctly with a diagnostic warning.
- Users are guided to fix the root cause (align catalog `name` with `owl:imports`).
