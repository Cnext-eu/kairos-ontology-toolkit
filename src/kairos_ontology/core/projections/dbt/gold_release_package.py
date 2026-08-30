# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Package validated Gold Power BI output into one release archive (DD-206 #8/#12 item 8).

``render_powerbi_artifacts`` returns TMDL, PBIP wrapper, DAX, DDL, ERD, dbt, and the
Kairos product-report JSON all mixed together in one ``dict[path, content]`` -- exactly
right for validation and for the ``emit-gold`` publish tree, but not what ships to
Fabric. The deployable unit is only the ``*.SemanticModel`` and ``*.Report`` folders;
everything else (DDL, ERD, DAX, dbt, the product report) is hub-internal.

This module is deliberately pure: it takes already-generated, already-validated
artifacts (one dict per domain) and produces deterministic zip bytes plus a SHA-256
digest. It does not itself run compilation, Gold projection, or validation -- the
release workflow (or a test) is expected to have done that first, the same way
``emit-gold`` does (``pbip_validate`` + optional ``tmdl_validate``), and to pass only
artifacts that already passed those gates.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from io import BytesIO

#: Path segments that mark a folder as a deployable Fabric item. Everything else
#: ``render_powerbi_artifacts`` returns (DDL, ERD, DAX, dbt, the Kairos product report,
#: fabric-cicd `parameter.yml`) is hub-internal and never shipped to Fabric.
_ITEM_SUFFIXES = (".SemanticModel", ".Report")

#: Fixed archive-member timestamp so re-packaging identical artifacts produces a
#: byte-identical zip (zipfile otherwise stamps "now", which would make the SHA-256
#: differ release to release even when nothing changed).
_FIXED_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class PowerBiReleaseArchive:
    """The packaged Power BI release artifact and its recorded checksum."""

    zip_bytes: bytes
    sha256: str
    domains: tuple[str, ...]
    file_count: int


def is_deployable_item_path(path: str) -> bool:
    """Return whether *path* falls inside a ``*.SemanticModel`` or ``*.Report`` folder."""
    return any(f"{suffix}/" in path for suffix in _ITEM_SUFFIXES)


def filter_deployable_artifacts(artifacts: dict[str, str]) -> dict[str, str]:
    """Keep only the ``*.SemanticModel``/``*.Report`` subtree of one domain's artifacts.

    Drops the DDL, ERD, DAX, dbt models, the Kairos product-report JSON, and
    fabric-cicd's ``parameter.yml`` -- none of those are Fabric package files, and
    ``parameter.yml`` in particular is deploy-time *tooling*, applied by fabric-cicd
    from the dataplatform's ``repository_directory`` root, not archive content.
    """
    return {path: content for path, content in artifacts.items() if is_deployable_item_path(path)}


def build_powerbi_release_archive(
    domain_artifacts: dict[str, dict[str, str]],
) -> PowerBiReleaseArchive | None:
    """Zip every domain's deployable Power BI item folders into one release archive.

    *domain_artifacts* maps each Gold-configured domain to the full artifact dict
    ``generate_gold_from_compile_plan`` returned for it (paths already domain-prefixed,
    e.g. ``"invoice/Invoice.SemanticModel/..."``). Returns ``None`` when no domain
    contributes a deployable item -- callers must not emit a dangling, empty archive
    (DD-206 #8: "fail when Gold is configured but the expected report or semantic model
    is absent" implies the inverse too: no archive when nothing is configured).

    Deterministic: fixed per-entry timestamps and a stable, sorted member order, so
    identical input always produces an identical archive and therefore an identical
    SHA-256 -- required for the checksum to mean anything as release evidence.
    """
    combined: dict[str, str] = {}
    contributing_domains: list[str] = []
    for domain in sorted(domain_artifacts):
        deployable = filter_deployable_artifacts(domain_artifacts[domain])
        if not deployable:
            continue
        # DD-206 §8 item 7: "fail when Gold is configured but the expected report or
        # semantic model is absent." render_powerbi_artifacts always emits both for a
        # Gold-configured domain, so this only trips on a genuine defect upstream --
        # exactly the case this is a defense against.
        missing = [
            suffix
            for suffix in _ITEM_SUFFIXES
            if not any(f"{suffix}/" in path for path in deployable)
        ]
        if missing:
            raise ValueError(
                f"domain {domain!r} is Gold-configured but its packaged output is "
                f"missing: {', '.join(missing)}"
            )
        contributing_domains.append(domain)
        overlap = combined.keys() & deployable.keys()
        if overlap:
            raise ValueError(
                f"domain {domain!r} contributes archive path(s) already written by "
                f"another domain: {sorted(overlap)}"
            )
        combined.update(deployable)

    if not combined:
        return None

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(combined):
            info = zipfile.ZipInfo(path, date_time=_FIXED_ZIP_DATETIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, combined[path])
    zip_bytes = buffer.getvalue()

    return PowerBiReleaseArchive(
        zip_bytes=zip_bytes,
        sha256=hashlib.sha256(zip_bytes).hexdigest(),
        domains=tuple(contributing_domains),
        file_count=len(combined),
    )
