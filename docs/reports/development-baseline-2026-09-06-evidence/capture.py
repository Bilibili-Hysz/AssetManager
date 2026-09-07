"""Capture isolated source copies so pytest cannot share RuntimeData cleanup."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import uuid


def main() -> None:
    evidence = Path(__file__).resolve().parent
    root = evidence.parents[2]
    run_id = uuid.uuid4().hex[:8]
    snapshot_root = root / ".pytest-tmp-lead-snapshots" / run_id
    paths: set[Path] = set()
    for folder in ("AssetsManager", "tests", "Plugins", "assets", "scripts", "webui/src"):
        paths.update(
            path for path in (root / folder).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )
    for pattern in ("*.py", "*.ini", "*.toml", "requirements*.txt", "*.spec", "pyrightconfig.json"):
        paths.update(root.glob(pattern))
    paths.add(root / "webui/package.json")
    manifest = {"run_id": run_id, "copies": {}, "sources": []}
    copies = {name: snapshot_root / name for name in ("sync", "lifecycle", "ops")}
    for path in sorted(paths):
        relative = path.relative_to(root)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        manifest["sources"].append({"path": relative.as_posix(), "sha256": digest})
        for copy in copies.values():
            destination = copy / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
    manifest["copies"] = {name: str(path) for name, path in copies.items()}
    manifest_name = "snapshot-manifest.json"
    if (evidence / manifest_name).exists():
        manifest_name = f"snapshot-{run_id}-manifest.json"
    (evidence / manifest_name).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    sys.stdout.write(json.dumps({"run_id": run_id, "copies": manifest["copies"], "files": len(paths), "manifest": manifest_name}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
