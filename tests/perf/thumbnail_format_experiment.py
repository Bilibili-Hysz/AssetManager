"""Manual thumbnail bake format experiment; not a pytest performance gate.

Usage:
    python -m tests.perf.thumbnail_format_experiment --library-root "H:\\VrChat\\Avatars（角色）"

All variants are written to a temporary directory. The source library is read
only and is never configured as a thumbnail cache.
"""
from __future__ import annotations

import argparse
import gc
import json
import platform
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter


def _images(root: Path, limit: int) -> list[Path]:
    from AssetsManager.application.asset_filters import IMAGE_EXTS

    result = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            result.append(path)
            if len(result) == limit:
                return result
    return result


def _has_transparency(image) -> bool:
    if not image.hasAlphaChannel():
        return False
    return any(image.pixelColor(x, y).alpha() < 255 for y in range(image.height()) for x in range(image.width()))


def _decode_ms(path: Path) -> float:
    from PySide6.QtGui import QImageReader

    started = perf_counter()
    reader = QImageReader(str(path))
    image = reader.read()
    if image.isNull():
        raise RuntimeError(f"Could not decode experiment variant: {path}")
    elapsed = (perf_counter() - started) * 1000
    del image
    del reader
    return elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare WebP and JPEG thumbnail bake variants")
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=24)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--quality", type=int, default=85)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/perf/thumbnail-format"))
    parser.add_argument("--storage-description", default="local filesystem")
    args = parser.parse_args()
    if args.sample_size < 1 or args.size < 1 or not 0 <= args.quality <= 100:
        parser.error("sample-size/size must be positive and quality must be 0-100")
    root = args.library_root.resolve()
    if not root.is_dir():
        parser.error("--library-root must be an existing directory")
    sources = _images(root, args.sample_size)
    if not sources:
        parser.error("no supported images found")

    from PySide6.QtCore import Qt, qVersion
    from PySide6.QtGui import QImageReader, QImageWriter
    import PySide6

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    variants = {"webp": {"encode_ms": [], "decode_ms": [], "bytes": []}, "jpeg": {"encode_ms": [], "decode_ms": [], "bytes": []}}
    opaque = 0
    transparent = 0

    with tempfile.TemporaryDirectory(prefix="assetsmanager-thumbnail-format-") as temp:
        temp_root = Path(temp)
        for index, source in enumerate(sources):
            reader = QImageReader(str(source))
            original = reader.size()
            if not original.isValid():
                continue
            reader.setScaledSize(original.scaled(args.size, args.size, Qt.AspectRatioMode.KeepAspectRatio))
            image = reader.read()
            if image.isNull():
                continue
            if _has_transparency(image):
                transparent += 1
            else:
                opaque += 1
            for name, fmt, image_to_save in (
                ("webp", b"WEBP", image),
                ("jpeg", b"JPEG", image.convertToFormat(image.Format.Format_RGB32)),
            ):
                target = temp_root / f"{index:03d}.{name}"
                started = perf_counter()
                writer = QImageWriter(str(target), fmt)
                writer.setQuality(args.quality)
                if not writer.write(image_to_save):
                    raise RuntimeError(f"Could not encode {name}: {source}")
                variants[name]["encode_ms"].append((perf_counter() - started) * 1000)
                variants[name]["decode_ms"].append(_decode_ms(target))
                variants[name]["bytes"].append(target.stat().st_size)
                del writer
                del image_to_save
            del image
            del reader
        gc.collect()

    def summary(values: list[float | int]) -> dict[str, float | int]:
        return {"count": len(values), "mean": sum(values) / len(values), "min": min(values), "max": max(values)}

    payload = {
        "schema_version": 1,
        "kind": "local_thumbnail_format_experiment",
        "generated_at": timestamp,
        "environment": {"platform": platform.platform(), "python": sys.version.split()[0], "pyside6": PySide6.__version__, "qt": qVersion()},
        "fixture": {"kind": "read_only_real_library", "sampled_images": len(sources), "opaque": opaque, "transparent": transparent, "size": args.size, "quality": args.quality, "storage_description": args.storage_description},
        "variants": {name: {metric: summary(values) for metric, values in result.items()} for name, result in variants.items()},
    }
    json_path = output_dir / "thumbnail-format-experiment.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Thumbnail Format Experiment",
        "",
        "Local trend evidence only. Source images are read-only; variants use a temporary directory.",
        "",
        f"- Sample: {len(sources)} real images from {args.storage_description}",
        f"- Scaled size: {args.size}px; quality: {args.quality}",
        f"- Opaque: {opaque}; transparent: {transparent}",
        "",
        "| Variant | Encode mean ms | Decode mean ms | Mean bytes |",
        "|---|---:|---:|---:|",
    ]
    for name, result in payload["variants"].items():
        lines.append(f"| {name} | {result['encode_ms']['mean']:.3f} | {result['decode_ms']['mean']:.3f} | {result['bytes']['mean']:.0f} |")
    markdown_path = output_dir / "thumbnail-format-experiment.md"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")


if __name__ == "__main__":
    main()
