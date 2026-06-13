# Kairos for Context Engineers — A Methodology Guide

> **Audience:** Context engineers and modelers who shape *how* the LLM-assisted
> design stages reason — what is computed deterministically, what is prompted, and
> what stays a human decision.
>
> This guide explains the **design stage model** (the two design models you
> reconcile) and the **three tiers of work** inside each design stage. It is about
> *where intelligence lives*, not how to install tools.

---

## 1. The Two Design Models

During design you are always juggling **two different models**, and the entire
design pipeline exists to reconcile them:

1. **The domain ontology** (`model/*.ttl`) — what the business *means*: classes
   like `Client`, `CorporateClient`, properties like `isActive`, `nationalID`.
   Often built by importing parts of a **reference model** (e.g. a logistics or
   party accelerator) and specializing it.
2. **The source vocabulary** (bronze) — what a source system *actually has*:
   tables like `tblClient`, columns like `IsActive bit`, `Type`, `NationalID`.

Design is the act of **reconciling** these two: deciding what the domain should
contain, then which source column means which domain property and how to transform
one into the other.

```
                 ┌─────────────────────────────────────────────┐
                 │  DOMAIN ONTOLOGY  (what the business means)   │
                 │  Client · CorporateClient · isActive · ...    │
                 └─────────────────────────────────────────────┘
   design-domain  ▲                                   │  design-mapping
   (build/extend  │                                   ▼  (bind sources)
    the model)    │                                   │
                 ┌─────────────────────────────────────────────┐
                 │  SOURCE VOCABULARY (what the source has)      │
                 │  tblClient · IsActive bit · Type · ...         │
                 └─────────────────────────────────────────────┘
```

---

## 2. The Design Stages

### Stage A — `design-domain` (build the model)

You decide what classes/properties the domain should have. To avoid modeling in a
vacuum, it reads `*-alignment.yaml` to pre-populate a **Source Evidence Table**:
"your sources contain `IsActive`, `NationalID`, `Type`… so the domain probably
needs `isActive`, `nationalID`, and maybe subclasses by `Type`." This is
**pre-modeling** — alignment is used as *evidence for what to model*. Output:
`model/*.ttl`.

### Stage B — `design-mapping` (bind sources to the finished model)

Now the domain model exists. For each source table you decide, column by column:
which domain property it maps to (SKOS predicate) and the SQL transform. Output:
`model/mappings/*.ttl`. This is **interactive reasoning** behind hard gates (must
read bronze + ontology independently, must confirm every mapping with the human,
write TTL only after confirmation).

> **One artifact, two consumers.** The same `*-alignment.yaml` feeds *both* stages:
> Stage A uses it to decide *what to model*; Stage B uses it to decide *how to
> bind*. This is why the alignment output cannot be restructured or deprecated
> without coupling two separate lifecycle stages (see DD-043, DD-045).

---

## 3. The Three Tiers of Work

The central context-engineering principle: **do not treat a design stage as one
monolithic LLM task.** Every stage is a mix of three very different kinds of work,
and each kind belongs to a different tool. Putting work in the wrong tier is the
root cause of both *unreliable output* (judgment sent to code) and *wasted,
non-reproducible effort* (deterministic work sent to an LLM).

| Tier | Nature | Examples | Right tool |
|---|---|---|---|
| **1. Deterministic** | Fully specified; one correct answer | Unpacking a reference model's subclass closure; pulling inherited data properties; building an inventory; comparing a column `data_type` to a property range | **Pure code, no LLM** — reproducible, unit-testable (e.g. DD-044 `generate-inventory`, specialization discovery) |
| **2. Promptable / pattern-based** | Open-ended but pattern-driven; a *candidate* answer | Proposing class labels/comments; suggesting specializations from source evidence; proposing a SKOS predicate or a `CAST(...)` transform candidate | **LLM API**, versioned prompt, fixed temperature — **candidate output only**, `requires_human_confirmation` |
| **3. Judgment / business context** | Requires business stakes the model can't see | "Is `CorporateClient` a meaningful distinction for *this* business?"; naming alignment; domain scope; which accelerator parts to adopt; whether a transform encodes the right policy | **Human + interactive Copilot**, behind confirmation gates — **never automated** |

### How to apply the tiers

1. **Push everything you can down to Tier 1.** If `rdflib` graph traversal can
   compute it reproducibly, never pay an LLM to guess it. Much of what *feels*
   LLM-shaped (unpacking reference subclasses, inherited properties, type
   comparison) is deterministic and already built.
2. **Use Tier 2 for candidates, never for committed artifacts.** A Tier-2 LLM call
   produces a *draft* carrying confidence + rationale + `requires_human_confirmation`.
   It accelerates the human; it does not author production TTL or SQL. A draft that
   looks *too* finished invites rubber-stamping — the failure mode that
   confirmation gates exist to prevent.
3. **Keep Tier 3 interactive and gated.** Business-alignment checkpoints, naming
   confirmation, and final authoring stay with the human + Copilot. This is where
   the value and the accountability live.

### Worked example — the SKOS predicate

The SKOS predicate (`exactMatch` / `closeMatch` / …) is **Tier 1**: it is a
mechanical relabel of the existing `alignment` category already computed in
`propose-alignment`. So it is *not* emitted as a separate hint — the
`design-mapping` skill derives it directly. By contrast, a `CAST(...)` transform is
**Tier 2** (a type-grounded candidate that must be confirmed), and "does this split
on `Type` reflect a real business distinction?" is **Tier 3** (human judgment). One
column mapping touches all three tiers — the engineering is in routing each part to
the right tier. (See DD-045 for how this shaped the mapping-hints design.)

---

## 4. Why This Matters

| Symptom | Likely tier error |
|---|---|
| Output is non-reproducible / changes between runs | Tier-1 work sent to an LLM (Tier 2/3) |
| LLM authored a transform or class that was subtly wrong | Tier-3 judgment sent to an LLM (Tier 2) |
| Humans rubber-stamp polished LLM proposals | Tier-2 candidate presented as authoritative |
| Conversation context "pollutes" the model | Tier-2 work left in free-form chat instead of a controlled, isolated API call |

**The goal of context engineering here:** keep each piece of design work in its
correct tier — deterministic where possible, prompted where patterned, and human
where the business stakes are highest — so the system is reproducible *and*
trustworthy at the same time.

---

## Related design decisions

- **DD-043** — `propose-alignment` as a pre-modeling artifact (the shared
  `*-alignment.yaml`).
- **DD-044** — deterministic reference-model inventories + specialization discovery
  (Tier 1).
- **DD-045** — mapping hints for `propose-alignment`: Tier-1 SKOS derivation,
  Tier-2 transform/structural candidates, Tier-3 human confirmation.
- **DD-046** — reference-model specialization visibility in `design-domain`:
  surfaces subclass-defined properties (from the Tier-1 DD-044 inventories) so the
  modeler reuses an existing subclass instead of creating a local duplicate.
