#!/usr/bin/env python3
"""Validate dated audit evidence manifests without executing their tests.

The validator proves that a manifest still names local reports, source anchors,
input bytes, and exact index links. It intentionally does not treat hand-written
test counts or historical prose as execution evidence.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
REVIEW_DIR = ROOT / "docs" / "full-review"
INDEX = REVIEW_DIR / "00-INDEX.md"
MANIFESTS = sorted(REVIEW_DIR.glob("audit-manifest-*.json"))
ALLOWED_SEVERITIES = {"P1", "P2", "P3"}
ALLOWED_STATUSES = {
    "confirmed",
    "conditional",
    "superseded",
    "fixed-unverified",
    "verified-fixed",
}
ALLOWED_SOURCE_KINDS = {"clean_checkout", "dirty_worktree"}
ANCHOR_RE = re.compile(r"^(?P<path>.+):(?P<line>[1-9][0-9]*)$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DATE_RE = re.compile(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}")
INDEX_LINK_RE = re.compile(
    r"(?<!!)\[[^\]]+\]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.relative_to(ROOT)}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)}: top-level value must be an object")
    return value


def require(mapping: dict[str, Any], key: str, manifest: Path, problems: list[str]) -> Any:
    if key not in mapping:
        problems.append(f"{manifest.relative_to(ROOT)}: missing {key!r}")
        return None
    return mapping[key]


def resolve_local_path(value: str, *, base: Path) -> Path | None:
    """Resolve a local path while rejecting absolute paths and traversal."""
    candidate = Path(value)
    if candidate.is_absolute() or candidate.drive:
        return None
    resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return resolved


def index_links(index_text: str, problems: list[str] | None = None) -> set[str]:
    """Return exact repository-relative targets from Markdown links in the index."""
    targets: set[str] = set()
    for raw_target in INDEX_LINK_RE.findall(index_text):
        target = raw_target.split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        resolved = resolve_local_path(target, base=REVIEW_DIR)
        if resolved is None:
            if problems is not None:
                problems.append(f"index link escapes repository: {raw_target}")
            continue
        if not resolved.is_file():
            if problems is not None:
                problems.append(f"index link target missing: {raw_target}")
            continue
        targets.add(resolved.relative_to(ROOT).as_posix())
    return targets


def date_from_name(name: str) -> str | None:
    match = DATE_RE.search(name)
    return match.group(0) if match else None


def validate_baseline(manifest: Path, baseline: Any, problems: list[str]) -> None:
    if not isinstance(baseline, dict):
        problems.append(f"{manifest.relative_to(ROOT)}: baseline must be an object")
        return
    for key in (
        "commit",
        "branch",
        "source_kind",
        "status_sha256",
        "diff_sha256",
        "tracked_change_count",
        "untracked_change_count",
    ):
        require(baseline, key, manifest, problems)
    commit = baseline.get("commit")
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        problems.append(
            f"{manifest.relative_to(ROOT)}: baseline.commit must be 40 lowercase hex characters"
        )
    branch = baseline.get("branch")
    if not isinstance(branch, str) or not branch:
        problems.append(f"{manifest.relative_to(ROOT)}: baseline.branch must be non-empty")
    if baseline.get("source_kind") not in ALLOWED_SOURCE_KINDS:
        problems.append(f"{manifest.relative_to(ROOT)}: invalid baseline.source_kind")
    for key in ("status_sha256", "diff_sha256"):
        value = baseline.get(key)
        if not isinstance(value, str) or not HASH_RE.fullmatch(value):
            problems.append(
                f"{manifest.relative_to(ROOT)}: baseline.{key} must be 64 lowercase hex characters"
            )
    for key in ("tracked_change_count", "untracked_change_count"):
        value = baseline.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            problems.append(
                f"{manifest.relative_to(ROOT)}: baseline.{key} must be a non-negative integer"
            )


def primary_report_paths(report_id: str, indexed_reports: list[str]) -> list[str]:
    candidates = {f"{report_id}.md", f"{report_id}-evidence.md"}
    match = re.search(r"(?P<date>20[0-9]{2}-[0-9]{2}-[0-9]{2})$", report_id)
    if match:
        stem = report_id[:match.start()].rstrip("-")
        candidates.add(f"{stem}-evidence-{match.group('date')}.md")
    return [path for path in indexed_reports if Path(path).name in candidates]


def valid_anchor(anchor: Any, manifest: Path, problems: list[str]) -> None:
    if not isinstance(anchor, str):
        problems.append(f"{manifest.relative_to(ROOT)}: anchor must be a string")
        return
    match = ANCHOR_RE.fullmatch(anchor)
    if not match:
        problems.append(f"{manifest.relative_to(ROOT)}: malformed anchor {anchor!r}")
        return
    source = resolve_local_path(match.group("path"), base=ROOT)
    if source is None or not source.is_file():
        problems.append(f"{manifest.relative_to(ROOT)}: anchor file missing: {anchor}")
        return
    line = int(match.group("line"))
    with source.open(encoding="utf-8") as handle:
        line_count = sum(1 for _ in handle)
    if line > line_count:
        problems.append(f"{manifest.relative_to(ROOT)}: anchor line out of range: {anchor}")


def validate_artifact_entry(
    manifest: Path, artifact: Any, label: str, problems: list[str]
) -> None:
    if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str) or not isinstance(artifact.get("sha256"), str):
        problems.append(f"{manifest.relative_to(ROOT)}: invalid {label} artifact entry")
        return
    path = resolve_local_path(artifact["path"], base=ROOT)
    if path is None or not path.is_file():
        problems.append(f"{manifest.relative_to(ROOT)}: {label} artifact missing: {artifact['path']}")
    elif not HASH_RE.fullmatch(artifact["sha256"]):
        problems.append(f"{manifest.relative_to(ROOT)}: invalid {label} artifact digest: {artifact['path']}")
    elif sha256(path) != artifact["sha256"]:
        problems.append(f"{manifest.relative_to(ROOT)}: {label} artifact digest drift: {artifact['path']}")


def validate_execution_artifacts(
    manifest: Path, validation: Any, problems: list[str]
) -> None:
    """Validate optional command artifact references used by newer manifests."""
    if not isinstance(validation, dict) or "commands" not in validation:
        return
    commands = validation["commands"]
    if not isinstance(commands, list) or not commands:
        problems.append(f"{manifest.relative_to(ROOT)}: validation.commands must be a non-empty list")
        return
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            problems.append(f"{manifest.relative_to(ROOT)}: command {index} must be an object")
            continue
        for key in ("argv", "platform", "fixture", "sample_count", "pass_criterion", "exit_code", "artifacts"):
            if key not in command:
                problems.append(f"{manifest.relative_to(ROOT)}: command {index} missing {key!r}")
        if not isinstance(command.get("argv"), list) or not command["argv"]:
            problems.append(f"{manifest.relative_to(ROOT)}: command {index}.argv must be non-empty")
        if isinstance(command.get("sample_count"), bool) or not isinstance(command.get("sample_count"), int) or command["sample_count"] < 1:
            problems.append(f"{manifest.relative_to(ROOT)}: command {index}.sample_count must be positive")
        if not isinstance(command.get("exit_code"), int) or isinstance(command.get("exit_code"), bool):
            problems.append(f"{manifest.relative_to(ROOT)}: command {index}.exit_code must be an integer")
        artifacts = command.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            problems.append(f"{manifest.relative_to(ROOT)}: command {index}.artifacts must be non-empty")
            continue
        for artifact_index, artifact in enumerate(artifacts):
            validate_artifact_entry(
                manifest,
                artifact,
                f"command {index} artifact {artifact_index}",
                problems,
            )


def validate_manifest(manifest: Path, index_text: str, problems: list[str]) -> dict[str, Any]:
    data = load_json(manifest)
    for key in (
        "schema_version",
        "report_id",
        "captured_at",
        "repository_root",
        "baseline",
        "validation",
        "inputs",
        "indexed_reports",
        "findings",
    ):
        require(data, key, manifest, problems)

    schema_version = data.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 1:
        problems.append(f"{manifest.relative_to(ROOT)}: schema_version must be a positive integer")

    report_id = data.get("report_id")
    if not isinstance(report_id, str) or not report_id:
        problems.append(f"{manifest.relative_to(ROOT)}: report_id must be non-empty")

    captured_date: str | None = None
    captured_at = data.get("captured_at")
    if not isinstance(captured_at, str):
        problems.append(f"{manifest.relative_to(ROOT)}: captured_at must be an ISO-8601 string")
    else:
        try:
            parsed = datetime.fromisoformat(captured_at)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timezone required")
            captured_date = parsed.date().isoformat()
        except ValueError:
            problems.append(f"{manifest.relative_to(ROOT)}: captured_at must include a timezone")

    repository_root = data.get("repository_root")
    if not isinstance(repository_root, str) or not repository_root:
        problems.append(f"{manifest.relative_to(ROOT)}: repository_root must be non-empty")

    validate_baseline(manifest, data.get("baseline"), problems)
    filename_date = date_from_name(manifest.name)
    report_date = date_from_name(report_id) if isinstance(report_id, str) else None
    if filename_date and captured_date and filename_date != captured_date:
        problems.append(f"{manifest.relative_to(ROOT)}: filename date disagrees with captured_at")
    if report_date and captured_date and report_date != captured_date:
        problems.append(f"{manifest.relative_to(ROOT)}: report_id date disagrees with captured_at")

    validation = data.get("validation")
    if not isinstance(validation, dict) or validation.get("mode") not in {"static_only", "dynamic"}:
        problems.append(
            f"{manifest.relative_to(ROOT)}: validation.mode must be static_only or dynamic"
        )
    elif not isinstance(validation.get("tests_executed"), bool):
        problems.append(
            f"{manifest.relative_to(ROOT)}: validation.tests_executed must be boolean"
        )
    elif validation["tests_executed"] != (validation["mode"] == "dynamic"):
        problems.append(f"{manifest.relative_to(ROOT)}: validation.mode/tests_executed disagree")
    validate_execution_artifacts(manifest, validation, problems)
    provenance_artifact = validation.get("provenance_artifact") if isinstance(validation, dict) else None
    if provenance_artifact is not None:
        validate_artifact_entry(manifest, provenance_artifact, "provenance", problems)

    inputs = data.get("inputs")
    input_texts: list[str] = []
    if not isinstance(inputs, list) or not inputs:
        problems.append(f"{manifest.relative_to(ROOT)}: inputs must be a non-empty list")
    else:
        for item in inputs:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not isinstance(item.get("sha256"), str)
            ):
                problems.append(f"{manifest.relative_to(ROOT)}: invalid input entry")
                continue
            path = resolve_local_path(item["path"], base=ROOT)
            if path is None or not path.is_file():
                problems.append(f"{manifest.relative_to(ROOT)}: input missing: {item['path']}")
                continue
            if not HASH_RE.fullmatch(item["sha256"]):
                problems.append(f"{manifest.relative_to(ROOT)}: invalid input digest: {item['path']}")
            elif sha256(path) != item["sha256"]:
                problems.append(f"{manifest.relative_to(ROOT)}: input digest drift: {item['path']}")
            input_texts.append(path.read_text(encoding="utf-8"))

    parsed_links = index_links(index_text, problems)
    indexed = data.get("indexed_reports")
    if not isinstance(indexed, list) or not indexed:
        problems.append(f"{manifest.relative_to(ROOT)}: indexed_reports must be a non-empty list")
    else:
        for rel_path in indexed:
            if not isinstance(rel_path, str):
                problems.append(f"{manifest.relative_to(ROOT)}: indexed report path must be a string")
                continue
            path = resolve_local_path(rel_path, base=ROOT)
            if path is None or not path.is_file():
                problems.append(f"{manifest.relative_to(ROOT)}: indexed report missing: {rel_path}")
            elif path.relative_to(ROOT).as_posix() not in parsed_links:
                problems.append(f"{manifest.relative_to(ROOT)}: report absent from index: {rel_path}")
        if isinstance(report_id, str):
            primary = primary_report_paths(report_id, indexed)
            if len(primary) != 1:
                problems.append(
                    f"{manifest.relative_to(ROOT)}: expected one indexed primary report for "
                    f"{report_id}, found {len(primary)}"
                )

    findings = data.get("findings")
    if not isinstance(findings, list) or not findings:
        problems.append(f"{manifest.relative_to(ROOT)}: findings must be a non-empty list")
        return data
    seen_ids: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            problems.append(f"{manifest.relative_to(ROOT)}: finding must be an object")
            continue
        canonical_id = finding.get("canonical_id")
        if not isinstance(canonical_id, str) or not canonical_id:
            problems.append(f"{manifest.relative_to(ROOT)}: finding canonical_id is required")
        elif canonical_id in seen_ids:
            problems.append(f"{manifest.relative_to(ROOT)}: duplicate canonical_id {canonical_id}")
        else:
            seen_ids.add(canonical_id)
        if finding.get("severity") not in ALLOWED_SEVERITIES:
            problems.append(f"{manifest.relative_to(ROOT)}: invalid severity for {canonical_id}")
        if finding.get("status") not in ALLOWED_STATUSES:
            problems.append(f"{manifest.relative_to(ROOT)}: invalid status for {canonical_id}")
        source_ids = finding.get("source_ids")
        if not isinstance(source_ids, list) or not all(
            isinstance(item, str) and item for item in source_ids
        ):
            problems.append(f"{manifest.relative_to(ROOT)}: source_ids required for {canonical_id}")
        else:
            for source_id in source_ids:
                if not any(source_id in text for text in input_texts):
                    problems.append(
                        f"{manifest.relative_to(ROOT)}: source ID absent from inputs: {source_id}"
                    )
        anchors = finding.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            problems.append(f"{manifest.relative_to(ROOT)}: anchors required for {canonical_id}")
        else:
            for anchor in anchors:
                valid_anchor(anchor, manifest, problems)
        for key in ("surface", "next_action", "dynamic_verification"):
            if not isinstance(finding.get(key), str) or not finding[key]:
                problems.append(f"{manifest.relative_to(ROOT)}: {key} required for {canonical_id}")
    return data


def validate_relations(
    manifests: list[tuple[Path, dict[str, Any]]], problems: list[str]
) -> None:
    known_ids = {
        finding.get("canonical_id")
        for _, data in manifests
        for finding in data.get("findings", [])
        if isinstance(finding, dict) and isinstance(finding.get("canonical_id"), str)
    }
    graph: dict[str, set[str]] = {}
    for manifest, data in manifests:
        relations = data.get("supersession_relations", [])
        if relations is None:
            continue
        if not isinstance(relations, list):
            problems.append(f"{manifest.relative_to(ROOT)}: supersession_relations must be a list")
            continue
        for relation in relations:
            if not isinstance(relation, dict):
                problems.append(f"{manifest.relative_to(ROOT)}: supersession relation must be an object")
                continue
            source = relation.get("superseder")
            target = relation.get("superseded")
            if not isinstance(source, str) or not isinstance(target, str):
                problems.append(
                    f"{manifest.relative_to(ROOT)}: supersession relation requires superseder/superseded"
                )
                continue
            try:
                manifest_label = str(manifest.relative_to(ROOT))
            except ValueError:
                manifest_label = str(manifest)
            if source == target:
                problems.append(f"{manifest_label}: supersession relation self-reference: {source}")
            for item in (source, target):
                if item not in known_ids:
                    problems.append(f"{manifest_label}: supersession ID absent from findings: {item}")
            graph.setdefault(source, set()).add(target)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            problems.append(f"supersession relation cycle detected at {node}")
            return
        if node in visited:
            return
        visiting.add(node)
        for child in graph.get(node, ()):
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def expected_indexed_files() -> set[str]:
    paths: set[str] = set()
    for path in REVIEW_DIR.iterdir():
        if not path.is_file():
            continue
        if path.name.startswith("audit-manifest-") and path.suffix == ".json":
            paths.add(path.relative_to(ROOT).as_posix())
        elif path.suffix == ".md" and DATE_RE.search(path.name):
            paths.add(path.relative_to(ROOT).as_posix())
    return paths


def main() -> int:
    if not MANIFESTS:
        # Empty state, not a violation: this gate guards the integrity of
        # manifests that exist. When a dated-evidence batch registers
        # manifests, every rule below applies again in full.
        print("no audit manifest registered; evidence gate has nothing to validate", file=sys.stderr)
        return 0
    index_text = INDEX.read_text(encoding="utf-8") if INDEX.is_file() else ""
    problems: list[str] = []
    parsed_links = index_links(index_text, problems)
    for target in sorted(expected_indexed_files() - parsed_links):
        problems.append(f"dated evidence file absent from index: {target}")

    manifest_data: list[tuple[Path, dict[str, Any]]] = []
    for manifest in MANIFESTS:
        try:
            manifest_data.append((manifest, validate_manifest(manifest, index_text, problems)))
        except ValueError as exc:
            problems.append(str(exc))
    validate_relations(manifest_data, problems)

    if problems:
        print("audit evidence validation failed:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"audit evidence manifests are valid ({len(MANIFESTS)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
