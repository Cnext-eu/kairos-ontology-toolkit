# DD-020: Stable Ontology IRIs — No Version in Namespace

**Status:** Accepted
**Date:** 2026-05-01
**Affects:** all ontology files, `detect_ontology_uri()`, projections, `owl:imports`
**Implementation:** `src/kairos_ontology/projections/shared.py:136-141`, hub ontology conventions

### Context

OWL 2 offers two versioning mechanisms:
1. **`owl:versionIRI`** — encodes the version in the IRI itself (e.g., `https://example.org/ont/1.0.0`)
2. **`owl:versionInfo`** — stores the version as a literal annotation on a stable IRI

In a data-platform context where ontologies drive generated artifacts (dbt models, DDL, Power BI
semantic models, FK scripts), the choice of versioning mechanism has cascading effects on downstream
stability.

### Decision

Use **stable, versionless ontology IRIs** with `owl:versionInfo` as the version annotation.
Do not use `owl:versionIRI`.

```turtle
<https://acme.example/ontology/client> a owl:Ontology ;
    owl:versionInfo "1.0.0" .
```

Version tracking is handled by git tags and releases on the hub repository, not by IRI changes.

### Rationale

| Concern | Why versionless IRIs are better |
|---------|-------------------------------|
| **Generated artifact stability** | Table names, column references, and FK scripts derive from namespace prefixes. Versioned IRIs would change all generated names on every version bump. |
| **`owl:imports` fragility** | Cross-domain imports (`owl:imports <.../client>`) would break when the imported ontology bumps its version. |
| **`detect_ontology_uri()` logic** | The toolkit matches ontology subjects by namespace prefix. Versioned IRIs would require version-aware lookup or regex matching. |
| **Hub git history** | Git already provides complete version history. Embedding version in IRIs duplicates this without benefit. |
| **Downstream consumers** | dbt `ref()` calls, Power BI table names, and search indexes all assume stable identifiers. |

Alternatives considered:
- **Versioned IRI + `owl:versionIRI`**: rejected — too much downstream churn for a data platform use case
- **Version in namespace path** (e.g., `/v1/client#`): rejected — same churn issues, plus complicates prefix declarations

### Consequences

- Ontology files MUST declare `owl:versionInfo` as a string literal for traceability
- Ontology files MUST NOT use `owl:versionIRI`
- Breaking ontology changes are managed via hub release process (CHANGELOG, git tags), not IRI changes
- The `detect_ontology_uri()` helper can rely on simple prefix matching without version parsing
