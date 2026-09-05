# DD-198: AI preflight surfaces a missing SDK as a missing dependency, with a uv-native fix, not as network unreachability

**Status:** Accepted
**Date:** 2026-08-20
**Affects:** `_create_foundry_client`, `_resolve_azure` (`core/ai_provider.py`); `_probe_client`, `preflight_ai_provider`, `AIRolePreflight.is_blocking` (`core/ai_preflight.py`); `check_ai_config_cmd` (`cli/inspection.py`)
**Implementation:** `core/ai_provider.py`, `core/ai_preflight.py`, `cli/inspection.py`, `scaffold/.env.example`
**Issue:** #553

### Context

Two separate problems compounded on hubs missing an optional AI-provider
SDK. First, the remediation text at all three `NotConfigured` raise sites
(Foundry's missing `azure-ai-projects` package, ×2, and Azure's missing
`azure-identity` package) told the operator to `pip install
kairos-ontology-toolkit[foundry/azure]` — the wrong tool for a project this
toolkit itself scaffolds and manages with `uv`. Second, and worse,
`ai_preflight.py`'s `_probe_client` caught that same `NotConfigured`
exception under a generic `except Exception` and rewrapped it as
`Unreachable`, so `check-ai-config` reported a missing SDK as
`STATUS_UNREACHABLE` with a "verify network connectivity" remediation —
actively misleading, since no network call was ever attempted, and burying
the real install hint inside the wrapped error's text instead of surfacing
it as the reported remediation.

### Decision

`core/ai_provider.py` gains a module-local `_extra_install_hint(extra: str)
-> str` returning `f"uv sync --extra {extra}"`, used at all three
`NotConfigured` raise sites in place of the `pip install` text.
`scaffold/.env.example` (and its committed root-repo copy) get the same
uv-native wording in their Azure/Foundry install comments, so a scaffolded
hub's own reference file matches what the CLI itself now says.

`_probe_client` lets `NotConfigured` propagate unchanged instead of
catching it as a generic `Exception`. `preflight_ai_provider` gains a new
`except NotConfigured` branch, ordered before the existing `except
Unreachable`, that reports a new `STATUS_MISSING_DEPENDENCY` status with
`remediation` set directly from the exception's own message — the same
uv-native hint the exception already carries, not a second copy of it.
`STATUS_MISSING_DEPENDENCY` is added to `AIRolePreflight.is_blocking`
alongside the existing blocking statuses, and to `cli/inspection.py`'s
`_STATUS_ICONS` table so `check-ai-config`'s text and JSON output both
render it distinctly from `not_configured`/`unreachable`.

Scope is deliberately limited to the three AI-provider call sites. The
`[flatfile]`/`[parquet]` extras' own `pip install` remediation text
(`field_mapping_report.py`, `import_flatfile.py`) is a different subsystem
with no reported bug and is left untouched, rather than pulled in as
unrelated scope creep.

### Consequences

`check-ai-config --probe` against a hub with the AI provider configured
but the matching SDK not installed now reports `missing_dependency` with
the exact `uv sync --extra ...` command to run, and no longer suggests
checking network connectivity for what is actually a local dependency gap.
No command (`init`, `new-repo`, `update --upgrade`) auto-installs the
matching extra during hub setup — that stretch goal from the issue's own
wording stays a "consider," not implemented here.
