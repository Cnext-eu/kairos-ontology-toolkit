# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""One exception mechanism for every excusable practice (DD-240).

An exception reads ``"<RULE> on <object> [<target>]: <reason>"`` in every area:

* semantic model -- ``kairos-ext:practiceException`` (or its original name,
  ``kairos-ext:bpaIgnoreRule``) in the Gold extension. ``RULE`` is a BPA rule ID or a
  ``semantic-model.*`` practice. Parsed by ``bpa_profile.parse_bpa_ignore``, which
  resolves catalogue practices through :func:`excusable_practice` here;
* DDD -- ``kairos-ddd:practiceException`` in an overlay or the strategic file, parsed by
  :func:`parse_ddd_exception`.

The rules are the same everywhere (DD-234): the reason is mandatory, the rule must exist
and be excusable, it must apply to that kind of object, and an exception that excuses
nothing fails the check that would have made the finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import Practice, practice


class PracticeExceptionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def excusable_practice(rule_id: str, *, area: str) -> Practice | None:
    """Return the catalogue-owned practice *rule_id* in *area* when it can be excused."""
    item = practice(rule_id)
    if item is None or item.bpa or item.area != area or not item.excusable:
        return None
    return item


@dataclass(frozen=True, slots=True)
class DddException:
    """One authored ``kairos-ddd:practiceException``, parsed."""

    rule_id: str
    kind: str
    #: The IRI or local name the author wrote.
    target: str
    reason: str
    source: str

    def matches(self, rule_id: str, kind: str, iri: str) -> bool:
        if (self.rule_id, self.kind) != (rule_id, kind):
            return False
        return self.target == iri or self.target == re.split(r"[#/]", iri)[-1]


#: The target is one token, and the reason follows a colon *and whitespace*: an IRI's
#: own ``https:`` colon is followed by a slash, so it is never read as the separator.
_DDD_EXCEPTION = re.compile(
    r"^(?P<rule>\S+)\s+on\s+(?P<kind>class|property|context)\s+(?P<target>\S+?)\s*:\s+"
    r"(?P<reason>\S.*)$",
    re.DOTALL,
)


def parse_ddd_exception(value: str) -> DddException:
    """Parse ``"<ddd.rule> on <class|property|context> <target>: <reason>"``, fail-closed."""
    match = _DDD_EXCEPTION.match(value.strip())
    if match is None:
        raise PracticeExceptionError(
            "ddd.practice-exception-malformed",
            (
                f"practiceException {value!r} must read "
                '"<ddd.rule> on <class|property|context> <target>: <reason>"'
            ),
        )
    rule_id, kind = match.group("rule"), match.group("kind")
    item = practice(rule_id)
    if item is None or item.area != "ddd":
        raise PracticeExceptionError(
            "ddd.practice-exception-unknown-rule",
            f"practiceException {value!r} names {rule_id!r}, which is not a DDD practice",
        )
    if not item.excusable:
        raise PracticeExceptionError(
            "ddd.practice-exception-not-excusable",
            f"practiceException {value!r}: {rule_id} cannot be excused; fix the design",
        )
    if kind not in item.objects:
        raise PracticeExceptionError(
            "ddd.practice-exception-wrong-object",
            (
                f"practiceException {value!r}: {rule_id} is about a "
                f"{' or '.join(item.objects)}, never a {kind}"
            ),
        )
    return DddException(rule_id, kind, match.group("target"), match.group("reason").strip(), value)
