# Metadata Combined Read Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce file-information reads from three database queries to two while preserving metadata output and session lifecycle behavior.

**Architecture:** Add a `MetadataRepository.get_notes_and_urls(file_path)` read method that selects the `notes` and `urls` columns from one `file_meta` row. It retains the existing URL JSON decoding and list-type validation. `MetadataService.get_metadata()` remains wrapped in `@session_operation`, reads tags through `TagRepository`, and receives notes plus URLs from the new Repository method.

**Tech Stack:** Python 3.14, SQLite, pytest.

## Global Constraints

- Preserve `MetadataService.get_metadata(library_root, path) -> AssetMetadata` and all InfoPanel-visible values.
- Keep URL decoding, malformed JSON handling, and non-list JSON rejection inside `MetadataRepository`.
- Keep the complete metadata read inside the existing `@session_operation` lease.
- Do not change database schema, LAN routes, controller interfaces, event publication, or standalone `get_notes()` / `get_urls()` behavior.
- Demonstrate the combined read with a focused regression test before production code changes.

---

### Task 1: Read Notes and URLs from One Metadata Row

**Files:**
- Modify: `AssetsManager/repositories/metadata_repository.py:25-61`
- Modify: `AssetsManager/application/metadata_service.py:53-65`
- Test: `tests/integration/test_repositories.py`
- Test: `tests/integration/test_metadata_service.py`

**Interfaces:**
- Consumes: `MetadataRepository(conn)`, its existing URL JSON parsing contract, and `MetadataService.get_metadata()`.
- Produces: `MetadataRepository.get_notes_and_urls(file_path: str) -> tuple[str, list[str]]`; `get_metadata()` performs one tag query and one combined metadata query.

- [ ] **Step 1: Write failing Repository tests**

```python
def test_get_notes_and_urls_reads_both_columns_and_validates_urls(memory_db):
    repo = MetadataRepository(memory_db)
    memory_db.execute(
        "INSERT INTO file_meta (file_path, notes, urls) VALUES (?, ?, ?)",
        ("/asset.txt", "note", '["https://example.com"]'),
    )
    memory_db.commit()

    assert repo.get_notes_and_urls("/asset.txt") == ("note", ["https://example.com"])


def test_get_notes_and_urls_rejects_non_list_json(memory_db):
    repo = MetadataRepository(memory_db)
    memory_db.execute(
        "INSERT INTO file_meta (file_path, notes, urls) VALUES (?, ?, ?)",
        ("/asset.txt", "note", '{"url": "https://example.com"}'),
    )
    memory_db.commit()

    assert repo.get_notes_and_urls("/asset.txt") == ("note", [])
```

- [ ] **Step 2: Run Repository tests to verify RED**

Run:

```powershell
python -m pytest tests/integration/test_repositories.py -k "notes_and_urls" -q
```

Expected: FAIL because `get_notes_and_urls` does not yet exist.

- [ ] **Step 3: Add the combined Repository read and shared URL decoder**

```python
def _decode_urls(self, file_path: str, value: str | None) -> list[str]:
    try:
        result = json.loads(value or "[]")
        if not isinstance(result, list):
            _log.warning("URLs JSON is not a list for %s: %r", file_path, value)
            return []
        return result
    except (json.JSONDecodeError, TypeError):
        _log.warning("Malformed URLs JSON for %s: %r", file_path, value)
        return []

def get_notes_and_urls(self, file_path: str) -> tuple[str, list[str]]:
    row = self._conn.execute(
        "SELECT notes, urls FROM file_meta WHERE file_path=?",
        (file_path,),
    ).fetchone()
    if not row:
        return ("", [])
    return (row[0] or "", self._decode_urls(file_path, row[1]))
```

Update `get_urls()` to delegate parsing to `_decode_urls()`.

- [ ] **Step 4: Run Repository tests to verify GREEN**

Run:

```powershell
python -m pytest tests/integration/test_repositories.py -q
```

Expected: all repository integration tests pass, including malformed-JSON cases.

- [ ] **Step 5: Write a failing service query-count test**

```python
def test_metadata_service_combines_notes_and_urls_into_one_metadata_query(tmp_path):
    from AssetsManager.application import MetadataService

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    asset.write_text("asset", encoding="utf-8")
    conn = _memory_conn()
    try:
        service = MetadataService(connection_provider=lambda _root: conn)
        service.set_notes(library, asset, "note")
        service.add_url(library, asset, "https://example.com")
        statements: list[str] = []
        conn.set_trace_callback(statements.append)

        metadata = service.get_metadata(library, asset)

        reads = [statement for statement in statements if statement.startswith("SELECT")]
        assert metadata.notes == "note"
        assert metadata.urls == ("https://example.com",)
        assert len(reads) == 2
    finally:
        conn.set_trace_callback(None)
        conn.close()
```

- [ ] **Step 6: Run the service test to verify RED**

Run:

```powershell
python -m pytest tests/integration/test_metadata_service.py::test_metadata_service_combines_notes_and_urls_into_one_metadata_query -q
```

Expected: FAIL because current `get_metadata()` performs separate notes and URLs queries.

- [ ] **Step 7: Route the service through the combined Repository read**

```python
notes, urls = meta_repo.get_notes_and_urls(str(target))
return AssetMetadata(
    path=target,
    tags=tuple(tag_repo.get_tags(str(target))),
    notes=notes,
    urls=tuple(urls),
)
```

- [ ] **Step 8: Run focused integration verification**

Run:

```powershell
python -m pytest tests/integration/test_repositories.py tests/integration/test_metadata_service.py -q
```

Expected: all Repository and MetadataService integration tests pass, including malformed URL JSON and two-query trace coverage.

- [ ] **Step 9: Run relevant UI and LAN metadata regressions**

Run:

```powershell
python -m pytest tests/unit/test_info_controller.py tests/lan/test_lan_api.py -q
```

Expected: InfoController and LAN metadata behavior remain unchanged.

- [ ] **Step 10: Commit the focused optimization**

```powershell
git add AssetsManager/repositories/metadata_repository.py AssetsManager/application/metadata_service.py tests/integration/test_repositories.py tests/integration/test_metadata_service.py docs/compose/plans/2026-07-17-metadata-combined-read.md
git commit -m "perf: combine metadata notes and URL reads"
```
