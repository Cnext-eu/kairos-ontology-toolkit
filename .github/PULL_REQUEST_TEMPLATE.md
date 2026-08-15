## Changes

<!-- Describe what this PR does and why -->

-

## Linked Issues

<!-- Use GitHub closing keywords so issues auto-close on merge.
     Example:  Closes #123   |   Fixes #456   |   Resolves #789
     Do NOT use parenthetical references like "(#123)" — they link but do not close. -->

Closes #

## Checklist

- [ ] Tests pass (`uv run pytest`)
- [ ] `uv run kairos-ontology validate` passes (if ontology changes)
- [ ] `uv run kairos-ontology project` regenerated (if ontology changes)
- [ ] Version bumped in `src/kairos_ontology/__init__.py` (if `src/` changed) or `skip-version` label added
- [ ] DCO sign-off on all commits (`git commit -s`)
- [ ] No secrets, credentials, or PII in code
