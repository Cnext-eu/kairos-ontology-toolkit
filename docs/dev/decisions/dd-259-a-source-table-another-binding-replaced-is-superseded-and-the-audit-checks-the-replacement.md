# DD-259: A source table another binding replaced is `superseded`, and the audit checks the replacement

**Status:** Accepted
**Date:** 2026-10-18
**Affects:** `core/source_disposition.py` (`DISPOSITIONS`, `CASCADING_DISPOSITIONS`,
`NON_GENERATING_DISPOSITIONS`, the DD-164 audit, `record_dispositions`),
`core/deferred_backlog.py` (`RULED_OUT`), `source-disposition set --superseded-by`, the how-to
[Use reference data and code lists](../../guide/how-to/use-reference-data.md) (section 7) and
the `kairos-design-source` skill. Extends DD-164 and the #881 cascade rule.
**Issue:** #1136

### Context

[DD-257](dd-257-a-reference-list-is-shipped-loaded-by-the-hub-or-owned-by-a-source-and-its-extensions.md)
tells a hub to bind a shipped reference list through a generated seed. A production
logistics hub had already bound three such lists from tables:
- Rec 19 and ISO 4217 from Bronze tables it had imported (`reference_data.transport_mode`,
  `reference_data.currency`);
- Incoterms from both `reference_data.incoterm` and an operational system's own table
  (`intris.intris_incoterms`).

Moving each binding to its seed left the old table with business data in its columns and
no binding. The DD-169 gate then failed on those columns. None of the five dispositions
was true of the table:

| Disposition | Why it is wrong here |
|---|---|
| `bound` | Nothing binds the table any more. |
| `registered-extension` | No new property is needed. |
| `deferred` | Nothing will ever model it: it was replaced. |
| `not-business-data` | It is business data. |
| `blueprint-gap` | The reference model lacks nothing. |

The hub retired each table by hand across nine files: the vocabulary, the samples, the
ledger, affinity, anchors, alignment and the gap-decision sheet. For the operational
system that edit does not last. Its next `import-source` and `analyse-sources` restore the
table, and the gate fires again. Only a recorded decision survives a re-import.

The #881 history sets the bar. A table-grain value that clears the column gate on a
reason nothing checks is how 40 `deferred` rows once retired 1,643 columns unseen.

### Decision

**A table whose rows another EntityBinding now supplies is recorded `superseded`, with
`superseded_by` naming that binding. The value clears the table's columns from the gate
only while the named binding exists, and no binding may still read the table.**

1. **Table grain only.** A table is replaced, not one of its columns. A column-grain
   `superseded` row is refused.
2. **`superseded_by` is a binding's `metadata.name`.** It is not a class or a seed name:
   - the binding is what the hub authors, and what makes the rows reach Silver;
   - the toolkit can check that it exists without loading the ontology.
3. **Checked when recorded.**
   - The named binding must exist.
   - The table must not be bound. A table a binding still reads reaches Silver, so it has
     not been replaced.
   - A rationale is required, as for every value that removes something from review.
4. **Checked again on every audit.** The DD-164 audit (`validate`) reports
   `disposition.superseded-by-unknown-binding` as a blocking error when the named binding
   no longer exists. A row that claims a replacement nobody can find does not quietly keep
   the columns decided. The existing `disposition.bound-and-ruled-out` error catches a
   superseded table that is bound again.
5. **What it joins.**

   | Set | Effect |
   |---|---|
   | `CASCADING_DISPOSITIONS` | the table's gap columns are decided |
   | `NON_GENERATING_DISPOSITIONS` | `generate-bindings` drafts no binding for it |
   | `deferred_backlog.RULED_OUT` | the backlog counts its columns as ruled out, not deferred |

   Schema-catalogue screening and anchoring treat it like any other recorded disposition:
   recording it changes neither.
6. **Not specific to reference data.** An old system's table replaced after a migration is
   the same case, and the wording says so.

### Consequences

- A hub records one ledger row per replaced table instead of editing nine files. The source
  system's next import does not undo it.
- The table may stay in Bronze while the dataplatform still loads it. Removing the
  loader, and the vocabulary with it, is the dataplatform's next step and needs no
  toolkit command.
- Renaming the replacing binding breaks `validate` until the ledger row is updated. The
  break is deliberate: the row's claim must stay true.

### Alternatives rejected

| Option | Why rejected |
|---|---|
| A `retire-source-table` command that deletes the table from the vocabulary, samples and every `_analysis` file | Undone by the next `import-source` of an operational system. It may still be useful later, as a tidy-up once the loader is gone. |
| `superseded_by` as a class IRI | It needs the ontology to check, and a class can be bound by several bindings or by none. The binding is the fact that makes the replacement true. |
| `superseded_by` as free text | That repeats #881: a cascade that clears the gate on a claim nothing checks. |
| Reuse `not-business-data` with a rationale | It states something false about the data, and every reader of the ledger takes it at its word. |
