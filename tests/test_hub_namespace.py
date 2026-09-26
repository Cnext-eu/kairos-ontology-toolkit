# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The one reader of the hub's ontology IRIs (DD-248 §5)."""

from pathlib import Path

from kairos_ontology.core.hub_namespace import (
    domain_namespace,
    hub_ontology_iris,
    hub_ontology_namespaces,
    is_hub_namespace,
    namespace_of,
    reset_hub_namespace_cache,
)

_ONT = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<{iri}> a owl:Ontology .
"""


def _hub(tmp_path: Path, **files: str) -> Path:
    ontologies = tmp_path / "model" / "ontologies"
    ontologies.mkdir(parents=True, exist_ok=True)
    for stem, iri in files.items():
        (ontologies / f"{stem}.ttl").write_text(_ONT.format(iri=iri), encoding="utf-8")
    return tmp_path


def test_every_authored_ontology_is_read_including_the_managed_ones(tmp_path):
    hub = _hub(
        tmp_path,
        _master="https://acme.com/ont/master",
        party="https://acme.com/ont/party",
        booking="https://acme.com/ont/booking#",
    )
    (tmp_path / "refmodels").mkdir()
    (tmp_path / "refmodels" / "base.ttl").write_text(
        _ONT.format(iri="urn:reference"), encoding="utf-8"
    )

    assert hub_ontology_iris(hub) == {
        "_master": "https://acme.com/ont/master",
        "party": "https://acme.com/ont/party",
        "booking": "https://acme.com/ont/booking",
    }
    assert hub_ontology_namespaces(hub) == frozenset(
        {"https://acme.com/ont/master", "https://acme.com/ont/party", "https://acme.com/ont/booking"}
    )
    assert domain_namespace(hub, "party") == "https://acme.com/ont/party#"
    assert domain_namespace(hub, "missing") is None


def test_is_hub_namespace_and_namespace_of():
    spaces = frozenset({"https://acme.com/ont/party"})
    assert is_hub_namespace("https://acme.com/ont/party#legalName", spaces)
    assert is_hub_namespace("https://acme.com/ont/party/legalName", spaces)
    assert not is_hub_namespace("https://www.kairosflow.ai/ont/bsp/party#legalName", spaces)
    assert namespace_of("urn:base#email") == "urn:base#"


def test_a_file_without_an_ontology_or_that_does_not_parse_is_skipped(tmp_path):
    hub = _hub(tmp_path, party="https://acme.com/ont/party")
    ontologies = tmp_path / "model" / "ontologies"
    (ontologies / "notes.ttl").write_text("# nothing declared\n", encoding="utf-8")
    (ontologies / "broken.ttl").write_text("this is not turtle {", encoding="utf-8")

    assert hub_ontology_iris(hub) == {"party": "https://acme.com/ont/party"}


def test_no_ontologies_directory_yields_nothing(tmp_path):
    assert hub_ontology_iris(tmp_path) == {}
    assert domain_namespace(tmp_path, "party") is None


def test_the_memo_follows_the_files_content(tmp_path):
    reset_hub_namespace_cache()
    hub = _hub(tmp_path, party="https://acme.com/ont/party")
    assert domain_namespace(hub, "party") == "https://acme.com/ont/party#"
    _hub(tmp_path, party="https://renamed.example/ont/party")
    assert domain_namespace(hub, "party") == "https://renamed.example/ont/party#"
