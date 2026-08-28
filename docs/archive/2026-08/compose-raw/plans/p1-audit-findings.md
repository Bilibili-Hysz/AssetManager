# P1 Audit: LAN Route DB Access Paths
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

**Date:** 2026-06-17
**Scope:** All LAN route handlers, server middleware, and shared helpers
**Verdict: SAFE — no concrete cross-thread safety issues found. P1 Task 1.3 (fixes) can be SKIPPED.**

---

## 1. Architecture Summary

```
Connection origin:
  LibrarySession.db_conn  ──►  _LanServerImpl._db_conn (stored at __init__)
                                    │
                                    ├── .db_conn property (direct access)
                                    ├── .connection_for() (same conn, with library_root validation)
                                    ├── AuthService._conn
                                    ├── DirectoryScanner._db (stored, never used for DB ops)
                                    └── LanScopedServices (lazy-built on first request)
                                         ├── MetadataService(connection_provider=lan.connection_for)
                                         ├── ProjectService(connection_provider=lan.connection_for)
                                         └── TagService(connection_provider=lan.connection_for)

Thread contexts:
  1. Qt main thread      — original owner of db_conn (LibrarySession)
  2. Event loop thread   — aiohttp request handlers, _startup(), _auth_middleware
  3. to_thread pool      — asyncio.to_thread() calls in files, metadata, thumbnails routes
  4. Scanner thread      — DirectoryScanner._scan_all (no DB access, filesystem only)

Locking:
  db_write_lock() = DatabaseManager._write_lock = threading.RLock() (reentrant, process-wide)
  All write operations in repositories and lan/auth.py use db_write_lock().
  Reads are unserialized (safe under WAL mode).
```

## 2. Complete DB Access Table

| Route / Handler | File:Line | DB Access Method | Via Service? | Thread Context | Write? | Lock Used |
|---|---|---|---|---|---|---|
| `_startup` → `init_users_table()` | server.py:272 | `db_conn.execute()` (CREATE TABLE) | No (direct) | Event loop | **YES** | `db_write_lock()` |
| `_auth_middleware` → `_has_active_users()` | server.py:334 | `db_conn.execute()` (SELECT COUNT) | No (direct) | Event loop | No | N/A (read) |
| `_auth_middleware` → `verify_user_token()` | server.py:385 | `AuthRepository.get_user_by_id()` | AuthService | Event loop | No | N/A (read) |
| `handle_files` → `_list()` | files.py:33 | None (filesystem only) | AssetService | **to_thread** | No | N/A |
| `handle_files` → `batch_cached_stats()` | files.py:57 | `MetadataService.get_cached_stats()` | MetadataService | Event loop | No | N/A (read) |
| `handle_login` → `authenticate_user()` | auth.py:20 | `AuthRepository.get_user_by_username()` | AuthService | Event loop | No | N/A (read) |
| `handle_register` → `init_tables()` | auth.py:52 | `AuthRepository.init_tables()` | AuthService | Event loop | **YES** | `db_write_lock()` |
| `handle_register` → `register_user()` | auth.py:54 | `AuthRepository.insert_user()` + invite consume | AuthService | Event loop | **YES** | `db_write_lock()` |
| `handle_verify_key` | auth.py:81 | No DB access (crypto only) | — | Event loop | No | N/A |
| `handle_users` → `list_users()` | users.py:13 | `AuthRepository.list_users()` | AuthService | Event loop | No | N/A (read) |
| `handle_toggle_user` → `set_user_active()` | users.py:34-36 | `AuthRepository.set_user_active()` | AuthService | Event loop | **YES** | `db_write_lock()` |
| `handle_invites` → `list_invite_codes()` | users.py:48 | `AuthRepository.list_invite_codes()` | AuthService | Event loop | No | N/A (read) |
| `handle_create_invite` → `insert_invite_code()` | users.py:58 | `AuthRepository.insert_invite_code()` | AuthService | Event loop | **YES** | `db_write_lock()` |
| `handle_revoke_invite` → `deactivate_invite_code()` | users.py:71 | `AuthRepository.deactivate_invite_code()` | AuthService | Event loop | **YES** | `db_write_lock()` |
| `handle_create_share` → `create_share()` | shares.py:101 | `ShareRepository.insert()` | ShareService | Event loop | **YES** | `db_write_lock()` |
| `handle_list_shares` → `list_shares()` | shares.py:131 | `ShareRepository.list_all()` | ShareService | Event loop | No | N/A (read) |
| `handle_delete_share` → `delete_share()` | shares.py:160 | `ShareRepository.delete()` | ShareService | Event loop | **YES** | `db_write_lock()` |
| `handle_verify_share_password` | shares.py:183-191 | `ShareRepository.get()`, `get_password_hash()` | ShareService | Event loop | No | N/A (read) |
| `handle_share_download` → `increment_download()` | shares.py:228 | `ShareRepository.increment_download()` | ShareService | Event loop | **YES** | `db_write_lock()` |
| `handle_share_preview` | shares.py:244 | `ShareRepository.get()` | ShareService | Event loop | No | N/A (read) |
| `handle_share_info` | shares.py:272 | `ShareRepository.get()`, `get_password_hash()` | ShareService | Event loop | No | N/A (read) |
| `handle_tags` → `list_tags()` | tags.py:16 | `conn.execute()` (SELECT from file_tags) | TagService | Event loop | No | N/A (read) |
| `handle_create_tag` → `add_tag()` | tags.py:38 | `TagRepository.get_tags()` + `add_tag()` | TagService | Event loop | **YES** | `db_write_lock()` |
| `handle_rename_tag` → `rename_tag()` | tags.py:59 | `TagRepository.rename_tag()` | TagService | Event loop | **YES** | `db_write_lock()` |
| `handle_delete_tag` → `delete_tag()` | tags.py:71 | `TagRepository.delete_tag()` | TagService | Event loop | **YES** | `db_write_lock()` |
| `handle_meta` → `get_metadata()` | metadata.py:19 | `MetadataRepository` + `TagStore.get_tags()` | MetadataService | **to_thread** | No | N/A (read) |
| `handle_search` → `search_by_tags()` | metadata.py:44 | `db_conn.execute()` (SELECT from file_tags) | SearchService | **to_thread** | No | N/A (read) |
| `handle_search` → `search_by_name_indexed()` | metadata.py:50 | `AssetIndexService.search_by_name()` | SearchService | **to_thread** | No | N/A (read) |
| `handle_home` → `get_home()` | metadata.py:78 | `db_conn` via connection_provider | ProjectService | **to_thread** | No | N/A (read) |
| `handle_tree` → `build_tree()` | metadata.py:91 | via connection_provider | ProjectService | **to_thread** | No | N/A (read) |
| `handle_projects` → `list_projects()` | metadata.py:118 | `db_conn` via connection_provider | ProjectService | **to_thread** | No | N/A (read) |
| `handle_project_detail` → `get_project_detail()` | metadata.py:141 | `db_conn` via connection_provider | ProjectService | **to_thread** | No | N/A (read) |
| `handle_thumbnail` → `_check_blur()` | thumbnails.py:26 | `db_conn.execute()` (SELECT from file_tags) | ThumbnailService | **to_thread** | No | N/A (read) |
| `handle_thumbnail_batch` → `_check_blur()` | thumbnails.py:78 | `db_conn.execute()` (SELECT from file_tags) | ThumbnailService | **to_thread** | No | N/A (read) |
| `handle_info` → `has_active_users()` | system.py:16 | `AuthRepository.has_active_users()` | AuthService (new) | Event loop | No | N/A (read) |
| `handle_info` → `count_projects()` | system.py:29 | via connection_provider | ProjectService | Event loop | No | N/A (read) |
| `handle_info` → `get_library_total_size()` | system.py:30 | via connection_provider | MetadataService | Event loop | No | N/A (read) |
| `handle_download` | downloads.py:32 | None (filesystem only) | — | Event loop | No | N/A |
| `handle_batch_download` | downloads.py:60 | None (filesystem only) | — | Event loop | No | N/A |
| `handle_index` / `handle_detail_page` | pages.py | None (static files) | — | Event loop | No | N/A |
| `handle_logout` | auth.py:89 | None | — | Event loop | No | N/A |
| `handle_me` | auth.py:95 | None (reads request context) | — | Event loop | No | N/A |
| `handle_tunnel_status` / `handle_stats` | system.py | None | — | Event loop | No | N/A |

## 3. Unsafe Pattern Analysis

### 3.1 `connection_for()` Consistency — PASS

`connection_for()` (server.py:162-170) always returns `self._db_conn`, the same connection stored at `__init__`. If a different `library_root` is requested, it raises `ValueError`. All services built via `LanScopedServices` use `lan.connection_for` as their `ConnectionProvider`, guaranteeing they all share the same connection.

### 3.2 Connection Not Closed While Server Running — PASS

The `_shutdown()` method (server.py:318-325) only stops the aiohttp runner and WebSocket manager. It does **not** close `self._db_conn`. The connection lifecycle is managed by `DatabaseManager` and `LibrarySession`, not by the LAN server. The Qt main thread owns the connection lifecycle.

### 3.3 `handle_files` → `AssetService().list_directory()` Write Safety — PASS

`AssetService.list_directory()` (asset_service.py:64-100) is pure filesystem — `os.scandir()`, sorting, filtering. No DB access at all. The DB read happens after `to_thread` returns, via `batch_cached_stats()` in the event loop thread.

### 3.4 `_has_active_users()` Thread Safety — PASS (with minor note)

Called from `_auth_middleware` (event loop thread). The method reads `_has_users_cache` and `_has_users_cache_time` without synchronization. However:
- Python's GIL ensures atomic reads of simple attributes
- Worst case: one extra DB query on cache miss (stale read of time)
- The cache is invalidated via `invalidate_user_cache()` from event loop thread only
- **Not a real safety issue**, just a minor inefficiency

### 3.5 `to_thread` Read Safety — PASS

All `asyncio.to_thread()` calls in routes only perform **reads** (SELECT queries). WAL mode allows concurrent reads from any thread. Write operations in `to_thread` contexts do not exist.

### 3.6 Write Lock Coverage — PASS

Every write path is wrapped in `db_write_lock()`:
- `AuthRepository`: `init_tables`, `insert_user`, `set_user_active`, `insert_invite_code`, `deactivate_invite_code`
- `ShareRepository`: `insert`, `delete`, `increment_download`
- `TagRepository`: `add_tag`, `remove_tag`, `rename_tag`, `delete_tag`, `remove_file`
- `MetadataRepository`: `set_notes`, `add_url`, `remove_url`, `set_cached_size`, etc.
- `lan/auth.py`: `init_users_table`, `register_user`, `authenticate_user` (last_login update), etc.

The lock is `threading.RLock()` (reentrant), so nested lock acquisitions from the same thread are safe.

### 3.7 `db_conn` Accessed After Server Stop — N/A

After `stop()` sets `self._running = False` and `self._loop = None`, no new requests are served. The connection remains valid (not closed by the server). If the Qt main thread closes the connection later, that's outside the server's scope.

## 4. Minor Observations (Not Safety Issues)

### 4.1 `handle_info` Creates Redundant AuthService

`system.py:16` creates `AuthService(lan.db_conn, lan.token_secret)` on every `/api/info` request instead of using the cached `get_auth_service(request)`. This is an unnecessary object allocation per request but not a safety issue — same connection, same thread.

### 4.2 `SearchService` Bypasses Repository Layer

`SearchService.search_by_tags()` (search_service.py:47) executes raw SQL directly on `db_conn` rather than going through a repository. This is a code organization concern, not a thread safety issue.

### 4.3 `TagService.list_tags()` Bypasses Repository Layer

`TagService.list_tags()` (tag_service.py:53) executes raw SQL directly on `conn`. Same pattern as SearchService — code organization, not safety.

### 4.4 `DirectoryScanner` Stores Unused `db_conn`

`DirectoryScanner.__init__` (scanner.py:17-19) stores `db_conn` but never uses it for any DB operation. Only filesystem scanning. Harmless but misleading.

## 5. Thread Context Summary

| Thread | Operations | DB Access | Safe? |
|---|---|---|---|
| Event loop | All route handlers, middleware, startup | Reads + writes (via services) | Yes — writes locked, reads WAL-safe |
| to_thread pool | `_list()`, `get_metadata()`, `search*()`, `_check_blur()`, project ops | **Reads only** | Yes — WAL mode |
| Scanner thread | `_scan_all()` | **None** (filesystem only) | N/A |
| Qt main thread | LibrarySession lifecycle | Owns connection | Outside LAN scope |

## 6. Conclusion

**No concrete cross-thread safety issues found.** The architecture is sound:

1. All writes are serialized via `db_write_lock()` (process-wide `RLock`)
2. All `to_thread` operations are read-only (WAL-safe)
3. `connection_for()` always returns the same connection
4. The server never closes the connection
5. `AssetService.list_directory()` does not touch the database

**Recommendation:** P1 Task 1.3 (fixes) can be **skipped**. The current implementation is safe for the documented thread model.
