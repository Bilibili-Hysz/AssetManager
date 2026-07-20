"""Manual directory-list telemetry artifact runner; not a pytest performance gate.

Usage:
    python -m tests.perf.directory_telemetry_benchmark --directories 100 500
    python -m tests.perf.directory_telemetry_benchmark --library-root "H:\\VrChat\\Avatars（角色）"

The output is local trend evidence. It is not a machine-independent budget.
"""
from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from statistics import quantiles
from xml.etree.ElementTree import Element, ElementTree, SubElement


def _percentile(values: list[float], percent: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return quantiles(values, n=100, method="inclusive")[percent - 1]


def _summary(events: list[dict], name: str) -> dict[str, float | int]:
    values = [event["elapsed_ms"] for event in events if event["name"] == name]
    return {
        "count": len(values),
        "min_ms": min(values, default=0.0),
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
        "p99_ms": _percentile(values, 99),
        "max_ms": max(values, default=0.0),
    }


def _event_dict(event) -> dict:
    return {
        "name": event.name,
        "elapsed_ms": event.elapsed_ms,
        "generation": event.generation,
        "attributes": dict(event.attributes),
    }


def _summary_outcomes(events: list[dict]) -> dict[str, int]:
    summaries = [event for event in events if event["name"] == "directory.summary"]
    return {
        "cache_hits": sum(event["attributes"].get("cache_hit") is True for event in summaries),
        "cache_misses": sum(event["attributes"].get("cache_hit") is False for event in summaries),
    }


def _make_fixture(root: Path, directory_count: int, items_per_directory: int) -> None:
    for index in range(directory_count):
        child = root / f"directory-{index:05d}"
        child.mkdir()
        for item in range(items_per_directory):
            suffix = ".png" if item == 0 else ".txt"
            (child / f"asset-{item:03d}{suffix}").touch()


def _run_scenario(root: Path, conn: sqlite3.Connection, scenario: str) -> list[dict]:
    from AssetsManager.application.asset_service import AssetService, DirectoryListOptions
    from AssetsManager.core.directory_cache import DirectoryCache
    from AssetsManager.core.performance import PerformanceRecorder

    recorder = PerformanceRecorder(enabled=True, max_events=10_000)
    service = AssetService(DirectoryCache(conn), recorder, session_token=f"manual-{scenario}")
    service.list_directory(
        root,
        root,
        DirectoryListOptions(scan_summaries=scenario != "summaries_off"),
    )
    return [_event_dict(event) for event in recorder.recent()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create local directory-list telemetry artifacts")
    parser.add_argument(
        "--directories", type=int, choices=(100, 500, 1000), nargs="+", default=[100, 500],
        help="Child-directory fixture sizes; defaults to the standard 100/500 matrix.",
    )
    parser.add_argument("--items-per-directory", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/perf/directory"))
    parser.add_argument(
        "--library-root", type=Path,
        help="Read-only real-library sample. Uses an in-memory cache and never writes the library.",
    )
    parser.add_argument(
        "--storage-description", default="local filesystem",
        help="Human-readable storage context retained in the artifact, such as 'external SSD'.",
    )
    parser.add_argument(
        "--parent-depth", type=int, default=0,
        help="For --library-root, list every directory at this relative depth; 0 lists only the root.",
    )
    args = parser.parse_args()
    if args.items_per_directory < 1:
        parser.error("--items-per-directory must be positive")
    if args.parent_depth < 0:
        parser.error("--parent-depth must not be negative")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    scenarios: dict[str, list[dict]] = {}

    if args.library_root is not None:
        library_root = args.library_root.resolve()
        if not library_root.is_dir():
            parser.error("--library-root must be an existing directory")
        roots = [library_root]
        for _ in range(args.parent_depth):
            roots = [child for root in roots for child in root.iterdir() if child.is_dir()]
        direct_entry_count = sum(1 for root in roots for _ in root.iterdir())
        direct_directory_count = sum(1 for root in roots for child in root.iterdir() if child.is_dir())
        fixture = {
            "kind": "read_only_real_library",
            "parent_depth": args.parent_depth,
            "sampled_parent_count": len(roots),
            "direct_entry_count": direct_entry_count,
            "direct_directory_count": direct_directory_count,
            "storage_description": args.storage_description,
        }
    else:
        fixture = {
            "kind": "synthetic",
            "directory_counts": args.directories,
            "items_per_directory": args.items_per_directory,
            "entry_type": "one_empty_png_and_empty_txt_files",
        }
        temp = tempfile.TemporaryDirectory(prefix="assetsmanager-directory-perf-")
        fixture_root = Path(temp.name)
        roots = []
        for directory_count in args.directories:
            root = fixture_root / f"library-{directory_count}"
            root.mkdir()
            _make_fixture(root, directory_count, args.items_per_directory)
            roots.append((root, str(directory_count)))
    try:
        if args.library_root is not None:
            scenario_roots = [(root, "real_library") for root in roots]
        else:
            scenario_roots = roots
        scenario_names = ("cold", "warm", "summaries_off")
        for scenario in scenario_names:
            scenario_events: dict[str, list[dict]] = {}
            for root, label in scenario_roots:
                scenario_events.setdefault(label, [])
                conn = sqlite3.connect(":memory:", check_same_thread=False)
                try:
                    from AssetsManager.core.database import _SCHEMA
                    from AssetsManager.core.db_migrations import migrate

                    conn.executescript(_SCHEMA)
                    migrate(conn)
                    if scenario == "warm":
                        _run_scenario(root, conn, "cold")
                    scenario_events[label].extend(_run_scenario(root, conn, scenario))
                finally:
                    conn.close()
            for label, events in scenario_events.items():
                scenarios[f"{label}-{scenario}"] = events
    finally:
        if args.library_root is None:
            temp.cleanup()

    payload = {
        "schema_version": 1,
        "kind": "local_trend_artifact",
        "generated_at": timestamp,
        "environment": {"platform": platform.platform(), "python": sys.version.split()[0]},
        "fixture": fixture,
        "scenarios": {
            name: {
                "events": events,
                "directory_list": _summary(events, "directory.list"),
                "directory_summary": _summary(events, "directory.summary"),
                **_summary_outcomes(events),
            }
            for name, events in scenarios.items()
        },
    }
    json_path = output_dir / "directory-telemetry.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    event_count = sum(len(events) for events in scenarios.values())
    suite = Element("testsuite", name="directory-telemetry", tests="1", failures="0", errors="0")
    case = SubElement(suite, "testcase", classname="performance", name="directory_telemetry_artifact")
    SubElement(case, "system-out").text = f"scenarios={len(scenarios)} events={event_count}"
    junit_path = output_dir / "directory-telemetry-junit.xml"
    ElementTree(suite).write(junit_path, encoding="utf-8", xml_declaration=True)

    lines = [
        "# Directory Telemetry Trend Artifact",
        "",
        "This report is local trend evidence, not a machine-independent performance budget.",
        "",
        f"- Fixture: {fixture['kind']}",
    ]
    if fixture["kind"] == "synthetic":
        lines.append(f"- Fixture sizes: {', '.join(str(count) for count in args.directories)} child directories")
        lines.append(f"- Items per directory: {args.items_per_directory}")
    else:
        lines.append(f"- Parent depth: {fixture['parent_depth']}")
        lines.append(f"- Sampled parent directories: {fixture['sampled_parent_count']}")
        lines.append(f"- Direct entries across parents: {fixture['direct_entry_count']}")
        lines.append(f"- Direct child directories across parents: {fixture['direct_directory_count']}")
        lines.append(f"- Storage: {fixture['storage_description']}")
        lines.append("- Cache: in-memory only; the sampled library is never modified.")
    lines.extend([
        "",
        "| Scenario | List P50 ms | List P95 ms | Summary count | Summary P50 ms | Hits | Misses |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for scenario, result in payload["scenarios"].items():
        listing = result["directory_list"]
        summary = result["directory_summary"]
        lines.append(
            f"| {scenario} | {listing['p50_ms']:.3f} | {listing['p95_ms']:.3f} | {summary['count']} | "
            f"{summary['p50_ms']:.3f} | {result['cache_hits']} | {result['cache_misses']} |"
        )
    markdown_path = output_dir / "directory-telemetry.md"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    print(f"Wrote {junit_path}")


if __name__ == "__main__":
    main()
