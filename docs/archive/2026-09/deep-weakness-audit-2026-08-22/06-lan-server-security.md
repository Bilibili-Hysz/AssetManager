# 06 · LAN/Web 服务器安全与正确性审计（2026-08-22）

**范围**：`AssetsManager/lan/` 全部模块 + 23 个路由模块 + `shop/` 子包，按调用链下沉到 domain/auth、application 的 share/order/shop_buyer/seller_auth/auth_service 及相关 repository 的关键路径。
**基线**：commit `5fbf930` 脏工作树。授权性质：用户自有代码的防御性渗透式代码审查，仅做代码推演，未实际运行攻击。
**注**：历史审查报告提到的 `routes/model_preview.py` 在当前代码库中已不存在。

## 总体评估

LAN 服务器的安全工程成熟度明显高于同类个人项目：中间件顺序为 security → metrics → auth 且认证 fail-closed（server.py:307, 1526-1657）；路由策略在 api.py 注册时声明、经 route_policy.py 回读，未匹配路由回落到 fail-closed 默认策略；所有文件服务入口（downloads/thumbnails/image/shares/shop media/delivery）都收敛到 `PathGuard.resolve` 或 `assert_under_root`，且对 NUL/控制字符、Windows ADS 冒号、绝对路径拼接、symlink 解析逃逸均有防护；所有 HMAC/PBKDF2 比较使用 `hmac.compare_digest`（domain/auth.py:45,125,178,202,262,303）；错误契约对 5xx 统一脱敏；商城的订单状态机 CAS、投递配额 CAS、幂等结账、rotate 同事务吊销旧令牌等不变量实现正确。SQL 全部参数化，routes 层未发现任何拼接 SQL。

**未发现 P0（无可直接利用的认证绕过/路径遍历/RCE）**。主要风险集中在三类：(1) Cloudflare 隧道使全部公网流量共享 `127.0.0.1` 速率桶，导致认证端点可被单点打挂（可用性）；(2) 密码模式令牌直接以存储的 PBKDF2 哈希作为 HMAC 密钥，DB 泄漏即可伪造管理员令牌；(3) 用户模式下邀请码为空时注册完全开放，经隧道等于向全互联网开放 viewer 注册。另有若干声明式能力位与 handler 实际检查的方向性漂移（handler 有检查、声明缺失）——目前无漏洞，但削弱了 L1 声明层"handler 忘记守卫也不至于 fail-open"的设计意图。

## 主要发现（按严重度排序）

### [P1][速率限制] Cloudflare 隧道使全部公网访客共享 127.0.0.1 速率桶，认证端点可被单点全局锁死 ✓已复核
- 位置：`AssetsManager/lan/security.py:173`（`ip = _normalize_ip(request.remote)`）、`AssetsManager/lan/tunnel.py:202`（`--url http://127.0.0.1:{port}`）
- 证据：cloudflared 从回环地址连接本地服务器，因此隧道开启时所有公网请求的 `request.remote` 都是 `127.0.0.1`。三层限流全部按此键分桶：general（默认 100/min）、browse（600/min）、auth_strict（10 次/5 分钟）。`delivery.py:80-111` 的 claim 暴力限制同样键于 `request.remote`。
- 影响：【确认】任意公网攻击者发 10 次失败登录即可让**所有**公网用户在 5 分钟内无法登录/注册/verify_key（429）；单个重度用户可耗尽全体共享的 browse 预算。正面作用是限制不会被绕过（只会更严），但这是一条向公网暴露的认证 DoS 通道。注意 `routes/quota.py:135-193` 已用签名 Cookie 解决了同一问题（`am_quota_id`），说明该问题有现成修复模式。
- 建议：当隧道激活时改用与 quota 相同的签名匿名 Cookie（或 cloudflared 注入的 `Cf-Connecting-Ip`，仅在确认来自回环时信任）作为限流身份键；auth_strict 桶至少应改为"每回环桶 + 全局第二桶"双层。

### [P2][令牌设计] 密码模式令牌以存储的 PBKDF2 哈希本身作为 HMAC 密钥（哈希即凭证）
- 位置：`domain/auth.py:146-156`（`generate_token(password_hash)` 直接用 `password_hash.encode()` 作 key）、`:159-178`（verify 同 key）；签发点 `application/auth_service.py:188-189`、`lan/routes/auth.py:43-44`
- 证据：`sig = hmac.new(password_hash.encode(), message.encode(), ...)[:32]`。user token / local_ui token 的密钥分别是进程内存随机 `token_secret`（bootstrap.py:627）和其 HMAC 派生值（runtime_validation.py:47-69），均不落盘；唯独 password 模式令牌的签名密钥就是 `users`/设置中持久化的 PBKDF2 哈希。
- 影响：【确认，需 DB 文件泄漏条件】拿到库 SQLite 文件（备份、同步盘、其他进程读文件）的攻击者无需破解密码即可本地 `generate_token(hash)` 伪造 24h 有效的 admin 令牌（password principal 拥有全部能力，principal.py:131-132），且撤销仅覆盖进程内/DB 撤销表。
- 建议：令牌密钥改为 `HKDF(password_hash, "lan-token-v2")` 或复用 `local_ui_auth_secret` 的派生方式（以内存 `token_secret` 为 key、密码哈希为消息），使落盘哈希不能直接充当签名密钥。

### [P2][认证边界] 用户模式下无邀请码时注册完全开放，viewer（browse/preview/realtime）可被任意人自注册
- 位置：`lan/routes/auth.py:53-76`（`/api/auth/register`，policy=public+auth_strict）；`application/auth_service.py:348-353`（仅当存在活跃邀请码时才要求）；`auth_repository.py:262-263`（默认 `role="viewer"`）；`principal.py:110,127-128`（viewer = browse+preview+realtime）
- 证据：`if not invite_code and has_active_codes: return None, "Invite code is required"`——反向即"无邀请码 ⇒ 无需邀请码"。注册端点是 public 且经隧道可达。
- 影响：【确认】owner 选择 user 模式后，若从未生成邀请码，任何互联网访客可注册 viewer 账号浏览/预览整个库并使用 WebSocket 实时通道。owner 对"user 模式=受控访问"的预期可能被打破。
- 建议：user 模式下默认要求邀请码（把"存在邀请码才要求"反转为"设置项默认关闭开放注册"），或在 `/api/info` 中向 owner 明示开放注册状态。

### [P2][暴力破解] 分享密码锁与 claim 兑换均为"先检查后计数"，并发突发可突破 5 次/60s 上限
- 位置：`lan/routes/shares.py:236-248`（check `password_attempt_blocked` → verify → `record_password_failure`）；`application/share_service.py:349-385`；同型竞态：`lan/routes/shop/delivery.py:97-111,127-146`
- 证据：检查与计数之间无原子性：N 个并发请求都能在失败计数为 0 时通过 blocked 检查，各自完成 PBKDF2 验证后再记录失败。突发容量受限于服务器并发（数十至上百），之后进入 60s 锁定。
- 影响：【确认，受并发上限约束】对单个 share 每分钟可猜测的口令数约等于并发突发数 + 5，高于设计的 5 次；claim 兑换同理（叠加 auth_strict 每 IP 10/5min，经隧道又全部折叠为单桶）。
- 建议：在 `verify` 之前先原子地"预留"一次尝试（如 `record_password_failure` 移到验证前、成功时回滚），或对 verify 加 per-share 信号量串行化。

### [P2][供应链] cloudflared 自动下载无版本/哈希锁定，且"校验"即执行 ✓已复核
- 位置：`lan/tunnel.py:25`（`releases/latest/download`，可变指针）；`:58-70`（`_validate_cloudflared_binary` 仅 `--version` 冒烟）
- 证据：HTTPS + GitHub 信任链是唯一保障；无 pinned 版本、无 SHA-256、无签名验证；`--version` 本身就是执行下载来的 EXE。下载缓存于共享目录（`shared_dir()`），历史上无权限校验。
- 影响：【疑似，需 GitHub/CDN 或本机 MITM 前置条件】一旦 release 指针被替换或缓存目录被同机低权进程预置恶意二进制，将以当前用户权限执行任意代码。开发模式还会直接使用项目根目录预置二进制（:113-120），该文件不在版本校验范围内。
- 建议：pin 固定版本 + 内置 SHA-256；`os.replace` 前先核对哈希再执行；缓存目录写入后校验 ACL。

### [P2][能力声明漂移] 声明式能力层与 handler 守卫方向相反：多条敏感路由未声明能力位
- 位置：`lan/api.py:289`（`GET /api/download/{path}` 无 `_DOWNLOAD`，而 290 行 batch 有）；`api.py:322`（`GET /api/shares` 未声明 `manage_links`）；`api.py:310,318,320`（`/api/auth/me`、`/api/online-users`、`/api/invites` 仅默认 required，无 `admin_users`）；`api.py:320`（`/api/stats` 无任何能力）
- 证据：`authorization.py:57-94` 的设计意图是"handler 忘记守卫时中间件兜底"；但这些路由实际是 handler 内联检查（downloads.py:129、shares.py:158、users.py:10,84,121）在兜底中间件的缺位。
- 影响：【确认，当前无漏洞】防护单层化：未来重构删掉 handler 内联检查即变成静默 fail-open，且静态审计（声明表）会给出错误的安全感。
- 建议：补齐声明：download→`download`、list_shares→`manage_links`、me/online-users/invites(GET)→按需、stats→`settings`。

### [P2][信息泄露] `/api/stats` 无任何权限检查，向任意已认证主体（含 viewer、无认证模式下的任何人）暴露服务器统计
- 位置：`lan/routes/system.py:132-141`；注册 `api.py:320`（`_SKIP`：仅 skip 限流，auth=required，无能力位）
- 证据：handler 直接返回 `lan.status()`：connections、requests、bytes_transferred、uptime。
- 影响：【确认】低敏感（无路径/身份信息），但 viewer/无认证模式下可无限轮询（rate_limit=skip）做流量侧信道。`/api/tunnel/status`（admin）反而正确做了 `require_admin`。
- 建议：加 `require_admin` 或声明 `settings` 能力；skip 限流改为 browse 档。

### [P2][信息泄露] 分享端点 410/expired 状态泄漏，与 download 的 404 折叠策略不一致
- 位置：`lan/routes/shares.py:366-367`（preview 对过期返回 410）、`:228-229`（verify 同）、`:193-194`（delete 同）、`:404-409`（info 对带密码分享返回 `expired` 布尔）；对照 `:288-293`（download 明确折叠为 404）
- 证据：share id 为 10 位字母数字（share_service.py:446-449，约 62^10），不可枚举猜测；但曾经持有链接的人可区分"已过期/已删除/已达上限"，且 `to_public_dict()`（domain/share.py:73-92）向无密码分享的任意访问者返回 `created_by`（owner 显示名）与共享相对路径。
- 影响：【确认，低危】链接历史持有者可探测链接生命周期；owner 用户名经公开分享外泄。
- 建议：preview/verify/delete 统一折叠 404；`to_public_dict` 在公开上下文中去除 `created_by`。

### [P3][Cookie] 隧道场景下认证/卖家/收据 Cookie 均无 Secure 标志
- 位置：`lan/routes/_helpers.py:415-435`（`secure=lan.ssl_active`，本地 TLS 关闭时为 False）；`shop/_common.py:191-201`、`seller_auth.py:23-33`（`secure=request.secure`，aiohttp 不信任 X-Forwarded-Proto）
- 证据：经 cloudflared 隧道公网为 HTTPS，但本地 hop 是 HTTP，`ssl_active=False`、`request.secure=False`。
- 影响：【确认，低危】公网 URL 实际仅 HTTPS 可达，且本地 hop 在回环上；风险主要是浏览器将 Cookie 降级发送到同 host 的明文请求。HttpOnly/SameSite=Lax 均已正确设置。
- 建议：隧道激活时强制 `secure=True`。

### [P3][DoS] `_claim_failures` 与 `_password_failures` 键空间无界增长
- 位置：`lan/routes/shop/delivery.py:77-111`（仅按访问键修剪，键本身不清除）；`application/share_service.py:57,349-385`
- 证据：与 `RateLimiter`（有 `max_ips=10000` LRU 逐出，security.py:90-95）不同，这两个字典的 stale 键只有被再次访问才删除。
- 影响：海量唯一 IP / share id 的失败请求可缓慢膨胀内存（每键 ≤10 个 float）。
- 建议：周期性全局清扫或复用 RateLimiter 的 LRU 逐出。

### [P3][加固] 全站无 CSP / X-Frame-Options / HSTS
- 位置：`lan/server.py:297-311`（无全局头中间件）；`routes/pages.py`、`api.py:458-463`（SPA 与静态资源无 CSP）
- 证据：grep 全 lan/ 仅见 `X-Content-Type-Options: nosniff`（thumbnails/_helpers）。图片/缩略图路由已严格排除 SVG（image.py:26、shares.py:23），但 SPA 本身无 CSP。
- 影响：【确认，卫生】一旦前端出现 XSS，无纵深防御；SPA 可被 iframe 嵌套（clickjacking）。
- 建议：加 `on_response` 中间件输出 `Content-Security-Policy`（default-src 'self'）、`X-Frame-Options: DENY`、隧道场景 `Strict-Transport-Security`。

### [P3][侧信道] 用户名枚举时序差异（登录路径）
- 位置：`application/auth_service.py:197-207`（用户不存在时立即返回，不跑 PBKDF2；存在时跑 600k 轮）
- 证据：错误消息统一为 "Invalid username or password"，但耗时差异 ~百毫秒级。
- 影响：【确认，低危】可枚举有效用户名。share 密码验证（share_service.py:310-325）已做到两侧同代价，可借鉴。
- 建议：dummy-hash 等耗时。

### [P3][WebSocket] 非控制帧被静默忽略，连接保持开放
- 位置：`lan/routes/websocket.py:233-238`
- 证据：`async for msg in ws` 只处理 PING/PONG；TEXT/BINARY/连续分片被丢弃但不关闭。未启用 permessage-deflate（无解压炸弹），出站广播有 1MB 截断（ws.py:17,572-631），50 连接上限 + 心跳 30s + 慢消费者 5s 逐出（ws.py:660-700）都已到位。
- 影响：【确认，低危】客户端可无限流式发送 ≤4MB 帧持续消耗解析 CPU。
- 建议：收到非 PING/PONG 帧即 `close(1003)`。

### [P3][性能/阻塞] 每请求在事件循环上同步执行 `verify_user_token`（SQLite 查询）
- 位置：`lan/server.py:1646`（required 路径）、`:1571`（optional 路径）
- 证据：access_key（PBKDF2）与 password 验证均已 `to_thread`（:1633,1653），user token 验证仍同步；虽有短 TTL 用户缓存（auth_service.py:245-276），缓存 miss 时阻塞 loop。同样 `routes/websocket.py:62-68` 心跳周期内同步调用。
- 影响：【确认，性能】高并发/缓存冷时放大尾延迟；`_auth_middleware` 中的撤销检查每次 miss 也会走一次 `to_thread` DB 查询（token_revocations.py:94-102）。
- 建议：`asyncio.to_thread` 包装，或迁移到持久化撤销的正缓存 + 短 TTL 负缓存。

### [P3][兼容性] ZIP 成员名在 Linux 库上可携带反斜杠（受害端 Zip Slip 面）
- 位置：`lan/routes/_helpers.py:552-565`（`arc = os.path.join(arc_name, os.path.relpath(fp, target))` 未清洗文件名中的 `\`）
- 证据：Windows 文件名不可能含 `\`，但库根在 Linux/挂载卷时可以；解包端在 Windows 会把 `\` 当分隔符。
- 影响：【疑似，受害端问题】下载者用不严格的解压工具时可能路径逃逸。
- 建议：写入前 `arc.replace("\\", "/")` 并拒绝含 `..` 段的成员名。

## 次要问题清单

- `routes/shares.py:144`：share_url 硬编码 `{ip}:{lan._port}`，隧道/非默认端口场景生成的链接不可用
- `security.py:249-251`：`X-RateLimit-Remaining` 仅在响应为 `web.Response` 时附加，StreamResponse（下载/图片）缺失
- `scanner.py:44-45`：`self._scan_thread = t` 在锁外赋值，与 `stop()` 存在良性的检查-使用竞态
- `server.py:794-797`：`status()` 的 `bytes_transferred` 恒为 None（未接线，观测性缺口）
- `routes/auth.py:53-76`：注册成功即登录并种 Cookie；注册接口无邮箱归属验证（buyer_email 任意填）
- `shop/_common.py:249-251`：`_buyer_owner` 将任意客户端提供的 Cookie 值直接 hash 为 owner key——熵足够但意味着"遗忘 Cookie 即失权、无恢复渠道"（有 receipt recover 兜底，属设计取舍）
- `routes/websocket.py:64-68`：无 token 的 user principal 回退到 `list_users()` 全表扫描（每 30s 心跳）——仅性能
- `tunnel.py:107-110`：`shutil.which` 在 PATH 含相对/当前目录时可能解析到 CWD 中的同名可执行文件，建议绝对路径校验
- `system.py:30-45`：`_INFO_COUNT_CACHE` 满 8 键即全清（非 LRU），多库切换时抖动——仅性能
- `commerce_policy.py:38-49`：每个请求重读 AppSettings（设计为 fail-closed），无缓存——仅性能
- 无认证配置（auth=none）时 guest 仍不能建 WS（realtime=False）、不能下载（默认）——行为与文档一致，但 `/api/stats` 在该模式下完全公开（见 P2 条）

## 路由权限抽查结果表

| 路由 | 声明权限（api.py） | 实际检查（handler） | 一致？ |
|---|---|---|---|
| GET /api/download/{path} | required+general，**无能力位** | `require_permission("download")`（downloads.py:129） | 效果一致；声明缺位 |
| POST /api/download/batch | `download` 能力 | `require_permission("download")`（:229） | 一致 |
| GET /api/files | required+browse | `require_permission("browse")`（files.py:24） | 一致 |
| GET /api/thumbnails/{path} | required+skip | `require_permission("preview")`（thumbnails.py:39） | 一致 |
| POST /api/thumbnails/batch | `preview`+skip | `require_permission("preview")`（:166） | 一致 |
| GET /api/image | required+skip | `require_permission("preview")` + 二次 `assert_under_root`（image.py:117,131） | 一致 |
| GET /api/meta/{path} | required | `require_permission("browse")`（metadata.py:32） | 一致 |
| PUT /api/notes/{path} | `write_notes` | `require_user_write`（metadata.py:60） | 一致 |
| POST /api/tags | `write_tags` | `require_user_write`（tags.py:30） | 一致 |
| PUT/DELETE /api/tags/{name}、POST /api/tags/remove | `admin_tags` | `require_admin`（tags.py:60,90,121） | 一致 |
| POST /api/shares、DELETE /api/shares/{id} | `manage_links` | `require_permission("manage_links")`（shares.py:62,183） | 一致 |
| GET /api/shares | required，**无能力位** | `require_permission("manage_links")`（shares.py:158） | 效果一致；声明缺位 |
| POST /api/auth/login / register / verify_key | public+auth_strict+`public_auth` | 凭证/邀请码校验（routes/auth.py:20-101） | 一致 |
| /api/users*、POST /api/invites、POST …/revoke | `admin_users` | `require_admin`（users.py:10,18,52,85,94,107） | 一致 |
| GET /api/invites | required，无能力位 | `require_admin`（users.py:84） | 效果一致；声明缺位 |
| GET /api/activity | required+browse | `require_admin`（users.py:116） | 一致（handler 更严） |
| GET /api/online-users | required | `require_admin`（users.py:121） | 一致 |
| **GET /api/stats** | required+skip，无能力位 | **无检查**（system.py:132） | **不一致（偏宽）** |
| GET /api/revision | required+skip | realtime 能力内联（system.py:146） | 一致 |
| /ws | required+skip | 中间件认证 + realtime + 拒绝 query token（websocket.py:138-141） | 一致 |
| POST /api/shares/{id}/verify | public(POST)+auth_strict+`share_verify` | 密码 + 5/60s 锁（shares.py:231-248） | 一致（锁有并发竞态） |
| GET /api/shares/{id}/download | public(GET) | `validate_access` + 原子计数 | 一致 |
| GET /api/shares/{id}/preview、/info | public(GET) | 令牌/allow_preview；**410/expired 未折叠** | 基本一致（泄露见 P2） |
| POST/PUT/DELETE /api/shop/items[/{id}] | `seller`（public_optional） | `require_seller`（catalog.py:53-55） | 一致 |
| GET /api/shop/cart 系列 | `buyer_cart`（guest-allowed） | 签名 Cookie 匿名身份（_common.py:233-251） | 一致 |
| POST /api/shop/cart/checkout | `buyer_orders` | `_buyer_owner` + 幂等键（强制）+ 事务 | 一致 |
| POST …/confirm | `buyer_orders` | 收据原子 CAS（orders.py:104-108） | 一致 |
| …/fulfill、/revoke、/delivery/rotate、/delivery/revoke | `seller` | `require_seller`（orders.py:98、delivery.py:41,161） | 一致 |
| GET /api/shop/orders/export、/stats | public_optional，**无能力位** | `@seller_required`（orders.py:141-164） | 效果一致；声明缺位 |
| GET /api/shop/delivery/{token}(/download) | public_optional | 32 字节 bearer 令牌 + 配额 CAS + 统一 404 | 一致 |
| POST /api/shop/delivery/{order_id}/claim | `buyer_claim` | claim CAS + 10/300s/IP 限流 + 统一 404 | 一致（限流键受隧道折叠影响） |
| GET /api/quota | public+browse | 公开配额信息 + 签名身份 Cookie | 一致 |
| POST /api/shop/analytics/store-view | `public_signal` | 签名 Cookie 每日去重 | 一致 |
| PUT /api/shop/seller-profile | `seller` | `require_seller`（seller_profile.py:83） | 一致 |
| GET /（及全部 SPA 页面） | public | 静态 index.html，无敏感内容 | 一致 |

**结论**：未发现 P0；声明层与 handler 层在所有抽查路由上最终效果一致，其中 4 组"声明缺位、handler 兜底"（download 单文件、GET /api/shares、GET /api/invites、shop stats/export）与 1 处双层皆无检查（/api/stats）建议按上表补齐。优先修复顺序：P1 隧道限流身份键 → P2 密码模式令牌密钥派生 → P2 注册默认策略 → P2 分享密码锁原子化 → P2 cloudflared 哈希固定。
