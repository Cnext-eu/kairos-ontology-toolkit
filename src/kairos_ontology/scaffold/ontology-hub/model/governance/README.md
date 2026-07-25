# Release governance

`release-baseline.yaml` is the reviewed DD-114 authority for strict release.
Fresh baselines are intentionally `draft`: an abstract owner role must review
the policy, adapter scope, expected artifacts, and optional hashes before setting
`approval_status: approved`.

Artifact pins use `domain:relative/path` keys when more than one domain emits the
same package-level path. Hashes are lowercase SHA-256 values over the final
written artifact bytes.

Runtime DQ observations may be imported as immutable
`dq-runtime-results.json` evidence. Kairos emits contracts and tests; monitoring,
alerting, result execution, and trend storage remain downstream.
