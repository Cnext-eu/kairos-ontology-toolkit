# DD-012: Non-Fatal GitHub Operations

**Status:** Accepted
**Date:** 2026-04-30
**Affects:** `_configure_branch_protection()`, `_add_reference_models()`
**Implementation:** try/except with warning prints, non-zero exit avoided

### Context

Several operations in `new-repo` depend on external services (GitHub API, network)
or features that may not be available (e.g., branch protection on free plan).

### Decision

GitHub API operations that are **supplementary** (not core to repo creation) use a
**warn-and-continue** pattern:

```python
try:
    subprocess.run([...], check=True)
    print("  ✓ Operation succeeded")
except subprocess.CalledProcessError as exc:
    print(f"  ⚠ Operation failed: {reason}")
    # Continue — don't abort repo creation
```

### Which operations are non-fatal?

| Operation | Fatal? | Rationale |
|-----------|--------|-----------|
| `gh repo create` | ✅ Fatal | Repos must be on GitHub |
| `git init` / `git commit` | ✅ Fatal | Core functionality |
| Branch protection | ⚠️ Non-fatal | Free plan can't use it |
| Reference models submodule | ⚠️ Non-fatal | Not required for a valid hub |
| SmartCoding update script | ⚠️ Non-fatal | Optional enhancement |

### Rationale

- Users shouldn't lose a fully scaffolded repo because branch protection failed
- Clear warning messages tell users what to fix manually
- `--skip-protection` provides explicit opt-out
