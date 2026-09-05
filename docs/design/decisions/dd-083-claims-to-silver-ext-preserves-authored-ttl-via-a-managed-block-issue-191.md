# DD-083: `claims-to-silver-ext` preserves authored TTL via a managed block (issue #191)

**Status:** Accepted
**Date:** 2026-06-20
**Affects:** `src/kairos_ontology/claim_projection_sync.py`,
`kairos-design-domain` skill
**Implementation:** issue #191 (split from #190 item 6); supersedes the
whole-graph rewrite

### Context

`_rewrite_domain_projection_surfaces` synced the managed `owl:imports` /
`kairos-ext:silverInclude` surfaces by re-serializing the **whole** rdflib graph
(`graph.serialize(destination=…)`). But `model/ontologies/{domain}.ttl` and
`{domain}-silver-ext.ttl` are also **hand-authored** (local subclasses, gap
properties, prefix layout, the DD-072 provenance header). Every sync therefore
stripped comments/header, collapsed prefixes, and reordered triples — one file was
simultaneously tool-owned and human-owned, written by a destructive whole-graph
re-serialize. (This was also the root of the DD-082 item-5 limitation: a scaffolded
provenance header was stripped on the first sync that had approved imported claims.)

Two options from the issue were rejected after auditing the loader:

- **Split into a generated `{domain}-imports.ttl` the authored file imports** —
  the projection loader follows `owl:imports` **direct-only, no transitive walk**
  (`catalog_utils.load_graph_with_catalog`; the no-catalog path follows none), and
  extension discovery is a fixed `*-silver-ext.ttl` glob (`projector._discover_extensions`).
  A generated intermediate import file would not resolve, and a separate includes
  file would not be discovered, without broad loader/discovery/sync changes.
- **Surgical rdflib writer** — rdflib preserves no formatting, degenerating into a
  fragile full-Turtle text patcher.

### Decision

Introduce a **block-delimited managed region**. The tool owns only the triples
between sentinel-comment markers; everything else is authored content preserved
verbatim:

```turtle
# >>> kairos-managed (generated from the Claim Registry — do not edit)
<https://acme.com/ont/party> <http://www.w3.org/2002/07/owl#imports> <https://refmodel.example/ontology/party> .
# <<< kairos-managed
```

- The managed block is regenerated **wholesale as text** with **full URIs** (so it
  is independent of the authored prefix declarations) and appended at the end of
  the file. `_strip_managed_block` removes the prior block; `_compose_managed_file`
  re-stitches authored text + fresh block.
- **No loader/discovery/semantic change.** The file keeps its name and structure;
  rdflib ignores the marker comments on parse, so both the projector and
  `check-claims` (`evaluate_domain_projection_sync`) read it exactly as before.
  `owl:imports` stays directly on the ontology subject (no transitivity needed).
- **Managed vs authored split:** external (non-hub-base) `owl:imports` and imported
  (non-local) `silverInclude` plus the forbidden `silverIncludeImports` bulk flag are
  managed; intra-hub `_foundation`/`_master` imports and local-class `silverInclude`
  stay authored.
- **Steady state is byte-stable** outside the block (idempotent). **Historical legacy
  migration (superseded by DD-100):** the original implementation stripped inline
  managed triples during first sync. Current releases require the explicit,
  backed-up `migrate` conversion instead.

### Consequences

- `claims-to-silver-ext` no longer destroys provenance headers, comments, prefix
  layout, or triple ordering; managed import/include sync is unchanged and still
  enforced by `check-claims`.
- Closes the DD-082 item-5 limitation — a scaffolded header now survives the first
  and subsequent syncs.
- Repeated syncs are idempotent (no marker accumulation).
