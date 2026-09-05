# DD-195: The scaffold offers every extra the toolkit ships, including langfuse

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `scaffold/pyproject.toml.template`
**Issue:** #563

### Context

DD-184 added the toolkit's own `langfuse` extra (`langfuse>=4.14.0,<5.0.0`),
which `core/tracing.py` depends on directly. The scaffold template that
generates a client hub's own `pyproject.toml` (`new-repo`/`init`) was never
updated to pass it through — a hub carrying real Langfuse credentials in
`.env` had no way to `uv sync --extra langfuse` at all, and tracing would
silently no-op (its own "off unless configured" path masks a missing
dependency identically to a deliberately-disabled one). Found on a real
client hub (2026-08-19).

### Decision

Add `langfuse = ["kairos-ontology-toolkit[langfuse]"]` to the scaffold
template, in the same bare-requirement shape as every sibling extra
(`azure`, `foundry`, `flatfile`, `parquet`, `otel` — no repeated wheel URL,
per issue #297).

### Consequences

A freshly scaffolded hub can install Langfuse tracing support the same way
it installs any other extra. `tests/test_packaging_extras.py` and
`tests/test_scaffold_toolkit_pin.py`'s `USER_FACING_EXTRAS` widened to
match — which also exercises, for free, the existing guard that the
toolkit's own `pyproject.toml` actually ships every scaffolded extra.
