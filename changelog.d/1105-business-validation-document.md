### Added
- **A business validation document per domain, generated from the model and signed off by the
  business (DD-254).** `kairos-ontology business-doc <domain> --facts` writes
  `business-doc.facts.json`: the domain's entities, fields, code lists, relationships with their
  OWL cardinality, neighbour domains, candidate gaps from the source ledgers and the domain's
  decisions, read from the ontology closure, the Silver contract, the compile plan and its
  bindings. The same hub always gives the same bytes. `--render --narrative <file>` joins those
  facts with a confirmed plain-language narrative and writes `<domain>-validation-v<N>.docx`:
  terms, the domain and its neighbours, landscape diagrams with crow's-foot line ends, one
  section per entity, gaps and open decisions, and a sign-off table, with Yes / No / Comment
  boxes on every row. A PDF preview is written when LibreOffice or Word is available.
  - **The narrative cannot add or drop a fact.** A narrative that names an ID the facts do not
    carry, or leaves an entity, relationship or field unplaced without an `omitted:` reason,
    is refused.
  - **Silver and OWL disagreements are surfaced.** When Silver joins a relationship
    many-to-one but the ontology still allows many, the facts carry a warning to fix the
    ontology rather than the wording.
  - **New optional extra `business-doc`** (python-docx). Diagrams are rasterised with a
    headless Chrome, Chromium or Edge (`KAIROS_CHROME` points at one); without one the SVGs are
    written beside the document and the command warns.
  - **New hub skill `kairos-design-business-validation`** drafts the narrative with you,
    confirms it block by block, renders, and routes every "No" back through
    `kairos-design-domain`. Routed from the hub `AGENTS.md`, `kairos-help` and `kairos-flow`
    as an optional action outside the compile path. Run `kairos-ontology update` to receive it.
