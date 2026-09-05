# DD-125: Domain-Ownership-Inferred Accelerator Resolution with Diagnostics

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `core/reference_modules.py`, `core/inventory.py`, `cli/main.py`
(`validate`, `project`/`check-projection`, `check-inventory`, `check-claims`)
**Implementation:** `resolve_hub_accelerator_detailed`, `AcceleratorResolution`,
`_accelerator_domain_owners`, `classify_domain_scope`

### Context

Four CLI surfaces each needed to pick one installed accelerator pack (a
`data-domains.yaml`-bearing `accelerator-packs/<name>/client-hub-blueprint/`) for a hub with
multiple packs installed, but only `validate` and `project`/`check-projection` actually
routed through the shared `resolve_hub_accelerator` helper. `check-inventory` had no
`--accelerator` option at all and hardcoded `accelerator=None` into
`resolve_domain_inventory_keys`, silently scoping against whichever pack
`analyse_sources.load_data_domains` happened to glob first (alphabetical). `check-claims`
had a `--accelerator` option but never consulted `[tool.kairos].accelerator` or inference —
it passed the raw CLI value (or `None`) straight into `load_data_domains`, so a hub with
`[tool.kairos].accelerator` configured, or with only one pack unambiguously owning the
claimed domain, could still have `check-claims` silently check a *different* pack's registry
than the one every other command resolved — producing a spurious "registry domain not found
in data-domains.yaml" warning that disagreed with the actual accelerator registry.
Separately, whenever two or more packs were installed and neither `--accelerator` nor
`[tool.kairos].accelerator` was set, `resolve_hub_accelerator` always raised the ambiguity
error, even when the active domain(s) in scope mapped unambiguously to exactly one pack's
`data-domains.yaml` (including domains nested two levels deep under `groups[].domains[]`) —
forcing an unnecessary `--accelerator` flag on every invocation for hubs where the answer was
already inferable from context. Finally, `check-inventory`'s scoped summary printed a bare
`"(none matched)"` for a requested `--domains` token and then still reported the domain
ready, without saying whether readiness came from an accelerator profile, a directly-matched
inventory stem, or neither.

### Decision

`resolve_hub_accelerator` gained a detailed sibling, `resolve_hub_accelerator_detailed`,
returning a frozen `AcceleratorResolution(accelerator, source, data_domains_path)`. The
precedence is unchanged and preserved exactly (explicit `--accelerator` >
`[tool.kairos].accelerator` > inference > ambiguity error; the original error strings —
`"Unknown accelerator {selected!r} from {source}. Available: {choices}"` and "Accelerator
selection is ambiguous. ..." — are byte-for-byte preserved so existing CLI/test assertions
keep working). No new config key was introduced. What's new is a `domain_hint` parameter:
when multiple packs are installed and neither an explicit value nor hub configuration
selects one, `_accelerator_domain_owners` loads each candidate pack's `data-domains.yaml`
via the *same* `analyse_sources.load_data_domains` parser used by
`resolve_domain_inventory_keys` (inventory) and managed-import planning — reusing one nested
`groups[].domains[]` registry parser everywhere so accelerator disambiguation, inventory
scoping, and claim-registry ownership checks never disagree about which pack owns a domain.
If exactly one installed pack owns a hinted domain, it is inferred (`source: "inferred
(domain ownership)"`); if the hint matches zero or more-than-one pack, or no hint is
available, the original hard ambiguity error is still raised — this never silently guesses
among genuinely plausible candidates. `resolve_hub_accelerator` is kept as a thin
backward-compatible wrapper returning only `.accelerator`.

Each of the four CLI commands now supplies a domain hint appropriate to its own scope
(`validate`/`project`/`check-projection`: `--ontology` file stem or all `model/ontologies/
*.ttl` stems; `check-inventory`: the active `--domains` filter; `check-claims`: the active
`--domains` filter, falling back to `model/claims/*-claims.yaml` stems when no filter is
given) and prints the resolved accelerator, its source, and the resolved
`data-domains.yaml` path as text-mode diagnostics (never added to any JSON `to_dict()`
output, so DD-122's versioned claim-check result and other JSON contracts are untouched).
`check-inventory` gained the previously-missing `--accelerator` option.

`core/inventory.py` gained `classify_domain_scope` (plus `DIRECT_PROFILE` /
`ACCELERATOR_PROFILE` / `NO_PROFILE` status constants), replacing the misleading
`"(none matched)"` scoped-inventory line with one of three explicit states per requested
`--domains` token: matched an accelerator `data-domains.yaml` entry that itself resolved
inventory keys (`ACCELERATOR_PROFILE`), matched no accelerator entry but did directly match
one or more already-materialized inventory stems in the report (`DIRECT_PROFILE` — and the
matching key set is now shown, identifying which inventory set makes the scoped result
ready), or matched neither (`NO_PROFILE`).

`check-claims`'s existing `report.unowned` computation in `claim_coverage.py` (and its
result semantics) were **not modified** — the fix is entirely upstream, in *which*
`data_domains` dict gets passed in; the command's `unowned` warning message was only
extended to also print the checked `data-domains.yaml` path for diagnosability.

### Rationale

Consolidating all four commands on one resolver — rather than four independent
call-sites — guarantees cross-command parity by construction: the same explicit
value, the same `[tool.kairos].accelerator`, and the same domain-ownership registry are
consulted everywhere, so a warning from one command can never disagree with another
command's view of which pack is active. Reusing `analyse_sources.load_data_domains` (rather
than a second nested-groups parser) for domain-ownership disambiguation is what makes the
"nested `groups[].domains[]` ownership" fix a single-parser guarantee instead of a
best-effort approximation. Restricting inference to the *unambiguous* case — and still
raising the original hard error otherwise — avoids trading a loud, correct ambiguity error
for a silent wrong guess; a hub whose domains never map unambiguously to one pack sees
exactly the same behavior as before. Keeping the new diagnostics text-only (never JSON) and
leaving `claim_coverage.py`'s result computation untouched avoids colliding with concurrent
claim-gates work on that same JSON surface (DD-122).

### Consequences

- `core/reference_modules.py`: new `AcceleratorResolution` dataclass,
  `_accelerator_domain_owners`, and `resolve_hub_accelerator_detailed`;
  `resolve_hub_accelerator` gained an optional `domain_hint` parameter (default `None`,
  fully backward compatible).
- `core/inventory.py`: new `classify_domain_scope` plus `DIRECT_PROFILE` /
  `ACCELERATOR_PROFILE` / `NO_PROFILE` constants.
- `cli/main.py`: `check-inventory` gained a new `--accelerator` option; `validate`,
  `check-inventory`, and `check-claims` gained text-mode "Accelerator: ... (source: ...)" /
  "Data domains: ..." diagnostic lines; `check-inventory`'s scoped summary no longer prints
  `"(none matched)"`.
- No new configuration key; precedence and existing ambiguity/unknown-accelerator error
  strings are unchanged, preserving CLI compatibility for existing scripts/tests.
- New tests: `tests/test_accelerator_resolution.py` — resolver precedence/inference/
  ambiguity unit tests, nested `groups[].domains[]` registry-parity tests, `check-inventory`
  scoped-wording tests, `check-claims` registry-ownership diagnostics tests, and
  cross-command (`validate`/`project`/`check-inventory`/`check-claims`) resolver-parity
  tests.
