# DD-178: An AI-generated artifact states its own provenance and review status

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `alignment-report`, any future model-authored artifact
**Implementation:** `core/_provenance.py` (`ai_attribution`, `ai_attribution_note`, `provenance_comment(ai_generated=...)`)

### Context

An ontology reads as authoritative — that is what one is for. So does a coverage
report with precise percentages in it. Neither carried any trace of the fact that a
language model proposed its content, or of which model, so a reader six months later
had no way to tell a machine proposal from a human decision, and no way to know what
would have to be re-run to reproduce it.

The run log has this information and nobody keeps run logs.

### Decision

Any artifact whose content a model proposed carries the model on its face. For Turtle
and YAML that is a `#`-comment block extending the existing DD-072 provenance header;
for Markdown reports it is a one-line note placed *above* the figures it qualifies.

`ai_attribution` records what a re-run would need — model, pipeline role, seed,
reasoning effort — omitting anything not set, so an artifact generated without a seed
does not claim one. The disclaimer names the artifact as a proposal for human review
and points at the decision log for recording acceptance.

The wording is about provenance and review status, not liability. The reader needs to
know which statements were machine-proposed and that a human has not necessarily
confirmed them; that is a claim the toolkit can actually stand behind.

### Consequences

Because seeding is best-effort at this prompt size (DD-177), the recorded settings are
an audit trail of what was *asked for*, not a promise the artifact can be reproduced
byte for byte. Recording them is still what makes a later divergence diagnosable
rather than mysterious.

Comment headers are inert in both formats — `rdflib` and `yaml.safe_load` ignore them
— and the header is idempotent, so regenerating never stacks. Deterministic generators
(`init`, `build-glossary`, `import-source`) are untouched and must never claim AI
assistance they did not use; a test pins that.
