# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-189 Stage-0 profiling: tags, maturity gate, privacy, outline annotation."""

from __future__ import annotations

import pytest

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402

from kairos_ontology.core.profile_sources import (  # noqa: E402
    annotate_outline,
    load_profile,
    profile_table,
    read_data_maturity,
    run_profile_sources,
)

SECRET = "ACME-SECRET-VALUE-42"


@pytest.fixture()
def import_dir(tmp_path):
    """A tiny two-table estate exercising every tag family."""
    d = tmp_path / ".import" / "sources" / "erp"
    d.mkdir(parents=True)
    n = 40
    orders = pa.table(
        {
            "order_id": list(range(n)),                          # unique
            "customer_id": [i % 5 for i in range(n)],            # low-card + fk?
            "tenant_id": [7] * n,                                # const
            "notes": [None] * n,                                 # empty (nulls)
            "blank": [""] * n,                                   # empty (blank strings)
            "amount": [float(i) * 1.5 for i in range(n)],        # measure-like
            "status": [("OPEN", "DONE")[i % 2] for i in range(n)],  # code-like
            "secret_ref": [SECRET] * n,                          # const; value must not leak
            "updated_at": ["2026-01-01T00:00"] * n,              # version-ish column name
        }
    )
    customers = pa.table(
        {"customer_id": [0, 1, 2, 3, 4], "code": ["A", "B", "C", "D", "E"]}
    )
    empty = pa.table({"x": pa.array([], type=pa.int64())})
    pq.write_table(orders, d / "orders.parquet")
    pq.write_table(customers, d / "customers.parquet")
    pq.write_table(empty, d / "ghost.parquet")
    return d


def _profile(import_dir, tmp_path, maturity="production"):
    out_dir = tmp_path / "hub" / "integration" / "sources" / "erp"
    run_profile_sources(import_dir, "erp", out_dir, data_maturity=maturity)
    return out_dir.parent, load_profile(out_dir.parent, "erp")


def test_column_tags_cover_every_family(import_dir, tmp_path):
    _, profile = _profile(import_dir, tmp_path)
    cols = profile["tables"]["orders"]["columns"]
    assert "unique" in cols["order_id"]["tags"]
    assert "const" in cols["tenant_id"]["tags"]
    assert "empty" in cols["notes"]["tags"]
    assert "empty" in cols["blank"]["tags"], "blank strings count as empty"
    assert "measure-like" in cols["amount"]["tags"]
    assert any(t.startswith("low-card(") for t in cols["customer_id"]["tags"])
    assert "fk?->customers.customer_id" in cols["customer_id"]["tags"]


def test_table_tags(import_dir, tmp_path):
    _, profile = _profile(import_dir, tmp_path)
    assert "empty-table" in profile["tables"]["ghost"]["table_tags"]
    # updated_at + a non-unique *_id column → versioned? caution
    assert "versioned?" in profile["tables"]["orders"]["table_tags"]
    assert profile["basis"] == "import-extract(full)"


def test_no_raw_values_in_artifact(import_dir, tmp_path):
    sources_dir, _ = _profile(import_dir, tmp_path)
    text = (sources_dir / "erp" / "erp.profile.yaml").read_text(encoding="utf-8")
    assert SECRET not in text, "profile artifact must carry statistics, never values"


def test_outline_annotation_and_production_gate(import_dir, tmp_path):
    sources_dir, _ = _profile(import_dir, tmp_path, maturity="production")
    outline = [("erp", "orders", ["order_id", "customer_id", "notes"]),
               ("other", "t", ["a"])]
    annotated, found = annotate_outline(outline, sources_dir)
    assert found
    cols = annotated[0][2]
    assert any(c.startswith("order_id[") and "unique" in c for c in cols)
    assert not any(c.startswith("notes") for c in cols), "empty column dropped"
    assert annotated[1] == ("other", "t", ["a"]), "unprofiled system untouched"


def test_test_maturity_never_excludes(import_dir, tmp_path):
    sources_dir, profile = _profile(import_dir, tmp_path, maturity="test")
    assert profile["data_maturity"] == "test"
    annotated, _ = annotate_outline(
        [("erp", "orders", ["order_id", "notes"])], sources_dir
    )
    assert any(c.startswith("notes[") for c in annotated[0][2]), (
        "under test maturity the empty tag is advisory — nothing excluded"
    )


def test_unique_timezone_aware_timestamp_column_does_not_crash(tmp_path):
    """Regression: frachtv5 CargoWise extract, a unique tz-aware timestamp
    column. `to_pylist()` on a tz-aware timestamp needs a tz database, which
    is not guaranteed present (ArrowInvalid on a bare Windows Python without
    `tzdata`) -- and a timestamp was never a useful FK key-set candidate
    regardless, so it must be excluded from key-set construction, not merely
    have the crash suppressed."""
    import datetime as dt

    n = 5
    table = pa.table({
        "id": list(range(n)),
        "created_utc": pa.array(
            [dt.datetime(2026, 1, i + 1, tzinfo=dt.timezone.utc) for i in range(n)],
            type=pa.timestamp("us", tz="UTC"),
        ),
    })
    d = tmp_path / ".import" / "sources" / "tz"
    d.mkdir(parents=True)
    pq.write_table(table, d / "events.parquet")
    prof, key_sets = profile_table(d / "events.parquet")
    assert "unique" in prof["columns"]["created_utc"]["tags"]
    assert "created_utc" not in key_sets, (
        "a unique temporal column must never enter key-set candidacy"
    )
    assert "id" in key_sets


def test_read_data_maturity(tmp_path):
    assert read_data_maturity(None) == "unspecified"
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "kairos.yaml").write_text("data_maturity: production\n", encoding="utf-8")
    assert read_data_maturity(hub) == "production"
    (hub / "kairos.yaml").write_text("data_maturity: staging\n", encoding="utf-8")
    assert read_data_maturity(hub) == "unspecified", "unknown values never guess"


def test_artifact_is_deterministic(import_dir, tmp_path):
    d1, _ = _profile(import_dir, tmp_path / "a")
    d2, _ = _profile(import_dir, tmp_path / "b")
    t1 = (d1 / "erp" / "erp.profile.yaml").read_text(encoding="utf-8")
    t2 = (d2 / "erp" / "erp.profile.yaml").read_text(encoding="utf-8")
    assert t1 == t2


def test_prompt_legend_wiring():
    from kairos_ontology.core.anchor_tables import build_anchor_prompt
    from kairos_ontology.core.anchor_tables import ClassCatalog

    catalog = ClassCatalog(text="- Thing [UNOWNED]: a thing", index={}, owners={},
                           bridged_from={})
    chunk = [("erp", "orders", ["order_id[unique]"])]
    with_legend = build_anchor_prompt(chunk, catalog, 1, profile_legend="LEGEND-MARK")
    without = build_anchor_prompt(chunk, catalog, 1)
    assert "LEGEND-MARK" in with_legend
    assert "LEGEND-MARK" not in without
