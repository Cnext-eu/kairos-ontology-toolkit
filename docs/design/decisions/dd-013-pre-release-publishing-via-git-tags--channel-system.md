# DD-013: Pre-Release Publishing via Git Tags + Channel System

**Status:** Accepted
**Date:** 2026-05-01
**Affects:** `release.ps1`, `.github/workflows/release.yml`, scaffold `pyproject.toml.template`, `cli/main.py` update command
**Implementation:** Tag-based pre-releases, `[tool.kairos] channel` in hub pyproject.toml

> **Superseded in part by [DD-066](dd-066-no-pypi-publishing--git-tag--wheel-url-distribution.md):**
> the toolkit is **never** published to PyPI (the publish job was never wired up and
> has since been removed from CI). References below to "skips PyPI publish" are
> historical — distribution is git-tag / wheel-URL only for *all* releases.

### Context

The toolkit needs a mechanism to publish pre-release versions that hub repos can
opt into for testing before a GA release. Options considered:
1. TestPyPI — adds infrastructure complexity, separate index config
2. Git tags only — simple, already supported by pip's git URL scheme
3. Separate branches — complex merge workflow, version confusion

### Decision

Use **git tag-based pre-releases** with a **channel system**:

| Component | Mechanism |
|-----------|-----------|
| Pre-release tagging | `release.ps1` option [4], tags like `v2.17.0-rc.1` |
| PEP 440 version | `2.17.0rc1` (in pyproject.toml / __init__.py) |
| GitHub Release | Marked as pre-release, skips PyPI publish |
| Channel config | `[tool.kairos] channel = "stable"` or `"preview"` in hub pyproject.toml |
| Resolution | `kairos-ontology update --upgrade` resolves via `gh api /repos/.../releases` |
| Dependency pin | Hub pyproject.toml pins to `@v2.17.0` (tag-based, not `@main`) |

### Version format mapping

| Label | Git tag | PEP 440 |
|-------|---------|---------|
| Release candidate | `v2.17.0-rc.1` | `2.17.0rc1` |
| Beta | `v2.17.0-beta.1` | `2.17.0b1` |
| Alpha | `v2.17.0-alpha.1` | `2.17.0a1` |

### Rationale

- No TestPyPI infrastructure needed — `pip install git+...@tag` works natively
- Channels are per-repo (version-controlled in pyproject.toml), not per-user
- `stable` (default) = existing behavior for production hubs
- `preview` = explicit opt-in for testing pre-releases
- Pre-releases skip PyPI publish (avoids polluting the public index)
- `@main` deprecated in favor of tag pins for reproducibility
