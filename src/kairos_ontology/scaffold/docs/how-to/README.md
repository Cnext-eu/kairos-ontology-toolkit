# How-to guides

Task recipes for people who already know roughly what they want. For a linear walkthrough
of the whole lifecycle read the [user guide](../USER_GUIDE.md); for the complete command
surface see the [CLI reference](../CLI_REFERENCE.md); for *why* the system is shaped this
way see the [architecture](https://github.com/Cnext-eu/kairos-ontology-toolkit/blob/main/docs/design/ontology-dbt-dataplatform-design-architecture.md) and
the [decision log](https://github.com/Cnext-eu/kairos-ontology-toolkit/blob/main/docs/design/toolkit-design-decisions.md).

| Goal | Guide |
|---|---|
| Start a new hub | [Create a hub](create-a-hub.md) |
| Agree and record what the business means | [Capture business context](capture-business-context.md) |
| Get a source system's schema into the hub | [Import a source system](import-a-source-system.md) |
| Define what the business means | [Design a domain](design-a-domain.md) |
| Connect a source table to a canonical entity | [Bind a source to an entity](bind-a-source-to-an-entity.md) |
| Onboard a second system to an entity you already model | [Add a second source to a class](add-a-second-source-to-a-class.md) |
| Handle logic a binding cannot express | [Write a contracted dbt model](write-a-contracted-dbt-model.md) |
| Produce the dbt artifacts | [Compile and emit](compile-and-emit.md) |
| Use the output downstream | [Consume from a dataplatform](consume-from-a-dataplatform.md) |
| Move to a newer toolkit | [Upgrade the toolkit](upgrade-the-toolkit.md) |
| Record why a modelling choice was made | [Record a decision](record-a-decision.md) |

Each guide names the skill that automates it. In an AI coding session, prefer the skill:
it runs pre-flight checks and validation gates the raw commands skip. These guides are
what the skill is doing, written out — for when you need to do it yourself, or to
understand a failure.

**One rule throughout.** Never read a `.ttl`, `.rdf` or `.owl` file as text to answer a
semantic question. Use `explain-term`, `show-class-inventory`, `list-class-properties` or
`resolve-ontology`. Serialised RDF does not reveal prefix-relative IRIs, properties
inherited across an `owl:imports` chain, or equivalence and inverse relations (DD-103).
