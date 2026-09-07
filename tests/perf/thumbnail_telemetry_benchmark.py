"""Manual P6/P7 thumbnail telemetry artifact runner; not a pytest performance gate.

Usage:
    python -m tests.perf.thumbnail_telemetry_benchmark --items 1000 --output-dir artifacts/perf/thumbnail
    python -m tests.perf.thumbnail_telemetry_benchmark --library-root "H:\\VrChat\\Avatars（角色）"

Results are local trend evidence. They must not become machine-independent
PR timing thresholds.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from xml.etree.ElementTree import Element, ElementTree, SubElement


def _event_dict(event) -> dict:
    return {
        "name": event.name,
        "elapsed_ms": event.elapsed_ms,
        "generation": event.generation,
        "attributes": dict(event.attributes),
    }


def _write_fixture(root: Path, item_count: int) -> list[Path]:
    from PySide6.QtGui import QImage

    root.mkdir(parents=True, exist_ok=True)
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0xFF4A90E2)
    paths = []
    for index in range(item_count):
        path = root / f"thumbnail-{index:05d}.png"
        if not image.save(str(path), "PNG"):
            raise RuntimeError(f"Could not write thumbnail fixture: {path}")
        paths.append(path)
    return paths


def _real_image_paths(root: Path, limit: int) -> list[Path]:
    from AssetsManager.application.asset_filters import IMAGE_EXTS

    paths: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            paths.append(path)
            if len(paths) == limit:
                return paths
    return paths


def _wait_for(loader, completed: list[tuple[int, float]], expected: int, app) -> None:
    deadline = perf_counter() + 30
    while len(completed) < expected and perf_counter() < deadline:
        app.processEvents()
        loader._pool.waitForDone(10)
    app.processEvents()
    if len(completed) != expected:
        raise RuntimeError(f"Timed out waiting for thumbnails: got {len(completed)}, expected {expected}")


def _run_scenario(paths: list[Path], scenario: str) -> tuple[list[dict], dict, dict]:
    import PySide6
    from PySide6.QtCore import qVersion
    from PySide6.QtWidgets import QApplication

    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.panels.file_list._loader import ThumbnailLoader

    app = QApplication.instance() or QApplication([])
    visible_count = min(24, len(paths))
    prefetch_count = min(48, max(0, len(paths) - visible_count))
    requested = paths[:visible_count + prefetch_count]
    recorder = PerformanceRecorder(enabled=True, max_events=max(2_000, len(requested) * 6))
    loader = ThumbnailLoader()
    loader.set_performance_context(recorder, f"manual-{scenario}")
    ready: list[tuple[int, float]] = []
    loader.thumbnail_ready.connect(lambda row, _path, _image: ready.append((row, perf_counter())))

    if scenario == "warm":
        for row, path in enumerate(requested):
            loader.request(row, str(path), priority=0 if row < visible_count else 1)
        _wait_for(loader, ready, len(requested), app)
        ready.clear()
        recorder.clear()

    started = perf_counter()
    for row, path in enumerate(requested):
        loader.request(row, str(path), priority=0 if row < visible_count else 1)
    _wait_for(loader, ready, len(requested), app)
    completed = [
        {"row": row, "elapsed_ms": (completed_at - started) * 1000, "kind": "visible" if row < visible_count else "prefetch"}
        for row, completed_at in ready
    ]
    events = [_event_dict(event) for event in recorder.recent()]
    event_counts = Counter(event["name"] for event in events)
    cache_outcomes = Counter(
        event["attributes"].get("outcome", "unknown")
        for event in events if event["name"] == "thumbnail.cache"
    )
    visible_completion = [event["elapsed_ms"] for event in completed if event["kind"] == "visible"]
    summary = {
        "requested": len(requested),
        "visible_requested": visible_count,
        "prefetch_requested": prefetch_count,
        "ready_count": len(completed),
        "visible_ready_count": len(visible_completion),
        "first_visible_ready_ms": min(visible_completion, default=0.0),
        "last_visible_ready_ms": max(visible_completion, default=0.0),
        "event_counts": dict(event_counts),
        "cache_outcomes": dict(cache_outcomes),
        "max_queue_depth": max(
            (event["attributes"].get("queue_depth", 0) for event in events if event["name"] == "thumbnail.queue"),
            default=0,
        ),
        "max_cache_bytes": max(
            (event["attributes"].get("cache_bytes", 0) for event in events if event["name"] == "thumbnail.cache"),
            default=0,
        ),
    }
    loader.stop()
    loader._pool.waitForDone(5_000)
    return events, {"ready": completed, "summary": summary}, {"pyside6": PySide6.__version__, "qt": qVersion()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create local P6/P7 thumbnail telemetry artifacts")
    parser.add_argument("--items", type=int, choices=(1000, 10000), nargs="+", default=[1000])
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/perf/thumbnail"))
    parser.add_argument("--library-root", type=Path, help="Read-only recursive real-library image sample.")
    parser.add_argument("--storage-description", default="local filesystem")
    args = parser.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    scenarios = {}
    qt_versions = None
    if args.library_root is not None:
        library_root = args.library_root.resolve()
        if not library_root.is_dir():
            parser.error("--library-root must be an existing directory")
        paths = _real_image_paths(library_root, 72)
        if not paths:
            parser.error("--library-root contains no supported images")
        fixture = {
            "kind": "read_only_real_library",
            "recursive_image_sample_size": len(paths),
            "storage_description": args.storage_description,
        }
        scenarios_to_run = [("real_library", paths)]
    else:
        temp = tempfile.TemporaryDirectory(prefix="assetsmanager-thumbnail-perf-")
        fixture_root = Path(temp.name)
        fixture = {"kind": "synthetic", "item_counts": args.items, "entry_type": "8x8_png"}
        scenarios_to_run = []
        for item_count in args.items:
            scenarios_to_run.append((str(item_count), _write_fixture(fixture_root / f"library-{item_count}", item_count)))
    try:
        for label, paths in scenarios_to_run:
            for scenario in ("cold", "warm"):
                events, progression, qt_versions = _run_scenario(paths, scenario)
                scenarios[f"{label}-{scenario}"] = {"events": events, **progression}
    finally:
        if args.library_root is None:
            temp.cleanup()

    payload = {
        "schema_version": 1,
        "kind": "local_trend_artifact",
        "generated_at": timestamp,
        "environment": {"platform": platform.platform(), "python": sys.version.split()[0], "qt_platform": os.environ["QT_QPA_PLATFORM"], **(qt_versions or {})},
        "fixture": {**fixture, "visible_requested": 24, "prefetch_requested": 48},
        "scenarios": scenarios,
    }
    json_path = output_dir / "thumbnail-telemetry.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# P6/P7 Thumbnail Telemetry Trend Artifact",
        "",
        "This report is local trend evidence, not a machine-independent performance budget.",
        "",
        f"- Fixture: {fixture['kind']}",
    ]
    if fixture["kind"] == "read_only_real_library":
        lines.extend([
            f"- Recursive image sample: {fixture['recursive_image_sample_size']} files",
            f"- Storage: {fixture['storage_description']}",
            "- The sampled library is never modified; no cache directory or bake database is configured.",
            "",
        ])
    lines.extend([
        "| Scenario | Visible ready | First visible ms | Last visible ms | Max queue depth | Max cache bytes | Cache outcomes |",
        "|---|---:|---:|---:|---:|---:|---|",
    ])
    for scenario, result in scenarios.items():
        summary = result["summary"]
        lines.append(
            f"| {scenario} | {summary['visible_ready_count']} | {summary['first_visible_ready_ms']:.3f} | "
            f"{summary['last_visible_ready_ms']:.3f} | {summary['max_queue_depth']} | {summary['max_cache_bytes']} | "
            f"{json.dumps(summary['cache_outcomes'], sort_keys=True)} |"
        )
    markdown_path = output_dir / "thumbnail-telemetry.md"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    suite = Element("testsuite", name="thumbnail-telemetry", tests="1", failures="0", errors="0")
    case = Element("testcase", classname="performance", name="p6_p7_thumbnail_artifact")
    SubElement(case, "system-out").text = f"scenarios={len(scenarios)}"
    suite.append(case)
    junit_path = output_dir / "thumbnail-telemetry-junit.xml"
    ElementTree(suite).write(junit_path, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    print(f"Wrote {junit_path}")


if __name__ == "__main__":
    main()
