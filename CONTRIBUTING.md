# Contributing to Kairos Ontology Toolkit

Thank you for your interest in contributing! This project is part of the
**Kairos Community Edition** by [Cnext.eu](https://cnext.eu).

## Developer Certificate of Origin (DCO)

All contributions must be signed off under the
[Developer Certificate of Origin v1.1](https://developercertificate.org/).

By adding a `Signed-off-by` line to your commit messages, you certify that you
wrote the code (or have the right to submit it) and that you agree to release
it under the project's Apache 2.0 license.

```bash
git commit -s -m "feat: add new projection target"
```

This produces a commit message like:

```
feat: add new projection target

Signed-off-by: Your Name <your.email@example.com>
```

> **Tip:** Configure git to sign off automatically:
> `git config --global format.signOff true`

## Getting started

### Prerequisites

- Python 3.12+
- [Poetry](https://python-poetry.org/) for dependency management

### Setup

```bash
git clone https://github.com/Cnext-eu/kairos-ontology-toolkit.git
cd kairos-ontology-toolkit
pip install -e ".[dev]"
```

### Running tests

```bash
python -m pytest
```

### Code style

- **Formatter:** Black (line length 100)
- **Linter:** Ruff
- Source layout: `src/kairos_ontology/`
- All new functions and endpoints must have unit tests

## How to contribute

### Reporting bugs

Open a [GitHub Issue](https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/new)
with:

- Steps to reproduce
- Expected vs actual behaviour
- Python version and OS

### Suggesting features

Open a GitHub Issue with the `enhancement` label describing:

- The use case
- Proposed solution (if any)
- Alternatives considered

### Submitting a pull request

1. **Fork** the repository and create a feature branch:
   ```bash
   git checkout -b feature/my-improvement
   ```
2. Make your changes — follow existing code conventions.
3. Add or update tests for your changes.
4. Run the full test suite: `python -m pytest`
5. Commit with DCO sign-off: `git commit -s`
6. Push and open a Pull Request against `main`.

### Commit message convention

| Prefix | When |
|--------|------|
| `feat:` | New feature or capability |
| `fix:` | Bug fix |
| `chore:` | Maintenance, dependencies, CI |
| `docs:` | Documentation only |
| `ontology:` | Ontology file changes |
| `projection:` | Projection output changes |

### PR checklist

- [ ] Tests pass (`python -m pytest`)
- [ ] `python -m kairos_ontology validate` passes (if ontology changes)
- [ ] `python -m kairos_ontology project` regenerated (if ontology changes)
- [ ] DCO sign-off on all commits
- [ ] No secrets, credentials, or PII in code

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
Please read it before participating.

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE).
