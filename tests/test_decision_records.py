# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the OKF decision-log parser, validator, and serializer (DD-141)."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from kairos_ontology.core import decision_records as dr

_VALID_BODY = """# Context / Finding
The RoRo source cannot populate ISO container fields.

# Decision
Use MMT/Equipment only.

# Alternatives rejected

| Option | Why rejected |
|--------|--------------|
| Subclass Container | wrong grain, mandatory containerNumber |

# Consequences
Validate with --degraded.
"""


def _write(dirpath: Path, name: str, frontmatter: str, body: str = _VALID_BODY) -> Path:
    path = dirpath / name
    path.write_text(f"---\n{frontmatter}---\n\n{body}", encoding="utf-8")
    return path


def _accepted_fm(record_id: str) -> str:
    return (
        "type: Decision Record\n"
        f"id: {record_id}\n"
        "title: Equipment uses MMT only\n"
        "domain: equipment\n"
        "status: stable\n"
        "decision_state: Accepted\n"
        "materiality: [evidence-conflict]\n"
        "generated: { by: kairos-ontology-toolkit/9.9.9, at: 2026-07-28T21:00:00Z }\n"
        "sources:\n"
        "  - { id: eq, resource: https://example.com/equipment.ttl }\n"
    )


@pytest.fixture()
def bundle(tmp_path: Path) -> Path:
    d = tmp_path / "decisions"
    d.mkdir()
    return d


def test_valid_accepted_record_has_no_findings(bundle: Path):
    _write(bundle, "HUB-DD-20260728-a1b2c3.md", _accepted_fm("HUB-DD-20260728-a1b2c3"))
    result = dr.validate_decision_bundle(bundle)
    assert result.errors == []
    assert result.warnings == []
    assert len(result.records) == 1


def test_absent_bundle_is_empty_and_passing(tmp_path: Path):
    result = dr.validate_decision_bundle(tmp_path / "nope")
    assert result.records == []
    assert result.errors == []


def test_reserved_and_template_files_are_not_records(bundle: Path):
    (bundle / "README.md").write_text("# readme", encoding="utf-8")
    (bundle / "index.md").write_text("# index", encoding="utf-8")
    (bundle / "HUB-DD-template.md.template").write_text("---\ntype: x\n---\n", encoding="utf-8")
    _write(bundle, "HUB-DD-20260728-a1b2c3.md", _accepted_fm("HUB-DD-20260728-a1b2c3"))
    result = dr.validate_decision_bundle(bundle)
    assert len(result.records) == 1


def test_missing_frontmatter_is_okf_conformance_error(bundle: Path):
    (bundle / "HUB-DD-20260728-x.md").write_text("# no frontmatter\n", encoding="utf-8")
    result = dr.validate_decision_bundle(bundle)
    codes = {(e.category, e.code) for e in result.errors}
    assert ("okf_conformance", "malformed_frontmatter") in codes


def test_malformed_yaml_is_okf_conformance_error(bundle: Path):
    (bundle / "HUB-DD-20260728-x.md").write_text("---\n: : :\nfoo\n---\nbody\n", encoding="utf-8")
    result = dr.validate_decision_bundle(bundle)
    assert any(e.category == "okf_conformance" for e in result.errors)


def test_top_level_yaml_not_mapping_is_error(bundle: Path):
    (bundle / "HUB-DD-20260728-x.md").write_text("---\n- a\n- b\n---\nbody\n", encoding="utf-8")
    result = dr.validate_decision_bundle(bundle)
    assert any(e.code == "malformed_frontmatter" for e in result.errors)


def test_missing_type_is_okf_error(bundle: Path):
    fm = "id: HUB-DD-20260728-x\ntitle: T\ndecision_state: Proposed\nstatus: draft\n"
    _write(bundle, "HUB-DD-20260728-x.md", fm)
    result = dr.validate_decision_bundle(bundle)
    assert any(e.category == "okf_conformance" and e.code == "missing_type" for e in result.errors)


def test_id_must_match_filename(bundle: Path):
    _write(bundle, "HUB-DD-20260728-zzz999.md", _accepted_fm("HUB-DD-20260728-a1b2c3"))
    result = dr.validate_decision_bundle(bundle)
    assert any(e.code == "id_filename_mismatch" for e in result.errors)


def test_duplicate_id_across_files(bundle: Path):
    _write(bundle, "HUB-DD-20260728-a1b2c3.md", _accepted_fm("HUB-DD-20260728-a1b2c3"))
    # second file whose id collides with the first but matches its own name check off
    dup = _accepted_fm("HUB-DD-20260728-a1b2c3")
    (bundle / "HUB-DD-20260728-a1b2c3-dup.md").write_text(
        f"---\n{dup}---\n\n{_VALID_BODY}", encoding="utf-8"
    )
    result = dr.validate_decision_bundle(bundle)
    assert any(e.code == "duplicate_id" for e in result.errors)


def test_invalid_status_and_decision_state(bundle: Path):
    fm = (
        "type: Decision Record\nid: HUB-DD-20260728-x\ntitle: T\n"
        "status: bogus\ndecision_state: Maybe\n"
        "generated: { by: human:me }\n"
    )
    _write(bundle, "HUB-DD-20260728-x.md", fm)
    result = dr.validate_decision_bundle(bundle)
    codes = {e.code for e in result.errors}
    assert "invalid_status" in codes
    assert "invalid_decision_state" in codes


def test_lifecycle_contradiction(bundle: Path):
    fm = (
        "type: Decision Record\nid: HUB-DD-20260728-x\ntitle: T\n"
        "status: draft\ndecision_state: Accepted\n"
        "materiality: [evidence-conflict]\n"
        "generated: { by: human:me }\n"
        "sources:\n  - { resource: https://example.com/x }\n"
    )
    _write(bundle, "HUB-DD-20260728-x.md", fm)
    result = dr.validate_decision_bundle(bundle)
    assert any(e.code == "lifecycle_contradiction" for e in result.errors)


def test_accepted_requires_materiality_sources_and_rejected_alt(bundle: Path):
    fm = (
        "type: Decision Record\nid: HUB-DD-20260728-x\ntitle: T\n"
        "status: stable\ndecision_state: Accepted\n"
        "generated: { by: human:me }\n"
    )
    _write(bundle, "HUB-DD-20260728-x.md", fm, body="# Context\nno alternatives here\n")
    codes = {e.code for e in dr.validate_decision_bundle(bundle).errors}
    assert {"missing_materiality", "missing_sources", "missing_rejected_alternative"} <= codes


def test_proposed_allows_empty_sources_as_warning(bundle: Path):
    fm = (
        "type: Decision Record\nid: HUB-DD-20260728-x\ntitle: T\n"
        "status: draft\ndecision_state: Proposed\n"
        "generated: { by: kairos-ontology-toolkit/9.9.9 }\n"
    )
    _write(bundle, "HUB-DD-20260728-x.md", fm, body="# Context\ntbd\n")
    result = dr.validate_decision_bundle(bundle)
    assert not any(e.code == "missing_sources" for e in result.errors)
    assert any(w.code == "no_sources" for w in result.warnings)


def test_missing_generated_by_is_error(bundle: Path):
    fm = (
        "type: Decision Record\nid: HUB-DD-20260728-x\ntitle: T\n"
        "status: draft\ndecision_state: Proposed\n"
    )
    _write(bundle, "HUB-DD-20260728-x.md", fm, body="# Context\ntbd\n")
    assert any(e.code == "missing_generated_by" for e in dr.validate_decision_bundle(bundle).errors)


def test_source_without_resource_is_error(bundle: Path):
    fm = (
        "type: Decision Record\nid: HUB-DD-20260728-x\ntitle: T\n"
        "status: stable\ndecision_state: Rejected\n"
        "generated: { by: human:me }\n"
        "sources:\n  - { id: bad }\n"
    )
    _write(bundle, "HUB-DD-20260728-x.md", fm)
    assert any(e.code == "invalid_source" for e in dr.validate_decision_bundle(bundle).errors)


def test_url_source_never_warns_but_missing_local_path_does(bundle: Path):
    fm = (
        "type: Decision Record\nid: HUB-DD-20260728-x\ntitle: T\n"
        "status: stable\ndecision_state: Accepted\n"
        "materiality: [persistent-consequence]\n"
        "generated: { by: human:me }\n"
        "sources:\n"
        "  - { resource: https://example.com/ok }\n"
        "  - { resource: ../model/ontologies/missing.ttl }\n"
    )
    _write(bundle, "HUB-DD-20260728-x.md", fm)
    result = dr.validate_decision_bundle(bundle)
    warn_codes = [w.code for w in result.warnings]
    assert warn_codes.count("unresolved_source") == 1


def test_local_source_path_resolves_relative_to_hub_root_not_decisions_dir(
    tmp_path: Path, bundle: Path
):
    """issue #349: sources[].resource must resolve against the hub root (the
    parent of the ``decisions/`` bundle directory), not against ``decisions/``
    itself — otherwise a citation written the same way every other hub path
    citation is written (relative to the hub root, no leading ``../``) wrongly
    warns as unresolved.
    """
    source_dir = tmp_path / "integration" / "sources" / "cargowise"
    source_dir.mkdir(parents=True)
    (source_dir / "GlbStaff.sample.yaml").write_text("a: 1\n", encoding="utf-8")

    fm = (
        "type: Decision Record\nid: HUB-DD-20260728-x\ntitle: T\n"
        "status: stable\ndecision_state: Accepted\n"
        "materiality: [evidence-conflict]\n"
        "generated: { by: human:me }\n"
        "sources:\n"
        "  - { resource: integration/sources/cargowise/GlbStaff.sample.yaml }\n"
    )
    _write(bundle, "HUB-DD-20260728-x.md", fm)
    result = dr.validate_decision_bundle(bundle)
    assert not any(w.code == "unresolved_source" for w in result.warnings)


# --- #420: nested-hub repo-root fallback for .import/ evidence ---------------


def _accepted_fm_with_sources(record_id: str, resources: list[str]) -> str:
    src_lines = "".join(f"  - {{ id: s{i}, resource: '{r}' }}\n" for i, r in enumerate(resources))
    return (
        "type: Decision Record\n"
        f"id: {record_id}\n"
        "title: T\n"
        "status: stable\n"
        "decision_state: Accepted\n"
        "materiality: [evidence-conflict]\n"
        "generated: { by: human:me }\n"
        f"sources:\n{src_lines}"
    )


@pytest.fixture()
def nested_bundle(tmp_path: Path) -> Path:
    """A decisions bundle inside a *nested* hub: ``<repo>/ontology-hub/decisions``,
    where ``<repo>`` carries the toolkit pin that ``find_managed_root`` anchors on
    (same fixture shape as tests/test_hub_utils.py::_make_pin_hub)."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.kairos]\nchannel = "stable"\n', encoding="utf-8"
    )
    hub = tmp_path / "ontology-hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    d = hub / "decisions"
    d.mkdir()
    return d


def _unresolved(result) -> list[str]:
    return [w.message for w in result.warnings if w.code == "unresolved_source"]


def test_nested_hub_import_citation_resolves_from_repo_root(nested_bundle: Path, tmp_path: Path):
    """issue #420: `.import/` evidence is a repo-root *sibling* of a nested hub,
    so a hub-root join can never reach it — the repo root must be probed."""
    evidence = tmp_path / ".import" / "businessdiscovery" / "x.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("evidence", encoding="utf-8")
    fm = _accepted_fm_with_sources(
        "HUB-DD-20260815-a1", [".import/businessdiscovery/x.md"]
    )
    _write(nested_bundle, "HUB-DD-20260815-a1.md", fm)
    assert _unresolved(dr.validate_decision_bundle(nested_bundle)) == []


def test_nested_hub_backslash_pdf_citation_resolves(nested_bundle: Path, tmp_path: Path):
    """Backslash-separated `.import\\...\\y.pdf` citations exist in the wild and
    must be normalized before joining (a raw backslash string is one opaque
    filename on POSIX); .pdf must count as a local path at all (#420)."""
    evidence = tmp_path / ".import" / "businessdiscovery" / "y.pdf"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("pdf", encoding="utf-8")
    fm = _accepted_fm_with_sources(
        "HUB-DD-20260815-a2", [r".import\businessdiscovery\y.pdf"]
    )
    _write(nested_bundle, "HUB-DD-20260815-a2.md", fm)
    assert _unresolved(dr.validate_decision_bundle(nested_bundle)) == []


def test_nested_hub_missing_import_citation_still_warns(nested_bundle: Path):
    fm = _accepted_fm_with_sources("HUB-DD-20260815-a3", [".import/gone/missing.pdf"])
    _write(nested_bundle, "HUB-DD-20260815-a3.md", fm)
    assert len(_unresolved(dr.validate_decision_bundle(nested_bundle))) == 1


def test_repo_root_never_probed_for_non_convention_paths(nested_bundle: Path, tmp_path: Path):
    """Scoping (#420): a rotted hub citation must NOT be satisfied by a
    same-named file at the repo root — only `.import/` and
    `ontology-reference-models/` first segments get the second base."""
    notes = tmp_path / "docs" / "notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("repo-level notes", encoding="utf-8")
    fm = _accepted_fm_with_sources("HUB-DD-20260815-a4", ["docs/notes.md"])
    _write(nested_bundle, "HUB-DD-20260815-a4.md", fm)
    assert len(_unresolved(dr.validate_decision_bundle(nested_bundle))) == 1


def test_standalone_hub_import_resolves_only_via_hub_root(bundle: Path, tmp_path: Path):
    """A standalone hub (no toolkit-pinned ancestor) keeps hub-root-only
    resolution: `.import/` under the hub root resolves; there is no second base."""
    evidence = tmp_path / ".import" / "a.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("evidence", encoding="utf-8")
    fm = _accepted_fm_with_sources(
        "HUB-DD-20260815-a5", [".import/a.md", ".import/missing.md"]
    )
    _write(bundle, "HUB-DD-20260815-a5.md", fm)
    warnings = _unresolved(dr.validate_decision_bundle(bundle))
    assert len(warnings) == 1
    assert ".import/missing.md" in warnings[0]


def test_binary_extension_citation_checked_case_insensitively(bundle: Path, tmp_path: Path):
    """`report.PDF` must be recognized as a local path (#420): warned while
    missing, resolved once the file exists under the hub root."""
    fm = _accepted_fm_with_sources("HUB-DD-20260815-a6", ["evidence/report.PDF"])
    _write(bundle, "HUB-DD-20260815-a6.md", fm)
    assert len(_unresolved(dr.validate_decision_bundle(bundle))) == 1
    target = tmp_path / "evidence" / "report.PDF"
    target.parent.mkdir(parents=True)
    target.write_text("pdf", encoding="utf-8")
    assert _unresolved(dr.validate_decision_bundle(bundle)) == []


def test_stale_after_warns_when_past(bundle: Path):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    fm = _accepted_fm("HUB-DD-20260728-x") + f"stale_after: {yesterday}\n"
    _write(bundle, "HUB-DD-20260728-x.md", fm)
    assert any(w.code == "stale" for w in dr.validate_decision_bundle(bundle).warnings)


def test_bom_and_crlf_frontmatter_parse(bundle: Path):
    content = f"---\n{_accepted_fm('HUB-DD-20260728-x')}---\n\n{_VALID_BODY}"
    (bundle / "HUB-DD-20260728-x.md").write_bytes(
        ("\ufeff" + content.replace("\n", "\r\n")).encode("utf-8")
    )
    result = dr.validate_decision_bundle(bundle)
    assert result.errors == []


def test_self_supersede_is_error(bundle: Path):
    fm = _accepted_fm("HUB-DD-20260728-x") + "supersedes: [HUB-DD-20260728-x]\n"
    _write(bundle, "HUB-DD-20260728-x.md", fm)
    assert any(e.code == "self_supersede" for e in dr.validate_decision_bundle(bundle).errors)


def test_supersede_requires_accepted_state(bundle: Path):
    fm = (
        "type: Decision Record\nid: HUB-DD-20260728-x\ntitle: T\n"
        "status: draft\ndecision_state: Proposed\n"
        "generated: { by: human:me }\n"
        "supersedes: [HUB-DD-20260728-y]\n"
    )
    _write(bundle, "HUB-DD-20260728-x.md", fm, body="# Context\ntbd\n")
    assert any(
        e.code == "supersede_requires_accept" for e in dr.validate_decision_bundle(bundle).errors
    )


def test_supersede_cycle_detected(bundle: Path):
    a = _accepted_fm("HUB-DD-20260728-a") + "supersedes: [HUB-DD-20260728-b]\n"
    b = _accepted_fm("HUB-DD-20260728-b") + "supersedes: [HUB-DD-20260728-a]\n"
    _write(bundle, "HUB-DD-20260728-a.md", a)
    _write(bundle, "HUB-DD-20260728-b.md", b)
    assert any(e.code == "supersede_cycle" for e in dr.validate_decision_bundle(bundle).errors)


def test_dangling_supersedes_warns(bundle: Path):
    fm = _accepted_fm("HUB-DD-20260728-x") + "supersedes: [HUB-DD-19990101-gone]\n"
    _write(bundle, "HUB-DD-20260728-x.md", fm)
    assert any(
        w.code == "dangling_supersedes" for w in dr.validate_decision_bundle(bundle).warnings
    )


def test_serialize_round_trips_and_orders_keys(tmp_path: Path):
    fm = {
        "sources": [{"resource": "https://example.com/x"}],
        "type": "Decision Record",
        "id": "HUB-DD-20260728-x",
        "title": "T",
        "status": "draft",
        "decision_state": "Proposed",
        "generated": {"by": dr.producer_actor("9.9.9"), "at": dr.rfc3339_now()},
    }
    text = dr.serialize_record(fm, "# Context\ntbd\n")
    assert text.index("type:") < text.index("sources:")  # deterministic order
    parsed, body, err = dr.split_frontmatter(text)
    assert err is None
    assert parsed["id"] == "HUB-DD-20260728-x"
    assert "Context" in body


def test_generate_decision_id_shape():
    rid = dr.generate_decision_id(date(2026, 7, 28), "a1b2c3")
    assert rid == "HUB-DD-20260728-a1b2c3"
    assert dr._ID_RE.match(rid)


def test_template_body_matches_scaffold_copy():
    """D4/#416c: `TEMPLATE_BODY`'s docstring calls it the "single source of
    truth shared by the `decision` CLI and the hub scaffold template", but
    nothing enforced that -- the scaffold `.template` file is an independent
    literal copy that could silently drift. Pin the equality so a drift there
    is caught instead of silently making the #416c lint (keyed off
    `TEMPLATE_BODY`) miss a stale scaffold copy."""
    scaffold_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "kairos_ontology"
        / "scaffold"
        / "ontology-hub"
        / "decisions"
        / "HUB-DD-template.md.template"
    )
    text = scaffold_path.read_text(encoding="utf-8")
    _, sep, body = text.partition("-->")
    assert sep, "scaffold template must contain the closing '-->' comment marker"
    assert body.strip() == dr.TEMPLATE_BODY.strip()


def test_unedited_template_body_warns_when_proposed(bundle: Path):
    fm = (
        "type: Decision Record\nid: HUB-DD-20260728-x\ntitle: T\n"
        "status: draft\ndecision_state: Proposed\n"
        "generated: { by: kairos-ontology-toolkit/9.9.9 }\n"
    )
    _write(bundle, "HUB-DD-20260728-x.md", fm, body=dr.TEMPLATE_BODY)
    result = dr.validate_decision_bundle(bundle)
    assert not any(e.code == "unedited_template_body" for e in result.errors)
    assert any(w.code == "unedited_template_body" for w in result.warnings)


def test_unedited_template_body_errors_when_accepted(bundle: Path):
    fm = _accepted_fm("HUB-DD-20260728-x")
    _write(bundle, "HUB-DD-20260728-x.md", fm, body=dr.TEMPLATE_BODY)
    result = dr.validate_decision_bundle(bundle)
    assert any(e.code == "unedited_template_body" for e in result.errors)
    assert not any(w.code == "unedited_template_body" for w in result.warnings)


def test_unedited_template_body_errors_when_superseded(bundle: Path):
    fm = (
        "type: Decision Record\nid: HUB-DD-20260728-x\ntitle: T\n"
        "status: deprecated\ndecision_state: Superseded\n"
        "generated: { by: human:me }\n"
        "sources:\n  - { resource: https://example.com/x }\n"
    )
    _write(bundle, "HUB-DD-20260728-x.md", fm, body=dr.TEMPLATE_BODY)
    result = dr.validate_decision_bundle(bundle)
    assert any(e.code == "unedited_template_body" for e in result.errors)


def test_genuine_authored_body_never_flagged_as_unedited_template(bundle: Path):
    """`_VALID_BODY` is real authored prose -- the control proving the lint
    does not fire on genuine content, even at the Accepted gate."""
    _write(bundle, "HUB-DD-20260728-a1b2c3.md", _accepted_fm("HUB-DD-20260728-a1b2c3"))
    result = dr.validate_decision_bundle(bundle)
    assert not any(e.code == "unedited_template_body" for e in result.errors)
    assert not any(w.code == "unedited_template_body" for w in result.warnings)


def test_build_index_derives_superseded_by(bundle: Path):
    a = _accepted_fm("HUB-DD-20260728-a") + "supersedes: [HUB-DD-20260728-b]\n"
    _write(bundle, "HUB-DD-20260728-a.md", a)
    old = (
        "type: Decision Record\nid: HUB-DD-20260728-b\ntitle: Old\n"
        "status: deprecated\ndecision_state: Superseded\n"
        "generated: { by: human:me }\n"
        "sources:\n  - { resource: https://example.com/x }\n"
    )
    _write(bundle, "HUB-DD-20260728-b.md", old)
    result = dr.validate_decision_bundle(bundle)
    index = dr.build_index_markdown(result.records)
    assert "HUB-DD-20260728-a" in index
    # b's row should show it is superseded by a
    b_row = [line for line in index.splitlines() if "HUB-DD-20260728-b]" in line][0]
    assert "HUB-DD-20260728-a" in b_row
