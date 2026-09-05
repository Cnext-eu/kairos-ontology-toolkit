# MDM documentation — designed, not yet live

**Status: not in use.** Nothing in this directory describes shipped, exercised behaviour.
It is design material for a Master Data Management capability that has been specified but
not adopted: no hub runs it, and it should not be read as current guidance or maintained
as though it were.

| Document | What it is |
|---|---|
| [mdmhubdesignv2.md](mdmhubdesignv2.md) | The design proposal (1,050 lines) |
| [mdm-design-decisions.md](mdm-design-decisions.md) | A separate `MDM-DD-NNN` log, deliberately kept out of the toolkit log so MDM could move at its own cadence |
| [kairos-mdm-runtime.md](kairos-mdm-runtime.md) | Intended runtime integration |
| [mdm-navigator-spec.md](mdm-navigator-spec.md) | Navigator specification |
| [user-stories.md](user-stories.md) | Requirements gathering |

A CLI surface exists (`kairos-ontology mdm-validate`, the `kairos-design-mdm` skill, and
optional MDM policy in the CompilePlan), so the capability is reachable — but reachable is
not adopted. Treat anything here as a proposal until a decision records otherwise.

Because it is not live, this material is **not kept in step with the toolkit**. Check it
against the code before relying on any statement in it.
