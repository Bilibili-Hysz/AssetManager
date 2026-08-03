# 03 — API 与跨表面契约

本文档按当前源码核对，客户端实现见 `webui/src/api/`，路由注册见 [`AssetsManager/lan/api.py`](../../../../AssetsManager/lan/api.py)，认证 middleware 见 [`AssetsManager/lan/server.py`](../../../../AssetsManager/lan/server.py)。

## 1. 通用 HTTP 规则

[`webui/src/api/client.ts`](../../../../webui/src/api/client.ts) 的约定：

- 所有 JSON API 路径自动变为 `/api/<path>`；
- GET query 只发送非 `undefined`/`null` 值；
- JSON body 自动设置 `Content-Type: application/json`；
- 所有请求使用 `credentials: 'same-origin'`；
- `401` 调用 `onUnauthorized` 并抛出 `Unauthorized`；`403` 抛出 `Forbidden`；`429` 抛出 `Rate limited`；
- 其他非 2xx 优先读取 `{ error: string }`；
- 读取类 API 支持 `AbortSignal`；下载支持 Blob、流式进度和取消。

## 2. 服务器信息与认证

| 方法 | 路径 | 前端入口 | 权限/语义 | 返回 |
|---|---|---|---|---|
| GET | `/api/info` | `systemApi.getInfo()` | 公开读取；带有效 cookie 时反映 canonical principal | `ServerInfo`，可能带 `principal`/`capabilities` |
| POST | `/api/auth/login` | `authApi.login()` / `loginWithPassword()` | 用户名密码或简单密码；成功设置 HttpOnly `lan_token` | `user` 或 `principal`/`ok` |
| POST | `/api/auth/register` | `authApi.register()` | server 校验用户名、密码、邀请 | `user`，成功设置 cookie |
| POST | `/api/auth/verify_key` | `authApi.verifyKey()` | access key 登录 | `ok`，成功设置 cookie |
| POST | `/api/auth/logout` | `authApi.logout()` | 删除 `lan_token` | `{ ok: true }` |
| GET | `/api/auth/me` | `authApi.me()` | 当前 cookie/header session | `principal`，用户可带 `user` |

前端不应读取、持久化或拼接 `lan_token`。cookie 是 HttpOnly、SameSite=Lax、path `/`、max-age 86400；实际 token 生命周期还受 Runtime/session 和认证配置变更影响。

## 3. 文件、项目、搜索、标签和缩略图

| 方法 | 路径 | 前端入口 | 权限 | 关键输入/输出 |
|---|---|---|---|---|
| GET | `/api/files` | `filesApi.list(params, signal)` | `browse` | query: `path`, `sort`, `order`, `filter`, `search`, `summaries`; 返回 `FilesResponse` |
| POST | `/api/files/summaries` | `filesApi.summaries(parent_path, paths, signal)` | `browse` | body: `parent_path`、1–48 个 `paths`; 返回目录摘要 |
| GET | `/api/projects` | project listing route | `browse` | 项目列表；当前主浏览流以 `/api/files` 为主 |
| GET | `/api/projects/{path}` | `metadataApi.getProjectDetail(path, signal)` | `browse` | path 需 encode；返回 `ProjectDetail` |
| GET | `/api/tree` | `metadataApi.getTree()` | `browse` | `TreeResponse` |
| GET | `/api/home` | `metadataApi.getHome(signal)` | `browse` | `HomeData` |
| GET | `/api/search` | `metadataApi.search(q, tags, category, signal)` | `browse` | query: `q`, `tags`, `category`; `SearchResponse` |
| GET | `/api/meta/{path}` | `metadataApi.getMeta(path, signal)` | `browse` | path 需 encode；`Metadata` |
| GET | `/api/tags` | `tagsApi.list()` | `browse` | `{ tags: Tag[] }` |
| POST | `/api/tags` | `tagsApi.add(tag, filePath)` | admin | `{ tag, file_path }` |
| PUT | `/api/tags/{name}` | `tagsApi.rename(oldName, newName)` | admin | `{ new_name }` |
| DELETE | `/api/tags/{name}` | `tagsApi.delete(name)` | admin | `{ ok: boolean }` |
| GET | `/api/thumbnails/{path}` | `thumbnail_url` 直接加载 | preview/path validation | 图片响应；路径必须在 library root 内 |
| POST | `/api/thumbnails/batch` | `thumbnailsApi.batch(paths, size)` | `preview` | paths 1–100、size 16–2048；base64 map |

路径契约：服务端使用 canonical resolve/containment 校验。前端只传相对库路径，不要拼接绝对路径、盘符或未经验证的用户输入。

## 4. 下载

| 方法 | 路径 | 前端入口 | 权限/限制 | 语义 |
|---|---|---|---|---|
| GET | `/api/download/{path}` | `filesApi.download(path)` 或直接链接 | `download` | 文件直接下载；目录生成 ZIP |
| POST | `/api/download/batch` | `filesApi.batchDownload(paths, onProgress, signal)` | `download` | 最多 100 paths，总大小上限 500 MB；返回 ZIP Blob |

下载链接必须使用安全 path encoding。批量下载 UI 要处理流式进度、取消、403、413 和失败 toast。

## 5. 分享

| 方法 | 路径 | 前端入口 | 权限/语义 |
|---|---|---|---|
| POST | `/api/shares` | `sharesApi.create(data)` | `manage_links`；paths 最多 100，server 验证 scope/密码/过期/下载上限 |
| GET | `/api/shares` | `sharesApi.list()` | `manage_links` |
| DELETE | `/api/shares/{id}` | `sharesApi.delete(id)` | `manage_links`，server 再查归属/权限 |
| GET | `/api/shares/{id}/info` | `sharesApi.getInfo(id)` | 公开 route；密码分享未验证时只返回受限 info |
| POST | `/api/shares/{id}/verify` | `sharesApi.verifyPassword(id, password)` | 公开 route；成功设置分享 cookie |
| GET | `/api/shares/{id}/preview/{path}` | `sharesApi.getPreviewUrl(id, path)` | share token、allow_preview、图片和 scope 均由 server 强制 |
| GET | `/api/shares/{id}/download/{path}` | `sharesApi.getDownloadUrl(id, path)` | 密码、过期、scope、下载上限由 server 强制 |

分享专属 token/cookie 不等同于 LAN 登录 token。ShareReceivePage 不应把 share password 或 token 写进普通 auth state，也不应以普通 `/api/files` 绕过 share scope。

## 6. 管理与系统

| 方法 | 路径 | 前端入口 | 权限 |
|---|---|---|---|
| GET | `/api/users` | `usersApi.list()` | admin |
| POST | `/api/users/{id}/toggle` | `usersApi.toggleUser(id, active)` | admin |
| GET | `/api/invites` | `usersApi.listInvites()` | admin |
| POST | `/api/invites` | `usersApi.createInvite()` | admin |
| POST | `/api/invites/{code}/revoke` | `usersApi.revokeInvite(code)` | admin |
| GET | `/api/activity` | `usersApi.getActivity()` | admin |
| GET | `/api/online-users` | `usersApi.getOnlineUsers()` | admin |
| GET | `/api/stats` | `systemApi.getStats()` | 按实际 route/middleware 处理 403 |
| GET | `/api/tunnel/status` | `systemApi.getTunnelStatus()` | 当前 route 明确要求 admin |
| GET | `/api/revision` | RealtimeContext `recover()` | `realtime` capability |

注意：`docs/lan-security.md` 的公开路径说明与当前 `system.py` 中 `/api/tunnel/status` 的 `require_admin()` 存在表述差异。前端必须按实际响应处理，后端文档/契约应后续统一。

## 7. WebSocket

连接为同源 `ws(s)://<same-origin>/ws`。握手要求：

- 浏览器携带同源 HttpOnly `lan_token` cookie，或处于 server 明确允许的无认证 guest 状态；
- principal 必须拥有 `realtime` capability；
- query-string `token` 和 `key` 会被拒绝；
- server 返回 `runtime_ready`：`{ type, epoch, revision }`；
- 失效事件为 `projection_invalidated`，包含 `epoch`、`revision`、`domains`、`paths`；
- revision gap 或 epoch change 必须恢复，不能假设中间事件已收到。

前端只订阅 domain 并重新请求权威 snapshot。不要依赖 `paths` 的完整性，也不要把 WebSocket 连接成功当作数据已同步。

## 8. DTO 变更规则

前端 DTO 集中在 [`webui/src/types/api.ts`](../../../../webui/src/types/api.ts)，后端稳定 DTO 集中在 [`AssetsManager/lan/dto.py`](../../../../AssetsManager/lan/dto.py)。修改字段前必须同步后端 route/DTO、前端 type/API factory、契约测试、`tests/lan` 公共契约和本矩阵。
