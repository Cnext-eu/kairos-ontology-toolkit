# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Allow ``python -m kairos_ontology`` as an alternative to the ``kairos-ontology`` CLI.

This is the recommended way to invoke the toolkit in client hub repos because
it works in any virtual environment without needing ``Scripts/`` on PATH.

Examples::

    python -m kairos_ontology validate
    python -m kairos_ontology project --target dbt
    python -m kairos_ontology --version
"""

import sys

from kairos_ontology.cli.main import _ensure_utf8_stdio, cli

_ensure_utf8_stdio()

if __name__ == "__main__":
    cli()
