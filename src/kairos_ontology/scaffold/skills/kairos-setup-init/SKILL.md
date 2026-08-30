---
name: kairos-setup-init
description: Create a fresh v5 Kairos ontology hub using the supported CLI scaffold.
---

# New V5 Ontology Hub

V5 hubs are created fresh; older authoring layouts are not upgraded automatically.

1. Verify Python 3.12+, uv, Git, and authenticated GitHub CLI.
2. From outside another Git repository, choose a lowercase `<name>-ontology-hub` name and company
   namespace.
3. Set `KAIROS_SKILL_CONTEXT=1` and run:

   ```powershell
   kairos-ontology new-repo <name> --company-domain <domain>
   ```

   This also scaffolds the managed root `CICD.md` and `CONTRIBUTING.md` — point new
   users to them for branching, review, and release conventions.
4. Run `uv sync` in the created repository. This installs both the toolkit
   and the reference-models package as Python dependencies.
5. Add a domain with `kairos-ontology init --company-domain <domain> --domain <name>`.
6. Confirm the scaffold contains `model/ontologies/`, `model/shapes/`,
   `integration/discovery/`, `integration/sources/`, `integration/bindings/`,
   `integration/transforms/dbt/models/`, and `kairos.yaml` (derived output is emitted to the
   sibling `ontology-hub-publish/`).
7. Author source inputs, ontology meaning, and closed EntityBinding YAML through their owning skills.
8. Run ontology validation and `kairos-ontology compile <domain> --check --format json`.

Do not copy old hub execution metadata into a v5 hub. Preserve reusable ontology and source meaning
only by reviewing and authoring it against the v5 contracts.
