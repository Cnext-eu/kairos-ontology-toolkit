# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Typed reference-module activation, import planning, and inventory."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

import yaml
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF

from .catalog_utils import CatalogResolver
from .ontology_loader import SemanticProfile, load_ontology


class DescendantPolicy(str, Enum):
    """Supported module-root descendant policies."""

    ALL = "all"
    SELECTED = "selected"
    NONE = "none"


@dataclass(frozen=True)
class ReferenceModuleProfile:
    """Version-pinned, source-neutral activation policy for one ontology module."""

    id: str
    ontology_iri: str
    version_pin: str | None
    catalog_uri: str | None = None
    term_namespaces: tuple[str, ...] = ()
    root_classes: tuple[str, ...] = ()
    descendant_policy: DescendantPolicy = DescendantPolicy.ALL
    included_branches: tuple[str, ...] = ()
    excluded_terms: tuple[str, ...] = ()
    projection_allowlist: tuple[str, ...] = ()
    default_annotation_sources: tuple[str, ...] = ()
    accepted_transitive_dependencies: tuple[str, ...] = ()
    local_extension_namespaces: tuple[str, ...] = ()
    legacy: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, legacy: bool = False) -> "ReferenceModuleProfile":
        """Parse and validate a module profile mapping."""
        module_id = str(data.get("id") or "").strip()
        ontology_iri = str(data.get("ontology_iri") or data.get("uri") or "").strip()
        if not module_id:
            raise ValueError("module profile requires 'id'")
        if not ontology_iri:
            raise ValueError(f"module profile {module_id!r} requires 'ontology_iri'")
        if ontology_iri.endswith("#"):
            raise ValueError(
                f"module profile {module_id!r} ontology_iri must be a document IRI, not "
                f"a term namespace ending in '#': {ontology_iri}"
            )

        version = data.get("version_pin", data.get("version"))
        if not legacy and (version is None or not str(version).strip()):
            raise ValueError(f"module profile {module_id!r} requires a version pin")

        descendants = data.get("descendants", data.get("descendant_policy", "all"))
        if isinstance(descendants, dict):
            policy = descendants.get("policy", "all")
            included = descendants.get("include", descendants.get("included_branches", []))
            excluded = descendants.get("exclude", descendants.get("excluded_terms", []))
        else:
            policy = descendants
            included = data.get("included_branches", [])
            excluded = data.get("excluded_terms", [])

        projection = data.get("projection", {})
        if isinstance(projection, dict):
            allowlist = projection.get("allowlist", data.get("projection_allowlist", []))
        else:
            allowlist = data.get("projection_allowlist", [])

        return cls(
            id=module_id,
            ontology_iri=ontology_iri,
            version_pin=str(version).strip() if version is not None else None,
            catalog_uri=str(data.get("catalog_uri") or ontology_iri),
            term_namespaces=_strings(data.get("term_namespaces", [])),
            root_classes=_strings(data.get("root_classes", data.get("roots", []))),
            descendant_policy=DescendantPolicy(str(policy)),
            included_branches=_strings(included),
            excluded_terms=_strings(excluded),
            projection_allowlist=_strings(allowlist),
            default_annotation_sources=_strings(
                data.get("default_annotation_sources", data.get("default_annotations", []))
            ),
            accepted_transitive_dependencies=_strings(
                data.get("accepted_transitive_dependencies", [])
            ),
            local_extension_namespaces=_strings(
                data.get("local_extension_namespaces", [])
            ),
            legacy=legacy,
        )


@dataclass(frozen=True)
class DataDomainActivation:
    """Reference-module profiles activated for one hub data domain."""

    domain: str
    module_ids: tuple[str, ...]


@dataclass(frozen=True)
class AcceleratorModuleConfig:
    """Typed accelerator module configuration parsed from ``data-domains.yaml``."""

    accelerator: str
    source_path: Path
    profiles: tuple[ReferenceModuleProfile, ...]
    domains: tuple[DataDomainActivation, ...]

    def profile(self, module_id: str) -> ReferenceModuleProfile | None:
        return next((item for item in self.profiles if item.id == module_id), None)

    def activation(self, domain: str) -> DataDomainActivation | None:
        return next((item for item in self.domains if item.domain == domain), None)


@dataclass(frozen=True)
class ModuleDiagnostic:
    """Structured module/import diagnostic suitable for reports and CLI output."""

    level: str
    code: str
    message: str
    term_uri: str | None = None
    expected_ontology_iri: str | None = None
    managed_source: str | None = None
    claim_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedReferenceModule:
    """A module profile resolved through the canonical closure/index API."""

    profile: ReferenceModuleProfile
    ontology_iri: str
    ontology_version: str | None
    closure_hash: str
    manifest: tuple[Any, ...]
    semantic_index: Any


@dataclass(frozen=True)
class ReferenceModuleContext:
    """Resolved module configuration shared by sync, validation, and projection."""

    config: AcceleratorModuleConfig
    modules: tuple[ResolvedReferenceModule, ...]
    diagnostics: tuple[ModuleDiagnostic, ...] = ()

    def module(self, module_id: str) -> ResolvedReferenceModule | None:
        return next((item for item in self.modules if item.profile.id == module_id), None)


def default_annotation_paths(
    config: AcceleratorModuleConfig,
    profile: ReferenceModuleProfile,
) -> tuple[Path, ...]:
    """Resolve profile annotation sources relative to its data-domains file."""
    paths = []
    for source in profile.default_annotation_sources:
        path = Path(source)
        if not path.is_absolute():
            path = config.source_path.parent / path
        paths.append(path.resolve())
    return tuple(sorted(paths))


def active_projection_allowlist(
    context: ReferenceModuleContext,
    domain: str,
) -> set[str]:
    """Return the explicit module-profile projection allow-list for a domain."""
    activation = context.config.activation(domain)
    if activation is None:
        return set()
    return {
        uri
        for module_id in activation.module_ids
        if (module := context.module(module_id)) is not None
        for uri in module.profile.projection_allowlist
    }


def active_default_annotation_paths(
    context: ReferenceModuleContext,
    domain: str,
) -> tuple[Path, ...]:
    """Return validated annotation sources from modules activated for a domain."""
    activation = context.config.activation(domain)
    if activation is None:
        return ()
    paths = {
        path
        for module_id in activation.module_ids
        if (module := context.module(module_id)) is not None
        for path in default_annotation_paths(context.config, module.profile)
    }
    return tuple(sorted(paths))


@dataclass(frozen=True)
class ManagedImportRequirement:
    """One direct import required by claims or configured module activation."""

    import_iri: str
    expected_ontology_iri: str
    managed_source: str
    reasons: tuple[str, ...] = ()
    term_uris: tuple[str, ...] = ()
    accepted_transitive: bool = False


@dataclass(frozen=True)
class ManagedImportPlan:
    """Deterministic managed-import and projection-selection plan."""

    domain: str
    requirements: tuple[ManagedImportRequirement, ...]
    selected_class_uris: tuple[str, ...]
    diagnostics: tuple[ModuleDiagnostic, ...] = ()
    activation_inventory: dict[str, Any] = field(default_factory=dict)

    @property
    def expected_imports(self) -> tuple[str, ...]:
        return tuple(sorted({item.import_iri for item in self.requirements}))

    @property
    def blocking_diagnostics(self) -> tuple[ModuleDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.level == "error")


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(sorted({str(item) for item in value if item is not None}))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "module"


def _legacy_document_iri(uri: str) -> str:
    """Adapt the historical hash-namespace format without changing slash document IRIs."""
    return uri[:-1] if uri.endswith("#") else uri


def _data_domains_path(ref_models_dir: Path, accelerator: str | None) -> Path | None:
    pattern = (
        f"accelerator-packs/{accelerator}/client-hub-blueprint/data-domains.yaml"
        if accelerator
        else "accelerator-packs/*/client-hub-blueprint/data-domains.yaml"
    )
    paths = sorted(ref_models_dir.glob(pattern))
    return paths[0] if paths else None


def load_accelerator_module_config(
    ref_models_dir: Path,
    accelerator: str | None = None,
) -> AcceleratorModuleConfig | None:
    """Load typed profiles and domain activations with legacy import compatibility."""
    path = _data_domains_path(Path(ref_models_dir), accelerator)
    if path is None:
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: data-domains.yaml must contain a mapping")

    profiles: dict[str, ReferenceModuleProfile] = {}
    for raw in data.get("module_profiles", []) or []:
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: module_profiles entries must be mappings")
        profile = ReferenceModuleProfile.from_dict(raw)
        if profile.id in profiles:
            raise ValueError(f"{path}: duplicate module profile id {profile.id!r}")
        profiles[profile.id] = profile

    domain_modules: dict[str, set[str]] = {}
    for group in data.get("groups", []) or []:
        for domain in group.get("domains", []) or []:
            domain_id = str(domain.get("id") or "").strip()
            if not domain_id:
                continue
            module_ids: list[str] = []
            for raw_import in domain.get("imports", []) or []:
                if not isinstance(raw_import, dict):
                    raise ValueError(f"{path}: imports entries must be mappings")
                profile_id = raw_import.get("profile") or raw_import.get("module_id")
                if profile_id:
                    profile_id = str(profile_id)
                    if profile_id not in profiles:
                        raise ValueError(
                            f"{path}: domain {domain_id!r} references unknown module "
                            f"profile {profile_id!r}"
                        )
                else:
                    uri = str(raw_import.get("uri") or "").strip()
                    if not uri:
                        continue
                    label = str(raw_import.get("module") or uri)
                    profile_id = f"legacy-{_slug(label)}"
                    suffix = 2
                    base_id = profile_id
                    while (
                        profile_id in profiles
                        and profiles[profile_id].catalog_uri != uri
                    ):
                        profile_id = f"{base_id}-{suffix}"
                        suffix += 1
                    profiles.setdefault(
                        profile_id,
                        ReferenceModuleProfile.from_dict(
                            {
                                "id": profile_id,
                                "ontology_iri": _legacy_document_iri(uri),
                                "catalog_uri": uri,
                                "term_namespaces": [uri],
                            },
                            legacy=True,
                        ),
                    )
                module_ids.append(profile_id)
            domain_modules.setdefault(domain_id, set()).update(module_ids)

    activations = [
        DataDomainActivation(domain=domain, module_ids=tuple(sorted(module_ids)))
        for domain, module_ids in sorted(domain_modules.items())
    ]

    return AcceleratorModuleConfig(
        accelerator=accelerator or path.parents[1].name,
        source_path=path,
        profiles=tuple(sorted(profiles.values(), key=lambda item: item.id)),
        domains=tuple(activations),
    )


def resolve_reference_modules(
    config: AcceleratorModuleConfig,
    *,
    catalog_path: Path | None,
) -> ReferenceModuleContext:
    """Resolve every profile and enforce its document IRI and version pin."""
    resolver = CatalogResolver(Path(catalog_path)) if catalog_path else None
    modules: list[ResolvedReferenceModule] = []
    diagnostics: list[ModuleDiagnostic] = []

    for profile in config.profiles:
        missing_defaults = [
            path for path in default_annotation_paths(config, profile) if not path.is_file()
        ]
        if missing_defaults:
            diagnostics.append(
                ModuleDiagnostic(
                    "error",
                    "module_default_annotations_missing",
                    f"Module {profile.id!r} default annotation source(s) do not exist: "
                    + ", ".join(str(path) for path in missing_defaults),
                    expected_ontology_iri=profile.ontology_iri,
                    managed_source=profile.id,
                )
            )
            continue
        invalid_defaults = []
        for path in default_annotation_paths(config, profile):
            try:
                Graph().parse(path)
            except Exception as exc:  # noqa: BLE001
                invalid_defaults.append(f"{path}: {exc}")
        if invalid_defaults:
            diagnostics.append(
                ModuleDiagnostic(
                    "error",
                    "module_default_annotations_invalid",
                    f"Module {profile.id!r} default annotation source(s) are invalid: "
                    + "; ".join(invalid_defaults),
                    expected_ontology_iri=profile.ontology_iri,
                    managed_source=profile.id,
                )
            )
            continue
        resolved = resolver.resolve(profile.catalog_uri or profile.ontology_iri) if resolver else None
        if resolved is None:
            diagnostics.append(
                ModuleDiagnostic(
                    "error",
                    "module_unresolved",
                    f"Module {profile.id!r} cannot be resolved through the catalog",
                    expected_ontology_iri=profile.ontology_iri,
                    managed_source=profile.id,
                )
            )
            continue
        try:
            loaded = load_ontology(
                Path(resolved),
                catalog_path=catalog_path,
                profile=SemanticProfile.KAIROS_DESIGN,
            )
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                ModuleDiagnostic(
                    "error",
                    "module_load_failed",
                    f"Module {profile.id!r} failed to load: {exc}",
                    expected_ontology_iri=profile.ontology_iri,
                    managed_source=profile.id,
                )
            )
            continue

        root = next((item for item in loaded.manifest if item.import_depth == 0), None)
        declared_iri = root.ontology_iri if root else None
        declared_version = root.ontology_version if root else None
        expected_iri = profile.ontology_iri.rstrip("#")
        if declared_iri and declared_iri.rstrip("#") != expected_iri:
            diagnostics.append(
                ModuleDiagnostic(
                    "error",
                    "module_ontology_iri_mismatch",
                    f"Module {profile.id!r} declares {declared_iri}, expected {expected_iri}",
                    expected_ontology_iri=expected_iri,
                    managed_source=profile.id,
                )
            )
            continue
        if profile.version_pin and declared_version != profile.version_pin:
            diagnostics.append(
                ModuleDiagnostic(
                    "error",
                    "module_version_mismatch",
                    f"Module {profile.id!r} version is {declared_version!r}, expected "
                    f"{profile.version_pin!r}",
                    expected_ontology_iri=expected_iri,
                    managed_source=profile.id,
                )
            )
            continue
        missing_profile_terms = [
            uri
            for uri in (*profile.root_classes, *profile.projection_allowlist)
            if loaded.semantic_index.class_by_uri(uri) is None
        ]
        if missing_profile_terms:
            diagnostics.append(
                ModuleDiagnostic(
                    "error",
                    "module_profile_term_missing",
                    f"Module {profile.id!r} profile references missing class(es): "
                    + ", ".join(sorted(missing_profile_terms)),
                    expected_ontology_iri=expected_iri,
                    managed_source=profile.id,
                )
            )
            continue
        modules.append(
            ResolvedReferenceModule(
                profile=profile,
                ontology_iri=(declared_iri or expected_iri).rstrip("#"),
                ontology_version=declared_version,
                closure_hash=loaded.closure_hash,
                manifest=loaded.manifest,
                semantic_index=loaded.semantic_index,
            )
        )

    return ReferenceModuleContext(
        config=config,
        modules=tuple(sorted(modules, key=lambda item: item.profile.id)),
        diagnostics=tuple(sorted(diagnostics, key=_diagnostic_key)),
    )


def build_reference_module_context(
    ref_models_dir: Path | None,
    *,
    catalog_path: Path | None,
    accelerator: str | None = None,
) -> ReferenceModuleContext | None:
    """Convenience loader used by CLI and semantic preflights."""
    if ref_models_dir is None or not Path(ref_models_dir).is_dir():
        return None
    config = load_accelerator_module_config(Path(ref_models_dir), accelerator)
    return (
        resolve_reference_modules(config, catalog_path=catalog_path)
        if config is not None
        else None
    )


def _diagnostic_key(item: ModuleDiagnostic) -> tuple[str, ...]:
    return (
        item.code,
        item.term_uri or "",
        item.expected_ontology_iri or "",
        item.managed_source or "",
        item.claim_id or "",
    )


def _claim_term_refs(registry: Any) -> list[tuple[str, str, str]]:
    from .binding_analysis import approved_imported_term_refs

    return [
        (claim_id, term_uri, claim_type)
        for claim_id, term_uri, claim_type in approved_imported_term_refs(registry)
    ]


def _module_term(module: ResolvedReferenceModule, uri: str) -> Any | None:
    return module.semantic_index.term(uri)


def _owner_ontology(module: ResolvedReferenceModule, term: Any) -> str:
    source = term.provenance.source_identity
    entry = next(
        (item for item in module.manifest if item.source_identity == source),
        None,
    )
    return (entry.ontology_iri if entry and entry.ontology_iri else source).rstrip("#")


def _find_term_module(
    uri: str,
    modules: Iterable[ResolvedReferenceModule],
    activated_ids: set[str],
) -> tuple[ResolvedReferenceModule, Any] | None:
    matches = [
        (module, term)
        for module in modules
        if (term := _module_term(module, uri)) is not None
    ]
    activated = [item for item in matches if item[0].profile.id in activated_ids]
    candidates = activated or matches
    return candidates[0] if len(candidates) == 1 else None


def _fallback_document_iri(term_uri: str) -> str:
    if "#" in term_uri:
        return term_uri.rsplit("#", 1)[0]
    if "/" in term_uri:
        return term_uri.rsplit("/", 1)[0]
    return term_uri


def _is_local_term(term_uri: str, ontology_iri: str | None) -> bool:
    if not ontology_iri:
        return False
    bare = ontology_iri.rstrip("#/")
    return term_uri.startswith((bare + "#", bare + "/"))


def build_managed_import_plan(
    registry: Any,
    *,
    domain: str,
    context: ReferenceModuleContext | None = None,
    ontology_graph: Graph | None = None,
    projected_uris: Iterable[str] | None = None,
    local_ontology_iri: str | None = None,
) -> ManagedImportPlan:
    """Build the union of claim-driven and data-domain-driven managed imports."""
    if local_ontology_iri is None and ontology_graph is not None:
        local_ontology_iri = next(
            (
                str(subject)
                for subject in ontology_graph.subjects(RDF.type, OWL.Ontology)
                if isinstance(subject, URIRef)
            ),
            None,
        )
    diagnostics = list(context.diagnostics if context else ())
    activation = context.config.activation(domain) if context else None
    activated_ids = set(activation.module_ids if activation else ())
    requirement_data: dict[tuple[str, str], dict[str, Any]] = {}

    def require(
        import_iri: str,
        *,
        owner_iri: str,
        source: str,
        reason: str,
        term_uri: str | None = None,
        accepted_transitive: bool = False,
    ) -> None:
        key = (import_iri.rstrip("#"), owner_iri.rstrip("#"))
        entry = requirement_data.setdefault(
            key,
            {
                "sources": set(),
                "reasons": set(),
                "terms": set(),
                "accepted_transitive": accepted_transitive,
            },
        )
        entry["sources"].add(source)
        entry["reasons"].add(reason)
        if term_uri:
            entry["terms"].add(term_uri)
        entry["accepted_transitive"] = (
            entry["accepted_transitive"] or accepted_transitive
        )

    if context and activation:
        for module_id in activation.module_ids:
            module = context.module(module_id)
            if module is None:
                continue
            require(
                module.ontology_iri,
                owner_iri=module.ontology_iri,
                source=module_id,
                reason=f"data-domain:{domain}",
            )

    class_claims: set[str] = set()
    for claim_id, term_uri, claim_type in _claim_term_refs(registry):
        if _is_local_term(term_uri, local_ontology_iri):
            continue
        if claim_type in {"class", "reference_data"}:
            class_claims.add(term_uri)
        match = (
            _find_term_module(term_uri, context.modules, activated_ids)
            if context
            else None
        )
        if match is None:
            fallback = _fallback_document_iri(term_uri).rstrip("#")
            require(
                fallback,
                owner_iri=fallback,
                source="claim-uri-fallback",
                reason=f"claim:{claim_id}",
                term_uri=term_uri,
            )
            if context:
                diagnostics.append(
                    ModuleDiagnostic(
                        "warning",
                        "term_owner_unresolved",
                        f"Could not resolve the managed module owning {term_uri}; "
                        f"using the legacy URI fallback {fallback}",
                        term_uri=term_uri,
                        expected_ontology_iri=fallback,
                        managed_source="claim-uri-fallback",
                        claim_id=claim_id,
                    )
                )
            continue

        module, term = match
        owner_iri = _owner_ontology(module, term)
        accepted = owner_iri in {
            item.rstrip("#")
            for item in module.profile.accepted_transitive_dependencies
        }
        import_iri = module.ontology_iri if accepted else owner_iri
        require(
            import_iri,
            owner_iri=owner_iri,
            source=module.profile.id,
            reason=f"claim:{claim_id}",
            term_uri=term_uri,
            accepted_transitive=accepted,
        )

    if context and ontology_graph is not None:
        authored_term_uris = {
            str(node)
            for triple in ontology_graph
            for node in triple
            if isinstance(node, URIRef)
            and not str(node).startswith(
                (
                    "http://www.w3.org/",
                    "https://www.w3.org/",
                    "https://kairos.cnext.eu/ext#",
                )
            )
        }
        for term_uri in sorted(authored_term_uris):
            matches = [
                module
                for module in context.modules
                if _module_term(module, term_uri) is not None
            ]
            match = _find_term_module(term_uri, context.modules, activated_ids)
            if match is None:
                if len(matches) > 1:
                    diagnostics.append(
                        ModuleDiagnostic(
                            "error",
                            "term_owner_ambiguous",
                            f"External term {term_uri} is provided by multiple managed "
                            "modules: "
                            + ", ".join(sorted(item.profile.id for item in matches)),
                            term_uri=term_uri,
                        )
                    )
                continue
            module, term = match
            owner_iri = _owner_ontology(module, term)
            accepted = owner_iri in {
                item.rstrip("#")
                for item in module.profile.accepted_transitive_dependencies
            }
            require(
                module.ontology_iri if accepted else owner_iri,
                owner_iri=owner_iri,
                source=module.profile.id,
                reason="authored-ontology",
                term_uri=term_uri,
                accepted_transitive=accepted,
            )

    profile_allowlist: set[str] = set()
    if context:
        for module_id in activated_ids:
            module = context.module(module_id)
            if module:
                profile_allowlist.update(module.profile.projection_allowlist)
    selected = class_claims | profile_allowlist

    requirements = tuple(
        ManagedImportRequirement(
            import_iri=iri,
            expected_ontology_iri=owner_iri,
            managed_source=",".join(sorted(data["sources"])),
            reasons=tuple(sorted(data["reasons"])),
            term_uris=tuple(sorted(data["terms"])),
            accepted_transitive=bool(data["accepted_transitive"]),
        )
        for (iri, owner_iri), data in sorted(requirement_data.items())
    )
    inventory = build_activation_inventory(
        domain=domain,
        context=context,
        selected_uris=selected,
        projected_uris=projected_uris,
    )
    plan = ManagedImportPlan(
        domain=domain,
        requirements=requirements,
        selected_class_uris=tuple(sorted(selected)),
        diagnostics=tuple(sorted(diagnostics, key=_diagnostic_key)),
        activation_inventory=inventory,
    )
    if ontology_graph is None:
        return plan
    return ManagedImportPlan(
        domain=plan.domain,
        requirements=plan.requirements,
        selected_class_uris=plan.selected_class_uris,
        diagnostics=tuple(
            sorted(
                (*plan.diagnostics, *validate_external_term_imports(ontology_graph, plan)),
                key=_diagnostic_key,
            )
        ),
        activation_inventory=plan.activation_inventory,
    )


def validate_external_term_imports(
    ontology_graph: Graph,
    plan: ManagedImportPlan,
) -> tuple[ModuleDiagnostic, ...]:
    """Report required imports absent from the root ontology's direct imports."""
    subjects = [
        subject
        for subject in ontology_graph.subjects(RDF.type, OWL.Ontology)
        if isinstance(subject, URIRef)
    ]
    direct = {
        str(value).rstrip("#")
        for subject in subjects
        for value in ontology_graph.objects(subject, OWL.imports)
    }
    diagnostics: list[ModuleDiagnostic] = []
    for requirement in plan.requirements:
        if requirement.import_iri.rstrip("#") in direct:
            continue
        terms = requirement.term_uris or (None,)
        reasons = requirement.reasons or (None,)
        for term in terms:
            claim_id = next(
                (
                    reason.removeprefix("claim:")
                    for reason in reasons
                    if reason and reason.startswith("claim:")
                ),
                None,
            )
            diagnostics.append(
                ModuleDiagnostic(
                    "error",
                    "missing_managed_import",
                    f"External term {term or '(configured module)'} requires "
                    f"owl:imports <{requirement.import_iri}>; owning ontology is "
                    f"<{requirement.expected_ontology_iri}> and managed source is "
                    f"{requirement.managed_source}",
                    term_uri=term,
                    expected_ontology_iri=requirement.expected_ontology_iri,
                    managed_source=requirement.managed_source,
                    claim_id=claim_id,
                )
            )
    return tuple(sorted(diagnostics, key=_diagnostic_key))


def _available_classes(module: ResolvedReferenceModule) -> set[str]:
    profile = module.profile
    all_classes = {item.uri for item in module.semantic_index.classes}
    if not profile.root_classes:
        available = set(all_classes)
    else:
        available = set(profile.root_classes)
        roots = set(profile.root_classes)
        if profile.descendant_policy is DescendantPolicy.ALL:
            for root in roots:
                record = module.semantic_index.class_by_uri(root)
                if record:
                    available.update(item.uri for item in record.descendants)
        elif profile.descendant_policy is DescendantPolicy.SELECTED:
            available.update(profile.included_branches)
            for branch in profile.included_branches:
                record = module.semantic_index.class_by_uri(branch)
                if record:
                    available.update(item.uri for item in record.descendants)
    return available - set(profile.excluded_terms)


def build_activation_inventory(
    *,
    domain: str,
    context: ReferenceModuleContext | None,
    selected_uris: Iterable[str] = (),
    projected_uris: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic closure/selection inventory without copying definitions."""
    selected = set(selected_uris)
    projected = selected if projected_uris is None else set(projected_uris)
    if context is None:
        return {
            "schema_version": 1,
            "domain": domain,
            "accelerator": None,
            "closure_hash": None,
            "modules": [],
            "terms": [],
        }

    activation = context.config.activation(domain)
    active_ids = set(activation.module_ids if activation else ())
    modules = [
        module for module in context.modules if module.profile.id in active_ids
    ]
    closure_payload = "\n".join(
        f"{module.profile.id}:{module.closure_hash}" for module in modules
    )
    inherited_by: dict[str, set[str]] = {}
    for module in modules:
        for cls in module.semantic_index.classes:
            for link in cls.inherited_properties:
                inherited_by.setdefault(link.uri, set()).add(cls.uri)

    terms: dict[str, dict[str, Any]] = {}
    for module in modules:
        available_classes = _available_classes(module)
        explicit_exclusions = set(module.profile.excluded_terms)
        records = [
            ("class", item) for item in module.semantic_index.classes
        ] + [
            ("property", item) for item in module.semantic_index.properties
        ] + [
            ("individual", item) for item in module.semantic_index.individuals
        ]
        for kind, record in records:
            if kind == "class":
                availability = (
                    "available" if record.uri in available_classes else "excluded"
                )
            else:
                availability = (
                    "excluded" if record.uri in explicit_exclusions else "available"
                )
            terms[record.uri] = {
                "uri": record.uri,
                "kind": kind,
                "module": module.profile.id,
                "availability": availability,
                "selection": (
                    "selected"
                    if record.uri in selected
                    else "excluded"
                    if availability == "excluded"
                    else "unselected"
                ),
                "inherited": bool(inherited_by.get(record.uri)),
                "inherited_by": sorted(inherited_by.get(record.uri, set())),
                "projection": (
                    "projected" if record.uri in projected else "not_projected"
                ),
                "provenance": {
                    "source_identity": record.provenance.source_identity,
                    "import_depth": record.provenance.import_depth,
                    "asserted": record.provenance.asserted,
                },
            }

    return {
        "schema_version": 1,
        "domain": domain,
        "accelerator": context.config.accelerator,
        "closure_hash": (
            hashlib.sha256(closure_payload.encode("utf-8")).hexdigest()
            if closure_payload
            else None
        ),
        "modules": [
            {
                "id": module.profile.id,
                "ontology_iri": module.ontology_iri,
                "version": module.ontology_version,
                "version_pin": module.profile.version_pin,
                "closure_hash": module.closure_hash,
                "root_classes": list(module.profile.root_classes),
                "descendant_policy": module.profile.descendant_policy.value,
                "projection_allowlist": list(module.profile.projection_allowlist),
                "default_annotation_sources": list(
                    module.profile.default_annotation_sources
                ),
                "local_extension_namespaces": list(
                    module.profile.local_extension_namespaces
                ),
            }
            for module in modules
        ],
        "terms": [terms[uri] for uri in sorted(terms)],
    }


def dump_activation_inventory(inventory: dict[str, Any]) -> str:
    """Serialize activation inventory deterministically."""
    return json.dumps(inventory, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
