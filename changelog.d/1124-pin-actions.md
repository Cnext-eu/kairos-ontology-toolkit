### Security
- **Scaffolded workflows pin every GitHub Action to a commit SHA.** They referenced
  actions by tag (`astral-sh/setup-uv@v10.0.1`, `azure/login@v2`, `actions/checkout@v4`, …).
  Whoever controls an action's repository can move a tag, and so change the code that runs in
  a hub's or dataplatform's CI, including jobs holding Azure credentials and a hub token.
  Security scanners fail pull requests on it. Each `uses:` now names the commit its tag points
  at today, with the release as a comment (`@<sha> # v10.0.1`), so CI runs exactly the same
  code as before. A test keeps every template pinned and every action on one release.
  `update --refresh-workflows` delivers the pinned generation to existing hubs and
  dataplatforms; a workflow declared under `customized-workflows` is left alone.
