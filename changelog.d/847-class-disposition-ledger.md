### Added
- **A class-level disposition ledger, `integration/discovery/class-dispositions.yaml` (DD-231,
  closes #847).** The class-side sibling of the source-table ledger: an `owl:Class` no
  EntityBinding targets never enters the plan — correct — but "not bound yet, deliberately,
  because X" had nowhere to live, so a context engineer's logical model in the ontology looked
  forgotten. `kairos-ontology class-disposition set --class <IRI or prefix:Local> --disposition
  deferred|architecture-only|abstract --rationale "..."` records the decision; `list
  [--undecided]`, `clear` and `init` complete the surface. `bound` and `bound-via-subclass` are
  derived from the bindings, never authored. **Adoption is opt-in, then binding:** until the hub
  creates the ledger (`init`, or the first `set`) `validate` reports undecided classes as
  warnings, so no existing hub goes red on upgrade; afterwards an undecided class is an error,
  degradable with `--degraded` like DD-164. A malformed ledger is itself the error, never read as
  empty; `decided_by` is closed in core; a disposition left behind on a class that a binding now
  targets is reported as `class-disposition.stale`.
