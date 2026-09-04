---
name: kairos-design-source
description: Import, document, and analyse source-system schemas for v5 hubs.
---

# Kairos Source Design

Create authoritative Bronze inputs under `integration/sources/<source>/`. Source vocabularies and
samples describe physical relations and columns; they do not define canonical entities.

**Sample redaction is opt-in (DD-214).** `extract-schema`, `import-source` and `import-flatfile`
write sample values as-is unless you pass `--redact-pii`. That is deliberate: the detector's false
positives destroyed the evidence this step exists to produce -- money, datetime and business-ID
columns arrived with zero samples, mislabelled as phone numbers -- while protecting nothing, since
the real values were present in the sibling `.samples.yaml` regardless.

Consequences you must tell the user about, not assume:

- Committed artifacts under `integration/sources/**` can contain raw client PII, and they enter the
  client's git history.
- `analyse-sources` reports unredacted findings and **proceeds**, so sample values can reach the
  configured AI provider.
- Pass `--redact-pii` when a source is known to carry personal data and the hub has not accepted
  that exposure. `kairos-ontology source-privacy [--fix]` audits and remediates after the fact.

## Design fleet mode (DD-088)

Default is interactive. An explicit fleet override applies only to this skill invocation and is
never inherited. Record rationale, confidence, and input references for every AI-approved choice.
Stop for ambiguous semantics, low confidence, secrets, PII, proprietary data, or destructive changes.

## Workflow

1. Inspect the supplied CSV, Excel, Parquet, extracted YAML, DDL, API schema, or existing TTL, and
   enumerate every source available for import (each `.input/` file or per-source subfolder, each
   extracted schema YAML, or DDL) so the full candidate set is known before importing anything.
2. When more than one source is available, ask the user whether to import all sources in one batch
   or select a subset. In fleet mode, default to importing every candidate and record the decision
   with its rationale.
3. Set `KAIROS_SKILL_CONTEXT=1` before skill-owned CLI calls.
4. For flat files, run `kairos-ontology import-flatfile --from <path> --system <name>`. Directory
   mode only reads the top level (non-recursive); pass `--recursive` for a nested export tree.
   Legacy `.xls` is recognized but never readable — ask the user to convert to `.xlsx` first.
5. For extracted schema YAML, run
   `kairos-ontology import-source --from <path> --system <name>`.
6. For a batch, run the matching import command once per selected source (or point `--from` at a
   parent directory where the CLI already accepts one). Continue past a single source failure so the
   remaining sources still import, and record each failure and its reason.
7. Review relation names, column names, physical types, nullability, keys, descriptions, and
   samples. Never expose credentials. Note that samples are unredacted by default (DD-214), so do
   not paste them into reports or transcripts -- describe them instead.
8. Parse every generated Turtle file with `rdflib`; use `kairos-ontology validate` through
   `kairos-execute-validate` when ontology or SHACL checks are required.
9. After the batch completes, show a short report listing which sources were imported (name and
   the generated `integration/sources/<source>/` path) and which remain un-imported or failed, with
   the reason. Confirm the remaining set with the user before continuing.
10. Once sources are settled, offer to import any Power BI / TMDL analysis the user has as **demand
    evidence, not a source**. Run `kairos-ontology import-tmdl <pbip.zip | SemanticModel/ |
    file.tmdl>`; it lands an Engineering Pack and a Concept Mapping template under
    `integration/discovery/bi/`. Never place it under `integration/sources/` or bind it as a source
    relation — it informs ontology and Gold design only. Fold each imported or skipped BI input into
    the same report from step 9.
11. When semantic source analysis is requested, select and disclose the AI provider immediately
    before the call, obtain invocation-scoped consent, and run `analyse-sources`. First run
    `kairos-ontology check-ai-config --role alignment`; if the role is `not_configured` or
    `misconfigured`, stop and print the remediation — never auto-degrade to a heuristic or
    plausible-empty result (DD-159). Report provider, authentication mode, and variable names
    only—never secret values. Preserve deterministic imports when AI analysis is skipped.
12. After `analyse-sources`, review the tables it could assign to **no domain at all**
    (`domain-coverage --format json` → `unassigned_source_tables`, DD-160). Some of these are
    noise; some are a real business concept the archetype catalog simply does not contain, and
    those are invisible to everything downstream — discovery only ever iterates the catalog, so
    such a concept can never be judged, tagged, or modeled. Propose registering each one
    (DD-162):

    ```powershell
    kairos-ontology register-concept `
      --uri <IRI> --label "<Label>" `
      --source-system <system> --source-evidence <table> [--source-evidence <table.column> ...] `
      --domain <domain-id> `
      --rationale "<why this belongs, with row counts / report usage>"
    ```

13. Once affinity is settled, **anchor every table globally before aligning** (DD-185):

    ```powershell
    kairos-ontology anchor-tables
    ```

    One model call decides what each table's rows *are*, against the full class catalog
    rather than one domain's shortlist, and derives each table's domain from the
    blueprint owner of its anchor. Read the reported counts: tables anchored to an
    **unowned** class are the extension worklist, and tables left unanchored are the
    ones no reference class fits. `propose-alignment` consumes the anchors and regroups
    tables into their derived domains, so run this *before* alignment, not after.

    Where the model gets a table wrong, **record the correction as a design ruling, not
    as a hand-edit** (DD-192). `integration/discovery/design-rulings.yaml` is the durable,
    transferable seam: `anchor-tables` renders the applicable rulings into its prompt as
    accumulated human authority that *outranks* the model's own reading, and records
    `rulings_applied` in `table-anchors.yaml` for provenance.

    ```yaml
    # integration/discovery/design-rulings.yaml
    - kind: disambiguation        # disambiguation | rejection | preference
      scope:
        class_pair: [Shipment, Consignment]
        applies_when: "the table carries a house bill reference and no master bill"
      ruling: Consignment
      rationale: "House-level rows are consignments; the master bill is the shipment."
      decided_by: user            # anything else is inert and reported (DD-192)
    ```

    This matters because a hand-edited anchor is undone by the next re-run, which is what
    makes people stop re-running analysis at all. Three boundaries: a ruling is always
    human-decided, never introduces a class, and never maps columns. An absent file is a
    silent no-op, and skipped entries are echoed with reasons.

14. After `propose-alignment`, close the DD-169 gap gate before entity binding. Do not
    review the raw column list — on a real hub that is well over a thousand rows, which
    is attrition rather than review. Instead (DD-186):

    ```powershell
    kairos-ontology draft-gap-decisions --auto          # record the rule-decidable ones
    kairos-ontology draft-gap-decisions --suggest       # draft the rest for review
    ```

    `--auto` records only the two reason codes that were never judgment calls
    (`operational` audit columns, `vendor-slot` placeholders). `--suggest` groups the
    remainder into domain-scoped families and asks the model to name the concept each
    family represents and flag families whose members do not belong together — it fills
    the reasoning, never the decision.

    Then open `integration/sources/_analysis/gap-decisions.yaml`, set `decision` on each
    family or single name to one of `bound | registered-extension | deferred |
    not-business-data | blueprint-gap`, and apply:

    ```powershell
    kairos-ontology draft-gap-decisions --apply
    ```

    Two cautions worth stating to the user. `blueprint-gap` asserts a **reference-model
    defect to file upstream** — it is not the neutral default; `deferred` is the honest
    choice for "in scope, not modelled yet". And a family whose `coherent` flag is
    `false` should be split into its member names rather than ruled on as a unit.

    Both `--source-evidence` and `--rationale` are mandatory: registration is a claim about
    source data, and an unevidenced or unexplained claim is a guess the next reader cannot
    check. Registered concepts always carry tier `optional` — the source data argued them into
    scope, no blueprint recommended them. **Propose, never decide**: leave `--decided-by user`
    for a human-confirmed registration, and mark an AI-proposed one `--decided-by ai` (it then
    blocks `compile`/`validate` until confirmed, DD-148). A URI already in the archetype
    catalog is rejected — that concept belongs in `core_concepts` with a real discovery
    judgment via **kairos-design-discovery**, not here.

    Registration records that a concept belongs and names its evidence. It does **not** model or
    bind it — authoring the class stays a **kairos-design-domain** decision, surfaced by
    `kairos-ontology next` as `model-registered-concept`.
13. Hand authoritative source relations to `kairos-design-mapping`, which authors closed
    `integration/bindings/*.binding.yaml` documents.

Do not author canonical classes here. Do not create execution policy in RDF. Complex relational
logic belongs in an ordinary contracted dbt SQL model plus dbt properties YAML under
`integration/transforms/dbt/models/`, referenced by `source.dbtModel` in an EntityBinding.
