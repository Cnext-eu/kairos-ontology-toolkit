# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Second-source fixture for the DD-213 conformance-relaxation tests."""

from __future__ import annotations

import yaml

ERP_VOCABULARY_HEADER = """@prefix src2: <https://example.test/source2#> .
@prefix kb: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
src2:erp a kb:SourceSystem ; rdfs:label "erp" ;
  kb:database "raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .
src2:parties a kb:SourceTable ; kb:sourceSystem src2:erp ;
  kb:tableName "parties" ; kb:primaryKeyColumns "party_id" .
src2:eid a kb:SourceColumn ; kb:sourceTable src2:parties ;
  kb:columnName "party_id" ; kb:dataType "varchar(50)" ;
  kb:nullable "false"^^xsd:boolean .
"""

ERP_NAME_COLUMN = """src2:ename a kb:SourceColumn ; kb:sourceTable src2:parties ;
  kb:columnName "party_name" ; kb:dataType "varchar(200)" ;
  kb:nullable "true"^^xsd:boolean .
"""

_CONFORMANCE = {
    "group": "party-customer",
    "conflict": "prefer-precedence",
    "union": {"mode": "union-all"},
}


def add_second_source(hub_root, binding_dir, *, partial: bool) -> None:
    """Add an ERP binding for the same class, optionally missing one property.

    ``partial=True`` is the case DD-213 exists to make possible: a second source that
    genuinely cannot supply every property the incumbent does.
    """
    source_dir = hub_root / "integration" / "sources" / "erp"
    source_dir.mkdir(parents=True, exist_ok=True)
    vocabulary = ERP_VOCABULARY_HEADER + ("" if partial else ERP_NAME_COLUMN)
    (source_dir / "erp.vocabulary.ttl").write_text(vocabulary, encoding="utf-8")

    fields = [{"property": "party:customer_id", "expression": "party_id"}]
    if not partial:
        fields.append({"property": "party:customerName", "expression": "party_name"})
    document = {
        "apiVersion": "kairos.eu/v5",
        "kind": "EntityBinding",
        "metadata": {"name": "erp-customer", "domain": "party"},
        "source": {"relation": "erp.parties"},
        "target": {"class": "party:Customer"},
        "grain": {"columns": ["party_id"]},
        "identity": {"strategy": "source-natural", "sourceKey": ["party_id"]},
        "load": {"mode": "full-refresh"},
        "conformance": {**_CONFORMANCE, "sourcePrecedence": 2},
        "fields": fields,
    }
    if partial:
        document["unmapped"] = ["party:customerName"]
    (binding_dir / "erp-customer.binding.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
    )

    # The incumbent must join the same conformance group for the group to exist at all.
    path = binding_dir / "customer.binding.yaml"
    incumbent = yaml.safe_load(path.read_text(encoding="utf-8"))
    incumbent["conformance"] = {**_CONFORMANCE, "sourcePrecedence": 1}
    path.write_text(yaml.safe_dump(incumbent, sort_keys=False), encoding="utf-8")
