# 06 · LAN 服务器层

## 1. 整体结构

```
lan/
├── server.py        # _LanServerImpl：aiohttp 生命周期 + 中间件 + 指标（1013 行核心）
├── manager.py       # ShareManager：UI 唯一入口，协调 server + tunnel 状态机
├── api.py           # 路由注册薄层（~50 端点）
├── principal.py     # 会话身份与能力模型（Capabilities）
├── dto.py           # 公共响应 DTO（契约稳定层）
├── security.py      # RateLimiter / AuthRateLimiter / IPBlacklist / 中间件工厂
├── path_guard.py    # PathGuard：路径穿越防护
├── auth.py          # 领域密码学再导出（薄）
├── scanner.py       # DirectoryScanner：全库内存索引（搜索加速）
├── tunnel.py        # TunnelManager：Cloudflare 隧道子进程
├── ws.py            # WebSocketManager：连接/心跳/广播/授权撤销
├── utils.py         # get_local_ip / generate_auth_token
└── routes/          # 11 个路由模块（files/downloads/shares/tags/thumbnails/metadata/auth/users/system/websocket/pages/_helpers）
```

**运行模型**：服务器跑在**独立后台线程 + 独立 asyncio 事件循环**（`_run` server.py:658-735）；Qt 主线程通过 `asyncio.run_coroutine_threadsafe` 与它通信（`broadcast` :530-535）。每次 start 重建 `web.Application`（`_build_app` :178-188），支持同一实例多次启停（生命周期代数 `_lifecycle_generation` 管理）。

## 2. 中间件链（三层）

`_build_app`（server.py:186）：`middlewares=[security_mw, metrics_mw, auth_mw]`

### ① 安全中间件（security.py:95-155）
- IP 黑名单（403）→ IP 白名单（配置后非白名单一律 403）→ 认证端点限流（10 次/5 分钟）→ 普通端点限流（默认 100-1000 次/分钟）
- **浏览类路径豁免限流**：`/ws`、`/api/thumbnails/`、`/api/files`、`/api/projects`、`/api/tags`、`/api/info`、`/assets`（防止缩略图风暴误伤）
- 返回 `X-RateLimit-Remaining` 头

### ② 指标中间件（server.py:190-194）
请求计数，无其他逻辑。

### ③ 认证中间件（server.py:924-1013）—— 身份判定核心
判定顺序（`principal_for_request` 构造 `SessionPrincipal`）：
```
公开路径表（_PUBLIC_PATHS / _PUBLIC_PATH_PREFIXES / 分享端点） → guest
/api/info 特例：永远可读，但带上有效凭据可提升身份
无任何认证配置 → guest
Bearer/Cookie token 依次尝试：
  1. access_key 校验（verify_key）     → admin(access_key)
  2. local_ui token（verify_auth_token，桌面 Qt 客户端用）→ admin(local_ui)
  3. 用户 token（verify_user_token）   → user/admin
  4. 简单密码 token（verify_token）    → admin(password)
否则 401
```

**能力矩阵**（principal.py `principal_for_request` :71-91）：
- admin：全能力（含 manage_links/manage_users/settings/upload）
- 注册用户：browse/preview/download/realtime，**无** upload/manage 权限
- guest：由设置控制（`lan_guest_list`/`lan_guest_preview`/`lan_guest_download`，默认 list+preview 开、download 关）

## 3. 路由清单（api.py setup_routes :40-74）

| 端点 | 权限 | 服务 | 说明 |
|---|---|---|---|
| `/` `/browse` `/detail` `/login` `/s/{id}` | 公开 | — | React SPA（webui/dist，缺失时 503） |
| `GET /api/files` | browse | AssetService | 目录列表（排序/过滤/搜索/深度/项目标记） |
| `POST /api/files/summaries` | browse | AssetService | 目录摘要批量（1-48 个直子目录，防滥用校验） |
| `GET /api/thumbnails/{path}` | preview | ThumbnailService | 缩略图（size 16-2048，缓存/模糊/原图三态） |
| `POST /api/thumbnails/batch` | preview | ThumbnailService | 批量缩略图（base64，1-100） |
| `GET /api/download/{path}` | download | — | 单文件 / 目录 ZIP（500MB 上限，临时文件写后删） |
| `POST /api/download/batch` | download | — | 批量 ZIP（≤100 路径，500MB 上限） |
| `GET /api/projects` `/api/projects/{path}` | browse | ProjectService | 项目列表/详情 |
| `GET /api/tree` `/api/home` | browse | ProjectService | 目录树/首页聚合 |
| `GET /api/meta/{path}` | browse | MetadataService | 标签/备注/URL（URL 经 scheme+netloc 白名单校验） |
| `GET /api/search` | browse | SearchService | 标签→内存索引→assets 表三级检索 |
| `GET/POST /api/tags*` | browse / **admin 写** | TagService | 标签增删改（写操作仅 admin） |
| `GET /api/info` | 公开 | — | 服务器信息 + principal/capabilities（前端鉴权依据） |
| `GET /api/revision` | realtime | — | Runtime 游标（epoch+revision），新式轮询 |
| `POST /api/auth/login/register/verify_key/logout` | 公开 | AuthService | 三种认证模式 + 注册（邀请码） |
| `GET /api/auth/me` | 认证 | AuthService | 当前用户 |
| `GET /api/users` `POST /api/users/{id}/toggle` | admin | AuthService | 用户管理 |
| `GET/POST /api/invites*` | admin | AuthService | 邀请码 |
| `GET /api/activity` `/api/online-users` | admin | ActivityLog/OnlineUsers | 审计/在线（内存 deque，≤100 条） |
| `GET /api/tunnel/status` `/api/stats` | admin / 认证 | — | 隧道/统计 |
| `POST/GET/DELETE /api/shares*` | manage_links | ShareService | 分享链接管理（普通用户仅看/删自己的） |
| `POST /api/shares/{id}/verify` | 公开 | ShareService | 分享密码验证 → 1h share_token（cookie 限定 path） |
| `GET /api/shares/{id}/download/{path}` | 分享 | ShareService | 分享下载（计数 +1） |
| `GET /api/shares/{id}/preview/{path}` | 分享 | ShareService | 分享预览（仅图片） |
| `GET /api/shares/{id}/info` | 公开 | ShareService | 分享元信息 |
| `GET /ws` | realtime 能力 | WebSocketManager | 实时事件 |

## 4. 安全设计细节（值得记录）

- **路径防护双层**：`PathGuard`（path_guard.py:35-54）——`\`→`/` 归一化 + strip + `resolve()` + `is_relative_to`，用于 API 入口；分享作用域另有 `_resolve_share_target`（shares.py:39-58）——`is_relative_to` 规范包含 + 分享路径白名单匹配
- **SQL 注入防护**：LIKE 查询统一 `ESCAPE '\\'` 转义 `%`/`_`/`\`（Repository 层）
- **下载安全**：Content-Disposition 文件名净化（控制字符/分隔符剥离，UTF-8 回退）、ZIP 临时文件响应后自动删除（downloads.py:32-49）
- **Cookie 安全**：`lan_token`（httponly + samesite=Lax + 24h）；`share_token` **限定 path=`/api/shares/{id}`**（分享凭据不泄露到其他端点）
- **Query 参数鉴权已废弃**（_helpers.py get_auth_token :300-326）：`?token=`/`?key=` 打警告日志，将移除；WebSocket 禁用 query 鉴权
- **分享下载竞态**：`increment_download` 为原子 UPDATE；但"检查限次→下载"非事务，极端并发可能超限 1 次（低风险）
- **认证缓存**：`_has_users_cache` 30s TTL，用户变更时 `invalidate_user_cache`
- **WebSocket 授权**：连接后 `authorize` 回调周期性重验（心跳 30s）；凭据吊销（revoke_authority）按 authority 组原子驱逐

## 5. WebSocket 实时体系

- 连接流程（websocket.py:135-246）：中间件已验身份 → `runtime_ready{epoch, revision}` 基线 → `ws_manager.add`（授权重验 + admission barrier + 在线列表上报）→ `finish_admission`（**基线漂移补偿**：若 admission 期间有广播，补发 runtime_ready）
- 广播（api.py runtime_startup :57-110）：RuntimeEventRouter 订阅者 → `projection_invalidated{epoch, revision, domains, paths}` → 逐 socket 串行保证顺序（`_invoke_callback` 回调链）
- 心跳（ws.py:280-320）：30s PING + 10s PONG 超时驱逐；`MAX_WS_CONNECTIONS=50`
- 授权吊销（revoke_authority：ws.py:250-277）：deactivate 用户后按 authority 原子驱逐其 socket

## 6. 隧道与扫描

- **TunnelManager**（tunnel.py:78-161）：`cloudflared tunnel --url http://127.0.0.1:{port}` 子进程 + stderr 解析 `https://*.trycloudflare.com`；查找顺序：PyInstaller bundle → 仓库根 → Shared 缓存 → PATH；**自动下载**（github release，54MB）
- **DirectoryScanner**（scanner.py:19-74）：服务器启动后后台 `os.walk` 全库建内存索引（隐藏文件跳过）；搜索线性过滤前 200 条；`is_scanning()` 供状态显示

## 7. ShareManager（manager.py）

UI 唯一操作对象：`start(port, password, access_key, rate_limit, runtime=...)` → `LanServer` → `stop()`（先停隧道再停服务器）→ 状态回调 `on_state_change`。桌面端 `LanSharingMixin._toggle_sharing`（widgets/lan_sharing.py:71）持有它。

## 8. 数据流要点

```
浏览器请求
 └→ security_mw（限流/黑名单/白名单）
     └→ auth_mw（principal 判定：key/local_ui/user/password/guest）
         └→ route handler
              ├→ PathGuard 路径校验
              ├→ require_permission(principal.capabilities)
              ├→ asyncio.to_thread(服务调用)   # 阻塞操作出事件循环
              └→ 响应（FileResponse/JSON）
变更事件（桌面端操作）→ 领域事件 → RuntimeEventRouter → WebSocket 广播 → 浏览器实时刷新
```
