# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A join ref is checked like any other, against declared joins rather than itself (#823).

`_validate_dbt_artifacts` built its set of acceptable `ref()` targets partly *from the
content it was about to check*: a regex collected every `join ... ref('X')` in the
artifacts and added X to the known set. So a ref in a join position whitelisted itself and
could never be reported — including when the name was a typo naming nothing at all.

Measuring before deleting it turned out to matter. Across the committed scenario hubs there
are three join-position refs, and one of them — `v5-product-hub`'s `billing` joining
`party`'s `customer` model — is a **legitimate cross-domain relationship join**. It is not
in the domain's render scope and is not any binding's declared contract either, so simply
removing the exemption would have reintroduced a false positive of exactly the class #728
removed.

`JoinSpec.referenced_model` already carries the joined model as structured data, which
answers the same question without the circularity: a join the project actually declares is
known, a string that merely appears in a join position is not.
"""

from __future__ import annotations

import logging
import pathlib

import pytest

from kairos_ontology.core.compiler import CompileMode, compile_domain
from kairos_ontology.core.projections.dbt.render import (
    _declared_join_models,
    _validate_dbt_artifacts,
)

_SCENARIOS = pathlib.Path(__file__).parent / "scenarios"


def test_a_typo_in_a_join_position_is_reported(caplog):
    """The defect: this was the one place a dangling ref could hide completely."""
    artifacts = {
        "models/silver/party/customer.sql": (
            "select * from {{ ref('customer_stage') }}\n"
            "left join {{ ref('tpyo_no_such_model') }} using (id)\n"
        )
    }

    with caplog.at_level(logging.WARNING):
        _validate_dbt_artifacts(
            artifacts, known_models={"customer_stage"}, join_models=set()
        )

    assert "tpyo_no_such_model" in caplog.text
    # ...and the legitimate ref beside it stays quiet.
    assert "ref('customer_stage')" not in caplog.text


def test_a_declared_join_target_is_accepted(caplog):
    """The case the old exemption existed to protect, now expressed precisely."""
    artifacts = {
        "models/silver/billing/invoice.sql": (
            "select * from {{ ref('invoice_stage') }}\n"
            "left join {{ ref('customer') }} as customer using (customer_id)\n"
        )
    }

    with caplog.at_level(logging.WARNING):
        _validate_dbt_artifacts(
            artifacts, known_models={"invoice_stage"}, join_models={"customer"}
        )

    assert "matched no model" not in caplog.text


def test_declaring_one_join_does_not_excuse_another(caplog):
    """The exemption is per declared target, so it cannot become a blanket opt-out for
    anything that happens to sit in a join position."""
    artifacts = {
        "models/silver/billing/invoice.sql": (
            "select * from {{ ref('invoice_stage') }}\n"
            "left join {{ ref('customer') }} using (customer_id)\n"
            "left join {{ ref('typo_here') }} using (other_id)\n"
        )
    }

    with caplog.at_level(logging.WARNING):
        _validate_dbt_artifacts(
            artifacts, known_models={"invoice_stage"}, join_models={"customer"}
        )

    assert "typo_here" in caplog.text
    assert "ref('customer')" not in caplog.text


class TestAgainstRealProjects:
    """The measurement that decided the shape of this fix, kept as a regression."""

    def test_the_cross_domain_join_is_declared_not_guessed(self):
        from kairos_ontology.core.compiler.kernel import build_compile_plan

        plan = build_compile_plan(_SCENARIOS / "v5-product-hub", "billing")
        assert _declared_join_models(plan.shaped_project) == {"customer"}

    @pytest.mark.parametrize(
        ("hub", "domain"),
        [("v5-product-hub", "billing"), ("v5-product-hub", "party"), ("v5-hub", "party")],
    )
    def test_a_real_emit_produces_no_ref_scan_warning(self, hub, domain, caplog):
        """Zero false positives across every committed hub that emits a join.

        `billing` is the one that matters: it joins `party`'s `customer` across a domain
        boundary, which is neither in its render scope nor a declared contract.
        """
        with caplog.at_level(logging.WARNING):
            result = compile_domain(_SCENARIOS / hub, domain, CompileMode.EMIT)

        assert result.succeeded
        assert "matched no model" not in caplog.text
