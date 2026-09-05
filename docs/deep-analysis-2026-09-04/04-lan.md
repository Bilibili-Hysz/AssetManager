# 04 · LAN 分享服务器层（AssetsManager/lan/）

> 状态：**DATED ANALYSIS（2026-09-04 实测快照）** · deep-analysis 系列之一，索引见 [README.md](README.md)。
> 方法：并行只读勘察代理全量扫描 `lan/`（22 个核心 .py + 22 个 routes 模块，共 12,624 行，wc -l 实测），关键机制逐文件深读，行号锚点为当前工作树。

---

## 1. 模块清单与规模实测

### 1.1 lan/ 根目录（22 个 .py；README 所称"核心 16 模块"为概数）

| 模块 | 行数 | 职责 |
|---|---|---|
| `__init__.py` | 329 | `LanServer` 外观门面：可选 aiohttp 探测、preflight 安全快照、tunnel 状态同步、`local_ui_token()` 签发 |
| `server.py` | **1204** | `_LanServerImpl` 主体：构造期 runtime 强校验、服务装配、metrics/auth 中间件、`_resolve_principal`、隧道门、热重载 |
| `server_lifecycle.py` | 633 | Mixin：stop/cleanup「单属主」协议、`_run` 状态机、`_shutdown`、runtime 生命周期适配器注册 |
| `api.py` | 377 | **唯一路由注册口** `setup_routes()`：72 条 `_add()` + 声明式 RoutePolicy + runtime 失效订阅 |
| `manager.py` | 557 | `ShareManager` 状态机（start/stop/status/tunnel 编排 + preflight 快照） |
| `ws.py` | **794** | `WebSocketManager`：50 连接上限、心跳、授权租约、1MB 帧截断、`revoke_authority` |
| `auth.py` | 37 | 纯 re-export：domain/auth 的 PBKDF2/HMAC/令牌函数 + `verify_token_async` |
| `principal.py` | 137 | `SessionPrincipal`/`Capabilities`：6 种身份 → 8 位能力映射 |
| `security.py` | 332 | `RateLimiter`/`AuthRateLimiter`/`IPBlacklist` + `create_security_middleware`（最外层中间件） |
| `route_policy.py` | 123 | `RoutePolicy(auth, rate_limit, capabilities)` 声明与查找；未知路由 fail-closed 默认 |
| `authorization.py` | 69 | L1 能力执行器 `enforce_capabilities`（403 / feature_disabled） |
| `token_revocations.py` | 171 | `TokenRevocationRegistry`：内存正缓存 + DB 持久化撤销（24h TTL / 10k 上限） |
| `path_guard.py` | 129 | `PathGuard`：C0 控制字符、NTFS ADS `:`、`..` 逃逸、TOCTOU 复检 |
| `safe_open.py` | 98 | 适配 `core.file_snapshot` 的 final-open 快照读取 |
| `scanner.py` | 146 | `DirectoryScanner` 后台全库扫描 + 搜索 |
| `tunnel.py` | 410 | `TunnelManager`：cloudflared 子进程、SHA-256 供应链校验、URL 正则提取 |
| `guarded_tunnel.py` | 29 | `_GuardedTunnel`：强制所有隧道变更过 owner 的 auth 门 |
| `tunnel_identity.py` | 106 | 隧道访客签名 cookie（`am_quota_id`，`v1.<32hex>.<HMAC>`） |
| `runtime_validation.py` | 178 | 构造期 runtime/session/服务绑定六重校验 + `_derive_local_ui_auth_secret` |
| `dto.py` | 400 | 响应 DTO（含 `RuntimeCursorResponse` epoch/revision） |
| `utils.py` | 168 | `get_local_ip`、`generate_auth_token`、`get_auth_headers` |
| `mcp_server.py` | 411 | `/mcp` 只读 MCP 端点（lan_mcp_token 空时 404 隐身） |

### 1.2 routes/ 22 模块（4 个共享私有模块 + 18 个业务模块）

| 模块 | 行数 | 端点数 | 职责 |
|---|---|---|---|
| `_helpers.py` | 752 | — | 服务定位器、PathGuard 包装、cookie、ZIP、ETag、模糊门、`require_*` 系 |
| `_errors.py` | 217 | — | `error_response` JSON 契约 + `error_contract_middleware`（最内层） |
| `_resource_urls.py` | 126 | — | 项目→LAN URL 投影（thumbnail/download/image URL） |
| `_telemetry.py` | 59 | — | `record_route_event` 性能事件单点 |
| `pages.py` | 51 | 7 | SPA 壳路由（`/`、`/browse`、`/detail`、`/login`、`/gallery`×3） |
| `auth.py` | 231 | 5 | 登录/注册/verify_key/登出（撤销+WS 驱逐）/me |
| `users.py` | 129 | 8 | 用户管理/邀请码/活动/在线（全部 admin） |
| `shares.py` | 419 | 8 | 分享链接 CRUD + 公开验证/下载/预览/info |
| `downloads.py` | 424 | 2 | 单/批量下载（100 路径、500MB、免费配额） |
| `files.py` | 271 | 2 | 文件列表/目录摘要（browse） |
| `metadata.py` | 452 | 8 | meta/notes/rating/search/home/tree/projects/project_detail |
| `collections.py` | 359 | 8 | 用户收藏集 CRUD + members + evaluate |
| `favorites.py` | 122 | 3 | 收藏增删查 |
| `tags.py` | 144 | 5 | 标签 CRUD（写=admin_tags） |
| `gallery.py` | 137 | 3 | 画廊 home/collection/resolve（重 IO 全 offload） |
| `thumbnails.py` | 484 | 2 | 单/批量缩略图（Pillow verify、模糊、ETag、413 门） |
| `image.py` | 287 | 1 | `/api/image` 原图预览（verify 内容门 + blur 门） |
| `quicksearch.py` | 98 | 1 | 快速搜索（256 字符查询上限） |
| `quota.py` | 315 | 1 | `/api/quota` 访客免费下载配额（签名 cookie 身份） |
| `sequence.py` | 69 | 1 | 帧序列邻居查询 |
| `system.py` | 174 | 4 | info/tunnel_status/stats/revision 游标 |
| `websocket.py` | 247 | 1 | `/ws` 握手 + per-kind 授权验证器 |

路由总数实测：`api.py` 中 `_add()` 共 **72 条** + `add_static` 1 条（`/assets`）+ 3 处方法级补充 declare——与 README「72 条路由」一致。

### 1.3 商城路由现状（ADR 0005 结论）

- `/api/shop/*` 54 条**已全部移除**：`grep api/shop` 在 `lan/` 内零命中；`routes/shop/` 目录、seller 相关模块均不存在。
- ADR 0005（`docs/adr/0005-commerce-extraction.md`）：2026-08-30 接受剥离，运行时代码删除，但 **13 个商城 DB 迁移 + schema 表刻意保留**（迁移链锁定，删除会毁老库升级），形成无害孤儿表。
- 残留：`docs/lan-security.md:40,71,104-106` 仍描述 seller/shop 路由与 cookie——**文档漂移**，代码已不在。

---

## 2. server.py 深读（_LanServerImpl）

### 2.1 构造期与 Runtime 强绑定

- `lan/__init__.py:56`：`LanServer(runtime=None)` 直接 `raise TypeError`——**构造强制 runtime=**，无 library_root 参数。
- `server.py:77-81`：session 为 None / 已关闭 → ValueError。
- `server.py:246-252` + `runtime_validation.py:72-118`：`_validate_runtime_service_bindings` 逐一核对 metadata/tag/thumbnail/project/search 服务的连接 provider 与 session 绑定。
- `server.py:283-312`：通过 `session._publish_while_live` 在 session 存活窗口内**原子发布** `_library_root/_db_conn/_token_secret/_auth_service/_share_service/services`——构造完成即绑定完成；无该钩子时回退再检查 `is_closed` 后发布，**仍是 fail-closed**。
- `server.py:317-332` `_ensure_zip_executor`：stop→start 循环中重建 ZIP 执行器（H1 回归修复）。

### 2.2 启动生命周期（start → _run → _startup）

`start()`（`server.py:403-506`）：
1. **SecurityPreflight 门**（:411-424）：`share_state != "local_active"` 拒绝启动并返回快照。
2. `_lifecycle_lock` 状态机（:425-464）：stopping/残留 stop 预约 → RuntimeError；生成新 `_lifecycle_generation`；`_build_app()` 重建。
3. 守护线程 `_run`（`server_lifecycle.py:396-481`）：新事件循环 → `_startup()`；**BaseException 全捕获**，失败时无人持清理权则自查 `_run_cleanup_attempt`，否则置标记让 stop 属主补重试。
4. 失败路径等 `_cleanup_started_event`（8s）+ join（8s），`cleanup_complete` 才置 stopped。

`_startup()`（`server.py:893-1004`）：TLS **fail-closed**（只给 cert 或只给 key 直接 ValueError，绝不降级 HTTP，:908-915）；port=0 时从 socket 读实际端口（:931-934）；`_register_runtime_adapter()`——runtime 必须 retain LAN 生命周期适配器否则 RuntimeError 并回滚站点（:950-988）；先启动 scanner 后 prewarm 画廊（prewarm 线程先等 scanner 最多 300s，避免 Windows/Defender 下双全库遍历互踩 IO，:995-1046）。

### 2.3 停止生命周期（单属主 cleanup 协议）

`server_lifecycle.py:73-312 stop()`：先停隧道 → 锁内状态机（活线程必须有 loop，否则 raise）；**cleanup-attempt 状态机**（idle/running/succeeded/failed + owner），失败且未用重试 → `_reset_cleanup_attempt_locked("stop-retry")`（每次失败只允许一次重试）；attempt event 跨线程权威发布（先发布终态再让 future done）。`_shutdown()`（:505-569）顺序：scanner.stop → gallery.close（带界 join 预热线程 10s）→ ZIP executor shutdown(cancel_futures=True) → stop_runtime_realtime → ws_manager.close_all → site.stop → runner.cleanup；任何异常 → `cleanup_complete=False` 并 raise（可重试）。

### 2.4 与桌面端边界（ports.py，G2 规则）

- `lan/ports.py:39-50 build_lan_server()` 是**唯一生产装配点**；`ports.py:15-36 LanDesktopAdapter` 懒 import 实现 `ShareSettingsPort`。
- 桌面 widget 只 import `application/desktop_ports` 协议类型，**从不直接 import `AssetsManager.lan`**。
- `__init__.py:81-138 LanServer.start()`：start 前后再各做一次 preflight 快照，post-start 校验失败会**回滚 stop**（回滚失败显式上报 `rollback_failed`）。

---

## 3. 认证体系

### 3.1 六种 Principal（principal.py:36-137）

| kind | role | 能力 | 来源 |
|---|---|---|---|
| `user`(admin) | admin | 全 8 项 | DB 用户 role=admin |
| `user`(user) | user | browse/preview/download/realtime | :124-125 |
| `user`(viewer/自注册默认) | user | 仅 browse/preview/realtime，**无 download** | :127 |
| `password`/`access_key`/`local_ui` | admin | 全能力 | 单一密码/访问密钥/桌面 UI 令牌 :131-132 |
| `share` | guest | 访客能力包（`lan_guest_*` 设置，download 默认 False） | :133-134, 93-99 |
| `guest` | guest（未认证） | 同访客包 | — |

`principal.py:105-109`：`upload` 能力已退役（恒 False），字段保留以维持公共形状。

### 3.2 HMAC 令牌（domain/auth.py，`ts.nonce.sig` 家族）

- 密码令牌（:146-156）：`{ts}.{nonce}.{sig}`，sig = HMAC-SHA256(password_hash, ...)[:32]，nonce=4 字节 hex——**同密码两次签发令牌不同**。
- 本地 UI 令牌（:183-203）、用户令牌（:209-265，消息含 uid+username+role，验证时回查用户仍 active）、分享令牌（:271-304，消息含 share_id）。
- PBKDF2：访问密钥 50k 迭代；密码 600k 迭代（OWASP 2023），legacy 100k 兼容验证 + `needs_password_rehash` 验证成功后重印（:55-57）。
- `local_ui_auth_secret` 派生（`runtime_validation.py:47-69`）：`HMAC-SHA256(token_secret, b"lan-local-ui-auth-v1\0" + json(认证配置))`——**密钥绑定认证配置，改密码即轮换**。
- 弱口令黑名单 + 复杂度要求（≥8 字符，:310-361）。

### 3.3 令牌撤销（fail-closed 三层）

`token_revocations.py`：内存表（sha256 → 过期时间，TTL 24h、上限 10k）；**持久化是权威**——`revoke_auth_token`（:45-73）先写 DB，写失败 → 进程内仍拒绝该 token 并抛 `TokenRevocationPersistenceError`（logout 路由据此 503 让客户端重试，`routes/auth.py:204-216`——**绝不留下已认证 cookie**）。`is_auth_token_revoked`（:75-103）：首次持久化读取未成功前一律 True（拒绝），DB 查询失败也 True；内存 miss 必须回查持久层（多进程共享库 DB 场景）。登出同时按 token 摘要驱逐在线 WS socket（`ws.py:467-479`）。

### 3.4 暴力破解锁定

- 登录/注册/verify_key/share-verify：`AuthRateLimiter` 10 次/300s/IP（`server.py:122`）。
- 分享密码：`ShareService.MAX_PASSWORD_FAILURES=5`、`PASSWORD_COOLDOWN_SECONDS=60`（`application/share_service.py:39-40`）——**5 次失败锁 60s**，滑动窗口，进程内 per-share（:349-393，机会性全局清扫防内存膨胀）；成功/失败都跑完整 PBKDF2（无时序泄漏）。

### 3.5 邀请码注册（fail-closed）

`AuthService.register_user`（`application/auth_service.py:335-363`）：存在任何 active 邀请码时必须携带，`insert_user_with_invite` 原子消费；`has_active_invite_codes(raise_on_error=True)` 查询失败按「有码」处理（fail-closed，不放开无码注册）。

### 3.6 凭据链（server.py:1095-1152，单一实现共享）

顺序：**撤销检查 → access_key → local_ui → user token → password**；user-token DB 查询失败降级为「无凭据」（required 路由 401 而非 500）。凭据只从 `Authorization: Bearer` 或 `lan_token` cookie 读取（`_helpers.py:537-551`），**明确禁用查询串凭据**——防日志/Referer 泄漏（WS 路由同样拒绝，`routes/websocket.py:139-142`）。

---

## 4. 中间件链与速率档位

### 4.1 顺序实测（server.py:361）

```python
web.Application(middlewares=[security_mw, self._metrics_middleware,
                              self._auth_middleware, error_contract_middleware])
```

**security → metrics → auth → error-contract(innermost) → handler**，与 README 一致，另加最内层 `error_contract_middleware`（统一 JSON 错误形状，5xx 不泄漏异常文本）。

### 4.2 限流四档（route_policy.py:26 + server.py:114-123 + security.py:180-323）

| 档位 | 预算 | 覆盖 |
|---|---|---|
| `general` | 100/60s/IP（默认） | 未声明的其余路由 |
| `browse` | **600/60s/IP**（独立限速器） | gallery/search/tree/home/info/quota/tags 等重公开面 |
| `auth_strict` | 10/300s/IP | login/register/verify_key + share verify |
| `skip` | 不限 | image/thumbnails/revision/stats/ws/static 轮询面 |

LRU 淘汰（10k IP 上限）；`X-RateLimit-Remaining` + `Retry-After` 头。**未知/404 路由 fail-closed**：无策略 → required + general（`route_policy.py:99-109`）。IP 归一化：IPv4-mapped IPv6 折叠、`::1`→127.0.0.1。

### 4.3 IP 黑白名单与隧道访客隔离

- 黑名单永远生效；白名单只约束直连——隧道激活时 loopback 放行（`security.py:265-276` + `server.py:381-386`）。
- 隧道模式按签名 cookie `am_quota_id` 把限流桶从 IP 换成 `tunnel:<client_id>`（`security.py:209-221`），**防一个访客的失败锁死所有隧道用户**；无 cookie 的新访客先落共享 loopback 桶，**只有成功响应才附新 cookie**（:227-261）——杜绝「刷失败换新身份」绕限。

---

## 5. WebSocket 体系

### 5.1 WebSocketManager（ws.py）

- `MAX_WS_CONNECTIONS=50`（:13），超限 close 1013；心跳 30s + ping 超时 10s + PONG 回调（W7 注释承认慢回环会误杀健康连接——fail-closed 权衡）；心跳周期内复验 `authorize` 回调，失权即 evict。
- **1MB 帧截断**（`MAX_BROADCAST_FRAME_BYTES`，:17）：超限帧带 `paths` 列表二分截断到 95% 预算（:572-619），否则丢弃并计数（`dropped/truncated_broadcast_frames` 观测）。
- **授权租约模型**：per-authority 锁 + transition 代数（:20-55, 105-225），`revoke_authority`（:375-410）把「改权威状态」和「驱逐 socket」合成一个原子边界；W5/W6/W8 系列注释记录了防旧心跳任务复活、权威表增长、慢 peer 5s 超时等已知权衡。
- `close_all`（:709-794）：先关接纳位、逐权威拿锁、清空状态后关 socket——**服务器 teardown 即凭据轮换边界**。

### 5.2 epoch+revision 失效推送协议

- 库游标：`runtime.epoch`（uuid，`application/runtime.py:23`）+ `revision`（单调递增，:88-99）。
- **/api/revision 权威游标**（`routes/system.py:167-174`）：要求 principal + `realtime` 能力。
- WS 准入即推基线 `runtime_ready`，注册后再读一次游标作为「准入屏障」，变了补发——消除注册与广播快照间的竞态（`routes/websocket.py:151-233`）。
- runtime 事件订阅 → `projection_invalidated` 广播（`api.py:309-363`）：跨线程 `run_coroutine_threadsafe` + teardown 先停派发再关订阅。
- per-principal 授权验证器：user 每 ping 重查 DB；access_key/password 每次重验 PBKDF2（**全部 to_thread**，绝不跑事件循环）；`reload_settings` 轮换认证配置时显式驱逐 local_ui WS（`server.py:852-874`）。

---

## 6. 路径安全（PathGuard）

`path_guard.py`：C0 控制字符与 Windows NTFS ADS `:` 一律拒（`file.txt:Zone.Identifier` 可过 is_relative_to 但开的是另一条流，专门堵这个，:54, :110-117）；反斜杠归一 + `(root/cleaned).resolve()` + `is_relative_to` 校验；`assert_under_root`（:72-84）**解析后二次包含复检**——所有路由 open 前的 TOCTOU 防线。所有文件读走 `safe_open.read_safe_file` → `core.file_snapshot`（root 约束 + expected_identity final-open 快照，`safe_open.py:54-67`），中途文件被换 → `ThumbnailSourceChangedError` → 409。ZIP 构建跳过 symlink、隐藏文件，逐 entry `assert_under_root`（`_helpers.py:650-698`）。

---

## 7. Cloudflare 隧道

- **强认证前置**：`server.py:730-746 start_tunnel` 在认证未启用时拒绝（`_tunnel_start_block_reason="authentication_required"`），日志明示 "never expose an unauthenticated LAN server through a tunnel"；`guarded_tunnel.py:11-29` 强制一切变更过 owner 的 auth 门。
- **供应链 fail-closed**（`tunnel.py:36-105`）：cloudflared 版本钉死 `2024.8.3`（绝不解析 latest）；下载抓 `.sha256` sidecar 校验，缺校验或摘要不匹配即丢弃；`--version` 冒烟。
- 子进程：`--no-autoupdate --url http://127.0.0.1:{port}`；stderr UTF-8 读线程正则提 `trycloudflare.com` URL（:206-214 边界锚定防 `x.trycloudflare.com.evil.io` 前后缀伪造）；monitor 线程监测意外退出；stop 幂等（terminate→kill 双段）。

---

## 8. 缩略图/图片服务

- **Pillow verify 内容门**（`routes/image.py:45-73`）：`Image.verify()` 后按实际 format 白名单映射 MIME，失败一律 404（"Image parsing is a security gate: fail closed"）；SVG 刻意排除（主动 XML 文档可带脚本，:31-33）；RAW/PSD 走 decoder registry，成功解码即验证，绝不回退原字节。
- **模糊门**（`_helpers.py:570-647`）：blur 资产只出处理后的 WEBP，**处理失败=500 绝不回原图**；模糊输出强制 `Cache-Control: private, no-store`；ETag 把 blur 决策绑进 validator（304 永不掩盖新模糊内容，`image.py:82-96`）。
- 缩略图（`routes/thumbnails.py`）：size 钳 16-2048；批量 ≤100 路径 + 413 预算门；音频波形/调色板派生注册。
- 缓存策略三档（`_helpers.py:50-69`）：模糊/JSON `no-store`；媒体 `private, max-age=3600`+ETag；仅公开画廊原图 `public`——**多用户库绝不共享代理缓存**。

---

## 9. 分享链接体系（routes/shares.py + share_service.py）

- **密码 ≥8**（`share_service.py:139-153`，≤128，刻意不强制复杂度——注释说明短而强的共享秘密仍可用）；创建即 PBKDF2 哈希存储。
- **限时** `expires_hours` 1–8760；到期/超额 → **410 Gone**（`routes/shares.py:203-204, 238-239, 373-374`）。
- **限次** `max_downloads` 1–10000；下载响应字节就绪后才 `increment_download`，DB 原子递增——并发竞争表现为 429 而非超卖（:330-345）。
- **撤销即时阻断**：`validate_access`（存在性/密码令牌/过期/限额/路径范围）+ `_resolve_share_target`（PathGuard + assert_under_root + share.paths 范围）；**信息折叠**：未知/过期/超额/范围外统一 404（:301-306），仅缺密码保留 401 引导 verify。
- 预览默认允许但可关（`allow_preview`，仅限安全图片扩展名，排除 SVG）；cookie `share_token` 作用域钉在 `/api/shares/{id}`；API 客户端可 `X-AssetsManager-API-Client: 1` 换 body 内 token。

---

## 10. 安全机制清单（32 项，file:line 锚点）

| # | 机制 | 锚点 |
|---|---|---|
| 1 | 构造强制 live runtime + 六重绑定校验 | server.py:60-81, 198-252; runtime_validation.py:99-118 |
| 2 | 启动/停止 preflight 门 | server.py:411-424; __init__.py:88-138 |
| 3 | 中间件链 security→metrics→auth→error-contract | server.py:361 |
| 4 | 未知路由 fail-closed 默认 | route_policy.py:99-109 |
| 5 | 声明式能力门（写路由必须声明 capabilities） | api.py:141-178; authorization.py:41-69 |
| 6 | 速率四档 + IP 归一 + LRU | security.py:62-124, 180-323; server.py:117-123 |
| 7 | 隧道访客签名身份隔离 + 拒绝不发 cookie | security.py:209-261, 326-330; tunnel_identity.py:25-101 |
| 8 | 查询串凭据禁用 | _helpers.py:537-551; routes/websocket.py:139-142 |
| 9 | HMAC 令牌 nonce + compare_digest | domain/auth.py:146-304 |
| 10 | local_ui 密钥绑定认证配置 + WS 驱逐 | runtime_validation.py:47-69; server.py:800-874 |
| 11 | 令牌撤销三层 fail-closed | token_revocations.py:45-146; routes/auth.py:186-216 |
| 12 | 登出撤销失败 503 强制重试 | routes/auth.py:204-216 |
| 13 | 分享密码 5 失败锁 60s（滑动窗口） | share_service.py:39-40, 349-393 |
| 14 | 邀请码 fail-closed | auth_service.py:350-363 |
| 15 | PathGuard：控制字符/NTFS ADS/`..`/symlink | path_guard.py:54-118, 72-84 |
| 16 | final-open 快照 + expected_identity（TOCTOU） | safe_open.py:54-67; routes/thumbnails.py:156, 305-311 |
| 17 | 隧道强认证前置 | server.py:730-751; guarded_tunnel.py:11-29 |
| 18 | cloudflared 版本钉死 + SHA-256 校验 | tunnel.py:36-46, 59-105 |
| 19 | TLS fail-closed | server.py:908-915 |
| 20 | Pillow verify 内容门 + SVG 排除 | routes/image.py:45-73, 31-33 |
| 21 | 模糊门不变量：失败=500 绝不回原图 + no-store | _helpers.py:585-647; image.py:128-136 |
| 22 | ETag 绑 blur 决策 | image.py:82-96, 251-263; thumbnails.py:137-151 |
| 23 | 分享 410/404 信息折叠 | routes/shares.py:301-306 |
| 24 | 下载限额原子递增 | routes/shares.py:330-345; downloads.py:23-24 |
| 25 | WS 50 连接/30s 心跳/1MB 截断/authority 租约 | ws.py:13-17, 105-225, 375-410, 572-619 |
| 26 | epoch+revision 游标 + 准入屏障补发 | routes/websocket.py:151-233; api.py:309-363 |
| 27 | 用户停用经 revoke_authority 原子驱逐 | routes/users.py:37-40 |
| 28 | MCP 端点空 token 404 隐身 + 恒时比较 | mcp_server.py:327-334 |
| 29 | 免费配额签名 cookie 身份 | routes/quota.py:70-104; _helpers.py:351-366 |
| 30 | has_active_users 失败缓存为 True（fail-closed） | server.py:1048-1077 |
| 31 | 5xx 不泄漏异常文本 | routes/_errors.py:132-140 |
| 32 | ZIP 防 symlink/隐藏/越根 entry | _helpers.py:650-698 |

---

## 11. 弱点与技术债

**架构层面**：
1. **读路由能力单层**（overview §已自认）：写面已全部声明 capabilities（api.py），但读面（`/api/meta`、`/api/download`、`/api/auth/me`、share 公开 GET 等）大多靠 handler 级 `require_permission`——handler 忘写守卫即 fail-open，属纵深单层。
2. **`_revoked_tokens` 并发契约靠注释维持**（`server.py:187-191` 自认）：内存撤销表「只许事件循环线程读写」但 `is_auth_token_revoked` 经 `to_thread` 在 worker 线程执行——靠独立 `_state_lock` 保护成立，属脆弱设计。
3. **share 密码锁定是进程内存**（`share_service.py:349` 自认 "In-process per-share guard"）：多进程共享库 DB 场景不共享；服务器重启清零；滑窗清扫只机会性执行。
4. **限流 keyed by IP**：NAT 多用户共享一个预算（`security.py:3-5` 注释承认的权衡）；无全局限流。
5. **`/api/stats` 限流=skip**（`api.py:291`）：admin 可被无限轮询。
6. **`_INFO_COUNT_CACHE` 无锁**（`routes/system.py:30-66`）：最坏多算一次遍历的轻微竞态。
7. **文档漂移**：`docs/lan-security.md` 仍列 seller/shop 路由（代码已剥离）；`overview-2026-08-27.md` 的 server.py=1678 行已过时（实测 1204）。
8. **孤儿迁移链**：13 个商城 DB 迁移保留（ADR 0005 有意），无写入方——明示受控债。
9. **ShareManager 与 LanServer 双门面**：preflight 逻辑在 `__init__.py:88-138` 与 `manager.py:100-135` 各写一遍，须同步演化。
10. `routes/shares.py:146,185` 直接读 `lan._port` 私有字段拼 URL（构造时快照，可接受）。
11. 登录失败无全局限失败计数锁定（只有 IP 级 auth_strict 10/300s + 活动日志可见性）。
12. `security.py:12-15` 三个限流器**刻意不加锁**、只许事件循环线程触碰——契约靠注释，新调用点易引入竞态。

---

## 12. 总评

该 LAN 子系统是整个代码库中**安全工程密度最高**的部分：fail-closed 语义贯穿（撤销读取失败即拒、模糊处理失败即 500、TLS 缺一半即拒、未知路由即 required、邀请码查询失败即关闭注册、cloudflared 校验失败即弃用）；「声明式策略 + 中间件执行 + handler 双保险」的三层授权结构清晰；WS 管理器对撤销/轮换/teardown 的并发边界处理（authority lease + transition generation + 单属主 cleanup）达到桌面级应用中罕见的严谨度。主要债务集中在读路由单层守卫、进程内存态的分享密码锁定、以及 ADR 0005 剥离后的文档/迁移链残留——三者均已被项目自身文档承认，属「已知、受控」的技术债而非潜伏缺陷。

---

**关联阅读**：桌面端如何启动/停止本服务器 → [08-entry-and-window-assembly.md](08-entry-and-window-assembly.md)；认证服务的应用层实现 → [03-application.md](03-application.md)；前端如何消费 WS/游标协议 → [05-webui.md](05-webui.md)。
