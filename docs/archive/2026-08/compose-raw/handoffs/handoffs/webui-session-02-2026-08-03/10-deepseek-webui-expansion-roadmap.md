# 10 — DeepSeek WebUI 初期扩展计划映射

## 1. 文档定位

DeepSeek Docs 早期 WebUI 规划主要分为三层：

- `DeepSeek Docs/功能缺口分析/05-WebUI.md`：G5-1～G5-9 功能缺口；
- `DeepSeek Docs/未来方向/03-橱窗化双端UI设计.md` 与 `04-DeviantArt式橱窗前端UI形态设计.md`：后续 Storefront/画廊化方向；
- `DeepSeek Docs/前后端分离改造计划/02-推荐实施计划.md`：A/B/C 架构迁移及 B3 WebUI realtime 试点。

这些文档是路线来源，不是当前完成状态。当前状态以代码、测试和 [`01-current-state.md`](./01-current-state.md) 为准。

## 2. G5 初期缺口映射

| 初期编号 | 原计划 | 当前代码状态 | 下一步判断 |
|---|---|---|---|
| G5-1 | 备注、URL、标签编辑 | InfoPanel 仍主要是读取；Share/Tags API 存在，但 metadata 编辑闭环和普通用户权限尚未形成 | 需要先做后端契约和权限设计，再做 InfoPanel 编辑态；暂不伪造 PUT meta |
| G5-2 | 上传组件、拖放和上传进度 | 当前 WebUI 没有上传 UI；`upload` capability 不能视为端点已交付 | 后端 upload route 和路径/权限/取消语义明确后再做；复用进度组件的视觉语言 |
| G5-3 | 批量选择、批量下载、未来批量标签 | 当前 BrowsePage 已有选择模式、批量 ZIP 和 DownloadProgress；批量标签仍未闭合 | 标记为“下载已落地、批量标签未落地”，不要重复开发下载基础设施 |
| G5-4 | 大目录虚拟滚动与 files 分页 | 当前 `ProjectGrid` 全量渲染 items，`/api/files` 无 offset/limit 契约 | 先做真实数据 benchmark，再决定前端窗口化、后端分页或两者；视觉 Grid 设计必须保留可替换的 virtualization 边界 |
| G5-5 | 搜索历史和快捷筛选 | 当前有防抖搜索、排序和标签过滤，但没有完整搜索历史/最近目录 UX | P2；先确定 localStorage 隐私、清理和键盘导航，再实现建议下拉 |
| G5-6 | 亮/暗模式切换 | `useTheme`、`am_theme`、`.light`、系统偏好监听和测试已存在；全页面视觉 parity 仍需验收 | 视为“基础能力已落地、视觉一致性未闭合”，纳入视觉 token/截图任务 |
| G5-7 | 统一错误反馈、401/503 页面 | client 已分类 401/403/429，部分组件有 Toast；统一 503/网络错误页面和所有 mutation feedback 仍不完整 | P1；先补错误状态矩阵和测试，再统一 Toast/InlineError/Retry 组件 |
| G5-8 | 分享创建、管理、QR | ShareDialog 已能创建带密码、期限、限次、预览选项的分享并复制 URL；QR 和完整管理/接收验收未闭合 | 先补 ShareReceivePage 与 ShareDialog 测试，再决定 QR 是否属于当前产品范围 |
| G5-9 | WebUI 运行时契约、WebSocket 集成、Playwright | WebUI 有 DTO fixture、RealtimeContext/useWebSocket 测试和 Chromium realtime acceptance；真实 LAN/移动/第二客户端矩阵仍未闭合 | 继续补 API factory contract、真实浏览器和跨端门禁，不重复建立第二套 realtime transport |

## 3. 前后端分离计划与当前状态

### 阶段 0：基线稳定

已完成。当前交接包以外置 Git HEAD、WebUI 37 files/292 tests、typecheck/build 作为前端基线。历史 `1590 passed` 等数字不再作为当前门禁。

### 阶段 A：服务边界

A1/A2/A3 已在当前架构基线落位：应用服务与 LAN route 分层、Runtime-owned sharing、按端 lazy projection 等边界已有证据。WebUI 任务不应把业务校验重新放回组件或 route。

### 阶段 B：桌面直连与 realtime

B1 已完成 Runtime-owned Auth/Share；B2 桌面缩略图服务边界已在 baseline；B3 的 TAGS 最小闭环和 WebUI recovery 代码已有，但真实浏览器、Desktop/Web 最终一致性和发布环境验收仍待完成。

### 阶段 C：契约化

C1 “单一来源契约/生成 TS 类型或 OpenAPI”仍是可选后续。当前优先级是先补方法级 contract tests 和矩阵；没有证据前不要大范围引入代码生成。

C3 Desktop 投影全面统一不是第二会话的前端主线；WebUI 继续使用 `RealtimeContext` 的 domain invalidation，不复制 Desktop Qt signal 体系。

## 4. Storefront/画廊化初期计划

未来方向文档提出同一 SPA 双视图域，而不是拆成两个应用：

```text
/store/*  → Storefront：公开、图片优先、移动优先、无管理 UI
/app/*    → Dashboard：登录守卫、现有 AppLayout、管理/工作台
/s/:id    → 兼容保留的分享接收入口
```

### S1：店面只读（未来）

复用 Landing 预览墙、Browse 网格、ProjectCard、DetailPage 和现有 `/api/home`、`/api/projects`、`/api/thumbnails`，只增加 StorefrontLayout 与域守卫。这个阶段不需要价格、支付、订单或新下载代码。

### S2：商品化（未来）

需要商品字段、价格和公开 item API；不能在当前 WebUI 中通过前端临时字段伪造。

### S3：交易闭环（未来）

订单、支付和交付可复用限次分享，但属于新的产品范围，不进入当前 WebUI 第二会话。

### S4：Dashboard 完善（未来）

店面配置、商品管理、订单/统计等属于后续 Dashboard 任务，必须保持与现有 admin capability 和 LAN API 契约分离。

DeepSeek Docs 同时明确排除社交功能：评论、关注、消息、推荐、徽章不进入路线。

## 5. 第二会话的合并顺序

1. 先补 G5-9 的前端直接证据：ShareReceivePage、API factories、App routing、i18n parity。
2. 再完成 G5-7 的 loading/empty/error/retry/unauthorized 视觉与反馈统一。
3. 再按 [`09-visual-optimization-and-design-system.md`](./09-visual-optimization-and-design-system.md) 做 Grid、Card、Detail、Mobile 和 reduced-motion 视觉切片。
4. 真实数据证明需要后，再决定 G5-4 virtualization 和性能重构。
5. 最后单独立项 S1 Storefront，不把长期商业化方向混进当前 Browse/Admin 改造。

## 6. 计划更新规则

- 每个任务一个 commit；行为变化先补测试。
- 计划状态只能在代码、测试或浏览器证据出现后更新。
- “已实现”与“已验收”分开记录。
- 后端协议、权限、分享 token 和 realtime cursor 变化必须同步 contract tests、LAN tests 和本目录。
- 如果任务被环境阻塞，记录阻塞原因和已执行的替代验证，不把阻塞写成失败或成功。
