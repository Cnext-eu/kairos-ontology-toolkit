"""Local file service — reads ontology files from disk instead of GitHub.

Used when ``KAIROS_DEV_MODE=true``.  Provides the same async interface as
``github_service`` so routers can use either backend transparently.
"""

from pathlib import Path
from typing import Optional

from ..config import settings


def _ontologies_dir() -> Path:
    return Path(settings.local_ontologies_dir)


async def list_ttl_files(
    token: str = "",
    path: Optional[str] = None,
    branch: Optional[str] = None,
) -> list[dict]:
    """List ``*.ttl`` / ``*.rdf`` files in the local ontologies directory."""
    base = Path(path) if path else _ontologies_dir()
    if not base.exists():
        return []
    return [
        {
            "name": f.name,
            "path": str(f.relative_to(base.parent)) if base.parent != base else f.name,
            "sha": "",
            "size": f.stat().st_size,
        }
        for f in sorted(base.iterdir())
        if f.suffix in (".ttl", ".rdf")
    ]


async def read_file(
    token: str = "",
    path: str = "",
    branch: Optional[str] = None,
) -> str:
    """Read a file from disk. *path* is relative to the workspace root or absolute."""
    # Try as-is first, then relative to ontologies dir
    p = Path(path)
    if not p.is_absolute():
        p = _ontologies_dir().parent / path
    return p.read_text(encoding="utf-8")


async def create_branch(token: str, branch_name: str, from_branch: Optional[str] = None) -> dict:
    raise NotImplementedError("create_branch is not available in dev mode")


async def write_file(
    token: str, path: str, content: str, branch: str, message: str, sha: Optional[str] = None,
) -> dict:
    raise NotImplementedError("write_file is not available in dev mode")


async def create_pull_request(
    token: str, branch: str, title: str, body: str = "", base: Optional[str] = None,
) -> dict:
    raise NotImplementedError("create_pull_request is not available in dev mode")


async def compare_branches(token: str, base: str, head: str) -> dict:
    raise NotImplementedError("compare_branches is not available in dev mode")
