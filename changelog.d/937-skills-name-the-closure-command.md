### Documentation
- **The skills name the closure-aware command where they used to say "read the ontology"
  (DD-243 follow-up).** `kairos-design-domain`'s reference step and `kairos-design-mapping`'s
  binding preparation now give the recipe — `show-class-inventory --domain <d>` for the tree,
  `list-class-properties <IRI> --domain <d>` for direct and inherited properties with their
  origin, `explain-term <IRI> --domain <d>` for one term — and every skill that carries the
  "never read a `.ttl` as text" rule now says why: a domain file carries only its own
  triples; the parents, inherited properties and inverse relations live in the modules it
  `owl:imports`, and only the CLI resolves that closure. The rule reaches the skills that
  lacked it (`design-discovery`, `design-source`, `develop-dbt-transformation`,
  `execute-project`, `execute-report`, `setup-migrate`, `toolkit-ops`, `flow`,
  `flow-autopilot`). Source vocabularies under `integration/sources/` are explicitly outside
  the rule.
- **`docs/guide/how-to/design-a-domain.md`** ran `list-class-properties` and `explain-term`
  without `--domain`, which is a usage error; fixed, and the how-to test now requires a
  scope on every inspection command. `USER_GUIDE.md` gains a short "Read the ontology through
  the CLI" section.
