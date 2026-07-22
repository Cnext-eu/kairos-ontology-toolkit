# dbt transformation candidates

`candidates.yaml` is the committed, non-executable inventory of imported SQL/dbt
evidence that may require governed transformation assessment.

- Candidate identity is the normalized repository-relative model artifact path.
- Detected facts are deterministic; `assessment` fields are governed decisions.
- `projection_authority` must remain `false`.
- Every non-`unassessed` decision records `assessed_sha256`; a changed checksum requires
  reassessment. A rename creates an orphan and a new candidate.
- An `implemented` decision records `implemented_model_name`, which identifies the discovered
  dbt contract independently of the imported artifact filename.

Use the source-onboarding skill to inventory explicit artifact roots. Do not place executable
dbt models here; implemented contracts belong under `integration/transforms/dbt/`.
