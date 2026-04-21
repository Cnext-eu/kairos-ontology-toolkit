# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| latest  | :white_check_mark: |
| < latest | :x:               |

We only provide security fixes for the latest released version.

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Instead, report vulnerabilities privately by emailing **security@cnext.eu**.

Please include:

- Description of the vulnerability
- Steps to reproduce
- Impact assessment
- Suggested fix (if any)

## Response timeline

- **Acknowledgement:** within 3 business days
- **Initial assessment:** within 7 business days
- **Fix release:** as soon as practical, typically within 30 days for
  confirmed vulnerabilities

## Disclosure policy

We follow coordinated disclosure. We will:

1. Confirm the vulnerability and determine its impact
2. Develop and test a fix
3. Release the fix and publish a security advisory
4. Credit the reporter (unless they prefer anonymity)

We ask reporters to allow reasonable time for a fix before public disclosure.

## Scope

This policy covers the `kairos-ontology-toolkit` Python package and its
associated FastAPI service. It does not cover:

- Third-party dependencies (report those to their respective maintainers)
- Ontology content authored by users of the toolkit
- Infrastructure hosting the service (contact your own infrastructure team)
