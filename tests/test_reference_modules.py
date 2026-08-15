# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for managed reference-module activation (CR-TK-01/02)."""

from __future__ import annotations

import pytest
import yaml
from rdflib import Graph

from kairos_ontology.core.reference_modules import (
    build_managed_import_plan,
    build_reference_module_context,
    load_accelerator_module_config,
)
from kairos_ontology.core.validator import run_validation

MODULE_IRI = "https://example.org/reference/orders"
TERM_NS = MODULE_IRI + "#"


def _write_reference_pack(tmp_path):
    ref_models = tmp_path / "reference-models"
    blueprint = ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint"
    blueprint.mkdir(parents=True)
    module = ref_models / "modules" / "orders.ttl"
    module.parent.mkdir()
    module.write_text(
        f"""\
@prefix ex: <{TERM_NS}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<{MODULE_IRI}> a owl:Ontology ; owl:versionInfo "2.1.0" .
ex:Order a owl:Class .
ex:SpecialOrder a owl:Class ; rdfs:subClassOf ex:Order .
ex:InternalOrder a owl:Class ; rdfs:subClassOf ex:Order .
ex:orderNumber a owl:DatatypeProperty ; rdfs:domain ex:Order .
ex:relatedOrder a owl:ObjectProperty ; rdfs:domain ex:Order ; rdfs:range ex:Order .
""",
        encoding="utf-8",
    )
    (blueprint / "data-domains.yaml").write_text(
        f"""\
schema_version: "2.0"
module_profiles:
  - id: orders
    ontology_iri: {MODULE_IRI}
    catalog_uri: {TERM_NS}
    version_pin: 2.1.0
    term_namespaces: [{TERM_NS}]
    root_classes: [{TERM_NS}Order]
    descendants:
      policy: all
      exclude: [{TERM_NS}InternalOrder]
    projection:
      allowlist: [{TERM_NS}Order]
    default_annotation_sources: [defaults/orders.ttl]
    local_extension_namespaces: [https://example.org/hub/orders#]
groups:
  - id: operations
    domains:
      - id: orders
        imports:
          - profile: orders
""",
        encoding="utf-8",
    )
    defaults = blueprint / "defaults" / "orders.ttl"
    defaults.parent.mkdir()
    defaults.write_text(
        f"""\
@prefix ex: <{TERM_NS}> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
ex:Order kairos-ext:scdType "2" .
""",
        encoding="utf-8",
    )
    catalog = ref_models / "catalog-v001.xml"
    catalog.write_text(
        f"""\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="{TERM_NS}" uri="modules/orders.ttl"/>
  <uri name="{MODULE_IRI}" uri="modules/orders.ttl"/>
</catalog>
""",
        encoding="utf-8",
    )
    return ref_models, catalog


def _add_unrelated_broken_module(ref_models):
    config_path = (
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint" / "data-domains.yaml"
    )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["module_profiles"].append(
        {
            "id": "broken",
            "ontology_iri": "https://example.org/reference/broken",
            "catalog_uri": "https://example.org/reference/broken",
            "version_pin": "1.0",
            "term_namespaces": ["https://example.org/reference/broken#"],
        }
    )
    data["groups"].append(
        {
            "id": "unrelated",
            "domains": [{"id": "billing", "imports": [{"profile": "broken"}]}],
        }
    )
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _domain_graph(*, imported: bool) -> Graph:
    import_line = f"owl:imports <{MODULE_IRI}> ;" if imported else ""
    graph = Graph()
    graph.parse(
        data=f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix hub: <https://example.org/hub/orders#> .
<https://example.org/hub/orders> a owl:Ontology ;
    {import_line}
    rdfs:label "Orders" .
hub:LocalOrder a owl:Class ; rdfs:subClassOf <{TERM_NS}SpecialOrder> .
""",
        format="turtle",
    )
    return graph


def _bare_ontology_graph(iri: str, *, imported_iri: str | None = None) -> Graph:
    """A minimal owl:Ontology graph with no authored term usage of any module."""
    import_line = f"owl:imports <{imported_iri}> ;" if imported_iri else ""
    graph = Graph()
    graph.parse(
        data=f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<{iri}> a owl:Ontology ;
    {import_line}
    rdfs:label "Bare" .
""",
        format="turtle",
    )
    return graph


def test_typed_profile_resolves_document_iri_and_version(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)

    config = load_accelerator_module_config(ref_models, "generic")
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )

    assert config.profiles[0].ontology_iri == MODULE_IRI
    assert config.profiles[0].version_pin == "2.1.0"
    assert context.modules[0].ontology_iri == MODULE_IRI
    assert context.modules[0].ontology_version == "2.1.0"
    assert context.diagnostics == ()


def test_domain_scoped_context_ignores_unrelated_broken_module(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    _add_unrelated_broken_module(ref_models)

    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
        requested_domains=["orders"],
    )

    assert [module.profile.id for module in context.modules] == ["orders"]
    assert context.diagnostics == ()


def test_profile_rejects_term_namespace_as_ontology_iri(tmp_path):
    ref_models, _catalog = _write_reference_pack(tmp_path)
    path = (
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint" / "data-domains.yaml"
    )
    path.write_text(
        f"""\
module_profiles:
  - id: invalid
    ontology_iri: {TERM_NS}
    version_pin: 1.0
groups: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="document IRI"):
        load_accelerator_module_config(ref_models, "generic")


def test_domain_activation_unions_profiles_across_groups(tmp_path):
    ref_models, _catalog = _write_reference_pack(tmp_path)
    path = (
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint" / "data-domains.yaml"
    )
    path.write_text(
        f"""\
module_profiles:
  - id: first
    ontology_iri: {MODULE_IRI}
    version_pin: 2.1.0
  - id: second
    ontology_iri: https://example.org/reference/second
    version_pin: 1.0
groups:
  - id: first-group
    domains:
      - id: orders
        imports: [{{profile: first}}]
  - id: second-group
    domains:
      - id: orders
        imports: [{{profile: second}}]
""",
        encoding="utf-8",
    )

    config = load_accelerator_module_config(ref_models, "generic")

    assert config.activation("orders").module_ids == ("first", "second")


def test_version_pin_mismatch_is_structured_error(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    path = (
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint" / "data-domains.yaml"
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace("version_pin: 2.1.0", "version_pin: 9.0"),
        encoding="utf-8",
    )

    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )

    assert context.modules == ()
    assert context.diagnostics[0].code == "module_version_mismatch"
    assert context.diagnostics[0].expected_ontology_iri == MODULE_IRI


def test_invalid_profile_default_annotations_are_blocking(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    defaults = (
        ref_models
        / "accelerator-packs"
        / "generic"
        / "client-hub-blueprint"
        / "defaults"
        / "orders.ttl"
    )
    defaults.write_text("not valid turtle [", encoding="utf-8")

    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )

    assert context.modules == ()
    assert context.diagnostics[0].code == "module_default_annotations_invalid"


def _set_profile_tier(ref_models, tier: str) -> None:
    """Inject a ``tier:`` key under the ``orders`` module profile written by
    ``_write_reference_pack``."""
    path = (
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint" / "data-domains.yaml"
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "version_pin: 2.1.0\n", f"version_pin: 2.1.0\n    tier: {tier}\n"
        ),
        encoding="utf-8",
    )


def test_tier_absent_defaults_to_required_and_missing_import_is_error(tmp_path):
    """Pins today's exact behavior: no accelerator anywhere sets ``tier:``, so a
    missing managed import must still be a hard error (issue #324)."""
    ref_models, catalog = _write_reference_pack(tmp_path)

    config = load_accelerator_module_config(ref_models, "generic")
    assert config.profiles[0].tier == "required"

    context = build_reference_module_context(ref_models, catalog_path=catalog, accelerator="generic")
    graph = _bare_ontology_graph("https://example.org/hub/orders")
    plan = build_managed_import_plan(domain="orders", context=context, ontology_graph=graph)

    assert plan.requirements[0].tier == "required"
    missing = [d for d in plan.diagnostics if d.code == "missing_managed_import"]
    assert missing
    assert all(d.level == "error" for d in missing)
    assert plan.blocking_diagnostics == tuple(missing)


def test_profile_tier_recommended_missing_import_is_warning(tmp_path, capsys):
    ref_models, catalog = _write_reference_pack(tmp_path)
    _set_profile_tier(ref_models, "recommended")

    config = load_accelerator_module_config(ref_models, "generic")
    assert config.profiles[0].tier == "recommended"

    context = build_reference_module_context(ref_models, catalog_path=catalog, accelerator="generic")
    graph = _bare_ontology_graph("https://example.org/hub/orders")
    plan = build_managed_import_plan(domain="orders", context=context, ontology_graph=graph)

    missing = [d for d in plan.diagnostics if d.code == "missing_managed_import"]
    assert missing
    assert all(d.level == "warning" for d in missing)
    assert plan.blocking_diagnostics == ()

    # A full `validate` run must not fail (without --degraded) when the only
    # finding is a missing "recommended"-tier managed import.
    ontologies_dir = tmp_path / "ontologies"
    ontologies_dir.mkdir()
    (ontologies_dir / "orders.ttl").write_text(
        """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<https://example.org/hub/orders> a owl:Ontology .
""",
        encoding="utf-8",
    )
    shapes_dir = tmp_path / "shapes"  # intentionally does not exist

    run_validation(
        ontologies_path=ontologies_dir,
        shapes_path=shapes_dir,
        catalog_path=catalog,
        do_syntax=False,
        do_shacl=True,
        do_consistency=False,
        ref_models_dir=ref_models,
        accelerator="generic",
    )

    captured = capsys.readouterr()
    assert "All validations passed" in captured.out


def test_profile_tier_optional_missing_import_is_warning(tmp_path):
    """Parity check for the "optional" tier alongside "recommended"."""
    ref_models, catalog = _write_reference_pack(tmp_path)
    _set_profile_tier(ref_models, "optional")

    config = load_accelerator_module_config(ref_models, "generic")
    assert config.profiles[0].tier == "optional"

    context = build_reference_module_context(ref_models, catalog_path=catalog, accelerator="generic")
    graph = _bare_ontology_graph("https://example.org/hub/orders")
    plan = build_managed_import_plan(domain="orders", context=context, ontology_graph=graph)

    missing = [d for d in plan.diagnostics if d.code == "missing_managed_import"]
    assert missing
    assert all(d.level == "warning" for d in missing)
    assert plan.blocking_diagnostics == ()


def test_invalid_tier_value_is_rejected(tmp_path):
    ref_models, _catalog = _write_reference_pack(tmp_path)
    _set_profile_tier(ref_models, "sometimes")

    with pytest.raises(ValueError, match="invalid tier"):
        load_accelerator_module_config(ref_models, "generic")


def test_domain_import_tier_override_beats_profile_default_for_that_domain_only(tmp_path):
    ref_models = tmp_path / "reference-models"
    blueprint = ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "data-domains.yaml").write_text(
        f"""\
module_profiles:
  - id: orders
    ontology_iri: {MODULE_IRI}
    version_pin: 2.1.0
    tier: optional
groups:
  - id: operations
    domains:
      - id: orders-a
        imports:
          - profile: orders
            tier: required
      - id: orders-b
        imports:
          - profile: orders
""",
        encoding="utf-8",
    )

    config = load_accelerator_module_config(ref_models, "generic")

    assert config.profile("orders").tier == "optional"
    assert config.activation("orders-a").module_tier_overrides == {"orders": "required"}
    assert config.activation("orders-b").module_tier_overrides == {}


def test_domain_activation_optional_merges_with_authored_required_to_required(tmp_path):
    """The same import required as "optional" (domain activation) and as
    "required" (genuine authored term usage) must merge to "required"/"error"."""
    ref_models, catalog = _write_reference_pack(tmp_path)
    _set_profile_tier(ref_models, "optional")

    context = build_reference_module_context(ref_models, catalog_path=catalog, accelerator="generic")
    # This graph authors a local class that subclasses ex:SpecialOrder, a term
    # actually owned by the "orders" module -- genuine authored term usage.
    graph = _domain_graph(imported=False)
    plan = build_managed_import_plan(domain="orders", context=context, ontology_graph=graph)

    assert len(plan.requirements) == 1
    assert plan.requirements[0].tier == "required"
    missing = [d for d in plan.diagnostics if d.code == "missing_managed_import"]
    assert missing
    assert all(d.level == "error" for d in missing)


def test_domain_activation_message_uses_activation_reason_not_configured_module(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)

    context = build_reference_module_context(ref_models, catalog_path=catalog, accelerator="generic")
    graph = _bare_ontology_graph("https://example.org/hub/orders")
    plan = build_managed_import_plan(domain="orders", context=context, ontology_graph=graph)

    missing = [d for d in plan.diagnostics if d.code == "missing_managed_import"]
    assert missing
    for diagnostic in missing:
        assert "Data-domain activation for" in diagnostic.message
        assert "orders" in diagnostic.message
        assert "(configured module)" not in diagnostic.message


def test_legacy_import_message_uses_readable_ontology_iri_not_internal_slug(tmp_path):
    ref_models = tmp_path / "reference-models"
    blueprint = ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint"
    blueprint.mkdir(parents=True)
    legacy_iri = "https://example.org/legacy/imo-party"
    legacy_ns = legacy_iri + "#"
    module = ref_models / "modules" / "party.ttl"
    module.parent.mkdir()
    module.write_text(
        f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<{legacy_iri}> a owl:Ontology .
""",
        encoding="utf-8",
    )
    (blueprint / "data-domains.yaml").write_text(
        f"""\
module_profiles: []
groups:
  - id: legacy-group
    domains:
      - id: party
        imports:
          - uri: {legacy_ns}
            module: imo-party
""",
        encoding="utf-8",
    )
    catalog = ref_models / "catalog-v001.xml"
    catalog.write_text(
        f"""\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="{legacy_ns}" uri="modules/party.ttl"/>
  <uri name="{legacy_iri}" uri="modules/party.ttl"/>
</catalog>
""",
        encoding="utf-8",
    )

    config = load_accelerator_module_config(ref_models, "generic")
    assert config.profiles[0].id == "legacy-imo-party"

    context = build_reference_module_context(ref_models, catalog_path=catalog, accelerator="generic")
    assert context.diagnostics == ()
    assert context.modules[0].ontology_iri == legacy_iri

    graph = _bare_ontology_graph("https://example.org/hub/party")
    plan = build_managed_import_plan(domain="party", context=context, ontology_graph=graph)

    missing = [d for d in plan.diagnostics if d.code == "missing_managed_import"]
    assert missing
    for diagnostic in missing:
        # The structured field stays the raw internal id...
        assert diagnostic.managed_source == "legacy-imo-party"
        # ...but the human-facing message prose must be readable instead.
        assert legacy_iri in diagnostic.message
        assert "legacy-imo-party" not in diagnostic.message


# ---------------------------------------------------------------------------
# Issue #426 (DD-155): Managed Import Completeness is mode-independent.
# ---------------------------------------------------------------------------

_SYNTAX_CLEAN_ORDERS_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://example.org/hub/orders> a owl:Ontology ;
    rdfs:label "Orders"@en ;
    rdfs:comment "Orders domain missing its required managed import."@en ;
    owl:versionInfo "0.1.0" .
"""


def _syntax_only_hub(tmp_path):
    """An ontologies dir whose one domain is naming-clean but import-incomplete."""
    ontologies_dir = tmp_path / "ontologies"
    ontologies_dir.mkdir()
    (ontologies_dir / "orders.ttl").write_text(_SYNTAX_CLEAN_ORDERS_TTL, encoding="utf-8")
    return ontologies_dir


def test_missing_managed_import_fails_a_syntax_only_run(tmp_path, capsys):
    """`validate --syntax` must run the managed-import check when reference models
    resolve — the accidental `--shacl`/`--consistency` gate let Gate 5's inner-loop
    command register four green gates on an unactivated domain (#426)."""
    ref_models, catalog = _write_reference_pack(tmp_path)
    ontologies_dir = _syntax_only_hub(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=tmp_path / "shapes",  # intentionally does not exist
            catalog_path=catalog,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
            ref_models_dir=ref_models,
            accelerator="generic",
        )

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "Managed Import Completeness" in out
    assert "missing/invalid import(s)" in out


def test_degraded_syntax_only_run_accepts_missing_managed_import(tmp_path, capsys):
    """`--degraded` semantics are unchanged and now also apply to --syntax runs."""
    ref_models, catalog = _write_reference_pack(tmp_path)
    ontologies_dir = _syntax_only_hub(tmp_path)

    run_validation(
        ontologies_path=ontologies_dir,
        shapes_path=tmp_path / "shapes",
        catalog_path=catalog,
        do_syntax=True,
        do_shacl=False,
        do_consistency=False,
        ref_models_dir=ref_models,
        accelerator="generic",
        degraded=True,
    )

    out = capsys.readouterr().out
    assert "degraded mode accepted" in out
    assert "All validations passed" in out


def test_syntax_only_run_without_reference_models_prints_no_imports_section(tmp_path, capsys):
    """Resolvability short-circuit: with no reference models (None, or a missing
    directory) the pre-pass, the section header, and the loop are all skipped, so
    a no-refmodels --syntax run keeps byte-identical output."""
    ontologies_dir = _syntax_only_hub(tmp_path)

    for ref_models_dir in (None, tmp_path / "does-not-exist"):
        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=tmp_path / "shapes",
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False,
            ref_models_dir=ref_models_dir,
        )
        out = capsys.readouterr().out
        assert "Managed Import Completeness" not in out
        assert "All validations passed" in out

# ---------------------------------------------------------------------------
# Issue #418 (DD-157): surplus-managed-import warning.
# surplus = authored direct imports ∩ managed-module IRIs − plan requirement IRIs
# ---------------------------------------------------------------------------

EXTRAS_IRI = "https://example.org/reference/extras"
EXTRAS_NS = EXTRAS_IRI + "#"


def _add_extras_module(ref_models, catalog, *, assigned_domain: str | None = "billing"):
    """A second, fully resolvable managed module, assigned to *assigned_domain*
    (or to no domain at all when ``None``)."""
    module = ref_models / "modules" / "extras.ttl"
    module.write_text(
        f"""\
@prefix ex2: <{EXTRAS_NS}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<{EXTRAS_IRI}> a owl:Ontology ; owl:versionInfo "1.0" .
ex2:Widget a owl:Class .
""",
        encoding="utf-8",
    )
    config_path = (
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint" / "data-domains.yaml"
    )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["module_profiles"].append(
        {
            "id": "extras",
            "ontology_iri": EXTRAS_IRI,
            "catalog_uri": EXTRAS_NS,
            "version_pin": "1.0",
            "term_namespaces": [EXTRAS_NS],
        }
    )
    if assigned_domain:
        data["groups"].append(
            {
                "id": "extras-group",
                "domains": [{"id": assigned_domain, "imports": [{"profile": "extras"}]}],
            }
        )
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    catalog.write_text(
        catalog.read_text(encoding="utf-8").replace(
            "</catalog>",
            f'  <uri name="{EXTRAS_NS}" uri="modules/extras.ttl"/>\n'
            f'  <uri name="{EXTRAS_IRI}" uri="modules/extras.ttl"/>\n'
            "</catalog>",
        ),
        encoding="utf-8",
    )


def _orders_graph_with_imports(*imports: str, use_extras_term: bool = False) -> Graph:
    import_lines = "".join(f"    owl:imports <{iri}> ;\n" for iri in imports)
    term_line = (
        f"hub:LocalWidget a owl:Class ; rdfs:subClassOf <{EXTRAS_NS}Widget> .\n"
        if use_extras_term
        else ""
    )
    graph = Graph()
    graph.parse(
        data=f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix hub: <https://example.org/hub/orders#> .
<https://example.org/hub/orders> a owl:Ontology ;
{import_lines}    rdfs:label "Orders" .
{term_line}""",
        format="turtle",
    )
    return graph


def test_surplus_import_of_another_domains_module_is_a_warning_naming_the_owner(tmp_path):
    """`orders` authors an import of the `extras` module, which the blueprint
    assigns only to `billing` and which the plan does not require — a warning
    that names the module and its owning domain(s). The scoped context does NOT
    resolve `extras` (managedness must match against config.profiles, not
    context.modules — the init gate's scoped context has the same shape)."""
    ref_models, catalog = _write_reference_pack(tmp_path)
    _add_extras_module(ref_models, catalog, assigned_domain="billing")

    context = build_reference_module_context(
        ref_models, catalog_path=catalog, accelerator="generic", requested_domains=["orders"]
    )
    assert context.module("extras") is None  # scoped context: not resolved, still managed
    graph = _orders_graph_with_imports(MODULE_IRI, EXTRAS_IRI)
    plan = build_managed_import_plan(domain="orders", context=context, ontology_graph=graph)

    surplus = [d for d in plan.diagnostics if d.code == "surplus_managed_import"]
    assert len(surplus) == 1
    assert surplus[0].level == "warning"
    assert surplus[0].managed_source == "extras"
    assert "billing" in surplus[0].message
    # The required (activation-backed, present) import never appears as surplus.
    assert all(d.managed_source != "orders" for d in surplus)
    # No missing-import errors either: the required import is authored.
    assert [d for d in plan.diagnostics if d.code == "missing_managed_import"] == []
    # Warning-severity only: nothing blocks.
    assert plan.blocking_diagnostics == ()


def test_surplus_import_of_module_assigned_to_no_domain_says_so(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    _add_extras_module(ref_models, catalog, assigned_domain=None)

    context = build_reference_module_context(
        ref_models, catalog_path=catalog, accelerator="generic", requested_domains=["orders"]
    )
    graph = _orders_graph_with_imports(MODULE_IRI, EXTRAS_IRI)
    plan = build_managed_import_plan(domain="orders", context=context, ontology_graph=graph)

    surplus = [d for d in plan.diagnostics if d.code == "surplus_managed_import"]
    assert len(surplus) == 1
    assert "assigns it to no domain" in surplus[0].message


def test_cross_module_term_use_import_is_a_requirement_not_surplus(tmp_path):
    """A non-activated module whose term the domain genuinely uses becomes a plan
    requirement (authored-local-dependency) — its import must never warn."""
    ref_models, catalog = _write_reference_pack(tmp_path)
    _add_extras_module(ref_models, catalog, assigned_domain="billing")

    # Mirror the validator/init-gate context: authored imports select modules too.
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
        requested_domains=["orders"],
        imported_ontology_iris=[EXTRAS_IRI],
    )
    assert context.module("extras") is not None
    graph = _orders_graph_with_imports(MODULE_IRI, EXTRAS_IRI, use_extras_term=True)
    plan = build_managed_import_plan(domain="orders", context=context, ontology_graph=graph)

    assert [d for d in plan.diagnostics if d.code == "surplus_managed_import"] == []
    assert [d for d in plan.diagnostics if d.code == "missing_managed_import"] == []


def test_required_activation_imports_alone_never_warn(tmp_path):
    """Baseline: only required imports authored → zero surplus diagnostics."""
    ref_models, catalog = _write_reference_pack(tmp_path)

    context = build_reference_module_context(ref_models, catalog_path=catalog, accelerator="generic")
    graph = _orders_graph_with_imports(MODULE_IRI)
    plan = build_managed_import_plan(domain="orders", context=context, ontology_graph=graph)

    assert [d for d in plan.diagnostics if d.code == "surplus_managed_import"] == []


def test_surplus_import_warning_does_not_fail_a_validate_run(tmp_path, capsys):
    """The warning flows through the validator's existing warning path and never
    flips the exit: `validate --syntax` prints it and still passes."""
    ref_models, catalog = _write_reference_pack(tmp_path)
    _add_extras_module(ref_models, catalog, assigned_domain="billing")

    ontologies_dir = tmp_path / "ontologies"
    ontologies_dir.mkdir()
    (ontologies_dir / "orders.ttl").write_text(
        f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://example.org/hub/orders> a owl:Ontology ;
    owl:imports <{MODULE_IRI}> ;
    owl:imports <{EXTRAS_IRI}> ;
    rdfs:label "Orders"@en ;
    rdfs:comment "Orders domain with one required and one surplus managed import."@en ;
    owl:versionInfo "0.1.0" .
""",
        encoding="utf-8",
    )

    run_validation(
        ontologies_path=ontologies_dir,
        shapes_path=tmp_path / "shapes",  # intentionally does not exist
        catalog_path=catalog,
        do_syntax=True,
        do_shacl=False,
        do_consistency=False,
        ref_models_dir=ref_models,
        accelerator="generic",
    )

    out = capsys.readouterr().out
    assert "surplus" in out.lower() or "extras" in out
    assert "billing" in out
    assert "All validations passed" in out


# ---------------------------------------------------------------------------
# Issue #441: term_owner_ambiguous — when two managed modules publish the same
# class IRI, the diagnostic severity depends on whether ALL candidate modules
# are already required imports for the domain.
# ---------------------------------------------------------------------------

CLONE_IRI = "https://example.org/reference/clone"
CLONE_NS = CLONE_IRI + "#"


def _add_clone_module(ref_models, catalog, *, assigned_domain: str | None = "orders"):
    """A second managed module that publishes the *same* class IRI as the orders
    module (``<MODULE_IRI>#Order``), creating a term_owner_ambiguous situation."""
    module = ref_models / "modules" / "clone.ttl"
    module.write_text(
        f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<{CLONE_IRI}> a owl:Ontology ; owl:versionInfo "1.0" .
<{TERM_NS}Order> a owl:Class .
""",
        encoding="utf-8",
    )
    config_path = (
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint" / "data-domains.yaml"
    )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["module_profiles"].append(
        {
            "id": "clone",
            "ontology_iri": CLONE_IRI,
            "catalog_uri": CLONE_NS,
            "version_pin": "1.0",
            "term_namespaces": [TERM_NS],  # same namespace: duplicate class IRI
        }
    )
    if assigned_domain:
        data["groups"].append(
            {
                "id": "clone-group",
                "domains": [{"id": assigned_domain, "imports": [{"profile": "clone"}]}],
            }
        )
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    catalog.write_text(
        catalog.read_text(encoding="utf-8").replace(
            "</catalog>",
            f'  <uri name="{CLONE_NS}" uri="modules/clone.ttl"/>\n'
            f'  <uri name="{CLONE_IRI}" uri="modules/clone.ttl"/>\n'
            "</catalog>",
        ),
        encoding="utf-8",
    )


def _orders_graph_using_shared_class(*imports: str) -> Graph:
    """A domain graph that uses the shared class IRI, triggering term-owner
    resolution."""
    import_lines = "".join(f"    owl:imports <{iri}> ;\n" for iri in imports)
    graph = Graph()
    graph.parse(
        data=f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix hub: <https://example.org/hub/orders#> .
<https://example.org/hub/orders> a owl:Ontology ;
{import_lines}    rdfs:label "Orders" .
hub:LocalOrder a owl:Class ; rdfs:subClassOf <{TERM_NS}Order> .
""",
        format="turtle",
    )
    return graph


def test_term_owner_ambiguous_downgrades_to_warning_when_all_candidates_required(tmp_path):
    """When both modules publishing a shared IRI are required imports for the
    domain (the activation loop adds them), the ambiguity cannot change the
    completeness verdict → warning, not error (issue #441)."""
    ref_models, catalog = _write_reference_pack(tmp_path)
    # Add a second module that publishes the same class IRI, assigned to the
    # same domain — both are required imports.
    _add_clone_module(ref_models, catalog, assigned_domain="orders")

    context = build_reference_module_context(
        ref_models, catalog_path=catalog, accelerator="generic", requested_domains=["orders"]
    )
    graph = _orders_graph_using_shared_class(MODULE_IRI, CLONE_IRI)
    plan = build_managed_import_plan(domain="orders", context=context, ontology_graph=graph)

    ambiguous = [d for d in plan.diagnostics if d.code == "term_owner_ambiguous"]
    assert len(ambiguous) == 1
    assert ambiguous[0].level == "warning"
    assert "orders" in ambiguous[0].message
    assert "clone" in ambiguous[0].message
    # Warning-only: does not block.
    assert all(d.level != "error" for d in plan.diagnostics if d.code == "term_owner_ambiguous")


def _add_clone_module_alone(ref_models, catalog):
    """A second managed module that publishes the *same* class IRI
    (``<MODULE_IRI>#Order``) as the orders module, assigned only to the
    ``billing`` domain — creating a term_owner_ambiguous situation."""
    module = ref_models / "modules" / "clone.ttl"
    module.write_text(
        f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<{CLONE_IRI}> a owl:Ontology ; owl:versionInfo "1.0" .
<{TERM_NS}Order> a owl:Class .
""",
        encoding="utf-8",
    )
    config_path = (
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint" / "data-domains.yaml"
    )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["module_profiles"].append(
        {
            "id": "clone",
            "ontology_iri": CLONE_IRI,
            "catalog_uri": CLONE_NS,
            "version_pin": "1.0",
            "term_namespaces": [TERM_NS],  # same namespace: duplicate class IRI
        }
    )
    # Add an empty-activation "other" domain alongside the existing groups.
    data["groups"].append(
        {
            "id": "ambiguous-group",
            "domains": [
                {"id": "billing", "imports": [{"profile": "clone"}]},
                {"id": "other", "imports": []},
            ],
        }
    )
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    catalog.write_text(
        catalog.read_text(encoding="utf-8").replace(
            "</catalog>",
            f'  <uri name="{CLONE_NS}" uri="modules/clone.ttl"/>\n'
            f'  <uri name="{CLONE_IRI}" uri="modules/clone.ttl"/>\n'
            "</catalog>",
        ),
        encoding="utf-8",
    )


def test_term_owner_ambiguous_remains_error_when_not_all_candidates_required(tmp_path):
    """When modules publishing a shared IRI are NOT required imports for the
    domain (neither is activated), the ambiguity is a real problem → error
    (issue #441)."""
    ref_models, catalog = _write_reference_pack(tmp_path)
    _add_clone_module_alone(ref_models, catalog)

    # "other" domain has empty imports; both modules are in scope via
    # imported_ontology_iris but neither is activated, so neither is a
    # required import.
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
        requested_domains=["other"],
        imported_ontology_iris=[MODULE_IRI, CLONE_IRI],
    )
    graph = Graph()
    graph.parse(
        data=f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix hub: <https://example.org/hub/other#> .
<https://example.org/hub/other> a owl:Ontology ;
    owl:imports <{MODULE_IRI}> ;
    owl:imports <{CLONE_IRI}> ;
    rdfs:label "Other" .
hub:LocalOrder a owl:Class ; rdfs:subClassOf <{TERM_NS}Order> .
""",
        format="turtle",
    )
    plan = build_managed_import_plan(domain="other", context=context, ontology_graph=graph)

    ambiguous = [d for d in plan.diagnostics if d.code == "term_owner_ambiguous"]
    assert len(ambiguous) == 1
    assert ambiguous[0].level == "error"
