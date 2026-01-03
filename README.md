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

**Best Practice:** Use standard HTTP/HTTPS namespaces with proper `owl:Ontology` declarations:

#### Declaring Your Ontology (Recommended)

```turtle
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/ontology#> .

# Declare your ontology (this defines the main namespace)
<http://example.org/ontology> a owl:Ontology ;
    rdfs:label "My Application Ontology" ;
    owl:versionInfo "1.0.0" ;
    owl:imports <https://spec.edmcouncil.org/fibo/ontology/FND/Relations/Relations/> .

# Your classes
ex:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .

ex:customerName a owl:DatatypeProperty ;
    rdfs:domain ex:Customer ;
    rdfs:range xsd:string .
```

**Why this matters:**
- The `owl:Ontology` declaration tells the toolkit which namespace is yours
- `owl:imports` declares external ontologies (FIBO, Schema.org, etc.)
- The toolkit automatically excludes imported namespaces from projection
- No need for hardcoded exclusion lists - works with ANY external ontology

#### Namespace Auto-Detection

The toolkit uses semantic web best practices to detect your namespace:

1. **Check `owl:Ontology` declaration** (preferred) - Uses the namespace of the declared ontology
2. **Exclude `owl:imports`** - Automatically filters out imported external ontologies
3. **Count classes in remaining namespaces** - Fallback if no declaration found

```bash
# Auto-detect (default)
kairos-ontology project --target dbt

# Explicit namespace
kairos-ontology project --target dbt --namespace "http://example.org/ontology#"
```

**Auto-detection priorities:**
1. ✅ Uses `owl:Ontology` declaration namespace
2. ✅ Excludes `owl:imports` (FIBO, Schema.org, etc. automatically filtered)
3. ✅ Falls back to most common non-standard namespace
4. ✅ Works with ANY external ontology - no hardcoded lists needed

**Supported namespace formats:**
- HTTP fragment: `http://example.org/ont#`
- HTTP path: `http://example.org/ont/`
- HTTPS: `https://example.org/ont#`
- URN: `urn:example:ont:`

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

### Creating a Release

Use the automated release script:

```powershell
# Windows (PowerShell)
.\release.ps1
```

```bash
# Linux/Mac
./release.sh
```

The script will:
1. Check for uncommitted changes
2. Prompt for release type (patch/minor/major)
3. Update version numbers in `pyproject.toml` and `__init__.py`
4. Update `poetry.lock`
5. Build the package
6. Commit changes
7. Create and push a git tag
8. Display installation instructions

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