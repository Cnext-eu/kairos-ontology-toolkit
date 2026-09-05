# DD-180: An unanchored table is reported, gated, and told where its class lives

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `alignment-report`, `compile`
**Implementation:** `core/alignment_report.py` (`UnanchoredTable`, `find_anchor_candidates`, `domain_imports`, `undecided_unanchored_tables`), `cli/compile.py`

### Context

Alignment anchors a table before mapping its columns: step 1 decides which reference
class the table *is*, step 2 maps each column to a property of that class. The anchor
is the frame. Without one, step 2 draws from the whole property pool with nothing to
constrain the choice.

Nothing reported when step 1 failed. The alignment file for an unanchored table looks
like any other, and every downstream consumer reads it as an ordinary result.

Testing a second domain is what exposed it. On `consignment`, run-to-run stability was
48% against `party`'s 93%, and the cause was not the model, the prompt or the settings
— all three had just been measured and improved. Split by anchor status it was
unambiguous:

| table | anchor | mapped per run | stability |
|---|---|---|---|
| `consignments` | Consignment | 26, 26, 24 | 67% |
| `shipments` | Shipment | 5, 3, 4 | 60% |
| `stops` | **none** | 26, 13, 8 | **30%** |
| `stops_table` | **none** | 23, 11, 16 | **44%** |

Both unanchored tables returned `unmatched` — the model was shown every class the
domain imports and declined to force-fit, which is the anchor contract working. It was
also right: the class those tables need is `TransportCall`, which exists in
`dcsa/transport-call#` and is imported by **`route-schedule`**, not `consignment`. 237
columns had no reachable home because of where a module was imported, not because of
anything a language model did.

An A/B on the same 122-column table ruled out the obvious alternative explanation: the
strict schema (DD-177) maps *more* under identical conditions (24/22 vs 16/11), varies
less, and uses half the output tokens. Width was not the problem either.

### Decision

`build_alignment_report` collects every table whose `ref_class` is empty or whose
status is `unmatched`/`rejected`, and for each one searches the *full* reference
vocabulary — not merely what the domain imports — for classes matching the table's name
and candidate entity, reporting which domain already imports each module.

That is the difference between "the model could not anchor `stops`" and "`TransportCall`
exists in `dcsa/transport-call#`, which `route-schedule` imports and `consignment` does
not". The first is an observation; the second is the fix.

Candidates rank by: a module some other domain imports first (a boundary mismatch is
both the likelier diagnosis and the cheaper fix, where an orphan module is usually
vocabulary coincidence), then token overlap, then fewest surplus tokens so
`TransportCall` outranks `BargeTransportCall`. Matching is blunt on purpose — the output
is a pointer for a human, not an automatic re-anchor, so a false suggestion costs a
moment's reading while a missed one costs a silent blind spot.

`compile` gates on it, before the DD-169 column gate: an unanchored table is the larger
omission, and listing a hundred homeless columns underneath one describes the symptom
while hiding the cause. Cleared by a table-grain disposition (DD-164), like any other
scope decision.

### Consequences

On the live hub this found **9 unanchored tables covering 306 columns**, across six
domains — only two of which were known. Every one names a candidate class and the
domain that already imports it, so each is a boundary decision rather than an
investigation: `compliance/resource_calendar_events` wants `events#` (imported by
`events`), `equipment/equipmentcode_fix` wants `onerecord/cargo#` (imported by
`booking`).

This is the mirror image of the defect that started this work. `Booking` appeared in
`party` where it did not belong; here `TransportCall` is absent from `consignment`
where it is needed. Same root cause — a mismatch between where affinity puts tables and
where the blueprint puts classes — and until now only the first direction was
detectable.

The wider lesson is about method, and is recorded here because it cost real time: every
conclusion in DD-174 through DD-179 was drawn from one domain of five narrow tables, and
the first different domain overturned the headline number. Single-domain measurement
sets a hypothesis; it does not settle one.
