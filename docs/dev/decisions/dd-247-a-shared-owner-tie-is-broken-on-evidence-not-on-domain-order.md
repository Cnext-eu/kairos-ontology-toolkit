# DD-247: A shared-owner tie is broken on evidence, not on domain order

**Status:** Accepted
**Date:** 2026-09-26
**Affects:** `anchor-tables`, and through it `propose-alignment` and `generate-bindings`
**Issue:** #1040
**Implementation:** `core/anchor_tables.py` (`derive_domain`, `load_hub_subclass_domains`, `load_affinity_secondary_domains`, `OWNER_AMBIGUOUS_FLAG`)

### Context

`anchor-tables` decides which domain each table goes to, and `propose-alignment` regroups
tables by that decision (`regroup_by_anchor`). `derive_domain` takes the domains that own
the anchor class's module, plus the domains bridging to the class (DD-181). If affinity
names one of those candidates, that one wins. Otherwise it returned the first owner.

Owners are collected in `sorted(data-domains.items())` order, so "the first owner" was
the alphabetically first domain id. In the logistics accelerator, `booking` and
`reference-data` both own the IATA OneRecord `cargo` module. On the
Global-Data-Warehouse hub, 24 party, claims and financial tables anchored to OneRecord
classes (Address, Company, Person, CodeListElement, Value) were routed to `booking`.
`booking`'s alignment pool then held 28 tables and 977 columns against 236 classes, and
its own tables' mapping accuracy dropped: `dtbbookingconfirmation` went from 13 mapped
columns to 4. Nothing in the artifact marked the choice as a guess.

Several modules in the pack have more than one owner: `mmt/transport-means`,
`tic/handling-operations`, `mmt/cargo`, `bsp/documents` and OneRecord `cargo`.

### Decision

A tie between several owners, none of which affinity names, is broken on evidence. If
there is no evidence, the tie is flagged; it is never resolved silently. The order:

1. **`hub-subclass`.** Pick a hub domain whose `model/ontologies/<domain>.ttl` declares
   `rdfs:subClassOf` to a copy of the anchor class. Prefer the affinity domain if it
   qualifies, then an owner, then the lowest id. This may pick a non-owner: a domain that
   subclasses the class imports it, so its pool reaches the anchor.
   - Only `rdfs:subClassOf` counts. `owl:equivalentClass` is not a compile anchor (#730),
     so it is not evidence either.
   - The evidence is read with `ontology_integrity.scan_domain_ontology`, which reads what
     each file itself declares. That is the question being asked, so it is not a DD-243
     closure read.
   - Only domains the blueprint knows are considered. A missing or unparseable file is
     simply no evidence.
2. **`owner+secondary`.** Pick the first of the table's affinity `secondary_domains`
   (DD-042) that is an owner. `anchor-tables` now reads that field, which it used to drop.
3. **Otherwise keep the first owner, with basis `owner`, and flag the row
   `owner-ambiguous`.** The run reports each flagged table with its owners.

Everything that already worked is unchanged:
- A single owner still wins over affinity ("a tie-break, not a veto").
- Affinity among the candidates still wins first.
- Bridges and unowned anchors behave as before.

### Rejected alternatives

- **Keep the affinity domain when it is not an owner.** This was the issue's third signal.
  Affinity names a domain that by definition does not own the anchor's module, so its
  alignment pool may not contain the class. `regroup_by_anchor` would then move the table
  into a pool that cannot map it. Keeping an owner and flagging the row is safe and still
  visible.
- **Blank the domain for a ruling.** `generate-bindings` skips a row with no domain, so
  the table would drop out of the pipeline silently.
- **A design-ruling kind that routes a table.** DD-192 rulings (disambiguation, rejection,
  preference) choose a class, not a domain. Today a ruling is recorded by editing the row's
  `domain` and setting `status: edited` (DD-190 pinning). A routing rule is a possible
  follow-up; it is not part of this decision.

### Consequences

- `domain_basis` gains two values, `hub-subclass` and `owner+secondary`, and `flags` gains
  `owner-ambiguous`. Neither field is validated downstream; only the unowned count reads
  `domain_basis`.
- The fix helps most on a re-run. A fresh hub's ontologies subclass nothing yet, so its
  first run falls through to the secondary-affinity signal or to the flag.
- Routing now depends on the hub's own ontologies. Adding a subclass to `party.ttl` can
  move a table on the next unpinned run, and the `#877` drift summary reports it.
