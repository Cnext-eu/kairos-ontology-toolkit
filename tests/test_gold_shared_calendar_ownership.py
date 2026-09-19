# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`models/gold/shared/` belongs to the hub, not to whichever domain compiled it (#849).

An approved calendar renders to `models/gold/shared/dim_date.sql` -- deliberately outside
the declaring domain's tree, because one hub materializes one governed calendar. But
`_is_shared_artifact` did not recognise the subtree, so those files were claimed by the
per-domain manifest. The second domain in a hub to author an approved calendar therefore
could not compile into the same target **at all**:

    ArtifactCollisionError: artifact destination collides with an unowned path:
    'models/gold/shared/_shared__gold_models.yml'

-- naming a path the author never wrote, and with no hint that two calendars were the
cause.

Moving the subtree to the shared manifest fixes the collision but raises the question it
was hiding: what if the two domains genuinely disagree? Measured on the fixture below,
two domains declaring the same bounds render a **byte-identical** `dim_date.sql` and
differ only in which profile URI is recorded as provenance. That is one table with two
contributors, not a conflict. Different bounds are a conflict, and reconciling those
silently would be worse than the collision this replaces -- so they still fail, now
naming the field that disagrees.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.projections.dbt.gold_shared import (
    SHARED_GOLD_MODELS_PATH,
    SharedGoldUnionError,
    is_shared_gold_artifact,
    union_shared_gold_artifact,
)

_PRODUCT_HUB = Path(__file__).parent / "scenarios" / "v5-product-hub"

_PARTY_GOLD = """
@prefix party: <https://example.test/ontology/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://example.test/ontology/party>
  kairos-ext:goldSchema "gold_party" ;
  kairos-ext:goldProductProfile "dimensional-powerbi-v1" ;
  kairos-ext:calendarProfile party:PartyCalendar .

party:PartyCalendar a kairos-ext:CalendarProfile ;
  kairos-ext:calendarStartDate "2020-01-01"^^xsd:date ;
  kairos-ext:calendarEndDate "__PARTY_END__"^^xsd:date ;
  kairos-ext:fiscalYearStartMonth 1 ;
  kairos-ext:weekPattern "iso-8601-monday" ;
  kairos-ext:calendarLocale "en-BE" ;
  kairos-ext:holidaySource "none-approved" ;
  kairos-ext:calendarTimeZone "Europe/Brussels" ;
  kairos-ext:periodClosurePolicy "finance-approved-period-status" ;
  kairos-ext:rolePlayingDate "SignupDate=dim_customer.signed_up_on" ;
  kairos-ext:calendarApprovalStatus "approved" .

party:Customer
  kairos-ext:goldTableType "dimension" ;
  kairos-ext:goldTableName "dim_customer" ;
  kairos-ext:goldSourceModel "customer" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:dimensionExposure "current-only" ;
  kairos-ext:dimensionVersionBinding "current" .
"""

_BILLING_GOLD = """
@prefix billing: <https://example.test/ontology/billing#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://example.test/ontology/billing>
  kairos-ext:goldSchema "gold_billing" ;
  kairos-ext:goldProductProfile "dimensional-powerbi-v1" ;
  kairos-ext:calendarProfile billing:BillingCalendar .

billing:BillingCalendar a kairos-ext:CalendarProfile ;
  kairos-ext:calendarStartDate "2020-01-01"^^xsd:date ;
  kairos-ext:calendarEndDate "2035-12-31"^^xsd:date ;
  kairos-ext:fiscalYearStartMonth 1 ;
  kairos-ext:weekPattern "iso-8601-monday" ;
  kairos-ext:calendarLocale "en-BE" ;
  kairos-ext:holidaySource "none-approved" ;
  kairos-ext:calendarTimeZone "Europe/Brussels" ;
  kairos-ext:periodClosurePolicy "finance-approved-period-status" ;
  kairos-ext:rolePlayingDate "InvoiceDate=fact_invoice.invoice_date" ;
  kairos-ext:calendarApprovalStatus "approved" .

billing:Invoice
  kairos-ext:goldTableType "fact" ;
  kairos-ext:goldTableName "fact_invoice" ;
  kairos-ext:goldSourceModel "invoice" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:factGrain "one row per invoice" ;
  kairos-ext:factType "transaction" ;
  kairos-ext:dimensionVersionBinding "current" .
"""

_PARTY_PROFILE = "https://example.test/ontology/party#PartyCalendar"
_BILLING_PROFILE = "https://example.test/ontology/billing#BillingCalendar"


def _hub(tmp_path: Path, *, party_end: str = "2035-12-31") -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_PRODUCT_HUB, hub)
    extensions = hub / "model" / "extensions"
    extensions.mkdir(parents=True, exist_ok=True)
    (extensions / "party-gold-ext.ttl").write_text(
        _PARTY_GOLD.replace("__PARTY_END__", party_end), encoding="utf-8"
    )
    (extensions / "billing-gold-ext.ttl").write_text(_BILLING_GOLD, encoding="utf-8")
    return hub


def _compile(hub: Path, domain: str, monkeypatch):
    monkeypatch.chdir(hub)
    return CliRunner().invoke(cli, ["compile", domain, "--emit", "--confirm-emit"])


def _dbt(hub: Path) -> Path:
    return hub.parent / "ontology-hub-publish" / "medallion" / "dbt"


def _shared_models(hub: Path) -> dict:
    path = _dbt(hub).joinpath(*SHARED_GOLD_MODELS_PATH.split("/"))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _meta(hub: Path) -> dict:
    return _shared_models(hub)["models"][0]["meta"]


class TestTwoCalendarDomainsInOneTarget:
    """The reported blocker, end to end."""

    def test_the_second_calendar_domain_can_compile(self, tmp_path, monkeypatch):
        hub = _hub(tmp_path)

        assert _compile(hub, "party", monkeypatch).exit_code == 0
        result = _compile(hub, "billing", monkeypatch)

        assert result.exit_code == 0, result.output
        assert _dbt(hub).joinpath("models", "gold", "shared", "dim_date.sql").is_file()

    def test_both_contributing_profiles_are_recorded(self, tmp_path, monkeypatch):
        """Whichever domain compiled last used to be the only one named."""
        hub = _hub(tmp_path)
        _compile(hub, "party", monkeypatch)
        _compile(hub, "billing", monkeypatch)

        assert _meta(hub)["calendar_profile"] == sorted([_PARTY_PROFILE, _BILLING_PROFILE])

    def test_the_shared_subtree_is_owned_by_the_shared_manifest(self, tmp_path, monkeypatch):
        """The ownership change itself: a per-domain manifest must no longer claim it."""
        hub = _hub(tmp_path)
        _compile(hub, "party", monkeypatch)

        import json

        owners = {
            manifest.name: {entry["path"] for entry in json.loads(manifest.read_text())["files"]}
            for manifest in _dbt(hub).glob(".kairos-compile-manifest.*.json")
        }
        shared_paths = {
            path for paths in owners.values() for path in paths if is_shared_gold_artifact(path)
        }
        assert shared_paths, "the fixture emitted no shared Gold artifacts; the test proves nothing"
        assert shared_paths <= owners[".kairos-compile-manifest.shared.json"]
        assert not shared_paths & owners[".kairos-compile-manifest.party.json"]

    def test_recompiling_one_domain_keeps_the_other_s_contribution(self, tmp_path, monkeypatch):
        """Every domain writes the shared manifest, so stale-removal would drop the
        calendar the moment a domain re-emitted without re-reading it."""
        hub = _hub(tmp_path)
        _compile(hub, "party", monkeypatch)
        _compile(hub, "billing", monkeypatch)

        assert _compile(hub, "party", monkeypatch).exit_code == 0

        assert _dbt(hub).joinpath("models", "gold", "shared", "dim_date.sql").is_file()
        assert _meta(hub)["calendar_profile"] == sorted([_PARTY_PROFILE, _BILLING_PROFILE])

    def test_a_repeated_compile_is_idempotent(self, tmp_path, monkeypatch):
        hub = _hub(tmp_path)
        _compile(hub, "party", monkeypatch)
        _compile(hub, "billing", monkeypatch)
        before = _shared_models(hub)

        _compile(hub, "billing", monkeypatch)

        assert _shared_models(hub) == before


class TestOneCalendarIsUnchanged:
    def test_a_single_contributor_keeps_a_scalar_profile(self, tmp_path, monkeypatch):
        """Every hub shipping today has one calendar-bearing domain; its bytes must not
        move. The union only runs against a file already on disk, so compiling one domain
        must leave the scalar the renderer wrote."""
        hub = _hub(tmp_path)
        _compile(hub, "billing", monkeypatch)

        assert _meta(hub)["calendar_profile"] == _BILLING_PROFILE


class TestGenuineDisagreement:
    def test_a_sole_contributor_can_change_its_own_calendar(self, tmp_path, monkeypatch):
        """Extending `calendar_end` is yearly maintenance, and a toolkit upgrade that
        renders more calendar columns re-emits changed bytes on every calendar hub. Both
        read the domain's own previous output back as a second contributor and failed
        closed -- naming "two domains" that were one, with `models/gold/shared/` deletion
        as the only recovery."""
        hub = _hub(tmp_path)
        assert _compile(hub, "party", monkeypatch).exit_code == 0
        dim_date = _dbt(hub).joinpath("models", "gold", "shared", "dim_date.sql")
        before = dim_date.read_text(encoding="utf-8")

        (hub / "model" / "extensions" / "party-gold-ext.ttl").write_text(
            _PARTY_GOLD.replace("__PARTY_END__", "2036-12-31"), encoding="utf-8"
        )
        result = _compile(hub, "party", monkeypatch)

        assert result.exit_code == 0, str(result.exception) or result.output
        assert _meta(hub)["calendar_end"] == "2036-12-31"
        assert _meta(hub)["calendar_profile"] == _PARTY_PROFILE
        # The model SQL is superseded along with the schema yml, not unioned against.
        assert dim_date.read_text(encoding="utf-8") != before

    def test_a_second_contributor_still_blocks_a_unilateral_change(self, tmp_path, monkeypatch):
        """Ownership is decided from the schema yml's recorded profiles: once billing has
        also contributed, party changing the bounds alone is a real disagreement."""
        hub = _hub(tmp_path)
        assert _compile(hub, "party", monkeypatch).exit_code == 0
        assert _compile(hub, "billing", monkeypatch).exit_code == 0

        (hub / "model" / "extensions" / "party-gold-ext.ttl").write_text(
            _PARTY_GOLD.replace("__PARTY_END__", "2036-12-31"), encoding="utf-8"
        )
        result = _compile(hub, "party", monkeypatch)

        assert result.exit_code != 0
        message = str(result.exception) if result.exception else result.output
        assert "calendar_end" in message
        assert _meta(hub)["calendar_end"] == "2035-12-31"

    def test_different_bounds_still_fail(self, tmp_path, monkeypatch):
        """Sharing the subtree must not turn a real conflict into last-writer-wins: two
        bounds is one physical table with two incompatible definitions."""
        hub = _hub(tmp_path, party_end="2030-12-31")
        assert _compile(hub, "party", monkeypatch).exit_code == 0

        result = _compile(hub, "billing", monkeypatch)

        assert result.exit_code != 0
        message = str(result.exception) if result.exception else result.output
        assert "2030-12-31" in message and "2035-12-31" in message
        assert "calendar_end" in message

    def test_nothing_is_written_when_the_union_fails(self, tmp_path, monkeypatch):
        """Preflight ordering: the first domain's calendar survives the second's failure."""
        hub = _hub(tmp_path, party_end="2030-12-31")
        _compile(hub, "party", monkeypatch)

        _compile(hub, "billing", monkeypatch)

        assert _meta(hub)["calendar_profile"] == _PARTY_PROFILE
        assert _meta(hub)["calendar_end"] == "2030-12-31"


class TestUnion:
    """`union_shared_gold_artifact` directly, for the cases the fixture cannot reach."""

    @staticmethod
    def _models(profile: str, **meta) -> str:
        return yaml.safe_dump(
            {
                "version": 2,
                "models": [
                    {
                        "name": "dim_date",
                        "description": "Approved governed calendar dimension.",
                        "meta": {
                            "calendar_profile": profile,
                            "calendar_approved": True,
                            "calendar_start": "2020-01-01",
                            "calendar_end": "2035-12-31",
                            **meta,
                        },
                        "columns": [{"name": "date_key"}],
                    }
                ],
            }
        )

    def test_identical_bytes_are_returned_unchanged(self):
        document = self._models(_PARTY_PROFILE)
        assert union_shared_gold_artifact(SHARED_GOLD_MODELS_PATH, document, document) is document

    def test_a_third_contributor_joins_the_existing_list(self):
        """A hub is not limited to two calendar-bearing domains, and the union runs
        pairwise against whatever is already on disk."""
        merged = union_shared_gold_artifact(
            SHARED_GOLD_MODELS_PATH,
            yaml.safe_dump(
                yaml.safe_load(self._models("x"))
                | {
                    "models": [
                        {
                            **yaml.safe_load(self._models("x"))["models"][0],
                            "meta": {
                                **yaml.safe_load(self._models("x"))["models"][0]["meta"],
                                "calendar_profile": [_PARTY_PROFILE, _BILLING_PROFILE],
                            },
                        }
                    ]
                }
            ),
            self._models("https://example.test/ontology/ops#OpsCalendar"),
        )
        assert yaml.safe_load(merged)["models"][0]["meta"]["calendar_profile"] == sorted(
            [_PARTY_PROFILE, _BILLING_PROFILE, "https://example.test/ontology/ops#OpsCalendar"]
        )

    def test_a_differing_model_sql_is_a_conflict(self):
        """Nothing but the schema yml carries per-domain provenance, so for the model SQL
        any difference at all is a disagreement about what gets built."""
        with pytest.raises(SharedGoldUnionError) as excinfo:
            union_shared_gold_artifact(
                "models/gold/shared/dim_date.sql", "select 1", "select 2"
            )
        assert "materialized once" in str(excinfo.value)

    def test_a_model_only_the_previous_domain_declared_is_kept(self):
        """The union is also what stops the shared manifest's stale-removal from
        deleting a table this run does not render."""
        previous = yaml.safe_load(self._models(_PARTY_PROFILE))
        previous["models"].append({"name": "dim_fiscal_period", "meta": {}})
        merged = union_shared_gold_artifact(
            SHARED_GOLD_MODELS_PATH,
            yaml.safe_dump(previous),
            self._models(_BILLING_PROFILE),
        )
        assert [item["name"] for item in yaml.safe_load(merged)["models"]] == [
            "dim_date",
            "dim_fiscal_period",
        ]

    def test_a_differing_column_set_is_a_conflict(self):
        other = yaml.safe_load(self._models(_BILLING_PROFILE))
        other["models"][0]["columns"] = [{"name": "date_key"}, {"name": "week_number"}]
        with pytest.raises(SharedGoldUnionError) as excinfo:
            union_shared_gold_artifact(
                SHARED_GOLD_MODELS_PATH, self._models(_PARTY_PROFILE), yaml.safe_dump(other)
            )
        assert "columns" in str(excinfo.value)
