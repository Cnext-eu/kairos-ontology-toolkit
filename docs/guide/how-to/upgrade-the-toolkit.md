# Upgrade the toolkit

**Skill:** `kairos-toolkit-ops`

A toolkit release pushes nothing. The hub pulls, and only for files the toolkit owns.

## Refresh managed files at the current pin

```bash
kairos-ontology update
```

## Preview without writing

```bash
kairos-ontology update --check
```

This is what `managed-check.yml` runs on every pull request, so it should exit 0 on a
healthy repository.

## Move to a newer release

```bash
kairos-ontology update --upgrade
kairos-ontology update --check
```

Do it in an isolated PR. On Windows a version-changing `--upgrade` finishes in a detached
process, because the running executable holds a lock on itself — wait for it, then check
`.kairos/upgrade-refresh.log`.

## Workflows

Workflows are not managed files: they carry local edits, and the managed marker is an HTML
comment that would be invalid YAML. `update` reports drift; only

```bash
kairos-ontology update --refresh-workflows
```

writes. A workflow reported as `customized` was edited locally and is left alone.

## What the toolkit owns, and what stays yours

Owned and replaced on update: `CICD.md`, `CONTRIBUTING.md`,
`.github/copilot-instructions.md`, `.claude/skills/*/SKILL.md`, and the per-directory
`README.md` guides. Edits to these are lost.

Yours, never overwritten: `.gitignore` and `.gitattributes` (missing template rules are
*reported*, not merged), `.claude/settings.json` (replaced only when it matches a
generation the toolkit knows it shipped), and the `decisions/` and feedback `index.md`
files, which are regenerated from your own records.

## Testing an unreleased build

```bash
kairos-ontology update --test-ref <commit>
kairos-ontology update --restore
```

Reversible by design: `--restore` puts the previous pin and managed files back.
