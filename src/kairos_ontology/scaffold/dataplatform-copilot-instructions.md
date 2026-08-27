# Kairos Dataplatform — Copilot Instructions

## Session greeting

Start the first response with:

> 👋 Welcome to the **Kairos Dataplatform** — a dbt consumer of deterministic
> Kairos v5 compiler artifacts.

## Architecture

The ontology hub authors canonical ontology/source TTL, one closed EntityBinding per source,
optional ordinary contracted dbt SQL/YAML, and optional Gold/MDM policy. Stateless compile
creates one immutable `CompilePlan`; emitted artifacts are pinned and consumed here.

- Never edit compiler-owned output.
- Pin an immutable Git revision or versioned artifact, never a moving production branch.
- Run `dbt deps`, `dbt parse`, `dbt build`, and `dbt test`.
- Use package-qualified `ref()` for generated models.
- Keep downstream-only logic in ordinary dbt models.
- Keep profiles and credentials outside Git.
- Do not treat compile success as release publication or deployment evidence.

Dataplatform setup supports `fabric-lakehouse`, `fabric-warehouse`, and `databricks`;
compiler adapters are `fabric` and `databricks`.

Managed `.claude/skills/` and `.github/copilot-instructions.md` files are refreshed with
`uv run kairos-ontology update`. `.claude/skills/` is read directly by both Claude Code and
GitHub Copilot's Agent Skills support — there is no separate `.github/skills/` copy. For
reversible unreleased testing use `update --test-ref <branch-or-sha>`, then `update --restore`;
neither publishes a release.
