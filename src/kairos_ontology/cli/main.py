"""Main CLI entry point for kairos-ontology toolkit."""

import click
from pathlib import Path
from ..validator import run_validation
from ..projector import run_projections
from ..catalog_test import test_catalog_resolution


@click.group()
@click.version_option()
def cli():
    """Kairos Ontology Toolkit - Validation and projection tools for OWL/Turtle ontologies."""
    pass


@cli.command()
@click.option('--ontologies', type=click.Path(exists=True), default='ontologies',
              help='Path to ontologies directory')
@click.option('--shapes', type=click.Path(exists=True), default='shapes',
              help='Path to SHACL shapes directory')
@click.option('--catalog', type=click.Path(exists=True), default='reference-models/catalog-v001.xml',
              help='Path to catalog file for resolving imports')
@click.option('--all', 'validate_all', is_flag=True,
              help='Validate all: syntax + SHACL + consistency')
@click.option('--syntax', is_flag=True, help='Validate syntax only')
@click.option('--shacl', is_flag=True, help='Validate SHACL only')
@click.option('--consistency', is_flag=True, help='Validate consistency only')
def validate(ontologies, shapes, catalog, validate_all, syntax, shacl, consistency):
    """Validate ontologies (syntax, SHACL, consistency)."""
    ontologies_path = Path(ontologies)
    shapes_path = Path(shapes)
    catalog_path = Path(catalog) if catalog else None
    
    # Default to all if nothing specified
    if not any([validate_all, syntax, shacl, consistency]):
        validate_all = True
    
    run_validation(
        ontologies_path=ontologies_path,
        shapes_path=shapes_path,
        catalog_path=catalog_path,
        do_syntax=validate_all or syntax,
        do_shacl=validate_all or shacl,
        do_consistency=validate_all or consistency
    )


@cli.command()
@click.option('--ontologies', type=click.Path(exists=True), default='ontologies',
              help='Path to ontologies directory')
@click.option('--catalog', type=click.Path(exists=True), default='reference-models/catalog-v001.xml',
              help='Path to catalog file for resolving imports')
@click.option('--output', type=click.Path(), default='output',
              help='Output directory for projections')
@click.option('--target', type=click.Choice(['all', 'dbt', 'neo4j', 'azure-search', 'a2ui', 'prompt']),
              default='all', help='Projection target')
@click.option('--namespace', type=str, default=None,
              help='Base namespace to project (e.g., http://example.org/ont/). Auto-detects if not provided.')
def project(ontologies, catalog, output, target, namespace):
    """Generate projections from ontologies."""
    ontologies_path = Path(ontologies)
    catalog_path = Path(catalog) if catalog else None
    output_path = Path(output)
    
    run_projections(
        ontologies_path=ontologies_path,
        catalog_path=catalog_path,
        output_path=output_path,
        target=target,
        namespace=namespace
    )


@cli.command(name='catalog-test')
@click.option('--catalog', type=click.Path(exists=True), required=True,
              help='Path to catalog file to test')
@click.option('--ontology', type=click.Path(exists=True),
              help='Optional: test with specific ontology file')
def catalog_test_cmd(catalog, ontology):
    """Test catalog resolution for imports."""
    catalog_path = Path(catalog)
    ontology_path = Path(ontology) if ontology else None
    
    test_catalog_resolution(catalog_path, ontology_path)


if __name__ == '__main__':
    cli()
