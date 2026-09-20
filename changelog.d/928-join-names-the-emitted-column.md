### Fixed
- **`propose-relationships` now joins on the column the parent actually emits.** The two
  sides of a relationship join are not in the same namespace: the emitted SQL reads the
  child from the raw source CTE (`src.<local>`) and the parent from the built model
  (`ref(parent).<foreign>`). `join.foreign` was derived from the parent's *source* key,
  so every proposal against a parent that renames its key on the way into Silver — the
  normal case, since a mapped field is emitted under the ontology property's name — named
  a column the parent model does not have. Measured on one hub: a proposal joining
  `parent.ACCOUNT_REF` where the parent emits `party_id` and no `ACCOUNT_REF`. It passed
  `compile --check`, emitted, and `audit-silver-samples` reported no errors, because that
  audit is offline and sample-based; it would have failed only when dbt ran.
- **A parent that does not expose its key at all no longer gets a guessed column name.**
  The fallback rendered the source column in snake_case, producing a plausible-looking
  name for a column that does not exist — in a module whose stated contract is to emit a
  sentinel rather than a guess. Such a match now reports `join_resolved: false` with the
  reason, and carries `<CONFIRM_JOIN_COLUMN>` in both `join.foreign` and the
  `externalReference` key.
- **A pasted proposal no longer fails the compiler's key-equality check.** The
  `externalReference` key and `join.foreign` are now derived from the same value, so they
  match exactly, as `safety.relationship-endpoint` requires. Previously the key was
  lowercased independently of the join, and a proposal pasted verbatim — as the command's
  own advisory instructs — could not compile.
