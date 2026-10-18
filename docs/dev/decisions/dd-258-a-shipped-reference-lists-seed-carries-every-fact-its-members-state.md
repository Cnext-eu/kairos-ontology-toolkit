# DD-258: A shipped reference list's seed carries every fact its members state

**Status:** Accepted
**Date:** 2026-10-18
**Affects:** `core/reference_lists.py` and `cli/reference_lists.py`
(`export-reference-list`), the how-to
[Use reference data and code lists](../../guide/how-to/use-reference-data.md), the
`kairos-develop-dbt-transformation` and `kairos-design-mapping` skills. Refines
[DD-257](dd-257-a-reference-list-is-shipped-loaded-by-the-hub-or-owned-by-a-source-and-its-extensions.md).
**Issue:** #1137. The reference models ship ISO 4217 from SIX from 1.42.0
(Cnext-eu/kairos-ontology-referencemodels#128).

### Context

DD-257 made `export-reference-list` write four columns: `code_list`, `code`, `name` and
`iri`. Each list's snapshot version and source went into the seed docs, not the rows.

A production logistics hub bound three shipped lists and immediately needed what the seed
dropped:

- **The list's version.** Its Gold dimensions show a `code_list_version` column. With
  nothing to read, the hub had two options. It could type the snapshot date into the
  contracted model's SQL, where `--all --check` never sees it go stale. Or it could take a
  date from a hub-owned seed, which is a different fact.
- **The members' own facts.** For currencies, the hub hand-maintained a sibling seed of ISO
  numeric codes and minor units.

ISO 4217 from SIX, which the reference models ship from 1.42.0, makes the gap a
correctness problem rather than an inconvenience. Of its 307 members:
- 129 are withdrawn codes, marked `owl:deprecated true` with an `iso4217:withdrawalDate`;
- 304 carry `iso4217:numericCode` and 165 carry `iso4217:minorUnit`.

The four-column seed exported all 307 as ordinary rows. Every withdrawn currency became a
live code, and every attribute the standard publishes was lost.

### Decision

**A generated seed row carries everything the reference models state about its member that
fits in a cell: the list's provenance, whether the code is deprecated, and every datatype
property value.**

1. **Fixed columns.** Every generated seed starts with `code_list`, `code`, `name`, `iri`,
   `list_version`, `list_source` and `deprecated`, in that order.
   - `list_version` is the list class's `owl:versionInfo`. The version is read from the
     class only, never from the ontology header: UN/CEFACT's header says
     `"snapshot 2026-10-17"`, which is not in the class value's format, and both real
     lists carry the value on the class. Empty when the class states none.
   - `list_source` is every `dcterms:source` of the list class, sorted and joined with
     ` | `. It used to keep only the first, which dropped ISO 4217's historic list.
   - `deprecated` is `true` when the member is `owl:deprecated`, otherwise `false`.
2. **Fact columns.** After the fixed columns comes one column per `owl:DatatypeProperty`
   that any member carries, named after the property's local name in snake_case and sorted
   by name.
   - Only declared datatype properties count. Annotations (`skos:altLabel`, notes) and the
     predicates the fixed columns already read are not facts.
   - A member without the fact has an empty cell. Several values share one cell, sorted
     and joined with ` | `; language-tagged values keep the English one, as `name` does.
   - Two properties with one local name, or one named like a fixed column, are refused.
     Renaming one silently would give a binding a column name that the next release could
     change.
3. **A withdrawn code stays a row.** DD-257 already keeps a retired extension because facts
   point at it, and the same holds for a withdrawn standard code. A model that offers codes
   for new data filters on `deprecated`; the governed list does not.
4. **One shape, no flag.** A per-seed flag would make `--all` remember a choice for every
   seed. Every generated seed has the same shape.
5. **Currencies bind `iso4217:CurrencyCode`.** This revises DD-257's "Currencies:
   `unece:CurrencyCodeList`". The UN/CEFACT copy lags ISO: it still lists `ANG`, `BGN`,
   `CUC` and `ZWL` as current and lacks `XAD`, `XCG` and `ZWG`. The reference models
   changed their own guidance the same way in 1.42.0.

### Consequences

- **Every generated seed is stale after the upgrade.** `export-reference-list --all
  --check`, which `pr-validate` runs, reports each one as changed until
  `export-reference-list --all` regenerates it. `diff_seed` compares every column, so a
  seed from before this change reads as "changed" code by code, not as an unexplained
  docs difference.
- **A contracted model that unions `_local` with `select *` breaks** on the column count.
  The how-to now shows the union with named columns and says why. A later release that adds
  a datatype property adds a column the same way.
- A hub binds `list_version` instead of typing a date into SQL, and drops a sibling seed
  whose attributes the list now carries. Sibling seeds remain right for attributes the
  standard does not state, such as a TEU factor.
- No compiled output changes.

### Alternatives rejected

| Option | Why rejected |
|---|---|
| Only `list_version` and `list_source`, as #1137 first proposed | It leaves the withdrawn codes unmarked and the published attributes lost, which is the larger defect. |
| Drop deprecated members from the seed | Facts recorded before the withdrawal point at those codes; the reference join would lose them (DD-257 §6). |
| A separate generated `<name>_lists` seed for provenance | One value per list is normalised, but every contracted model would need another join for a value that changes only with the reference models. |
| Fall back to the ontology header's `owl:versionInfo` | The header and class values have different formats, so one column would mix them. |
| `--with-provenance` flag | Two shapes per command; `--all` would have to record the flag per seed. |
