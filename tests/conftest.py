# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Test fixtures and configuration."""

import sys
import pytest
from pathlib import Path
import tempfile
import shutil
import types

# Make sibling helper modules (e.g. archetype_fixtures.py) importable by name even
# though `tests` is a package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ---------------------------------------------------------------------------
# Block the installed referencemodels package during tests.
# ---------------------------------------------------------------------------
# On CI, ``uv sync --all-groups`` installs ``kairos-ontology-referencemodels``
# as a dev dependency.  Tests that build synthetic fixtures and expect no
# reference-models resolution (the majority) would silently resolve the real
# package instead — causing hangs, false passes, or mysterious failures.
#
# We block the package at import time by inserting a sentinel that raises
# ``ImportError`` on attribute access.  Tests that **want** the real package
# (``test_refmodels_contract.py``, ``test_refmodels_package_resolution.py``)
# clear the sentinel at module level before computing their refmodels root.
_BLOCK_MOD = types.ModuleType("kairos_ontology_referencemodels")


def _raise_import_error(*a, **kw):
    raise ImportError("blocked by conftest for test isolation")


_BLOCK_MOD.refmodels_root = _raise_import_error  # type: ignore[attr-defined]
sys.modules["kairos_ontology_referencemodels"] = _BLOCK_MOD


# ---------------------------------------------------------------------------
# AI provider env-var isolation (DD-159)
# ---------------------------------------------------------------------------
# ``_load_dotenv_from_hub()`` runs at import time (ai_provider.py:94) and walks
# up 5 parents looking for a .env file. A developer with a .env at the repo
# root (or running pytest inside a hub checkout) gets a real GITHUB_TOKEN into
# os.environ before collection — "not configured" tests then fail locally while
# the code is correct. We delete every name in ``AI_ENV_VAR_NAMES`` before each
# test so tests see a clean slate.
import os as _os

try:
    from kairos_ontology.core.ai_provider import AI_ENV_VAR_NAMES as _AI_ENV_VARS
except ImportError:  # pragma: no cover — ai_provider must be importable
    _AI_ENV_VARS = frozenset()


@pytest.fixture(autouse=True)
def _clean_ai_env():
    """Delete every AI provider env var before each test (DD-159)."""
    for key in _AI_ENV_VARS:
        _os.environ.pop(key, None)
    yield
    for key in _AI_ENV_VARS:
        _os.environ.pop(key, None)


@pytest.fixture
def github_provider_env():
    """Opt-in fixture: set a configured GitHub Models provider for tests that need one."""
    _os.environ["GITHUB_TOKEN"] = "ghp_TEST_TOKEN_FOR_TESTS_ONLY"
    yield
    _os.environ.pop("GITHUB_TOKEN", None)


@pytest.fixture(autouse=True)
def _block_ai_probe(monkeypatch):
    """Prevent any test from hitting the network via ai_preflight probe.

    Tests that need a live probe must use the ``live_probe`` marker and override
    this fixture.
    """
    try:
        import kairos_ontology.core.ai_preflight as _ap
        monkeypatch.setattr(_ap, "_probe_client", _raise_for_probe, raising=False)
    except ImportError:
        pass  # ai_preflight not yet created


def _raise_for_probe(*a, **kw):
    raise RuntimeError(
        "ai_preflight probe blocked by conftest; use the 'live_probe' marker for real network tests"
    )


# ---------------------------------------------------------------------------
# Guard: detect stale (non-editable) installs early
# ---------------------------------------------------------------------------
def _check_editable_install() -> None:
    """Warn if kairos_ontology is loaded from site-packages instead of src/.

    When hub repos (which depend on kairos-ontology-toolkit via git+https)
    are installed in the same Python environment, ``pip install`` can silently
    overwrite the editable install with the remote version.  This guard
    catches that early so tests don't run against stale code.
    """
    import kairos_ontology

    module_path = Path(kairos_ontology.__file__).resolve()
    repo_src = (Path(__file__).parent.parent / "src").resolve()
    if not str(module_path).startswith(str(repo_src)):
        import warnings

        warnings.warn(
            f"kairos_ontology is loading from {module_path} instead of "
            f"{repo_src}.  Tests may run against stale code.\n"
            f"Fix: pip install -e {Path(__file__).parent.parent}",
            stacklevel=1,
        )


_check_editable_install()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp = Path(tempfile.mkdtemp())
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


@pytest.fixture
def sample_ontology():
    """Sample ontology content in Turtle format."""
    return """
@prefix : <http://kairos.example/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

:CustomerOntology a owl:Ontology ;
    rdfs:label "Customer Ontology"@en ;
    rdfs:comment "Domain model for customer management"@en ;
    owl:versionInfo "1.1.3" .

:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .

:customerName a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Name" ;
    rdfs:comment "The name of the customer" .

:customerEmail a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Email" ;
    rdfs:comment "Email address of the customer" .
"""


@pytest.fixture
def sample_ontology_with_subclass():
    """Sample ontology with inheritance."""
    return """
@prefix : <http://kairos.example/ontology/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

:PersonOntology a owl:Ontology ;
    rdfs:label "Person Ontology"@en ;
    rdfs:comment "Domain model for person management"@en ;
    owl:versionInfo "1.1.3" .

:Person a owl:Class ;
    rdfs:label "Person" ;
    rdfs:comment "A person entity" .

:Employee a owl:Class ;
    rdfs:label "Employee" ;
    rdfs:comment "An employee entity" ;
    rdfs:subClassOf :Person .

:personName a owl:DatatypeProperty ;
    rdfs:domain :Person ;
    rdfs:range xsd:string ;
    rdfs:label "Person Name" .

:employeeId a owl:DatatypeProperty ;
    rdfs:domain :Employee ;
    rdfs:range xsd:string ;
    rdfs:label "Employee ID" .
"""


@pytest.fixture
def ontology_files(temp_dir, sample_ontology, sample_ontology_with_subclass):
    """Create sample ontology files in a temporary directory."""
    ontologies_dir = temp_dir / "ontologies"
    ontologies_dir.mkdir()

    # Create multiple ontology files
    customer_file = ontologies_dir / "customer.ttl"
    customer_file.write_text(sample_ontology, encoding="utf-8")

    person_file = ontologies_dir / "person.ttl"
    person_file.write_text(sample_ontology_with_subclass, encoding="utf-8")

    return {"dir": ontologies_dir, "customer": customer_file, "person": person_file}


@pytest.fixture
def http_ontology():
    """Sample ontology using HTTP namespace (standard semantic web practice)."""
    return """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.org/ontology/> .

ex:Product a owl:Class ;
    rdfs:label "Product" ;
    rdfs:comment "A product in the catalog" .

ex:productName a owl:DatatypeProperty ;
    rdfs:domain ex:Product ;
    rdfs:range xsd:string ;
    rdfs:label "Product Name" .

ex:productPrice a owl:DatatypeProperty ;
    rdfs:domain ex:Product ;
    rdfs:range xsd:decimal ;
    rdfs:label "Product Price" .
"""


@pytest.fixture
def hash_ontology():
    """Sample ontology using hash-based HTTP namespace (common in FIBO, etc.)."""
    return """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix fibo: <https://spec.edmcouncil.org/fibo/ontology/FND/Relations/Relations#> .

fibo:Organization a owl:Class ;
    rdfs:label "Organization" ;
    rdfs:comment "A legal organization" .

fibo:orgName a owl:DatatypeProperty ;
    rdfs:domain fibo:Organization ;
    rdfs:range xsd:string ;
    rdfs:label "Organization Name" .
"""


@pytest.fixture
def ontology_with_fibo_imports():
    """Sample ontology that imports FIBO classes but defines its own custom classes."""
    return """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix fibo: <https://spec.edmcouncil.org/fibo/ontology/FND/Relations/Relations#> .
@prefix custom: <http://mycorp.example.com/ontology#> .

# Declare this as the main ontology (imports FIBO)
<http://mycorp.example.com/ontology> a owl:Ontology ;
    rdfs:label "My Corporate Ontology" ;
    owl:imports <https://spec.edmcouncil.org/fibo/ontology/FND/Relations/Relations/> .

# Imported FIBO classes (many of them)
fibo:Organization a owl:Class ;
    rdfs:label "Organization" .

fibo:Person a owl:Class ;
    rdfs:label "Person" .

fibo:LegalEntity a owl:Class ;
    rdfs:label "Legal Entity" .

fibo:Contract a owl:Class ;
    rdfs:label "Contract" .

fibo:Agreement a owl:Class ;
    rdfs:label "Agreement" .

# Custom classes (fewer, but these are what we want to project)
custom:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer in our system" .

custom:Order a owl:Class ;
    rdfs:label "Order" ;
    rdfs:comment "A customer order" .

custom:Product a owl:Class ;
    rdfs:label "Product" ;
    rdfs:comment "A product in our catalog" .

custom:customerName a owl:DatatypeProperty ;
    rdfs:domain custom:Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Name" .

custom:orderTotal a owl:DatatypeProperty ;
    rdfs:domain custom:Order ;
    rdfs:range xsd:decimal ;
    rdfs:label "Order Total" .
"""


@pytest.fixture
def ontology_with_declaration():
    """Ontology with proper owl:Ontology declaration (semantic web best practice)."""
    return """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.com/myapp/ontology#> .

# Ontology declaration (THIS defines the main namespace)
<http://example.com/myapp/ontology> a owl:Ontology ;
    rdfs:label "My Application Ontology" ;
    owl:versionInfo "1.0.0" ;
    owl:imports <https://spec.edmcouncil.org/fibo/ontology/FND/Relations/Relations/> .

# Custom classes
ex:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "A customer entity" .

ex:customerName a owl:DatatypeProperty ;
    rdfs:domain ex:Customer ;
    rdfs:range xsd:string .
"""


@pytest.fixture
def sample_shacl_shapes():
    """Sample SHACL shapes with various constraint types for testing."""
    return """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <http://kairos.example/ontology/> .

:CustomerShape a sh:NodeShape ;
    sh:targetClass :Customer ;
    sh:property [
        sh:path :customerName ;
        sh:minCount 1 ;
        sh:minLength 2 ;
        sh:maxLength 100 ;
        sh:datatype xsd:string ;
    ] ;
    sh:property [
        sh:path :customerEmail ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
    ] .
"""
