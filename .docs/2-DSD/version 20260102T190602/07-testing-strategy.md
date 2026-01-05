# Testing Strategy

**Implementation Note:** This document has been updated to reflect the actual CLI toolkit implementation. Original testing strategy targeted an integrated "Hub" with CI/CD; actual implementation is a local CLI tool with comprehensive pytest-based testing.

---

## Overview

The Kairos Ontology Toolkit testing strategy ensures **ontology correctness**, **artifact quality**, and **CLI reliability**. Since the toolkit is a build-time CLI tool (not runtime), testing focuses on:
1. **Validation Logic** (syntax, SHACL, consistency checks) - ✅ IMPLEMENTED
2. **Projection Correctness** (ontology → artifact transformation) - ✅ IMPLEMENTED  
3. **CLI Interface** (command parsing, error handling) - ✅ IMPLEMENTED
4. **Multi-Domain Support** (separate outputs per .ttl file) - ✅ IMPLEMENTED

**Testing Philosophy:**
- **Shift-Left:** Catch errors early in validation, not in runtime systems ✅
- **Automated:** All tests run via pytest; users integrate into their CI/CD 📋
- **Coverage-Driven:** Target 80%+ code coverage for projection logic ✅
- **Example-Based:** Use real-world ontology examples (e.g., Customer, Order) ✅

**Implementation Status:**
- ✅ **Unit Testing**: Comprehensive pytest suite for all modules
- ✅ **Integration Testing**: End-to-end projection tests
- 📋 **CI/CD Testing**: Users implement in their pipelines
- 📋 **UAT**: Users conduct in their environments

## Testing Levels

### 1. Unit Testing ✅ IMPLEMENTED
**Scope:** Individual functions and modules

**Framework:** `pytest` (Python 3.12 compatible)

**Coverage Target:** 80%+ for projection and validation logic

**Actual Implementation:** Comprehensive test suite in `tests/` directory

**Actual Test Structure:**
```
tests/
├── __init__.py
├── conftest.py                  # pytest fixtures
├── test_catalog_utils.py        # Catalog resolution tests
├── test_projector.py            # Main projector tests
├── test_validator.py            # Validation pipeline tests
└── tmp/                         # Test output directory
```

**Example Tests (Actual Implementation):**

#### Validation Module Tests
```python
# tests/test_validator.py
import pytest
from pathlib import Path
from kairos_ontology.validator import validate_ontology

def test_validate_syntax_valid_turtle():
    """Test that valid Turtle syntax passes validation"""
    result = validate_ontology(
        ontology_file=Path("fixtures/valid.ttl"),
        shapes_file=None,
        catalog_file=None
    )
    assert result['syntax']['conforms'] is True

def test_validate_shacl_pass():
    """Test SHACL validation with conforming ontology"""
    result = validate_ontology(
        ontology_file=Path("fixtures/customer.ttl"),
        shapes_file=Path("fixtures/customer.shacl.ttl"),
        catalog_file=None
    )
    assert result['shacl']['conforms'] is True
    assert result['shacl']['violations'] == []
```

#### Projection Module Tests
```python
# tests/test_projector.py
import pytest
from pathlib import Path
from kairos_ontology.projector import project_ontology

def test_dbt_projector_generates_sql(tmp_path):
    """Test that DBT projector generates valid SQL"""
    project_ontology(
        ontology_file=Path("fixtures/customer.ttl"),
        output_dir=tmp_path,
        target="dbt",
        catalog_file=None
    )
    
    sql_file = tmp_path / "models" / "customer.sql"
    assert sql_file.exists()
    assert "SELECT" in sql_file.read_text()

def test_neo4j_projector_generates_cypher(tmp_path):
    """Test that Neo4j projector generates valid Cypher"""
    project_ontology(
        ontology_file=Path("fixtures/customer.ttl"),
        output_dir=tmp_path,
        target="neo4j",
        catalog_file=None
    )
    
    cypher_file = tmp_path / "schema.cypher"
    assert cypher_file.exists()
    assert "CREATE CONSTRAINT" in cypher_file.read_text()
```

#### Catalog Resolution Tests
```python
# tests/test_catalog_utils.py  
import pytest
from kairos_ontology.catalog_utils import resolve_catalog

def test_catalog_resolution():
    """Test XML catalog import resolution"""
    result = resolve_catalog(
        catalog_file=Path("fixtures/catalog.xml"),
        uri="http://schema.org/"
    )
    assert result is not None
    assert result.exists()
```

---

### 2. Integration Testing ✅ IMPLEMENTED
**Scope:** Multi-module workflows (validation → projection → artifact generation)

**Framework:** `pytest` with fixtures

**Coverage Target:** All critical paths (happy path + error scenarios)

**Actual Implementation:** Integration tests in `tests/` directory

**Example Tests (Actual CLI Toolkit):**

#### End-to-End Projection Test
```python
# tests/test_projector.py (integration tests)
import pytest
from pathlib import Path
from kairos_ontology.projector import project_ontology

def test_full_projection_all_targets(tmp_path):
    """Test complete projection workflow for all targets"""
    ontology_file = Path("fixtures/customer.ttl")
    
    # Test each projection target
    for target in ['dbt', 'neo4j', 'azure-search', 'a2ui', 'prompt']:
        output_dir = tmp_path / target
        project_ontology(
            ontology_file=ontology_file,
            output_dir=output_dir,
            target=target,
            catalog_file=None
        )
        
        # Verify output directory exists
        assert output_dir.exists()
        
        # Verify at least one artifact generated
        artifacts = list(output_dir.rglob("*.*"))
        assert len(artifacts) > 0

def test_projection_with_catalog(tmp_path):
    """Test projection with catalog-based imports"""
    result = project_ontology(
        ontology_file=Path("fixtures/ontology_with_imports.ttl"),
        output_dir=tmp_path,
        target="dbt",
        catalog_file=Path("fixtures/catalog.xml")
    )
    
    assert result['success'] is True
    assert tmp_path.exists()
```

#### CLI Integration Test
```python
# tests/test_cli.py
import subprocess
import pytest

def test_cli_validate_command():
    """Test kairos-ontology validate CLI command"""
    result = subprocess.run(
        ["kairos-ontology", "validate", "fixtures/customer.ttl"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "PASS" in result.stdout or "conforms" in result.stdout.lower()

def test_cli_project_command():
    """Test kairos-ontology project CLI command"""
    result = subprocess.run(
        ["kairos-ontology", "project", "fixtures/customer.ttl", 
         "--target", "dbt", "--output", "tmp/test_output"],
        capture_output=True,
        text=True  
    )
    assert result.returncode == 0
```

---

### 3. End-to-End (E2E) Testing 📋 USER IMPLEMENTS
**Scope:** Complete workflow from ontology authoring to artifact deployment

**Implementation:** Users integrate toolkit CLI commands into their CI/CD pipelines

**Toolkit Provides:** Exit codes, validation reports, error messages for CI/CD integration

**Example User CI/CD Integration:**

#### Example GitHub Actions Workflow (User Implements)
```yaml
# .github/workflows/validate-ontology.yml (user creates)
name: Validate Ontology

on:
  pull_request:
    paths:
      - '**/*.ttl'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - name: Install Kairos Ontology Toolkit
        run: |
          pip install -e git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git#egg=kairos-ontology
      
      - name: Validate Ontology Files
        run: |
          for file in ontologies/*.ttl; do
            kairos-ontology validate "$file" --shapes shapes/
          done
      
      - name: Generate Artifacts
        if: success()
        run: |
          kairos-ontology project ontologies/core.ttl --target dbt --output artifacts/
```

#### Example Azure DevOps Pipeline (User Implements)
```yaml
# azure-pipelines.yml (user creates)
trigger:
  branches:
    include:
      - main
  paths:
    include:
      - ontologies/**/*.ttl

pool:
  vmImage: 'ubuntu-latest'

steps:
- task: UsePythonVersion@0
  inputs:
    versionSpec: '3.12'

- script: |
    pip install kairos-ontology
    kairos-ontology validate ontologies/core.ttl
  displayName: 'Validate Ontology'

- script: |
    kairos-ontology project ontologies/core.ttl --target dbt --output $(Build.ArtifactStagingDirectory)/dbt
  displayName: 'Generate DBT Artifacts'

- task: PublishBuildArtifacts@1
  inputs:
    pathToPublish: '$(Build.ArtifactStagingDirectory)'
    artifactName: 'ontology-artifacts'
```

---

### 4. User Acceptance Testing (UAT) 📋 USER CONDUCTS
**Scope:** Manual testing by end users in their environments

**Toolkit Support:** CLI commands, documentation, examples

**User Responsibilities:** Conduct UAT in their specific workflow contexts

**Example User Test Scenarios:**

#### UAT-1: Domain Expert Workflow (User Conducts)
**Participant:** Domain expert (user's team)

**Scenario:** Author new ontology class and validate locally

**Steps:**
1. Install toolkit: `pip install kairos-ontology`
2. Create/edit `.ttl` file in text editor
3. Run validation: `kairos-ontology validate my-ontology.ttl`
4. Fix any errors reported
5. Commit to Git when validation passes

**Success Criteria (User Defines):**
- User completes workflow independently
- Validation errors are understandable
- Able to fix errors without support

---

#### UAT-2: Data Engineer Artifact Deployment (User Conducts)
**Participant:** Data engineer (user's team)

**Scenario:** Download DBT artifacts and deploy to Microsoft Fabric

**Steps:**
1. Download artifact package from Azure Blob Storage
2. Extract DBT models
3. Copy models to Fabric DBT project
4. Run `dbt run`
5. Verify tables created in Lakehouse

**Success Criteria:**
- [ ] User completes steps in < 1 hour
- [ ] DBT models execute without errors
- [ ] Tables created match ontology definitions

**Metrics:**
- Time to complete: ___ minutes
- Number of issues encountered: ___
- Quality of documentation: ___ / 5

---

#### UAT-3: AI Developer Prompt Context Loading
**Participant:** AI developer

**Scenario:** Load prompt context into LLM agent

**Steps:**
1. Download prompt context artifact
2. Parse JSON file
3. Integrate context into system prompt
4. Test agent with semantic queries

**Success Criteria:**
- [ ] Agent correctly uses ontology terminology
- [ ] Synonyms recognized (e.g., "client" → "customer")
- [ ] Agent responses are semantically grounded

**Metrics:**
- Agent accuracy improvement: ___% 
- Time to integration: ___ minutes

---

### 5. Performance Testing 🚧 BASIC IMPLEMENTATION
**Scope:** Validate toolkit execution time and scalability

**Tools:** `pytest-benchmark` (can be added), manual timing

**Status:** Basic performance testing implemented; comprehensive benchmarks user responsibility

**Targets (Not Formally Tested):**
- Validation: < 1 minute for typical ontology (100-500 classes)
- Projection: < 2 minutes for 500-class ontology
- Multi-domain: Linear scaling with number of .ttl files

**User Can Test Performance:**

```python
# User can add performance tests
import time
from kairos_ontology.projector import project_ontology

def test_projection_performance():
    """Test projection speed for large ontology"""
    start = time.time()
    project_ontology(
        ontology_file="large_ontology.ttl",
        output_dir="output/",
        target="dbt"
    )
    duration = time.time() - start
    print(f"Projection took {duration:.2f} seconds")
    assert duration < 120  # < 2 minutes for 500-class ontology
```

---

### 6. Security Testing 📋 USER RESPONSIBILITY
**Scope:** Validate security controls for user's implementation

**Toolkit Security:** Minimal (local-only CLI tool, no secrets, no network calls)

**User Security Responsibilities:**
- Git repository access control
- CI/CD pipeline security
- Artifact storage security
- Secrets management (if publishing to cloud)

**User Can Implement Security Scans:**

#### Example: Secret Detection (User Implements)
```bash
# User adds to their CI/CD pipeline
# Install and run Gitleaks
gitleaks detect --source . --verbose
```

#### Example: Dependency Scanning (User Implements)
```bash
# User checks toolkit dependencies
pip install safety
safety check
```

#### Example: Code Security Scan (User Implements)
```bash
# User scans their ontology files and custom scripts
pip install bandit
bandit -r scripts/
```

**Toolkit Input Validation:**
- ✅ RDF syntax validation via rdflib (prevents malformed Turtle)
- ✅ File path validation (Path objects, existence checks)
- ✅ No arbitrary code execution (templates are Jinja2, sandboxed)

---

## Test Environments

### Local Development Environment ✅ PRIMARY ENVIRONMENT
**Purpose:** Developer testing during implementation

**Configuration:**
- Python 3.12 virtual environment
- Local Git repository  
- Sample ontology files (user creates)
- Toolkit installed: `pip install -e .` or `pip install kairos-ontology`

**Access:** All developers (users install locally)

**Status:** ✅ Toolkit runs entirely locally, no remote dependencies

---

### CI/CD Environment 📋 USER CONFIGURES
**Purpose:** Automated testing in user's CI/CD pipeline

**Configuration (User Implements):**
- GitHub Actions, Azure DevOps, GitLab CI, Jenkins, etc.
- Python 3.12 runner
- Install toolkit: `pip install kairos-ontology`
- Run commands: `kairos-ontology validate`, `kairos-ontology project`

**Triggers (User Defines):**
- Pull request: Validation
- Merge to main: Validation + projection + artifact publishing

**Status:** 📋 Users integrate toolkit CLI into their pipelines

---

### Test/Staging Environment 📋 USER MANAGES
**Purpose:** User's integration testing environment

**Configuration (User Implements):**
- User's Azure/AWS/GCP subscription
- Storage for generated artifacts
- Runtime systems (DBT, Neo4j, Azure Search, etc.)

**Access:** User's team

**Status:** 📋 Users create test environments for their workflows

---

### Production Environment 📋 USER MANAGES
**Purpose:** User's production artifact deployment

**Configuration (User Implements):**
- User's production cloud subscription
- Versioned artifact storage
- Production runtime systems

**Access:** User's CI/CD automation (service principals, etc.)

**Status:** 📋 Users manage production deployment

## Test Data Strategy

### Fixture Ontologies

| Fixture | Purpose | Size | Location |
|---------|---------|------|----------|
| `customer.ttl` | Valid example for happy path tests | 5 classes, 15 properties | `tests/fixtures/` |
| `customer.shacl.ttl` | SHACL shapes for customer ontology | 5 shapes | `tests/fixtures/` |
| `invalid.ttl` | Syntax error for validation tests | 1 class (broken) | `tests/fixtures/` |
| `customer_invalid.ttl` | SHACL violation example | 5 classes (violates constraints) | `tests/fixtures/` |
| `large_ontology_500.ttl` | Performance testing | 500 classes | `tests/fixtures/performance/` |
| `skos_customer.ttl` | SKOS mapping example | 1 concept, 3 synonyms | `tests/fixtures/` |

### Synthetic Data Generation
For scalability testing, generate ontologies programmatically:

```python
# tests/utils/ontology_generator.py
def generate_test_ontology(num_classes=100, num_properties=5):
    """Generate synthetic ontology for testing"""
    from rdflib import Graph, Namespace, RDF, OWL
    
    g = Graph()
    EX = Namespace("http://example.org/")
    g.bind("ex", EX)
    
    for i in range(num_classes):
        class_uri = EX[f"Class{i}"]
        g.add((class_uri, RDF.type, OWL.Class))
        
        for j in range(num_properties):
            prop_uri = EX[f"property{i}_{j}"]
            g.add((prop_uri, RDF.type, OWL.DatatypeProperty))
            g.add((prop_uri, RDFS.domain, class_uri))
    
    return g
```

---

## Test Automation

### CI/CD Test Workflow

```yaml
# .github/workflows/test.yml
name: Test Suite

on:
  pull_request:
  push:
    branches: [main]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - name: Install Dependencies
        run: pip install -r requirements.txt pytest pytest-cov
      
      - name: Run Unit Tests
        run: pytest tests/ --cov=scripts --cov-report=xml --cov-report=term
      
      - name: Check Coverage
        run: |
          coverage report --fail-under=80
      
      - name: Upload Coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml

  integration-tests:
    needs: unit-tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - run: pip install -r requirements.txt pytest
      
      - name: Run Integration Tests
        run: pytest tests/integration/ -v

  security-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Run Gitleaks
        uses: gitleaks/gitleaks-action@v2
      
      - name: Run Bandit (Python Security)
        run: |
          pip install bandit
          bandit -r scripts/ -f json -o bandit-report.json
```

---

## QA Process

### Pre-Commit Checks (Optional)
Developers can install pre-commit hooks to catch issues locally:

```bash
# Install pre-commit
pip install pre-commit

# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 24.1.0
    hooks:
      - id: black
  
  - repo: https://github.com/pycqa/flake8
    rev: 7.0.0
    hooks:
      - id: flake8
  
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
```

### Code Review Checklist
Reviewers verify:
- [ ] Unit tests added for new functionality
- [ ] Test coverage ≥ 80% (check coverage report)
- [ ] Integration tests updated if workflow changed
- [ ] Fixtures added for new test scenarios
- [ ] Security scan passes (no secrets, no vulnerabilities)
- [ ] Performance benchmarks within targets

---

## Defect Management

### Severity Levels

| Severity | Definition | Response Time | Example |
|----------|------------|---------------|---------|
| **P0 (Critical)** | CI/CD pipeline broken, no artifacts published | 1 hour | Validation script crashes on valid ontology |
| **P1 (High)** | Incorrect artifacts generated, affects runtime | 4 hours | DBT models missing columns |
| **P2 (Medium)** | Non-critical feature broken | 1 day | SKOS synonyms not extracted |
| **P3 (Low)** | Minor issue, workaround exists | 1 week | Validation warning message unclear |

### Defect Workflow
1. **Report:** Create GitHub issue with severity label
2. **Triage:** Platform team assesses severity and priority
3. **Fix:** Developer implements fix with test case
4. **Verify:** QA validates fix in CI/CD and staging
5. **Close:** Merge to main and deploy

---

## Test Metrics & Reporting

### Coverage Report
```bash
# Generate coverage report
pytest tests/ --cov=scripts --cov-report=html

# View report
open htmlcov/index.html
```

**Target:** 80%+ coverage for `scripts/` directory

### Test Execution Report
```bash
# Run with verbose output and JUnit XML for CI
pytest tests/ -v --junitxml=test-results.xml
```

**Metrics Tracked:**
- Total tests: 120+
- Pass rate: ≥ 95%
- Execution time: < 5 minutes

### Performance Benchmark Report
```bash
# Run performance tests with benchmarking
pytest tests/performance/ --benchmark-only --benchmark-json=benchmark.json
```

**Thresholds:**
- Validation: < 60s for 500-class ontology
- Projection: < 120s for 500-class ontology

---

## Continuous Improvement

### Test Review Cadence
- **Sprint Retrospective:** Review test failures and coverage
- **Monthly:** Analyze flaky tests and optimize
- **Quarterly:** Update test strategy based on production issues

### Test Debt Management
- **Definition:** Tests marked as `@pytest.mark.skip` or commented out
- **Policy:** No skipped tests allowed in main branch (fix or delete)
- **Review:** Sprint review includes test debt count (target: 0)

---

## Acceptance Criteria Summary

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| **Unit Test Coverage** | ≥ 80% | pytest --cov |
| **Integration Tests** | All critical paths covered | Manual review |
| **E2E Tests** | PR validation + main merge | GitHub Actions |
| **UAT Completion** | 3 scenarios passed | User feedback |
| **Performance** | < 5 min pipeline, < 2 min projection | CI/CD logs |
| **Security Scan** | 0 vulnerabilities | Gitleaks + Bandit |
| **Defect Rate** | < 5% validation errors | Validation reports |

---

**Testing Strategy Version:** 1.0  
**Last Updated:** January 2, 2026  
**Next Review:** Sprint 6 (Week 12) - Post-prototype retrospective
