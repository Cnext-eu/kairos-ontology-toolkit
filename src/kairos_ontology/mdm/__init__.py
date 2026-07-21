# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Design-time Master Data Management (MDM) layer for the Kairos toolkit.

This subpackage is the **design-time** half of the MDM architecture described in
``docs/mdm/mdmhubdesignv2.md``.  It owns:

* the ``kairos-mdm:`` extension **vocabulary** (:mod:`.vocabulary`);
* the runtime-neutral **profile** dataclasses (:mod:`.model`);
* structural + SHACL **validation** of ``*-mdm-ext.ttl`` files (:mod:`.validation`);
* the ``mdm-profile`` **projector** that emits an immutable profile release
  (:mod:`.profile_projector`).

Architecture boundary (MDM-DD-002): ``mdm`` may import from
:mod:`kairos_ontology.core`, but ``core`` must never import from ``mdm``.  MDM is
an *additive* extension consumer of the ontology core, projected as an 8th target
(ADR-1).  Runtime services (matching engine, stewardship UI, operational store)
live in the separate ``kairos-mdm-runtime`` repository — none of that lives here.
"""

from kairos_ontology.mdm.vocabulary import KAIROS_MDM, discover_mdm_extension
from kairos_ontology.mdm.model import (
    DataQualityRule,
    MasteredConcept,
    MatchAttribute,
    MatchRule,
    MdmProfile,
    ProbabilisticArtifactRef,
    ProfileProvenance,
    ReferenceListPolicy,
    StewardRole,
    SurvivorshipRule,
    WorkflowPolicy,
)
from kairos_ontology.mdm.validation import validate_mdm_extension
from kairos_ontology.mdm.profile_projector import generate_mdm_profile_artifacts

__all__ = [
    "KAIROS_MDM",
    "discover_mdm_extension",
    "DataQualityRule",
    "MasteredConcept",
    "MatchAttribute",
    "MatchRule",
    "MdmProfile",
    "ProbabilisticArtifactRef",
    "ProfileProvenance",
    "ReferenceListPolicy",
    "StewardRole",
    "SurvivorshipRule",
    "WorkflowPolicy",
    "validate_mdm_extension",
    "generate_mdm_profile_artifacts",
]


def _project_mdm_profile(
    *,
    graph,
    namespace,
    ontology_name,
    ext_path,
    ontology_metadata,
):
    return generate_mdm_profile_artifacts(
        graph=graph,
        namespace=namespace,
        ontology_name=ontology_name,
        mdm_ext_path=ext_path,
        ontology_metadata=ontology_metadata,
    )


def _register_projection_target() -> None:
    """Register the ``mdm-profile`` target with the core projector registry.

    Importing this package registers MDM as an additive projection target
    *without* core ever importing ``mdm`` — preserving the one-way boundary
    (MDM-DD-002).  Registration is idempotent, so repeated imports are safe.
    """
    from kairos_ontology.core.projector import register_target

    register_target(
        "mdm-profile",
        discover_ext=discover_mdm_extension,
        project=_project_mdm_profile,
        output_subdir="mdm",
    )


_register_projection_target()
