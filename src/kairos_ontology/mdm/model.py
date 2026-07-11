# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Runtime-neutral MDM profile dataclasses.

The **MDM profile** is the immutable, runtime-neutral policy object projected from
``*-mdm-ext.ttl`` (mdmhubdesignv2.md §5.1, Terminology §3).  It is consumed by the
``kairos-mdm-runtime`` and pinned by the dataplatform under ``contracts/mdm/`` — so
these dataclasses deliberately hold **policy only**, never runtime state (enterprise
IDs, crosswalks, scores) and never environment bindings (endpoints, secrets, Entra
group maps).

Every dataclass is JSON-serializable via :meth:`to_dict` so the projector can emit a
stable ``<domain>-mdm-profile.json`` release.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProfileProvenance:
    """Which hub + toolkit version produced this profile release (§5.1)."""

    domain: str = ""
    ontology_iri: str = ""
    ontology_version: str = ""
    toolkit_version: str = ""
    generated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MatchAttribute:
    """An attribute that participates in identity resolution / survivorship."""

    property_iri: str
    name: str
    is_identifier: bool = False
    identifier_type: Optional[str] = None
    authoritative_sources: List[str] = field(default_factory=list)
    survivorship: Optional[str] = None
    survivorship_priority: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MatchRule:
    """A deterministic match rule (probabilistic weights live out-of-band — ADR-5)."""

    rule_iri: str
    on_attributes: List[str] = field(default_factory=list)
    comparator: str = "exact"
    threshold: Optional[float] = None
    action: str = "candidate"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProbabilisticArtifactRef:
    """Content-addressed reference to the owned probabilistic model (ADR-5)."""

    digest: str = ""
    version: Optional[str] = None
    uri: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SurvivorshipRule:
    """Attribute-level survivorship precedence (denormalized for readability)."""

    property_iri: str
    strategy: str
    priority: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowPolicy:
    """Automatic-action boundaries + maker/checker + SLA for a mastered concept."""

    maker_checker: bool = False
    auto_action_bound: Optional[float] = None
    sla_hours: Optional[int] = None
    escalation_role: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StewardRole:
    """An abstract governance role (environment identity mapping stays external)."""

    role_iri: str
    name: str
    scope: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DataQualityRule:
    """A data-quality rule scored against a DAMA dimension (§11)."""

    rule_iri: str
    dimension: str
    on_attributes: List[str] = field(default_factory=list)
    expression: Optional[str] = None
    scorecard_threshold: Optional[float] = None
    severity: str = "warning"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReferenceListPolicy:
    """Reference-data ownership / release / license policy (§9.2)."""

    class_iri: str
    name: str
    owner: Optional[str] = None
    release_policy: Optional[str] = None
    license: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MasteredConcept:
    """A mastered entity and all policy attached to it."""

    class_iri: str
    name: str
    label: str = ""
    mdm_style: Optional[str] = None
    match_attributes: List[MatchAttribute] = field(default_factory=list)
    match_rules: List[MatchRule] = field(default_factory=list)
    survivorship: List[SurvivorshipRule] = field(default_factory=list)
    workflow: WorkflowPolicy = field(default_factory=WorkflowPolicy)
    data_quality: List[DataQualityRule] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "class_iri": self.class_iri,
            "name": self.name,
            "label": self.label,
            "mdm_style": self.mdm_style,
            "match_attributes": [a.to_dict() for a in self.match_attributes],
            "match_rules": [r.to_dict() for r in self.match_rules],
            "survivorship": [s.to_dict() for s in self.survivorship],
            "workflow": self.workflow.to_dict(),
            "data_quality": [d.to_dict() for d in self.data_quality],
        }


@dataclass
class MdmProfile:
    """The complete immutable, runtime-neutral MDM profile for one domain."""

    provenance: ProfileProvenance = field(default_factory=ProfileProvenance)
    mastered_concepts: List[MasteredConcept] = field(default_factory=list)
    reference_lists: List[ReferenceListPolicy] = field(default_factory=list)
    steward_roles: List[StewardRole] = field(default_factory=list)
    probabilistic_artifact: Optional[ProbabilisticArtifactRef] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provenance": self.provenance.to_dict(),
            "mastered_concepts": [c.to_dict() for c in self.mastered_concepts],
            "reference_lists": [r.to_dict() for r in self.reference_lists],
            "steward_roles": [r.to_dict() for r in self.steward_roles],
            "probabilistic_artifact": (
                self.probabilistic_artifact.to_dict()
                if self.probabilistic_artifact
                else None
            ),
        }
