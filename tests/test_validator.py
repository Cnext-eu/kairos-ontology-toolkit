"""Tests for the validation module."""

import pytest
from pathlib import Path
from kairos_ontology.validator import run_validation


class TestValidator:
    """Test the validation pipeline."""
    
    def test_syntax_validation_valid_file(self, temp_dir, sample_ontology, capsys):
        """Test syntax validation with valid ontology."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        ontology_file = ontologies_dir / "customer.ttl"
        ontology_file.write_text(sample_ontology, encoding='utf-8')
        
        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()
        
        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False
        )
        
        captured = capsys.readouterr()
        assert "Syntax Validation" in captured.out
        assert "Passed:" in captured.out or "✓" in captured.out
    
    def test_syntax_validation_invalid_file(self, temp_dir, capsys):
        """Test syntax validation with invalid ontology."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        invalid_file = ontologies_dir / "invalid.ttl"
        invalid_file.write_text("Invalid Turtle @#$%", encoding='utf-8')
        
        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()
        
        with pytest.raises(SystemExit):
            run_validation(
                ontologies_path=ontologies_dir,
                shapes_path=shapes_dir,
                catalog_path=None,
                do_syntax=True,
                do_shacl=False,
                do_consistency=False
            )
        
        captured = capsys.readouterr()
        assert "Failed:" in captured.out or "✗" in captured.out
    
    def test_empty_ontologies_directory(self, temp_dir, capsys):
        """Test validation with empty ontologies directory."""
        ontologies_dir = temp_dir / "ontologies"
        ontologies_dir.mkdir()
        
        shapes_dir = temp_dir / "shapes"
        shapes_dir.mkdir()
        
        run_validation(
            ontologies_path=ontologies_dir,
            shapes_path=shapes_dir,
            catalog_path=None,
            do_syntax=True,
            do_shacl=False,
            do_consistency=False
        )
        
        captured = capsys.readouterr()
        assert "Found 0 ontology files" in captured.out
