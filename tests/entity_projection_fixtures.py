# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Fixture entity-projection packs for the DD-188 detector tests (issue #531).

Deliberately a **fixture, not the live pack**. The point of DD-188 is that the
vocabulary ships in reference-models and can change there without a toolkit
release; tests that read the installed pack would pin today's data instead of the
contract, and would start failing for reasons that are not the toolkit's.

``POSTAL_ADDRESS_YAML`` is the DD-188 shared contract's worked example verbatim —
it is what the ``logistics`` pack is authored against, so the toolkit's semantics
are exercised against the same shape the producer emits.
"""

from __future__ import annotations

from pathlib import Path

ADDRESS_URI = "https://www.kairosflow.ai/ont/bsp/reference-data#Address"

#: The contract's worked example. Note what it exercises beyond the old hardcoded
#: vocabulary: ``pickup`` (absent from ``_ADDRESS_QUALIFIER_TOKENS``), ``weak`` on
#: ``city``/``country``, and ``requires: context`` on ``state``.
POSTAL_ADDRESS_YAML = f"""\
schema_version: 1

projections:
  - id: postal-address
    target_concept: Address
    target_candidates:
      - {ADDRESS_URI}
    min_complementary_parts: 2
    relationship_naming: "has{{Role}}Address"
    default_relationship: hasAddress
    cardinality: "1:n"

    part_kinds:
      - kind: street
        tokens: [street]
      - kind: house_number
        tokens: [house]
        compact: [housenumber, houseno]
      - kind: postal
        tokens: [zip, postal, postcode]
        compact: [postalcode, zipcode]
      - kind: city
        tokens: [city, town]
        weak: true
      - kind: state
        tokens: [state, province, region]
        requires: context
      - kind: country
        tokens: [country]
        weak: true
      - kind: address_line
        tokens: [address, addressline]

    role_qualifiers: [shipper, consignee, billing, shipping, delivery, invoice,
                      mailing, registered, home, work, contact,
                      pickup, collection, origin, destination,
                      loading, unloading, depot, terminal, port]

    context_tokens: [location, premises, site, facility]
"""


def write_projection_pack(
    root: Path,
    yaml_text: str = POSTAL_ADDRESS_YAML,
    accelerator: str = "logistics",
    subdir: str = "client-hub-blueprint",
) -> Path:
    """Write *yaml_text* as ``<root>/accelerator-packs/<accelerator>/<subdir>/entity-projections.yaml``.

    Returns the path written, so a test can assert the loader found that exact file.
    """
    path = Path(root) / "accelerator-packs" / accelerator / subdir / "entity-projections.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8")
    return path


def load_fixture_projections(yaml_text: str = POSTAL_ADDRESS_YAML):
    """Parse *yaml_text* into the tuple of ``EntityProjection`` the detector takes."""
    import yaml

    from kairos_ontology.core.entity_projections import parse_entity_projections

    return parse_entity_projections(yaml.safe_load(yaml_text)).projections
