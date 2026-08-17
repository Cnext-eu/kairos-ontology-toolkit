# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the pack-scoped entity-projection loader (DD-188, issue #531).

Every case reads a fixture written into ``tmp_path``, never the installed
accelerator pack: these pin the *contract* between the two repos, so a vocabulary
change shipped in reference-models cannot silently rewrite what the toolkit
promises — and the suite stays green on a machine with no packs installed.
"""

from __future__ import annotations

import logging

import pytest
import yaml

from kairos_ontology.core.entity_projections import (
    PROJECTIONS_FILENAME,
    ProjectionConfig,
    entity_projection_paths,
    load_entity_projections,
    parse_entity_projections,
)

from entity_projection_fixtures import (
    ADDRESS_URI,
    POSTAL_ADDRESS_YAML,
    write_projection_pack,
)


class TestResolution:
    """The precedent being matched is ``load_data_domains``, exactly."""

    def test_reads_the_pack_scoped_blueprint_file(self, tmp_path):
        written = write_projection_pack(tmp_path, accelerator="logistics")
        assert written.parent.name == "client-hub-blueprint"
        config = load_entity_projections(tmp_path, "logistics")
        assert config.source_path == written
        assert [p.id for p in config.projections] == ["postal-address"]

    def test_accelerator_pins_which_pack_is_read(self, tmp_path):
        """With several packs installed, globbing takes `financial-services` first
        alphabetically. An explicit accelerator must not be second-guessed."""
        write_projection_pack(tmp_path, accelerator="logistics")
        write_projection_pack(
            tmp_path,
            POSTAL_ADDRESS_YAML.replace("id: postal-address", "id: branch-address"),
            accelerator="financial-services",
        )
        assert [p.id for p in load_entity_projections(tmp_path, "logistics").projections] == [
            "postal-address"
        ]
        assert [
            p.id for p in load_entity_projections(tmp_path, "financial-services").projections
        ] == ["branch-address"]

    def test_no_accelerator_means_first_sorted_match_wins(self, tmp_path):
        write_projection_pack(tmp_path, accelerator="logistics")
        write_projection_pack(
            tmp_path,
            POSTAL_ADDRESS_YAML.replace("id: postal-address", "id: branch-address"),
            accelerator="financial-services",
        )
        config = load_entity_projections(tmp_path, None)
        assert [p.id for p in config.projections] == ["branch-address"]

    def test_current_blueprint_is_not_searched(self, tmp_path):
        """`<pack>/current/blueprint/` is the logistics-only blueprint dossier and
        `financial-services/current/` has no `blueprint/` at all, so it can never be
        the pack-agnostic hub-facing surface. Reading it would work for one pack and
        be structurally impossible for the other."""
        write_projection_pack(tmp_path, accelerator="logistics", subdir="current/blueprint")
        assert entity_projection_paths(tmp_path, "logistics") == []
        assert load_entity_projections(tmp_path, "logistics").projections == ()


class TestNoConfig:
    """DD-188's central rule: absence is a real, reported answer."""

    def test_missing_file_returns_an_empty_config(self, tmp_path):
        (tmp_path / "accelerator-packs" / "logistics" / "client-hub-blueprint").mkdir(parents=True)
        config = load_entity_projections(tmp_path, "logistics")
        assert config.projections == ()
        assert not config
        assert config.source_path is None

    def test_missing_file_is_logged_with_the_reason(self, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="kairos_ontology.core.entity_projections"):
            load_entity_projections(tmp_path, "logistics")
        assert f"No {PROJECTIONS_FILENAME} found" in caplog.text
        assert "no built-in projection vocabulary" in caplog.text

    def test_no_refmodels_dir_at_all_is_logged_not_raised(self, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="kairos_ontology.core.entity_projections"):
            config = load_entity_projections(None, "logistics")
        assert config.projections == ()
        assert "No reference-models directory available" in caplog.text

    def test_a_pack_that_ships_none_is_a_supported_state(self, tmp_path):
        """`financial-services` deliberately ships no projections. That is the
        intended state, not a broken install."""
        write_projection_pack(tmp_path, accelerator="logistics")
        assert load_entity_projections(tmp_path, "financial-services").projections == ()


class TestMalformedInput:
    """Advisory input must never fail a run — warn and carry on, like the precedent."""

    def _write(self, tmp_path, text):
        path = (
            tmp_path
            / "accelerator-packs"
            / "logistics"
            / "client-hub-blueprint"
            / PROJECTIONS_FILENAME
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_unparseable_yaml_warns_and_yields_nothing(self, tmp_path, caplog):
        self._write(tmp_path, "projections: [ unclosed")
        with caplog.at_level(logging.WARNING, logger="kairos_ontology.core.entity_projections"):
            config = load_entity_projections(tmp_path, "logistics")
        assert config.projections == ()
        assert "Failed to load" in caplog.text

    def test_a_projection_with_no_part_kinds_is_dropped_with_a_warning(self, tmp_path, caplog):
        self._write(tmp_path, "schema_version: 1\nprojections:\n  - id: hollow\n")
        with caplog.at_level(logging.WARNING, logger="kairos_ontology.core.entity_projections"):
            config = load_entity_projections(tmp_path, "logistics")
        assert config.projections == ()
        assert "no usable part_kinds" in caplog.text

    @pytest.mark.parametrize("payload", ["", "[]", "projections: {}"])
    def test_structurally_wrong_payloads_yield_an_empty_config(self, payload):
        config = parse_entity_projections(yaml.safe_load(payload) if payload else None)
        assert config.projections == ()
        assert config.warnings

    def test_duplicate_ids_keep_the_first(self, tmp_path):
        doubled = POSTAL_ADDRESS_YAML + POSTAL_ADDRESS_YAML.split("projections:", 1)[1]
        config = parse_entity_projections(yaml.safe_load(doubled))
        assert [p.id for p in config.projections] == ["postal-address"]
        assert any("duplicate" in w for w in config.warnings)


class TestSchema:
    """The parsed shape is the DD-188 contract, field for field."""

    @pytest.fixture
    def projection(self):
        return parse_entity_projections(yaml.safe_load(POSTAL_ADDRESS_YAML)).projections[0]

    def test_top_level_fields(self, projection):
        assert projection.id == "postal-address"
        assert projection.target_concept == "Address"
        assert projection.target_candidates == (ADDRESS_URI,)
        assert projection.min_complementary_parts == 2
        assert projection.relationship_naming == "has{Role}Address"
        assert projection.default_relationship == "hasAddress"
        assert projection.cardinality == "1:n"

    def test_part_kind_gates(self, projection):
        by_kind = {p.kind: p for p in projection.part_kinds}
        assert by_kind["street"].weak is False
        assert by_kind["street"].needs_confirmation is False
        assert by_kind["city"].weak is True
        assert by_kind["city"].needs_context is False
        assert by_kind["state"].needs_context is True
        assert by_kind["postal"].compact == ("postalcode", "zipcode")

    def test_part_kind_order_is_the_declaration_order(self, projection):
        """Kinds are matched most-specific-first, so the file's order is load-bearing
        and must survive parsing."""
        assert [p.kind for p in projection.part_kinds] == [
            "street",
            "house_number",
            "postal",
            "city",
            "state",
            "country",
            "address_line",
        ]

    def test_freight_roles_the_old_hardcoded_list_lacked(self, projection):
        assert {"pickup", "origin", "destination", "terminal", "depot", "port"} <= (
            projection.role_qualifiers
        )

    def test_context_tokens(self, projection):
        assert projection.context_tokens == frozenset({"location", "premises", "site", "facility"})

    def test_empty_config_is_falsy_and_a_populated_one_is_truthy(self, projection):
        assert not ProjectionConfig()
        assert parse_entity_projections(yaml.safe_load(POSTAL_ADDRESS_YAML))
