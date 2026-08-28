"""Focused tests for dated audit evidence governance checks."""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).parents[2] / "scripts" / "check_audit_reports.py"
_SPEC = spec_from_file_location("check_audit_reports", _SCRIPT)
assert _SPEC and _SPEC.loader
_AUDIT = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_AUDIT)


def test_primary_report_paths_supports_existing_evidence_naming() -> None:
    indexed = [
        "docs/full-review/c10-min-import-durable-intent-recovery-evidence-2026-08-21.md",
        "docs/full-review/other-2026-08-21.md",
    ]
    assert _AUDIT.primary_report_paths(
        "c10-min-import-durable-intent-recovery-2026-08-21", indexed
    ) == [indexed[0]]


def test_index_links_are_exact_and_reject_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    review = tmp_path / "docs" / "full-review"
    review.mkdir(parents=True)
    (review / "valid.md").write_text("valid", encoding="utf-8")
    monkeypatch.setattr(_AUDIT, "ROOT", tmp_path)
    monkeypatch.setattr(_AUDIT, "REVIEW_DIR", review)
    problems: list[str] = []

    links = _AUDIT.index_links(
        "[valid](valid.md#section) [text](../outside.md) [false](invalid-valid.md)",
        problems,
    )

    assert links == {"docs/full-review/valid.md"}
    assert any("missing" in problem for problem in problems)


def test_validate_manifest_rejects_baseline_and_mode_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = tmp_path / "docs" / "full-review"
    review.mkdir(parents=True)
    report = review / "sample-evidence-2026-08-21.md"
    report.write_text("# sample\n", encoding="utf-8")
    source = tmp_path / "source.md"
    source.write_text("SRC-1\n", encoding="utf-8")
    anchor = tmp_path / "anchor.py"
    anchor.write_text("pass\n", encoding="utf-8")
    manifest = review / "audit-manifest-sample-2026-08-21.json"
    monkeypatch.setattr(_AUDIT, "ROOT", tmp_path)
    monkeypatch.setattr(_AUDIT, "REVIEW_DIR", review)

    data = {
        "schema_version": 1,
        "report_id": "sample-2026-08-21",
        "captured_at": "2026-08-21T12:00:00+00:00",
        "repository_root": str(tmp_path),
        "baseline": {
            "commit": "bad",
            "branch": "branch",
            "source_kind": "unknown",
            "status_sha256": "bad",
            "diff_sha256": "bad",
            "tracked_change_count": -1,
            "untracked_change_count": 0,
        },
        "validation": {"mode": "static_only", "tests_executed": True},
        "inputs": [{"path": "source.md", "sha256": _AUDIT.sha256(source)}],
        "indexed_reports": ["docs/full-review/sample-evidence-2026-08-21.md"],
        "findings": [
            {
                "canonical_id": "SAMPLE-1",
                "severity": "P1",
                "status": "fixed-unverified",
                "source_ids": ["SRC-1"],
                "anchors": ["anchor.py:1"],
                "surface": "surface",
                "next_action": "next",
                "dynamic_verification": "dynamic",
            }
        ],
    }
    manifest.write_text(json.dumps(data), encoding="utf-8")
    problems: list[str] = []

    _AUDIT.validate_manifest(
        manifest,
        "[sample](sample-evidence-2026-08-21.md)",
        problems,
    )

    assert any("baseline.commit" in problem for problem in problems)
    assert any("source_kind" in problem for problem in problems)
    assert any("mode/tests_executed" in problem for problem in problems)
    assert any("tracked_change_count" in problem for problem in problems)


def test_validate_relations_rejects_unknown_ids_and_cycles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_AUDIT, "ROOT", tmp_path)
    first = {
        "findings": [{"canonical_id": "A"}],
        "supersession_relations": [{"superseder": "A", "superseded": "B"}],
    }
    second = {
        "findings": [{"canonical_id": "B"}],
        "supersession_relations": [{"superseder": "B", "superseded": "A"}],
    }
    problems: list[str] = []

    _AUDIT.validate_relations(
        [(tmp_path / "a.json", first), (tmp_path / "b.json", second)],
        problems,
    )

    assert any("cycle" in problem for problem in problems)


def test_validate_relations_rejects_self_reference() -> None:
    problems: list[str] = []
    _AUDIT.validate_relations(
        [
            (
                Path("manifest.json"),
                {
                    "findings": [{"canonical_id": "A"}],
                    "supersession_relations": [
                        {"superseder": "A", "superseded": "A"}
                    ],
                },
            )
        ],
        problems,
    )
    assert any("self-reference" in problem for problem in problems)


def test_validate_execution_artifacts_checks_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_AUDIT, "ROOT", tmp_path)
    artifact = tmp_path / "stdout.log"
    artifact.write_text("ok\n", encoding="utf-8")
    problems: list[str] = []

    _AUDIT.validate_execution_artifacts(
        tmp_path / "manifest.json",
        {
            "commands": [
                {
                    "argv": ["tool"],
                    "platform": "test",
                    "fixture": "one fixture",
                    "sample_count": 1,
                    "pass_criterion": "exit_code == 0",
                    "exit_code": 0,
                    "artifacts": [
                        {"path": "stdout.log", "sha256": "0" * 64}
                    ],
                }
            ]
        },
        problems,
    )

    assert any("artifact digest drift" in problem for problem in problems)


def test_main_treats_no_manifests_as_empty_state_not_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    review = tmp_path / "docs" / "full-review"
    review.mkdir(parents=True)
    monkeypatch.setattr(_AUDIT, "ROOT", tmp_path)
    monkeypatch.setattr(_AUDIT, "REVIEW_DIR", review)
    monkeypatch.setattr(_AUDIT, "MANIFESTS", [])
    monkeypatch.setattr(_AUDIT, "INDEX", review / "00-INDEX.md")

    assert _AUDIT.main() == 0
    assert "no audit manifest registered" in capsys.readouterr().err
