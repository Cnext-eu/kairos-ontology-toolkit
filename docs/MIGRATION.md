# Migration Guide: Flat → Grouped Hub Layout

This guide helps users of existing ontology hub repositories migrate from the
old flat directory layout to the new grouped layout introduced in
**kairos-ontology-toolkit v2.5** (and later).

---

## Directory Comparison

### Old (flat) layout

```
ontology-hub/
├── ontologies/          # Domain .ttl files + *-silver-ext.ttl
├── shapes/              # SHACL constraints
├── mappings/            # SKOS mappings
├── sources/             # Source system reference docs
├── bronze/              # Bronze vocabulary TTL
└── output/              # Generated projections (was gitignored)
    ├── dbt/
    ├── silver/
    ├── neo4j/
    ├── azure-search/
    ├── a2ui/
    └── prompt/
application-models/      # Mermaid ERDs (separate from hub)
```

### New (grouped) layout

```
ontology-hub/
├── model/               # Domain model (ontology-centric)
│   ├── ontologies/      # Domain .ttl files
│   ├── shapes/          # SHACL constraints
│   └── extensions/      # *-silver-ext.ttl projection annotations
├── integration/         # Source system integration
│   ├── sources/         # Reference docs (API specs, SQL DDL)
│   └── mappings/        # SKOS mappings
└── output/              # All projections (committed, not gitignored)
    ├── medallion/       # Medallion architecture
    │   ├── bronze/      # Bronze vocabulary TTL
    │   ├── silver/      # Silver DDL/ERD
    │   ├── gold/        # Gold dimensional models
    │   └── dbt/         # dbt models (bronze → silver)
    ├── neo4j/
    ├── azure-search/
    ├── a2ui/
    └── prompt/
```

**Key changes at a glance:**

| Old path | New path |
|----------|----------|
| `ontologies/` | `model/ontologies/` |
| `ontologies/*-silver-ext.ttl` | `model/extensions/` |
| `shapes/` | `model/shapes/` |
| `sources/` | `integration/sources/` |
| `mappings/` | `integration/mappings/` |
| `bronze/` | `output/medallion/bronze/` |
| `output/silver/` | `output/medallion/silver/` |
| `output/dbt/` | `output/medallion/dbt/` |
| *(none)* | `output/medallion/gold/` |
| `application-models/` | *(removed — ERDs now in `output/medallion/silver/`)* |

---

## Prerequisites

1. **Upgrade the toolkit** to the latest version:

   ```bash
   pip install --upgrade kairos-ontology-toolkit
   ```

2. **Commit any uncommitted work** — the migration moves and deletes files,
   so you want a clean baseline to revert to if needed:

   ```bash
   git status            # check for uncommitted changes
   git add -A && git commit -m "chore: save work before migration"
   ```

3. **Back up your hub** (optional but recommended):

   ```bash
   git tag pre-migration  # lightweight tag for easy rollback
   ```

---

## Automatic Migration (Recommended)

The toolkit includes a `migrate` command that handles the entire process:

```bash
# 1. Preview what will change (dry-run, no files moved)
kairos-ontology migrate --check

# 2. Execute the migration
kairos-ontology migrate

# 3. Refresh managed files (.github/copilot-instructions.md, etc.)
kairos-ontology update

# 4. Verify ontologies still parse and pass SHACL validation
kairos-ontology validate

# 5. Regenerate all projections under the new output paths
kairos-ontology project

# 6. Commit the result
git add -A && git commit -m "refactor: migrate hub to new layout"
```

> **Tip:** Run `kairos-ontology migrate --check` first and review the output
> carefully. It lists every file move, directory creation, and deletion.

---

## Manual Migration (Step-by-Step)

If you prefer full control, run the following shell commands from the root of
your hub repository.

### Step 1 — Create the new directory structure

```bash
mkdir -p model/ontologies model/shapes model/extensions
mkdir -p integration/sources integration/mappings
mkdir -p output/medallion/bronze output/medallion/silver
mkdir -p output/medallion/gold output/medallion/dbt
```

### Step 2 — Move domain ontologies (excluding extension files)

```bash
# Move all .ttl files that are NOT silver-ext files
find ontologies/ -name '*.ttl' ! -name '*-silver-ext.ttl' -exec mv {} model/ontologies/ \;
```

### Step 3 — Move extension files

```bash
mv ontologies/*-silver-ext.ttl model/extensions/
```

### Step 4 — Move shapes

```bash
mv shapes/* model/shapes/
```

### Step 5 — Move integration artifacts

```bash
mv sources/* integration/sources/
mv mappings/* integration/mappings/
```

### Step 6 — Move medallion outputs

```bash
mv bronze/*  output/medallion/bronze/
mv output/silver/* output/medallion/silver/
mv output/dbt/*    output/medallion/dbt/
```

### Step 7 — Move remaining projection outputs

The `neo4j/`, `azure-search/`, `a2ui/`, and `prompt/` directories stay under
`output/` — no move needed if they are already there.

### Step 8 — Remove old directories and application-models

```bash
rmdir ontologies shapes mappings sources bronze
rm -rf application-models/
```

### Step 9 — Update .gitignore

Remove any line that gitignores `output/`. Projections are now committed.

```bash
sed -i '/^output\//d' .gitignore
```

### Step 10 — Refresh managed files and validate

```bash
kairos-ontology update
kairos-ontology validate
kairos-ontology project
git add -A && git commit -m "refactor: migrate hub to new layout"
```

---

## What Changes

### Deleted: `application-models/`

The `application-models/` directory previously held Mermaid ERD files generated
separately. These are now produced as part of the silver projection and live in
`output/medallion/silver/`. The standalone directory is no longer needed.

### Committed: `output/`

Previously `output/` was gitignored and regenerated on each developer's machine.
The new layout **commits all projection output** so that:

- CI/CD can diff projections against the previous commit.
- Consumers (e.g., dbt projects, Power BI) can reference stable paths.
- Code review covers generated artifacts.

### Updated CLI defaults

| Flag | Old default | New default |
|------|-------------|-------------|
| `--ontologies` | `ontologies/` | `model/ontologies/` |
| `--shapes` | `shapes/` | `model/shapes/` |
| `--extensions` | *(none)* | `model/extensions/` |
| `--sources` | `sources/` | `integration/sources/` |
| `--mappings` | `mappings/` | `integration/mappings/` |
| `--bronze` | `bronze/` | `output/medallion/bronze/` |

---

## Troubleshooting

### What if I have custom CI/CD referencing old paths?

Update your workflow files (`.github/workflows/*.yml`, Azure Pipelines, etc.)
to use the new paths. Common changes:

```yaml
# Before
- run: kairos-ontology validate --ontologies ontologies/ --shapes shapes/
# After
- run: kairos-ontology validate --ontologies model/ontologies/ --shapes model/shapes/
```

Search your repo for references to the old directory names:

```bash
grep -rn 'ontologies/\|shapes/\|mappings/\|sources/\|bronze/' .github/
```

### What if migration fails partway?

Because you committed (or tagged) before starting, you can always reset:

```bash
git checkout .          # discard uncommitted changes
git clean -fd           # remove untracked new directories
```

Or if you created a tag:

```bash
git reset --hard pre-migration
```

### What if I have files in both old and new locations?

The `kairos-ontology migrate` command detects this and aborts with a conflict
list. Resolve conflicts manually by choosing which copy to keep, then re-run
the migration.

For the manual path, check for duplicates before committing:

```bash
# Example: find .ttl files that exist in both old and new locations
diff <(ls ontologies/*.ttl 2>/dev/null | xargs -n1 basename) \
     <(ls model/ontologies/*.ttl 2>/dev/null | xargs -n1 basename)
```

---

## FAQ

### Do I need to update my `.github/copilot-instructions.md`?

**Yes.** Running `kairos-ontology update` after migration automatically
refreshes the Copilot instructions file with the new directory paths. If you
maintain the file manually, update all path references to match the new layout.

### Do I need to re-run projections?

**Yes.** Output paths have changed, so you must regenerate all projections:

```bash
kairos-ontology project
```

This populates the new `output/` tree. Old output files in the previous
locations are removed during migration.

### Is the migration reversible?

**Yes**, as long as you committed before migrating. Use `git revert` or
`git reset --hard` to return to the flat layout. The toolkit still supports
the old layout via explicit `--ontologies`, `--shapes`, etc. flags, but new
features will target the grouped layout only.

### Do I need to update `pyproject.toml` or `dbt_project.yml`?

- **`pyproject.toml`**: No — the toolkit package itself is not affected.
- **`dbt_project.yml`**: Yes, if your dbt project references paths under the
  old `output/dbt/` directory. Update them to `output/medallion/dbt/`.

### What if I have custom (non-toolkit) files in the old directories?

The `kairos-ontology migrate` command only moves files it recognises (`.ttl`,
`.md`, `.yml`, etc.). Unknown files are left in place and flagged in the
migration report. Move them manually to the appropriate new location.
