# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""compile --all parses each ledger file and each bronze source file once (#968).

On a 15-domain hub the ledger was parsed twice per domain (30 parses of a 0.99 MB file,
36% of the run) and the same source .ttl files 187 times (17%). These pin the acceptance
criteria: once per process, re-read when the file changes, and a caller cannot corrupt
the shared value.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from kairos_ontology.core import source_disposition
from kairos_ontology.core.compiler import kernel
from kairos_ontology.core.source_disposition import load_dispositions, record_disposition


def _count_calls(monkeypatch, module, name):
    calls = {"n": 0}
    original = getattr(module, name)

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, counting)
    return calls


class TestTheLedger:
    def test_repeated_reads_parse_once(self, tmp_path, monkeypatch):
        record_disposition(hub_root=tmp_path, system="tms", table="t",
                           disposition="deferred", rationale="later")
        source_disposition._DISPOSITIONS_CACHE.clear()
        parses = _count_calls(monkeypatch, source_disposition, "_load_dispositions_uncached")

        for _ in range(5):
            load_dispositions(tmp_path)

        assert parses["n"] == 1

    def test_a_write_in_the_same_process_is_seen(self, tmp_path):
        record_disposition(hub_root=tmp_path, system="tms", table="t",
                           disposition="deferred", rationale="later")
        assert set(load_dispositions(tmp_path)) == {("tms", "t", "")}

        record_disposition(hub_root=tmp_path, system="tms", table="u",
                           disposition="deferred", rationale="later")

        assert set(load_dispositions(tmp_path)) == {("tms", "t", ""), ("tms", "u", "")}

    def test_a_caller_cannot_corrupt_the_cache(self, tmp_path):
        record_disposition(hub_root=tmp_path, system="tms", table="t",
                           disposition="deferred", rationale="later")
        first = load_dispositions(tmp_path)
        first[("tms", "t", "")]["disposition"] = "tampered"
        first[("x", "y", "")] = {}

        again = load_dispositions(tmp_path)
        assert again[("tms", "t", "")]["disposition"] == "deferred"
        assert ("x", "y", "") not in again


_SOURCE = """@prefix kb: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <https://ex.test/tms#> .
ex:orders a kb:SourceTable ; kb:tableName "orders" ; kb:sourceSystem ex:system .
ex:system rdfs:label "tms" .
ex:orders_id kb:sourceTable ex:orders ; kb:columnName "id" ; kb:dataType "string" .
"""


class TestBronzeSources:
    def test_the_same_file_is_parsed_once(self, tmp_path, monkeypatch):
        path = tmp_path / "tms.vocabulary.ttl"
        path.write_text(_SOURCE, encoding="utf-8")
        kernel._SOURCE_RELATIONS_CACHE.clear()
        parses = _count_calls(monkeypatch, kernel, "_parse_source_relations")

        first = kernel._source_relations_for_path(path)
        second = kernel._source_relations_for_path(Path(str(path)))

        assert parses["n"] == 1
        assert first is second and first[0].table_name == "orders"

    def test_a_changed_file_is_parsed_again(self, tmp_path, monkeypatch):
        path = tmp_path / "tms.vocabulary.ttl"
        path.write_text(_SOURCE, encoding="utf-8")
        kernel._SOURCE_RELATIONS_CACHE.clear()
        before = kernel._source_relations_for_path(path)

        path.write_text(_SOURCE.replace('"orders"', '"orders_v2"'), encoding="utf-8")
        stamp = time.time() + 5
        os.utime(path, (stamp, stamp))

        after = kernel._source_relations_for_path(path)
        assert before[0].table_name == "orders"
        assert after[0].table_name == "orders_v2"
