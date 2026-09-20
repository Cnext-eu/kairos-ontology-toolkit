# DD-233: Staged business evidence nothing consumed fails validate

**Status:** Accepted
**Date:** 2026-09-20
**Affects:** new `core/import_evidence.py` (`audit_import_evidence`, `find_powerbi_exports`,
`find_misplaced_documents`), `core/validator.py` (integrity block),
`cli/setup.py` (`init`/`new-repo` scaffold `.import/powerbi/`),
new `scaffold/import/powerbi/README.md`, `tests/test_import_evidence.py`
**Issue:** [#885](https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/885) — asked
for directly during a dogfood session (2026-09-20): "make sure it is a hard stop if
business data is in .import and not used downstream."

### Context

`.import/` holds the two inputs the pipeline cannot re-derive for itself: the client's
own documents, and the Power BI models that record what the business already measures.
Source schemas can be re-read from the warehouse at any time; these cannot be
reconstructed from anything the toolkit has.

Nothing checked that either was used. `discovery-status` read
`.import/businessdiscovery/` alone and reported an empty directory as "nothing to
check" — a sentence that is equally true when the client sent no documents and when they
sent thirty to a directory no command looks in. And there was no scaffolded home for a
Power BI export at all: `init` created `businessdiscovery/` and `modeling/` and nothing
else, so `import-tmdl`'s *output* location was conventional while its *input* location
was whatever each hub invented.

Measured on one real hub: thirty-one client documents (domain-definition PDFs, a KPI
process mapping, definition workbooks, requirement documents) sat in `.import/Input/`,
and three Power BI exports in `.import/Powerbi_out/`. Both paths were invented locally
because neither had a scaffolded one. Every command reported success throughout, and the
hub was modelled from source column names alone — the ontology inherited from the
accelerator, the silver contract far narrower than the source system.

The failure mode is not a wrong answer. It is silence that looks identical to success.

### Decision

**1. `.import/powerbi/` is scaffolded**, beside `businessdiscovery/`, by both `init` and
`new-repo`, with a README covering both export shapes (`definition/tables/` and flat),
the `.pbip`-pointer-needs-its-folders trap, and DD-147's demand-evidence-not-authority
rule. An input the pipeline requires gets a conventional home; without one, hubs invent
their own and every command then fails to find it.

**2. `validate` fails on staged evidence nothing consumed**, in three kinds:

| kind | meaning |
|---|---|
| `unextracted` | a document in `.import/businessdiscovery/` with no `*.extraction.yaml` |
| `unimported` | a Power BI export under `.import/` with no engineering pack in `integration/discovery/bi/` |
| `misplaced` | a business document under `.import/` but outside every directory a command reads |

`misplaced` is the one that matters most: the operator has supplied the evidence and has
no way to discover that nothing can see it. The other two are visible work items; this
one is invisible by construction.

`--degraded` downgrades all three to warnings, consistent with every other integrity
check.

**3. Detection is deterministic and reads no file contents** — extensions, paths, and the
presence of sibling artifacts only. A Power BI export is matched on the marker files
Power BI writes (`model.tmdl`, `database.tmdl`, `*.pbip`) rather than on folder naming,
because the folder is named by whoever exported it.

A `.pbip` pointer is kept distinct from a model folder rather than collapsed by nesting.
Collapsing them let one stray pointer in a staging folder hide the three real exports
beneath it — under-reporting, which is the exact failure this gate exists to prevent.

**4. The document-kind list is narrow** (`.pdf`, `.docx`, `.doc`, `.pptx`, `.ppt`,
`.xlsx`, `.xls`, `.md`). A stray `.txt` or `.csv` is far more likely to be scratch than a
briefing, and a false "you forgot this" is how a gate gets disabled.

### Consequences

A hub cannot pass `validate` while holding client evidence nothing has read. On the hub
this was found on, the gate reported twenty-nine findings; after moving the files to the
conventional locations it reported thirty-one `unextracted` documents — which is the true
statement, and the one nothing was making before.

This is a *reporting* gate, not a processing one: it does not extract anything, and
clearing it means doing the discovery work or recording a decision not to. That is
deliberate — the toolkit can tell you the evidence is unread; only a human can tell you
it does not matter.

The narrow document-kind list and the marker-file matching both trade recall for
precision. A gate that cries wolf is turned off, and this one blocks `validate`.

### Alternatives considered

**Warn instead of fail.** Rejected for the same reason `propose-alignment`'s
business-glossary check blocks rather than warns: a warning about missing input is read
after the expensive work has been done against the input that was there.

**Make `discovery-status` louder and leave `validate` alone.** Rejected because
`discovery-status` is opt-in and nothing runs it. The whole defect is that the operator
had no reason to suspect anything was wrong.

**Infer intent from the invented directory names** (treat `.import/Input/` as
business discovery, `.import/Powerbi_out/` as Power BI). Rejected: it rewards the
divergence it is trying to remove, and the next hub invents different names.
