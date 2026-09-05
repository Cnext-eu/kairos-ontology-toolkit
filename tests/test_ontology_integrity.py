# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Hub-wide ontology integrity checks (DD-163).

The fixtures below are miniatures of the defect classes found in a real 21-domain
autopilot run: a concept minted locally in several domains, a class the file's own
header excludes, a class the blueprint's ``does_not_own`` places elsewhere, an address
value object flattened into scalars, and an import nothing references.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kairos_ontology.core.ontology_integrity import (
    BLOCKING_CODES,
    audit_ontology_integrity,
    check_collapsed_value_objects,
    check_cross_domain_duplicates,
    check_declared_exclusions,
    check_external_terms_resolve,
    check_reference_model_shadowing,
    check_unanchored_classes,
    check_unused_imports,
    class_named_in_prose,
    extract_header_exclusions,
    parse_excluded_subjects,
    scan_hub_ontologies,
)

_PREFIXES = """\
@prefix : <https://example.com/ont/{domain}#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://example.com/ont/{domain}> a owl:Ontology ;
    rdfs:label "{domain} ontology"@en ;
    owl:versionInfo "1.0.0" .
"""


def _klass(name: str) -> str:
    return (
        f"\n:{name} a owl:Class ;\n"
        f'    rdfs:label "{name}"@en ;\n'
        f'    rdfs:comment "The {name} concept."@en .\n'
    )


def _datatype_property(name: str, domain_class: str) -> str:
    return (
        f"\n:{name} a owl:DatatypeProperty ;\n"
        f'    rdfs:label "{name}"@en ;\n'
        f"    rdfs:domain :{domain_class} ;\n"
        f"    rdfs:range xsd:string .\n"
    )


def _write_domain(
    directory: Path,
    domain: str,
    *,
    classes: tuple[str, ...] = (),
    properties: tuple[tuple[str, str], ...] = (),
    header: str = "",
    imports: tuple[str, ...] = (),
) -> Path:
    body = header + _PREFIXES.format(domain=domain)
    if imports:
        joined = " ,\n        ".join(f"<{iri}>" for iri in imports)
        body = body.rstrip(" .\n") + f" ;\n    owl:imports {joined} .\n"
    for name in classes:
        body += _klass(name)
    for prop, owner in properties:
        body += _datatype_property(prop, owner)
    path = directory / f"{domain}.ttl"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Prose matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("class_name", "prose", "expected"),
    [
        ("Booking", "Contracts, bookings, invoices, or terminal moves.", True),
        # Head-noun matching is the point: prefixing a leaked class with the local
        # domain name is the commonest way a boundary is crossed while looking clean.
        ("IntermodalBooking", "Contracts, bookings, invoices.", True),
        ("TerminalBooking", "bookings", True),
        ("Consignment", "Contracts, bookings, invoices.", False),
        ("Party", "Contracts, bookings, invoices.", False),
        # Short head nouns cannot match; too collision-prone to block on.
        ("Leg", "legs and moves", False),
        ("Booking", "", False),
    ],
)
def test_class_named_in_prose(class_name: str, prose: str, expected: bool) -> None:
    assert class_named_in_prose(class_name, prose) is expected


def test_extract_header_exclusions_reads_the_exemplar_block() -> None:
    text = (
        "# Domain: party\n"
        "#\n"
        "# Deliberate exclusions (with reasons):\n"
        "#   - Party bookings: owned by the booking domain; party may participate\n"
        "#     in bookings but does not own the reservation lifecycle\n"
        "#\n"
        "@prefix : <https://example.com/ont/party#> .\n"
    )
    block = extract_header_exclusions(text)
    assert "Party bookings" in block
    assert "booking domain" in block


def test_extract_header_exclusions_absent_block_is_a_no_op() -> None:
    assert extract_header_exclusions("# Domain: party\n@prefix : <x> .\n") == ""


def test_parse_excluded_subjects_ignores_self_owned_clarifications() -> None:
    """A bullet naming *this* domain as owner defends a class; it does not exclude it."""
    block = (
        "- MDM company master: owned by the mdm domain; party defines the role model\n"
        "- Contact details: owned by the party domain as PII satellites\n"
        "- Party bookings: owned by the booking domain; party may participate\n"
    )
    subjects = parse_excluded_subjects(block, domain="party")
    owners = {owner for _, owner in subjects}
    assert owners == {"mdm", "booking"}
    assert not any("Contact details" in subject for subject, _ in subjects)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def test_cross_domain_duplicate_is_reported_once_per_declaring_domain(tmp_path: Path) -> None:
    _write_domain(tmp_path, "party", classes=("Party", "Booking"))
    _write_domain(tmp_path, "booking", classes=("Booking",))
    _write_domain(tmp_path, "mdm", classes=("Booking",))

    diagnostics = check_cross_domain_duplicates(scan_hub_ontologies(tmp_path))

    assert {d.domain for d in diagnostics} == {"party", "booking", "mdm"}
    assert all(d.level == "error" for d in diagnostics)
    assert all("Booking" in d.message for d in diagnostics)
    # Party is declared once, so it must not be flagged.
    assert not any(d.term_uri and d.term_uri.endswith("#Party") for d in diagnostics)


def test_unique_classes_produce_no_duplicate_diagnostics(tmp_path: Path) -> None:
    _write_domain(tmp_path, "party", classes=("Party",))
    _write_domain(tmp_path, "booking", classes=("Booking",))
    assert check_cross_domain_duplicates(scan_hub_ontologies(tmp_path)) == []


def test_declared_exclusion_violation_is_flagged(tmp_path: Path) -> None:
    header = (
        "# Deliberate exclusions (with reasons):\n"
        "#   - Party bookings: owned by the booking domain\n"
        "#\n"
    )
    _write_domain(tmp_path, "party", classes=("Party", "Booking"), header=header)

    diagnostics = check_declared_exclusions(scan_hub_ontologies(tmp_path))

    assert len(diagnostics) == 1
    assert diagnostics[0].term_uri.endswith("#Booking")
    assert diagnostics[0].level == "error"


def test_self_owned_header_bullet_does_not_flag_its_own_class(tmp_path: Path) -> None:
    """Regression: 'Contact details: owned by the party domain' defends :Contact."""
    header = (
        "# Deliberate exclusions (with reasons):\n"
        "#   - Contact details: owned by the party domain as PII satellites\n"
        "#\n"
    )
    _write_domain(tmp_path, "party", classes=("Contact",), header=header)
    assert check_declared_exclusions(scan_hub_ontologies(tmp_path)) == []


def test_domain_name_in_subject_phrase_does_not_flag_the_domain_class(tmp_path: Path) -> None:
    """Regression: 'Party bookings' must flag :Booking, never :Party."""
    header = (
        "# Deliberate exclusions (with reasons):\n"
        "#   - Party bookings: owned by the booking domain\n"
        "#\n"
    )
    _write_domain(tmp_path, "party", classes=("Party", "Booking"), header=header)

    flagged = {
        d.term_uri.rsplit("#", 1)[1]
        for d in check_declared_exclusions(scan_hub_ontologies(tmp_path))
    }
    assert flagged == {"Booking"}


def test_blueprint_boundary_violation_is_flagged(tmp_path: Path) -> None:
    _write_domain(tmp_path, "party", classes=("Party", "Booking"))
    data_domains = {
        "party": {
            "owns": "Legal entities, customers, suppliers, contacts, roles.",
            "does_not_own": "Contracts, bookings, invoices, operational events.",
        }
    }
    report = audit_ontology_integrity(ontologies_dir=tmp_path, data_domains=data_domains)
    codes = {d.code for d in report.diagnostics}
    assert "integrity.class-outside-blueprint-boundary" in codes
    offenders = {
        d.term_uri.rsplit("#", 1)[1]
        for d in report.diagnostics
        if d.code == "integrity.class-outside-blueprint-boundary"
    }
    assert offenders == {"Booking"}


def test_unused_import_is_flagged_and_a_referenced_one_is_not(tmp_path: Path) -> None:
    used = "https://www.kairosflow.ai/ont/bsp/party"
    unused = "https://www.kairosflow.ai/ont/imo/party"
    path = _write_domain(tmp_path, "party", classes=("Party",), imports=(used, unused))
    # Anchor the local class into the module that should count as used.
    path.write_text(
        path.read_text(encoding="utf-8") + f"\n:Party rdfs:subClassOf <{used}#TradeParty> .\n",
        encoding="utf-8",
    )

    diagnostics = check_unused_imports(scan_hub_ontologies(tmp_path))

    assert [d.term_uri for d in diagnostics] == [unused]


def test_owl_imports_triple_does_not_count_as_using_the_module(tmp_path: Path) -> None:
    """Regression: the import statement itself must not mark the module as used."""
    module = "https://www.kairosflow.ai/ont/bsp/party"
    _write_domain(tmp_path, "party", classes=("Party",), imports=(module,))
    assert [d.term_uri for d in check_unused_imports(scan_hub_ontologies(tmp_path))] == [module]


def test_collapsed_address_value_object_is_flagged(tmp_path: Path) -> None:
    _write_domain(
        tmp_path,
        "party",
        classes=("Company",),
        properties=(
            ("companyBillingAddress", "Company"),
            ("companyBillingCity", "Company"),
            ("companyBillingCountry", "Company"),
            ("companyBillingPostalCode", "Company"),
        ),
    )
    diagnostics = check_collapsed_value_objects(scan_hub_ontologies(tmp_path))
    assert len(diagnostics) == 1
    assert diagnostics[0].level == "warning"
    assert "companyBillingCity" in diagnostics[0].message


def test_two_address_scalars_are_below_the_cluster_threshold(tmp_path: Path) -> None:
    _write_domain(
        tmp_path,
        "party",
        classes=("Company",),
        properties=(("companyBillingAddress", "Company"), ("companyBillingCity", "Company")),
    )
    assert check_collapsed_value_objects(scan_hub_ontologies(tmp_path)) == []


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_clean_hub_scores_perfectly_and_is_not_blocking(tmp_path: Path) -> None:
    module = "https://www.kairosflow.ai/ont/bsp/party"
    path = _write_domain(tmp_path, "party", classes=("Party",), imports=(module,))
    path.write_text(
        path.read_text(encoding="utf-8") + f"\n:Party rdfs:subClassOf <{module}#TradeParty> .\n",
        encoding="utf-8",
    )
    _write_domain(tmp_path, "booking", classes=("Booking",))

    report = audit_ontology_integrity(ontologies_dir=tmp_path, data_domains={})

    assert report.is_blocking is False
    assert report.scores()["class_uniqueness"] == 1.0
    assert report.scores()["import_utilisation"] == 1.0


def test_report_scopes_diagnostics_to_requested_domains(tmp_path: Path) -> None:
    _write_domain(tmp_path, "party", classes=("Booking",))
    _write_domain(tmp_path, "mdm", classes=("Booking",))

    report = audit_ontology_integrity(ontologies_dir=tmp_path, data_domains={}, domains=["party"])

    assert {d.domain for d in report.diagnostics} == {"party"}
    # The duplicate is still *detected* hub-wide; only reporting is scoped.
    assert any(d.code == "integrity.class-redeclared-across-domains" for d in report.diagnostics)


def test_underscore_prefixed_files_are_not_treated_as_domains(tmp_path: Path) -> None:
    _write_domain(tmp_path, "party", classes=("Party",))
    _write_domain(tmp_path, "_master", classes=("Party",))
    report = audit_ontology_integrity(ontologies_dir=tmp_path, data_domains={})
    assert report.domains_scanned == 1
    assert report.duplicate_class_declarations == 0


def test_empty_directory_reports_a_notice_not_a_failure(tmp_path: Path) -> None:
    report = audit_ontology_integrity(ontologies_dir=tmp_path, data_domains={})
    assert report.is_blocking is False
    assert report.notices


def test_blocking_codes_are_exactly_the_error_level_checks(tmp_path: Path) -> None:
    header = (
        "# Deliberate exclusions (with reasons):\n"
        "#   - Party bookings: owned by the booking domain\n"
        "#\n"
    )
    _write_domain(tmp_path, "party", classes=("Booking",), header=header)
    _write_domain(tmp_path, "booking", classes=("Booking",))

    report = audit_ontology_integrity(
        ontologies_dir=tmp_path,
        data_domains={"party": {"does_not_own": "bookings and invoices"}},
    )
    assert {d.code for d in report.errors} <= BLOCKING_CODES
    assert all(d.code not in BLOCKING_CODES for d in report.warnings)


def test_scaffold_placeholder_bullet_flags_nothing(tmp_path: Path) -> None:
    """The seeded '- <Concept>: owned by the <other> domain' example must be inert.

    scaffold-domain writes it so an author extends the block in the enforceable form;
    it must never itself exclude anything.
    """
    header = (
        "# Deliberate exclusions (with reasons):\n"
        "#   Blueprint DOES NOT OWN: Contracts, bookings, invoices.\n"
        "#   Record each concept you leave out as its own bullet, in this\n"
        "#   form, so 'kairos-ontology validate' can enforce it:\n"
        "#     - <Concept>: owned by the <other> domain; <why>\n"
        "#\n"
    )
    _write_domain(tmp_path, "party", classes=("Party", "Booking"), header=header)
    assert check_declared_exclusions(scan_hub_ontologies(tmp_path)) == []


def test_author_filled_bullet_under_scaffold_header_is_enforced(tmp_path: Path) -> None:
    """Filling the seeded form in makes the exclusion enforceable, which is the point."""
    header = (
        "# Deliberate exclusions (with reasons):\n"
        "#   Blueprint DOES NOT OWN: Contracts, bookings, invoices.\n"
        "#     - Bookings: owned by the booking domain; party only participates\n"
        "#\n"
    )
    _write_domain(tmp_path, "party", classes=("Party", "Booking"), header=header)
    flagged = {
        d.term_uri.rsplit("#", 1)[1]
        for d in check_declared_exclusions(scan_hub_ontologies(tmp_path))
    }
    assert flagged == {"Booking"}


def test_unauthored_scaffold_does_not_warn_about_its_own_imports(tmp_path: Path) -> None:
    """A scaffolded domain with no classes yet cannot use its blueprint imports."""
    _write_domain(
        tmp_path, "party", classes=(), imports=("https://www.kairosflow.ai/ont/bsp/party",)
    )
    assert check_unused_imports(scan_hub_ontologies(tmp_path)) == []


def test_authored_domain_still_warns_about_unused_imports(tmp_path: Path) -> None:
    module = "https://www.kairosflow.ai/ont/bsp/party"
    _write_domain(tmp_path, "party", classes=("Party",), imports=(module,))
    assert [d.term_uri for d in check_unused_imports(scan_hub_ontologies(tmp_path))] == [module]


def test_degradable_and_non_degradable_codes_partition_the_blocking_set() -> None:
    from kairos_ontology.core.ontology_integrity import (
        DEGRADABLE_CODES,
        NON_DEGRADABLE_CODES,
    )

    assert NON_DEGRADABLE_CODES | DEGRADABLE_CODES == BLOCKING_CODES
    assert not (NON_DEGRADABLE_CODES & DEGRADABLE_CODES)
    # The two failures a hub can always fix itself must not be bypassable, or fleet mode
    # clears the whole defect class with one flag.
    assert "integrity.class-redeclared-across-domains" in NON_DEGRADABLE_CODES
    assert "integrity.class-violates-declared-exclusion" in NON_DEGRADABLE_CODES


# ---------------------------------------------------------------------------
# External term resolution
# ---------------------------------------------------------------------------

_MODULE = "https://www.kairosflow.ai/ont/mmt/cargo"
_TERMS = {_MODULE: {"classes": {"CargoItem"}, "properties": {"cargoDescription"}}}


def _with_extra(path: Path, extra: str) -> Path:
    path.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8")
    return path


def test_a_typod_term_in_an_imported_module_is_flagged(tmp_path: Path) -> None:
    """The mistake nothing else catches.

    The namespace IS imported, so missing_managed_import is satisfied and silent; the
    term simply does not exist. Before this check the file validated clean.
    """
    path = _write_domain(tmp_path, "cargo", classes=("Item",), imports=(_MODULE,))
    _with_extra(path, f"\n:Item rdfs:subClassOf <{_MODULE}#CargoIteem> .\n")

    diagnostics = check_external_terms_resolve(scan_hub_ontologies(tmp_path), _TERMS)

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "integrity.external-term-unresolved"
    assert diagnostics[0].level == "error"
    assert "CargoIteem" in diagnostics[0].message


def test_a_term_that_exists_is_not_flagged(tmp_path: Path) -> None:
    path = _write_domain(tmp_path, "cargo", classes=("Item",), imports=(_MODULE,))
    _with_extra(path, f"\n:Item rdfs:subClassOf <{_MODULE}#CargoItem> .\n")

    assert check_external_terms_resolve(scan_hub_ontologies(tmp_path), _TERMS) == []


def test_a_property_name_counts_as_a_term(tmp_path: Path) -> None:
    """subPropertyOf resolves against the module's properties, not only its classes."""
    path = _write_domain(tmp_path, "cargo", classes=("Item",), imports=(_MODULE,))
    _with_extra(
        path,
        "\n:describes a owl:DatatypeProperty ; rdfs:domain :Item ;\n"
        f"    rdfs:subPropertyOf <{_MODULE}#cargoDescription> .\n",
    )

    assert check_external_terms_resolve(scan_hub_ontologies(tmp_path), _TERMS) == []


def test_an_unmanaged_module_is_left_to_the_import_check(tmp_path: Path) -> None:
    """A module the catalog never resolved is missing_managed_import's business.

    Reporting it here too would produce two errors for one mistake.
    """
    other = "https://example.org/not-managed"
    path = _write_domain(tmp_path, "cargo", classes=("Item",), imports=(other,))
    _with_extra(path, f"\n:Item rdfs:subClassOf <{other}#Whatever> .\n")

    assert check_external_terms_resolve(scan_hub_ontologies(tmp_path), _TERMS) == []


def test_no_catalog_means_no_judgement(tmp_path: Path) -> None:
    """Empty module_terms is 'no basis to judge', matching the shadowing check."""
    path = _write_domain(tmp_path, "cargo", classes=("Item",), imports=(_MODULE,))
    _with_extra(path, f"\n:Item rdfs:subClassOf <{_MODULE}#CargoIteem> .\n")

    assert check_external_terms_resolve(scan_hub_ontologies(tmp_path), {}) == []


def test_the_code_is_degradable_not_hard_blocking(tmp_path: Path) -> None:
    """Same defect class as missing_managed_import, which is deliberately degradable.

    A stricter sibling for the same mistake would also newly block `compile`, which
    consults NON_DEGRADABLE_CODES only.
    """
    from kairos_ontology.core.ontology_integrity import (
        DEGRADABLE_CODES,
        NON_DEGRADABLE_CODES,
    )

    assert "integrity.external-term-unresolved" in DEGRADABLE_CODES
    assert "integrity.external-term-unresolved" not in NON_DEGRADABLE_CODES
    assert "integrity.external-term-unresolved" in BLOCKING_CODES


# ---------------------------------------------------------------------------
# Anchor resolution (#537)
# ---------------------------------------------------------------------------


def _typo_hub(tmp_path: Path, parent_local: str) -> dict:
    path = _write_domain(tmp_path, "cargo", classes=("CargoItem",), imports=(_MODULE,))
    _with_extra(path, f"\n:CargoItem rdfs:subClassOf <{_MODULE}#{parent_local}> .\n")
    return scan_hub_ontologies(tmp_path, _TERMS)


def test_a_resolvable_parent_still_anchors(tmp_path: Path) -> None:
    onts = _typo_hub(tmp_path, "CargoItem")
    assert onts["cargo"].anchored_classes == frozenset({"CargoItem"})


def test_an_equivalent_class_no_longer_counts_as_an_anchor(tmp_path: Path) -> None:
    """#730: the compiler resolves anchoring through rdfs:subClassOf only, so an
    equivalence-only link passed this check and then bound nothing."""
    path = _write_domain(tmp_path, "cargo", classes=("CargoItem",), imports=(_MODULE,))
    _with_extra(
        path,
        f"\n:CargoItem <http://www.w3.org/2002/07/owl#equivalentClass> <{_MODULE}#CargoItem> .\n",
    )
    onts = scan_hub_ontologies(tmp_path, _TERMS)
    assert onts["cargo"].anchored_classes == frozenset()
    diagnostics = check_unanchored_classes(onts)
    assert [d.code for d in diagnostics] == ["integrity.class-unanchored"]
    assert "rdfs:subClassOf" in diagnostics[0].remediation
    assert "owl:equivalentClass does not anchor" in diagnostics[0].remediation


def test_an_unresolvable_parent_no_longer_counts_as_an_anchor(tmp_path: Path) -> None:
    """A typo'd parent used to register as anchored, which was worse than unreported."""
    onts = _typo_hub(tmp_path, "CargoIteem")
    assert onts["cargo"].anchored_classes == frozenset()


def test_the_typo_stops_silencing_the_unanchored_check(tmp_path: Path) -> None:
    onts = _typo_hub(tmp_path, "CargoIteem")
    assert [d.code for d in check_unanchored_classes(onts)] == ["integrity.class-unanchored"]


def test_the_typo_stops_silencing_the_shadowing_check(tmp_path: Path) -> None:
    """':CargoItem' duplicates a class in an imported module with no working link --
    exactly what the shadowing check exists to catch, and the typo suppressed it."""
    onts = _typo_hub(tmp_path, "CargoIteem")
    codes = [d.code for d in check_reference_model_shadowing(onts, _TERMS)]
    assert "integrity.local-class-shadows-reference-model" in codes


def test_without_a_catalog_anchoring_is_unchanged(tmp_path: Path) -> None:
    """compile passes no catalog. Declaring every anchor broken there would be worse
    than the bug: it would turn an unresolved catalog into a hub-wide regression."""
    path = _write_domain(tmp_path, "cargo", classes=("CargoItem",), imports=(_MODULE,))
    _with_extra(path, f"\n:CargoItem rdfs:subClassOf <{_MODULE}#CargoIteem> .\n")

    assert scan_hub_ontologies(tmp_path).get("cargo").anchored_classes == frozenset({"CargoItem"})


def test_an_unmanaged_module_still_anchors(tmp_path: Path) -> None:
    """A module the catalog never resolved cannot be judged; missing_managed_import owns it."""
    other = "https://example.org/not-managed"
    path = _write_domain(tmp_path, "cargo", classes=("CargoItem",), imports=(other,))
    _with_extra(path, f"\n:CargoItem rdfs:subClassOf <{other}#Whatever> .\n")

    assert scan_hub_ontologies(tmp_path, _TERMS)["cargo"].anchored_classes == frozenset(
        {"CargoItem"}
    )
