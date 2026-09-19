### Fixed
- **A dangling `ref()` in a join position is now reported (issue #823).** The dbt ref scan
  built its set of acceptable targets partly *from the content it was about to check*: a
  regex collected every `join ... ref('X')` in the artifacts and added X to the known set.
  A ref in a join position therefore whitelisted itself and could never be reported —
  including when the name was a typo naming nothing at all. It was the one place a
  dangling ref could hide from this scan completely.

  The exemption turned out to be load-bearing rather than dead weight, which measuring
  before deleting it revealed: one of the three join-position refs across the committed
  scenario hubs is a legitimate **cross-domain relationship join**, which is neither in the
  domain's render scope nor any binding's declared contract. Simply removing the exemption
  would have reintroduced a false positive of exactly the class #728 removed.

  The scan now consults the joins the project actually *declares* — `JoinSpec` already
  carries the referenced model as structured data — so a declared cross-domain join is
  known while a string that merely appears in a join position is not.
