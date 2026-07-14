"""Search application service."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from AssetsManager.core.format_utils import CATEGORY_MAP


class _Scanner(Protocol):
    def search(self, query: str, limit: int = 200) -> list[dict]: ...


@dataclass(frozen=True)
class SearchResult:
    name: str
    path: str
    extension: str
    category: str

    @property
    def thumbnail_url(self) -> str:
        from urllib.parse import quote
        return f"/api/thumbnails/{quote(self.path, safe='/')}"


class SearchService:
    """Search assets by tags or name."""

    def search_by_tags(
        self,
        library_root: str | Path,
        tags: list[str],
        query: str = "",
        category: str = "all",
        db_conn: sqlite3.Connection | None = None,
    ) -> list[SearchResult]:
        """Find files that have any of the given tags."""
        if not db_conn:
            return []
        results: list[SearchResult] = []
        for tag in tags:
            try:
                rows = db_conn.execute(
                    "SELECT file_path FROM file_tags WHERE LOWER(tag)=LOWER(?)", (tag,)
                ).fetchall()
                for (fp,) in rows:
                    rel = os.path.relpath(fp, library_root).replace("\\", "/")
                    name = os.path.basename(fp)
                    if query and query not in name.lower():
                        continue
                    ext = os.path.splitext(name)[1].lower()
                    cat = CATEGORY_MAP.get(ext, "other")
                    if category != "all" and cat != category:
                        continue
                    results.append(SearchResult(name=name, path=rel, extension=ext, category=cat))
            except Exception:
                continue
        return results

    def search_by_name(
        self,
        query: str,
        category: str = "all",
        scanner: _Scanner | None = None,
        limit: int = 200,
    ) -> list[SearchResult]:
        """Find files by name using the in-memory scanner index."""
        if not scanner or not query:
            return []
        try:
            index_results = scanner.search(query, limit=limit)
        except Exception:
            return []

        results: list[SearchResult] = []
        for f in index_results:
            cat = CATEGORY_MAP.get(f["extension"], "other")
            if category != "all" and cat != category:
                continue
            results.append(SearchResult(
                name=f["name"], path=f["path"],
                extension=f["extension"], category=cat,
            ))
        return results

    def search_by_name_indexed(
        self,
        library_root: str | Path,
        query: str,
        category: str = "all",
        db_conn: sqlite3.Connection | None = None,
        limit: int = 200,
    ) -> list[SearchResult]:
        """Find files by name using the assets DB index.

        This is an alternative to ``search_by_name`` that uses the
        ``assets`` table instead of the in-memory scanner. It works
        even when the scanner hasn't been populated yet.
        """
        if not db_conn or not query:
            return []
        try:
            from AssetsManager.application.asset_index_service import AssetIndexService
            entries = AssetIndexService().search_by_name(db_conn, library_root, query, limit=limit)
        except Exception:
            return []

        results: list[SearchResult] = []
        for e in entries:
            cat = CATEGORY_MAP.get(e.extension, "other")
            if category != "all" and cat != category:
                continue
            rel = os.path.relpath(e.file_path, library_root).replace("\\", "/")
            results.append(SearchResult(
                name=e.name, path=rel,
                extension=e.extension, category=cat,
            ))
        return results
