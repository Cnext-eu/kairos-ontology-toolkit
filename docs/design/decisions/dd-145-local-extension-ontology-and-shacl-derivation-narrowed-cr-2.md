# DD-145: Local-Extension Ontology and SHACL Derivation (Narrowed CR-2)

**Status:** Accepted
**Date:** 2026-08-09
**Affects:** `core/suggest_shapes.py`, `core/compiler/result.py` (`ExplainEntity`), a new
`derive-ontology --from-binding` CLI surface
**Implementation:** deferred pending accelerator-pack Silver/SHACL defaults content; toolkit
mechanism scoped here with a documented fallback

### Context

CR-2 (`docs/temp/cr-fast-path-to-silver.md`) originally proposed deriving a domain's
ontology TTL and SHACL shapes wholesale from its `EntityBinding` YAML, to stop hand-authoring
three mutually-redundant artifacts per entity. Read literally, this contradicts DD-133's
explicit statement that an `EntityBinding` is "validated ... then converted directly into
frozen dataclasses and the existing graph-free mapping AST — never serialized to intermediate
RDF." Once DD-144 makes accelerator-direct binding the default for both tiers, the scope of
what CR-2 actually needs to solve shrinks: in the non-deviating case there is no local class
or shape to keep in sync with the binding at all (DD-144's machine-managed stub declares no
local terms), so there is nothing to derive. CR-2 only still matters for the **local-extension
case** — a binding whose target class genuinely deviates from the accelerator and therefore
does declare a local subclass with one or more extension properties, which do need *some*
ontology declaration and, if SHACL validation is desired, a shape.

### Decision

Narrow CR-2 to local-extension properties only, and adopt the CR's "option 2" shape uniformly
(never the "derive in place as a reviewable diff" alternative), so DD-133's authored-input
invariant never has an exception to remember: a `derive-ontology --from-binding <path>`
command reads an `EntityBinding`'s local-extension `fields:` (properties whose class is a
locally-declared subclass, per DD-144) and **scaffolds** — never silently writes into the
authored tree — a small TTL fragment (one `owl:DatatypeProperty` per extension field, domain/
range inferred from the source contract and the binding's resolved expression type) for a
human to review and merge into the domain's ontology file by hand. The same command, when
the accelerator pack ships a reviewed SHACL shape for the parent accelerator class (content
that is `docs/temp/logistics-accelerator-dbt-silver-design-plan.md` §7's "pending"
`silver-defaults/*.ttl`, not yet available for logistics), scaffolds a small SHACL fragment
**extending** that shape with constraints for the extension properties only — never a full
per-hub shape derived from scratch. When no accelerator shape default exists, the command
scaffolds a shape for the local-extension properties alone, with the same "advisory, human
reviews" framing `suggest-shapes` (DD-076) already uses, and does not attempt to describe the
accelerator-owned portion of the class at all.

`suggest-shapes`'s existing, currently-unused `mappings:` extension point
(`core/suggest_shapes.py`, "Extension point for DD-076+: mappings may later retarget shapes to
domain properties") is the intended seam: retargeted from raw bronze-profiling input to the
compiler's already-resolved `ExplainEntity.fields`/`target_class`/`grain`
(`compiler/result.py`), scoped to local-extension fields only.

### Rationale

Narrowing to the local-extension case is what DD-144 makes possible: it was the introduction
of accelerator-direct binding that removed the non-deviating case from CR-2's scope entirely,
not a separate decision. Choosing the explicit-scaffold shape uniformly (rather than CR-2's
original per-tier split) means DD-133's "authored TTL is an input, never an output" rule holds
without a carve-out to track and re-justify later. Reusing `suggest-shapes`'s existing,
already-designed-for-this extension point avoids building a second SHACL-generation code path
next to the one that already exists for the bronze-profiling case.

### Consequences

- No change to DD-133's authored-input contract; no intermediate RDF is ever produced from a
  binding except as an explicitly-requested, human-reviewed scaffold output, matching how
  `suggest-shapes` and `scaffold-mapping`'s legacy scaffolds already behave.
- This decision records the mechanism; **implementation is deferred**. The toolkit-side
  scaffold command can be built without waiting on the accelerator pack, with a documented
  fallback (no reused shape, extension-only shape) when no accelerator default exists — but
  the full value of "extend, don't derive" is gated on that content shipping.
- Full CR-2 (deriving a shape for the accelerator-owned portion of a class) is explicitly
  **not** adopted — DD-144 makes it unnecessary, and attempting it would recreate the
  cross-file consistency burden this whole initiative exists to remove.

---
```
