# Record a decision

**Skill:** none — this is a direct command

The hub's Decision Log holds durable rationale for material modelling choices. It is the
hub's own record, separate from the toolkit's decision log.

## Create a record

```bash
kairos-ontology decision new --title "Invoice grain is one row per invoice line" \
  --domain billing --materiality high
```

`--decision-state` and `--source` are optional. The command writes the record and
regenerates `decisions/index.md`.

## What is worth recording

Anything a reader six months from now would otherwise have to reverse-engineer:

- which source wins for a property two systems both populate;
- why a class is *not* aligned to an obvious reference-model term;
- a grain choice, and what was rejected;
- an exception granted to a convention.

Not worth recording: anything the code already states. A decision log that competes with
the compiler loses.

## Inspect

```bash
kairos-ontology decision list
kairos-ontology validate
```

`validate` lints an existing Decision Log bundle along with everything else.

## Do not hand-edit the index

`decisions/index.md` is regenerated from the records. Edit a record and re-run the command
instead. The toolkit deliberately does not manage that file, precisely so your records
survive an upgrade.
