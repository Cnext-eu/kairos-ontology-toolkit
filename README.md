# Kairos Ontology Toolkit

Validation and projection tools for OWL/Turtle ontologies in the Kairos platform.

## Features

- **3-Level Validation Pipeline**
  - Syntax validation (RDF/OWL parsing)
  - SHACL constraint validation
  - Consistency checking (SPARQL)

- **Multi-Target Projections**
  - DBT SQL models for data warehouses
  - Neo4j Cypher schemas for graph databases
  - Azure AI Search index definitions
  - A2UI JSON schemas for UI generation
  - Prompt context for LLM interactions

- **Catalog-Based Import Resolution**
  - Resolve external ontology imports via XML catalogs
  - Support for FIBO and other standard ontologies

## Installation

```bash
# Install from GitHub
pip install git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git

# Or install from PyPI (when published)
pip install kairos-ontology-toolkit
```

## Usage

### Project Structure

Create your ontology hub with this structure:

```
my-ontology-hub/
├── ontologies/                    # Your custom ontologies (default)
│   ├── my-domain.ttl
│   └── my-concepts.ttl
├── shapes/                        # SHACL validation shapes (default)
│   ├── domain-constraints.ttl
│   └── validation-rules.ttl
├── reference-models/              # External ontologies
│   ├── catalog-v001.xml          # Import resolution catalog (default)
│   └── fibo/                     # Example: FIBO ontologies
└── output/                        # Generated projections (default)
    ├── dbt/
    ├── neo4j/
    ├── azure-search/
    ├── a2ui/
    └── prompt/
```

### Namespace Format

**Important:** Use URN format for your ontology namespaces to ensure Windows compatibility:

```turtle
@prefix kairos: <urn:kairos:ont:core:> .

kairos:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .

kairos:customerName a owl:DatatypeProperty ;
    rdfs:domain kairos:Customer ;
    rdfs:range xsd:string .
```

❌ **Don't use:** `http://kairos.ai/ont/core#` (causes Windows path issues)
✅ **Use:** `urn:kairos:ont:core:` (Windows-compatible)

### Validate Ontologies

```bash
# Validate everything (syntax + SHACL + consistency)
kairos-ontology validate --all

# Validate specific aspects
kairos-ontology validate --syntax
kairos-ontology validate --shacl
kairos-ontology validate --consistency

# Custom paths
kairos-ontology validate --ontologies ./ontologies --shapes ./shapes --catalog ./catalog.xml
```

### Generate Projections

```bash
# Generate all projections
kairos-ontology project --target all

# Generate specific projection
kairos-ontology project --target dbt
kairos-ontology project --target neo4j
kairos-ontology project --target azure-search

# Custom paths
kairos-ontology project --ontologies ./ontologies --output ./output --catalog ./catalog.xml
```

### Test Catalog Resolution

```bash
# Test catalog file
kairos-ontology catalog-test --catalog ./catalog.xml

# Test with specific ontology
kairos-ontology catalog-test --catalog ./catalog.xml --ontology ./ontologies/customer.ttl
```

## Development

```bash
# Clone repository
git clone https://github.com/Cnext-eu/kairos-ontology-toolkit.git
cd kairos-ontology-toolkit

# Install with Poetry
poetry install

# Run tests
poetry run pytest

# Build package
poetry build
```

## Architecture

```
kairos-ontology-toolkit/
├── src/
│   └── kairos_ontology/
│       ├── cli/              # Click-based CLI
│       ├── projections/      # Projection generators
│       ├── templates/        # Jinja2 templates
│       ├── validator.py      # Validation pipeline
│       ├── projector.py      # Projection orchestrator
│       └── catalog_utils.py  # Catalog resolution
└── tests/                    # Unit tests
```

## Troubleshooting

### DBT Projection shows "No files generated"

This usually means:
1. No classes found with namespace starting with `urn:kairos:ont:`
2. Classes exist but have no datatype properties
3. Check your ontology uses the correct URN namespace format

### Windows Path Errors

If you see errors with `:` in file paths, ensure your ontology namespaces use URN format (`urn:kairos:ont:core:`) instead of HTTP URLs (`http://...`).

## License

MIT License - see LICENSE file for details.