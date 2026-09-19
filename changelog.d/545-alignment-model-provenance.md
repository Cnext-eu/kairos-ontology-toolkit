### Added
- **`check-ai-config` now flags a model whose *tier* is wrong for the role (issue #545).**
  It reported `ok` with no caveat for `KAIROS_AI_ALIGNMENT_MODEL=gpt-5.5`, and the run then
  recorded `model_used: gpt-5.4` — which reads as a silent downgrade to a weaker model
  after a provider error. It is not: `--high-accuracy` selects `gpt-5.4` *on purpose* for
  this role, because alignment is deterministic closed-vocabulary matching and a reasoning
  model adds latency and cost without benefit. The configured value was the one at odds
  with the toolkit's own advice, and a parameter rejection can never change the model.

  Reconstructing that took reading `ai_provider.py`. The advisory now says it at
  pre-flight, which is where DD-159 wants it caught, and explicitly pre-empts the
  downgrade reading. It is a note, not a failure — the run works.

- **Alignment artifacts record `model_source` alongside `model_used`.** `high-accuracy-tier`,
  `explicit-model`, `role-env-override` or `default`, so the outcome carries its reason.
  Omitted when a library caller does not supply one, which keeps the previous artifact
  shape.

### Known issues
- `dropped_params` is not yet persisted. A reviewer comparing two runs still has no record
  that one of them ran without `temperature` after a provider rejection. That needs state
  threaded from the provider retry through a threaded fan-out to the artifact, which is a
  larger change than the rest of this and is deliberately left out.
