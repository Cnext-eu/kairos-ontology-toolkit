# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scaffold XML templates must render to well-formed XML."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path


SCAFFOLD_DIR = Path("src/kairos_ontology/scaffold")


def _render_placeholders(content: str) -> str:
    values = {
        "company_name": "Contoso",
        "company_domain": "contoso.example",
        "refmodels_ref": "v1.20.0",
        "refmodels_version": "1.20.0",
        "refmodels_channel": "preview",
    }
    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: values.get(m[1], "dummy"), content)


def _xml_comment_bodies(content: str) -> list[str]:
    return re.findall(r"<!--(.*?)-->", content, flags=re.DOTALL)


def test_scaffold_xml_templates_render_to_wellformed_xml():
    xml_paths = sorted(SCAFFOLD_DIR.rglob("*.xml")) + sorted(SCAFFOLD_DIR.rglob("*.xml.template"))
    assert xml_paths

    for path in xml_paths:
        rendered = _render_placeholders(path.read_text(encoding="utf-8"))
        ET.fromstring(rendered)


def test_catalog_template_has_no_next_catalog():
    """The catalog template must not contain a <nextCatalog> element (DD-158).

    The reference-models catalog is overlaid at runtime via
    CatalogResolver.with_reference_models(), not via XML catalog chaining.
    The comment block may mention <nextCatalog> as guidance, but the element
    must not be present.
    """
    catalog_template = SCAFFOLD_DIR / "ontology-hub" / "catalog-v001.xml.template"
    rendered = _render_placeholders(catalog_template.read_text(encoding="utf-8"))
    # Parse the XML and assert no nextCatalog element exists in the tree
    root = ET.fromstring(rendered)
    # nextCatalog is not in the default namespace, so search by local-name
    for child in root:
        assert child.tag.split("}")[-1] != "nextCatalog"
    catalog_template = SCAFFOLD_DIR / "ontology-hub" / "catalog-v001.xml.template"
    rendered = _render_placeholders(catalog_template.read_text(encoding="utf-8"))

    comments = _xml_comment_bodies(rendered)
    assert comments
    assert all("--" not in comment for comment in comments)
