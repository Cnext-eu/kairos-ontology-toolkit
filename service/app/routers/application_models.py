# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Application Models router — list and read Mermaid class-diagram files.

Application models are stored as ``*.mmd`` files under
``output/medallion/silver/`` in each ontology-hub repository.  They complement
ontology domains by providing entity-relationship diagrams that can be rendered
directly in the web UI.
"""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from ..config import get_github_service

router = APIRouter()


@router.get("/")
async def list_application_models(
    repo_owner: Optional[str] = Header(None, alias="X-Kairos-Repo-Owner"),
    repo_name: Optional[str] = Header(None, alias="X-Kairos-Repo-Name"),
):
    """Return a list of available application-model files for the active repo.

    Each entry has ``name``, ``path``, ``sha``, and ``size``.
    Returns an empty list when the silver output folder does not exist.
    """
    gh = get_github_service()
    files = await gh.list_mmd_files(owner=repo_owner, repo=repo_name)
    return files


@router.get("/{name}")
async def get_application_model(
    name: str,
    repo_owner: Optional[str] = Header(None, alias="X-Kairos-Repo-Owner"),
    repo_name: Optional[str] = Header(None, alias="X-Kairos-Repo-Name"),
):
    """Return the raw Mermaid content of a single application model.

    ``name`` should be the filename without the ``.mmd`` extension, e.g. ``customer-order``.
    """
    gh = get_github_service()
    try:
        content = await gh.read_mmd_file(name, owner=repo_owner, repo=repo_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Application model '{name}' not found.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"name": name, "content": content}
