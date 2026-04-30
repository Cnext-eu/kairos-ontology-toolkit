---
name: kairos-ontology-hub-migration
description: >
  Migrate an existing ontology hub from the flat directory layout to the
  grouped model/ + integration/ + output/ structure. Uses the kairos-ontology
  migrate CLI command.
---

<!-- kairos-ontology-toolkit:managed v0.0.0 -->

# Hub Migration Skill

You are helping a user migrate an existing ontology hub repository from the
old flat directory layout to the new grouped structure.

## When to use this skill

- When upgrading a hub repo that was created with toolkit v2.4.x or earlier
- The old layout has `ontology-hub/ontologies/` at the top level (instead of
  `ontology-hub/model/ontologies/`)

## Prerequisites

- Toolkit upgraded to the version that includes the `migrate` command
- Clean git working tree — commit or stash any uncommitted changes first
- Create a feature branch first using **SC-feature-branch**

## Migration workflow

### Step 1 — Preview the migration

```bash
kairos-ontology migrate --check
```

This performs a dry run: it shows which files would be moved and which
directories would be created, without making any changes.

### Step 2 — Execute the migration

```bash
kairos-ontology migrate
```

This moves files and directories from the old layout to the new grouped
structure.

### Step 3 — Refresh managed files

```bash
kairos-ontology update
```

Ensures all managed files (copilot-instructions, skills, workflows) are
up to date with the current toolkit version.

### Step 4 — Validate

```bash
kairos-ontology validate
```

Confirms that all ontology files, SHACL shapes, and extensions pass
syntax and constraint validation in their new locations.

### Step 5 — Re-project

```bash
kairos-ontology project
```

Regenerates all projection outputs (dbt, silver, bronze, etc.) so that
they reference the correct new paths.

### Step 6 — Review and commit

```bash
git add -A
git status
git diff --cached --stat
git commit -m "chore: migrate hub to grouped directory layout"
```

Review the changes carefully before committing. Make sure no files were
left behind in old directories.

### Step 7 — Create a PR

Use **SC-merge-pr** to create a pull request for the migration.

## What the migrate command does

The `migrate` command reorganises the hub into three top-level groups:

| Old location | New location |
|---|---|
| `ontologies/` | `model/ontologies/` |
| `shapes/` | `model/shapes/` |
| `*-silver-ext.ttl` | `model/extensions/` |
| `sources/` | `integration/sources/` |
| `mappings/` | `model/mappings/{system-name}/` |
| `bronze/` | `integration/sources/{system-name}/` (as `{system-name}.vocabulary.ttl`) |
| `output/silver/` | `output/medallion/dbt/` |
| `output/dbt/` | `output/medallion/dbt/` |

Additionally:

- Creates the `model/`, `integration/`, and `output/medallion/` directory
  trees if they do not already exist.
- Removes the `application-models/` directory (ERDs are now generated into
  `output/medallion/dbt/docs/diagrams/`).
- Cleans up any empty old directories after files have been moved.

## Post-migration checklist

- [ ] All ontology files in `model/ontologies/`
- [ ] Silver-ext files in `model/extensions/`
- [ ] SHACL shapes in `model/shapes/`
- [ ] Sources in `integration/sources/`
- [ ] Mappings in `model/mappings/{system-name}/`
- [ ] Bronze vocab in `integration/sources/{system-name}/{system-name}.vocabulary.ttl`
- [ ] `kairos-ontology validate` passes
- [ ] `kairos-ontology project` regenerates successfully
- [ ] No `application-models/` directory remains
- [ ] `.gitignore` no longer ignores `ontology-hub/output/`

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Custom files left in old directories | `migrate` only moves known file types | Move remaining files manually to the appropriate new directory |
| CI/CD pipelines fail after migration | Pipeline config references old paths | Update pipeline YAML to use the new `model/`, `integration/`, `output/` paths |
| Partial migration needed | Some domains already migrated, others not | Run `migrate --check` to see what remains, then move files manually for the partially-migrated domains |
| `validate` fails after migration | Import paths inside TTL files still reference old locations | Update `owl:imports` IRIs if they used relative file paths; the ontology namespace IRIs themselves should not change |
| `.gitignore` still ignores output | Old `.gitignore` rule excluded `ontology-hub/output/` | Remove or update the rule so that `output/medallion/` artifacts are tracked |
