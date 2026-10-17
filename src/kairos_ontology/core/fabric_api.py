# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A minimal, read-only Fabric REST client for resolving environment IDs (DD-255, #1114).

Only what environment resolution needs: list the workspaces the caller can see and the
Warehouses in one of them. Pages are followed through ``continuationToken`` and a 429 is
retried after its ``Retry-After``. Nothing here writes to Fabric.

The token comes from ``azure-identity`` when it is installed (the ``azure`` extra), and
otherwise from the Azure CLI, which every GitHub runner has after ``azure/login``. The
transport is injectable so tests never touch the network.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterator

#: Fabric REST API root.
FABRIC_API = "https://api.fabric.microsoft.com/v1"

#: The scope a Fabric REST token is issued for.
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"

#: ``(url, token) -> parsed JSON``. Raises :class:`FabricApiError` on failure.
Transport = Callable[[str, str], dict]

_MAX_RETRIES = 3


class FabricApiError(Exception):
    """A Fabric REST call failed, or no token could be obtained."""


@dataclass(frozen=True, slots=True)
class FabricWorkspace:
    """One workspace the caller can see."""

    id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class FabricWarehouse:
    """One Warehouse item, with the SQL endpoint host dbt connects to."""

    id: str
    display_name: str
    workspace_id: str
    connection_string: str


def acquire_token() -> str:
    """Return a Fabric REST token from azure-identity, or failing that the Azure CLI."""
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError:
        DefaultAzureCredential = None  # noqa: N806
    if DefaultAzureCredential is not None:
        try:
            credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            return credential.get_token(FABRIC_SCOPE).token
        except Exception as exc:  # azure-identity raises a family of auth errors
            raise FabricApiError(f"azure-identity could not get a Fabric token: {exc}") from exc
    az = shutil.which("az")
    if az is None:
        raise FabricApiError(
            "No Fabric token: install the azure extra (azure-identity) or the Azure CLI, "
            "and sign in (`az login`, or `azure/login` in a workflow)"
        )
    resource = FABRIC_SCOPE.removesuffix("/.default")
    completed = subprocess.run(
        [az, "account", "get-access-token", "--resource", resource, "--query", "accessToken",
         "-o", "tsv"],
        capture_output=True,
        text=True,
        check=False,
    )
    token = completed.stdout.strip()
    if completed.returncode != 0 or not token:
        raise FabricApiError(
            f"`az account get-access-token` failed: {completed.stderr.strip() or 'no token'}"
        )
    return token


def urllib_transport(url: str, token: str) -> dict:
    """GET *url* with a bearer token, retrying a 429 after its ``Retry-After``."""
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    for attempt in range(_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < _MAX_RETRIES:
                time.sleep(min(int(exc.headers.get("Retry-After") or 5), 60))
                continue
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise FabricApiError(f"GET {url} failed: HTTP {exc.code} {body}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise FabricApiError(f"GET {url} failed: {exc}") from exc
    raise FabricApiError(f"GET {url} failed: still throttled after {_MAX_RETRIES} retries")


class FabricClient:
    """The few read-only Fabric REST calls environment resolution makes."""

    def __init__(
        self,
        *,
        token: str | None = None,
        transport: Transport | None = None,
        token_provider: Callable[[], str] = acquire_token,
    ) -> None:
        self._token = token
        self._token_provider = token_provider
        self._transport = transport or urllib_transport

    def _get_pages(self, path: str) -> Iterator[dict]:
        if self._token is None:
            self._token = self._token_provider()
        url = f"{FABRIC_API}{path}"
        while True:
            page = self._transport(url, self._token)
            yield from page.get("value") or ()
            continuation = page.get("continuationToken")
            if not continuation:
                return
            separator = "&" if "?" in path else "?"
            url = (
                f"{FABRIC_API}{path}{separator}continuationToken="
                f"{urllib.parse.quote(str(continuation), safe='')}"
            )

    def workspaces(self) -> list[FabricWorkspace]:
        """Every workspace the caller can see."""
        return [
            FabricWorkspace(id=str(item["id"]), display_name=str(item.get("displayName", "")))
            for item in self._get_pages("/workspaces")
        ]

    def warehouses(self, workspace_id: str) -> list[FabricWarehouse]:
        """The Warehouses in one workspace, with their SQL connection strings."""
        quoted = urllib.parse.quote(workspace_id, safe="")
        return [
            FabricWarehouse(
                id=str(item["id"]),
                display_name=str(item.get("displayName", "")),
                workspace_id=workspace_id,
                connection_string=str((item.get("properties") or {}).get("connectionString", "")),
            )
            for item in self._get_pages(f"/workspaces/{quoted}/warehouses")
        ]
