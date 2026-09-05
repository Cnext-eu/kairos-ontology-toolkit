# DD-187: Domain design runs as a fleet, and every refusal is recorded in the file it belongs to

**Status:** Accepted
**Date:** 2026-08-17
**Affects:** kairos-design-domain, kairos-flow autopilot leg 2, `validate` integrity warnings
**Evidence:** cldn-v5b hub, 13 domains authored in one parallel pass

### Context

Leg 2 turns alignment evidence into domain ontologies. On the live hub that is 22
domains, ~1,900 alignment proposals and an import closure of several thousand
reference terms. Authored serially by one context it is slow and, worse,
inconsistent: the standard applied to domain 1 has drifted by domain 13.

DD-088 already establishes design fleet mode — decisions AI-approved rather than
user-confirmed, with mandatory stop conditions. Leg 2 is the first use of it at
full width.

### Decision

**One agent per domain, one shared authoring contract, run in parallel.** The
contract fixes the order of work: resolve the import closure *before* writing,
read the anchors and alignment, author, refuse, validate, report. Every agent
gets the same two finished exemplars (`party`, `consignment`) as the house style,
not a prose description of it.

**Refusals are a first-class deliverable, written into the TTL itself.** Each
domain file ends with a numbered block naming every alignment proposal not
modelled and why. This is the load-bearing part of the decision. A refusal kept
in a report is detached from the model within one release; a refusal in the file
is read by the next person to open it, and survives the toolkit that produced it.
On the live hub this is 142 numbered refusals across 15 files — a larger artefact
than the 40 classes and 109 properties they accompany, and a more useful one.

**Refusing is the default when evidence and closure disagree.** Five refusal
classes are mandatory: out-of-closure parent terms, role-as-flag and
role-as-subclass, collisions (two source columns onto one reference property),
sub-0.60 confidence, and anchor/property disagreement. An empty domain is a
correct outcome — `customs` and `terminal-operations` are empty by decision, with
the reasoning recorded.

**`integrity.managed-import-unused` is reclassified as a sourcing signal, not
authoring debt.** A domain that imports a blueprint-mandated module and
references nothing from it is reporting that the blueprint's scope outran the
evidence. The warning must not be silenced by minting a term no source column
reaches. Every agent in the live run independently refused to game it.

### Consequences

Thirteen domains in one pass: 40 classes, 109 properties, all validating, with
**zero** out-of-closure parent terms, zero source-system names in `rdfs:comment`,
and no PII modelled while the GDPR hold stands. Consistency held across agents
because the contract, not the agent, carried the standard.

The unused-import count is now a readable backlog. Ten domains carry 42 such
warnings, and they concentrate exactly where sourcing is thin:
`terminal-operations` owns ~40 classes with zero source tables; `commercial`'s
entire contract-and-pricing scope has no evidence while its one table is a
packaging ledger; `equipment` owns reefers, chassis and swap bodies and is
sourced by a single spreadsheet export. This is the most valuable output of the
leg, and it is only legible because nothing was invented to hide it.

Running wide also made the toolkit's own defects visible by repetition rather
than by inspection — a per-class property enum gap in DD-177, alignment not
searching value-object subclasses, alignment files going stale against newer
imports, and several bad anchors. One agent finding these reads as noise;
several finding them independently reads as a defect list. See the hub's
`_analysis/leg2-findings.md`.
