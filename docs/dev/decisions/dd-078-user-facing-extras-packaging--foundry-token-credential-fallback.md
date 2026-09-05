# DD-078: User-facing extras packaging + Foundry token-credential fallback

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `pyproject.toml`, `src/kairos_ontology/ai_provider.py`, scaffold `.env.example` copies
**Implementation:** `pyproject.toml` (`[project.optional-dependencies]` + `[dependency-groups]`), `ai_provider.py::_create_foundry_client`, `tests/test_packaging_extras.py`, `tests/test_ai_provider.py`

### Context

Two related defects broke the Microsoft Foundry AI provider path used by
`analyse-sources` / `propose-alignment`:

1. **Extras installed nothing.** The four user-facing extras (`azure`, `foundry`,
   `flatfile`, `parquet`) were declared **only** under `[dependency-groups]`
   (PEP 735). The documented `pip install kairos-ontology-toolkit[<extra>]`
   resolves `[project.optional-dependencies]`, and dependency-groups are not
   written into wheel metadata — so the install silently resolved nothing and
   `azure` was never importable.

2. **API-key auth crashed the Foundry path.** `_create_foundry_client` wrapped
   `AZURE_FOUNDRY_API_KEY` in `AzureKeyCredential` and passed it to
   `AIProjectClient`. In azure-ai-projects 2.x, `get_openai_client()` mints an AAD
   token via `credential.get_token(...)`; `AzureKeyCredential` has no `get_token`,
   raising `'AzureKeyCredential' object has no attribute 'get_token'`. Every table
   failed and fell back to `mdm`/0.00, producing garbage analysis output.

### Decision

- **Dual-declare** the four user-facing extras in **both**
  `[project.optional-dependencies]` (so the wheel `[extra]` install works) and
  `[dependency-groups]` (for `uv sync --group`). A parity test
  (`tests/test_packaging_extras.py`) prevents drift; `dev` stays group-only.
- **Foundry credential fallback.** Prefer a real `TokenCredential`
  (`DefaultAzureCredential`). When `AZURE_FOUNDRY_API_KEY` is set, attempt
  `AzureKeyCredential` but catch the `AttributeError` from the SDK's token path and
  **fall back to `DefaultAzureCredential`**, with a clear `EnvironmentError` when
  neither credential is usable.

### Rationale

Key auth is fundamentally incompatible with the Foundry SDK's
`get_openai_client()`, so silently requiring a token (or erroring usefully) is
correct. Keeping both extra declarations avoids breaking either pip or uv
workflows. Defensive try/fallback keeps behavior correct across SDK versions.

### Consequences

- `pip install kairos-ontology-toolkit[foundry]` now pulls `azure-ai-projects` +
  `azure-identity`.
- Foundry users authenticate via `az login` / managed identity; a set API key no
  longer breaks the run (it falls back to token auth).
- Extras must be edited in two places — guarded by the parity test.
