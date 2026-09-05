# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Generation-outcome constants shared by analyse-sources and propose-alignment.

Moved out of :mod:`kairos_ontology.core.propose_alignment` so that both
:mod:`kairos_ontology.core.analyse_sources` (which ``propose_alignment`` already
imports) and :mod:`kairos_ontology.core.propose_alignment` can import from here
without a circular import.  Values are unchanged so no artifact is affected.
"""

from __future__ import annotations

#: A real LLM call was made and returned a structured (possibly empty/no-match)
#: result — the only outcome persisted as a real result.
OUTCOME_SEMANTIC_SUCCESS = "semantic_success"

#: The LLM call itself failed (network, auth, rate-limit exhaustion, malformed
#: response, …). The table has no real semantic content; it must never be
#: written or reported as if the model had genuinely returned "no match".
OUTCOME_PROVIDER_FAILURE = "provider_failure"

#: No LLM call was even attempted because there was no reference-model class to
#: align against (e.g. the domain's reference model did not resolve). Every
#: column for the table falls back to a passthrough/custom disposition.
#: **Not** "no LLM" — it means "no reference model to align against".
OUTCOME_FALLBACK_ONLY = "fallback_only"

#: The model answered but returned an unresolvable id (e.g. a class IRI that
#: does not exist in the vocabulary). Currently indistinguishable from a real
#: failure in persisted state; this constant lets future code distinguish it.
OUTCOME_UNRESOLVED_ANSWER = "unresolved_answer"
