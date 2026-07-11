# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The ``kairos-mdm:`` extension vocabulary — namespace, terms and enumerations.

The MDM extension is authored in ``model/extensions/<domain>-mdm-ext.ttl`` files
that annotate ontology IRIs with mastering/governance policy (ADR-1).  This module
is the single source of truth for the vocabulary IRIs and their permitted
enumerated values so the projector (:mod:`.profile_projector`) and validator
(:mod:`.validation`) stay in agreement.

Design intent (mdmhubdesignv2.md §5.1): the profile references ontology IRIs and
configures mastered domains + MDM style, attribute-level authority + survivorship,
**deterministic** match rules/thresholds plus a content-addressed reference to the
probabilistic artifact (never probabilistic weights in Turtle — ADR-5), workflow /
maker-checker policy, abstract steward roles, reference-data policy, and DQ rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rdflib import Namespace

# The MDM extension namespace. Mirrors KAIROS_EXT (…/ext#) with a dedicated slug so
# MDM terms never collide with the medallion extension vocabulary.
KAIROS_MDM = Namespace("https://kairos.cnext.eu/mdm#")


# ---------------------------------------------------------------------------
# Class-level annotation terms (on owl:Class)
# ---------------------------------------------------------------------------
MASTERED = KAIROS_MDM.mastered               # xsd:boolean — class is a mastered entity
MDM_STYLE = KAIROS_MDM.mdmStyle              # enum MDM_STYLES
REFERENCE_LIST = KAIROS_MDM.referenceList    # xsd:boolean — class is reference data

# ---------------------------------------------------------------------------
# Attribute-level annotation terms (on owl:DatatypeProperty / owl:ObjectProperty)
# ---------------------------------------------------------------------------
MATCH_ATTRIBUTE = KAIROS_MDM.matchAttribute        # xsd:boolean
IS_IDENTIFIER = KAIROS_MDM.identifier              # xsd:boolean — match-capable identifier
IDENTIFIER_TYPE = KAIROS_MDM.identifierType        # e.g. VAT, KBO, LEI, EORI
AUTHORITATIVE_SOURCE = KAIROS_MDM.authoritativeSource   # source system name(s)
SURVIVORSHIP = KAIROS_MDM.survivorship             # enum SURVIVORSHIP_STRATEGIES
SURVIVORSHIP_PRIORITY = KAIROS_MDM.survivorshipPriority  # xsd:integer (lower = wins)

# ---------------------------------------------------------------------------
# Deterministic match rules (kairos-mdm:MatchRule resources)
# ---------------------------------------------------------------------------
MATCH_RULE = KAIROS_MDM.MatchRule           # rdf:type of a deterministic rule node
APPLIES_TO = KAIROS_MDM.appliesTo           # rule -> owl:Class it masters
ON_ATTRIBUTE = KAIROS_MDM.onAttribute       # rule/DQ -> property IRI
COMPARATOR = KAIROS_MDM.comparator          # enum COMPARATORS
THRESHOLD = KAIROS_MDM.threshold            # xsd:decimal 0..1
MATCH_ACTION = KAIROS_MDM.matchAction       # enum MATCH_ACTIONS

# ---------------------------------------------------------------------------
# Probabilistic-model reference (ADR-5) — content-addressed, never weights in TTL
# ---------------------------------------------------------------------------
PROBABILISTIC_ARTIFACT = KAIROS_MDM.probabilisticArtifact  # ontology -> artifact node
ARTIFACT_DIGEST = KAIROS_MDM.artifactDigest   # e.g. sha256:… (content address)
ARTIFACT_VERSION = KAIROS_MDM.artifactVersion
ARTIFACT_URI = KAIROS_MDM.artifactUri

# ---------------------------------------------------------------------------
# Workflow / stewardship policy (on owl:Class)
# ---------------------------------------------------------------------------
MAKER_CHECKER = KAIROS_MDM.makerChecker         # xsd:boolean
AUTO_ACTION_BOUND = KAIROS_MDM.autoActionBound  # xsd:decimal — score >= bound may auto-act
SLA_HOURS = KAIROS_MDM.slaHours                 # xsd:integer
ESCALATION_ROLE = KAIROS_MDM.escalationRole     # abstract role name

# ---------------------------------------------------------------------------
# Abstract steward roles (kairos-mdm:StewardRole resources) — environment identity
# mapping stays in the dataplatform binding, never here (§5.1).
# ---------------------------------------------------------------------------
STEWARD_ROLE = KAIROS_MDM.StewardRole
ROLE_NAME = KAIROS_MDM.roleName
ROLE_SCOPE = KAIROS_MDM.scope

# ---------------------------------------------------------------------------
# Reference-data policy (on a referenceList class)
# ---------------------------------------------------------------------------
REFERENCE_OWNER = KAIROS_MDM.referenceOwner
RELEASE_POLICY = KAIROS_MDM.releasePolicy
REFERENCE_LICENSE = KAIROS_MDM.license          # license/attribution (§9.2)

# ---------------------------------------------------------------------------
# Data-quality rules (kairos-mdm:DataQualityRule resources) — §11
# ---------------------------------------------------------------------------
DQ_RULE = KAIROS_MDM.DataQualityRule
DQ_DIMENSION = KAIROS_MDM.dimension             # enum DQ_DIMENSIONS (DAMA six)
DQ_EXPRESSION = KAIROS_MDM.expression
DQ_SCORECARD_THRESHOLD = KAIROS_MDM.scorecardThreshold  # xsd:decimal 0..1
DQ_SEVERITY = KAIROS_MDM.severity               # enum DQ_SEVERITIES


# ---------------------------------------------------------------------------
# Enumerations (permitted controlled values)
# ---------------------------------------------------------------------------
#: MDM implementation styles (Gartner/DAMA).
MDM_STYLES = frozenset({"registry", "consolidation", "coexistence", "centralized"})

#: Attribute survivorship strategies (§5.1).
SURVIVORSHIP_STRATEGIES = frozenset(
    {"source-precedence", "recency", "completeness", "most-trusted", "manual"}
)

#: Deterministic comparators for match rules.
COMPARATORS = frozenset({"exact", "normalized", "fuzzy-reference"})

#: Outcome of a deterministic match rule.
MATCH_ACTIONS = frozenset({"auto-merge", "candidate", "review"})

#: The six DAMA data-quality dimensions (§11).
DQ_DIMENSIONS = frozenset(
    {"accuracy", "completeness", "consistency", "timeliness", "uniqueness", "validity"}
)

#: Data-quality rule severities.
DQ_SEVERITIES = frozenset({"info", "warning", "error"})


def discover_mdm_extension(
    onto_name: str,
    src_file: Path,
    extensions_dir: Optional[Path],
) -> Optional[Path]:
    """Locate the ``<domain>-mdm-ext.ttl`` extension for a domain ontology.

    Mirrors the discovery convention used by the medallion projectors
    (:func:`kairos_ontology.core.projector._discover_extensions`): prefer the
    grouped ``model/extensions/`` layout, then fall back to a file sitting next to
    the ontology (legacy flat layout).  Exact ``<onto_name>-mdm-ext.ttl`` wins over
    a wildcard ``*-mdm-ext.ttl`` match.

    Returns the path, or ``None`` when the domain has no MDM policy (in which case
    the projector emits nothing for that domain).
    """
    exact = f"{onto_name}-mdm-ext.ttl"

    if extensions_dir and extensions_dir.exists():
        candidate = extensions_dir / exact
        if candidate.exists():
            return candidate
        wildcard = sorted(extensions_dir.glob("*-mdm-ext.ttl"))
        if wildcard:
            return wildcard[0]

    parent = src_file.parent
    candidate = parent / exact
    if candidate.exists():
        return candidate
    wildcard = sorted(parent.glob("*-mdm-ext.ttl"))
    if wildcard:
        return wildcard[0]

    return None
