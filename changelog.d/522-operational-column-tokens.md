### Fixed
- **The `operational` column rule no longer sweeps up business data (issue #522).**
  `_OPERATIONAL_PATTERNS` was matched by bare substring, so `timestamp` caught
  `transaction_timestamp`, `pickup_start_timestamp` and `timestamp_posted` — occurrence
  times, which are the central fact of an event or ledger row — while `source_id` caught
  `resource_id` and `_by` caught `owned_by_subco`.

  This matters more than a misreported reason code: `operational` is one of two reason
  codes DD-186 auto-dispositions to `not-business-data` without human review, and that is
  the only disposition which *removes* a column from the DD-169 gate rather than deferring
  it. On one hub, 114 of 185 columns auto-dispositioned from this reason were contradicted
  by the aligner's own output in the same run.

  Matching is now on name tokens with boundaries: `timestamp` alone decides nothing (audit
  intent is carried by the action — `created`, `loaded`, `ingested` — never by the type
  suffix), `by` counts only as a trailing token, and `source id` only as an adjacent pair.

  The vocabulary is `gap_decisions._AUDIT_NAME_TOKENS`, reused rather than copied: the
  gate and the aligner disagreeing about what "audit" means is how this class of bug
  arises. The aligner stays deliberately wider for pipeline artifacts the gate has no
  token for, and a test pins that it is never narrower.

### Notes
- #521's cross-check now withholds fewer candidates, because fewer are misclassified in
  the first place. That is the intended direction: the cross-check is a safety net, not
  the fix.
