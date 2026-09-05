# DD-041: LLM-powered Source Affinity Analysis & Coverage Reporting

**Status:** Accepted
**Date:** 2026-06-04 (updated 2026-07-18)
**Affects:** `analyse_sources.py`, `coverage_report.py`, `ai_provider.py`, CLI,
`kairos-design-source` and `kairos-design-domain` skills
**Implementation:** `src/kairos_ontology/analyse_sources.py`, `src/kairos_ontology/coverage_report.py`, `src/kairos_ontology/ai_provider.py`

### Context

When modeling with the `kairos-design-domain` skill, all source vocabulary is loaded into the
LLM context window. This leads to:
- Context overflow with many sources
- Poor reference model reuse (~18% data property coverage on average)
- No automated correlation between source columns and reference model properties
- No post-modeling feedback loop to measure alignment quality

Name-only matching (tokenized, fuzzy) catches only a fraction of semantic overlaps.
E.g., `arrivalEstimated` ↔ `estimatedArrivalTime`, `MAFINR` ↔ `mafiNumber` require
semantic understanding.

Additionally, reference models are modular (root files declare `owl:imports` to sub-modules).
The original flat `glob("*.ttl")` only found root stubs with almost no class definitions.

### Decision

Introduce two new CLI commands powered by LLM (gpt-5.4-mini, configurable via AI provider):

1. **`analyse-sources`** (pre-modeling) — semantically matches source table/columns against
   reference model domains. Outputs per-source affinity reports to
   `integration/sources/_analysis/`. The modeling skill uses these to scope context
   (only load relevant tables) and seed the Source Evidence Table.

2. **`coverage-report`** (post-modeling) — measures how well the final ontology aligns with
   reference models, with source evidence tracing. Shows class/property coverage %,
   identifies custom vs. industry-standard concepts, and suggests improvements.

**AI Provider abstraction** (`ai_provider.py`):
- Configurable via `KAIROS_AI_PROVIDER=github|azure|foundry` env var
- GitHub Models: `GITHUB_TOKEN` + `https://models.inference.ai.azure.com`
- Azure AI Foundry: `AZURE_AI_ENDPOINT` + `AZURE_AI_KEY` or
  `DefaultAzureCredential`
- Microsoft Foundry: `AZURE_FOUNDRY_ENDPOINT` + `DefaultAzureCredential`
- Both return OpenAI-compatible client (same SDK)

At the beginning of every `kairos-design-source` invocation, the skill asks the
user to select the provider and authentication mode for that invocation. Existing
`.env` configuration is summarized without exposing values and, when complete,
is the recommended default; the user still confirms it before the first LLM call.
The override choices include GitHub Models, Azure AI with a key, Azure AI with
Azure identity, Microsoft Foundry with Azure identity, or skipping AI analysis.
The skill must not silently fall back to another configured provider or
credential mode.

**Recursive reference model resolution** (`resolve_reference_models()`):
- Discovers TTLs recursively (`**/*.ttl`)
- Groups sub-modules by top-level directory (= domain)
- Merges all files in each domain into a single rdflib.Graph
- Skips pure import-stub files
- `--max-domains` CLI option caps LLM calls for rate limit protection

### Rationale

- LLM semantic matching far exceeds tokenized name matching — understands naming conventions,
  abbreviations, sample data patterns, and domain context from labels/comments
- gpt-5.4-mini provides excellent quality at efficient cost for column→property matching
- Pre-analysis scopes the modeling context → better quality, fewer custom classes
- Post-modeling report creates a feedback loop to iteratively improve coverage
- Sample values (from extract-schema) are key input — `BEANR, NLRTM` → Port.unlocode
- AI provider abstraction allows teams to use their existing Azure AI Foundry deployments
- Recursive resolution handles real-world modular reference models (48 files → 8-10 domains)

### Consequences

- AI provider env var is required for source analysis (GITHUB_TOKEN or AZURE_AI_ENDPOINT)
- Provider/authentication consent is invocation-scoped and recorded without secrets
  in the source phase log.
- New prerequisite gate in modeling skill — sources must be analysed before design
- Output stored in `integration/sources/_analysis/` (gitignored or committed per preference)
- Coverage reports in `output/reports/` provide actionable improvement guidance
- `azure-identity` is an optional dependency (`[azure]` extra group)
- `.env.example` scaffolded into new hub repos with provider documentation
