# DD-249: A bound table follows its binding's domain unless a human pinned it

**Status:** Accepted
**Date:** 2026-09-26
**Affects:** `anchor-tables`, and through it `propose-alignment`; `generate-bindings`; the kairos-design-source skill
**Issue:** #1048
**Implementation:** `core/source_disposition.py` (`load_binding_owners`), `core/anchor_tables.py` (`apply_binding_domains`, `BINDING_AMBIGUOUS_FLAG`), `core/generate_bindings.py`

### Context

DD-247 routes each anchored table to a domain through a chain of evidence: affinity among
the anchor's candidate domains, then a hub domain subclassing the anchor, then a secondary
affinity domain that owns it, then the first owner, flagged `owner-ambiguous`. None of
those steps looks at the EntityBindings the hub has already authored. A binding states,
in `metadata.domain`, which domain a source table belongs to; it is the strongest
evidence a hub has, and the chain ignored it. On the Global-Data-Warehouse hub
`cargowise.glbcompany`, `cargowise.orgcuscode` and `intris.intris_orders__fmsdom_party`
were anchored to domains other than the one their binding names.

Two facts shape the answer.

- **A binding domain can be hub-local.** `fracht-company` is a domain the hub declared
  for its own entities; it owns no module in `data-domains.yaml`, so it has no reference
  class pool. `regroup_by_anchor` moves a table into a domain's alignment only when that
  domain has one (`domain_uris_by_id.get(target)`), so routing a table to such a domain
  is a label on the anchors sheet, not a move of its alignment.
- **Humans already pinned some of these rows.** `cargowise.glbstaff` is bound in
  `fracht-company` (`cargowise-fracht-staff-member.binding.yaml`) and pinned by hand to
  `party`. The pin is what took its alignment from 11 to 37 mapped columns: party's class
  pool maps a staff member's columns, fracht-company has no pool at all. Following the
  binding there would have lost that.

Which tables a binding reads is not a flat question either. On GDW, 54 source tables are
bound. Walking every binding's full `dbtModel` `ref()` closure (the walk
`load_bound_relations` uses, correctly, for "is this table bound at all"), 21 of them are
read by more than one binding. Much of that is a merge model that `ref()`s another
binding's selected model to join that entity in: `int_merged__party` refs
`int_merged__fracht_legal_entity`, so the full walk counts `cargowise.glbcompany` as a
party table as well as a fracht-company one.

### Decision

1. **Precedence is pin > binding > the DD-247 chain.** After the chain has produced a
   domain for every row, `run_anchor_tables` applies a deterministic binding pass
   (`apply_binding_domains`, no model call):
   - A row kept verbatim this run -- pinned (`confirmed`/`edited`) or kept by
     `--only-new` -- is never changed. If its domain is not one of its bindings' domains,
     the run reports the disagreement at warning level, naming the binding file:
     `cargowise.glbstaff: pinned to party, bound in fracht-company
     (cargowise-fracht-staff-member.binding.yaml)`. Agreement says nothing.
   - Any other row read by bindings in exactly one domain takes that domain, with
     `domain_basis: binding`, even when the domain owns no module; an `owner-ambiguous`
     flag on it is cleared.
   - A row read by bindings in several domains keeps the chain's domain when it is one of
     them (`domain_basis: binding`). Otherwise the chain's result stands and the row is
     flagged `binding-ambiguous`, with the domains recorded under `binding_domains`, and
     the run asks for a ruling (pin the row with `status: edited`).
   - An unbound table, or one whose bindings declare no domain, is untouched.
2. **The pin wins because it is the only lever for the class pool.** A binding domain
   that is hub-local cannot receive the table's alignment (see Context), so a human who
   pinned the row to the reference domain whose pool maps its columns made the better
   call for alignment, and the binding cannot overrule it. The disagreement warning keeps
   the difference visible, so it is accepted on purpose or re-pinned.
3. **Ownership is an ownership walk.** `load_binding_owners` maps each bound
   `(system, table)` to the `(domain, binding file)` pairs that own it. It walks each
   `dbtModel` binding's `ref()` closure like `load_bound_relations` does, but it stops at
   -- does not read or descend into -- a model that *another* binding selects as its
   `dbtModel.sqlPath`; the tables behind it belong to that binding. The binding's own
   selected model is always read. `load_bound_relations` keeps its full walk, and its set
   is unchanged: every model the ownership walk stops at is some binding's selected model
   and is read by that binding's walk, so the key sets of the two are equal. Memoized
   with the same discipline (digests of every file read plus the input listing).
4. **`generate-bindings` does not draft a duplicate.** A table that a binding file other
   than the one this generator would write already reads is skipped, with the note
   `already bound by <file>`, with or without `--force`. The existing guard only looked
   for the generator's own `<system>-<table>-to-<domain>.binding.yaml`, and only 4 of
   GDW's 47 bindings follow that naming, so every hand-authored binding was invisible to
   it. The generator's own previously written file still reports `exists`, and is
   rewritten under `--force`. It uses the ownership walk, so the note names the binding
   whose entity the table is.

### Measurements (GDW, 2026-09-26)

- 54 bound tables; 21 read by more than one binding under the full walk, 15 under the
  ownership walk. The key sets of `load_binding_owners` and `load_bound_relations` are
  equal (54).
- With the stop rule, `cargowise.glbcompany` is owned by `fracht-company` only.
- 12 tables still span several domains after the stop rule -- they are read directly by
  bindings in different domains, for example `cargowise.jobheader` by consignment,
  financial and fracht-company bindings. Those are the `binding-ambiguous` candidates
  when the chain's domain is none of them; on the current sheet two are
  (`cargowise.jobheader` and `intris.intris_orders_flat`, both anchored to `booking`).
- On the current sheet (108 rows, 6 pinned) the pass routes 45 rows, changes the domain
  of 11 unpinned ones, and reports one disagreement: `cargowise.glbstaff`.
- `generate-bindings --dry-run` on a copy of the hub: before, 34 would-write drafts for
  tables a binding already reads; after, none (53 `already bound by` skips).

### Rejected alternatives

- **Binding over pin.** Simpler, and it would have moved `glbstaff` into a domain with no
  class pool, losing 26 of its 37 mapped columns without anyone deciding that.
- **The full walk for ownership.** It attributes a joined-in entity's tables to every
  merge model that joins it, which turns clear cases (`glbcompany`) into ambiguous ones.
- **Make the binding domain regroup alignment.** A hub-local domain has no reference
  modules to align against; giving it a pool is a separate question about hub-local
  domains, not about routing.

### Consequences

- `domain_basis` gains `binding`, and `flags` gains `binding-ambiguous` (with
  `binding_domains` beside it). Only the unowned count reads `domain_basis`; a `binding`
  row is never counted as unowned.
- A hub-local binding domain is a label: `propose-alignment` still aligns such a table in
  no pool, since `regroup_by_anchor` does not move it. A hub that wants the reference
  pool pins the row to the reference domain and accepts the disagreement warning.
- Routing now depends on the bindings directory. Authoring a binding can move an unpinned
  row on the next run; the `#877` drift summary reports it.
- The anchor copy (`anchor_uri`) is still chosen from the chain's domain; the binding
  pass changes the domain only.
