# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`analyse-sources` resolves the hub's accelerator rather than scanning (DD-183).

Affinity classifies each source table into a data domain. With an accelerator it
uses the blueprint's governed domains; without one it falls back to globbing every
TTL under the reference-models tree and treating each directory group as a
candidate.

On the live corpus that fallback offered **274 pseudo-domains** — FIBO, ACTUS, the
pattern library, and version strings like `1.2.0` and `current` — instead of the
blueprint's 22. Tables were classified into module names no domain owns
(`shipment-journey`, `track-and-trace`, `transport-order`), and 8 of 19 domains in
the result did not exist in the blueprint at all.

What makes the fallback dangerous is that its output looks completely normal:
nothing downstream can tell a governed domain from a scanned directory name. The
hub already declares `[tool.kairos].accelerator`, so the fix is to read it.
"""

import re
from pathlib import Path

CLI = Path(__file__).resolve().parent.parent / "src" / "kairos_ontology" / "cli" / "sources.py"


class TestResolutionIsAttempted:
    def test_analyse_sources_resolves_the_hub_accelerator(self):
        source = CLI.read_text(encoding="utf-8")
        assert "resolve_hub_accelerator" in source, (
            "analyse-sources must resolve the hub's declared accelerator; without one "
            "it silently classifies against every ontology in the tree (DD-183)."
        )

    def test_resolution_happens_before_the_domain_preflight(self):
        """Resolving after the pre-flight would print — and use — the wrong list."""
        source = CLI.read_text(encoding="utf-8")
        resolve_at = source.index("resolve_hub_accelerator")
        preflight_at = source.index("data domain(s) from")
        assert resolve_at < preflight_at

    def test_unresolved_accelerator_warns_loudly(self):
        """Silence here produced a plausible-looking, wholly wrong classification."""
        source = CLI.read_text(encoding="utf-8")
        block = source[source.index("No accelerator resolved") :][:600]
        assert "not the blueprint" in block
        assert "err=True" in block, "the warning must reach stderr, not be a status line"

    def test_the_warning_names_both_remedies(self):
        source = CLI.read_text(encoding="utf-8")
        block = source[source.index("No accelerator resolved") :][:600]
        assert "--accelerator" in block
        assert "tool.kairos" in block


class TestInferenceIsDistinguishable:
    def test_output_says_whether_the_accelerator_was_inferred(self):
        """A reader must be able to tell an inferred pack from one they passed."""
        source = CLI.read_text(encoding="utf-8")
        assert "inferred from hub" in source
        assert "explicit" in source

    def test_explicit_accelerator_is_not_overridden(self):
        """Inference must only fill a gap, never replace a passed value."""
        source = CLI.read_text(encoding="utf-8")
        guard = re.search(r"if not accelerator:\s*\n\s*try:", source)
        assert guard, "resolution must sit behind `if not accelerator:`"
