"""Repeatable real-image IO and directory benchmark protocol.

This is a manual evidence runner, not a pytest performance gate. It refuses to
create image fixtures: ``--dataset-root`` must point at an existing read-only
dataset containing real image files.

Example::

    python -m tests.perf.real_io_directory_benchmark \
        --dataset-root "H:\\VrChat\\Avatars（角色）" \
        --dataset-id vrchat-avatars \
        --dataset-version 2026-08-04-v1 \
        --sample-size 64 \
        --repeats 5 \
        --output-dir artifacts/perf/real-io-directory

The runner records cold/warm intent, but does not claim to evict the operating
system file cache. Cold therefore means "no in-process pre-read" and warm
means "one untimed pre-read before the timed repeats". Publish-machine runs
should record storage and cache conditions alongside the generated artifact.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import quantiles
from time import perf_counter_ns


IMAGE_EXTENSIONS = frozenset(
    {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp", ".avif", ".heic"}
)
PROTOCOL_VERSION = "real-image-io-directory-v1"


def _percentile(values: list[float], percent: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return quantiles(values, n=100, method="inclusive")[percent - 1]


def _summary(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "min_ms": min(values, default=0.0),
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
        "max_ms": max(values, default=0.0),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_manifest(dataset_root: Path, dataset_id: str, dataset_version: str) -> tuple[list[dict], str]:
    entries: list[dict] = []
    for path in sorted(dataset_root.rglob("*"), key=lambda item: item.relative_to(dataset_root).as_posix().casefold()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        relative = path.relative_to(dataset_root).as_posix()
        stat = path.stat()
        entries.append(
            {
                "relative_path": relative,
                "size_bytes": stat.st_size,
                "sha256": _sha256(path),
            }
        )
    manifest = {
        "manifest_version": 1,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "image_extensions": sorted(IMAGE_EXTENSIONS),
        "entries": entries,
    }
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return entries, hashlib.sha256(encoded).hexdigest()


def _fixed_sample(entries: list[dict], dataset_id: str, dataset_version: str, seed: str, sample_size: int) -> list[dict]:
    ranked = sorted(
        entries,
        key=lambda entry: hashlib.sha256(
            f"{dataset_id}\0{dataset_version}\0{seed}\0{entry['relative_path']}".encode("utf-8")
        ).hexdigest(),
    )
    return ranked[: min(sample_size, len(ranked))]


def _read_images(dataset_root: Path, sample: list[dict]) -> int:
    total_bytes = 0
    for entry in sample:
        path = dataset_root / Path(entry["relative_path"])
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                total_bytes += len(chunk)
    return total_bytes


def _scan_directories(dataset_root: Path) -> tuple[int, int]:
    file_count = 0
    image_count = 0
    pending = [dataset_root]
    while pending:
        current = pending.pop()
        with os.scandir(current) as iterator:
            for item in iterator:
                if item.is_dir(follow_symlinks=False):
                    pending.append(Path(item.path))
                elif item.is_file(follow_symlinks=False):
                    file_count += 1
                    if Path(item.name).suffix.lower() in IMAGE_EXTENSIONS:
                        image_count += 1
    return file_count, image_count


def _timed(operation, repeats: int, warmup: bool) -> tuple[list[float], list[int]]:
    if warmup:
        operation()
    durations: list[float] = []
    values: list[int] = []
    for _ in range(repeats):
        gc.collect()
        started = perf_counter_ns()
        value = operation()
        durations.append((perf_counter_ns() - started) / 1_000_000)
        values.append(value if isinstance(value, int) else 0)
    return durations, values


def _hardware_metadata() -> dict:
    uname = platform.uname()
    disk = shutil.disk_usage(Path.cwd())
    return {
        "platform": platform.platform(),
        "system": uname.system,
        "release": uname.release,
        "machine": uname.machine,
        "processor": platform.processor(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "cwd_volume_free_bytes": disk.free,
    }


def _run_scenario(dataset_root: Path, sample: list[dict], scenario: str, repeats: int) -> dict:
    warmup = scenario == "warm"
    read_durations, read_bytes = _timed(lambda: _read_images(dataset_root, sample), repeats, warmup)
    directory_durations, directory_counts = _timed(
        lambda: _scan_directories(dataset_root), repeats, warmup
    )
    return {
        "cold_warm_definition": (
            "no in-process pre-read; OS cache not evicted"
            if scenario == "cold"
            else "one untimed in-process pre-read; OS cache not controlled"
        ),
        "image_read_bytes": {"timings_ms": read_durations, "bytes_per_repeat": read_bytes, **_summary(read_durations)},
        "directory_recursive_scan": {
            "timings_ms": directory_durations,
            "file_count_per_repeat": [item[0] for item in directory_counts],
            "image_count_per_repeat": [item[1] for item in directory_counts],
            **_summary(directory_durations),
        },
    }


def _write_markdown(path: Path, payload: dict) -> None:
    lines = [
        "# Real Image IO / Directory Benchmark Protocol Result",
        "",
        "This is local trend evidence and is explicitly **not a blocking performance gate**.",
        "",
        f"- Protocol: `{payload['protocol_version']}`",
        f"- Dataset: `{payload['dataset']['id']}` / version `{payload['dataset']['version']}`",
        f"- Manifest SHA-256: `{payload['dataset']['manifest_sha256']}`",
        f"- Fixed sample: `{payload['dataset']['sample_size']}` of `{payload['dataset']['image_count']}` images",
        f"- Seed: `{payload['dataset']['sampling_seed']}`",
        f"- Repeats: `{payload['protocol']['repeats']}`",
        f"- Storage description: {payload['protocol']['storage_description']}",
        "",
        "## Results",
        "",
        "| Scenario | Operation | N | P50 ms | P95 ms | Min ms | Max ms |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for scenario, result in payload["scenarios"].items():
        for operation, summary in result.items():
            if not isinstance(summary, dict) or "p50_ms" not in summary:
                continue
            lines.append(
                f"| {scenario} | {operation} | {summary['count']} | {summary['p50_ms']:.3f} | "
                f"{summary['p95_ms']:.3f} | {summary['min_ms']:.3f} | {summary['max_ms']:.3f} |"
            )
    lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            "- The dataset is read-only; the runner never creates, modifies, or deletes image files.",
            "- Manifest hashing and sample selection happen before timing and are excluded from measured operations.",
            "- `cold` is a best-effort first-access condition. No OS cache flush is attempted or implied.",
            "- Compare results only with the same dataset ID/version, manifest hash, sample seed/size, repeat count, storage context, and hardware metadata.",
            "- Results must be reviewed as evidence; they do not fail CI or directly become release thresholds.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a real-image IO and directory trend benchmark")
    parser.add_argument("--dataset-root", type=Path, required=True, help="Existing read-only dataset root")
    parser.add_argument("--dataset-id", required=True, help="Stable human-defined dataset identifier")
    parser.add_argument("--dataset-version", required=True, help="Stable dataset version or capture label")
    parser.add_argument("--sample-size", type=int, default=64)
    parser.add_argument("--sampling-seed", default="assetsmanager-real-io-v1")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--storage-description", default="unspecified storage")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/perf/real-io-directory"))
    args = parser.parse_args()
    if args.sample_size < 1:
        parser.error("--sample-size must be positive")
    if args.repeats != 5:
        parser.error("--repeats must be exactly 5 for this protocol")
    dataset_root = args.dataset_root.resolve()
    if not dataset_root.is_dir():
        parser.error("--dataset-root must be an existing directory")

    entries, manifest_sha256 = _build_manifest(dataset_root, args.dataset_id, args.dataset_version)
    if not entries:
        parser.error("--dataset-root contains no supported real image files; no synthetic fallback is provided")
    sample = _fixed_sample(entries, args.dataset_id, args.dataset_version, args.sampling_seed, args.sample_size)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "dataset_id": args.dataset_id,
        "dataset_version": args.dataset_version,
        "manifest_sha256": manifest_sha256,
        "entries": entries,
        "fixed_sample": sample,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "generated_at": timestamp,
        "blocking_gate": False,
        "dataset": {
            "id": args.dataset_id,
            "version": args.dataset_version,
            "root": str(dataset_root),
            "image_count": len(entries),
            "manifest_sha256": manifest_sha256,
            "sample_size": len(sample),
            "sampling_seed": args.sampling_seed,
        },
        "protocol": {
            "repeats": args.repeats,
            "scenarios": ["cold", "warm"],
            "storage_description": args.storage_description,
            "cache_control": "not_available; OS file cache is not flushed",
        },
        "hardware": _hardware_metadata(),
        "scenarios": {
            scenario: _run_scenario(dataset_root, sample, scenario, args.repeats)
            for scenario in ("cold", "warm")
        },
    }
    json_path = output_dir / "real-io-directory.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path = output_dir / "real-io-directory.md"
    _write_markdown(markdown_path, payload)
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    print(f"Wrote {output_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
