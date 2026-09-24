### Added
- **`kairos-ontology read-document <file>` prints a staged document's text (#907).**
  DD-233 fails `validate` until every file under `.import/businessdiscovery/` has an
  extraction. The toolkit could not open most of them, though: on one hub 20 of 31 were
  `.docx`/`.pptx`/`.xlsx`. `read-document` reads `.pdf`, `.docx`, `.pptx` (including
  speaker notes), `.xlsx`, `.md`, `.txt`, `.csv`, `.xml` and `.htm`, in reading order.
  - Headings are marked (`## Slide 3`, `## Sheet: Rates`) and tables come out as rows, so
    an extraction can cite where a term came from.
  - It says which pages or slides have no text and need reading visually.
  - Legacy `.doc`/`.ppt`/`.xls` get a clear "save as .docx/.pptx/.xlsx" message.
  - The Office readers are in a new `documents` extra: `uv sync --extra documents`. PDF
    needs nothing extra.
- **`.import/drafts/` for staged files that should not be extracted (#907).** Every file
  under `.import/businessdiscovery/` counts as a discovery document and needs an
  extraction. Put an outdated deck or a working copy in `drafts/` instead: nothing reads
  it, and `validate` does not report it. `init` creates the folder, and `update` adds it
  to existing hubs.

### Changed
- **One definition of "business document" (#907).** The DD-233 "staged where nothing
  reads it" check now uses the same format list as the discovery readers, so `.xml` and
  `.htm` files staged outside a known folder are reported. They were processed by
  discovery but invisible to the gate. Loose `.txt`/`.csv` files stay unreported, as
  DD-233 intends.
