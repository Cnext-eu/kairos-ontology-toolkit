# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for F1 (toolkit-optimizations, issue #219) — naming parity.

The dbt silver projector previously hardcoded ``silver_{domain}`` as the schema
and derived model names purely from the class local name, ignoring the
``kairos-ext:silverSchema`` / ``silverTableName`` / ``isReferenceData`` /
``namingConvention`` annotations that the silver DDL projector honours. That made
the two targets emit divergent physical names for the same ontology.

Both now consume the shared physical-naming helpers, so schema + table + SK-key
names must match across targets for the acme-hub ``client`` domain (which sets a
``silver`` schema override and several ``silverTableName`` overrides).
"""

import re

from kairos_ontology.core.projections.medallion_silver_projector import (
    generate_silver_artifacts,
)
from kairos_ontology.core.projections.shared import (
    silver_schema_name,
    silver_table_name,
)

from .conftest import (
    EXTENSIONS_DIR,
    SHAPES_DIR,
)


def _client_silver_ddl(client_ontology) -> str:
    graph, namespace, classes = client_ontology
    arts = generate_silver_artifacts(
        classes=classes, graph=graph, namespace=namespace, shapes_dir=SHAPES_DIR,
        ontology_name="client",
        projection_ext_path=EXTENSIONS_DIR / "client-silver-ext.ttl",
    )
    return "\n".join(v for k, v in arts.items() if k.endswith(".sql"))


class TestNamingParity:
    def test_dbt_schema_matches_silver_override(self, client_dbt_artifacts):
        # client-silver-ext sets kairos-ext:silverSchema "silver" — dbt must use it
        # (previously it hardcoded "silver_client").
        model = next(
            v for k, v in client_dbt_artifacts.items()
            if k.endswith("corporate_client.sql")
        )
        m = re.search(r"schema\s*=\s*'([^']+)'", model)
        assert m is not None
        assert m.group(1) == "silver"

    def test_dbt_honours_silver_table_name_override(self, client_dbt_artifacts):
        # ClientType has silverTableName "client_type"; the dbt model file must use it.
        paths = "\n".join(client_dbt_artifacts.keys())
        assert "models/silver/client/client_type.sql" in paths

    def test_silver_and_dbt_agree_on_schema_and_tables(
        self, client_ontology, client_dbt_artifacts
    ):
        ddl = _client_silver_ddl(client_ontology)
        # Silver DDL schema-qualifies tables as silver.<table>; client_pii and
        # identifier both carry silverTableName overrides.
        assert "silver.client_pii" in ddl
        assert "silver.identifier" in ddl
        # dbt emits the identical physical table names as model files.
        dbt_paths = "\n".join(client_dbt_artifacts.keys())
        for tbl in ("client_pii", "identifier"):
            assert f"models/silver/client/{tbl}.sql" in dbt_paths, (
                f"dbt missing model for {tbl}"
            )

    def test_sk_key_parity(self, client_ontology, client_dbt_artifacts):
        # The SK/unique_key derives from the (shared) physical table name, so the
        # dbt unique_key for identifier must be identifier_sk — matching silver's
        # primary key column (silver names the PK <table>_sk).
        ddl = _client_silver_ddl(client_ontology)
        assert "identifier_sk" in ddl
        model = next(
            v for k, v in client_dbt_artifacts.items()
            if k.endswith("/identifier.sql")
        )
        assert "identifier_sk" in model


class TestSharedNamingHelper:
    """The shared helper is the single source of truth for both targets."""

    def test_schema_default_is_byte_identical(self):
        from rdflib import Graph, URIRef
        g = Graph()
        onto = URIRef("https://ex.org/ont/foo")
        # No silverSchema annotation → default silver_{ontology_name}.
        assert silver_schema_name(g, onto, "foo") == "silver_foo"

    def test_table_default_is_byte_identical(self):
        from rdflib import Graph, URIRef
        g = Graph()
        cls = URIRef("https://ex.org/ont/foo#InvoiceLine")
        # No override, default naming convention → camel_to_snake.
        assert silver_table_name(g, cls, "InvoiceLine") == "invoice_line"

    def test_override_and_reference_prefix(self):
        from rdflib import Graph, Literal, URIRef
        from kairos_ontology.core.projections.shared import KAIROS_EXT
        g = Graph()
        cls = URIRef("https://ex.org/ont/foo#Country")
        # isReferenceData without silverTableName → ref_ prefix.
        g.add((cls, KAIROS_EXT.isReferenceData, Literal("true")))
        assert silver_table_name(g, cls, "Country") == "ref_country"
        # silverTableName override wins outright (no ref_ prefix applied).
        g.add((cls, KAIROS_EXT.silverTableName, Literal("country")))
        assert silver_table_name(g, cls, "Country") == "country"
