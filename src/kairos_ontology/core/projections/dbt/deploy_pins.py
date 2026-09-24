# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Versions of the deploy tooling the scaffolded dataplatform workflow installs (DD-239).

Pinned here, in the toolkit, and bumped only by a toolkit release -- the same manual
refresh as the vendored BPA rules and the ``semantic-link-labs`` pin (DD-238). The deploy
workflow template carries the literal version; ``tests/test_init_dataplatform.py`` fails
when the two disagree.
"""

from __future__ import annotations

#: Verified against 1.3.0: ``FabricWorkspace(repository_directory=, token_credential=,
#: item_type_in_scope=, environment=, workspace_id=)``, ``publish_all_items``, and
#: ``parameter.yml`` read from the root of ``repository_directory``.
FABRIC_CICD_PIN = "1.3.0"
