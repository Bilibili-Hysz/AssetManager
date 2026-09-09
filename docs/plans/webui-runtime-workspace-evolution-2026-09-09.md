# WebUI Runtime 工作台演进计划

> 排期更新（2026-09-09）：用户明确提出重写 WebUI 与桌面 ShareSystem；当前主线以[分享体验重写方案](sharing-experience-rewrite-2026-09-09.md)及[周计划](weekly-priorities-2026-09-14.md)为准。本文 Phase 1 的已有工作区改动保留并纳入新主线验收；Phase 2/3 等架构扩展不占首批预算。本文仍作为技术演进备忘，不表示后续阶段已启动。

状态：`IN_PROGRESS`  
基线：2026-09-09 当前 `master` 工作区  
范围：桌面入口、LAN/WebUI 运行上下文、实时状态、长任务和前后端契约

## 1. 目标

将 WebUI 明确建设为一个以 `LibraryRuntime` 为边界的浏览器工作台。桌面端负责库生命周期、LAN 服务生命周期和浏览器入口；WebUI 负责浏览、搜索、预览、元数据操作、下载和远程协作；桌面端与 WebUI 共享 Application Services，不复制业务规则。

本计划保留当前 React SPA + aiohttp + 同进程 Runtime 的技术路线。第一阶段优先改善可观察性和边界契约，再逐步处理长任务、Command/Query 分层和更深的服务解耦。

## 2. 运行模式

WebUI 需要显式识别三种访问模式：

| 模式 | 入口 | 默认能力 | 生命周期 |
|---|---|---|---|
| `local` | 桌面端“在浏览器中打开” | 当前库的完整本机能力 | 绑定桌面进程和当前 Runtime |
| `lan` | 局域网地址、二维码 | 按用户/访问密钥授权的浏览、预览、下载和可选写操作 | 绑定 LAN server 和当前 Runtime |
| `share` | `/s/:shareId` | 分享资源范围内的只读或下载能力 | 绑定 ShareService 的分享授权 |

服务端通过 `/api/info` 返回访问模式、库身份和 Runtime 游标。前端所有功能入口以服务端 capabilities 为准，页面不自行推断权限。

## 3. 目标架构

```text
PySide6 Desktop / Browser React SPA
            |
            v
   LAN HTTP + WebSocket Adapter
            |
            v
   Application Query / Command Services
            |
            v
   LibraryRuntime + LibrarySession
            |
            v
   Repository / Domain Event / File System / SQLite
```

实时通道继续采用控制面与数据面分离：

- WebSocket 只发送 `runtime_ready`、`projection_invalidated` 和 Job 状态等轻量事件；
- HTTP API 返回权威投影数据；
- `epoch/revision` 用于检测 Runtime 更换、乱序和事件缺口；
- 前端缓存按 Runtime、身份、路径和筛选条件隔离。

## 4. 分阶段执行

### Phase 0：基线与契约盘点（已完成）

- [x] 确认桌面启动链：`main.py/run.py -> app.main -> StartupWindow -> MainWindow`。
- [x] 确认 `LibrarySession -> LibraryRuntime -> LibraryScopedServices` 是当前库边界。
- [x] 确认 WebUI 是 LAN aiohttp 服务托管的 React SPA，不是 Qt WebView。
- [x] 确认 WebSocket 使用失效通知，HTTP 重新拉取数据。
- [x] 确认现有 `/api/info` 已返回库信息、认证模式、principal 和 capabilities。
- [x] 确认桌面状态栏存在一处 URL 手工拼接路径，需要统一到 server status。

### Phase 1：运行上下文和连接状态（本轮）

目标：让浏览器知道自己处于哪种访问模式、绑定哪一个 Runtime，并在服务或实时通道异常时给出可恢复的反馈。

- [ ] `/api/info` 增加 `client_mode`、`runtime_epoch`、`runtime_revision`。
- [ ] 保证未认证请求的响应仍然安全、稳定、兼容登录页。
- [ ] WebUI 类型补齐运行上下文字段。
- [ ] 增加全局 `ConnectionStatusBanner`：
  - 服务不可用时提供重试；
  - WebSocket 重连或断开时提供状态反馈；
  - Runtime 恢复失败时提供显式恢复操作；
  - 正常状态不占用页面空间。
- [ ] 桌面分享状态栏统一使用 `LanServer.status()['url']` 或统一 URL adapter。
- [ ] 增加后端契约、前端组件和桌面入口回归测试。

验收标准：

1. `/api/info` 对 guest、local_ui、user、share principal 都能返回合法上下文。
2. WebUI typecheck 和相关 Vitest 测试通过。
3. HTTPS server status 返回的地址可被桌面状态栏原样复制。
4. 服务不可用、WS 恢复失败和正常连接三种状态都有明确测试。

### Phase 2：统一查询/命令边界

目标：减少页面内业务编排，让桌面端和 WebUI 调用同一套 application use case。

- [ ] 为文件重命名、批量标签、元数据更新、收藏和 Collection 操作定义 Command DTO。
- [ ] 将 API handler 收敛为“请求解码 → 调用 Application Service → DTO 编码”。
- [ ] 为 query key 引入统一工厂，包含 `runtime_epoch`、身份 generation 和查询参数。
- [ ] 将乐观更新、失败回滚和 projection invalidation 规则集中到 mutation hooks。
- [ ] 清理页面直接拼接 API 路径和重复的权限判断。

验收标准：

- 同一个业务规则只在 Application Service 校验一次。
- 桌面和 WebUI 的错误码、验证消息和 revision 行为一致。
- 页面组件只保留交互状态，不持有 SQLite、Repository 或 transport 语义。

### Phase 3：Job 与后台操作

目标：让导入、批量 ZIP、缩略图构建和后台扫描脱离单次 HTTP 请求生命周期。

建议接口：

```text
POST /api/jobs
GET  /api/jobs/{id}
POST /api/jobs/{id}/cancel
```

WebSocket 事件：

```json
{
  "type": "job_progress",
  "job_id": "...",
  "phase": "thumbnail",
  "completed": 80,
  "total": 120
}
```

- [ ] 先为批量下载和导入建立 Job 状态模型。
- [ ] 增加任务取消、失败原因、重试和完成后的 projection invalidation。
- [ ] WebUI 增加全局任务抽屉或底部任务条。
- [ ] 保留单文件流式下载的直接响应路径。

验收标准：

- 浏览器刷新或短暂断线不会丢失任务状态。
- 任务取消具有幂等性。
- Runtime 关闭时所有任务进入可解释的 cancelled/failed 状态。

### Phase 4：契约生成和多库边界

- [ ] 将 `/api/info` 纳入 `lan/dto.py` 的稳定 DTO 与 TypeScript 生成流程。
- [ ] 扩展 `scripts/gen_ts_types.py --check` 覆盖 ServerInfo。
- [ ] 明确一个浏览器标签页对应一个 Runtime。
- [ ] Runtime epoch 变化时清理旧缓存并显示库切换/服务重启提示。
- [ ] 为 local、lan、share 三种模式建立 Playwright 验收矩阵。

## 5. 具体文件边界

### 当前阶段

- 后端：`AssetsManager/lan/routes/system.py`、必要的 LAN contract tests。
- 桌面：`AssetsManager/window.py` 及对应 desktop test。
- 前端：`webui/src/types/api.ts`、`webui/src/App.tsx`、连接状态组件、i18n 和组件测试。
- 文档：本计划文件及阶段完成记录。

### 后续阶段

- Application commands：`AssetsManager/application/`。
- Job runtime：`AssetsManager/application/`、`AssetsManager/lan/routes/`、`webui/src/stores/`。
- 契约生成：`AssetsManager/lan/dto.py`、`scripts/gen_ts_types.py`、`webui/src/types/contracts.ts`。

## 6. 测试策略

- Python：`/api/info` principal/mode/runtime contract、HTTPS URL 状态回退、切库后 Runtime 游标变化。
- WebUI：ConnectionStatusBanner 状态矩阵、AuthContext serverInfo 兼容、RealtimeContext 恢复失败。
- 集成：local_ui 登录/打开、LAN guest/user、share principal、WS 重连和 epoch 更换。
- E2E：浏览器刷新深链接、移动宽度、键盘可达性、服务重启后的可恢复反馈。

## 7. 风险与控制

| 风险 | 控制措施 |
|---|---|
| 修改 `/api/info` 破坏登录页 | 字段只增不删；保留现有 auth/share/library_stats 结构；加入 contract test |
| Runtime 切换后缓存串库 | 使用 `runtime_epoch` 作为缓存命名空间；切换时清理旧查询 |
| WS 断线导致用户误以为数据实时 | 显示连接/恢复状态；恢复失败提供手动重试 |
| 桌面/LAN URL 不一致 | 统一使用 server-owned status URL，保留兼容回退 |
| 大范围重构引入回归 | 先做边界和可观察性改动，再迁移命令和 Job |
| 用户已有工作区改动被覆盖 | 每个阶段使用独立文件边界；不执行 reset、stash 或批量格式化 |

## 8. 完成定义

本计划的长期完成定义是：

1. 三种 WebUI 访问模式在服务端和前端都有明确契约。
2. 桌面端、LAN API 和 WebUI 共享 Application Service 业务规则。
3. Runtime、身份、缓存和实时状态不会跨库或跨用户污染。
4. 长任务可观察、可取消、可恢复。
5. 关键 API 和 TypeScript 类型由单一契约生成或严格校验。
6. local、lan、share、重连、Runtime 更换和桌面退出均有自动化验收。
