### Added
- **`kairos-ontology gates` lists every gate, the evidence it reads, and the flag that
  bypasses it (DD-234).** Until now the only way to find out what could block the
  pipeline, and what could get past it, was to read sixteen `click.option` declarations
  across eight CLI files. One of them — a fourth `--degraded`, on `resolve-ontology` —
  had no help text at all, and was found only by the AST scan written for this change.
- **Enforcement modes: `--mode interactive|autopilot|ci`, or `KAIROS_MODE`.** The modes
  differ in one thing — whether an escape flag that downgrades the result is accepted —
  and the difference is about who is watching, not about how important the check is. In
  `autopilot` and `ci` the flag is refused at parse time, before the command body runs,
  with a message naming the gate and the human decision it needs. `interactive` is the
  default and every current behaviour is unchanged.
- **Artifacts record how they were enforced.** `*-alignment.yaml` and `table-anchors.yaml`
  produced under an escape carry an `enforcement:` block naming the mode and the flags.
  A file written with `--without-discovery` was otherwise indistinguishable afterwards
  from a grounded one — the flag was printed to a terminal and written into nothing. The
  block is emitted only when there is something to say, so a clean run's output is
  byte-identical to what the previous version wrote.

### Fixed
- **`compile` no longer passes the DD-169 and DD-180 gates on evidence it could not
  read.** Both are built on `build_alignment_report`, which degrades gracefully by
  design — an unreadable file is skipped, an absent directory yields nothing — so "no
  findings" and "nothing was read" reached the gate indistinguishable. Measured on a real
  hub, varying only the readability of the input: healthy, 661 undecided columns; one
  `*-alignment.yaml` malformed, 405, with 256 columns silently gone; `_analysis/`
  deleted, **0, and the gate passed clean**. No exception was raised in any of the three.
  `compile` now reports `alignment.evidence-missing` and blocks. Scoped to hubs that have
  imported sources, so a hub with nothing to align is unaffected.
- **A gate that crashes no longer reports as a gate that passed.** The DD-169 and DD-180
  guards were wrapped in `except Exception: ... = []` so a broken guard could not break an
  unrelated compile. The intent was sound; the effect was that a gate whose failure mode
  is *pass* is an advisory with a strict-sounding name. Both now return
  `gate.evaluation-failed`, naming the gate and carrying the exception so a toolkit defect
  is distinguishable from a malformed hub file.
- **`resolve-ontology --degraded` is documented.** It had no help text, so the one
  undocumented escape in the CLI is now described where an operator meets it.
