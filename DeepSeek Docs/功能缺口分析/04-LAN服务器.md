# 04 · LAN 服务器功能缺口

覆盖：`lan/*`（server/api/routes/ws/tunnel/security）

## G4-1 上传能力是死代码（最严重缺口）[P0][L]

- **现状**：能力模型声称支持上传：`Capabilities.upload`（principal.py:18）、admin 权限 `upload: True`（_helpers.py:203）、DTO 输出（dto.py:11,19）；但 **`api.py` 全部 50 个端点中没有任何上传/写入路由**（rg 验证：upload 仅出现在能力定义处）；WebUI 也无上传组件
- **缺口**：用户注册系统 + 权限模型里明确区分"注册用户无上传、admin 有上传"，但功能从未实现
- **用户影响**：团队协作场景无法通过浏览器向库添加文件；权限模型对用户是"虚假承诺"
- **实现路径**：`POST /api/upload`（multipart，PathGuard 校验目标目录 + `sanitize_filename` + `unique_destination` 防冲突 → `FileOperationService.copy` 语义 + 事件广播）；限流/大小限制（复用 downloads 的 500MB 常量思路）；WebUI 拖放上传组件；**完成权限语义闭环**（L）

> **处理状态（2026-08-15）**：选择「下线能力声明」——`principal.py` 的 `all_caps`（admin/password/access_key/local_ui）将 `upload` 由 `True` 改为 `False`，消除「admin 有上传」的虚假承诺；`upload` 字段保留为恒 `False` 的保留字段（公开 capabilities 形状不变，无契约/TS 涟漪）。真正实现上传仍列为 P1/P2 后续（`G4-2` 远程文件管理是其姊妹项，可一并在「实现上传」时补）。

## G4-2 无远程文件管理端点 [P1][L]

- **现状**：Web 端只能浏览/下载；无 重命名/移动/删除/新建文件夹 端点（桌面 `FileOperationService` 7 个操作全部未暴露）；标签写接口 admin-only（tags.py:41-70）
- **用户影响**：人在外面想整理库（改文件名、挪目录、删废图）做不到
- **实现路径**：`PATCH /api/files/{path}`（rename/move）+ `DELETE /api/files/{path}`（回收站）+ `POST /api/folders`，复用 FileOperationService（绑定 runtime 的 scoped 实例已在 LanScopedServices 中——只需确认 asset_index 依赖注入）；权限：admin 全量、注册用户限制在"可写目录"配置（L）

## G4-3 活动日志不持久化 [P1][S]

- **现状**：`ActivityLog`（_helpers.py:36-58）是**内存 deque(maxlen=100)**：重启即丢、无分页、无导出；在线用户同理（OnlineUsers :60-78 内存字典）
- **用户影响**：管理审计（谁下载了什么）无法回溯
- **实现路径**：新增 `activity_log` 表（user/action/detail/ip/timestamp + 可选 share_id），ActivityLog 写表 + 读接口分页；在线用户保持内存（实时语义）（S-M）

## G4-4 分享链接能力缺口 [P1][M]

- **现状**（share 相关）：① 分享页（`/s/{id}`）无**视频预览**（`handle_share_preview` 仅 IMAGE_EXTS，shares.py:283-300）② 无"暂停/恢复"分享 ③ Web 端无 QR 展示（QR 仅桌面 ShareQrDialog）④ 无分享链接有效期到期前提醒 ⑤ `handle_list_shares` 不分页（大列表拖慢）
- **实现路径**：① 视频预览（走 G1-2 的 mp4 直出，M）② shares 表加 `paused` 列 + validate_access 检查（S）③ 分享页内嵌 QR（segno 已在依赖，S）

## G4-5 认证体验缺口 [P1][M]

- **现状**：① 无忘记密码/重置流程（管理员也无法重置，只能 deactivate + 重注册）② 无 2FA ③ 邀请码无过期时间（auth_repository 有 is_active 无 expires_at）④ 登录无"记住我"语义（token 固定 24h，cookie max_age=86400 但 token 本身 24h）
- **实现路径**：① admin 界面"重置密码"（输入新密码 → 重新哈希，S）② 邀请码加 expires_at（S）③ 2FA（TOTP，M）

## G4-6 HTTPS 与公网体验 [P1][M]

- **现状**：HTTPS 需手动提供 cert/key（server.py:750-757，失败静默回退 HTTP——**用户可能以为加密实际明文**）；Cloudflare 隧道为 trycloudflare 临时 URL（重启失效）
- **缺口**：① 隧道 URL 变化无通知（复制给别人的链接失效）② HTTPS 回退无警告 UI
- **实现路径**：① 隧道状态变化 → Toast/托盘通知 + 状态栏显示（S）② 启动隧道前若未配 HTTPS 显示安全提示（S）③ 长域名支持（cloudflared named tunnel，需用户 CF 账号，M）

## G4-7 速率限制不可配置 [P2][S]

- **现状**：`RateLimiter`（security.py:18-59）参数构造时传入（默认 100-1000/分钟）；分享设置对话框无"速率限制"配置项（IP 黑名单有）；认证限流固定 10 次/5 分钟
- **实现路径**：设置项 `lan_rate_limit` 热加载（reload_settings 已有机制，S）

## G4-8 WebSocket 连接上限硬编码 [P2][S]

- **现状**：`MAX_WS_CONNECTIONS=50`（ws.py:14）常量；无配置、无超限提示（返回 1013 静默关闭）
- **实现路径**：AppSettings 配置 + 超限响应携带提示信息（S）

## G4-9 无"仅管理员可访问"模式 [P2][M]

- **现状**：认证模式只有 key/password/user/none；无"关闭 guest 浏览"的全局开关（guest 权限走三个独立设置，开启/关闭分散）；无"库内敏感子目录对 guest 隐藏"能力
- **实现路径**：设置页"访客访问"总开关 + `lan_guest_list/preview/download` 联动；可选 `hidden_paths` 配置（PathGuard 后二次过滤，M）

## G4-10 无下载限速/断点续传 [P2][L]

- **现状**：FileResponse 全速传输；无 Range 处理（aiohttp FileResponse 自带部分 Range 支持？——响应头无 Accept-Ranges 显式声明）；浏览器侧下载无队列
- **实现路径**：多用户大文件场景下按 IP 限速中间件（L，个人场景优先级低）

## G4-11 服务器状态观察不足 [P2][M]

- **现状**：`/api/stats` 有 connections/requests/bytes/uptime，但无：按端点统计、错误率、活动日志导出、内存占用；`PerformanceRecorder` 遥测在服务器侧无查看入口（桌面侧也无 UI 展示）
- **实现路径**：分享设置"性能"页：recorder 事件表 + 导出（M）
