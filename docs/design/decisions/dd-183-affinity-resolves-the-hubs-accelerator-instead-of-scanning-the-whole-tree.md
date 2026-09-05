# DD-183: Affinity resolves the hub's accelerator instead of scanning the whole tree

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `analyse-sources`
**Implementation:** `cli/sources.py`

### Context

Affinity classifies each source table into a data domain. Given an accelerator it
uses the blueprint's governed domains; given none it falls back to globbing every
TTL under the reference-models tree and treating each directory group as a
candidate domain.

That fallback was never sound, and reference-models v1.28/1.29 made it obvious by
adding 80 TTL files. A run without `--accelerator` reported:

    📊 Resolved 274 domain(s) (12501 classes, 29089 properties)
       • Partnerships Ontology …  • ACTUS Challenge Examples Ontology …
       • 1.2.0 …  • current …  • deferred-relationship …

FIBO, ACTUS, the pattern library and version strings, offered as domains alongside
`party` and `financial`. 75 tables were classified against those 274 candidates,
and 8 of the 19 resulting domains — `shipment-journey`, `track-and-trace`,
`transport-order`, `revenue-yield`, `cost-accounting`, `vessel-registry`,
`container-operations`, `carbon` — are reference-model *module* names that no
blueprint domain owns.

What makes this dangerous is that the output looks entirely normal. The affinity
file has the same shape either way, and nothing downstream can tell a governed
domain from a scanned directory name. The same run with `--accelerator logistics`
produced 22 domains and assignments closely tracking the previous baseline
(financial 17→16, booking 11→7, consignment 4→5).

The hub already declares `[tool.kairos].accelerator = "logistics"` — the same
setting DD-181 reads for cross-domain bridges. Affinity simply never consulted it.

### Decision

When `--accelerator` is absent, `analyse-sources` resolves the hub's declared
accelerator through `resolve_hub_accelerator` (DD-125) — the shared path `validate`,
`project` and DD-181 already use — with any `--domains` filter as a hint. Inference
only fills a gap; an explicit flag is never overridden, and the output states which
of the two applied.

If nothing resolves, the fallback still runs but says plainly, on stderr, that
classification is against every ontology in the tree rather than the blueprint's
governed domains, and names both remedies.

### Consequences

This is the second defect of the same shape in one session: DD-181's bridge loader
also silently took the alphabetically-first accelerator pack when none was
resolved. Both produced plausible output from the wrong vocabulary. The pattern
worth naming is that a *default* which quietly widens scope is more dangerous than
one that fails — a failure gets investigated, a wrong-but-shaped-right answer gets
consumed.

The remaining exposure is that the fallback still exists. It is retained because a
hub with no accelerator is a legitimate configuration, but it is now loud rather
than silent.
