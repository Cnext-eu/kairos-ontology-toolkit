# Custom-Transformation Mappings

Map generated virtual-source tables and columns to ontology classes and properties here
using the existing SKOS and `kairos-map:` vocabulary.

Use `kairos-design-mapping` after `kairos-ontology sync-dbt-contracts`. The generated
virtual vocabulary is a source boundary, not a second mapping mechanism. Do not duplicate
executable dbt SQL or decision logic in Turtle.
