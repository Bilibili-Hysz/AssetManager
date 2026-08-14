"""Manual grid telemetry artifact runner; not a pytest performance gate.

Usage:
    python -m tests.perf.grid_telemetry_benchmark --items 1000 --output-dir artifacts/perf/grid
    python -m tests.perf.grid_telemetry_benchmark --library-root "H:\\VrChat\\Avatars（角色）" --parent-depth 1

The produced measurements are local trend evidence. They are not universal
frame-budget thresholds and must not be used as ordinary PR pass/fail checks.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
from collections import Counter
from time import perf_counter
from xml.etree.ElementTree import Element, ElementTree, SubElement
from datetime import UTC, datetime
from pathlib import Path
from statistics import quantiles


def _percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return quantiles(values, n=100, method="inclusive")[int(percent) - 1]


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


def _invalidation_summary(events: list[dict]) -> dict[str, int]:
    return dict(Counter(
        event["attributes"].get("reason", "unknown")
        for event in events if event["name"] == "grid.invalidation"
    ))


def _attribute_summary(events: list[dict], name: str, attribute: str) -> dict[str, float | int]:
    values = [event["attributes"].get(attribute, 0) for event in events if event["name"] == name]
    numeric_values = [float(value) for value in values if isinstance(value, (int, float))]
    return {
        "count": len(numeric_values),
        "p50": _percentile(numeric_values, 50),
        "p95": _percentile(numeric_values, 95),
        "max": max(numeric_values, default=0.0),
    }


def _texture_cache_summary(events: list[dict]) -> dict[str, float | int]:
    values = [event["attributes"].get("texture_cache_bytes", 0) for event in events if event["name"] == "grid.frame"]
    numeric_values = [float(value) for value in values if isinstance(value, (int, float))]
    return {"max_bytes": max(numeric_values, default=0.0)}


def _event_dict(event) -> dict:
    return {
        "name": event.name,
        "elapsed_ms": event.elapsed_ms,
        "generation": event.generation,
        "attributes": dict(event.attributes),
    }


def _preview_source(directory: Path) -> Path | None:
    """Match the Grid's direct-child folder preview lookup without recursion."""
    from AssetsManager.application.asset_filters import IMAGE_EXTS

    try:
        for index, entry in enumerate(directory.iterdir()):
            if index > 500:
                break
            if entry.is_file() and entry.suffix.lower() in IMAGE_EXTS:
                return entry
    except OSError:
        pass
    return None


def _run_scenario(
    root: Path, item_count: int, scenario: str, *, load_previews: bool = False
) -> tuple[list[dict], dict[str, str], int]:
    import PySide6
    from PySide6.QtCore import qVersion
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import QApplication

    from AssetsManager.core.performance import PerformanceRecorder
    from AssetsManager.panels.file_list._grid_layout import GridLayout
    from AssetsManager.panels.file_list._loader import ThumbnailLoader
    from AssetsManager.panels.file_list._grid_widget import FileListGridWidget
    from AssetsManager.panels.file_list._model import FileSystemModel

    app = QApplication.instance() or QApplication([])
    recorder = PerformanceRecorder(enabled=True, max_events=2_000)
    model = FileSystemModel()
    model.set_performance_context(recorder, f"manual-{scenario}")
    model.set_directory(str(root))
    model._wait_for_scan()
    baseline_reset_events = tuple(
        event for event in recorder.recent() if event.name == "model.reset"
    )
    widget = FileListGridWidget()
    widget.set_model(model)
    widget.set_layout_ref(GridLayout())
    widget.resize(1200, 720)
    widget.update_layout(model.rowCount(), widget.width())
    widget.set_performance_context(recorder, f"manual-{scenario}", model.scan_generation)
    widget.show()
    app.processEvents()
    preview_requests: list[tuple[int, Path, str]] = []
    layout = widget._layout
    if load_previews and layout is not None:
        for row in layout.visible_rows(widget._scroll_y, widget.height()):
            entry = model.entry_at(row)
            if entry is None or not entry.is_dir():
                continue
            source = _preview_source(Path(entry.path))
            if source is not None:
                preview_requests.append((row, source, entry.path))
        if preview_requests:
            loader = ThumbnailLoader()
            ready: list[int] = []
            pending_rows: set[int] = set()
            if scenario == "delivery":
                recorder.clear()
                batch_timer = QTimer()
                batch_timer.setSingleShot(True)
                batch_timer.setInterval(50)

                def flush_thumbnail_batch() -> None:
                    if not pending_rows:
                        return
                    rows = sorted(pending_rows)
                    pending_rows.clear()
                    widget.record_thumbnail_batch(len(rows))
                    widget.commit_thumbnail_rows(rows)

                batch_timer.timeout.connect(flush_thumbnail_batch)

            def on_thumbnail_ready(row: int, item_path: str, image) -> None:
                if image is None or image.isNull():
                    return
                started = widget.start_thumbnail_delivery_measurement()
                pixmap = QPixmap.fromImage(image)
                widget.record_thumbnail_pixmap(started)
                index = model.index(row, 0)
                if not index.isValid() or model.path_at(row) != item_path:
                    return
                entry = model.entry_at(row)
                if entry is None:
                    return
                model._raw_pixmaps[entry.path] = pixmap
                model.setData(index, QIcon(pixmap), Qt.ItemDataRole.DecorationRole)
                ready.append(row)
                if scenario == "delivery":
                    pending_rows.add(row)
                    batch_timer.start()

            loader.thumbnail_ready.connect(on_thumbnail_ready)
            for row, source, item_path in preview_requests:
                loader.request(row, str(source), item_path=item_path)
            deadline = perf_counter() + 30
            while (len(ready) < len(preview_requests) or pending_rows) and perf_counter() < deadline:
                app.processEvents()
                loader._pool.waitForDone(10)
            loader.stop()
            loader._pool.waitForDone(5_000)
            if len(ready) != len(preview_requests):
                raise RuntimeError(f"Timed out waiting for previews: got {len(ready)}, expected {len(preview_requests)}")
            if scenario == "delivery":
                widget.repaint()
                events = [
                    *(_event_dict(event) for event in baseline_reset_events),
                    *(_event_dict(event) for event in recorder.recent()),
                ]
                widget.deleteLater()
                model.shutdown()
                app.processEvents()
                return events, {"pyside6": PySide6.__version__, "qt": qVersion()}, len(preview_requests)

    if scenario in {"warm", "resize", "scroll_zoom"}:
        widget.repaint()
        widget.repaint()
    # Exclude model/layout/initial show work and warm-up paints from the sample.
    recorder.clear()
    if scenario == "cold":
        widget.invalidate_textures()
    elif scenario == "resize":
        widget.update_layout(model.rowCount(), 1000)
    elif scenario == "scroll_zoom":
        scrollbar = widget._scrollbar
        for target_size in (128, 64):
            start_size = widget._thumb_size
            widget.begin_zoom(target_size)
            for size in (
                start_size + (target_size - start_size) // 3,
                start_size + 2 * (target_size - start_size) // 3,
                target_size,
            ):
                widget.set_zoom_thumb_size(size)
                scrollbar.setValue(min(scrollbar.maximum(), scrollbar.value() + widget.height() // 2))
                widget.repaint()
                app.processEvents()
            widget.set_thumb_size(target_size)
            widget.update_layout(model.rowCount(), widget.width())
            widget.finish_zoom()
            widget.invalidate_textures()
            for _ in range(3):
                widget.repaint()
                app.processEvents()
        scrollbar.setValue(max(0, scrollbar.maximum() - widget.height()))
    widget.repaint()

    # Exercise the real entrance/animation callback without forcing a threshold.
    widget._animator._entrance_queue = list(range(min(item_count, 24)))
    for _ in range(4):
        widget._animator._anim_tick()
        app.processEvents()

    events = [
        *(_event_dict(event) for event in baseline_reset_events),
        *(_event_dict(event) for event in recorder.recent()),
    ]
    widget.deleteLater()
    model.shutdown()
    app.processEvents()
    return events, {"pyside6": PySide6.__version__, "qt": qVersion()}, len(preview_requests)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create local grid telemetry trend artifacts")
    parser.add_argument(
        "--items", type=int, choices=(1000, 10000, 50000), nargs="+", default=[1000, 10000],
        help="Fixture sizes to include; 50k is available for explicit acceptance runs.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/perf/grid"))
    parser.add_argument("--library-root", type=Path, help="Read-only real-library grid sample.")
    parser.add_argument("--parent-depth", type=int, default=0)
    parser.add_argument("--storage-description", default="local filesystem")
    args = parser.parse_args()
    if args.parent_depth < 0:
        parser.error("--parent-depth must not be negative")

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
        roots = [library_root]
        for _ in range(args.parent_depth):
            roots = [child for root in roots for child in root.iterdir() if child.is_dir()]
        fixture = {
            "kind": "read_only_real_library", "parent_depth": args.parent_depth,
            "sampled_parent_count": len(roots), "storage_description": args.storage_description,
        }
        scenario_roots = roots
    else:
        temp = tempfile.TemporaryDirectory(prefix="assetsmanager-grid-perf-")
        fixture_root = Path(temp.name)
        fixture = {"kind": "synthetic", "item_counts": args.items, "entry_type": "empty_txt", "thumbnail_size": 96}
        scenario_roots = []
        for item_count in args.items:
            root = fixture_root / f"library-{item_count}"
            root.mkdir()
            for index in range(item_count):
                (root / f"asset-{index:05d}.txt").touch()
            scenario_roots.append((str(item_count), root, item_count))
    try:
        if args.library_root is not None:
            for scenario in ("cold", "warm", "scroll_zoom"):
                events = []
                preview_requests = 0
                for root in scenario_roots:
                    root_events, qt_versions, request_count = _run_scenario(root, 24, scenario)
                    events.extend(root_events)
                    preview_requests += request_count
                scenarios[f"real_library-{scenario}"] = events
                preview_events = []
                preview_requests = 0
                for root in scenario_roots:
                    root_events, qt_versions, request_count = _run_scenario(root, 24, scenario, load_previews=True)
                    preview_events.extend(root_events)
                    preview_requests += request_count
                scenarios[f"real_library-preview-{scenario}"] = preview_events
                fixture["direct_preview_requests"] = preview_requests
            resize_events = []
            for root in scenario_roots:
                root_events, qt_versions, _ = _run_scenario(root, 24, "resize")
                resize_events.extend(root_events)
            scenarios["real_library-resize"] = resize_events
            delivery_events = []
            preview_requests = 0
            for root in scenario_roots:
                root_events, qt_versions, request_count = _run_scenario(root, 24, "delivery", load_previews=True)
                delivery_events.extend(root_events)
                preview_requests += request_count
            scenarios["real_library-preview-delivery"] = delivery_events
            fixture["direct_preview_delivery_requests"] = preview_requests
        else:
            for label, root, item_count in scenario_roots:
                for scenario in ("cold", "warm", "scroll_zoom"):
                    events, qt_versions, _ = _run_scenario(root, item_count, scenario)
                    scenarios[f"{label}-{scenario}"] = events
    finally:
        if args.library_root is None:
            temp.cleanup()

    payload = {
        "schema_version": 1,
        "kind": "local_trend_artifact",
        "generated_at": timestamp,
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "qt_platform": os.environ["QT_QPA_PLATFORM"],
            **(qt_versions or {}),
        },
        "fixture": fixture,
        "scenarios": {
            name: {
                "events": events,
                "grid_frame": _summary(events, "grid.frame"),
                "model_reset": _summary(events, "model.reset"),
                "animation_tick": _summary(events, "grid.animation_tick"),
                "frame_request": _summary(events, "grid.frame_request"),
                "invalidation_reasons": _invalidation_summary(events),
                "thumbnail_batch_count": _attribute_summary(events, "grid.thumbnail_batch", "count"),
                "frame_texture_build_count": _attribute_summary(events, "grid.frame", "texture_build_count"),
                "frame_deferred_texture_count": _attribute_summary(events, "grid.frame", "deferred_texture_count"),
                "frame_request_coalescing": _attribute_summary(
                    events, "grid.frame_request", "coalesced_request_count"
                ),
                "texture_cache": _texture_cache_summary(events),
                "texture_evictions": sum(event["name"] == "grid.texture_eviction" for event in events),
            }
            for name, events in scenarios.items()
        },
    }
    json_path = output_dir / "grid-telemetry.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    event_count = sum(len(result["events"]) for result in payload["scenarios"].values())
    suite = Element("testsuite", name="grid-telemetry", tests="1", failures="0", errors="0")
    case = Element("testcase", classname="performance", name="grid_telemetry_artifact")
    SubElement(case, "system-out").text = f"scenarios={len(payload['scenarios'])} events={event_count}"
    suite.append(case)
    junit_path = output_dir / "grid-telemetry-junit.xml"
    ElementTree(suite).write(junit_path, encoding="utf-8", xml_declaration=True)

    lines = [
        "# Grid Telemetry Trend Artifact",
        "",
        "This report is local trend evidence, not a machine-independent performance budget.",
        "",
        f"- Fixture: {fixture['kind']}",
        f"- Qt platform: `{os.environ['QT_QPA_PLATFORM']}`",
    ]
    if fixture["kind"] == "synthetic":
        lines.append(f"- Fixture sizes: {', '.join(str(item_count) for item_count in args.items)} deterministic entries")
    else:
        lines.extend([
            f"- Parent depth: {fixture['parent_depth']}",
            f"- Sampled parent directories: {fixture['sampled_parent_count']}",
            f"- Storage: {fixture['storage_description']}",
            "- The sampled library is never modified.",
        ])
    lines.extend([
        "",
        "| Scenario | Event | Count | Min ms | P50 ms | P95 ms | P99 ms | Max ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for scenario, result in payload["scenarios"].items():
        for event_name, summary in (("model.reset", result["model_reset"]), ("grid.frame", result["grid_frame"]), ("grid.texture", _summary(result["events"], "grid.texture")), ("grid.animation_tick", result["animation_tick"]), ("grid.frame_request", result["frame_request"])):
            lines.append(
                f"| {scenario} | {event_name} | {summary['count']} | {summary['min_ms']:.3f} | "
                f"{summary['p50_ms']:.3f} | {summary['p95_ms']:.3f} | {summary['p99_ms']:.3f} | {summary['max_ms']:.3f} |"
            )
        lines.append(f"| {scenario} | grid.invalidation reasons | {json.dumps(result['invalidation_reasons'], sort_keys=True)} | | | | | |")
        batch = result["thumbnail_batch_count"]
        texture_builds = result["frame_texture_build_count"]
        deferred_textures = result["frame_deferred_texture_count"]
        frame_requests = result["frame_request_coalescing"]
        texture_cache = result["texture_cache"]
        lines.append(
            f"| {scenario} | thumbnail batch size | {batch['count']} | {batch['p50']:.0f} | "
            f"{batch['p95']:.0f} | | {batch['max']:.0f} |"
        )
        lines.append(
            f"| {scenario} | frame texture build count | {texture_builds['count']} | {texture_builds['p50']:.0f} | "
            f"{texture_builds['p95']:.0f} | | {texture_builds['max']:.0f} |"
        )
        lines.append(
            f"| {scenario} | frame deferred texture count | {deferred_textures['count']} | {deferred_textures['p50']:.0f} | "
            f"{deferred_textures['p95']:.0f} | | {deferred_textures['max']:.0f} |"
        )
        lines.append(
            f"| {scenario} | coalesced frame requests | {frame_requests['count']} | {frame_requests['p50']:.0f} | "
            f"{frame_requests['p95']:.0f} | | {frame_requests['max']:.0f} |"
        )
        lines.append(
            f"| {scenario} | texture cache | {result['texture_evictions']} evictions | | | | | "
            f"{texture_cache['max_bytes'] / (1024 * 1024):.1f} MiB max |"
        )
    markdown_path = output_dir / "grid-telemetry.md"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    print(f"Wrote {junit_path}")


if __name__ == "__main__":
    main()
