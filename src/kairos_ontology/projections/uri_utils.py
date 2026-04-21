# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""URI utilities for extracting local names from ontology URIs."""


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
    if '#' in uri:
        return uri.split('#')[-1]
    
    # Path-based URI
    if '/' in uri:
        return uri.split('/')[-1]
    
    # URN format
    if ':' in uri:
        return uri.split(':')[-1]
    
    # Fallback - return as is
    return uri
