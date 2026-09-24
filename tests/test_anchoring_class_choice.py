# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Choosing the right reference class during anchoring (#913, #927, #863)."""

from __future__ import annotations

from dataclasses import replace

import pytest
import yaml

from kairos_ontology.core.anchor_tables import (
    ClassCatalog,
    choose_class_copy_with_basis,
    detect_shared_class_anchors,
)
from kairos_ontology.core.blueprint_artifacts import load_canonical_class_uris

_BSP = "https://ref.test/bsp/commercial#TransportLeg"
_MMT = "https://ref.test/mmt/consignment#TransportLeg"


def _copies(bsp_props=("legId",), mmt_props=("legId",)):
    return [
        {"module": "https://ref.test/bsp/commercial", "uri": _BSP, "properties": list(bsp_props)},
        {"module": "https://ref.test/mmt/consignment", "uri": _MMT, "properties": list(mmt_props)},
    ]


def _catalog(canonical=frozenset()):
    owners = {"https://ref.test/bsp/commercial": ["trade"],
              "https://ref.test/mmt/consignment": ["consignment"]}
    return ClassCatalog(text="", index={}, owners=owners, canonical_uris=canonical)


class TestTheCanonicalRegistry:
    """#913: the pack's own judgement breaks a tie the columns cannot."""

    def test_it_breaks_a_tie_and_says_so(self):
        chosen, basis = choose_class_copy_with_basis(
            _copies(), _catalog(frozenset({_MMT})), "consignment", ["LEG_NO"]
        )
        assert chosen["uri"] == _MMT
        assert basis == "canonical class registry"

    def test_the_tables_own_columns_outrank_it(self):
        """Direct evidence about this table beats curated judgement about the concept."""
        chosen, basis = choose_class_copy_with_basis(
            _copies(bsp_props=("vesselVoyage", "legId")), _catalog(frozenset({_MMT})),
            "consignment", ["VESSEL_VOYAGE"],
        )
        assert chosen["uri"] == _BSP
        assert basis == "column/property overlap"

    def test_without_a_registry_nothing_changes(self):
        chosen, _ = choose_class_copy_with_basis(_copies(), _catalog(), "consignment", ["X"])
        assert chosen["uri"] == _MMT, "same-domain ownership still settles a full tie"

    def test_the_loader_reads_the_dossier_and_skips_rejected(self, tmp_path):
        path = tmp_path / "accelerator-packs" / "logistics" / "current" / "blueprint"
        path.mkdir(parents=True)
        (path / "canonical-class-registry.yaml").write_text(yaml.safe_dump({"concepts": [
            {"id": "transport-leg", "class_uri": _MMT, "disposition": "unresolved"},
            {"id": "old", "class_uri": _BSP, "disposition": "rejected"},
        ]}), encoding="utf-8")

        assert load_canonical_class_uris(tmp_path, "logistics") == frozenset({_MMT})
        assert load_canonical_class_uris(tmp_path, "financial") == frozenset(), "no dossier"
        assert load_canonical_class_uris(None, "logistics") == frozenset()


class TestSharedAbstractClass:
    """#927: three unrelated code lists on one abstract class are not one entity."""

    def _tables(self):
        return [
            {"system": "tms", "table": "equipcodes", "anchor": "CodeListElement",
             "anchor_uri": "https://ref.test/cargo#CodeListElement", "natural_key": ["CODE"]},
            {"system": "tms", "table": "edi_codes", "anchor": "CodeListElement",
             "anchor_uri": "https://ref.test/cargo#CodeListElement",
             "natural_key": ["PARTNER", "DIRECTION", "TYPE", "CODE"]},
            {"system": "tms", "table": "settings", "anchor": "CodeListElement",
             "anchor_uri": "https://ref.test/cargo#CodeListElement",
             "natural_key": ["APP", "KEY"]},
            {"system": "erp", "table": "codes", "anchor": "CodeListElement",
             "anchor_uri": "https://ref.test/cargo#CodeListElement", "natural_key": ["CODE"]},
        ]

    def test_one_system_at_different_arity_is_reported(self):
        (finding,) = detect_shared_class_anchors(self._tables())
        assert finding["system"] == "tms"
        assert [t["table"] for t in finding["tables"]] == ["edi_codes", "equipcodes", "settings"]

    def test_the_same_arity_is_left_alone(self):
        tables = [dict(t, natural_key=["CODE"]) for t in self._tables()]
        assert detect_shared_class_anchors(tables) == []

    def test_the_compile_gate_names_the_likely_cause(self):
        from kairos_ontology.core.compiler import CompileError
        from tests.test_compiler_conformance import _binding, _plan

        first = _binding("equip-codes", "tms.equipcodes", 1)
        second = replace(_binding("edi-codes", "tms.edi_codes", 2), conformance=None)
        second = replace(
            second,
            identity=replace(second.identity, source_key=("partner", "direction", "code")),
        )

        with pytest.raises(CompileError) as excinfo:
            _plan(first, second)

        (required,) = [d for d in excinfo.value.diagnostics
                       if d.code == "conformance.group-required"]
        assert "abstract class" in required.message
        assert "own hub-local subclass" in required.message


class TestModuleQualifiedMatches:
    """#863: a duplicated name can be pinned to a module, and the proposal pool is scoped."""

    def _universe(self):
        class_record = {_BSP: object(), _MMT: object()}
        name_to_uris = {"TransportLeg": {_BSP, _MMT}}
        class_owner = {_BSP: "bsp-commercial", _MMT: "mmt-consignment"}
        return class_record, name_to_uris, class_owner

    def test_a_bare_duplicate_stays_unresolved(self):
        from kairos_ontology.core.design_landscape import _resolve_universe_token

        record, names, owner = self._universe()
        assert _resolve_universe_token("TransportLeg", record, names, owner) is None

    @pytest.mark.parametrize("token", [
        "consignment:TransportLeg", "mmt/consignment:TransportLeg", "mmt-consignment:TransportLeg",
    ])
    def test_a_module_prefix_pins_it(self, token):
        from kairos_ontology.core.design_landscape import _resolve_universe_token

        record, names, owner = self._universe()
        assert _resolve_universe_token(token, record, names, owner) == _MMT

    def test_the_proposer_reads_only_the_activated_modules(self, tmp_path, monkeypatch):
        from kairos_ontology.core import class_anchoring
        from kairos_ontology.core.import_tmdl import propose_reference_matches
        from kairos_ontology.core.tmdl_parser import TmdlModel, TmdlTable

        seen = {}

        def fake_terms(catalog_path, *, module_scope=None):
            seen["scope"] = module_scope
            return []

        monkeypatch.setattr(class_anchoring, "read_reference_terms", fake_terms)
        catalog = tmp_path / "catalog-v001.xml"
        catalog.write_text("<catalog/>", encoding="utf-8")
        model = TmdlModel(name="M", tables=[TmdlTable(name="d_TransportLeg")])

        propose_reference_matches(model, catalog, {"https://ref.test/mmt/consignment"})

        assert seen["scope"] == {"https://ref.test/mmt/consignment"}
