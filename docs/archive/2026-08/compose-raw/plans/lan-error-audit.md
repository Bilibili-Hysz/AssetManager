# LAN Error Response Audit — Internal Path / Exception Leakage
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

**Date:** 2026-06-17
**Scope:** All `AssetsManager/lan/` route handlers, server, middleware, and supporting modules.
**Previous work:** `lan/auth.py` registration fallback sanitized; `lan/server.py::connection_for()` ValueError replaced with generic message.

---

## Summary

| Severity | Count | Description |
|----------|-------|-------------|
| Critical | 0     | No filesystem paths, stack traces, or exception internals leaked to clients |
| Minor    | 0     | (see Notes below for informational items) |
| Safe     | 62    | All error responses use generic, client-safe messages |

**No fixes required.** The codebase is already well-sanitized.

---

## Files Audited

| File | Error Responses | Verdict |
|------|----------------|---------|
| `lan/routes/auth.py`        | 11 | Safe — all hardcoded strings |
| `lan/routes/users.py`       | 7  | Safe |
| `lan/routes/shares.py`      | 20 | Safe |
| `lan/routes/files.py`       | 3  | Safe |
| `lan/routes/metadata.py`    | 5  | Safe |
| `lan/routes/tags.py`        | 9  | Safe |
| `lan/routes/thumbnails.py`  | 2  | Safe |
| `lan/routes/downloads.py`   | 8  | Safe |
| `lan/routes/system.py`      | 0  | Safe — data responses only |
| `lan/routes/pages.py`       | 1  | Safe — plain text 404 |
| `lan/routes/_helpers.py`    | 3  | Safe — raises aiohttp HTTP exceptions with generic reasons |
| `lan/routes/websocket.py`   | 0  | Safe — no error responses |
| `lan/server.py`             | 1  | Safe — `"Unauthorized"` in middleware |
| `lan/security.py`           | 3  | Safe — generic 403/429 messages |

---

## Detailed Findings

### Pattern search results

```
rg "str\(exc\)"  → 0 matches in lan/
rg "str\(e\)"    → 0 matches in lan/
rg "traceback"   → 0 matches in lan/
rg "repr\("      → 0 matches in lan/ (error context)
```

No route handler uses `str(exc)`, `traceback.format_exc()`, or `repr()` in any client-facing error response.

### Auth error messages (`lan/routes/auth.py`)

The `authenticate_user()` and `register_user()` methods return specific validation strings:

- `"User not found"`, `"User is deactivated"`, `"Invalid password"` (auth)
- `"Username must be at least 2 characters"`, `"Username already exists"`, etc. (registration)

These are **intentionally specific** for good UX and do not leak internal paths, database schemas, or stack traces. They are standard authentication feedback.

Note: The distinction between "User not found" and "Invalid password" enables user enumeration. This is a separate auth-design concern, not a path/exception leakage issue.

### `validate_path` / `validated_existing_key` (`lan/routes/_helpers.py`)

These raise `web.HTTPBadRequest(reason="Path escape detected")` and `web.HTTPNotFound(reason="File not found")`. The `reason` is used by aiohttp's default error handler for the status line, not the response body — **no path leakage**.

When called inside `except Exception` blocks (e.g., `shares.py:66`, `downloads.py:83`), the HTTP exception is caught and replaced with a generic message. This is slightly imprecise but safe.

### Server startup (`lan/server.py`)

- Line 104: `raise OSError(f"Failed to start server on port {port}")` — caught internally, not exposed to HTTP clients.
- Lines 114, 289, 301: `_log.warning/error(...)` — server logs only, never sent to clients.
- Line 397: `{"error": "Unauthorized"}` — safe.

### ZIP creation (`lan/routes/_helpers.py`)

- Line 220: `_log.exception("Failed to create ZIP at %s", zip_path)` — logs the temp path server-side only. The client receives `"Failed to create ZIP"` (generic).

---

## Notes (informational, not actionable)

1. **`server.status()` exposes `library_root` as full path** (line 135). This is returned by `handle_info` but `handle_info` only sends `lan.library_root.name` (just the folder name, not the full path). The `handle_stats` endpoint does not expose it. No leakage.

2. **`_log.warning("Server shutdown timed out or failed: %s", e)`** at `server.py:114` logs the exception string. This is server-side logging only — appropriate and not client-facing.

---

## Conclusion

The LAN error handling is well-designed. All client-facing error responses use hardcoded, generic messages. No filesystem paths, stack traces, database error details, or internal exception strings are leaked. No changes needed.
