# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Provenance sidecar against the synthetic ``v5-hub`` scenario (DD-218).

Uses the embedded hub rather than a hand-built minimal one so the assertions run over
real authored inputs: two bindings, two source vocabularies, an ontology, contracted dbt
models and the packaged templates.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from kairos_ontology.cli.compile import _emit_compile_artifacts
from kairos_ontology.core.compiler import CompileMode, compile_domain
from kairos_ontology.core.compiler.provenance import PROVENANCE_SCHEMA

_HUB = Path(__file__).parent / "v5-hub"


def _emit(tmp_path: Path) -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_HUB, hub)
    target = tmp_path / "publish" / "medallion" / "dbt"
    _emit_compile_artifacts(compile_domain(hub, "party", CompileMode.EMIT), target)
    return target


def _document(target: Path) -> dict:
    return json.loads((target / "metadata" / "party.provenance.json").read_text(encoding="utf-8"))


def test_emit_writes_a_sidecar_describing_the_scenario_hub(tmp_path):
    document = _document(_emit(tmp_path))

    assert document["schema"] == PROVENANCE_SCHEMA
    assert document["domain"] == "party"
    assert document["adapter"] == "fabric-warehouse"
    assert len(document["provenanceHash"]) == 64

    names = {item["name"] for item in document["inputs"]}
    assert "integration/bindings/customer.binding.yaml" in names
    assert "integration/bindings/country.binding.yaml" in names
    assert "integration/sources/crm/crm.vocabulary.ttl" in names
    assert "model/ontologies/party.ttl" in names
    assert "kairos.yaml" in names
    assert any(name.startswith("templates/") for name in names)


def test_input_names_are_posix_on_every_platform(tmp_path):
    """The name is hashed into `provenance_hash`, so a separator decides the digest.

    Four of the six `ProvenanceInput` sites normalised and two did not, so on Windows
    the bindings, source vocabularies and ontology arrived as
    `integration\\bindings\\customer.binding.yaml` while the templates arrived as
    `templates/...`. The same hub then hashed differently per platform, which quietly
    breaks the reproducibility a pinned release tag is supposed to give.
    """
    document = _document(_emit(tmp_path))
    offenders = [item["name"] for item in document["inputs"] if "\\" in item["name"]]
    assert not offenders, offenders


def test_every_digest_matches_the_authored_file_on_disk(tmp_path):
    hub = tmp_path / "hub"
    shutil.copytree(_HUB, hub)
    target = tmp_path / "publish" / "medallion" / "dbt"
    _emit_compile_artifacts(compile_domain(hub, "party", CompileMode.EMIT), target)

    document = _document(target)
    digests = {item["name"]: item["sha256"] for item in document["inputs"]}
    for name in (
        "integration/bindings/customer.binding.yaml",
        "model/ontologies/party.ttl",
        "kairos.yaml",
    ):
        content = (hub / name).read_text(encoding="utf-8")
        assert digests[name] == hashlib.sha256(content.encode("utf-8")).hexdigest(), name


def test_manifest_records_the_sidecar_without_changing_shape(tmp_path):
    target = _emit(tmp_path)
    manifest = json.loads(
        (target / ".kairos-compile-manifest.party.json").read_text(encoding="utf-8")
    )

    assert set(manifest) == {"files", "schema"}
    entry = next(
        item for item in manifest["files"] if item["path"] == "metadata/party.provenance.json"
    )
    on_disk = (target / "metadata" / "party.provenance.json").read_bytes()
    assert entry["sha256"] == hashlib.sha256(on_disk).hexdigest()


def test_editing_one_binding_moves_one_digest_and_the_hash(tmp_path):
    hub = tmp_path / "hub"
    shutil.copytree(_HUB, hub)
    target = tmp_path / "publish" / "medallion" / "dbt"

    _emit_compile_artifacts(compile_domain(hub, "party", CompileMode.EMIT), target)
    before = _document(target)

    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(binding.read_text(encoding="utf-8") + "\n# touched\n", encoding="utf-8")
    _emit_compile_artifacts(compile_domain(hub, "party", CompileMode.EMIT), target)
    after = _document(target)

    assert before["provenanceHash"] != after["provenanceHash"]
    moved = {
        name
        for name in {item["name"] for item in before["inputs"]}
        if _digest(before, name) != _digest(after, name)
    }
    assert moved == {"integration/bindings/customer.binding.yaml"}


def test_re_emitting_unchanged_inputs_is_byte_identical(tmp_path):
    hub = tmp_path / "hub"
    shutil.copytree(_HUB, hub)
    target = tmp_path / "publish" / "medallion" / "dbt"
    sidecar = target / "metadata" / "party.provenance.json"

    _emit_compile_artifacts(compile_domain(hub, "party", CompileMode.EMIT), target)
    first = sidecar.read_bytes()
    _emit_compile_artifacts(compile_domain(hub, "party", CompileMode.EMIT), target)

    assert sidecar.read_bytes() == first


def _digest(document: dict, name: str) -> str | None:
    for item in document["inputs"]:
        if item["name"] == name:
            return item["sha256"]
    return None
