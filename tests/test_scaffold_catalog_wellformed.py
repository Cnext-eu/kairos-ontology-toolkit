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


def test_scaffold_xml_template_comments_do_not_contain_double_hyphen():
    catalog_template = SCAFFOLD_DIR / "ontology-hub" / "catalog-v001.xml.template"
    rendered = _render_placeholders(catalog_template.read_text(encoding="utf-8"))

    comments = _xml_comment_bodies(rendered)
    assert comments
    assert all("--" not in comment for comment in comments)
