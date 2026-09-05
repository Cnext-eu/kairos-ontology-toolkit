# DD-030: rewriteURI Catalog Resolution with Extension Fallback

**Status:** Accepted
**Date:** 2026-05-29
**Affects:** `src/kairos_ontology/catalog_utils.py` (CatalogResolver)
**Implementation:** `CatalogResolver._resolve_via_rewrite()` + `_rewrite_rules` list

### Context

The OASIS XML Catalog standard supports `<rewriteURI>` elements that perform prefix-based
URI-to-path rewriting. FIBO and other large reference ontologies use a single rewrite rule
to map hundreds of ontology URIs to a local directory tree. The toolkit only supported
`<uri>` (exact mapping) elements, causing all FIBO imports to fail with "No catalog mapping
for" warnings.

Additionally, FIBO URIs use trailing slashes (e.g., `.../Agents/`) while the actual files
use `.rdf` extensions (e.g., `Agents.rdf`), so even after prefix rewriting the path doesn't
directly point to a file.

### Decision

1. Parse `<rewriteURI>` elements and store them sorted by descending `uriStartString`
   length (longest-prefix-wins, per OASIS XML Catalog 1.1 §6.5).
2. Apply rewrite rules in `resolve()` only after all exact `<uri>` lookups fail.
3. When the rewritten path doesn't exist as a file, apply an **extension fallback**:
   strip trailing slash, then probe `.rdf` → `.ttl` → `.owl` in order.
4. Only return paths where `Path.is_file()` is True — never return directories.
5. Emit an info-level diagnostic when extension fallback is used; emit a warning when
   multiple extensions match (ambiguity).

### Rationale

- **Longest-prefix-wins** follows the OASIS spec and prevents ambiguous resolution when
  multiple rewrite rules overlap (e.g., a general FIBO rule + a specific FND rule).
- **Extension fallback** is necessary because FIBO URIs use trailing slashes but files use
  `.rdf` extensions — a pure string rewrite cannot produce the correct file path.
- **Fixed priority order** (`.rdf` → `.ttl` → `.owl`) is deterministic and matches the
  publishing conventions of FIBO/OMG/W3C (RDF/XML) while supporting Kairos TTL files.
- **Exact `<uri>` always wins** — this ensures existing catalogs with explicit entries
  are unaffected (zero-cost path for already-working catalogs).

### Consequences

- FIBO and other reference ontologies with `<rewriteURI>` catalogs now resolve without
  requiring per-module `<uri>` entries
- Extension fallback emits diagnostics that flow into `projection-report.json` via
  `CatalogLoadResult` (see DD-030's companion fix for report propagation)
- Ambiguous cases (both `.rdf` and `.ttl` exist) are logged as warnings — users can add
  an explicit `<uri>` entry to override
- No performance concern: rewrite rules are only checked when O(1) dict lookups fail,
  and typical catalogs have 1-3 rewrite rules
