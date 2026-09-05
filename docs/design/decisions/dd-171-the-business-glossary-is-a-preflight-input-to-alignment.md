# DD-171: The business glossary is a preflight input to alignment

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, discovery preflight
**Implementation:** `core/propose_alignment.py` (`load_glossary_terms`)

### Context

The glossary was treated as documentation. It is evidence: it is where the organisation
already wrote down what its own terms mean, and the pattern-library cautions need it on
every run, not on the runs where someone remembered to pass it.

### Decision

Alignment loads glossary terms as part of discovery preflight, unconditionally.

### Consequences

Glossary absence is now visible at preflight rather than silently producing a
vocabulary-blind alignment.
