# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Status-scan awareness of aspirational stubs (DD-096 D4).

`kairos-ontology status` must distinguish *stub* from *bound* by running the
canonical BindingAnalysis over the hub's authorities (Claim Registry + graph +
sources + mappings), not by reading generated `meta.is_aspirational`. A silver
domain with an approved-but-unbound claim is therefore *in-progress* (aspirational
stub pending binding), not `done`.
"""

from kairos_ontology.core.status import (
    STATE_DONE,
    STATE_IN_PROGRESS,
    _domain_aspirational_stubs,
    scan_hub_status,
)

from .test_scenario_release_gate import _build_hub


def _silver_instance(hub, domain="widget"):
    status = scan_hub_status(hub)
    silver = status.phase("silver")
    return silver, next((i for i in silver.instances if i.name == domain), None)


def test_helper_reports_unbound_eligible_class(tmp_path):
    hub = _build_hub(tmp_path, with_claims=True)
    assert _domain_aspirational_stubs(hub, "widget") == ["Widget"]


def test_silver_in_progress_when_aspirational_stub_pending(tmp_path):
    hub = _build_hub(tmp_path, with_claims=True)
    silver, inst = _silver_instance(hub)
    assert inst is not None
    assert inst.state == STATE_IN_PROGRESS
    assert "pending binding" in inst.detail
    assert "Widget" in inst.detail
    assert silver.state == STATE_IN_PROGRESS


def test_silver_done_without_claims_authority(tmp_path):
    """No claims registry → no eligibility authority → silver stays done."""
    hub = _build_hub(tmp_path, with_claims=False)
    silver, inst = _silver_instance(hub)
    assert inst is not None
    assert inst.state == STATE_DONE
    assert _domain_aspirational_stubs(hub, "widget") == []
