### Fixed
- **`discovery-status` no longer answers "nothing to check" when there is.** It read
  `.import/businessdiscovery/` alone, so on a hub holding thirty client documents filed
  one directory across it printed `(no discovery documents found — nothing to check)` —
  a sentence that sounded like an answer and stopped anyone looking further. When that
  directory is empty it now scans the rest of `.import/`, names the business documents
  staged where nothing reads them, and says where to move them. The DD-233 gate already
  blocked `validate` on this; the command a human runs to ask *what evidence do I have*
  should not have been the one saying "none".
