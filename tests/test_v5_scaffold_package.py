# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Package-data contract for the lean v5 hub scaffold."""

from pathlib import Path

import kairos_ontology


def test_packaged_v5_scaffold_contract() -> None:
    scaffold = Path(kairos_ontology.__file__).parent / "scaffold"
    required = {
        "ontology-hub/kairos.yaml.template",
        "ontology-hub/catalog-v001.xml.template",
        "ontology-hub/model/ontologies/master.ttl.template",
        "ontology-hub/model/ontologies/foundation.ttl.template",
        "ontology-hub/model/ontologies/starter.ttl.template",
        "ontology-hub/model/shapes/README.md",
        "ontology-hub/integration/bindings/README.md",
        "ontology-hub/integration/sources/README.md",
        "ontology-hub/integration/transforms/dbt/README.md",
    }
    retired = {
        "ontology-hub/model/governance/release-baseline.yaml",
        "ontology-hub/model/extensions/silver-ext.ttl.template",
        "ontology-hub/integration/preparation/source-prep.ttl.template",
        "ontology-hub/integration/transforms/dbt/evidence/README.md",
    }

    assert all((scaffold / path).is_file() for path in required)
    assert all(not (scaffold / path).exists() for path in retired)
