"""Mock implementations of core service protocols for testing.

Usage:
    from tests.mocks import MockTagStore, MockSettings, MockProjectData
    store = MockTagStore()
    store.add_tag("/test/file.png", "nature")
    assert "nature" in store.get_tags("/test/file.png")
"""
import tempfile
from pathlib import Path


class MockTagStore:
    """In-memory tag store for testing."""

    def __init__(self):
        self._tags: dict[str, list[str]] = {}

    def get_tags(self, filepath: str) -> list[str]:
        return list(self._tags.get(filepath, []))

    def get_tags_for_files(self, filepaths: list[str]) -> dict[str, list[str]]:
        return {str(Path(filepath).resolve()): list(self._tags.get(filepath, [])) for filepath in filepaths}

    def add_tag(self, filepath: str, tag: str) -> None:
        if filepath not in self._tags:
            self._tags[filepath] = []
        if tag not in self._tags[filepath]:
            self._tags[filepath].append(tag)

    def remove_tag(self, filepath: str, tag: str) -> None:
        if filepath in self._tags and tag in self._tags[filepath]:
            self._tags[filepath].remove(tag)

    def remove_file(self, filepath: str) -> None:
        self._tags.pop(filepath, None)

    def get_all_tags(self) -> list[str]:
        tags = set()
        for file_tags in self._tags.values():
            tags.update(file_tags)
        return sorted(tags)

    def get_files_by_tag(self, tag: str) -> list[str]:
        return [fp for fp, tags in self._tags.items() if tag in tags]

    def save(self) -> None:
        pass  # In-memory, no persistence needed


class MockProjectData:
    """In-memory project data for testing."""

    def __init__(self):
        self._notes: dict[str, str] = {}
        self._urls: dict[str, list[str]] = {}
        self._dir_sizes: dict[str, tuple[int, bool]] = {}

    def get_notes(self, path: str) -> str:
        return self._notes.get(path, "")

    def set_notes(self, path: str, text: str) -> None:
        self._notes[path] = text

    def get_urls(self, path: str) -> list[str]:
        return list(self._urls.get(path, []))

    def add_url(self, path: str, url: str) -> None:
        if not url.startswith("http"):
            raise ValueError("Invalid URL")
        if path not in self._urls:
            self._urls[path] = []
        if url not in self._urls[path]:
            self._urls[path].append(url)

    def remove_url(self, path: str, url: str) -> None:
        if path in self._urls and url in self._urls[path]:
            self._urls[path].remove(url)

    def get_dir_size(self, dir_path: str, force: bool = False) -> tuple[int, bool]:
        if dir_path in self._dir_sizes:
            return self._dir_sizes[dir_path]
        return (0, False)


class MockSettings:
    """In-memory settings for testing."""

    def __init__(self):
        self._data: dict = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value) -> None:
        self._data[key] = value

    def save(self) -> None:
        pass

    def load(self) -> None:
        pass

    def get_list(self, key, default=None) -> list:
        val = self._data.get(key)
        if isinstance(val, list):
            return list(val)
        return default if default is not None else []

    def set_list(self, key, values, max_items=None) -> None:
        result = list(values)
        if max_items and len(result) > max_items:
            result = result[:max_items]
        self._data[key] = result

    def prepend_list(self, key, value, max_items=50) -> None:
        items = self.get_list(key)
        if value in items:
            items.remove(value)
        items.insert(0, value)
        self.set_list(key, items, max_items)

    def remove_from_list(self, key, value) -> None:
        items = self.get_list(key)
        if value in items:
            items.remove(value)
            self.set_list(key, items)


class MockDatabase:
    """SQLite :memory: database for testing."""

    def __init__(self):
        import sqlite3
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS file_tags (
                file_path TEXT NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY (file_path, tag)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS file_meta (
                file_path TEXT PRIMARY KEY,
                notes TEXT DEFAULT '',
                urls TEXT DEFAULT '[]'
            )
        """)
        self._conn.commit()
        self._current_root = "."

    def open_library(self, root_path: str) -> None:
        self._current_root = root_path

    def close(self) -> None:
        self._conn.close()

    @property
    def db_conn(self):
        return self._conn

    @property
    def data_dir(self) -> Path:
        return Path(tempfile.gettempdir()) / "mock_data"

    @property
    def thumb_dir(self) -> Path:
        return self.data_dir / ".thumbnails"
