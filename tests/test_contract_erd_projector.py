# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Declared Silver contract diagram (DD-216 / issue #698)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from kairos_ontology.core.compiler.contracts import load_silver_contract
from kairos_ontology.core.compiler.result import CompileError
from kairos_ontology.core.projections.contract_erd_projector import (
    generate_contract_erd_artifacts,
    render_contract_erd,
)
from kairos_ontology.core.projector import (
    projection_target_choices,
    projection_targets_for_all,
    run_projections,
)

CONTRACT = textwrap.dedent("""
    apiVersion: kairos.eu/v5
    kind: SilverContract
    metadata:
      domain: party
    entities:
      - class: party:Customer
        modelName: customer
        stability: preview
        closed: true
        grain:
          columns: [customer_id]
        identity:
          strategy: source-natural
          businessKey: [customer_id]
        properties:
          - property: party:customerId
            type: string(64)
            requirement: required
            nullable: false
          - property: party:displayName
            type: string(256)
            requirement: optional
            nullable: true
          - property: party:legacyRating
            type: string(16)
            requirement: optional
            nullable: true
            lifecycle:
              deprecated:
                since: "3.2.0"
                removeIn: "4.0.0"
                replacedBy: party:creditRating
          - property: party:creditRating
            type: string(16)
            requirement: optional
            nullable: true
        technicalColumns:
          - name: source_batch_id
            type: string(64)
            requirement: optional
            nullable: true
        relationships:
          - property: party:hasAccount
            target: party:Account
          - property: party:representsLegalEntity
            target: finance:LegalEntity
      - class: party:Account
        modelName: account
        stability: preview
        closed: false
        grain:
          columns: [account_id]
        identity:
          strategy: source-natural
        properties:
          - property: party:accountId
            type: string(32)
            requirement: required
            nullable: false
""").strip()


@pytest.fixture
def contracts_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "contracts"
    directory.mkdir()
    (directory / "party.contract.yaml").write_text(CONTRACT, encoding="utf-8")
    return directory


def _content(contracts_dir: Path) -> str:
    return generate_contract_erd_artifacts(contracts_dir, "party")["party-contract-erd.mmd"]


class TestContractErd:
    def test_renders_an_er_diagram_per_declared_entity(self, contracts_dir):
        content = _content(contracts_dir)
        assert content.startswith("%% Declared Silver contract ERD: party")
        assert "erDiagram" in content
        assert "    CUSTOMER {" in content
        assert "    ACCOUNT {" in content

    def test_declares_canonical_types_not_adapter_physical_ones(self, contracts_dir):
        """The point of the diagram: the promise, not what Silver emits today."""
        content = _content(contracts_dir)
        assert "string_64 customer_id" in content
        assert "VARCHAR" not in content.upper().replace("VARCHAR_", "")

    def test_shows_what_the_emitted_erd_cannot(self, contracts_dir):
        """`requirement`, nullability, stability, closed, and per-column deprecation.

        These exist only in the contract, and are the whole reason this beats reading
        the YAML (#698).
        """
        content = _content(contracts_dir)
        assert '"required, not null"' in content
        assert '"optional"' in content
        assert "stability=preview, closed" in content
        assert "stability=preview, open" in content
        assert "deprecated since 3.2.0, removed in 4.0.0, replaced by creditRating" in content

    def test_marks_a_cross_domain_target_as_external(self, contracts_dir):
        """Cross-domain reach is exactly what the emitted ERD hides behind a `_sk`."""
        content = _content(contracts_dir)
        assert 'LEGALENTITY ||--o{ CUSTOMER : "representsLegalEntity [external]"' in content
        assert 'ACCOUNT ||--o{ CUSTOMER : "hasAccount"' in content

    def test_a_technical_column_is_labelled(self, contracts_dir):
        assert '"technical, optional"' in _content(contracts_dir)

    def test_the_grain_column_is_the_primary_key(self, contracts_dir):
        assert "string_64 customer_id PK" in _content(contracts_dir)

    def test_an_ungoverned_domain_emits_nothing(self, contracts_dir):
        """Adopting a contract is opt-in (DD-213 §6), so a hub without one must not
        start emitting an empty diagram for every domain."""
        assert generate_contract_erd_artifacts(contracts_dir, "logistics") == {}

    def test_a_missing_contracts_directory_emits_nothing(self):
        assert generate_contract_erd_artifacts(None, "party") == {}

    def test_a_malformed_contract_is_reported_not_skipped(self, contracts_dir):
        """`run_projections` catches per domain and prints the failure, so raising here
        surfaces the problem instead of silently producing no diagram."""
        (contracts_dir / "party.contract.yaml").write_text(
            CONTRACT.replace(
                "stability: preview\n    closed: false", "stability: stable\n    closed: false"
            ),
            encoding="utf-8",
        )
        with pytest.raises(CompileError):
            generate_contract_erd_artifacts(contracts_dir, "party")

    def test_no_comment_line_is_ever_bare(self, contracts_dir):
        """A `%%` with no text after it fails the erDiagram parser outright, and the
        error points at the wrong line because it is reported post-comment-stripping
        (#698, reproduced against mermaid-cli 11.12.0)."""
        for line in _content(contracts_dir).splitlines():
            assert line.strip() != "%%"

    def test_output_is_deterministic(self, contracts_dir):
        contract = load_silver_contract(CONTRACT)
        assert render_contract_erd(contract) == render_contract_erd(contract)

    def test_output_carries_no_carriage_return(self, contracts_dir):
        assert "\r" not in _content(contracts_dir)


class TestTargetRegistration:
    def test_contract_erd_is_a_registered_target(self):
        assert "contract-erd" in projection_target_choices()
        assert "contract-erd" in projection_targets_for_all()

    def test_target_writes_into_its_own_architecture_directory(self, tmp_path):
        hub = tmp_path / "ontology-hub"
        ontologies = hub / "model" / "ontologies"
        ontologies.mkdir(parents=True)
        (ontologies / "party.ttl").write_text(
            textwrap.dedent("""
                @prefix party: <https://example.test/party#> .
                @prefix owl: <http://www.w3.org/2002/07/owl#> .
                <https://example.test/party> a owl:Ontology .
                party:Customer a owl:Class .
                """).strip(),
            encoding="utf-8",
        )
        contracts = hub / "model" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "party.contract.yaml").write_text(CONTRACT, encoding="utf-8")

        output = tmp_path / "out"
        run_projections(
            ontologies_path=ontologies,
            catalog_path=None,
            output_path=output,
            target="contract-erd",
        )

        written = output / "architecture" / "contract-erd" / "party-contract-erd.mmd"
        assert written.is_file()
        assert "erDiagram" in written.read_text(encoding="utf-8")
        assert b"\r" not in written.read_bytes()
