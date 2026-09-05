# DD-185: Tables are anchored globally, in one call, before per-table alignment

**Status:** Accepted
**Date:** 2026-08-17
**Affects:** `anchor-tables` (new), `propose-alignment`, `analyse-sources`
**Implementation:** `core/anchor_tables.py`, `cli/sources.py` (`anchor-tables`), `core/propose_alignment.py` (consumption)

### Context

The per-table pipeline decided a table's anchor from inside one domain's view:
affinity guessed the domain, a lexical shortlist picked twelve candidate classes,
the model chose among them. Measured failures: the shortlist ranked `TradeParty`
#24 for a table of companies (`Address` won on column overlap 44:20), ~40% of
tables needed a second 70KB full-inventory call, a plausible-but-wrong shortlist
anchor passed both retry thresholds silently, and affinity itself moved tables
between runs (`stops`: consignment → events on consecutive runs).

Anchoring is a grain question — *what is one row?* — and it wants the widest view
with the least detail. Brute force is arithmetically impossible (2,035 column
verdicts ≈ 163k output tokens in one response; the full property-detailed model is
~250k tokens per table). But every table's column names against a one-line-per-class
catalog fits in one ~35k-token call.

Tested on the live corpus before building: 6/6 on human-reviewed anchors (with
ownership marks; 5/6 without), honest nulls on metadata junk tables, zero invented
class names, and — against the hand-crafted cldn2 hub's nine bindings — 9/9 exact
grain-column matches as a secondary output. Sample values were tested and cost
accuracy here (5/6) and ~7k tokens: they stay in stage-2 mapping, where they are
proven, and out of anchoring.

### Decision

`anchor-tables` runs one global call (chunked above 150 tables): all tables'
column names × the full class catalog, each class marked with its owning blueprint
domain, plus the three anchoring-relevant pattern rules (role flags → neutral
party class; code-list tables; grain-of-one-row). Output is `table-anchors.yaml`:
anchor, alternate, confidence, derived domain, grain columns, natural key and load
hint per table, with DD-178 AI provenance. Every table is a required key in the
strict response schema (the DD-177 shape), so a table cannot be skipped; class
names are free strings — 1,275 candidates exceed the 1,000-value enum budget — and
are validated afterwards, invented names nulled with the evidence kept.

The domain is derived, not guessed: candidates are the domains owning any copy of
the anchor plus the domains bridging to it (DD-181), with affinity kept as a
tie-break *within* candidates. Bridge-awareness keeps a table in the bridging
domain instead of moving it to the owner — a move would trade an anchor gap for a
grain error. An anchor no domain can reach keeps its affinity domain and is
flagged `unowned`: the extension worklist, surfaced up front.

`propose-alignment` consumes the anchors through the existing uri-anchor-contract
override, with three guards: a human-confirmed alias always outranks the model's
anchor; nothing below `ANCHOR_CONFIDENCE_FLOOR` (0.6) is applied; and an anchor
outside the domain's pool (home + bridges) is reported, never silently applied.
Applied anchors are recorded as status `anchored` — never `confirmed`, which
means a human decided. The anchor and its status join the per-table cache key.

Column-level dispositions (DD-164) now feed the prompt: a column recorded as
`not-business-data` — including a system-wide `(system, "", column)` entry — is
excluded from the outline, so a SaaS tenant discriminator cannot become a grain or
key member. On the live run the model had keyed every qargo table on `tenant_id`
before the exclusion; zero after.

### Consequences

Live pilot on the hub: 72/75 tables anchored in one 54-second call, all five
session-confirmed anchors correct, six unowned-class flags, zero invented names.
Party alignment with anchors: three overrides applied, one refused as
outside-pool, one refused below the floor (0.18 — the honest `unmatched` beat a
bad pin), no full-inventory retries.

Two defects were found live and fixed: duplicate class names across modules
(ownership derived from an arbitrary copy put `consignments` in `commercial`; the
index now keeps every copy and aggregates), and the affinity reader using a field
name that does not exist (`primary_domain` vs `domain`).

Not yet done, in honest order: alignment still *groups* tables by affinity's
domains, so an anchor pointing outside that grouping is reported rather than
moving the table — regrouping by derived domain is the follow-up that makes
affinity fully derived. The binding-draft generator (assemble EntityBinding
skeletons from anchors + alignment) and the Langfuse golden-set evaluation are
deferred; the latter because the cldn2 golden set contains genuine modelling
disagreements (`shipments`: Shipment vs TransportMovement) that need human labels
before they can score anything.
