---
name: kairos-design-discovery
description: Capture confirmed business context and terminology for ontology and binding design.
---

# Business Discovery

Capture business context under `integration/discovery/` before ontology and binding design.
Discovery inputs may include user statements, repository documents, and public research.

## Design fleet mode (DD-088)

Default is interactive. An explicit fleet override applies only to this skill invocation and is
never inherited. Record rationale, confidence, and references for every AI-approved choice. Stop
for ambiguity, low confidence, sensitive data, or consequential policy choices.

## Workflow

1. Read existing discovery inputs and the hub README before proposing changes.
2. Summarize the company, offerings, operating concepts, and terminology. Mark public research as
   inferred until approved; never present inference as stakeholder-confirmed fact.
3. Confirm or AI-approve each business term and ontology link before writing it.
4. Write business context as ordinary Markdown/YAML and alternative terminology as an rdflib-built
   SKOS glossary. Keep canonical class/property definitions in `model/ontologies/` unchanged.
5. Link glossary concepts to ontology IRIs with semantic references; never redefine those IRIs.
6. Parse generated Turtle and report unresolved terms for later ontology or binding review.

Discovery artifacts are authored inputs, not execution authority. Source relations live under
`integration/sources/`; canonical meaning lives in OWL; source-to-canonical execution lives only in
closed `integration/bindings/*.binding.yaml` EntityBinding documents.
