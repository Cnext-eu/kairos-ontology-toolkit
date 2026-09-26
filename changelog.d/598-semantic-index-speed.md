### Performance
- **The semantic index builds about 2.5 times faster (#598).** Every domain compile, the Gold
  shaping in `emit-gold`, and the cold reference-corpus walk build one index per ontology
  closure. On a 15-domain hub, with byte-identical output:

  | Command | Before | After |
  |---|---|---|
  | `compile --all --emit`, warm | 21.3 s | 18.7 s |
  | `emit-gold`, 15-domain product | 9.9 s | 7.4 s |

  Two changes cover it:
  - **The closure graph is no longer copied** for profiles that only read it. OWL RL
    still expands a copy.
  - **Term provenance is looked up in one per-closure index.** It used to scan every
    source graph again for each question, about 96,000 scans per run. Closure order is
    unchanged, so the first match, and therefore the answer, is the same.
