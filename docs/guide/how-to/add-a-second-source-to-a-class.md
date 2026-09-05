# Add a second source to a class

**Skill:** `kairos-design-mapping`

Onboarding a second system to a class you already model is the case that most often
surprises people, because the two bindings are not independent.

## The constraint

`conformance.property-incompatible` requires every binding in a conformance group to
declare an **identical** property set. Adding a second source therefore either forces the
new binding to match the existing one, or forces an edit to the existing one.

That is deliberate — a Silver model has one shape — but note the consequence: without a
declared contract, an ordinary source-onboarding event can reshape the canonical model.
DD-213 addresses this by making the contract a third authored input that bindings conform
*to* rather than constitute. Gate A, compile-time conformance, is implemented; the
release-time comparison (Gate B) is not.

## Steps

1. **See the shape you have to match.**

   ```bash
   kairos-ontology compile billing --explain --format json
   kairos-ontology fit-report --class Invoice --domain billing --source erp
   ```

2. **Author the second binding** against the same class, starting from the existing one
   rather than from scratch:

   ```bash
   kairos-ontology scaffold-binding --system erp --table invoice_header \
     --target-class Invoice --domain billing \
     --from-binding integration/bindings/crm-invoices.binding.yaml
   ```

3. **Compile and read the conformance diagnostics.**

   ```bash
   kairos-ontology compile billing --check
   ```

   A `conformance.*` code means the two bindings disagree about the entity's shape. Decide
   which is right. Do not simply delete the property from whichever binding complains —
   deleting a `fields:` entry drops a Silver column.

4. **If the domain has a contract**, `contract.*` diagnostics name the declared shape and
   how each binding deviates. That is the better failure: it states the intended shape
   instead of letting the first binding become the de-facto standard.

## Verify

```bash
kairos-ontology compile billing --check
kairos-ontology audit-column-coverage
```

## Record the decision

Which source wins for a property both populate is exactly the choice that is invisible six
months later. See [Record a decision](record-a-decision.md).
