# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Declared Silver contract schema, loader, scaffold, and scope resolution (DD-213)."""

from __future__ import annotations

import textwrap

import pytest
import yaml

from kairos_ontology.core.compiler.contract_scaffold import (
    build_contract_document,
    render_contract_yaml,
)
from kairos_ontology.core.compiler.contracts import (
    load_silver_contract,
    resolved_column_name,
)
from kairos_ontology.core.compiler.kernel import build_compile_plan, resolve_scope
from kairos_ontology.core.compiler.result import CompileError

from _contract_second_source import add_second_source as _add_second_source

GOOD_CONTRACT = textwrap.dedent("""
    apiVersion: kairos.eu/v5
    kind: SilverContract
    metadata:
      domain: party
    entities:
      - class: party:Customer
        modelName: customer
        stability: stable
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
        technicalColumns:
          - name: source_batch_id
            type: string(64)
            requirement: optional
            nullable: true
""").strip()


def _codes(text: str) -> set[str]:
    with pytest.raises(CompileError) as excinfo:
        load_silver_contract(text, path="party.contract.yaml")
    return {item.code for item in excinfo.value.diagnostics}


def _document() -> dict:
    """Return the good contract as a mutable document.

    Variants are built by mutating this structure rather than by string surgery, so a
    reindent of the fixture cannot silently turn a rule test into a no-op.
    """
    return yaml.safe_load(GOOD_CONTRACT)


def _dump(document: dict) -> str:
    return yaml.safe_dump(document, sort_keys=False)


def _entity(document: dict) -> dict:
    return document["entities"][0]


class TestContractLoader:
    def test_parses_a_well_formed_contract(self):
        contract = load_silver_contract(GOOD_CONTRACT, path="party.contract.yaml")
        assert contract.domain == "party"
        entity = contract.entity_for("party:Customer")
        assert entity is not None
        assert entity.model_name == "customer"
        assert entity.closed is True
        assert [item.property for item in entity.required_properties] == ["party:customerId"]
        assert [item.property for item in entity.optional_properties] == ["party:displayName"]

    def test_column_name_defaults_to_the_kernel_rule(self):
        """An unpinned columnName must reproduce ``camel_to_snake`` exactly (DD-213 §6).

        If this drifts, adopting a scaffolded contract stops being a no-op.
        """
        entity = load_silver_contract(GOOD_CONTRACT).entity_for("party:Customer")
        assert [resolved_column_name(item) for item in entity.properties] == [
            "customer_id",
            "display_name",
        ]

    def test_pinned_column_name_wins(self):
        document = _document()
        _entity(document)["properties"][1]["columnName"] = "full_name"
        entity = load_silver_contract(_dump(document)).entity_for("party:Customer")
        assert resolved_column_name(entity.properties[1]) == "full_name"

    def test_unknown_field_is_rejected(self):
        document = _document()
        document["unexpected"] = True
        assert "contract.schema" in _codes(_dump(document))

    def test_duplicate_key_is_rejected(self):
        text = GOOD_CONTRACT.replace(
            "    stability: stable\n",
            "    stability: stable\n    stability: preview\n",
        )
        assert "contract.duplicate-key" in _codes(text)

    def test_unknown_canonical_type_is_rejected(self):
        document = _document()
        _entity(document)["properties"][0]["type"] = "varchar(64)"
        assert "contract.schema" in _codes(_dump(document))

    def test_document_must_be_a_mapping(self):
        assert "contract.not-a-mapping" in _codes("- not a mapping\n")


class TestContractLoadRules:
    def test_optional_property_must_be_nullable(self):
        """An unmapped optional property is padded with NULL, so it cannot be non-null."""
        document = _document()
        _entity(document)["properties"][1]["nullable"] = False
        assert "contract.optional-not-nullable" in _codes(_dump(document))

    def test_optional_technical_column_must_be_nullable(self):
        document = _document()
        _entity(document)["technicalColumns"][0]["nullable"] = False
        assert "contract.optional-not-nullable" in _codes(_dump(document))

    def test_open_contract_requires_preview_stability(self):
        document = _document()
        _entity(document)["closed"] = False
        assert "contract.closed-requires-preview" in _codes(_dump(document))

    def test_open_contract_is_allowed_while_preview(self):
        document = _document()
        _entity(document)["closed"] = False
        _entity(document)["stability"] = "preview"
        assert load_silver_contract(_dump(document)).entities[0].closed is False

    def test_grain_column_must_be_declared_required(self):
        document = _document()
        _entity(document)["grain"]["columns"] = ["display_name"]
        assert "contract.grain-not-required" in _codes(_dump(document))

    def test_grain_column_must_be_declared_at_all(self):
        document = _document()
        _entity(document)["grain"]["columns"] = ["nosuchcolumn"]
        assert "contract.grain-not-required" in _codes(_dump(document))

    def test_business_key_column_must_be_declared_required(self):
        document = _document()
        _entity(document)["identity"]["businessKey"] = ["display_name"]
        assert "contract.grain-not-required" in _codes(_dump(document))

    def test_column_name_collision_is_rejected(self):
        document = _document()
        _entity(document)["properties"][1]["columnName"] = "customer_id"
        assert "contract.column-name-collision" in _codes(_dump(document))

    def test_reserved_envelope_name_is_rejected(self):
        """The DD-104 audit envelope is compiler-owned and outside the closed scope."""
        document = _document()
        _entity(document)["technicalColumns"][0]["name"] = "_loaded_at"
        assert "contract.column-name-collision" in _codes(_dump(document))

    def test_reserved_surrogate_key_suffix_is_rejected(self):
        """``<model>_sk`` is the generated surrogate join key, not an authored column."""
        document = _document()
        _entity(document)["technicalColumns"][0]["name"] = "customer_sk"
        assert "contract.column-name-collision" in _codes(_dump(document))

    def test_duplicate_entity_is_rejected(self):
        document = _document()
        document["entities"].append(dict(_entity(document)))
        assert "contract.duplicate-entity" in _codes(_dump(document))

    def test_deprecation_window_must_span_two_versions(self):
        document = _document()
        _entity(document)["properties"][1]["lifecycle"] = {
            "deprecated": {"since": "3.2.0", "removeIn": "3.2.0"}
        }
        assert "contract.deprecated-shape" in _codes(_dump(document))

    def test_replaced_by_must_resolve_within_the_entity(self):
        document = _document()
        _entity(document)["properties"][1]["lifecycle"] = {
            "deprecated": {
                "since": "3.2.0",
                "removeIn": "4.0.0",
                "replacedBy": "party:nowhere",
            }
        }
        assert "contract.deprecated-shape" in _codes(_dump(document))

    def test_a_valid_deprecation_window_is_accepted(self):
        document = _document()
        _entity(document)["properties"][1]["lifecycle"] = {
            "deprecated": {
                "since": "3.2.0",
                "removeIn": "4.0.0",
                "replacedBy": "party:customerId",
            }
        }
        entity = load_silver_contract(_dump(document)).entity_for("party:Customer")
        assert entity.properties[1].deprecated.remove_in == "4.0.0"


def _write_hub(hub_root):
    """Minimal v5 hub, mirroring tests/test_silver_sample_audit.py::_write_v5_hub."""
    ontology_dir = hub_root / "model" / "ontologies"
    source_dir = hub_root / "integration" / "sources" / "crm"
    binding_dir = hub_root / "integration" / "bindings"
    ontology_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    binding_dir.mkdir(parents=True)
    (hub_root / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    (ontology_dir / "party.ttl").write_text(
        textwrap.dedent("""
            @prefix party: <https://example.test/party#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
            party:Customer a owl:Class ; rdfs:label "Customer" .
            party:customer_id a owl:DatatypeProperty ;
              rdfs:domain party:Customer ; rdfs:range xsd:string .
            party:customerName a owl:DatatypeProperty ;
              rdfs:domain party:Customer ; rdfs:range xsd:string .
            party:loyaltyTier a owl:DatatypeProperty ;
              rdfs:domain party:Customer ; rdfs:range xsd:string .
            """).strip(),
        encoding="utf-8",
    )
    (source_dir / "crm.vocabulary.ttl").write_text(
        textwrap.dedent("""
            @prefix src: <https://example.test/source#> .
            @prefix kb: <https://kairos.cnext.eu/bronze#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            src:crm a kb:SourceSystem ; rdfs:label "crm" ;
              kb:database "raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .
            src:customers a kb:SourceTable ; kb:sourceSystem src:crm ;
              kb:tableName "customers" ; kb:primaryKeyColumns "customer_id" .
            src:id a kb:SourceColumn ; kb:sourceTable src:customers ;
              kb:columnName "customer_id" ; kb:dataType "varchar(50)" ;
              kb:nullable "false"^^xsd:boolean .
            src:name a kb:SourceColumn ; kb:sourceTable src:customers ;
              kb:columnName "customer_name" ; kb:dataType "varchar(200)" ;
              kb:nullable "true"^^xsd:boolean .
            """).strip(),
        encoding="utf-8",
    )
    (binding_dir / "customer.binding.yaml").write_text(
        textwrap.dedent("""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: crm-customer
              domain: party
            source:
              relation: crm.customers
            target:
              class: party:Customer
            grain:
              columns: [customer_id]
            identity:
              strategy: source-natural
              sourceKey: [customer_id]
            load:
              mode: full-refresh
            fields:
              - property: party:customer_id
                expression: customer_id
              - property: party:customerName
                expression: customer_name
            """).strip(),
        encoding="utf-8",
    )
    return binding_dir


class TestContractScaffold:
    def test_scaffolds_a_loadable_contract_from_a_plan(self, tmp_path):
        _write_hub(tmp_path)
        plan = build_compile_plan(tmp_path, "party")
        document = build_contract_document(plan)
        contract = load_silver_contract(render_contract_yaml(document), path="generated")
        entity = contract.entity_for("party:Customer")
        assert entity is not None
        assert entity.stability == "preview"
        assert entity.closed is True
        assert [item.property for item in entity.properties] == [
            "party:customer_id",
            "party:customerName",
        ]

    def test_scaffolded_columns_match_the_emitted_model_exactly(self, tmp_path):
        """The contract must record what the compiler already emits -- name, order, type,
        nullability -- or adopting it would not be a no-op (DD-213 §6)."""
        _write_hub(tmp_path)
        plan = build_compile_plan(tmp_path, "party")
        model = next(
            item
            for item in plan.shaped_project.silver_models
            if item.identity.model_name == "customer"
        )
        document = build_contract_document(plan)
        entity = load_silver_contract(render_contract_yaml(document)).entity_for("party:Customer")

        # Only author-declared roles are contract-governed. Generated keys, the entity IRI,
        # and the DD-104 audit/source-identity envelope are compiler-owned and DO appear in
        # SilverModelSpec.columns -- they are simply outside the contract's scope.
        emitted = [
            column
            for column in model.columns
            if column.role in {"business", "business-natural-key"}
        ]
        assert [resolved_column_name(item) for item in entity.properties] == [
            column.name for column in emitted
        ]
        assert [item.nullable for item in entity.properties] == [
            bool(column.nullable) for column in emitted
        ]
        assert entity.model_name == model.identity.model_name

    def test_scaffold_omits_compiler_owned_columns(self, tmp_path):
        """The envelope and generated keys are emitted unconditionally, so a contract that
        declared them would be rejected by its own reserved-name rule."""
        _write_hub(tmp_path)
        plan = build_compile_plan(tmp_path, "party")
        entity = load_silver_contract(
            render_contract_yaml(build_contract_document(plan))
        ).entity_for("party:Customer")
        declared = {resolved_column_name(item) for item in entity.properties}
        declared |= {item.name for item in entity.technical_columns}
        assert not any(name.startswith("_") or name.endswith("_sk") for name in declared)

    def test_scaffold_records_grain_as_emitted_columns(self, tmp_path):
        _write_hub(tmp_path)
        plan = build_compile_plan(tmp_path, "party")
        entity = load_silver_contract(
            render_contract_yaml(build_contract_document(plan))
        ).entity_for("party:Customer")
        assert entity.grain == ("customer_id",)
        assert entity.identity.strategy == "source-natural"


class TestContractScope:
    def test_absent_contract_directory_leaves_scope_empty(self, tmp_path):
        _write_hub(tmp_path)
        scope, _ = resolve_scope(tmp_path, "party")
        assert scope.contract_paths == ()

    def test_domain_contract_joins_scope_and_provenance(self, tmp_path):
        _write_hub(tmp_path)
        before = resolve_scope(tmp_path, "party")[0].provenance_hash()
        contracts = tmp_path / "model" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "party.contract.yaml").write_text(GOOD_CONTRACT, encoding="utf-8")
        scope, _ = resolve_scope(tmp_path, "party")
        assert [p.replace("\\", "/").split("/")[-1] for p in scope.contract_paths] == [
            "party.contract.yaml"
        ]
        assert scope.provenance_hash() != before

    def test_unrelated_foreign_contract_stays_out_of_scope(self, tmp_path):
        """An unrelated domain's contract must not churn this domain's provenance hash."""
        _write_hub(tmp_path)
        contracts = tmp_path / "model" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "party.contract.yaml").write_text(GOOD_CONTRACT, encoding="utf-8")
        baseline = resolve_scope(tmp_path, "party")[0].provenance_hash()
        (contracts / "finance.contract.yaml").write_text(
            GOOD_CONTRACT.replace("domain: party", "domain: finance").replace(
                "party:Customer", "finance:Invoice"
            ),
            encoding="utf-8",
        )
        scope, _ = resolve_scope(tmp_path, "party")
        assert len(scope.contract_paths) == 1
        assert scope.provenance_hash() == baseline

    def test_foreign_contract_joins_scope_for_a_cross_domain_relationship(self, tmp_path):
        """A relationship FK column embeds the *parent's* model name, so the parent's
        contract is load-bearing for this domain's emitted columns (DD-213 §3)."""
        binding_dir = _write_hub(tmp_path)
        path = binding_dir / "customer.binding.yaml"
        path.write_text(
            path.read_text(encoding="utf-8")
            + textwrap.dedent("""
                relationships:
                  - property: party:hasInvoice
                    target: finance:Invoice
                    join:
                      - local: customer_id
                        foreign: customer_id
                    cardinality: many-to-one
                    mode: non-temporal
                    missingParent: error
                    ambiguousParent: error
                """),
            encoding="utf-8",
        )
        contracts = tmp_path / "model" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "finance.contract.yaml").write_text(
            GOOD_CONTRACT.replace("domain: party", "domain: finance").replace(
                "party:Customer", "finance:Invoice"
            ),
            encoding="utf-8",
        )
        scope, _ = resolve_scope(tmp_path, "party")
        assert [p.replace("\\", "/").split("/")[-1] for p in scope.contract_paths] == [
            "finance.contract.yaml"
        ]


def _adopt_contract(hub_root, mutate=None):
    """Scaffold a contract for the hub, optionally mutate it, and write it into place."""
    plan = build_compile_plan(hub_root, "party")
    document = build_contract_document(plan)
    if mutate is not None:
        mutate(document)
    contracts = hub_root / "model" / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    path = contracts / "party.contract.yaml"
    path.write_text(render_contract_yaml(document), encoding="utf-8")
    return path


def _diagnostics(hub_root):
    plan = build_compile_plan(hub_root, "party")
    return {item.code: item for item in plan.diagnostics.items}


class TestGateA:
    def test_ungoverned_domain_emits_no_contract_diagnostics(self, tmp_path):
        """DD-213 §6: an ungoverned domain compiles exactly as it did before -- which means
        no new advisory on every compile, or every downstream consumer has to learn to
        ignore it."""
        _write_hub(tmp_path)
        assert not [code for code in _diagnostics(tmp_path) if code.startswith("contract.")]

    def test_adopting_a_scaffolded_contract_is_clean(self, tmp_path):
        """The generated contract records what is, so it must conform to itself."""
        _write_hub(tmp_path)
        _adopt_contract(tmp_path)
        assert not [code for code in _diagnostics(tmp_path) if code.startswith("contract.")]

    def test_undeclared_class_is_reported(self, tmp_path):
        _write_hub(tmp_path)

        def rename(document):
            document["entities"][0]["class"] = "party:Somethingelse"

        _adopt_contract(tmp_path, rename)
        assert "contract.class-not-declared" in _diagnostics(tmp_path)

    def test_required_property_unmapped_is_reported(self, tmp_path):
        """Adding a required property to the contract must call out every binding that
        does not supply it -- this is the rule that makes the contract a contract."""
        _write_hub(tmp_path)

        def add_required(document):
            document["entities"][0]["properties"].append(
                {
                    "property": "party:loyaltyTier",
                    "columnName": "loyalty_tier",
                    "type": "string",
                    "requirement": "required",
                    "nullable": True,
                }
            )

        _adopt_contract(tmp_path, add_required)
        assert "contract.required-property-unmapped" in _diagnostics(tmp_path)

    def test_optional_property_must_be_declared_unmapped(self, tmp_path):
        _write_hub(tmp_path)

        def add_optional(document):
            document["entities"][0]["properties"].append(
                {
                    "property": "party:loyaltyTier",
                    "columnName": "loyalty_tier",
                    "type": "string",
                    "requirement": "optional",
                    "nullable": True,
                }
            )

        _adopt_contract(tmp_path, add_optional)
        assert "contract.optional-property-undeclared" in _diagnostics(tmp_path)

    def test_declaring_unmapped_silences_the_gap(self, tmp_path):
        """A partial source conforms by declaring its gap explicitly (DD-213 §4)."""
        binding_dir = _write_hub(tmp_path)

        def add_optional(document):
            document["entities"][0]["properties"].append(
                {
                    "property": "party:loyaltyTier",
                    "columnName": "loyalty_tier",
                    "type": "string",
                    "requirement": "optional",
                    "nullable": True,
                }
            )

        _adopt_contract(tmp_path, add_optional)
        path = binding_dir / "customer.binding.yaml"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nunmapped: [party:loyaltyTier]\n",
            encoding="utf-8",
        )
        codes = _diagnostics(tmp_path)
        assert "contract.optional-property-undeclared" not in codes
        assert "contract.unmapped-property-required" not in codes

    def test_unmapped_cannot_name_a_required_property(self, tmp_path):
        binding_dir = _write_hub(tmp_path)
        _adopt_contract(tmp_path)
        path = binding_dir / "customer.binding.yaml"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nunmapped: [party:customerName]\n",
            encoding="utf-8",
        )
        assert "contract.unmapped-property-required" in _diagnostics(tmp_path)

    def test_undeclared_property_is_reported_for_a_closed_entity(self, tmp_path):
        _write_hub(tmp_path)

        def drop_one(document):
            document["entities"][0]["properties"].pop()

        _adopt_contract(tmp_path, drop_one)
        assert "contract.property-not-declared" in _diagnostics(tmp_path)

    def test_type_mismatch_is_reported(self, tmp_path):
        """Canonical type is source-derived, so a contract type the source cannot produce
        must be reported rather than silently coerced (DD-213 §4)."""
        _write_hub(tmp_path)

        def retype(document):
            document["entities"][0]["properties"][0]["type"] = "int64"

        _adopt_contract(tmp_path, retype)
        assert "contract.type-mismatch" in _diagnostics(tmp_path)

    def test_nullability_mismatch_is_reported(self, tmp_path):
        _write_hub(tmp_path)

        def flip(document):
            for item in document["entities"][0]["properties"]:
                item["nullable"] = not item["nullable"]

        _adopt_contract(tmp_path, flip)
        assert "contract.nullability-mismatch" in _diagnostics(tmp_path)

    def test_identity_strategy_mismatch_is_reported(self, tmp_path):
        _write_hub(tmp_path)

        def flip(document):
            document["entities"][0]["identity"]["strategy"] = "surrogate"

        _adopt_contract(tmp_path, flip)
        assert "contract.identity-mismatch" in _diagnostics(tmp_path)

    def test_gate_a_findings_block(self, tmp_path):
        """Once the contract drives emission, a divergent binding must not emit a shape
        nobody declared."""
        _write_hub(tmp_path)

        def retype(document):
            document["entities"][0]["properties"][0]["type"] = "int64"

        _adopt_contract(tmp_path, retype)
        plan = build_compile_plan(tmp_path, "party")
        finding = next(
            item for item in plan.diagnostics.items if item.code == "contract.type-mismatch"
        )
        assert finding.severity.value == "error"

    def test_unresolved_contract_property_is_reported(self, tmp_path):
        """A contract may not declare a symbol a binding could never bind."""
        _write_hub(tmp_path)

        def add_unknown(document):
            document["entities"][0]["properties"].append(
                {
                    "property": "party:nosuchproperty",
                    "type": "string",
                    "requirement": "optional",
                    "nullable": True,
                }
            )

        _adopt_contract(tmp_path, add_unknown)
        assert "contract.property-unresolved" in _diagnostics(tmp_path)


def _model_columns(hub_root, model_name):
    plan = build_compile_plan(hub_root, "party")
    model = next(
        item
        for item in plan.shaped_project.silver_models
        if item.identity.model_name == model_name
    )
    return [column.name for column in model.columns]


def _authored_columns(hub_root, model_name):
    """Only the columns the contract governs, excluding compiler-owned ones."""
    plan = build_compile_plan(hub_root, "party")
    model = next(
        item
        for item in plan.shaped_project.silver_models
        if item.identity.model_name == model_name
    )
    return [
        column.name
        for column in model.columns
        if column.role in {"business", "business-natural-key"}
    ]


class TestContractDrivenEmission:
    def test_adoption_is_a_no_op(self, tmp_path):
        """Scaffold a contract, adopt it, and the emitted columns must not move.

        This is DD-213 §6's acceptance test: the generated contract records what is, so
        turning it on cannot change the emit.
        """
        _write_hub(tmp_path)
        before = _model_columns(tmp_path, "customer")
        _adopt_contract(tmp_path)
        assert _model_columns(tmp_path, "customer") == before

    def test_contract_order_drives_column_order(self, tmp_path):
        """Reordering a binding's fields: is fingerprint-neutral once governed -- the
        contract decides column order, not the authored YAML sequence."""
        binding_dir = _write_hub(tmp_path)
        _adopt_contract(tmp_path)
        governed = _model_columns(tmp_path, "customer")

        path = binding_dir / "customer.binding.yaml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        document["fields"].reverse()
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        assert _model_columns(tmp_path, "customer") == governed

    def test_pinned_column_name_survives_an_ontology_rename(self, tmp_path):
        """The point of pinning: a physical column keeps its name when the ontology
        property behind it is renamed."""
        _write_hub(tmp_path)

        def pin(document):
            document["entities"][0]["properties"][1]["columnName"] = "customer_name"

        _adopt_contract(tmp_path, pin)
        assert "customer_name" in _model_columns(tmp_path, "customer")

    def test_optional_gap_is_padded_as_a_column(self, tmp_path):
        """A source that cannot supply an optional property still emits its column, so the
        Silver shape does not depend on which sources happen to exist."""
        binding_dir = _write_hub(tmp_path)

        def add_optional(document):
            document["entities"][0]["properties"].append(
                {
                    "property": "party:loyaltyTier",
                    "columnName": "loyalty_tier",
                    "type": "string",
                    "requirement": "optional",
                    "nullable": True,
                }
            )

        _adopt_contract(tmp_path, add_optional)
        path = binding_dir / "customer.binding.yaml"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nunmapped: [party:loyaltyTier]\n",
            encoding="utf-8",
        )
        assert "loyalty_tier" in _model_columns(tmp_path, "customer")

    def test_padded_column_is_excluded_from_change_detection(self, tmp_path):
        """A padded NULL must never join the SCD2 canonical hash: the day the source starts
        supplying it, every row's hash would change at once."""
        binding_dir = _write_hub(tmp_path)

        def add_optional(document):
            document["entities"][0]["properties"].append(
                {
                    "property": "party:loyaltyTier",
                    "columnName": "loyalty_tier",
                    "type": "string",
                    "requirement": "optional",
                    "nullable": True,
                }
            )

        _adopt_contract(tmp_path, add_optional)
        path = binding_dir / "customer.binding.yaml"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nunmapped: [party:loyaltyTier]\n",
            encoding="utf-8",
        )
        plan = build_compile_plan(tmp_path, "party")
        model = next(
            item
            for item in plan.shaped_project.silver_models
            if item.identity.model_name == "customer"
        )
        padded = next(item for item in model.columns if item.name == "loyalty_tier")
        supplied = next(item for item in model.columns if item.name == "customer_name")
        assert padded.include_in_change_detection is False
        assert supplied.include_in_change_detection is True

    def test_required_property_is_never_padded(self, tmp_path):
        """Padding a required property would hide the very violation Gate A exists to
        surface, so it must block instead."""
        _write_hub(tmp_path)

        def add_required(document):
            document["entities"][0]["properties"].append(
                {
                    "property": "party:loyaltyTier",
                    "columnName": "loyalty_tier",
                    "type": "string",
                    "requirement": "required",
                    "nullable": True,
                }
            )

        _adopt_contract(tmp_path, add_required)
        codes = _diagnostics(tmp_path)
        assert "contract.required-property-unmapped" in codes
        assert codes["contract.required-property-unmapped"].severity.value == "error"


class TestConformanceRelaxation:
    def test_a_partial_second_source_is_rejected_without_a_contract(self, tmp_path):
        """The status quo this proposal exists to change: onboarding a source that cannot
        supply every property forces an edit to the incumbent binding."""
        binding_dir = _write_hub(tmp_path)
        _add_second_source(tmp_path, binding_dir, partial=True)
        assert "conformance.property-incompatible" in _diagnostics(tmp_path)

    def test_gaining_a_second_source_widens_the_column_type(self, tmp_path):
        """A pre-existing toolkit defect, surfaced by Gate A on first contact.

        The conformance UNION drops the string length its branches keep -- ``string(50)``
        becomes unsized ``string`` -- so a class's published column type silently widens the
        moment it gains a second source, with no ontology or binding change. This is exactly
        the class of instability DD-213 exists to catch, and the check is deliberately left
        strict rather than relaxed to accommodate it: the widening is real and a consumer
        would feel it.

        Tracked as issue #681. This test asserts the CURRENT behaviour, so it will fail once
        the union preserves its branches' length -- at which point flip it to assert the
        types agree rather than deleting it.
        """
        binding_dir = _write_hub(tmp_path)
        _adopt_contract(tmp_path)
        _add_second_source(tmp_path, binding_dir, partial=False)
        finding = _diagnostics(tmp_path).get("contract.type-mismatch")
        assert finding is not None
        assert "string" in finding.message

    def test_a_partial_second_source_joins_a_governed_group(self, tmp_path):
        """DD-213's headline: a new source binds to the Silver model by declaring its gap,
        without reshaping it or touching any existing binding."""
        binding_dir = _write_hub(tmp_path)

        def govern(document):
            entity = document["entities"][0]
            entity["properties"][1]["requirement"] = "optional"
            entity["properties"][1]["nullable"] = True
            # The union emits unsized string (see the widening test above), so this is the
            # contract an operator lands once the class is multi-source.
            for item in entity["properties"]:
                item["type"] = "string"

        _adopt_contract(tmp_path, govern)
        _add_second_source(tmp_path, binding_dir, partial=True)
        codes = _diagnostics(tmp_path)
        assert "conformance.property-incompatible" not in codes
        assert not [code for code in codes if code.startswith("contract.")]
        assert _authored_columns(tmp_path, "customer") == ["customer_id", "customer_name"]

    def test_union_columns_do_not_depend_on_binding_filename(self, tmp_path):
        """B1: the union takes its columns from `base_model` -- the binding that sorts first
        by path. Under a contract that must stop mattering, or a partial source could
        silently truncate the canonical model by being renamed."""
        binding_dir = _write_hub(tmp_path)

        def govern(document):
            entity = document["entities"][0]
            entity["properties"][1]["requirement"] = "optional"
            entity["properties"][1]["nullable"] = True
            for item in entity["properties"]:
                item["type"] = "string"

        _adopt_contract(tmp_path, govern)
        _add_second_source(tmp_path, binding_dir, partial=True)
        columns = _authored_columns(tmp_path, "customer")
        assert columns == ["customer_id", "customer_name"]

        # Rename the partial binding so it now sorts FIRST, becoming `base_model`.
        (binding_dir / "erp-customer.binding.yaml").rename(
            binding_dir / "aaa-customer.binding.yaml"
        )
        assert _authored_columns(tmp_path, "customer") == columns


class TestRealHubShapes:
    """Shapes found in real client hubs that synthetic fixtures did not cover.

    Both cases below were caught by running scaffold-contract against
    fracht-client-ontology-hub, where the scaffolder produced documents its own loader
    rejected. Pinned here so a synthetic-only fixture cannot let them regress.
    """

    def test_absolute_iris_are_accepted(self):
        """Real hubs author target.class and field properties as absolute IRIs, not
        prefixed QNames."""
        document = _document()
        entity = _entity(document)
        entity["class"] = "https://fracht.com/ont/party#FrachtParty"
        entity["properties"][0]["property"] = "https://fracht.com/ont/party#partyReference"
        entity["properties"][1]["property"] = (
            "https://www.kairosflow.ai/ont/bsp/party#partyIdentifier"
        )
        # The local name is taken after '#', not by splitting on the scheme colon.
        entity["grain"]["columns"] = ["party_reference"]
        entity["identity"]["businessKey"] = ["party_reference"]
        contract = load_silver_contract(_dump(document))
        declared = contract.entity_for("https://fracht.com/ont/party#FrachtParty")
        assert declared is not None
        assert [resolved_column_name(item) for item in declared.properties] == [
            "party_reference",
            "party_identifier",
        ]

    def test_a_technical_column_may_carry_the_grain(self):
        """A materialized grain is routinely a DD-139 technical identity column that is no
        semantic property at all -- e.g. `source_record_id` in fracht's bindings."""
        document = _document()
        entity = _entity(document)
        entity["technicalColumns"][0] = {
            "name": "source_record_id",
            "type": "string",
            "requirement": "required",
            "nullable": False,
        }
        entity["grain"]["columns"] = ["source_record_id"]
        entity["identity"]["businessKey"] = ["source_record_id"]
        contract = load_silver_contract(_dump(document))
        assert contract.entity_for("party:Customer").grain == ("source_record_id",)

    def test_an_optional_technical_grain_column_is_still_rejected(self):
        document = _document()
        entity = _entity(document)
        entity["technicalColumns"][0] = {
            "name": "source_record_id",
            "type": "string",
            "requirement": "optional",
            "nullable": True,
        }
        entity["grain"]["columns"] = ["source_record_id"]
        assert "contract.grain-not-required" in _codes(_dump(document))
