### Added
- **`propose-relationships` explains a relationship whose foreign key is on the other
  side.** When an object property runs container-to-contained — `rdfs:domain` on the
  container, `rdfs:range` on the contained side — the container becomes the child and
  there is nothing on it to join with. v5's `cardinality` enum has no `one-to-many`, so
  such an edge is not mis-cardinalitied but unauthorable on the side proposed; the only
  correct entry is the inverse property on the key-carrying binding. The command now
  tries the reverse direction and, when it resolves, names the binding that holds the key,
  the columns that join, and what stands between that and a usable entry:
  - no `owl:inverseOf` declared — declare one and re-run;
  - an inverse declared and usable — author it there, named;
  - an inverse declared whose own `rdfs:domain` excludes the class holding the key — which
    is reported rather than silently failing, because reading the assertion is not enough
    to know the endpoints fit. Observed on a real reference module whose inverse pair does
    not have its domain and range swapped.

  It stops short of emitting an entry for the other side: that needs a property URI, and
  DD-160 §3 is explicit that the object property is read, not guessed.

  Measured before building, as the issue asked: the reverse resolved for none of the
  unresolved proposals on the hub that reported this, and for 3 of 11 on a second hub —
  none of which could be turned into a proposal, for the two distinct reasons above.

  Reported in the text output, in `--format json` as `reverse_join`, and summarised in the
  run's notes.
