# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The emitted `require-dbt-version` has to satisfy dbt's parser, not pip's (#888).

`require-dbt-version` is read by dbt's own semver implementation, which requires all
three version components. A two-part `>=1.10` is a perfectly good pip specifier and an
invalid dbt one, and dbt rejects the entire project file on it before reading anything
else -- so every emitted medallion project failed at `dbt deps`.
"""

import re

import pytest

from kairos_ontology.core.adapters import DBT_CORE_FLOOR, DBT_CORE_REQUIREMENT

_THREE_PART = re.compile(r"^(?:[<>=!~^]+)?\d+\.\d+\.\d+")


def _specifiers(requirement: str) -> list[str]:
    return [part.strip() for part in requirement.split(",") if part.strip()]


class TestDbtVersionSpecifiers:
    def test_the_emitted_floor_is_a_three_part_version(self):
        assert _THREE_PART.match(DBT_CORE_FLOOR), (
            f"{DBT_CORE_FLOOR!r} omits the patch component; dbt's semver rejects it"
        )

    def test_every_scaffolded_requirement_specifier_is_three_part(self):
        for specifier in _specifiers(DBT_CORE_REQUIREMENT):
            assert _THREE_PART.match(specifier), f"{specifier!r} in DBT_CORE_REQUIREMENT"

    def test_dbt_itself_accepts_the_emitted_floor(self):
        """The authority is dbt's parser; the regex above is only a fast proxy for it."""
        parse = pytest.importorskip("dbt.config.project")._parse_versions

        assert parse(DBT_CORE_FLOOR)

    def test_dbt_rejects_the_two_part_spelling_this_guards_against(self):
        parse = pytest.importorskip("dbt.config.project")._parse_versions

        with pytest.raises(Exception, match="not a valid semantic version"):
            parse(">=1.10")
