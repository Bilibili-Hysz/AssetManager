"""Tag repository — CRUD operations for the file_tags table."""
from __future__ import annotations

import logging
from sqlite3 import Connection

from AssetsManager.core.database import db_write_lock

_log = logging.getLogger(__name__)


class TagRepository:
    """Encapsulates all tag-related database operations.

    This repository provides a clean interface for tag CRUD without
    exposing raw SQL to application services.
    """

    def __init__(self, conn: Connection):
        self._conn = conn

    def get_tags(self, file_path: str) -> list[str]:
        """Return all tags for a file path, sorted alphabetically."""
        rows = self._conn.execute(
            "SELECT tag FROM file_tags WHERE file_path=? ORDER BY tag",
            (file_path,),
        ).fetchall()
        return [r[0] for r in rows]

    def get_tags_for_files(self, file_paths: list[str]) -> dict[str, list[str]]:
        """Return tags for multiple files, keyed by file path.

        Uses chunked IN queries to avoid SQLite variable limit.
        """
        if not file_paths:
            return {}
        result: dict[str, list[str]] = {p: [] for p in file_paths}
        for start in range(0, len(file_paths), 900):
            chunk = file_paths[start:start + 900]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT file_path, tag FROM file_tags WHERE file_path IN ({placeholders}) ORDER BY file_path, tag",
                chunk,
            ).fetchall()
            for path, tag in rows:
                result.setdefault(path, []).append(tag)
        return result

    def add_tag(self, file_path: str, tag: str) -> bool:
        """Add a tag to a file. Returns True if inserted (not duplicate)."""
        with db_write_lock():
            try:
                self._conn.execute(
                    "INSERT OR IGNORE INTO file_tags (file_path, tag) VALUES (?, ?)",
                    (file_path, tag),
                )
                self._conn.commit()
                return True
            except Exception:
                _log.warning("add_tag failed for %s/%s", file_path, tag, exc_info=True)
                return False

    def remove_tag(self, file_path: str, tag: str) -> bool:
        """Remove a tag from a file. Returns True if deleted."""
        with db_write_lock():
            try:
                self._conn.execute(
                    "DELETE FROM file_tags WHERE file_path=? AND tag=?",
                    (file_path, tag),
                )
                self._conn.commit()
                return True
            except Exception:
                _log.warning("remove_tag failed for %s/%s", file_path, tag, exc_info=True)
                return False

    def remove_file(self, file_path: str) -> int:
        """Remove all tags for a file. Returns number of tags removed."""
        with db_write_lock():
            cur = self._conn.execute(
                "DELETE FROM file_tags WHERE file_path=?",
                (file_path,),
            )
            self._conn.commit()
            return cur.rowcount

    def get_all_tags(self) -> list[str]:
        """Return all unique tags across all files."""
        rows = self._conn.execute(
            "SELECT DISTINCT tag FROM file_tags ORDER BY tag"
        ).fetchall()
        return [r[0] for r in rows]

    def get_files_by_tag(self, tag: str) -> list[str]:
        """Return all file paths that have a given tag."""
        rows = self._conn.execute(
            "SELECT file_path FROM file_tags WHERE tag=?",
            (tag,),
        ).fetchall()
        return [r[0] for r in rows]

    def get_tags_for_tree(self, dir_path: str) -> list[str]:
        """Return all unique tags for files under a directory prefix."""
        escaped = dir_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self._conn.execute(
            "SELECT DISTINCT tag FROM file_tags WHERE file_path LIKE ? ESCAPE '\\' ORDER BY tag",
            (escaped + "%",),
        ).fetchall()
        return [r[0] for r in rows]

    def rename_tag(self, old_name: str, new_name: str) -> int:
        """Rename a tag across all files. Returns number of rows affected."""
        with db_write_lock():
            cur = self._conn.execute(
                "UPDATE file_tags SET tag=? WHERE tag=?",
                (new_name, old_name),
            )
            self._conn.commit()
            return cur.rowcount

    def delete_tag(self, tag_name: str) -> int:
        """Delete a tag from all files. Returns number of rows affected."""
        with db_write_lock():
            cur = self._conn.execute(
                "DELETE FROM file_tags WHERE tag=?",
                (tag_name,),
            )
            self._conn.commit()
            return cur.rowcount

    def migrate_path(self, old_path: str, new_path: str) -> int:
        """Move all tags from old_path to new_path. Returns rows affected."""
        escaped = old_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with db_write_lock():
            rows = self._conn.execute(
                "SELECT file_path, tag FROM file_tags WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (old_path, escaped + "/%"),
            ).fetchall()
            count = 0
            for path, tag in rows:
                mapped = new_path + path[len(old_path):] if path.startswith(old_path + "/") else new_path
                self._conn.execute(
                    "INSERT OR IGNORE INTO file_tags (file_path, tag) VALUES (?, ?)",
                    (mapped, tag),
                )
                count += 1
            if rows:
                self._conn.execute(
                    "DELETE FROM file_tags WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                    (old_path, escaped + "/%"),
                )
            self._conn.commit()
            return count

    # ── Tag metadata (color, icon, category) ───────────────────

    def get_tag_metadata(self, tag: str) -> dict[str, str] | None:
        """Return metadata for a tag, or None if not set."""
        row = self._conn.execute(
            "SELECT color, icon, category FROM tag_metadata WHERE tag=?",
            (tag,),
        ).fetchone()
        if row is None:
            return None
        return {"color": row[0], "icon": row[1], "category": row[2]}

    def set_tag_metadata(self, tag: str, color: str = "", icon: str = "", category: str = "") -> None:
        """Set metadata for a tag."""
        with db_write_lock():
            self._conn.execute(
                "INSERT INTO tag_metadata (tag, color, icon, category) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(tag) DO UPDATE SET "
                "color=excluded.color, icon=excluded.icon, category=excluded.category",
                (tag, color, icon, category),
            )
            self._conn.commit()

    def get_tags_with_metadata(self) -> list[dict]:
        """Return all tags with their metadata."""
        rows = self._conn.execute(
            "SELECT t.tag, COUNT(*) as cnt, COALESCE(m.color, '') as color, "
            "COALESCE(m.icon, '') as icon, COALESCE(m.category, '') as category "
            "FROM file_tags t LEFT JOIN tag_metadata m ON t.tag = m.tag "
            "GROUP BY t.tag ORDER BY t.tag"
        ).fetchall()
        return [
            {"name": r[0], "count": r[1], "color": r[2], "icon": r[3], "category": r[4]}
            for r in rows
        ]

    def delete_tag_metadata(self, tag: str) -> None:
        """Delete metadata for a tag."""
        with db_write_lock():
            self._conn.execute("DELETE FROM tag_metadata WHERE tag=?", (tag,))
            self._conn.commit()
