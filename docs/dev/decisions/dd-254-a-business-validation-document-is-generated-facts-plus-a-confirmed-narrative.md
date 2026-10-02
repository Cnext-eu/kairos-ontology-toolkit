# DD-254: A business validation document is generated facts plus a confirmed narrative

**Status:** Accepted
**Date:** 2026-10-01
**Affects:** `core/projections/business_doc/` (facts, layout, diagram_svg, render_docx),
`cli/business_doc.py` (`business-doc`), the `business-doc` optional extra, the
`kairos-design-business-validation` hub skill, the hub output lane
`ontology-hub-publish/business/<domain>/`
**Issue:** #1105

### Context

Before Silver is built on a domain, someone from the business has to confirm that the
canonical model matches how the business works. Hubs did this with hand-built Word documents:
classes, fields and cardinalities copied out of the ontology and the contract, diagrams drawn
by hand, explanations typed in. The facts drifted from the model between versions, every
domain's document looked different, and most review remarks were about transcription
(crow's feet drawn the wrong way round, a field listed that the contract does not carry,
words nobody defined) rather than about the model.

An agent cannot simply write the whole document either. It would have to assemble the facts
itself, which is the transcription problem again, and it would be tempted to read `.ttl`
files as text to do it (DD-103). The document also carries content no input holds: the
plain-language definitions, the "why it works this way" panels and the questions put to the
business. Those have to be drafted and confirmed by a person.

### Decision

**The document is built from two files with separate authority.**

- `kairos-ontology business-doc <domain> --facts` writes `business-doc.facts.json`
  (schema version 1). It is derived deterministically from the domain's ontology closure
  (`load_ontology`, profile `kairos-design`, DD-243), the Silver contract, the compile plan
  and its bindings, the source disposition ledgers and the decision bundle. Cardinality comes
  from `erd_projector.edge_multiplicities` (DD-241), the one derivation every diagram already
  uses, mapped to `1 | 01 | 1n | 0n`. Same hub, same bytes; a `facts_hash` identifies it.
- `business-doc.narrative.yaml` is authored by the agent and confirmed by a person through the
  `kairos-design-business-validation` skill. It may word and group facts; it may not add one.
- `kairos-ontology business-doc <domain> --render --narrative <file>` rebuilds the facts,
  validates the narrative against them and fails closed: an ID the facts do not carry, or a
  core entity, relationship or non-deprecated field that is neither placed nor explicitly
  `omitted:` with a reason, is an error. It then writes `<domain>-validation-v<N>.docx`
  (diagrams as PNG on landscape pages) and, when LibreOffice is available, a PDF preview.
  For the same facts and narrative, `word/document.xml` and every diagram SVG are
  byte-identical; the core-properties timestamps come from the narrative date.

The output goes to `ontology-hub-publish/business/<domain>/` and is **not drift-gated**: the
document holds a human-authored narrative and a date, so regenerating it is not a check. A
signed document is evidence for a design decision, recorded with `kairos-ontology decision
new`, never for a compile, release or deployment.

python-docx is the optional extra `business-doc`. A missing extra is reported with the
install command. Diagrams are rasterised with a headless Chromium browser (Chrome, Chromium
or Edge); when none is found the SVGs are written beside the document, the figure page holds
a placeholder, and the command warns.

### Consequences

- **Facts the business sees are exactly the facts the compiler sees.** A wrong cardinality in
  the document is a wrong cardinality in the ontology, fixed through `kairos-design-domain`,
  not in the document.
- **Whether a number held on an entity points to another object is narrative, not fact.** The
  ontology does not say that a `houseBillNumber` is the number of another object, so the facts
  do not claim it; the narrative lists such fields under `held_references`.
- **Code lists are recognised by annotation, not by name:** a range class marked
  `kairos-ext:isReferenceData`, `kairos-mdm:referenceList`, or a subclass of `skos:Concept`.
  An unmarked code class is drawn as an ordinary relationship until it is marked.
- **Rejected: extending `report_projector`.** It is the legacy engineering report and its
  output is not shaped for business sign-off.
- **Rejected: a drift-gated projection like the others.** The narrative and date are human
  input; drift would always be reported.
- **Rejected: Markdown or HTML output.** Business reviewers comment and sign in Word; the PDF
  is a preview only.
