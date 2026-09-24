# Drafts — staged files that should not be extracted

Put a client file here when you want to keep it beside the hub but **do not** want the
discovery step to read it: an outdated deck, a working copy, a duplicate of a document
already under `businessdiscovery/`, a file you have not yet been cleared to use.

> **Location:** this folder lives at the **repository root** (`.import/drafts/`), beside
> `.import/businessdiscovery/` and `.import/powerbi/`. Like them it is gitignored.

## How the toolkit treats this folder

- **Nothing reads it.** `discovery-status`, the `kairos-design-discovery` skill and
  `import-tmdl` never look here.
- **`validate` does not report it.** Every file under `.import/businessdiscovery/` must be
  extracted before `validate` passes (DD-233), and a business document anywhere else
  under `.import/` is reported as misplaced. Files in `drafts/` are neither.

## Moving a file out again

When a draft becomes evidence, move it to `.import/businessdiscovery/` and run
`kairos-ontology discovery-status`. It will be listed as needing extraction.
`kairos-ontology read-document <file>` prints its text for the discovery step.
