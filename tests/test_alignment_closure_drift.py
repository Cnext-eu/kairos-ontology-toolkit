# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""An alignment stale against its domain's import closure is now reported (#518).

A `<domain>-alignment.yaml` records the `domain_uris` it was generated against, and
nothing compared them to anything. When the closure later widened — a reference-models
upgrade, a blueprint change, a bridge being added — the file was silently stale and
downstream stages consumed it as current.

The failure is invisible *and points the wrong way*. What surfaces is
`integrity.managed-import-unused`: "this domain imports a module and references nothing
from it", which reads as a **sourcing** gap ("we have no data for this") when the cause is
a **staleness** gap ("we never looked"). On a hub using those warnings as a sourcing
backlog (DD-187), a stale file corrupts the backlog.

Reported on the two domains in the issue: `equipment`, whose closure gained
`dcsa/container-operations` and a whole container lifecycle no proposal references; and
`terminal-operations`, whose alignment predates `tic/reefer-monitoring`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from kairos_ontology.core.alignment_closure import (
    closure_fingerprint,
    detect_closure_drift,
)

_WAS = ["https://ref.test/mmt/equipment", "https://ref.test/dcsa/equipment"]
_NOW = _WAS + ["https://ref.test/dcsa/container-operations"]


def _artifact(tmp_path: Path, uris=_WAS, *, domain: str = "equipment") -> Path:
    path = tmp_path / f"{domain}-alignment.yaml"
    path.write_text(
        yaml.safe_dump({"domain": domain, "domain_uris": list(uris), "tables": []}),
        encoding="utf-8",
    )
    return path


class TestFingerprint:
    def test_order_and_trailing_separators_do_not_count_as_drift(self):
        """A cosmetic difference reported as drift would train readers to ignore it."""
        assert closure_fingerprint(_WAS) == closure_fingerprint(
            [f"{_WAS[1]}#", f"{_WAS[0]}/"]
        )

    def test_a_real_difference_changes_the_digest(self):
        assert closure_fingerprint(_WAS) != closure_fingerprint(_NOW)


class TestDriftDetection:
    def test_a_widened_closure_is_reported(self, tmp_path):
        drift = detect_closure_drift(_artifact(tmp_path), _NOW)
        assert drift is not None
        assert drift.added == ("https://ref.test/dcsa/container-operations",)
        assert drift.removed == ()

    def test_a_narrowed_closure_is_reported(self, tmp_path):
        drift = detect_closure_drift(_artifact(tmp_path, _NOW), _WAS)
        assert drift is not None
        assert drift.removed == ("https://ref.test/dcsa/container-operations",)

    def test_an_unchanged_closure_is_silent(self, tmp_path):
        assert detect_closure_drift(_artifact(tmp_path), _WAS) is None

    def test_the_message_names_the_modules_and_corrects_the_reading(self, tmp_path):
        text = detect_closure_drift(_artifact(tmp_path), _NOW).describe()
        assert "dcsa/container-operations" in text
        # The point of the message: stop the reader filing it as a sourcing gap.
        assert "staleness gap, not a sourcing gap" in text
        assert "propose-alignment" in text


class TestFailsQuietRatherThanWrong:
    """This warns about a real difference; guessing would make it ignorable."""

    def test_an_unreadable_artifact_is_not_called_stale(self, tmp_path):
        path = tmp_path / "broken-alignment.yaml"
        path.write_text("{[not yaml", encoding="utf-8")
        assert detect_closure_drift(path, _NOW) is None

    def test_a_missing_file_is_not_called_stale(self, tmp_path):
        assert detect_closure_drift(tmp_path / "nope.yaml", _NOW) is None

    def test_an_artifact_without_domain_uris_is_not_called_stale(self, tmp_path):
        """Pre-fingerprint artifacts exist in the field and are not evidence of drift."""
        path = tmp_path / "old-alignment.yaml"
        path.write_text(yaml.safe_dump({"domain": "old", "tables": []}), encoding="utf-8")
        assert detect_closure_drift(path, _NOW) is None

    def test_an_unresolvable_closure_does_not_report_everything_as_removed(self, tmp_path):
        """Nothing resolving now is a different problem, and calling every module removed
        would be a misleading way to report it."""
        assert detect_closure_drift(_artifact(tmp_path), ()) is None


def test_the_written_artifact_carries_the_fingerprint(tmp_path):
    """Fix 1 of the issue: persist it, so the comparison has something to stand on."""
    from kairos_ontology.core.propose_alignment import DomainAlignment, alignment_to_dict

    document = alignment_to_dict(
        DomainAlignment(
            domain="equipment",
            domain_uris=list(_WAS),
            generated_at="2026-09-19T00:00:00Z",
            model_used="gpt-5.4",
        )
    )
    assert document["closure_sha256"] == closure_fingerprint(_WAS)


def test_a_stem_fallback_domain_is_not_suffixed_twice():
    """A hand-edited artifact without a `domain` key falls back to the file stem, which
    already ends in `-alignment`; the message said `equipment-alignment-alignment.yaml`."""
    from kairos_ontology.core.alignment_closure import ClosureDrift

    message = ClosureDrift(domain="equipment-alignment", added=("x",), removed=()).describe()

    assert message.startswith("equipment-alignment.yaml is stale")
    assert "alignment-alignment" not in message
