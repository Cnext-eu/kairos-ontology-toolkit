# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""URI utilities for extracting local names from ontology URIs."""

import re


def camel_to_snake(name: str) -> str:
    """Convert CamelCase or camelCase to snake_case (R4)."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def dbt_source_name(system_label: str) -> str:
    """Return the dbt source name a vocabulary system is declared under (#584).

    The single naming authority shared by catalog rendering
    (``dbt.shape._source_catalogs`` names ``models/silver/_<name>__sources.yml``) and by
    the compiler's contracted ``{{ source() }}`` validation, so a hand-authored source
    call matches iff dbt would resolve it against the declaration the toolkit emits.
    (``medallion_dbt_projector`` still carries two local copies of this rule; unifying
    them is deferred to the #586 stage-(b) follow-up.)
    """
    return camel_to_snake(system_label).replace(" ", "_")


def local_name(uri: str) -> str:
    """Extract local name from a URI (after ``#`` or last ``/``)."""
    if "#" in uri:
        return uri.rsplit("#", 1)[1]
    return uri.rsplit("/", 1)[1]


def extract_local_name(uri: str) -> str:
    """Extract the local name from an ontology URI.

    Handles both fragment (#) and path (/) based URIs, as well as URNs.

    Examples:
        http://example.org/ont#Person -> Person
        http://example.org/ont/Person -> Person
        https://spec.edmcouncil.org/fibo/ontology/FND/Person -> Person
        urn:example:ont:Person -> Person

    Args:
        uri: The full URI string

    Returns:
        The local name (last component after # or / or :)
    """
    if not uri:
        return ""

    # Fragment-based URI (most common for ontologies)
    if "#" in uri:
        return uri.split("#")[-1]

    # Path-based URI
    if "/" in uri:
        return uri.split("/")[-1]

    # URN format
    if ":" in uri:
        return uri.split(":")[-1]

    # Fallback - return as is
    return uri
