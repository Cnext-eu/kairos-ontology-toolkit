# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Graph-aware alignment: role structure and relational consistency (DD-179).

A flat table hides its relationships in its naming. ``shipper_code``,
``shipper_name``, ``consignee_code``, ``consignee_name`` is not four unrelated
columns — it is two references to the same kind of entity in different roles,
and that is the strongest available signal for choosing between two object
properties with the same range.

Grouping is conservative on purpose. A false group asserts a relationship the
data does not have, which is worse than no grouping at all, so most of these
tests are about what must *not* be grouped.
"""

import pytest

from kairos_ontology.core.propose_alignment import (
    FLAG_ROLE_COLLISION,
    flag_role_collisions,
    format_role_structure,
    group_columns_by_role,
)


def cols(*names):
    return [{"name": n, "data_type": "varchar"} for n in names]


class TestRoleGrouping:
    def test_the_canonical_shipment_case(self):
        groups, ungrouped = group_columns_by_role(
            cols(
                "shipper_code",
                "shipper_name",
                "consignee_code",
                "consignee_name",
                "origin",
                "destination",
            )
        )
        assert {t for t, _ in groups} == {"shipper", "consignee"}
        for _, members in groups:
            assert len(members) == 2
        assert [c["name"] for c in ungrouped] == ["origin", "destination"]

    def test_a_single_column_is_not_a_role(self):
        groups, ungrouped = group_columns_by_role(cols("shipper_code", "origin"))
        assert groups == []
        assert len(ungrouped) == 2

    def test_the_table_subject_is_not_a_role(self):
        """On a customers table, half the columns start with 'customer'."""
        groups, _ = group_columns_by_role(
            cols("customer_id", "customer_name", "customer_code", "region")
        )
        assert groups == [], "the dominant prefix is the subject, not a related entity"

    def test_a_minority_prefix_still_groups_in_a_wide_table(self):
        columns = cols(
            "shipper_code", "shipper_name", *[f"other_{i}" for i in range(10)]
        )
        groups, _ = group_columns_by_role(columns)
        assert "shipper" in {t for t, _ in groups}

    @pytest.mark.parametrize(
        "names",
        [
            ("is_active", "is_archived"),
            ("created_at", "created_by"),
            ("total_weight", "total_volume"),
            ("date_from", "date_to"),
        ],
    )
    def test_structural_prefixes_are_never_roles(self, names):
        groups, _ = group_columns_by_role(cols(*names))
        assert groups == [], f"{names[0].split('_')[0]!r} is not an entity role"

    def test_camel_case_is_tokenized(self):
        groups, _ = group_columns_by_role(cols("ShipperCode", "ShipperName", "Origin"))
        assert {t for t, _ in groups} == {"shipper"}

    def test_grouping_is_order_deterministic(self):
        """Output order follows input order, which DD-175 already made stable."""
        columns = cols("shipper_code", "shipper_name", "consignee_code", "consignee_name")
        first = [(t, [c["name"] for c in m]) for t, m in group_columns_by_role(columns)[0]]
        second = [(t, [c["name"] for c in m]) for t, m in group_columns_by_role(columns)[0]]
        assert first == second

    def test_empty_and_nameless_input(self):
        assert group_columns_by_role([]) == ([], [])
        groups, ungrouped = group_columns_by_role([{"name": ""}, {"name": ""}])
        assert groups == []
        assert len(ungrouped) == 2


class TestPromptRendering:
    def test_renders_groups_and_the_disambiguation_rule(self):
        text = format_role_structure(
            cols("shipper_code", "shipper_name", "consignee_code", "consignee_name")
        )
        assert 'ROLE "shipper" (2 columns): shipper_code, shipper_name' in text
        assert 'ROLE "consignee"' in text
        assert "must NOT map to" in text, "the rule is what makes the grouping actionable"

    def test_empty_when_no_role_found_so_prompt_is_unchanged(self):
        """A table without this shape must send a byte-identical prompt to before."""
        assert format_role_structure(cols("id", "region", "notes")) == ""

    def test_ungrouped_columns_are_still_listed(self):
        text = format_role_structure(
            cols("shipper_code", "shipper_name", "origin", "destination")
        )
        assert "no role group: origin, destination" in text


class TestRoleCollisionGuard:
    def test_flags_two_roles_on_one_property(self):
        columns = cols("shipper_code", "shipper_name", "consignee_code", "consignee_name")
        flags = flag_role_collisions(
            columns,
            [
                {"column": "shipper_code", "ref_property": "hasShipper"},
                {"column": "consignee_code", "ref_property": "hasShipper"},
            ],
        )
        assert len(flags) == 1
        assert FLAG_ROLE_COLLISION in flags[0]
        assert "hasShipper" in flags[0]
        assert "consignee" in flags[0] and "shipper" in flags[0]

    def test_silent_when_roles_map_distinctly(self):
        columns = cols("shipper_code", "shipper_name", "consignee_code", "consignee_name")
        assert (
            flag_role_collisions(
                columns,
                [
                    {"column": "shipper_code", "ref_property": "hasShipper"},
                    {"column": "consignee_code", "ref_property": "hasConsignee"},
                ],
            )
            == []
        )

    def test_same_role_reusing_a_property_is_not_a_collision(self):
        """Two columns of one role sharing a property is normal, not a conflict."""
        columns = cols("shipper_code", "shipper_name", "consignee_code", "consignee_name")
        assert (
            flag_role_collisions(
                columns,
                [
                    {"column": "shipper_code", "ref_property": "hasShipper"},
                    {"column": "shipper_name", "ref_property": "hasShipper"},
                ],
            )
            == []
        )

    def test_unmapped_columns_are_ignored(self):
        columns = cols("shipper_code", "shipper_name", "consignee_code", "consignee_name")
        assert (
            flag_role_collisions(
                columns,
                [
                    {"column": "shipper_code", "ref_property": None},
                    {"column": "consignee_code", "ref_property": None},
                ],
            )
            == []
        )

    def test_no_flag_without_at_least_two_roles(self):
        assert flag_role_collisions(cols("a", "b"), [{"column": "a", "ref_property": "p"}]) == []

    def test_malformed_entries_do_not_raise(self):
        columns = cols("shipper_code", "shipper_name", "consignee_code", "consignee_name")
        flag_role_collisions(columns, [None, "junk", {}, {"column": "shipper_code"}])

    def test_flags_are_ordered_reproducibly(self):
        columns = cols(
            "shipper_code", "shipper_name", "consignee_code", "consignee_name",
            "notify_code", "notify_name",
        )
        alignments = [
            {"column": "shipper_code", "ref_property": "hasParty"},
            {"column": "consignee_code", "ref_property": "hasParty"},
            {"column": "notify_code", "ref_property": "hasContact"},
            {"column": "notify_name", "ref_property": "hasContact"},
        ]
        assert flag_role_collisions(columns, alignments) == flag_role_collisions(
            columns, alignments
        )


class TestEntityReferenceRequirement:
    """Precision: a shared prefix alone is not a role (found on the live corpus)."""

    @pytest.mark.parametrize(
        "names,reason",
        [
            (("ActualDate", "ActualTimeFrom", "ActualTimeUpTo"), "temporal qualifier"),
            (("KmLoadingTotal", "KmUnloadingTotal"), "unit prefix on two measures"),
            (("CoordinateLatitude", "CoordinateLongitude"), "value object, not a reference"),
            (("NetWeight", "NetVolume"), "qualifier on two measures"),
        ],
    )
    def test_prefix_without_an_entity_reference_is_not_a_role(self, names, reason):
        groups, ungrouped = group_columns_by_role(cols(*names))
        assert groups == [], f"grouped a {reason}"
        assert len(ungrouped) == len(names)

    @pytest.mark.parametrize(
        "names",
        [
            ("shipper_code", "shipper_name"),
            ("consignee_id", "consignee_description"),
            ("haulier_key", "haulier_ref"),
            ("SupplierNumber", "SupplierLabel"),
        ],
    )
    def test_entity_references_still_group(self, names):
        groups, _ = group_columns_by_role(cols(*names))
        assert len(groups) == 1, f"{names} is an entity referenced twice"

    def test_one_qualifying_member_carries_the_group(self):
        """A role's other columns need not themselves be identifiers."""
        groups, _ = group_columns_by_role(
            cols(
                "shipper_name",
                "shipper_country",
                "shipper_since",
                "order_no",
                "weight",
                "volume",
            )
        )
        assert len(groups) == 1
        assert len(groups[0][1]) == 3, "all members of a qualifying role stay together"

    def test_a_prefix_covering_the_whole_table_is_still_the_subject(self):
        """Even with an identifier present: 3 of 3 columns is not a *related* entity."""
        assert group_columns_by_role(
            cols("shipper_name", "shipper_country", "shipper_since")
        ) == ([], cols("shipper_name", "shipper_country", "shipper_since"))
