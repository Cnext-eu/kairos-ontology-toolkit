# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Staged business evidence nothing consumed (DD-234).

Source schemas the pipeline can re-read at will. The client's own documents and their
Power BI models are the two inputs only a human can supply, and a hub modelled without
them is modelled from column names. The failure this guards against is not an error
message — it is silence that reads identically whether the client sent nothing or sent
thirty documents to a directory no command looks in.
"""

from kairos_ontology.core.import_evidence import (
    audit_import_evidence,
    find_misplaced_documents,
    find_powerbi_exports,
)


def _hub(tmp_path):
    """A repo with an ontology-hub/ and an empty .import/."""
    (tmp_path / ".import").mkdir()
    hub = tmp_path / "ontology-hub"
    (hub / "businessdiscovery" / "_extractions").mkdir(parents=True)
    (hub / "integration" / "discovery" / "bi").mkdir(parents=True)
    return hub


def _semantic_model(root, name):
    folder = root / f"{name}.SemanticModel"
    (folder / "definition").mkdir(parents=True)
    (folder / "definition" / "model.tmdl").write_text("model Model\n", encoding="utf-8")
    return folder


class TestPowerBiExportDiscovery:
    def test_a_definition_folder_is_found(self, tmp_path):
        _semantic_model(tmp_path, "Sales")

        assert [p.name for p in find_powerbi_exports(tmp_path)] == ["definition"]

    def test_a_flat_export_is_found(self, tmp_path):
        flat = tmp_path / "Flat"
        flat.mkdir()
        (flat / "model.tmdl").write_text("model Model\n", encoding="utf-8")

        assert find_powerbi_exports(tmp_path) == [flat]

    def test_a_loose_pointer_does_not_mask_its_siblings(self, tmp_path):
        """The bug this guards: one stray .pbip hid three real exports beneath it."""
        staging = tmp_path / "staging"
        staging.mkdir()
        (staging / "Orphan.pbip").write_text("{}", encoding="utf-8")
        for name in ("A", "B"):
            folder = staging / name
            folder.mkdir()
            (folder / "model.tmdl").write_text("model Model\n", encoding="utf-8")

        found = {p.name for p in find_powerbi_exports(tmp_path)}

        assert found == {"A", "B", "Orphan.pbip"}

    def test_a_pointer_beside_the_model_it_names_is_not_double_reported(self, tmp_path):
        _semantic_model(tmp_path, "Sales")
        (tmp_path / "Sales.pbip").write_text("{}", encoding="utf-8")

        assert [p.name for p in find_powerbi_exports(tmp_path)] == ["definition"]

    def test_hidden_directories_are_skipped(self, tmp_path):
        hidden = tmp_path / ".trash" / "Old"
        hidden.mkdir(parents=True)
        (hidden / "model.tmdl").write_text("model Model\n", encoding="utf-8")

        assert find_powerbi_exports(tmp_path) == []


class TestMisplacedDocuments:
    def test_a_document_outside_every_known_directory_is_reported(self, tmp_path):
        stray = tmp_path / "Input" / "Ports"
        stray.mkdir(parents=True)
        (stray / "definitions.docx").write_text("x", encoding="utf-8")

        assert [p.name for p in find_misplaced_documents(tmp_path)] == ["definitions.docx"]

    def test_documents_in_the_right_place_are_not_reported(self, tmp_path):
        good = tmp_path / "businessdiscovery" / "sub"
        good.mkdir(parents=True)
        (good / "definitions.docx").write_text("x", encoding="utf-8")

        assert find_misplaced_documents(tmp_path) == []

    def test_readmes_and_unrelated_files_are_not_reported(self, tmp_path):
        (tmp_path / "README.md").write_text("x", encoding="utf-8")
        (tmp_path / "scratch.txt").write_text("x", encoding="utf-8")
        (tmp_path / "data.csv").write_text("x", encoding="utf-8")

        assert find_misplaced_documents(tmp_path) == []


class TestAuditImportEvidence:
    def test_a_clean_hub_reports_nothing(self, tmp_path):
        _hub(tmp_path)

        report = audit_import_evidence(tmp_path, tmp_path / "ontology-hub")

        assert report.findings == []

    def test_a_missing_import_directory_is_not_a_finding(self, tmp_path):
        hub = tmp_path / "ontology-hub"
        hub.mkdir()

        report = audit_import_evidence(tmp_path, hub)

        assert report.findings == []
        assert report.notices

    def test_an_unimported_export_is_a_finding(self, tmp_path):
        hub = _hub(tmp_path)
        pbi = tmp_path / ".import" / "powerbi"
        pbi.mkdir()
        flat = pbi / "Volume"
        flat.mkdir()
        (flat / "model.tmdl").write_text("model Model\n", encoding="utf-8")

        report = audit_import_evidence(tmp_path, hub)

        assert [f.kind for f in report.findings] == ["unimported"]
        assert report.powerbi_total == 1
        assert report.powerbi_imported == 0
        assert "import-tmdl" in report.findings[0].remediation

    def test_an_imported_export_is_not_a_finding(self, tmp_path):
        hub = _hub(tmp_path)
        pbi = tmp_path / ".import" / "powerbi"
        pbi.mkdir()
        flat = pbi / "Volume"
        flat.mkdir()
        (flat / "model.tmdl").write_text("model Model\n", encoding="utf-8")
        (hub / "integration" / "discovery" / "bi" / "Volume-engineering-pack.md").write_text(
            "# Volume", encoding="utf-8"
        )

        report = audit_import_evidence(tmp_path, hub)

        assert report.findings == []
        assert report.powerbi_imported == 1

    def test_a_misplaced_document_is_a_finding_with_a_move_remediation(self, tmp_path):
        hub = _hub(tmp_path)
        stray = tmp_path / ".import" / "Input"
        stray.mkdir()
        (stray / "domain-definitions.pdf").write_text("x", encoding="utf-8")

        report = audit_import_evidence(tmp_path, hub)

        assert [f.kind for f in report.findings] == ["misplaced"]
        assert "businessdiscovery" in report.findings[0].remediation

    def test_an_unextracted_document_is_a_finding(self, tmp_path):
        hub = _hub(tmp_path)
        bd = tmp_path / ".import" / "businessdiscovery"
        bd.mkdir()
        (bd / "workshop.pdf").write_text("x", encoding="utf-8")

        report = audit_import_evidence(tmp_path, hub)

        assert [f.kind for f in report.findings] == ["unextracted"]
        assert report.documents_total == 1
        assert report.documents_extracted == 0
