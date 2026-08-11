# 模块排 Bug 清单（module-lan-core.md · 2026-08-10 P0 第1轮）

> 来源: 只读探索代理审计，行号经源码核对。修复前需第二子代理复核真实性。


# LAN 核心文件缺陷审计清单（M10a）
审计日期: 2026-08-10
范围: lan/api.py, lan/auth.py, lan/manager.py, lan/path_guard.py, lan/principal.py, lan/security.py, lan/server.py
（认证/路径守卫组合核查时交叉引用了 lan/routes/_helpers.py、lan/routes/auth.py、lan/routes/downloads.py、lan/routes/shares.py、lan/routes/system.py、application/auth_service.py、repositories/auth_repository.py、domain/auth.py、domain/share.py）

共计 21 项：高 2 / 中 5 / 低 14

## Bug 1 - `_has_active_users` 数据库异常时认证失败开放（fail-open），auth 中间件放行全部请求
- 位置: AssetsManager/lan/server.py:1464-1465（配合 1624-1629 的"未配置认证则放行"判定）
- 严重度: 高
- 描述: `_has_active_users()` 在 `has_active_users(raise_on_error=True)` 抛异常时返回 `self._has_users_cache or False`。若缓存为空或已过期（TTL 30s），返回 False；`_auth_middleware` 据此判定"未配置任何认证"（1627 行），将请求以 guest 放行。用户模式下（无 access_key、无 password），SQLite 一旦被锁/磁盘错误，整个 LAN 服务器退化为无认证开放，浏览与下载全部暴露。
- 触发/复现: 配置 user 模式认证并存在活跃用户 → 服务器运行中使数据库短暂不可用（如另一进程持有写锁触发 `database is locked`）→ 缓存 30s 过期后任意请求 → 返回 200 而非 401，guest 可浏览/下载。
- 修复建议: 异常时 fail-closed（返回 True 并记日志，或直接让异常上抛为 503），绝不能返回 False 当作"无用户"。

## Bug 2 - 启动期 `_configured_auth_status` 失败开放，auth 配置的服务器以无认证启动
- 位置: AssetsManager/lan/manager.py:478-482
- 严重度: 高
- 描述: 用户模式启动时若 `has_active_users()` 抛异常（DB 锁/IO 错误），被 `except Exception` 吞掉并返回 `(False, "none")`；security preflight 据此判定认证未启用，`ShareManager.start()` 照常启动服务器且无任何认证。
- 触发/复现: 以 auth_mode="user" 启动，启动瞬间 DB 查询失败（如并发写锁）→ 服务器以开放状态监听 0.0.0.0。
- 修复建议: 异常时视为"无法确认安全状态"，中断启动并返回 failure_reason，而不是降级为无认证。

## Bug 3 - seller 登录端点未纳入严格认证限流（密码暴力破解窗口）
- 位置: AssetsManager/lan/security.py:117-120（`_AUTH_ENDPOINTS` 仅含 /api/auth/login 与 /api/auth/register）
- 严重度: 中
- 描述: `/api/shop/auth/login`（api.py:262）与 `/api/auth/seller-login`（api.py:282）为公开端点（server.py:1481-1486），但只受通用限流（默认 1000 次/60 秒），不受 AuthRateLimiter（10 次/300 秒）约束。seller 口令可被暴力尝试。
- 触发/复现: 对 `/api/shop/auth/login` 循环 POST 不同口令，每分钟可尝试 1000 次。
- 修复建议: 将两个 seller 登录端点加入 `_AUTH_ENDPOINTS`。

## Bug 4 - 查询串 token 认证（?token= / ?key=）全局可用，令牌泄露面大
- 位置: AssetsManager/lan/server.py:1633；AssetsManager/lan/routes/_helpers.py:355-375
- 严重度: 中
- 描述: 除 `/ws` 外所有路径允许 `?token=`/`?key=` 通过查询串认证（代码注释自认已废弃但仍启用）。令牌会进入服务器访问日志、浏览器历史、Referer 头。配合无服务端撤销的 24h 令牌（见 Bug 5），泄露后 24 小时内可冒用。
- 触发/复现: 访问 `http://ip:port/api/files?path=/&token=<valid>` 即可认证；token 出现在日志/历史中。
- 修复建议: 默认禁止 query 认证（allow_query=False），只保留 Authorization/cookie。

## Bug 5 - 注销不撤销令牌（无服务端会话/撤销列表）
- 位置: AssetsManager/lan/routes/auth.py:98-101
- 严重度: 中
- 描述: `handle_logout` 仅 `del_cookie`；所有令牌（password/local_ui/user）均为无状态 HMAC 时间戳令牌，24h 内仍有效。被窃取或从日志恢复的令牌在"注销"后依然可认证。
- 触发/复现: 登录拿到 token（cookie 或 query）→ 注销 → 用原 token 直接请求受保护端点 → 200。
- 修复建议: 引入服务端撤销（撤销列表/版本号）或缩短有效期并增加刷新机制。

## Bug 6 - `broadcast()` 在 loop 关闭/停止竞态下未防护，异常上抛且 future 无人观察
- 位置: AssetsManager/lan/server.py:944-949
- 严重度: 中
- 描述: `asyncio.run_coroutine_threadsafe(self._ws_manager.broadcast(...), self._loop)` 未加锁读取 `_loop`/`_running`，也未 try/except。若调用时 loop 已关闭（stop 完成/启动失败）会抛 RuntimeError 直接传给调用方（UI 线程）；返回的 future 从不 await/观察，广播异常静默丢失（"exception was never retrieved"）。
- 触发/复现: 服务器停止后（或停止过程中）UI/事件回调调用 `lan.broadcast(...)`。
- 修复建议: 检查 `loop.is_closed()`、包 try/except、给 future 加 done callback 记录异常。

## Bug 7 - `ShareManager.stop()` 未捕获 `server.stop()` 异常，状态卡死
- 位置: AssetsManager/lan/manager.py:216-218
- 严重度: 中
- 描述: `self._server.stop()` 无 try/except。`_LanServerImpl.stop()` 在关闭超时/线程未终止时会 raise（server.py:683-686, 781），异常直接上抛到 UI，`self._server`、`_state` 均未清理；之后 `start()` 因 "previous server thread is still alive"（server.py:486）持续失败，需要强杀进程才能恢复。
- 触发/复现: 关闭时 WS 连接不释放导致 shutdown 8s 超时 → `TimeoutError` 上抛。
- 修复建议: 捕获异常，仍推进状态机（清理句柄、置 stopped/failed），仅把错误记录到 failure_reason。

## Bug 8 - PathGuard 未处理内嵌 NUL 字节，抛 ValueError 变成 HTTP 500
- 位置: AssetsManager/lan/path_guard.py:36（调用方 routes/_helpers.py:310-323 仅捕获 PathEscapeError/MissingPathError）
- 严重度: 低
- 描述: URL 中 `%00` 经 aiohttp 与 `unquote` 双重解码后进入 `(root / cleaned).resolve()`，Windows/Linux 均抛 ValueError；未被捕获 → 500。属健壮性/错误处理缺陷（无信息泄露，aiohttp 默认 500 为通用文案）。
- 触发/复现: `GET /api/download/..%00/secret.txt`（或任意含 %00 路径）。
- 修复建议: `resolve()` 内显式拒绝 `\x00`（及其他控制字符），或 validate_path 捕获 ValueError 转 400。

## Bug 9 - Windows NTFS 备用数据流（file:stream）可绕过路径守卫
- 位置: AssetsManager/lan/path_guard.py:35-37（下载入口 AssetsManager/lan/routes/downloads.py:99-100）
- 严重度: 低
- 描述: `root / "file.txt:Zone.Identifier"` 在 pathlib 中视为同一文件的另一部分名，`is_relative_to` 判定通过，`Path.exists()`/`web.FileResponse` 在 Windows 上会打开该 ADS 并流式返回其内容。仅影响 Windows 主机且需知道流名。
- 触发/复现: Windows 上 `GET /api/download/secret.txt:Zone.Identifier`（冒号 URL 编码）。
- 修复建议: PathGuard 拒绝含 `:` 的路径段（Windows 特定），或下载前用 `os.path.splitdrive`/检查。

## Bug 10 - 目录/批量 ZIP 打包未对库内符号链接做逐文件校验，可外泄库外文件
- 位置: AssetsManager/lan/routes/_helpers.py:394-417（`build_zip_sync` 的 os.walk + zf.write）；入口仅校验顶层 target（downloads.py:158/256）
- 严重度: 低
- 描述: `validate_path` 只校验请求的入口路径；os.walk 不跟随目录 symlink，但目录内指向库外的文件 symlink 会被 `zf.write` 打开并把目标内容打入 ZIP。若库内存在指向敏感文件的链接，具有 download 权限的访客即可外泄。
- 触发/复现: 库内存在 `ln -s C:\Windows\...\file x.jpg`（Windows 上为 .lnk 场景受限，主要影响支持 symlink 的目录），访客下载该目录。
- 修复建议: 打包遍历时对每个文件 `Path(fp).resolve()` 校验仍在 target 子树内，否则跳过。

## Bug 11 - 限流/黑名单按 `request.remote` 计数，None 时共用 "unknown" 桶
- 位置: AssetsManager/lan/security.py:134
- 严重度: 低
- 描述: `ip = request.remote or "unknown"` — 若 aiohttp 无法解析对端（如 unix socket/异常连接），所有此类请求共享同一个限流桶与黑名单身份。
- 修复建议: remote 为空时直接拒绝或按连接唯一标识处理。

## Bug 12 - `/api/files` 与 `/api/thumbnails/batch` 完全跳过限流
- 位置: AssetsManager/lan/security.py:104-113（`_RATE_LIMIT_SKIP` 精确匹配 "/api/files"；`path.startswith("/api/thumbnails/")` 覆盖批量 POST）
- 严重度: 低
- 描述: 精确匹配使 `/api/files`（含 summarize 的昂贵列表）不受限流；`/api/thumbnails/batch` POST（批量图像处理，CPU 密集）也因前缀匹配被跳过。认证用户可无限触发。
- 修复建议: 仅对 GET 浏览类跳过；批量缩略图纳入限流。

## Bug 13 - 通用限流 429 的 Retry-After 硬编码 5 与 60s 窗口不符
- 位置: AssetsManager/lan/security.py:164-168
- 严重度: 低
- 描述: 窗口 60s，但响应头与 JSON 均写死 `retry_after: 5`，客户端按 5s 重试仍被拒，且误导调用方。
- 修复建议: 按实际剩余窗口计算。

## Bug 14 - IP 白名单与隧道/代理/IPv6 组合的边界问题
- ✅ 已修复（2026-08-11 P2 低危首批）: security.py `_normalize_ip`（IPv4-mapped/::1 归一化）+ `create_security_middleware(tunnel_active=...)` 隧道运行期回环放行；server.py `_build_app` 接线 `self._tunnel_active`。测试: tests/lan/test_low_batch_security.py。
- 位置: AssetsManager/lan/security.py:141-143
- 严重度: 低
- 描述: 走 cloudflared 隧道时对端恒为 127.0.0.1，配置 LAN 网段白名单会全部阻断隧道流量；配置 `0.0.0.0` 永远不会匹配真实客户端；IPv6 回环 `::1`/`::ffff:127.0.0.1` 与 `127.0.0.1` 字符串比较不匹配。均无规范化处理。
- 修复建议: 文档化白名单语义，或对 IP 做规范化/展开比较，并提供隧道放行选项。

## Bug 15 - 空登录请求在仅用户模式下返回 200 {"ok": True}
- ✅ 已修复（2026-08-11 P2 低危首批）: auth.py:46 无 username 且无 password_hash 分支返回 400 `{"error": "Credentials required"}`。测试: tests/lan/test_low_batch_auth.py。
- 位置: AssetsManager/lan/routes/auth.py:46
- 严重度: 低
- 描述: 无 username 且未配置 password 时（如用户模式），POST /api/auth/login 空 body 返回 200 `{"ok": True}` 且无任何 cookie —— 前端可能误判已登录；同时模糊了"登录失败"语义。
- 修复建议: 无任何凭证分支返回 400/401。

## Bug 16 - 登录/注册接口存在用户枚举
- ✅ 已修复（2026-08-11 P2 低危首批）: auth_service.py `authenticate_user` 三分支统一 `"Invalid username or password"`；`register_user` 重复用户名 → `"Registration failed"`。测试: tests/lan/test_low_batch_auth.py。残余（接受）: 不存在/停用用户跳过 PBKDF2 存在毫秒级时序差；邀请码注册本质是注册预言机，属开放注册设计固有。
- 位置: AssetsManager/lan/routes/auth.py:27-35（"User not found" vs "Invalid password"）；application/auth_service.py:186-191、237-238（"Username already exists"）
- 严重度: 低
- 描述: 错误消息区分用户存在性，可在 LAN 上枚举用户名。
- 修复建议: 统一返回通用错误消息。

## Bug 17 - 公开 /api/info 泄露认证模式与库信息
- 📌 决策：保持公开（2026-08-11，文档化权衡）: 前端登录页需要 `auth_mode` 决定渲染 key/user/password 表单（webui/src/pages/LoginPage.tsx），落地页需要 share_name/library_stats/footer_text（LandingPage.tsx）。完整载荷对未认证请求公开是**有意设计**，不含机密/用户数据；system.py:12-19 已加 NOTE 说明。行为未变。
- 位置: AssetsManager/lan/routes/system.py:54-73（中间件 server.py:1574-1600 使其公开可读）
- 严重度: 低
- 描述: 未认证请求可读取 `auth_mode`（none/password/key/user 精确告知攻击者攻击面）、share_name、库名与库大小统计。
- 修复建议: auth_mode 仅对已认证请求返回，或模糊为布尔值。

## Bug 18 - 未配置邀请码时注册完全开放，自注册用户获得下载权限
- ✅ 已修复（2026-08-11 P2 低危首批）: principal.py `kind=="user"` 三分支映射 —— admin→all_caps、显式 "user"→user_caps、其余（viewer/未知，自注册默认）→viewer_caps（无 download）。测试: tests/lan/test_low_batch_principal.py。注: 代码库唯一建用户路径 register_user 默认 role="viewer"，故所有自注册用户（含邀请码路径）不再获得下载能力；与 get_user_permissions 未知角色→guest（download False）一致。
- 位置: AssetsManager/application/auth_service.py:230-255（注册端点公开：routes/auth.py:49-72；注册用户能力 principal.py:86 `user_caps.download=True`）
- 严重度: 低
- 描述: 只要邀请码表为空，注册无需邀请码；而 LAN 上任何人可访问公开的 /api/auth/register。默认 guest 无下载权限，但自注册的 "user" 角色拥有 download 权限，等于绕过 guest 下载限制。
- 修复建议: 首个用户引导后默认要求邀请码，或限制自注册角色能力。

## Bug 19 - 异常用户记录导致 principal 构造 500
- ✅ 已修复（2026-08-11 P2 低危首批）: principal.py `_as_int`/`_as_float` 对 None/TypeError/ValueError 返回安全默认值。测试: tests/lan/test_low_batch_principal.py。
- 位置: AssetsManager/lan/principal.py:93-95
- 严重度: 低
- 描述: 回退分支中 `_as_int(user.get("id", 0))`/`_as_float(...)` 对 None 值抛 TypeError（int(None)），使 /api/auth/me 与鉴权流程 500。
- 修复建议: 对缺失/None 字段使用安全默认值。

## Bug 20 - 服务器关闭未停止后台目录扫描线程
- ✅ 已修复（2026-08-11 P2 低危首批）: scanner.py 新增 `stop()`（取消标志 + join(2s)，可重复调用、无持锁死锁），walk 循环检查取消标志；server.py `_shutdown` 防御式调用。测试: tests/lan/test_low_batch_cookies_scanner.py。
- 位置: AssetsManager/lan/server.py:1315-1316（启动扫描）；`_shutdown` 1367-1385 无对应停止
- 严重度: 低
- 描述: `DirectoryScanner.start_background_scan()` 启动 daemon 线程（scanner.py:24-30），`_shutdown` 不通知停止。快速重启时旧扫描线程与新扫描并发占用 I/O；停止后线程仍在后台遍历库。
- 修复建议: 给 scanner 增加 cancel 标志/stop()，在 `_shutdown` 中调用。

## Bug 21 - 认证 cookie 缺少 Secure 标志（HTTPS 模式下）
- ✅ 已修复（2026-08-11 P2 低危首批）: `set_auth_cookie`/`set_share_cookie` 增加 keyword-only `secure=False` 参数；routes/auth.py 4 处调用点传 `secure=lan.ssl_active`，shares.py 1 处经 `request.app.get(LAN_APP_KEY)` 防御传值；**同族补齐**: seller_auth.py `_set_seller_cookie` 同样加 secure（`request.secure`）。HTTP 场景默认 False 不破坏登录。测试: tests/lan/test_low_batch_cookies_scanner.py。
- 位置: AssetsManager/lan/routes/_helpers.py:326-329（`set_auth_cookie`）、332-337（`set_share_cookie`）
- 严重度: 低
- 描述: 启用 SSL（ssl_cert/ssl_key）后，lan_token/share_token cookie 仍未设置 secure=True（HttpOnly/SameSite=Lax 已正确）。若存在 TLS 终结代理或客户端混合访问，cookie 可能经明文通道传输。注意：HTTP 场景下直接加 Secure 会破坏登录，应条件设置。
- 修复建议: 按 `lan.ssl_active`/`request.secure` 条件设置 Secure。

## 检查点结论（无问题的项明确列出）
- 路径遍历核心防线: PathGuard.resolve 对 `..`、绝对路径、驱动器盘符（C:foo）、UNC（//server/share）、反斜杠混用、双层 URL 编码（%252e%252e）的规范化与 `is_relative_to` 终检均已实测/推演通过，未发现主绕过；残余问题仅为 Bug 8/9/10（NUL、ADS、ZIP 内 symlink，均低危）。符号链接在入口处被 resolve() 跟随并拒绝（image.py:138-140、shares.py:36-53 亦复检）。
- 中间件顺序: 经 aiohttp 3.14 源码与实测验证，`middlewares=[security, metrics, auth]` 中首元素为最外层 → security（黑名单/限流）先于 auth 执行，顺序正确，无问题。
- 密码/密钥存储与比较: PBKDF2（50k/100k 迭代）+ `hmac.compare_digest`，verify_key/verify_password/verify_token/verify_auth_token/verify_user_token/verify_share_token 实现正确，无问题。
- 分享口令校验: PBKDF2 + compare_digest，verify 端点已纳入认证限流，无问题。

