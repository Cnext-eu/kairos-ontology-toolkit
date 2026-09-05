# DD-054: Reference-Model Inventories Namespaced by Owning Model

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `generate-inventory`, `check-inventory`, `model/inventory/*.yaml`
**Implementation:** `inventory.py` (`inventory_filename`, `check_inventories`),
`cli/main.py` (`generate-inventory` command)

### Context

Materialized inventories (DD-044) were named purely from the source TTL **stem**
(`{stem}-inventory.yaml`). Many reference models contribute a same-named module —
e.g. `party.ttl` exists in BSP, DCSA, IMO, MMT, TIC, and WCO. All six mapped to a
single `party-inventory.yaml`, so generation was **last-write-wins** (alphabetical
→ WCO survived) and the other five models' classes (`bsp:TradeParty` and its role
subclasses, `imo:MaritimeParty`, `mmt:TransportParty`, …) were silently dropped.
The collision also affected `documents`, `locations`, `events`, and `equipment`.

A modeler trusting the inventory (per DD-046) would conclude those classes don't
exist and recreate them locally — exactly the Gate-6 anti-pattern inventories are
meant to prevent. Contrary to the original bug report, the DD-047 staleness gate
did **not** report a false green: it surfaced the collision as *spurious* `STALE`
entries (the single file's stored hash matched only one source), producing an
**unfixable deadlock** — re-running `generate-inventory` could never clear it —
and a reporting glitch where the same stem appeared in both the `ok` and `stale`
lists.

### Decision

Namespace reference-model inventory files by their owning model via a single
shared helper `inventory_filename(ttl_path, *, ref_models_dir)`:

- Reference-model TTL under `derived-ontologies/` →
  `{model}-{stem}-inventory.yaml` (e.g. `bsp-party-inventory.yaml`), where *model*
  is the path segment directly after `derived-ontologies` (intermediate segments
  such as DCSA's `shared-kernel` are ignored).
- Hub-owned ontologies (`model/ontologies/`) keep `{stem}-inventory.yaml` — their
  stems are unique within a hub.

Both `generate-inventory` and `check_inventories` use this helper so the
source→inventory mapping always agrees, which removes the deadlock and the
double-listing glitch. `generate-inventory` gains a default `--prune` that removes
inventory files no longer produced by any source (self-heals legacy stem-named
files), and aborts loudly on any residual same-name collision rather than silently
overwriting.

### Rationale

Per-model filenames give each source TTL a 1:1, sha-verifiable inventory — the
simplest scheme that keeps the DD-047 freshness check sound. The alternative
(merging same-domain modules into one file with per-class provenance) was rejected
as more complex for the freshness gate. Consumers (`propose-alignment`,
`coverage-report`) already glob and merge **all** `*.yaml` in `model/inventory/`,
so they transparently pick up the now-complete set with no code change.

### Consequences

- Existing hubs must re-run `generate-inventory`; `--prune` deletes the stale
  stem-named files and writes the per-model set (commit the result).
- Supersedes the stem-keyed naming established in DD-044 and hardens DD-047.
- Any future same-model/same-stem collision is a loud error (a deterministic
  disambiguation guard can be added if such a case ever arises).

### Amendment (2026-08-14): the collision was not loud, and `--prune` deleted good inventories

Two claims above did not hold in the implementation. Recording both, and what replaced them.

**"Aborts loudly on any residual same-name collision" was not true.** The generator printed a `❌ Inventory
name collision … Report this (DD-054 disambiguation gap)` line to stderr and then `continue`d, touching no
counter and no exit code — a `❌` in a command that exits 0. The colliding source was silently absent from
the run, and because the *checker* still enumerated it and compared against the winner's stored hash, the
losing key was reported **permanently `STALE`**: unfixable by any number of `generate-inventory` runs (#406).
A collision now routes to a real failure bucket and blocks, which is what this DD always claimed.

**The collision was not a two-file accident, and the root cause is here in the naming rule.** `_ref_model_id`
namespaces only paths containing a `derived-ontologies` segment, so a reference-model TTL outside that tree
falls through to bare `{stem}-inventory.yaml`. Every `blueprints/patterns/*/template.ttl` therefore collapses
to the same `template-inventory.yaml` — the collision scales with the pattern library. Those files are
copyable stubs carrying `https://example.org/` placeholder namespaces and deliberately no `owl:versionInfo`;
a semantic-index inventory of one has no consumer. They are now **excluded from inventory enumeration**, in
`iter_reference_inventory_sources` rather than at any call site, so generator and checker agree by
construction (the same reason the `archive/` exclusion lives there).

**`--prune` was a data-loss path, and the obvious guard would not have closed it.** Prune unlinked every
`*-inventory.yaml` absent from the set of files the run wrote. Two ways that set was wrongly incomplete:

1. a source that **failed** never entered it, so its previously-good committed inventory was deleted —
   turning a transient closure failure into a `missing` on the next check, i.e. the fix command destroyed the
   evidence that the source had ever been fine;
2. worse, **scope**: only *one* of the ontology / reference-model roots need resolve, so a run scoped to the
   hub alone reported **zero failures** and deleted every reference-model inventory, with no warning at all.

Because of (2), gating prune on "no failures this run" is insufficient — that path has no failures. Prune is
now defined by what the run could positively account for: it **hard-skips with an explanation** when either
scope root was unresolved, and otherwise reuses the checker's own orphan notion, which is built from the
sources it enumerated regardless of parse success. A source that merely fails is still *seen*, so it can
never be mistaken for orphaned.
