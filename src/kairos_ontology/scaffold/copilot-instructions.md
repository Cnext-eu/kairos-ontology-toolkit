# Kairos Ontology Hub — Agent instructions

This repository's agent instructions are in `AGENTS.md` at the repository root. Read it before
acting. This file exists for the Copilot surfaces that do not read `AGENTS.md`, and it carries
only the rules that must never be missed:

- Never read an ontology serialization (`.ttl`, `.rdf`, `.owl`) as text. Use
  `kairos-ontology explain-term`, `list-class-properties`, `show-class-inventory` or
  `resolve-ontology` (or the same tools on the hub's MCP server): they read the `owl:imports`
  closure, which one file does not contain (DD-103).
- Never hand-edit `../ontology-hub-publish/`; it is compiler output.
- Invoke the owning `kairos-*` skill under `.claude/skills/` before a design change or a
  skill-managed command; `kairos-flow` picks the next step.
