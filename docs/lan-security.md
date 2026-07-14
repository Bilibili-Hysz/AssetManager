# LAN Security Rules

LAN sharing exposes local files over HTTP, so path validation is a hard security boundary.

## Path Validation

- Never trust request paths, query parameters, JSON paths, or share IDs.
- Resolve paths and verify they remain under the library root or the share scope before access.
- Do not use string prefix checks for path containment.
- Download, thumbnail, preview, ZIP, tag, and metadata routes must all use the same path validation policy.
- Share routes must validate both the library root and the share's allowed path list.

## Authentication Modes

| Mode | Config | Token Format | TTL |
|------|--------|-------------|-----|
| None | No password/key/users | `"no-auth"` literal | N/A |
| Password | `lan_password` (stored as PBKDF2 hash) | `generate_token(password_hash)` | 24h |
| Access Key | `lan_access_key` (stored as PBKDF2 hash) | Raw key on each request | Per-request |
| User Registration | `users` table in SQLite | `generate_user_token(id, username, role, secret)` | 24h |
| Local UI | `token_secret` (random 32-byte hex) | `generate_auth_token(secret)` via `utils.py` | 24h |

### Token Sources

Tokens are read from (in order):
1. Cookie: `lan_token` (httponly)
2. Header: `Authorization: Bearer <token>`
3. Query param: `?token=` or `?key=`

### Middleware Verification Order

1. Skip for public paths: `/api/auth/login`, `/api/auth/register`, `/api/auth/verify_key`, `/api/info`, `/api/tunnel/status`, `/ws`, `/`, `/favicon.ico`, `/static/*`, `/s/*`, `GET /api/shares/*`
2. If no auth configured → allow
3. Check raw access key against stored hash
4. Check `verify_auth_token(token, token_secret)` (local UI)
5. Check `verify_user_token(token, secret, db_conn)` (per-user)
6. Check `verify_token(token, password_hash)` (simple password)
7. If all fail → 401

## Rate Limiting

| Limiter | Config | Scope |
|---------|--------|-------|
| `RateLimiter` | 1000 req/60s | Non-browsing paths |
| `AuthRateLimiter` | 10 attempts/300s | `/api/auth/login`, `/api/auth/register`, `/api/shares/*/verify` |

## Password Storage

All passwords use PBKDF2-SHA256 with format `salt_hex:key_hex`.
- Passwords: 32-byte salt, 100,000 iterations
- Access keys: 16-byte salt, 50,000 iterations
- `is_password_hash()` detects if a stored value is already hashed (64-hex:64-hex format)

## Crypto Layer

All pure crypto functions (hashing, token generation/verification) live in `AssetsManager.domain.auth`. The LAN layer re-exports them for backward compatibility. `AuthService` and `ShareService` import crypto from `domain.auth` and DB operations from `lan.auth`.

## Cookie Settings

- `httponly=True`
- `samesite=Lax"`
- `path="/"`
- `max_age=86400`

## Tests

Tests in `tests/lan/test_lan_api.py` cover path traversal, rate limiting, auth middleware, share scoping, token verification, and password hash compatibility.
