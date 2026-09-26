# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The ontology-side guards of DD-248 §5.

``validate`` warns about a local property that resembles a closure property and errors
on a property declared under a namespace the hub does not author; ``scaffold-extensions``
refuses to mint into a foreign namespace and skips a property the class already has.
"""

from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.closure_lookup import terms_from_ref_classes
from kairos_ontology.core.extension_stubs import build_extension_stubs, closure_candidates_for
from kairos_ontology.core.ontology_integrity import (
    ALL_CODES,
    BLOCKING_CODES,
    DEGRADABLE_CODES,
    NON_DEGRADABLE_CODES,
    audit_ontology_integrity,
    check_property_namespace,
    check_property_resemblance,
    scan_hub_ontologies,
)

REF = "https://www.kairosflow.ai/ont/bsp/documents"
ACME = "https://acme.com/ont"

_PREFIXES = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <{ns}#> .

<{ns}> a owl:Ontology ; rdfs:label "x"@en ; owl:versionInfo "1.0.0" .
:Document a owl:Class ; rdfs:label "Document"@en ; rdfs:comment "A document."@en .
"""


def _write(directory: Path, domain: str, body: str, ns: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{domain}.ttl"
    path.write_text(_PREFIXES.format(ns=ns or f"{ACME}/{domain}") + body, encoding="utf-8")
    return path


def _prop(name: str, *, label: str = "", extra: str = "") -> str:
    lbl = f'    rdfs:label "{label}"@en ;\n' if label else ""
    return (
        f"\n:{name} a owl:DatatypeProperty ;\n{lbl}    rdfs:domain :Document ;\n"
        f"    rdfs:range xsd:string {extra}.\n"
    )


def _closure(*names: str):
    return terms_from_ref_classes(
        [
            {
                "uri": f"{REF}#Document",
                "name": "Document",
                "properties": [
                    {"uri": f"{REF}#{n}", "name": n, "label": "", "type": "datatype"}
                    for n in names
                ],
            }
        ]
    )


class TestResemblance:
    def test_a_near_duplicate_is_warned_with_the_candidate_and_the_command(self, tmp_path):
        _write(tmp_path, "documents", _prop("documentTypeCode") + _prop("unrelatedFlag"))
        ontologies = scan_hub_ontologies(tmp_path)

        [diag] = check_property_resemblance(
            ontologies, {"documents": _closure("documentType", "issuedOn")}
        )

        assert diag.level == "warning"
        assert diag.code == "integrity.local-property-resembles-reference-property"
        assert f"<{REF}#documentType> (near" in diag.message
        assert "find-term documentTypeCode --domain documents" in diag.remediation
        assert diag.term_uri == f"{ACME}/documents#documentTypeCode"

    def test_a_link_silences_it_and_an_exact_name_is_left_to_the_shadow_check(self, tmp_path):
        _write(
            tmp_path,
            "documents",
            _prop("documentTypeCode", extra=f"; rdfs:subPropertyOf <{REF}#documentType> ")
            + _prop("issuedOn", extra=f"; owl:equivalentProperty <{REF}#issuedOn> ")
            + _prop("documentType"),
        )
        ontologies = scan_hub_ontologies(tmp_path)

        assert check_property_resemblance(
            ontologies, {"documents": _closure("documentType", "issuedOn")}
        ) == []

    def test_a_label_can_be_the_resemblance_and_generic_names_are_silent(self, tmp_path):
        _write(tmp_path, "documents", _prop("docKind", label="Document type") + _prop("code"))
        ontologies = scan_hub_ontologies(tmp_path)

        [diag] = check_property_resemblance(
            ontologies, {"documents": _closure("documentType", "typeCode")}
        )
        assert diag.term_uri.endswith("#docKind") and "(exact" in diag.message

    def test_no_closure_no_warnings(self, tmp_path):
        _write(tmp_path, "documents", _prop("documentTypeCode"))
        assert check_property_resemblance(scan_hub_ontologies(tmp_path), {}) == []


class TestNamespace:
    def _hub(self, tmp_path):
        ontologies = tmp_path / "model" / "ontologies"
        _write(
            ontologies,
            "documents",
            _prop("localOne")
            + f"\n<{REF}#ghost> a owl:DatatypeProperty ; rdfs:domain :Document ; "
            "rdfs:range xsd:string .\n"
            f"<{ACME}/party#misplaced> a owl:ObjectProperty ; rdfs:domain :Document .\n"
            f"<https://elsewhere.example/ont#stray> a owl:AnnotationProperty .\n",
        )
        _write(ontologies, "party", "")
        _write(ontologies, "documents-silver-ext", f"\n<{REF}#ignored> a owl:DatatypeProperty .\n")
        return tmp_path

    def test_a_reference_namespace_errors_a_sibling_warns_and_an_unknown_one_is_left(
        self, tmp_path
    ):
        hub = self._hub(tmp_path)
        ontologies = scan_hub_ontologies(hub / "model" / "ontologies")
        module_terms = {REF: {"classes": set(), "properties": {"ghost"}}}

        diagnostics = check_property_namespace(
            ontologies, frozenset({f"{ACME}/documents", f"{ACME}/party"}), module_terms
        )

        by_term = {d.term_uri: d for d in diagnostics}
        # The `elsewhere.example` declaration is neither a reference module nor a hub
        # namespace: a prefix that is the parent path of the ontology IRI is an older
        # valid convention, so an unclassifiable namespace is not a finding.
        assert set(by_term) == {f"{REF}#ghost", f"{ACME}/party#misplaced"}
        ghost = by_term[f"{REF}#ghost"]
        assert ghost.level == "error" and f"reference module <{REF}>" in ghost.message
        assert "rename it ':ghost'" in ghost.remediation
        misplaced = by_term[f"{ACME}/party#misplaced"]
        assert misplaced.level == "warning" and "sibling hub namespace" in misplaced.message
        assert all(d.code == "integrity.property-outside-hub-namespace" for d in diagnostics)

    def test_the_audit_wires_it_and_the_code_is_degradable(self, tmp_path, monkeypatch):
        hub = self._hub(tmp_path)
        # The audit resolves reference modules from the catalog; stand the one in.
        monkeypatch.setattr(
            "kairos_ontology.core.ontology_integrity._module_terms",
            lambda _catalog: {REF: {"classes": set(), "properties": {"ghost"}}},
        )

        report = audit_ontology_integrity(ontologies_dir=hub / "model" / "ontologies")

        codes = {(d.code, d.level) for d in report.diagnostics}
        assert ("integrity.property-outside-hub-namespace", "error") in codes
        assert ("integrity.property-outside-hub-namespace", "warning") in codes
        assert "integrity.property-outside-hub-namespace" in DEGRADABLE_CODES
        assert "integrity.property-outside-hub-namespace" not in NON_DEGRADABLE_CODES
        assert "integrity.property-outside-hub-namespace" in BLOCKING_CODES
        assert "integrity.local-property-resembles-reference-property" in ALL_CODES
        assert "integrity.local-property-resembles-reference-property" not in BLOCKING_CODES

    def test_a_clean_hub_reports_nothing(self, tmp_path):
        ontologies = tmp_path / "model" / "ontologies"
        _write(ontologies, "documents", _prop("localOne"))
        report = audit_ontology_integrity(ontologies_dir=ontologies)
        assert not [
            d for d in report.diagnostics if d.code == "integrity.property-outside-hub-namespace"
        ]


# ---------------------------------------------------------------------------
# scaffold-extensions
# ---------------------------------------------------------------------------

REF_TTL = f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <{REF}#> .

<{REF}> a owl:Ontology .
:Document a owl:Class .
:documentType a owl:DatatypeProperty ; rdfs:domain :Document ; rdfs:range xsd:string .
"""

DOMAIN_TTL = f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix : <{ACME}/documents#> .

<{ACME}/documents> a owl:Ontology ; owl:imports <{REF}> .
"""


def _extension_hub(tmp_path: Path, decisions: list[dict]) -> Path:
    ontologies = tmp_path / "model" / "ontologies"
    ontologies.mkdir(parents=True)
    (tmp_path / "refmodels").mkdir()
    (ontologies / "documents.ttl").write_text(DOMAIN_TTL, encoding="utf-8")
    (ontologies / "_master.ttl").write_text(
        f"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<{ACME}/master> a owl:Ontology ; "
        f"owl:imports <{ACME}/documents> .\n",
        encoding="utf-8",
    )
    (tmp_path / "refmodels" / "documents.ttl").write_text(REF_TTL, encoding="utf-8")
    (tmp_path / "catalog-v001.xml").write_text(
        '<?xml version="1.0"?>\n<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        f'  <uri name="{ACME}/documents" uri="model/ontologies/documents.ttl"/>\n'
        f'  <uri name="{REF}" uri="refmodels/documents.ttl"/>\n</catalog>\n',
        encoding="utf-8",
    )
    analysis = tmp_path / "integration" / "sources" / "_analysis"
    analysis.mkdir(parents=True)
    (analysis / "table-dispositions.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "tables": decisions}), encoding="utf-8"
    )
    (analysis / "hub.table-anchors.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "tables": [
                    {"system": "src", "table": "docs", "domain": "documents",
                     "anchor": "Document", "anchor_uri": f"{REF}#Document"}
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _decision(column: str, name: str) -> dict:
    return {
        "system": "src", "table": "docs", "column": column,
        "disposition": "registered-extension", "rationale": "real", "decided_by": "user",
        "proposed_property": {"name": name, "range": "xsd:string", "on_class": "Document",
                              "why": "..."},
    }


class TestScaffoldExtensionsGuard:
    def test_a_property_the_class_already_has_is_skipped_unless_forced(self, tmp_path):
        hub = _extension_hub(
            tmp_path, [_decision("DOC_TYPE_CODE", "documentTypeCode"), _decision("X", "wharfCode")]
        )
        ns = f"{ACME}/documents#"

        text, report = build_extension_stubs(hub, domain="documents", namespace=ns)

        assert [p.name for p in report.properties] == ["wharfCode"]
        [item] = report.closure_candidates
        assert item["property"] == "documentTypeCode"
        assert item["candidates"][0]["uri"] == f"{REF}#documentType"
        assert any("closure-candidate" in s["reason"] for s in report.skipped)
        assert ":documentTypeCode" not in text and ":wharfCode" in text

        forced, _ = build_extension_stubs(hub, domain="documents", namespace=ns, force=True)
        assert ":documentTypeCode" in forced

    def test_an_unloadable_closure_is_advisory(self, tmp_path):
        from kairos_ontology.core.extension_stubs import ExtensionProperty

        prop = ExtensionProperty("documentTypeCode", "xsd:string", f"{REF}#Document", "", ())
        assert closure_candidates_for(tmp_path, "documents", [prop]) == {}

    def test_the_command_refuses_a_foreign_or_missing_namespace(self, tmp_path, monkeypatch):
        hub = _extension_hub(tmp_path, [])
        monkeypatch.chdir(hub)
        runner = CliRunner()

        ok = runner.invoke(cli, ["scaffold-extensions", "--domain", "documents", "--dry-run"])
        assert ok.exit_code == 0, ok.output

        foreign = runner.invoke(
            cli, ["scaffold-extensions", "--domain", "documents", "--namespace", f"{REF}#"]
        )
        assert foreign.exit_code == 1
        assert f"reference module <{REF}>" in foreign.output

        unknown = runner.invoke(
            cli, ["scaffold-extensions", "--domain", "documents", "--namespace",
                  "https://example.com/ont/documents#"]
        )
        assert unknown.exit_code == 1 and "not a namespace this hub authors" in unknown.output

        missing = runner.invoke(cli, ["scaffold-extensions", "--domain", "nowhere"])
        assert missing.exit_code == 1 and "scaffold-domain" in missing.output
