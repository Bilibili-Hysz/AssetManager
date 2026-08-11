"""One-shot migration for legacy emoji icon values in favorites.json and tag_metadata.

Dry-run by default (prints what would change); pass --apply to write back.
Idempotent and fail-safe: an error in one library never blocks the others.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from AssetsManager.core import icons
from AssetsManager.core.path_resolver import runtime_root
from AssetsManager.panels.sidebar import _FAVORITE_ICON_MAP

FAV_FALLBACK = "star"
TAG_FALLBACK = "tag"
_INVALID = "__invalid__"

_LIBRARY_DIR_RE = re.compile(r"^.+_[0-9a-f]{10}$")


def _resolve_favorite(value) -> str | None:
    """Return the canonical semantic name for a favorites icon value, or None."""
    target = (
        _FAVORITE_ICON_MAP[value]
        if isinstance(value, str) and value in _FAVORITE_ICON_MAP
        else icons.normalize(value, fallback=FAV_FALLBACK)
    )
    return None if target == value else target


def _resolve_tag_icon(value) -> str | None:
    """Return the canonical semantic name for a tag icon value, or None."""
    if not isinstance(value, str) or not value:
        return None
    target = icons.normalize(value, fallback=TAG_FALLBACK)
    return None if target == value else target


def _migrate_favorites(path: Path, apply: bool) -> tuple[int, list[tuple[str, str]]]:
    """Return (count, [(old, new), ...]) of icon values that need migration."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return 0, []
    changes: list[tuple[str, str]] = []
    for item in data:
        if not isinstance(item, dict) or "icon" not in item:
            continue
        target = _resolve_favorite(item["icon"])
        if target is None:
            continue
        changes.append((str(item["icon"]), target))
        item["icon"] = target
    if changes and apply:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return len(changes), changes


def _migrate_tag_metadata(path: Path, apply: bool) -> tuple[int, list[tuple[str, str, str]]]:
    """Return (count, [(new, tag, old), ...]) of tag icons that need migration."""
    con = sqlite3.connect(path)
    try:
        cur = con.cursor()
        cur.execute("PRAGMA query_only=ON")
        has_table = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tag_metadata'"
        ).fetchone()
        if not has_table:
            return 0, []
        cols = {row[1] for row in cur.execute("PRAGMA table_info(tag_metadata)")}
        if "tag" not in cols or "icon" not in cols:
            return 0, []
        rows = cur.execute("SELECT tag, icon FROM tag_metadata").fetchall()
    finally:
        con.close()
    changes: list[tuple[str, str, str]] = []
    for tag, icon in rows:
        target = _resolve_tag_icon(icon)
        if target is None:
            continue
        changes.append((target, tag, str(icon)))
    if changes and apply:
        con = sqlite3.connect(path)
        try:
            con.execute("BEGIN")
            con.executemany(
                "UPDATE tag_metadata SET icon=? WHERE tag=? AND icon=?", changes
            )
            con.commit()
        finally:
            con.close()
    return len(changes), changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write changes back (default: dry-run)"
    )
    args = parser.parse_args()

    root = runtime_root()
    shared = root / "Shared"
    total_fav = 0
    total_tag = 0
    failed = 0
    skipped = 0
    libraries = 0
    identities = sorted(shared.glob("*.identity")) if shared.is_dir() else []
    for ident in identities:
        data_name = ident.stem
        if data_name.startswith(".") or not _LIBRARY_DIR_RE.match(data_name):
            continue
        data_dir = root / data_name
        if not data_dir.is_dir():
            continue
        libraries += 1
        fav_path = data_dir / "favorites.json"
        db_path = data_dir / "assetmanager.db"
        fav_count = 0
        tag_count = 0
        if fav_path.is_file():
            try:
                fav_count, changes = _migrate_favorites(fav_path, args.apply)
            except json.JSONDecodeError as exc:
                skipped += 1
                print(f"[warn] {fav_path}: {exc}", file=sys.stderr)
            except Exception as exc:
                failed += 1
                print(f"[warn] {fav_path}: {exc}", file=sys.stderr)
            else:
                for old, new in changes:
                    print(f"{data_dir.name}: favorites {old!r} -> {new}")
        if db_path.is_file():
            try:
                tag_count, changes = _migrate_tag_metadata(db_path, args.apply)
            except Exception as exc:
                failed += 1
                print(f"[warn] {db_path}: {exc}", file=sys.stderr)
            else:
                for new, tag, old in changes:
                    print(f"{data_dir.name}: tag {tag!r} {old!r} -> {new}")
        if fav_count or tag_count:
            print(f"{data_dir.name}: favorites={fav_count} tag_metadata={tag_count}")
        total_fav += fav_count
        total_tag += tag_count

    mode = "applied" if args.apply else "dry-run"
    if total_fav + total_tag == 0:
        print(f"无需迁移（未发现 legacy emoji 图标值） [{mode}]")
    else:
        print(f"favorites migrated: {total_fav} [{mode}]")
        print(f"tag_metadata migrated: {total_tag} [{mode}]")
    print(f"libraries scanned: {libraries} skipped: {skipped} failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
