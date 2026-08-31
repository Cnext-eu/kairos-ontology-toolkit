# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI contracts for structured semantic inspection (issue #224)."""

import json

from click.testing import CliRunner

from kairos_ontology.cli.main import cli


ONTOLOGY = """\
@prefix ex: <https://example.org/domain#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/domain> a owl:Ontology ; owl:versionInfo "1.0" .
ex:Party a owl:Class ; rdfs:label "Party" .
ex:name a owl:DatatypeProperty ; rdfs:domain ex:Party ; rdfs:label "Name" .
"""


def test_resolve_ontology_json_contract(tmp_path):
    ontology = tmp_path / "domain.ttl"
    ontology.write_text(ONTOLOGY, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        ["resolve-ontology", str(ontology), "--json-output"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["import_complete"] is True
    assert len(payload["closure_hash"]) == 64
    assert payload["manifest"][0]["ontology_iri"] == "https://example.org/domain"


def test_show_class_inventory_discloses_slice_coverage(tmp_path):
    ontology = tmp_path / "domain.ttl"
    ontology.write_text(ONTOLOGY, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "show-class-inventory",
            "--ontology",
            str(ontology),
            "--max-classes",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["metadata"]["semantic_profile"] == "kairos-design"
    assert payload["metadata"]["included_class_count"] == 1
    assert payload["classes"][0]["uri"] == "https://example.org/domain#Party"


def test_explain_term_requires_full_uri_and_returns_provenance(tmp_path):
    ontology = tmp_path / "domain.ttl"
    ontology.write_text(ONTOLOGY, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "explain-term",
            "https://example.org/domain#Party",
            "--ontology",
            str(ontology),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["term"]["uri"] == "https://example.org/domain#Party"
    assert payload["term"]["provenance"]["source_identity"] == "https://example.org/domain"


def test_explain_term_accepts_domain_shorthand(tmp_path, monkeypatch):
    ontologies_dir = tmp_path / "model" / "ontologies"
    ontologies_dir.mkdir(parents=True)
    (ontologies_dir / "domain.ttl").write_text(ONTOLOGY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        [
            "explain-term",
            "https://example.org/domain#Party",
            "--domain",
            "domain",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["term"]["uri"] == "https://example.org/domain#Party"


def test_explain_term_requires_ontology_or_domain(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["explain-term", "https://example.org/domain#Party"])

    assert result.exit_code != 0
    assert "Provide --ontology or --domain" in result.output


def test_show_source_schema_returns_parsed_tables(tmp_path):
    sources = tmp_path / "sources"
    system_dir = sources / "erp"
    system_dir.mkdir(parents=True)
    (system_dir / "erp.ttl").write_text(
        """\
@prefix kb: <https://kairos.cnext.eu/bronze#> .
@prefix ex: <urn:source:> .
ex:Customer a kb:SourceTable ; kb:tableName "Customer" .
ex:Customer_Id a kb:SourceColumn ;
    kb:columnName "Id" ;
    kb:dataType "integer" ;
    kb:belongsToTable ex:Customer .
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["show-source-schema", "--system", "erp", "--sources", str(sources)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["system"] == "erp"
    assert payload["table_count"] == 1
    assert payload["tables"]["Customer"][0]["name"] == "Id"


# ---------------------------------------------------------------------------
# Issue #445 — bindable tokens in show-class-inventory and list-class-properties
# ---------------------------------------------------------------------------

ONTOLOGY_WITH_IMPORTS = """\
@prefix ex: <https://example.org/domain#> .
@prefix ext: <https://example.org/external#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/domain> a owl:Ontology ; owl:versionInfo "1.0" .
ex:Party a owl:Class ; rdfs:label "Party" .
ex:name a owl:DatatypeProperty ; rdfs:domain ex:Party ; rdfs:label "Name" .
ex:address a owl:DatatypeProperty ; rdfs:domain ex:Party ; rdfs:label "Address" .
"""


def test_show_class_inventory_exposes_tokens(tmp_path):
    ontology = tmp_path / "domain.ttl"
    ontology.write_text(ONTOLOGY_WITH_IMPORTS, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        ["show-class-inventory", "--ontology", str(ontology)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    party = payload["classes"][0]
    assert party["uri"] == "https://example.org/domain#Party"
    tokens = party["tokens"]
    # The full URI is always a bindable token.
    assert "https://example.org/domain#Party" in tokens
    # The declared @prefix alias ex:Party must be present.
    assert "ex:Party" in tokens
    # The domain-stem token domain:Party must be present.
    assert "domain:Party" in tokens


def test_show_class_inventory_tokens_empty_for_no_classes(tmp_path):
    ontology = tmp_path / "empty.ttl"
    ontology.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<https://example.org/empty> a owl:Ontology ; owl:versionInfo \"1.0\" .\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["show-class-inventory", "--ontology", str(ontology)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["classes"] == []


def _catalog(path, mappings: dict[str, str]):
    entries = "".join(f'  <uri name="{uri}" uri="{target}"/>\n' for uri, target in mappings.items())
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        f"{entries}</catalog>\n",
        encoding="utf-8",
    )
    return path


def test_show_class_inventory_domain_stem_token_is_scoped_to_the_root_namespace(tmp_path):
    """Issue #674: three imports declare an ambiguous `party:` prefix, each with their own
    `Contact` class in their own namespace. Before the fix, every one of them independently
    claimed `party:Contact` as a token via the unconditional `<domain-stem>:<local>` rule --
    even though compile only ever resolves that token for a class in the root ontology's own
    namespace. None of these imported classes live there, so none should claim it."""
    from kairos_ontology.core.ontology_loader import load_ontology
    from kairos_ontology.cli.inspection import _compute_class_tokens

    root = tmp_path / "party.ttl"
    root.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<https://example.test/root/party> a owl:Ontology ;\n"
        "    owl:imports <urn:bsp> ; owl:imports <urn:dcsa> ; owl:imports <urn:rail> .\n"
        "<https://example.test/root/party#LocalThing> a owl:Class .\n",
        encoding="utf-8",
    )
    for name, ns in (("bsp", "bsp"), ("dcsa", "dcsa"), ("rail", "rail")):
        (tmp_path / f"{name}.ttl").write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            f"@prefix party: <https://example.test/{ns}/party#> .\n"
            f"<urn:{name}> a owl:Ontology .\n"
            "party:Contact a owl:Class .\n",
            encoding="utf-8",
        )
    catalog = _catalog(
        tmp_path / "catalog.xml",
        {"urn:bsp": "bsp.ttl", "urn:dcsa": "dcsa.ttl", "urn:rail": "rail.ttl"},
    )

    loaded = load_ontology(root, catalog_path=catalog)

    bsp_tokens = _compute_class_tokens(loaded, root, "https://example.test/bsp/party#Contact")
    dcsa_tokens = _compute_class_tokens(loaded, root, "https://example.test/dcsa/party#Contact")
    rail_tokens = _compute_class_tokens(loaded, root, "https://example.test/rail/party#Contact")
    local_tokens = _compute_class_tokens(
        loaded, root, "https://example.test/root/party#LocalThing"
    )

    assert "party:Contact" not in bsp_tokens
    assert "party:Contact" not in dcsa_tokens
    assert "party:Contact" not in rail_tokens
    # The root's own class still gets its domain-stem token -- only the cross-namespace
    # leak is fixed, not the whole mechanism.
    assert "party:LocalThing" in local_tokens


def test_list_class_properties_exposes_tokens(tmp_path):
    ontology = tmp_path / "domain.ttl"
    ontology.write_text(ONTOLOGY_WITH_IMPORTS, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "list-class-properties",
            "https://example.org/domain#Party",
            "--ontology",
            str(ontology),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["class_uri"] == "https://example.org/domain#Party"
    tokens = payload["tokens"]
    assert "https://example.org/domain#Party" in tokens
    assert "ex:Party" in tokens
    assert "domain:Party" in tokens


def test_list_class_properties_tokens_for_unresolvable_class(tmp_path):
    ontology = tmp_path / "domain.ttl"
    ontology.write_text(ONTOLOGY, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "list-class-properties",
            "https://example.org/domain#NonExistent",
            "--ontology",
            str(ontology),
        ],
    )

    assert result.exit_code != 0
    assert "does not resolve" in result.output


# ---------------------------------------------------------------------------
# Issue #484 — --datatypes-only filter for list-class-properties
# ---------------------------------------------------------------------------

ONTOLOGY_MIXED_PROPERTIES = """\
@prefix ex: <https://example.org/domain#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<https://example.org/domain> a owl:Ontology ; owl:versionInfo "1.0" .
ex:Party a owl:Class ; rdfs:label "Party" .
ex:name a owl:DatatypeProperty ; rdfs:domain ex:Party ; rdfs:range xsd:string ; rdfs:label "Name" .
ex:age a owl:DatatypeProperty ; rdfs:domain ex:Party ; rdfs:range xsd:integer ; rdfs:label "Age" .
ex:knows a owl:ObjectProperty ; rdfs:domain ex:Party ; rdfs:range ex:Party ; rdfs:label "Knows" .
"""


def test_list_class_properties_datatypes_only_filters_to_datatype_properties(tmp_path):
    ontology = tmp_path / "domain.ttl"
    ontology.write_text(ONTOLOGY_MIXED_PROPERTIES, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "list-class-properties",
            "https://example.org/domain#Party",
            "--ontology",
            str(ontology),
            "--datatypes-only",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    prop_types = [p["property_type"] for p in payload["properties"]]
    assert prop_types == ["datatype", "datatype"]
    names = [p["name"] for p in payload["properties"]]
    assert "knows" not in names
    assert "name" in names
    assert "age" in names


def test_list_class_properties_without_flag_shows_all_properties(tmp_path):
    ontology = tmp_path / "domain.ttl"
    ontology.write_text(ONTOLOGY_MIXED_PROPERTIES, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "list-class-properties",
            "https://example.org/domain#Party",
            "--ontology",
            str(ontology),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    prop_types = sorted(p["property_type"] for p in payload["properties"])
    assert prop_types == ["datatype", "datatype", "object"]
    names = [p["name"] for p in payload["properties"]]
    assert "name" in names
    assert "age" in names
    assert "knows" in names


# ---------------------------------------------------------------------------
# Issue #480 — --all flag for show-class-inventory
# ---------------------------------------------------------------------------

ALL_DOMAIN_FINANCIAL = """\
@prefix fin: <https://example.org/financial#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<https://example.org/financial> a owl:Ontology ; owl:versionInfo "1.0" .
fin:Account a owl:Class ; rdfs:label "Account" .
fin:balance a owl:DatatypeProperty ; rdfs:domain fin:Account ; rdfs:range xsd:decimal ; rdfs:label "Balance" .
fin:hasHolder a owl:ObjectProperty ; rdfs:domain fin:Account ; rdfs:range fin:Party ; rdfs:label "Has Holder" .
fin:Party a owl:Class ; rdfs:label "Party" .
"""

ALL_DOMAIN_PARTY = """\
@prefix party: <https://example.org/party#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<https://example.org/party> a owl:Ontology ; owl:versionInfo "1.0" .
party:Person a owl:Class ; rdfs:label "Person" .
party:name a owl:DatatypeProperty ; rdfs:domain party:Person ; rdfs:range xsd:string ; rdfs:label "Name" .
"""

ALL_DOMAIN_EMPTY_CLASSES = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/propsOnly> a owl:Ontology ; owl:versionInfo "1.0" .
ex:lonely a owl:DatatypeProperty ; rdfs:label "Lonely" .
"""

ONTOLOGY_NO_DATATYPE_PROPERTIES = """\
@prefix rel: <https://example.org/relations#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/relations> a owl:Ontology ; owl:versionInfo "1.0" .
rel:Node a owl:Class ; rdfs:label "Node" .
rel:linkedTo a owl:ObjectProperty ; rdfs:domain rel:Node ; rdfs:range rel:Node ; rdfs:label "Linked To" .
"""


def _make_all_hub(hub_root):
    """Create a hub with two domain ontologies under model/ontologies/."""
    ont_dir = hub_root / "model" / "ontologies"
    ont_dir.mkdir(parents=True)
    (ont_dir / "financial.ttl").write_text(ALL_DOMAIN_FINANCIAL, encoding="utf-8")
    (ont_dir / "party.ttl").write_text(ALL_DOMAIN_PARTY, encoding="utf-8")
    # Non-domain files that must be excluded by is_domain_ontology_stem.
    (ont_dir / "_master.ttl").write_text(
        '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
        '<https://example.org/master> a owl:Ontology ; owl:versionInfo "1.0" .\n',
        encoding="utf-8",
    )
    (hub_root / "model" / "shapes").mkdir(parents=True, exist_ok=True)
    return hub_root


def test_show_class_inventory_all_iterates_all_domains(tmp_path, monkeypatch):
    """--all iterates every domain ontology and produces a combined summary."""
    hub = tmp_path / "ontology-hub"
    _make_all_hub(hub)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["show-class-inventory", "--all"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    domain_names = [d["domain"] for d in payload["domains"]]
    assert domain_names == ["financial", "party"]

    fin = next(d for d in payload["domains"] if d["domain"] == "financial")
    assert fin["class_count"] == 2
    account = next(c for c in fin["classes"] if c["class_uri"] == "https://example.org/financial#Account")
    assert account["label"] == "Account"
    assert account["datatype_property_count"] == 1
    assert account["object_property_count"] == 1
    assert account["shacl_shape_status"] == "absent"

    party = next(d for d in payload["domains"] if d["domain"] == "party")
    person = party["classes"][0]
    assert person["class_uri"] == "https://example.org/party#Person"
    assert person["datatype_property_count"] == 1
    assert person["object_property_count"] == 0


def test_show_class_inventory_all_zero_datatype_count(tmp_path, monkeypatch):
    """Classes with zero datatype properties show datatype_property_count: 0."""
    hub = tmp_path / "ontology-hub"
    ont_dir = hub / "model" / "ontologies"
    ont_dir.mkdir(parents=True)
    (ont_dir / "relations.ttl").write_text(ONTOLOGY_NO_DATATYPE_PROPERTIES, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["show-class-inventory", "--all"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload["domains"]) == 1
    domain = payload["domains"][0]
    assert domain["domain"] == "relations"
    cls = domain["classes"][0]
    assert cls["class_uri"] == "https://example.org/relations#Node"
    assert cls["datatype_property_count"] == 0
    assert cls["object_property_count"] == 1


def test_show_class_inventory_all_without_hub_raises(tmp_path, monkeypatch):
    """--all outside of a hub directory raises an error."""
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["show-class-inventory", "--all"],
    )

    assert result.exit_code != 0
    assert "Cannot locate a hub" in result.output


def test_show_class_inventory_all_with_max_classes(tmp_path, monkeypatch):
    """--all with --max-classes limits each domain to the given count."""
    hub = tmp_path / "ontology-hub"
    _make_all_hub(hub)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["show-class-inventory", "--all", "--max-classes", "1"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    for domain in payload["domains"]:
        assert domain["class_count"] == 1


def test_show_class_inventory_all_shacl_present(tmp_path, monkeypatch):
    """--all reports shacl_shape_status 'present' when a SHACL file exists."""
    hub = tmp_path / "ontology-hub"
    _make_all_hub(hub)
    # Create a SHACL shape file for the financial domain.
    (hub / "model" / "shapes" / "financial.shacl.ttl").write_text(
        '@prefix sh: <http://www.w3.org/ns/shacl#> .\n', encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["show-class-inventory", "--all"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    fin = next(d for d in payload["domains"] if d["domain"] == "financial")
    account = next(c for c in fin["classes"] if c["class_uri"] == "https://example.org/financial#Account")
    assert account["shacl_shape_status"] == "present"
    party = next(d for d in payload["domains"] if d["domain"] == "party")
    person = party["classes"][0]
    assert person["shacl_shape_status"] == "absent"

