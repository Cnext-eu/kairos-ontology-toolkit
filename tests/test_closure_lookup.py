# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The deterministic closure lookup behind DD-248 (#1051).

The pairs pinned here are from a real 15-domain hub: every "real" pair was a hub-local
property that duplicated a closure property, and every "noise" pair is one that bare
string similarity (>= 0.8) accepted and a reviewer rejected.
"""

import random

import pytest

from kairos_ontology.core.closure_lookup import (
    ClosureCandidate,
    find_candidates,
    infer_column_prefix,
    name_tokens,
    normalise_term,
    terms_from_index,
    terms_from_ref_classes,
)

BSP = "https://ref.example/ont/bsp#"


def _cls(name, *props, uri=None):
    return {
        "uri": uri or f"{BSP}{name}",
        "name": name,
        "properties": [
            {"uri": f"{BSP}{p}", "name": p, "label": label, "type": "datatype"}
            for p, label in (x if isinstance(x, tuple) else (x, "") for x in props)
        ],
    }


@pytest.fixture
def index():
    return terms_from_ref_classes(
        [
            _cls("Document", "documentType", "documentReference"),
            _cls("Consignment", "estimatedDeparture", "shippedOnBoardDate", "hasInvoiceLine"),
            _cls("Party", "legalName", ("tradingName", "Trading name"), "contactRole",
                 "agentReference", "inspectionStatusCode", "specimenTypeCode"),
            _cls("PackagingType", "typeCode", "code"),
            _cls("Contract", "contractNumber"),
            _cls("Location", "hasDestinationLocation"),
            _cls("Thing", "description"),
        ]
    )


class TestNormalisation:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("legalName", "legal name"),
            ("LEGAL_NAME", "legal name"),
            ("legal-name", "legal name"),
            ("ETLLoadDate", "etl load date"),
            ("EQUIPMENTTYPE14", "equipmenttype 14"),
            ("CONTRACT_NBR", "contract number"),
            ("CUST_REF", "cust reference"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalise_term(self, raw, expected):
        assert normalise_term(raw) == expected

    def test_prefix_is_stripped_once_and_case_insensitively(self):
        assert normalise_term("XX_LEGAL_NAME", strip_prefixes=("XX_",)) == "legal name"
        assert normalise_term("xx_legal_name", strip_prefixes=("XX_",)) == "legal name"
        assert normalise_term("XX_", strip_prefixes=("XX_",)) == "xx"

    def test_name_tokens_is_the_family_split(self):
        assert name_tokens("pickup_location_city") == ["pickup", "location", "city"]
        assert name_tokens("ISO6346") == ["iso6346"]

    def test_prefix_inference_needs_a_shared_majority(self):
        cargowise = ["XX_LEGAL_NAME", "XX_CODE", "XX_COUNTRY", "XX_CITY", "PK"]
        assert infer_column_prefix(cargowise) == "XX_"
        assert infer_column_prefix(["PO_NUMBER", "customer", "city", "country"]) == ""
        assert infer_column_prefix([]) == ""


class TestExactAndNear:
    def test_exact_name_match_scores_one(self, index):
        [hit] = find_candidates(index, "LEGAL_NAME")
        assert (hit.name, hit.score, hit.match) == ("legalName", 1.0, "exact")
        assert hit.class_uris == (f"{BSP}Party",)

    def test_exact_label_match(self, index):
        hits = find_candidates(index, "TRADING_NAME")
        assert hits[0].name == "tradingName" and hits[0].match == "exact"
        by_label = find_candidates(index, "TN", label="Trading name")
        assert by_label[0].name == "tradingName"

    def test_abbreviation_reaches_the_expanded_property(self, index):
        [hit] = find_candidates(index, "CONTRACT_NBR")
        assert hit.name == "contractNumber" and hit.match == "exact"

    @pytest.mark.parametrize(
        "column, expected",
        [
            ("documentTypeCode", "documentType"),
            ("estimatedDepartureDateTime", "estimatedDeparture"),
            ("shippedOnBoardDateTime", "shippedOnBoardDate"),
            ("containsInvoiceLine", "hasInvoiceLine"),
            ("destinationLocation", "hasDestinationLocation"),
        ],
    )
    def test_real_near_matches_are_found(self, index, column, expected):
        hits = find_candidates(index, column)
        assert hits and hits[0].name == expected and hits[0].match == "near"
        assert 0.0 < hits[0].score < 1.0

    @pytest.mark.parametrize(
        "column",
        [
            "eventReference",  # vs agentReference: same head, different concept
            "contactPhone",  # vs contactRole
            "instructionStatusCode",  # vs inspectionStatusCode
            "shipmentTypeCode",  # vs specimenTypeCode
        ],
    )
    def test_similar_strings_with_disjoint_tokens_are_not_candidates(self, index, column):
        assert find_candidates(index, column) == []

    def test_generic_names_match_exactly_only(self, index):
        assert find_candidates(index, "PI_TYPE") == []
        assert find_candidates(index, "jobDescription") == []
        assert find_candidates(index, "LOCATION_TYPE_CODE") == []  # typeCode is all-generic
        [hit] = find_candidates(index, "CODE")
        assert hit.name == "code" and hit.match == "exact"
        [hit] = find_candidates(index, "TYPE_CODE")
        assert hit.name == "typeCode" and hit.match == "exact"

    def test_too_many_extra_tokens_is_not_near(self, index):
        assert find_candidates(index, "estimatedDepartureDateTimeLocalZone") == []

    def test_min_score_drops_weak_near_matches_but_never_an_exact_one(self, index):
        weak = find_candidates(index, "estimatedDepartureDateTime")
        assert weak and weak[0].name == "estimatedDeparture"
        assert find_candidates(index, "estimatedDepartureDateTime", min_score=0.99) == []
        [exact] = find_candidates(index, "LEGAL_NAME", min_score=0.99)
        assert exact.match == "exact"

    def test_one_token_cannot_claim_a_three_token_name(self):
        index = terms_from_ref_classes([_cls("Transaction", "hasDocument", "documentType")])
        assert [c.name for c in find_candidates(index, "documentTypeCode")] == ["documentType"]
        # …but it still claims a two-token one.
        assert [c.name for c in find_candidates(index, "documentRef")] == ["hasDocument"]

    def test_prefix_stripping_turns_a_near_match_exact(self, index):
        [near] = find_candidates(index, "XX_LEGAL_NAME")
        assert (near.name, near.match) == ("legalName", "near")
        [exact] = find_candidates(index, "XX_LEGAL_NAME", strip_prefixes=("XX_",))
        assert (exact.name, exact.match) == ("legalName", "exact")


class TestOrderingAndShape:
    def test_output_is_deterministic_under_shuffled_input(self):
        classes = [
            _cls("A", "documentType", "documentTypeCode"),
            _cls("B", "documentTypeCode2", "typeDocument"),
        ]
        expected = find_candidates(terms_from_ref_classes(classes), "documentType", limit=10)
        for seed in range(5):
            shuffled = list(classes)
            random.Random(seed).shuffle(shuffled)
            for cls in shuffled:
                random.Random(seed).shuffle(cls["properties"])
            assert find_candidates(terms_from_ref_classes(shuffled), "documentType", limit=10) == expected
        assert [c.match for c in expected][0] == "exact"
        assert [c.score for c in expected] == sorted((c.score for c in expected), reverse=True)

    def test_limit_is_honoured(self):
        classes = [_cls("A", *[f"vesselName{i}" for i in range(9)])]
        assert len(find_candidates(terms_from_ref_classes(classes), "vessel_name", limit=3)) == 3

    def test_inherited_copies_are_one_term_owning_every_class(self):
        base = _cls("Party", "legalName")
        sub = _cls("Carrier", "legalName")
        index = terms_from_ref_classes([base, sub])
        assert len(index) == 1
        [hit] = find_candidates(index, "legalName")
        assert hit.class_uris == (f"{BSP}Carrier", f"{BSP}Party")

    def test_entry_shape(self):
        entry = ClosureCandidate(
            uri=f"{BSP}legalName", name="legalName", class_uris=(f"{BSP}Party",),
            score=0.8765, match="near",
        ).to_entry()
        assert entry == {
            "uri": f"{BSP}legalName", "name": "legalName", "class": "Party",
            "score": 0.88, "match": "near",
        }

    def test_no_terms_no_candidates(self):
        assert find_candidates(terms_from_ref_classes([]), "anything") == []
        assert find_candidates(terms_from_ref_classes([_cls("A", "x")]), "") == []


class TestFromSemanticIndex:
    def test_terms_come_from_the_closure_index(self, tmp_path):
        from kairos_ontology.core.ontology_loader import load_ontology

        (tmp_path / "base.ttl").write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
            "<urn:base> a owl:Ontology .\n"
            "<urn:base#Party> a owl:Class .\n"
            "<urn:base#legalName> a owl:DatatypeProperty ; rdfs:label \"Legal name\" ;\n"
            "    rdfs:domain <urn:base#Party> ; rdfs:range xsd:string .\n",
            encoding="utf-8",
        )
        (tmp_path / "customer.ttl").write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "<urn:customer> a owl:Ontology ; owl:imports <urn:base> .\n"
            "<urn:customer#Customer> a owl:Class ; rdfs:subClassOf <urn:base#Party> .\n",
            encoding="utf-8",
        )
        (tmp_path / "catalog-v001.xml").write_text(
            '<?xml version="1.0"?>\n'
            '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog" prefer="public">\n'
            '  <uri name="urn:base" uri="base.ttl"/>\n'
            "</catalog>\n",
            encoding="utf-8",
        )
        loaded = load_ontology(
            tmp_path / "customer.ttl",
            catalog_path=tmp_path / "catalog-v001.xml",
            profile="kairos-design",
        )
        index = terms_from_index(loaded.semantic_index)
        [hit] = find_candidates(index, "LEGAL_NAME")
        assert hit.uri == "urn:base#legalName"
        assert hit.class_uris == ("urn:base#Party",)
        assert find_candidates(index, "x", label="Legal name")[0].uri == "urn:base#legalName"
