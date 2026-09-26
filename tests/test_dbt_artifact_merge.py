# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the dbt artifact merge/reconciliation helpers (issue #220).

The full-hub projector merges each domain's dbt artifacts. Package-level files
(``dbt_project.yml``/``README.md``/``packages.yml``) and shared per-source
``_sources.yml`` files legitimately differ per domain and must be reconciled rather
than rejected as collisions.
"""

from __future__ import annotations

import pytest
import yaml

from kairos_ontology.core.projector import (
    SourcesUnionError,
    _merge_dbt_artifacts,
    _union_sources_yaml,
)


def _sources_doc(source_name: str, tables: list[str]) -> str:
    doc = {
        "version": 2,
        "sources": [
            {
                "name": source_name,
                "description": f"Bronze source: {source_name}",
                "database": "acme",
                "schema": "bronze",
                "tables": [{"name": t, "description": t} for t in tables],
            }
        ],
    }
    return yaml.safe_dump(doc, sort_keys=False)


def test_union_sources_yaml_unions_tables():
    a = _sources_doc("qargo", ["Booking", "Leg"])
    b = _sources_doc("qargo", ["Booking", "Consignment"])

    merged = _union_sources_yaml(a, b)
    doc = yaml.safe_load(merged)

    assert len(doc["sources"]) == 1
    src = doc["sources"][0]
    assert src["name"] == "qargo"
    names = [t["name"] for t in src["tables"]]
    # Deterministic union: deduped and stable-sorted by table name.
    assert names == ["Booking", "Consignment", "Leg"]
    # Header fields are preserved.
    assert src["database"] == "acme"
    assert src["schema"] == "bronze"


def test_union_sources_yaml_is_deterministic_regardless_of_order():
    a = _sources_doc("qargo", ["Leg", "Booking"])
    b = _sources_doc("qargo", ["Consignment"])
    assert _union_sources_yaml(a, b) == _union_sources_yaml(b, a)


def test_union_sources_yaml_raises_on_conflicting_source_header():
    """#584/#586: dbt allows one definition per source name — first-wins would let one
    domain's stale vocabulary silently override another's, so the union fails closed."""
    a = _sources_doc("qargo", ["Booking"])
    b = a.replace("database: acme", "database: other")

    with pytest.raises(SourcesUnionError, match="conflicting source metadata"):
        _union_sources_yaml(a, b)


def test_union_sources_yaml_raises_on_conflicting_table_entry():
    a = _sources_doc("qargo", ["Booking"])
    b = a.replace("description: Booking", "description: Changed")

    with pytest.raises(SourcesUnionError, match="conflicting table entry"):
        _union_sources_yaml(a, b)


def test_merge_dbt_artifacts_reports_sources_union_conflict_as_collision():
    """The legacy generate path must fail closed in its documented collision style."""
    path = "models/silver/_qargo__sources.yml"
    dest = {path: _sources_doc("qargo", ["Booking"])}

    with pytest.raises(
        RuntimeError,
        match="Generated dbt artifact collisions.*_qargo__sources.*conflicting source metadata",
    ):
        _merge_dbt_artifacts(
            dest,
            {path: _sources_doc("qargo", ["Booking"]).replace("schema: bronze", "schema: other")},
            context="Generated dbt artifact collisions",
        )


def test_merge_dbt_artifacts_package_level_last_wins():
    """Package-level config must not collide — the orchestrator regenerates it."""
    dest = {"dbt_project.yml": "domain-a", "README.md": "readme-a"}
    _merge_dbt_artifacts(
        dest,
        {"dbt_project.yml": "domain-b", "README.md": "readme-b"},
        context="Generated dbt artifact collisions",
    )
    # Does not raise; last write wins (definitive version regenerated post-loop).
    assert dest["dbt_project.yml"] == "domain-b"
    assert dest["README.md"] == "readme-b"


def test_merge_dbt_artifacts_unions_shared_sources():
    path = "models/silver/_qargo__sources.yml"
    dest = {path: _sources_doc("qargo", ["Booking"])}
    _merge_dbt_artifacts(
        dest,
        {path: _sources_doc("qargo", ["Consignment"])},
        context="Generated dbt artifact collisions",
    )
    names = [t["name"] for t in yaml.safe_load(dest[path])["sources"][0]["tables"]]
    assert names == ["Booking", "Consignment"]


def test_merge_dbt_artifacts_identical_shared_gold_passes():
    path = "models/gold/shared/dim_date.sql"
    dest = {path: "SELECT 1"}
    _merge_dbt_artifacts(dest, {path: "SELECT 1"}, context="Generated dbt artifact collisions")
    assert dest[path] == "SELECT 1"


def test_merge_dbt_artifacts_raises_on_real_collision():
    path = "models/silver/client/dim_client.sql"
    dest = {path: "SELECT 1"}
    with pytest.raises(RuntimeError, match="Generated dbt artifact collisions"):
        _merge_dbt_artifacts(dest, {path: "SELECT 2"}, context="Generated dbt artifact collisions")


def _rendered_catalog(tables: tuple[str, ...], *, logical: bool = False, label: str = "") -> str:
    from kairos_ontology.core.projections.dbt.render import _render_source, _template_environment
    from kairos_ontology.core.projections.dbt.specs import SourceCatalogSpec, SourceTableSpec
    from tests.test_dbt_phases import TEMPLATE_DIR

    spec = SourceCatalogSpec(
        artifact_path="models/silver/_tms__sources.yml",
        source_name="tms",
        system_label="Acme TMS",
        database="acme",
        schema="bronze",
        tables=tuple(SourceTableSpec(name=t, label=label or t) for t in tables),
        logical_sources_only=logical,
    )
    return _render_source(spec, _template_environment(str(TEMPLATE_DIR)))


@pytest.mark.parametrize("logical", (False, True))
def test_a_rendered_catalog_is_already_in_union_layout(logical):
    """#1009: union with its own previous output must not change a single byte."""
    rendered = _rendered_catalog(("booking", "leg"), logical=logical)
    assert _union_sources_yaml(rendered, rendered) == rendered
    assert _union_sources_yaml("", rendered) == rendered


def test_the_union_of_two_rendered_catalogs_is_order_independent_and_stable():
    a = _rendered_catalog(("booking",))
    b = _rendered_catalog(("leg",))
    merged = _union_sources_yaml(a, b)
    assert merged == _union_sources_yaml(b, a)
    assert _union_sources_yaml(merged, a) == merged
    assert _union_sources_yaml(merged, b) == merged


def test_the_logical_sources_note_survives_the_union():
    rendered = _rendered_catalog(("booking",), logical=True)
    merged = _union_sources_yaml(rendered, _rendered_catalog(("leg",), logical=True))
    assert merged.startswith("# Physical database/schema binding is defined")
    assert "database:" not in merged


def test_a_label_with_quotes_or_accents_renders_valid_yaml():
    rendered = _rendered_catalog(("booking",), label='Boeking "export" — é')
    table = yaml.safe_load(rendered)["sources"][0]["tables"][0]
    assert table["description"] == 'Boeking "export" — é'
    assert "é" in rendered
