### Fixed
- **Sibling ranking now sees tables bound through dbt models.** In 5.24.2 the ranking of
  deferred columns that complete a bound field (#1068) only knew the fields of
  `source.relation` bindings. A hub that binds through contracted dbt models, the path for
  anything beyond one relation, therefore got almost no candidates: one on a production hub
  where a lineage trace found about 130. A table's bound fields for sibling detection now
  also include:
  - column-grain ledger rows recorded `bound`;
  - columns a binding's dbtModel chain names (`read_by`, DD-250). The chain's output aliases
    and type names are ignored, because only a name the bronze vocabulary, the profile or the
    ledger knows as a column of the table counts. A chain column the ledger keeps `deferred`
    is not treated as bound (the staged-but-unused case).

  The "Completes" column shows the evidence (`read by <model>`, `bound (ledger)`) where the
  property is not known. A shared table-code prefix (`JZ_`, `AH_`) no longer counts as a word
  in common, so `JZ_WeightUQ` stops pairing with `JZ_InvoiceAmount`. Detection is still a
  ranking aid and never records a decision.
