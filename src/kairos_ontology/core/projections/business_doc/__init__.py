# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Per-domain business validation document (DD-254, #1105).

Two inputs with separate authority: ``facts`` (derived deterministically from the hub) and
``narrative`` (drafted by the agent, confirmed by a person). ``render_docx`` joins them into a
Word document after ``narrative.validate_narrative`` has checked that the narrative adds no
fact and leaves none unplaced.
"""

from .facts import (
    FACTS_FILENAME,
    SCHEMA_VERSION,
    BusinessDocError,
    build_facts,
    business_type,
    cardinality_code,
    facts_json,
)
from .narrative import NARRATIVE_FILENAME, load_narrative, validate_narrative

__all__ = [
    "FACTS_FILENAME",
    "NARRATIVE_FILENAME",
    "SCHEMA_VERSION",
    "BusinessDocError",
    "build_facts",
    "business_type",
    "cardinality_code",
    "facts_json",
    "load_narrative",
    "validate_narrative",
]
