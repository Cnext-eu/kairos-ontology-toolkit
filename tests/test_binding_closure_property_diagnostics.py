# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A property one hop away in the import closure is named, not denied (#853).

Split out of #811, whose "wall 2" this replaces. That issue reported the problem as a
*reachability* asymmetry -- range-class scalars supposedly usable only when the hub
declares a local subclass of the range. Measured both ways, that is not what happens:
neither shape makes the property usable from the parent binding, and the companion-binding
route works with no local subclass at all (DD-144, `test_compiler_accelerator_direct.py`).

What is real is the diagnostic. The compiler indexes the whole ``owl:imports`` closure
(DD-103), so a property on a class nothing in this compile pulled in resolves against no
token in scope while sitting one hop away in the graph -- and was reported as:

    property 'imo:flagStateCountryCode' does not resolve in the ontology

which sends the author hunting for a typo, a missing prefix or a missing import. The
answer is "that property belongs to another class; bind it and link the two".

Which of the two failures an author gets depends on whether anything else in the compile
happened to pull the property's class into scope -- invisible to them, and irrelevant to
their mistake. So both messages now say the same actionable thing.

Nothing here changes which bindings compile. Both cases failed before and fail now.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from kairos_ontology.core.compiler import compile_domain

sys.path.insert(0, str(Path(__file__).parent))

from test_compiler_accelerator_direct import _ONTOLOGY, _hub  # noqa: E402

# A local subclass of the range class. The shape #811 claimed made the difference.
_WITH_LOCAL_SUBCLASS = (
    _ONTOLOGY
    + """
    party:LocalTradeParty a owl:Class ; rdfs:subClassOf acc:TradeParty ;
      rdfs:label "Local trade party" .
"""
)

_PARENT_BINDING = """
    apiVersion: kairos.eu/v5
    kind: EntityBinding
    metadata:
      name: crm-organisation
      domain: party
    source:
      relation: crm.organisations
    target:
      class: party:Organisation
    grain:
      columns: [org_id]
    identity:
      strategy: source-natural
      sourceKey: [org_id]
    load:
      mode: full-refresh
    fields:
      - property: party:orgId
        expression: org_id
      - property: {property}
        expression: name
"""


def _compile(tmp_path: Path, *, ontology: str, property_token: str):
    # A fresh subdirectory per call: `_hub` mkdirs without `exist_ok`, and two of the
    # tests below compile the same fixture twice to compare the two messages.
    root = tmp_path / f"hub{len(list(tmp_path.iterdir()))}"
    root.mkdir()
    hub = _hub(
        root,
        ontology=ontology,
        bindings={
            "organisation": textwrap.dedent(
                _PARENT_BINDING.format(property=property_token)
            )
        },
    )
    return compile_domain(hub, "party")


def _messages(result, *codes: str) -> str:
    return " ".join(item.message for item in result.diagnostics.items if item.code in codes)


_UNRESOLVED = ("safety.property-unresolved", "binding.unknown-property")
_INCOMPATIBLE = ("binding.property-domain-incompatible",)


class TestClosurePropertyIsNamed:
    def test_a_closure_property_is_no_longer_called_non_existent(self, tmp_path):
        """The reported symptom, with no local subclass anywhere."""
        result = _compile(tmp_path, ontology=_ONTOLOGY, property_token="acc:partyName")

        message = _messages(result, *_UNRESOLVED)
        assert "does not resolve in the ontology" not in message
        assert "exists in the import closure" in message

    def test_the_message_names_the_owning_class(self, tmp_path):
        result = _compile(tmp_path, ontology=_ONTOLOGY, property_token="acc:partyName")

        assert "'acc:TradeParty'" in _messages(result, *_UNRESOLVED)

    def test_the_owning_class_is_named_as_a_token_not_a_bare_iri(self, tmp_path):
        """The author has to type it into `target.class`. A resolved class carries both a
        qname and its IRI, and sorting between them picked by first character."""
        message = _messages(
            _compile(tmp_path, ontology=_ONTOLOGY, property_token="acc:partyName"),
            *_UNRESOLVED,
        )
        assert "https://example.test/accelerator/party#TradeParty" not in message

    def test_the_message_gives_the_route_not_just_the_diagnosis(self, tmp_path):
        message = _messages(
            _compile(tmp_path, ontology=_ONTOLOGY, property_token="acc:partyName"),
            *_UNRESOLVED,
        )
        assert "relationships:" in message
        assert "technicalFields:" in message
        # The route only works because an imported class needs no local subclass (DD-144),
        # which is exactly what #811 believed was required.
        assert "DD-144" in message


class TestTheOtherHalfOfTheSameMistake:
    """With a local subclass the property resolves, so a different code fires. Same
    authoring error, so it must say the same actionable thing."""

    def test_a_local_subclass_does_not_make_it_reachable(self, tmp_path):
        """#811's central claim, measured. It fails either way."""
        result = _compile(
            tmp_path, ontology=_WITH_LOCAL_SUBCLASS, property_token="acc:partyName"
        )
        assert not result.succeeded
        assert "binding.property-domain-incompatible" in {
            item.code for item in result.diagnostics.items
        }

    def test_the_domain_incompatible_message_names_the_owning_class(self, tmp_path):
        """The *declaring* class, `acc:TradeParty`. `party:LocalTradeParty` merely inherits
        the property; naming it as the declarer sent the author to a class that declares
        nothing, while the unresolved variant of the same mistake named the real one."""
        message = _messages(
            _compile(tmp_path, ontology=_WITH_LOCAL_SUBCLASS, property_token="acc:partyName"),
            *_INCOMPATIBLE,
        )
        assert "'acc:TradeParty'" in message
        assert "LocalTradeParty" not in message
        assert "https://example.test/accelerator/party#TradeParty" not in message

    def test_both_failures_offer_the_same_route(self, tmp_path):
        unresolved = _messages(
            _compile(tmp_path, ontology=_ONTOLOGY, property_token="acc:partyName"),
            *_UNRESOLVED,
        )
        incompatible = _messages(
            _compile(tmp_path, ontology=_WITH_LOCAL_SUBCLASS, property_token="acc:partyName"),
            *_INCOMPATIBLE,
        )
        for fragment in ("in its own EntityBinding", "relationships:", "technicalFields:"):
            assert fragment in unresolved, fragment
            assert fragment in incompatible, fragment

    def test_the_bound_class_is_still_named(self, tmp_path):
        """Narrowing the message must not drop what it already said."""
        message = _messages(
            _compile(tmp_path, ontology=_WITH_LOCAL_SUBCLASS, property_token="acc:partyName"),
            *_INCOMPATIBLE,
        )
        assert "does not apply to class 'party:Organisation'" in message


class TestAGenuineTypoIsUnchanged:
    def test_an_unknown_token_still_reports_as_unknown(self, tmp_path):
        """Softening this would be the opposite mistake: a token matching nothing anywhere
        really does not resolve, and the token list is the right help."""
        message = _messages(
            _compile(tmp_path, ontology=_ONTOLOGY, property_token="party:noSuchThing"),
            *_UNRESOLVED,
        )
        assert "does not resolve in the ontology" in message
        assert "usable property tokens" in message
        assert "import closure" not in message

    def test_a_token_with_an_undeclared_prefix_still_reports_as_unknown(self, tmp_path):
        message = _messages(
            _compile(tmp_path, ontology=_ONTOLOGY, property_token="nope:partyName"),
            *_UNRESOLVED,
        )
        assert "does not resolve in the ontology" in message

class TestTheRecommendedRouteWorks:
    """The message tells the author to bind the owning class directly. It must be true."""

    @pytest.mark.parametrize(
        "ontology",
        [_ONTOLOGY, _WITH_LOCAL_SUBCLASS],
        ids=["no-local-subclass", "local-subclass"],
    )
    def test_binding_the_owning_class_compiles(self, tmp_path, ontology):
        root = tmp_path / "hub"
        root.mkdir()
        hub = _hub(
            root,
            ontology=ontology,
            bindings={
                "trade-party": textwrap.dedent(
                    _PARENT_BINDING.replace(
                        "class: party:Organisation", "class: acc:TradeParty"
                    )
                    .replace("property: party:orgId", "property: acc:tradePartyId")
                    .format(property="acc:partyName")
                )
            },
        )
        result = compile_domain(hub, "party")
        assert result.succeeded, {item.code for item in result.diagnostics.items}
