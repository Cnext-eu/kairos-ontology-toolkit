# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Owner-tagged candidate property pool: issues #517 and #520.

The two are one mechanism seen from opposite ends. #517 widens the pool so a
property on a *value object* of the anchor is offered at all; #520 requires that
whatever the model picks is checked as a ``(class, property)`` **pair**, not as a
name that exists somewhere. Widening the pool without pairing the check makes the
wrong-class hazard strictly worse, so both are asserted against the same fixtures.

The fixtures are the real shapes the defects were found on, reduced:

* ``imo/vessel-registry`` — ``Vessel --hasCapacity--> VesselCapacity``, with
  ``GrossTonnage`` as a subclass carrying ``grossTonnageValue``. ``Vessel`` carries
  no tonnage property at all, which is why aligning a ``GRT`` column against the
  anchor alone reported a false gap.
* ``tic/*`` — two distinct classes both named ``Terminal``, only one of which
  declares ``terminalName``. Nothing in the model's answer distinguishes them.
"""

import json
from unittest import mock

import pytest
import yaml

from kairos_ontology.core.propose_alignment import (
    build_domain_alignments,
    MAX_VALUE_OBJECT_CLASSES,
    TOTAL_SCHEMA_ENUM_BUDGET,
    align_table,
    build_alignment_prompt,
    build_alignment_response_schema,
    build_class_property_index,
    build_property_owner_index,
    enforce_class_property_pairs,
    expand_value_object_pool,
    qualified_property_names,
    schema_uses_qualified_properties,
)

VESSEL = {
    "name": "Vessel",
    "label": "Vessel",
    "comment": "",
    "uri": "https://example.com/ont/imo/vessel-registry#Vessel",
    "properties": [
        {"name": "vesselName", "label": "vessel name", "range": "string", "type": "datatype"},
        {
            "name": "hasCapacity",
            "label": "has capacity",
            "range": "VesselCapacity",
            "range_uri": "https://example.com/ont/imo/vessel-registry#VesselCapacity",
            "type": "object",
        },
    ],
}

VESSEL_CAPACITY = {
    "name": "VesselCapacity",
    "label": "Vessel Capacity",
    "comment": "",
    "uri": "https://example.com/ont/imo/vessel-registry#VesselCapacity",
    "properties": [
        {"name": "capacityUnit", "label": "capacity unit", "range": "string", "type": "datatype"},
    ],
    "specializations": [
        {
            "class": "GrossTonnage",
            "class_uri": "https://example.com/ont/imo/vessel-registry#GrossTonnage",
            "distance": 1,
            "properties": [
                {
                    "name": "grossTonnageValue",
                    "label": "gross tonnage value",
                    "range": "decimal",
                    "type": "datatype",
                }
            ],
        },
        {
            # Inherits everything, declares nothing: a prompt slot spent on this
            # would repeat the parent's vocabulary verbatim.
            "class": "BareCapacity",
            "class_uri": "https://example.com/ont/imo/vessel-registry#BareCapacity",
            "distance": 1,
            "properties": [],
        },
    ],
}

GROSS_TONNAGE = {
    "name": "GrossTonnage",
    "label": "Gross Tonnage",
    "comment": "1969 Tonnage Convention.",
    "uri": "https://example.com/ont/imo/vessel-registry#GrossTonnage",
    "properties": [
        {"name": "capacityUnit", "label": "capacity unit", "range": "string", "type": "datatype"},
        {
            "name": "grossTonnageValue",
            "label": "gross tonnage value",
            "range": "decimal",
            "type": "datatype",
        },
    ],
}

BARE_CAPACITY = {
    "name": "BareCapacity",
    "label": "Bare Capacity",
    "comment": "",
    "uri": "https://example.com/ont/imo/vessel-registry#BareCapacity",
    "properties": [
        {"name": "capacityUnit", "label": "capacity unit", "range": "string", "type": "datatype"},
    ],
}

SURVEYOR = {
    "name": "Surveyor",
    "label": "Surveyor",
    "comment": "",
    "uri": "https://example.com/ont/imo/certificates#Surveyor",
    "properties": [
        {"name": "surveyorName", "label": "surveyor name", "range": "string",
         "type": "datatype"},
    ],
}

CERTIFICATE = {
    "name": "StatutoryCertificate",
    "label": "Statutory Certificate",
    "comment": "",
    "uri": "https://example.com/ont/imo/certificates#StatutoryCertificate",
    "properties": [
        {
            "name": "issuedFor",
            "label": "issued for",
            "range": "Vessel",
            "range_uri": "https://example.com/ont/imo/vessel-registry#Vessel",
            "type": "object",
        },
        {
            "name": "surveyedBy",
            "label": "surveyed by",
            "range": "Surveyor",
            "range_uri": "https://example.com/ont/imo/certificates#Surveyor",
            "type": "object",
        },
    ],
}

VESSEL_INVENTORY = [
    VESSEL,
    VESSEL_CAPACITY,
    GROSS_TONNAGE,
    BARE_CAPACITY,
    CERTIFICATE,
    SURVEYOR,
]

#: Two same-named classes, only one carrying ``terminalName`` — the #520 evidence.
TERMINAL_INFRA = {
    "name": "Terminal",
    "label": "Terminal",
    "comment": "",
    "uri": "https://example.com/ont/tic/terminal-infrastructure#Terminal",
    "properties": [
        {"name": "terminalName", "label": "terminal name", "range": "string", "type": "datatype"},
    ],
}

TERMINAL_LOCATION = {
    "name": "Terminal",
    "label": "Terminal",
    "comment": "",
    "uri": "https://example.com/ont/tic/locations#Terminal",
    "properties": [
        {"name": "unlocode", "label": "UN/LOCODE", "range": "string", "type": "datatype"},
    ],
}

HORIZONTAL_MOVE = {
    "name": "HorizontalMove",
    "label": "Horizontal Move",
    "comment": "",
    "uri": "https://example.com/ont/tic/handling-operations#HorizontalMove",
    "properties": [
        {"name": "moveTimestamp", "label": "move timestamp", "range": "dateTime",
         "type": "datatype"},
    ],
}


def _mock_client(response_dict, prompts=None):
    """A client that records the user prompt and replays one canned response."""

    def create_completion(**kwargs):
        if prompts is not None:
            prompts.append(kwargs["messages"][1]["content"])
        return mock.MagicMock(
            choices=[mock.MagicMock(message=mock.MagicMock(content=json.dumps(response_dict)))]
        )

    client = mock.MagicMock()
    client.chat.completions.create = create_completion
    return client


@pytest.fixture
def fleet_analysis_dir(tmp_path):
    """One vessel table in a ``vessel-maritime`` domain, anchored to ``Vessel``."""
    analysis = tmp_path / "_analysis"
    analysis.mkdir()
    (analysis / "seeds-affinity.yaml").write_text(
        yaml.safe_dump(
            {
                "system": "seeds",
                "schema_version": 2,
                "tables": [
                    {
                        "table": "d_vyr_ship_s_archive",
                        "total_columns": 2,
                        "domain": "vessel-maritime",
                        "domain_uris": ["https://example.com/ont/imo/vessel-registry#"],
                        "confidence": 0.9,
                        "likely_entity": "Vessel",
                        "indicative_columns": ["SHIP_NAME"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return analysis


@pytest.fixture
def fleet_sources_dir(tmp_path):
    sources = tmp_path / "sources"
    (sources / "seeds").mkdir(parents=True)
    (sources / "seeds" / "seeds.vocabulary.ttl").write_text(
        """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .

<#d_vyr_ship_s_archive> a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "d_vyr_ship_s_archive" .

<#c_ship_name> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "SHIP_NAME" ;
    kairos-bronze:dataType "nvarchar(80)" ;
    kairos-bronze:belongsToTable <#d_vyr_ship_s_archive> .

<#c_grt> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "GRT" ;
    kairos-bronze:dataType "int" ;
    kairos-bronze:belongsToTable <#d_vyr_ship_s_archive> .
""",
        encoding="utf-8",
    )
    return sources


# ---------------------------------------------------------------------------
# Issue #517 — value objects reach the candidate pool
# ---------------------------------------------------------------------------


class TestValueObjectPool:
    def test_subclass_of_an_object_property_range_is_offered(self):
        """The reported failure: ``grossTonnageValue`` two hops from the anchor.

        Hub evidence (``vessel-maritime``): the twelve-class lexical shortlist held
        ``Vessel`` and eleven certificate classes, so the property was never shown
        and the ``GRT`` column came back a gap with a local-property proposal.
        """
        added = expand_value_object_pool([VESSEL], VESSEL_INVENTORY, anchor_class="Vessel")
        offered = {
            (cls["name"], prop["name"]) for cls in added for prop in cls["properties"]
        }
        assert ("GrossTonnage", "grossTonnageValue") in offered
        assert ("VesselCapacity", "capacityUnit") in offered

    def test_each_addition_names_the_route_it_was_reached_by(self):
        added = expand_value_object_pool([VESSEL], VESSEL_INVENTORY, anchor_class="Vessel")
        assert all(c["_value_object_of"]["via"] == "Vessel.hasCapacity" for c in added)
        assert all(c["_value_object_of"]["owner"] == "Vessel" for c in added)

    def test_a_subclass_contributes_only_what_it_declares(self):
        """A subclass that only inherits adds no vocabulary, so it gets no slot.

        Without this the terminal-operations pool picked up six equipment
        subclasses whose rendered property lists were identical to their parent's.
        """
        added = {c["name"]: c for c in expand_value_object_pool([VESSEL], VESSEL_INVENTORY)}
        assert "BareCapacity" not in added
        assert [p["name"] for p in added["GrossTonnage"]["properties"]] == ["grossTonnageValue"]

    def test_classes_already_shortlisted_are_not_duplicated(self):
        added = expand_value_object_pool(
            [VESSEL, GROSS_TONNAGE], VESSEL_INVENTORY, anchor_class="Vessel"
        )
        assert "GrossTonnage" not in {c["name"] for c in added}

    def test_the_anchor_gets_first_claim_on_the_budget(self):
        """With one slot to spend it goes to the anchor's own value object."""
        added = expand_value_object_pool(
            [CERTIFICATE, VESSEL], VESSEL_INVENTORY, anchor_class="Vessel", max_classes=1
        )
        assert [c["name"] for c in added] == ["VesselCapacity"]

    def test_without_an_anchor_the_shortlist_order_decides(self):
        added = expand_value_object_pool(
            [CERTIFICATE, VESSEL], VESSEL_INVENTORY, max_classes=1
        )
        assert [c["name"] for c in added] == ["Surveyor"]

    def test_expansion_is_bounded(self):
        added = expand_value_object_pool([VESSEL], VESSEL_INVENTORY, anchor_class="Vessel")
        assert len(added) <= MAX_VALUE_OBJECT_CLASSES

    def test_datatype_properties_are_not_followed(self):
        """Only object properties point at another class; a range name that happens
        to collide with a class must not drag it in."""
        literal_only = {
            "name": "Thing",
            "uri": "https://example.com/ont/x#Thing",
            "properties": [
                {"name": "capacity", "range": "VesselCapacity", "type": "datatype"},
            ],
        }
        assert expand_value_object_pool([literal_only], VESSEL_INVENTORY) == []

    def test_a_pool_without_value_objects_adds_nothing(self):
        assert expand_value_object_pool([TERMINAL_INFRA], [TERMINAL_INFRA]) == []


class TestValueObjectPrompt:
    def test_the_prompt_lists_the_value_object_and_its_route(self):
        pool = [VESSEL] + expand_value_object_pool(
            [VESSEL], VESSEL_INVENTORY, anchor_class="Vessel"
        )
        prompt = build_alignment_prompt(
            "d_vyr_ship_s_archive",
            [{"name": "GRT", "data_type": "int"}],
            pool,
            table_ref_classes=[VESSEL],
        )
        assert "grossTonnageValue" in prompt
        assert "VALUE OBJECT / RELATED ENTITY reached from Vessel.hasCapacity" in prompt
        assert "VALUE OBJECTS:" in prompt

    def test_a_home_only_prompt_is_not_told_about_module_markers(self):
        """``table_ref_classes`` no longer implies cross-module mode (#517).

        The note tells the model to read '[module: X]' markers; with no tagged
        class in the pool there are none, and the instruction is simply false.
        """
        pool = [VESSEL] + expand_value_object_pool([VESSEL], VESSEL_INVENTORY)
        prompt = build_alignment_prompt(
            "t", [{"name": "GRT", "data_type": "int"}], pool, table_ref_classes=[VESSEL]
        )
        assert "CROSS-MODULE:" not in prompt
        assert "ref_module" not in prompt

    def test_a_tagged_pool_still_gets_the_cross_module_note(self):
        tagged = [dict(VESSEL_CAPACITY, module="vessel-registry")]
        prompt = build_alignment_prompt(
            "t", [{"name": "x", "data_type": "int"}], [VESSEL] + tagged, table_ref_classes=[VESSEL]
        )
        assert "CROSS-MODULE:" in prompt
        assert "ref_module" in prompt


class TestValueObjectReachesTheModel:
    def test_the_call_offers_the_tonnage_property(self):
        """End to end through ``align_table``: the property is in the prompt *and*
        in the strict-schema enum, so the model can actually return it."""
        prompts: list[str] = []
        client = _mock_client(
            {
                "ref_class": "Vessel",
                "ref_class_confidence": 0.9,
                "column_alignments": [
                    {
                        "column": "GRT",
                        "ref_property": "GrossTonnage.grossTonnageValue",
                        "alignment": "semantic",
                        "confidence": 0.9,
                        "rationale": "gross registered tonnage",
                    }
                ],
            },
            prompts,
        )
        pool = [VESSEL] + expand_value_object_pool(
            [VESSEL], VESSEL_INVENTORY, anchor_class="Vessel"
        )
        result = align_table(
            client,
            "gpt-5.4",
            "d_vyr_ship_s_archive",
            [{"name": "GRT", "data_type": "int"}],
            pool,
            table_ref_classes=[VESSEL],
        )
        assert "grossTonnageValue" in prompts[0]
        mapped = result["column_alignments"][0]
        assert mapped["alignment"] == "semantic"
        assert mapped["ref_class"] == "GrossTonnage"
        assert mapped["ref_property"] == "grossTonnageValue"

    def test_the_pipeline_offers_it_without_being_asked(
        self, fleet_analysis_dir, fleet_sources_dir
    ):
        """The reproduction from issue #517, through the real selection path.

        Nothing here hands the pool a value object: the domain inventory is the
        whole ``imo/vessel-registry`` shape and the table anchors to ``Vessel``.
        Before the fix the shortlist stopped at the anchor, ``grossTonnageValue``
        never appeared in the prompt, and the ``GRT`` column was reported as a gap.
        """
        prompts: list[str] = []
        client = _mock_client(
            {
                "ref_class": "Vessel",
                "ref_class_confidence": 0.9,
                "column_alignments": [
                    {
                        "column": "GRT",
                        "ref_class": "GrossTonnage",
                        "ref_property": "grossTonnageValue",
                        "alignment": "semantic",
                        "confidence": 0.9,
                        "rationale": "gross registered tonnage",
                    }
                ],
            },
            prompts,
        )
        with (
            mock.patch(
                "kairos_ontology.core.propose_alignment.get_ai_client", return_value=client
            ),
            mock.patch("kairos_ontology.core.propose_alignment.require_ai_provider"),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                return_value=VESSEL_INVENTORY,
            ),
        ):
            alignments = build_domain_alignments(
                analysis_dir=fleet_analysis_dir,
                sources_dir=fleet_sources_dir,
                catalog_path=None,
                domains_filter=["vessel-maritime"],
                max_prompt_classes=1,
            )
        assert "grossTonnageValue" in prompts[0]
        table = alignments[0].tables[0]
        grt = next(c for c in table.columns if c.column == "GRT")
        assert (grt.ref_class, grt.ref_property) == ("GrossTonnage", "grossTonnageValue")


# ---------------------------------------------------------------------------
# Issue #520 — the pair, not the name
# ---------------------------------------------------------------------------


class TestPairIndex:
    def test_index_records_the_owner_of_every_property(self):
        index = build_class_property_index([TERMINAL_INFRA, TERMINAL_LOCATION, HORIZONTAL_MOVE])
        assert index["Terminal"] == frozenset({"terminalName", "unlocode"})
        assert index["HorizontalMove"] == frozenset({"moveTimestamp"})

    def test_owner_index_is_the_inverse(self):
        owners = build_property_owner_index(
            build_class_property_index([TERMINAL_INFRA, HORIZONTAL_MOVE, GROSS_TONNAGE])
        )
        assert owners["terminalName"] == ("Terminal",)
        assert owners["capacityUnit"] == ("GrossTonnage",)


class TestClassPropertyPairValidation:
    def test_a_property_on_a_class_that_lacks_it_is_reassigned_to_its_owner(self):
        """The hub failure: ``terminalName`` proposed on a class without it.

        One offered class declares it, so the property names its own owner and the
        mapping is corrected rather than discarded.
        """
        alignments = [
            {
                "column": "CompanyName",
                "ref_class": "HorizontalMove",
                "ref_property": "terminalName",
                "alignment": "partial",
                "rationale": "the visited company is a terminal",
            }
        ]
        repaired, rejected = enforce_class_property_pairs(
            alignments, [TERMINAL_INFRA, HORIZONTAL_MOVE]
        )
        assert (repaired, rejected) == (1, 0)
        assert alignments[0]["ref_class"] == "Terminal"
        assert alignments[0]["ref_property"] == "terminalName"

    def test_an_ambiguous_owner_is_rejected_rather_than_guessed(self):
        alignments = [
            {
                "column": "Code",
                "ref_class": "HorizontalMove",
                "ref_property": "sharedCode",
                "alignment": "semantic",
                "rationale": "looked right",
            }
        ]
        a = dict(TERMINAL_INFRA, properties=[{"name": "sharedCode"}])
        b = dict(HORIZONTAL_MOVE, name="Berth", properties=[{"name": "sharedCode"}])
        repaired, rejected = enforce_class_property_pairs(alignments, [a, b, HORIZONTAL_MOVE])
        assert (repaired, rejected) == (0, 1)
        assert alignments[0]["alignment"] == "custom"
        assert alignments[0]["ref_property"] == ""
        assert "Rejected wrong-class reference property 'sharedCode'" in alignments[0]["rationale"]
        assert "looked right" in alignments[0]["rationale"]

    def test_a_property_no_offered_class_carries_is_rejected(self):
        alignments = [
            {
                "column": "X",
                "ref_class": "Terminal",
                "ref_property": "invented",
                "alignment": "exact",
                "rationale": "",
            }
        ]
        assert enforce_class_property_pairs(alignments, [TERMINAL_INFRA]) == (0, 1)
        assert alignments[0]["alignment"] == "custom"

    def test_a_correct_pair_is_left_exactly_as_it_was(self):
        alignments = [
            {
                "column": "Name",
                "ref_class": "Terminal",
                "ref_property": "terminalName",
                "alignment": "exact",
                "rationale": "same concept",
            }
        ]
        before = dict(alignments[0])
        assert enforce_class_property_pairs(alignments, [TERMINAL_INFRA]) == (0, 0)
        assert alignments[0] == before

    def test_same_named_classes_are_unioned_not_intersected(self):
        """Both ``tic`` modules declare a ``Terminal``; the response names only
        ``Terminal``. Neither can be ruled out, so neither is rejected."""
        alignments = [
            {"column": "a", "ref_class": "Terminal", "ref_property": "terminalName",
             "alignment": "exact", "rationale": ""},
            {"column": "b", "ref_class": "Terminal", "ref_property": "unlocode",
             "alignment": "exact", "rationale": ""},
        ]
        assert enforce_class_property_pairs(
            alignments, [TERMINAL_INFRA, TERMINAL_LOCATION]
        ) == (0, 0)

    def test_custom_columns_are_not_touched(self):
        alignments = [
            {"column": "x", "ref_class": "Terminal", "ref_property": "whatever",
             "alignment": "custom", "rationale": "no match"}
        ]
        assert enforce_class_property_pairs(alignments, [TERMINAL_INFRA]) == (0, 0)
        assert alignments[0]["ref_property"] == "whatever"


class TestPairValidationInTheAlignmentCall:
    def test_a_wrong_class_pair_does_not_survive_the_call(self):
        """The whole point of #520: the response looks perfectly well-formed."""
        client = _mock_client(
            {
                "ref_class": "HorizontalMove",
                "ref_class_confidence": 0.7,
                "column_alignments": [
                    {
                        "column": "CompanyName",
                        "ref_class": "HorizontalMove",
                        "ref_property": "terminalName",
                        "alignment": "partial",
                        "confidence": 0.63,
                        "rationale": "when the visited company is a terminal",
                    }
                ],
            }
        )
        result = align_table(
            client,
            "gpt-5.4",
            "EsriGrid_Operational_SQL_converted",
            [{"name": "CompanyName", "data_type": "varchar(max)"}],
            [HORIZONTAL_MOVE, TERMINAL_INFRA],
        )
        mapped = result["column_alignments"][0]
        assert (mapped["ref_class"], mapped["ref_property"]) == ("Terminal", "terminalName")

    def test_an_unownable_property_leaves_the_column_honestly_unmatched(self):
        client = _mock_client(
            {
                "ref_class": "HorizontalMove",
                "ref_class_confidence": 0.7,
                "column_alignments": [
                    {
                        "column": "CompanyName",
                        "ref_class": "HorizontalMove",
                        "ref_property": "moveTimestamp",
                        "alignment": "semantic",
                        "confidence": 0.6,
                        "rationale": "",
                    },
                    {
                        "column": "Actie",
                        "ref_class": "Berth",
                        "ref_property": "berthName",
                        "alignment": "semantic",
                        "confidence": 0.6,
                        "rationale": "",
                    },
                ],
            }
        )
        result = align_table(
            client,
            "gpt-5.4",
            "t",
            [
                {"name": "CompanyName", "data_type": "varchar(max)"},
                {"name": "Actie", "data_type": "varchar(max)"},
            ],
            [HORIZONTAL_MOVE, TERMINAL_INFRA],
        )
        kept, dropped = result["column_alignments"]
        assert (kept["ref_class"], kept["ref_property"]) == ("HorizontalMove", "moveTimestamp")
        assert dropped["alignment"] == "custom"
        assert dropped["ref_property"] == ""


# ---------------------------------------------------------------------------
# Issue #520 option 2 — qualified enum members, measured against the budget
# ---------------------------------------------------------------------------


class TestQualifiedPropertyEnum:
    def test_enum_members_carry_their_owning_class(self):
        pairs = qualified_property_names([TERMINAL_INFRA, TERMINAL_LOCATION])
        fmt, notes = build_alignment_response_schema(
            ["c"], ["Terminal"], ["terminalName", "unlocode"], qualified_properties=pairs
        )
        verdict = fmt["json_schema"]["schema"]["$defs"]["ColumnVerdict"]["properties"]
        assert verdict["ref_property"]["enum"] == [
            "Terminal.terminalName",
            "Terminal.unlocode",
            None,
        ]
        assert notes == []
        assert schema_uses_qualified_properties(fmt) is True

    def test_the_default_call_is_unchanged(self):
        """Callers that pass no pairs must get exactly the DD-177 schema."""
        fmt, notes = build_alignment_response_schema(["c"], ["C"], ["p", "q"])
        verdict = fmt["json_schema"]["schema"]["$defs"]["ColumnVerdict"]["properties"]
        assert verdict["ref_property"]["enum"] == ["p", "q", None]
        assert notes == []
        assert schema_uses_qualified_properties(fmt) is False

    def test_qualified_falls_back_to_bare_names_before_dropping_the_enum(self):
        """Degradation is three-tier, so nothing that used to fit stops fitting."""
        classes = [f"Class{i}" for i in range(30)]
        bare = [f"prop{i}" for i in range(200)]
        pairs = [f"{c}.{p}" for c in classes for p in bare][:1000]
        fmt, notes = build_alignment_response_schema(
            ["c"], classes, bare, qualified_properties=pairs
        )
        verdict = fmt["json_schema"]["schema"]["$defs"]["ColumnVerdict"]["properties"]
        assert verdict["ref_property"]["enum"] == [*sorted(bare), None]
        assert any("ref_property enum not qualified" in n for n in notes)

    def test_the_qualified_schema_stays_within_the_provider_limit(self):
        classes = [f"Class{i}" for i in range(40)]
        pairs = [f"Class{i}.prop{j}" for i in range(40) for j in range(10)]
        fmt, _ = build_alignment_response_schema(
            ["c"], classes, [f"prop{j}" for j in range(10)], qualified_properties=pairs
        )

        def count(node):
            if isinstance(node, dict):
                return len(node.get("enum", [])) + sum(count(v) for v in node.values())
            if isinstance(node, list):
                return sum(count(v) for v in node)
            return 0

        assert count(fmt["json_schema"]["schema"]) <= TOTAL_SCHEMA_ENUM_BUDGET + 1

    def test_the_prompt_asks_for_the_shape_the_enum_accepts(self):
        prompt = build_alignment_prompt(
            "t", [{"name": "x", "data_type": "int"}], [TERMINAL_INFRA], qualified_properties=True
        )
        assert "PROPERTY NAMING" in prompt
        assert "'<OwningClass>.<propertyName>'" in prompt
        assert "OwningClass.propertyName" in prompt

    def test_the_default_prompt_asks_for_a_bare_name(self):
        prompt = build_alignment_prompt("t", [{"name": "x", "data_type": "int"}], [TERMINAL_INFRA])
        assert "PROPERTY NAMING" not in prompt
        assert "<real reference property name, or null if alignment is custom>" in prompt

    def test_a_qualified_answer_is_split_back_into_class_and_property(self):
        client = _mock_client(
            {
                "ref_class": "HorizontalMove",
                "ref_class_confidence": 0.8,
                "column_alignments": [
                    {
                        "column": "CompanyName",
                        "ref_class": "HorizontalMove",
                        "ref_property": "Terminal.terminalName",
                        "alignment": "semantic",
                        "confidence": 0.8,
                        "rationale": "",
                    }
                ],
            }
        )
        result = align_table(
            client,
            "gpt-5.4",
            "t",
            [{"name": "CompanyName", "data_type": "varchar(max)"}],
            [HORIZONTAL_MOVE, TERMINAL_INFRA],
        )
        mapped = result["column_alignments"][0]
        assert mapped["ref_class"] == "Terminal"
        assert mapped["ref_property"] == "terminalName"

    def test_an_unknown_qualifier_is_not_believed(self):
        """A dotted token whose qualifier is not an offered class is not a pair."""
        client = _mock_client(
            {
                "ref_class": "HorizontalMove",
                "ref_class_confidence": 0.8,
                "column_alignments": [
                    {
                        "column": "CompanyName",
                        "ref_class": "HorizontalMove",
                        "ref_property": "Nowhere.terminalName",
                        "alignment": "semantic",
                        "confidence": 0.8,
                        "rationale": "",
                    }
                ],
            }
        )
        result = align_table(
            client,
            "gpt-5.4",
            "t",
            [{"name": "CompanyName", "data_type": "varchar(max)"}],
            [HORIZONTAL_MOVE, TERMINAL_INFRA],
        )
        assert result["column_alignments"][0]["alignment"] == "custom"
