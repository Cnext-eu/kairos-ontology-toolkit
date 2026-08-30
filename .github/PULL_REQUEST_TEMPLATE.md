## Changes

<!-- Describe what this PR does and why -->

-

## Linked Issues

<!-- Use GitHub closing keywords so issues auto-close on merge.
     Example:  Closes #123   |   Fixes #456   |   Resolves #789
     Note: this repo's auto-close-issues workflow ALSO closes any issue
     referenced in parentheses, like "(#123)", when the PR merges.
     Partial fix of a multi-part issue? Qualify it — "(#123 P2)" or
     "(#123 Problem 2)" — or use "Refs #123", and the issue stays open. -->

Closes #

## Checklist

- [ ] Tests pass (`uv run pytest`)
- [ ] `uv run kairos-ontology validate` passes (if ontology changes)
- [ ] `uv run kairos-ontology project` regenerated (if ontology changes)
- [ ] Version bump only if this PR is cutting a release (see `docs/RELEASING.md`) — not required otherwise
- [ ] DCO sign-off on all commits (`git commit -s`)
- [ ] No secrets, credentials, or PII in code
