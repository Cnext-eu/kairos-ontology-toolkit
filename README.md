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

- **Domain-Specific Outputs**
  - Each ontology file generates separate output artifacts
  - Enables independent deployment of data domains
  - Organized by domain name for better isolation

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
│   ├── customer.ttl              # Customer domain
│   ├── order.ttl                 # Order domain
│   └── product.ttl               # Product domain
├── shapes/                        # SHACL validation shapes (default)
│   ├── customer.shacl.ttl
│   └── order.shacl.ttl
├── reference-models/              # External ontologies
│   ├── catalog-v001.xml          # Import resolution catalog (default)
│   └── fibo/                     # Example: FIBO ontologies
└── output/                        # Generated projections (default)
    ├── dbt/
    │   ├── customer/             # Customer domain outputs
    │   │   └── models/silver/
    │   │       ├── customer.sql
    │   │       └── schema_customer.yml
    │   └── order/                # Order domain outputs
    │       └── models/silver/
    ├── neo4j/
    │   ├── customer-schema.cypher
    │   └── order-schema.cypher
    ├── azure-search/
    │   ├── customer/
    │   │   └── indexes/
    │   └── order/
    │       └── indexes/
    ├── a2ui/
    │   ├── customer/
    │   │   └── schemas/
    │   └── order/
    │       └── schemas/
    └── prompt/
        ├── customer-context.json
        ├── customer-context-detailed.json
        ├── order-context.json
        └── order-context-detailed.json
```

**Why this structure?**
- Each ontology file (e.g., `customer.ttl`) represents a separate data domain
- Domain-specific outputs enable independent deployment to production
- Different teams can own and deploy their domains separately
- Supports multi-domain architectures and microservices

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

### Multi-Domain Architecture

The toolkit supports multi-domain ontology architectures where each domain is independently deployable:

```turtle
# customer.ttl - Customer domain
@prefix cust: <http://example.org/customer#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

<http://example.org/customer> a owl:Ontology ;
    rdfs:label "Customer Domain Ontology" ;
    owl:versionInfo "1.0.0" .

cust:Customer a owl:Class ;
    rdfs:label "Customer" .

cust:customerName a owl:DatatypeProperty ;
    rdfs:domain cust:Customer ;
    rdfs:range xsd:string .
```

```turtle
# order.ttl - Order domain
@prefix ord: <http://example.org/order#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

<http://example.org/order> a owl:Ontology ;
    rdfs:label "Order Domain Ontology" ;
    owl:versionInfo "1.0.0" .

ord:Order a owl:Class ;
    rdfs:label "Order" .

ord:orderDate a owl:DatatypeProperty ;
    rdfs:domain ord:Order ;
    rdfs:range xsd:dateTime .
```

**Projection Output:**
```
output/
├── dbt/
│   ├── customer/models/silver/customer.sql
│   └── order/models/silver/order.sql
├── neo4j/
│   ├── customer-schema.cypher
│   └── order-schema.cypher
└── prompt/
    ├── customer-context.json
    └── order-context.json
```

**Deployment:**
- Deploy customer domain independently: `dbt run --models customer.*`
- Deploy order domain separately: `dbt run --models order.*`
- Version and release domains independently
- Different teams can own different domains

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
# Generate all projections for all ontologies
kairos-ontology project --target all

# Generate specific projection type
kairos-ontology project --target dbt
kairos-ontology project --target neo4j
kairos-ontology project --target azure-search
kairos-ontology project --target a2ui
kairos-ontology project --target prompt

# Custom paths
kairos-ontology project --ontologies ./ontologies --output ./output --catalog ./catalog.xml
```

**Output Organization:**

Each ontology file generates domain-specific outputs:

```bash
# Input: ontologies/customer.ttl, ontologies/order.ttl

# DBT outputs:
output/dbt/customer/models/silver/customer.sql
output/dbt/order/models/silver/order.sql

# Neo4j outputs:
output/neo4j/customer-schema.cypher
output/neo4j/order-schema.cypher

# Prompt outputs:
output/prompt/customer-context.json
output/prompt/order-context.json
```

**Benefits:**
- Deploy each domain independently to production
- Different teams can own different domains
- Selective deployment and versioning per domain
- Better organization and isolation of artifacts

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
│       ├── ontology_ops.py   # rdflib CRUD operations
│       └── catalog_utils.py  # Catalog resolution
├── service/                  # FastAPI service (REST + AI chat)
│   ├── app/
│   │   ├── main.py           # FastAPI entry point
│   │   ├── config.py         # pydantic-settings configuration
│   │   ├── routers/          # ontology, validation, projection, chat
│   │   └── services/         # github_service, sdk_service, copilot_tools, local_service
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── tests/                    # Unit tests (toolkit + service)
└── docker-compose.yml
```

## Service

The FastAPI service exposes the toolkit via REST endpoints and an AI chat interface powered by the [GitHub Copilot SDK](https://github.com/github/copilot-sdk).

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/api/ontology/query` | List / search classes, properties, relationships |
| `POST` | `/api/ontology/change` | Propose a TTL change (returns diff preview) |
| `POST` | `/api/ontology/apply` | Commit change to feature branch + open PR |
| `POST` | `/api/validate` | Validate an ontology domain from the repo |
| `POST` | `/api/validate/content` | Validate raw TTL content |
| `GET` | `/api/project/targets` | List available projection targets |
| `POST` | `/api/project` | Generate projection artifacts |
| `POST` | `/api/chat` | AI chat via Copilot SDK (SSE streaming) |

All endpoints except `/health`, `/api/validate/content`, and `/api/project/targets` require an `Authorization: Bearer <token>` header.

### Copilot SDK Chat

The `/api/chat` endpoint creates a Copilot SDK session with 5 custom tools:

- **query_ontology** — search the ontology structure
- **propose_change** — generate a modification with diff preview
- **validate_ontology** — run SHACL / syntax validation
- **generate_projection** — produce dbt / neo4j / azure-search / a2ui / prompt artifacts
- **apply_change** — commit to a feature branch and open a PR

### Setup

1. Create a GitHub App with repository read/write permissions
2. Install it on the target ontology repository
3. Configure environment variables:

```bash
cp service/.env.example service/.env
# Fill in KAIROS_GITHUB_APP_ID, KAIROS_GITHUB_APP_PRIVATE_KEY, etc.
```

### Running the Service

**With Docker Compose:**

```bash
docker compose up --build
```

**Locally (dev mode — reads TTL files from disk, no GitHub App needed):**

```bash
# Install service dependencies
pip install -e ".[service]"

# Set dev mode
export KAIROS_DEV_MODE=true
export KAIROS_LOCAL_ONTOLOGIES_DIR=./ontologies

# Start the server
cd service
uvicorn app.main:app --reload --port 8000
```

In dev mode, read-only endpoints (query, validate, project) work against local files. Write endpoints (change/apply) and AI chat are unavailable.

### Docker

```bash
# Build
docker build -f service/Dockerfile -t kairos-service .

# Run
docker run -p 8000:8000 --env-file service/.env kairos-service
```

### CI/CD

The `.github/workflows/ci.yml` pipeline runs on every push and PR:

1. **test** — installs dependencies, runs ruff lint, runs all 59 tests
2. **docker** — builds the Docker image (depends on test passing)

## Troubleshooting

### No Files Generated for a Domain

This usually means:
1. No classes found with the auto-detected namespace
2. Classes exist but have no datatype properties
3. Check your ontology has proper `owl:Ontology` declaration
4. Verify namespace matches between ontology declaration and class URIs

### Understanding Domain-Specific Outputs

**Before (v1.1.x and earlier):**
- All ontologies merged into single output
- Single set of files per projection type

**After (v1.2.0+):**
- Each ontology file processed separately
- Domain-specific outputs per ontology
- Example: `customer.ttl` → `customer-context.json`

### Windows Path Errors

If you see errors with `:` in file paths, ensure your ontology namespaces use proper URL format. The toolkit automatically sanitizes filenames to be Windows-compatible.

## License

MIT License - see LICENSE file for details.