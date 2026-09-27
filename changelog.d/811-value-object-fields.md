### Added
- **A binding can map a value object's scalars onto its parent with `via` (DD-252).**
  Reference models put much of their meaning in object properties whose range is a value
  object, such as `cargo:hasGrossWeight` to `Weight{weightValue, weightUnit}`. `fields:`
  took scalars only. So the choice was a companion binding plus a relationship, which made
  one Silver table per value object, or a `purpose: carried` technical field with no
  ontology property behind it. Now a field can name the object property that reaches the
  value object:

  ```yaml
  fields:
    - property: cargo:weightValue
      via: cargo:hasGrossWeight
      expression: GROSSWEIGHT
  ```

  The value lands on the parent's table as `gross_weight_value`. The column is named from
  both hops, with the shared word written once. Its provenance records both the scalar
  property and the `via`. Two value objects of one class, such as gross and net weight,
  give two columns. `fit-report` counts the `via` object property as populated.

  `via` must be single-valued in OWL: `owl:FunctionalProperty`, or a max-1 restriction on
  the class or an ancestor (DD-241). Most accelerator value objects declare no bound, so
  `binding.value-object-not-single-valued` blocks the field and prints the restriction to
  add to the hub's own class. The binding never asserts the bound. A class governed by a
  Silver contract, and a value object inside a value object, are refused with their own
  diagnostics for now. A hub that authors no `via` field gets byte-identical output.

### Decisions
- **DD-252:** a single-valued value object's scalars are fields of its parent, named
  through `via`.
