# LAN Security Rules

> 状态:**LIVING** · updated: 2026-09-04 · 以代码为事实源;与代码的全面偏差清单见 `docs/overview-2026-08-27.md` §18。本文件不再重复 dated 证据(见 `docs/full-review/`)。
>
> **剥离标注（2026-09-04）**：商城运行时已按 [ADR 0005](adr/0005-commerce-extraction.md) 于 2026-08-30 移除（`/api/shop/*`、`/storefront`、`/seller` 路由与 seller/shop cookie 均不在当前代码中；13 个商城 DB 迁移与 schema 表为保迁移链**刻意保留**为无害孤儿）。下文标注 ~~删除线~~ 的商城条目是历史快照，保留用于理解迁移链；当前有效清单以 `lan/api.py` 实测为准（72 条路由，见 `docs/deep-analysis-2026-09-04/04-lan.md` §1）。

LAN sharing exposes local files through the configured HTTP or HTTPS endpoint, so path validation is a hard security boundary. Without both a certificate and key the endpoint is HTTP; with both it is HTTPS.

## Path Validation

- Never trust request paths, query parameters, JSON paths, or share IDs.
- Resolve paths and verify they remain under the library root or the share scope before access.
- Do not use string prefix checks for path containment.
- Download, thumbnail, preview, ZIP, tag, and metadata routes must all use the same path validation policy.
- Share routes must validate both the library root and the share's allowed path list.

## Authentication Modes

| Mode | Config | Token Format | TTL |
|------|--------|-------------|-----|
| None | No password/key/users | guest principal (no token literal) | N/A |
| Password | `lan_password` (stored as PBKDF2 hash) | `generate_token(password_hash)` — `ts.nonce.sig` | 24h |
| Access Key | `lan_access_key` (stored as PBKDF2 hash) | Raw key on each request; login exchanges it for a `local_ui` token | Per-request |
| User Registration | `users` table in SQLite | `generate_user_token(id, username, role, secret)` — `ts.uid.nonce.sig` | 24h |
| Local UI | derived `local_ui_auth_secret` | `generate_auth_token(local_ui_auth_secret)` via `utils.py` | 24h or until session close/config change, whichever comes first |
| Runtime sharing | frozen Runtime `token_secret` (random 32-byte hex) | AuthService/ShareService internal secret; not a LAN UI token | Runtime/session lifetime; never persisted |

> 令牌格式：新格式 `ts.nonce.sig`（nonce = `secrets.token_hex(4)`，消除同秒确定性）；verify 兼容旧格式 `ts.sig`。所有 sig 为 HMAC-SHA256 截断 32 hex。

### Token Sources

`ApplicationBootstrap` generates `token_secret` once per live Runtime/session, shares it between that Runtime's `AuthService` and `ShareService`, reuses it across LAN stop/start, and never persists it. LAN derives `local_ui_auth_secret` from that Runtime secret plus `access_key/password/auth_mode`; unchanged auth configuration is stable across stop/start, while a configuration change invalidates old local UI tokens. Closing the session invalidates both layers; another library/session has a separate secret and database.

Tokens are read from (in order):
1. Header: `Authorization: Bearer <token>` (优先)
2. Cookie: `lan_token` (httponly)

**Query parameters (`?token=` / `?key=`) are explicitly NOT supported** — they were removed to prevent credential leakage into logs, browser history, and Referer headers (`lan/routes/_helpers.py get_auth_token`). WebSocket handshakes additionally reject any query-parameter credentials.

### Middleware Verification Order

1. Public paths pass through as guest: `/api/auth/login|register|verify_key`、`/api/quota`、`/login`、`/browse`、`/detail`、`/`、`/favicon.ico`；public prefixes：`/assets`、`/s`；public share endpoints：`POST /api/shares/{id}/verify`、`GET /api/shares/{id}/info|download|preview`（仅无尾段/带路径）。（历史：~~`/api/auth/seller-status|seller-login|seller-logout`、`/storefront`、`/store`、`/seller`、`/app`、`/api/shop`~~ 已随 ADR 0005 剥离）
2. If no auth configured (key/password/users all absent) → guest allow（`_has_active_users` 带 30s 负缓存，DB 异常 fail-closed）
3. Check raw access key against stored hash (PBKDF2 `verify_key`)
4. Check `verify_auth_token(token, local_ui_auth_secret)` (local UI)
5. Check `auth_service.verify_user_token(token)` (per-user；撤销表 `_revoked_tokens` 先行校验，TTL 24h/上限 10000)
6. Check `verify_token(token, password_hash)` (simple password)
7. If all fail → 401

> `/api/info` 特例：公开读，但携带有效凭证时反射其身份（access_key → local_ui → user → password）。

## Share Start Preflight

LAN sharing startup is guarded by a UI-neutral security preflight shared by the Desktop mixin, ShareManager, and public LanServer facade.

- `lan_share_safety_ack_version` is versioned and must exactly match the current contract version; missing, malformed, old, or future values are treated as unconfirmed.
- lan_trusted_network_confirmed is false by default and only permits unauthenticated LAN exposure when the user has explicitly confirmed the network is trusted.
- Effective authentication must come from the server auth_status result. A configured mode string or the trusted-network flag cannot authorize a public tunnel.
- Missing or failing auth_status is fail-closed for tunnel startup.
- The preflight snapshot exposes `share_state`, `tunnel_state`, `confirmation_required`, `trusted_network_confirmed`, and `failure_reason` for Desktop/LAN/WebUI consumers.
- `security_preflight_from_settings()` is the canonical factory for the Desktop, ShareManager, and LanServer entry paths.
- `lan_share_last_successful_bind` and `lan_share_last_successful_auth` record only the last successfully started bind/effective-auth posture; they never contain passwords, hashes, access keys, or tokens. A failed settings commit restores the previous in-memory history and leaves the next start fail-safe.
- A cancelled start request leaves a previously persisted acknowledgement intact; it does not mean “revoke historical trust.”

The service gate, historical posture wiring, and first-share confirmation/write-back skeleton are delivered as a partial slice; GUI visual acceptance, version-expiry guidance, cross-restart UI evidence, and final product copy remain pending in the Desktop UI workstream.

## Rate Limiting

滑窗实现(security.py,每 IP 时间戳列表截头,非桶计数):显式无锁,契约=仅事件循环线程访问。

| Limiter | 预算 | 范围 |
|---------|------|------|
| `AuthRateLimiter`(auth_strict) | 10 attempts/300s | `/api/auth/login`、`/api/auth/register`、`/api/auth/verify_key` + 任意 `/api/shares/{id}/verify` 结尾路径（历史：~~`/api/auth/seller-login`、`/api/shop/auth/login`~~ 已随 ADR 0005 剥离） |
| browse 档 | 600 req/60s | 浏览类端点(`_BROWSE_RATE` 策略) |
| `RateLimiter`(general) | `_LanServerImpl` 默认 100/60s;`ShareManager` 默认 1000/60s | 其余非浏览路径;**未知/未声明路由 = required+general(fail-closed)** |
| 分享密码锁定(服务层) | 5 failures / 60s 冷却 | 每 share_id **进程内**失败计数(`ShareService.password_attempt_blocked`),429 + Retry-After;**重启即清零,多进程各自计数** |
| IP 黑名单/白名单 | settings / 配置 | `request.remote` 为空 → 400 拒绝(不共用 "unknown" 桶) |

**隧道模式(Cloudflare)**:限流身份键在访客签名 cookie 有效时变为 `tunnel:<client_id>`(按访客隔离桶);无 cookie 访客共享 loopback 桶;拒绝响应**不发**新 cookie(防身份农场)。成功响应附 `X-RateLimit-Remaining`。

429 响应的 `Retry-After` 按限流器窗口动态计算(`RateLimiter.retry_after(ip)`),不再硬编码。

## Password Storage

All passwords use PBKDF2-SHA256. **当前格式为自描述 `pbkdf2_sha256$iterations$salt$key`**(verify 从哈希字符串重放 iterations,不读模块常量,因此跨成本兼容):
- Passwords: **600,000 iterations**(OWASP 2023 现行;`PASSWORD_ITERATIONS`)
- Legacy 口令格式 `salt_hex:key_hex` 按 `LEGACY_PASSWORD_ITERATIONS=100,000` 重放(`needs_password_rehash` 迁移)
- Access keys: 50,000 iterations(`KEY_ITERATIONS`,仍为 `salt_hex:key_hex`)
- `is_password_hash()` 两种格式都识别
- Share passwords: minimum **8 characters**(`ShareService.validate_password`);`domain.auth.validate_password_strength` 提供完整强度规则(8-128 位 + 4 类字符 + 弱密码黑名单≈40 条)

> 2026-08-27 修正:此前版本误写为"salt_hex:key_hex / 100,000 iterations";`domain/auth.py` 自 600k 迁移后格式与迭代数均已变化。

## Crypto Layer

All pure crypto functions (hashing, token generation/verification) live in `AssetsManager.domain.auth`. The LAN layer re-exports them for backward compatibility. `AuthService` and `ShareService` import crypto from `domain.auth` and DB operations from `lan.auth`; both services are Runtime-owned and use the same session DB connection and secret. Their tables are initialized idempotently during Runtime creation within the session operation lease, rather than being owned by LAN start.

## Cookie Settings

| Cookie | 用途 | Path | Max-Age |
|--------|------|------|---------|
| `lan_token` | 主认证（24h） | `/` | 86400 |
| `share_token` | 分享作用域（1h） | `/api/shares/{id}` | 3600 |
| `am_quota_id` | 匿名免费配额身份（30d，HMAC 签名） | `/` | 2592000 |
| ~~`seller_session`~~ | ~~卖家会话（12h，内存验证）~~ | ~~`/`~~ | ADR 0005 剥离 |
| ~~`shop_cart_token` / `shop_wishlist_token`~~ | ~~买家 owner（365d）~~ | ~~`/`~~ | ADR 0005 剥离 |
| ~~`shop_order_receipt_{order_id}`~~ | ~~订单回执（30d，HttpOnly）~~ | ~~`/api/shop`~~ | ADR 0005 剥离 |
| ~~`shop_store_visit`~~ | ~~商店访问（24h）~~ | ~~`/api/shop`~~ | ADR 0005 剥离 |

全部 `httponly=True`、`samesite=Lax`；敏感 cookie 视 TLS 状态条件加 `secure`。

## Known Gaps(2026-08-27 实测,追踪于 docs/overview-2026-08-27.md §19)

- `/api/stats` 仅要求认证、无权限检查(任一认证 principal 含 guest 可读连接/请求/字节/uptime;system.py:135-144,未被测试锁住)。
- 读路由(browse/preview/download/admin 读)只有 handler 级守卫,无声明能力,中间件对空能力元组直接放行(authorization.py:66-67);写路由 55 条已全部声明(capabilities 门)。
- cloudflared 供应链:`tunnel.py` 下载用 `releases/latest`(**无版本 pin**)、仅 `--version` 冒烟(**无 SHA-256 校验**);PATH/内置 binary 完全跳过校验;未用 `--no-autoupdate`。
- verify_user_token 事件循环内同步 DB 查询(仅 PBKDF2 offload);user token 校验有 5s 进程内缓存(admin 降权 ≤5s 窗口旧令牌仍有效)。
- 分享密码锁定与卖家会话均为进程内状态(重启/多进程绕过)。

## Tests

Tests in `tests/lan/test_lan_api.py` cover path traversal, rate limiting, auth middleware, share scoping, token verification, and password hash compatibility. Any counts recorded in migration/architecture documents are historical snapshots until the final suite is rerun; this document intentionally does not claim a final test total.
