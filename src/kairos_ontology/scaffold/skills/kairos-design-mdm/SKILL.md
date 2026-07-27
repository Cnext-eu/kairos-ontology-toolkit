---
name: kairos-design-mdm
description: Author optional design-time MDM policy consumed from the canonical v5 CompilePlan.
---

# Kairos MDM Design

MDM policy is an optional, runtime-neutral consumer of canonical entities in the immutable
CompilePlan. EntityBinding remains the sole source-to-canonical execution authority. Runtime
matching, stewardship, operational storage, and synchronization belong outside this toolkit.

## Design fleet mode (DD-088)

Default is interactive. A fleet override applies only to this skill invocation and is never
inherited. Record rationale, confidence, and references for every AI-approved choice. Stop for
uncertain identifiers, automatic merge bounds, survivorship, sensitive data, reference-data
licensing, or destructive choices.

## Policy design

For each mastered canonical class, review and author:

- MDM style and whether the class is mastered or governed reference data;
- identifiers and match attributes;
- deterministic match rules, comparators, thresholds, and actions;
- authoritative sources, survivorship strategy, and deterministic tie-breakers;
- maker/checker behavior, abstract steward roles, escalation, and service targets;
- reference-data ownership/licensing policy; and
- data-quality dimensions, thresholds, and severity.

Probabilistic models are referenced only by immutable URI, version, and digest; never embed model
weights. Environment identity mappings are downstream configuration.

Compile the domain first with `kairos-ontology compile <domain> --check --format json`. Project the
MDM profile only through the registered CompilePlan consumer. The MDM consumer must not load source
or ontology scope independently, rebuild the plan, or alter canonical materialization.
