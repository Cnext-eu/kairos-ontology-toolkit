# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
#!/usr/bin/env python3
"""
SKOS Utilities - Parse SKOS mappings for synonym extraction

Provides shared functionality for loading SKOS concepts and extracting
alternative labels (synonyms) for use in projections.
"""

from pathlib import Path
from typing import Dict, List, Optional
from rdflib import Graph, Namespace, SKOS
from .uri_utils import extract_local_name


class SKOSParser:
    """Parse SKOS mapping files and extract synonyms"""
    
    def __init__(self, mappings_dir: Optional[Path] = None):
        self.mappings_dir = mappings_dir or Path("ontology-hub/model/mappings")
        self.SKOS = SKOS
        self.KAIROS = Namespace("urn:kairos:ont:core:")
    
    def load_all_mappings(self) -> Graph:
        """Load all SKOS mapping files from mappings directory"""
        graph = Graph()
        
        if not self.mappings_dir.exists():
            return graph
        
        for mapping_file in self.mappings_dir.glob("*.ttl"):
            try:
                graph.parse(mapping_file, format='turtle')
            except (SyntaxError, ValueError) as e:
                print(f"Warning: Could not parse {mapping_file}: {e}")
        
        return graph
    
    def get_synonyms_for_class(self, class_name: str, graph: Graph = None) -> List[str]:
        """
        Get all SKOS alternative labels for a class
        
        Args:
            class_name: Name of the OWL class (e.g., "Customer")
            graph: Optional pre-loaded SKOS graph
        
        Returns:
            List of synonym strings
        """
        if graph is None:
            graph = self.load_all_mappings()
        
        synonyms = []
        for alt_label in graph.objects(subject=self.KAIROS[f"{class_name}Concept"], 
                                       predicate=self.SKOS.altLabel):
            synonyms.append(str(alt_label))
        
        return synonyms
    
    def get_all_synonyms(self, graph: Graph = None) -> Dict[str, List[str]]:
        """
        Get synonyms for all classes in SKOS mappings
        
        Returns:
            Dictionary mapping class names to lists of synonyms
        """
        if graph is None:
            graph = self.load_all_mappings()
        
        synonyms_map = {}
        
        # Query for all concepts with altLabels
        query = """
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        
        SELECT ?concept ?altLabel
        WHERE {
            ?concept skos:altLabel ?altLabel .
        }
        """
        
        for row in graph.query(query):
            concept_uri = str(row.concept)
            # Extract class name from concept URI (e.g., "CustomerConcept" -> "Customer")
            if "Concept" in concept_uri:
                class_name = extract_local_name(concept_uri).replace("Concept", "")
                
                if class_name not in synonyms_map:
                    synonyms_map[class_name] = []
                
                synonyms_map[class_name].append(str(row.altLabel))
        
        return synonyms_map
    
    def generate_solr_synonyms(self, class_name: str, preferred_label: str, 
                               synonyms: List[str]) -> str:
        """
        Generate Solr-format synonym line
        
        Format: preferredLabel, synonym1, synonym2, ...
        
        Args:
            class_name: Name of the class
            preferred_label: Preferred term (e.g., "Customer")
            synonyms: List of alternative terms
        
        Returns:
            Solr synonym line
        """
        if not synonyms:
            return ""
        
        # Combine preferred label with synonyms
        all_terms = [preferred_label.lower()] + [s.lower() for s in synonyms]
        # Remove duplicates while preserving order
        unique_terms = list(dict.fromkeys(all_terms))
        
        return ", ".join(unique_terms)
