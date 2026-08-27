# AssetsManager 会话优化汇总与后续路线

> **状态**：已完成工作与后续建议的交接索引
> **日期**：2026-07-15
> **范围**：本仓本次持续优化会话；不替代 `docs/architecture.md`、ADR、或各 Batch 的交付报告。

---

## 1. 当前结论

AssetsManager 已从以迁移为主的架构收口阶段，进入“**以可验证的小批次修复稳定性、交互一致性与性能**”的阶段。本会话没有重做产品视觉语言；所有桌面修复均遵循以下边界：

- 优先修复已复现或独立审查确认的问题。
- 异步工作必须绑定原始 `LibrarySession`、任务代次或 Qt 对象存活状态。
- 运行时语言与 UI 缩放是独立生命周期，不能假定构造期 `tr(...)` 或固定 `scaled_px()` 会自动刷新。
- 刷新既有界面时只原位更新文案、样式或受控几何；不得重建用户输入、选择、滚动位置、动态列表或进行中的工作。
- 全部改动应保留现有主题、控件和交互风格，不在稳定性批次中混入视觉重设计。

本次最终完整 Python 质量门的最新成功记录为：

```text
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q

1307 passed in 90.36s
```

后续运行完整门禁时，测试总数可能因本会话新增 desktop 回归而增加；不要将历史数字视为固定基线。

---

## 2. 已优化项

### 2.1 交付安全、LAN 与 WebUI

已完成 Batch A、Batch C 的主要可靠性收口，详细证据分别见：

- `docs/compose/reports/batch-a-delivery-safety.md`
- `docs/compose/reports/batch-c-lan-webui-reliability.md`

已实现的关键契约：

- React SPA 静态资源公开引导，而受保护 API 保持认证边界。
- 浏览器采用同源 HttpOnly Cookie；密码分享采用限定到 share 路径的 HttpOnly `share_token`。
- 仅显式 API 客户端请求保留 Bearer token 兼容，避免浏览器暴露 token。
- WebSocket 拒绝 query token，使用有限客户端数、唯一 PING 负载关联 PONG、慢客户端有界清理和前端有限重连。
- 下载响应安全处理文件名，批量下载维持 JSON/Blob 契约。
- React 请求以 abort、代次和 disposal 防止陈旧结果覆盖；导航变更会使旧 tag/metadata 请求失效。
- LAN 静态 fallback 仍是降级路径，不宣称与 React SPA 同等功能。

### 2.2 文件操作、Undo/Redo 与会话一致性

已完成 Batch B、Batch D 的主要收口，详细证据见：

- `docs/compose/reports/batch-b-file-operation-consistency.md`
- `docs/compose/reports/batch-d-scoped-library-services.md`

已建立的关键不变量：

- FileList 的重命名、复制、移动、导入、回收站/永久删除、恢复、Undo/Redo 经 session-bound `FileOperationService` 执行。
- 文件系统成功后才协调 metadata、thumbnail、asset index，再发布 session-scoped domain event。
- Undo/Redo 按 canonical `LibrarySession` 隔离，且仅在执行成功后移动历史。
- 面板和异步 worker 捕获原始 session、服务、路径与代次；切库或同根重开后不能将旧工作写入新库。
- 会话关闭拒绝新工作、排空 lease，并避免同线程 reentrant close 死锁。
- presentation 不应借由 fallback 创建 FileOperationService、UndoService、数据库连接或新 session。

### 2.3 性能与可观测性

本会话持续推进了性能测量和低风险优化切片：

- 建立目录摘要、目录首屏、搜索、缩略图队列/缓存、数据库写锁、文件命令、LAN 搜索/缩略图/下载、Grid 帧调度等性能事件。
- 增加 nightly 性能 artifact 与外接 SSD 的真实库采样，避免只以合成 microbenchmark 决策。
- 优化目录摘要 warm path 的 metadata/cache 批量读取与重复 `stat`，并实施 visible-first lazy hydration。
- 实现缩略图有界准入、字节缓存、可见区优先与有界预取。
- 优化 Grid 纹理创建节奏、合并帧调度、局部重绘、动画所有权、缩放视口锚点和旧纹理过渡，降低快速缩放/滚动的黑卡、抖动与全量重绘风险。

性能工作遵循“**先观测、再假设、再比较**”。任何后续性能改动必须保留真实库和可复现基准证据，不以单次主观流畅度判断替代数据。

### 2.4 工程治理与类型边界

已完成的工程性收口包括：

- 扩大 Pyright 覆盖并修复 FileList、Info、Sidebar、标签编辑、分享 dialog、启动窗口和若干 Qt 生命周期空访问问题。
- 修复 Qt teardown 的原生崩溃/警告路径，保持全量 suite 可重复运行。
- 收敛 application SQL 到 repository、移除无调用 legacy helper，并由 architecture boundary tests 控制新的过渡性例外。
- 统一 session-scoped domain event 到 Qt bridge 的 UI 消费路径；`core.signal_bus` 仅承载 presentation 协调，不承载应用层 mutation fact。

### 2.5 Share System

已完成 Share System 桌面端分阶段改造：专用 shell、分享链接整合、访问页、配置页、清理与可访问性修复，以及按需二维码分享恢复。

当前原则：

- Share System 的浏览器认证与下载安全契约以 LAN 报告为准。
- 桌面 Share System 维持独立导航 shell；不要把它误当成普通 `TabbedDialog` 再做通用重建。
- 二维码分享按需生成/展示，避免在无分享链接或无可用地址时产生误导性 UI。

相关设计资料：`docs/Suggestions/share-system-desktop-DESIGN.md` 与 `docs/Suggestions/share-system-desktop-redesign-2026-07-15.md`。

### 2.6 桌面 UI 可靠性

本会话完成了由 UI 审查驱动的独立小批次修复：

#### 生命周期、窗口与 workspace

- 延迟 Qt 回调加入 generation/存活防护，避免 rebuild 或 shutdown 后访问失效 widget/item。
- 缩略图调度把 admission 拒绝视为终止结果，worker completion 不再捕获已关闭 dialog。
- hide-to-tray 使用 `QSystemTrayIcon.isSystemTrayAvailable()` 判定实际能力。
- Workspace 以 canonical library root 去重；不提供尚不存在真正 clone/session 模型的 Duplicate 功能。
- Sidebar 新增 section visibility 时兼容既有 `sidebar_depth_cfg`，恢复后立即投影到已创建控件。

#### FileList 与 Info 运行时语言

- FileList filter 的显示文案与语义 key 分离：以 `FILTER_CATEGORY_LABELS` 的 canonical key 存入 combo `userData`。
- 语言刷新替换显示项时阻断 combo signal，保留当前 semantic filter、排序、视图状态。
- Info 原位刷新静态标签，不重绘动态 metadata、tag、链接或当前选中资源。
- 已补齐 `filelist.filter.*` 的英语、中文和日语翻译。

#### 共享 Dialog 刷新契约

`TabbedDialog` 现在提供显式 opt-in 的运行时刷新生命周期：

- 所有 dialog 保留主题订阅行为。
- 仅 `supports_runtime_refresh = True` 的子类订阅 `language_changed` 和 `ui_scale_changed`；未迁移 dialog 不会出现局部翻译。
- tabbed chrome 可原位刷新 OK、Cancel、Apply 与有注册 key 的 tab 标题。
- `closeEvent()` 和 `done()` 都会断开总线；后者覆盖 `exec()` 中 `accept()`/`reject()` 仅隐藏而不走 close event 的 Qt 路径。
- 已显示 dialog 再次 show 时会重新连接，不会累计回调。
- runtime scale hook 接收 scale 值。子类不得通过通用 refresh 重建 tab、动态列表或业务 worker。

#### 已迁移 dialog

| Dialog | 已覆盖行为 | 必须保持的状态 |
| --- | --- | --- |
| `SettingsDialog` | 标题、tab、背景/主题/语言/缩略图文案、标准按钮、radio 文案；外部 scale 同步 slider/百分比；布局、radio group、按钮约束与最小尺寸缩放。 | 当前 tab、背景路径、checkbox、slider、选中 theme/language/quality、进度与按钮禁用状态。 |
| `TagEditorDialog` | 标题、分组、placeholder、按钮/tooltip；chip 的主题/缩放视觉重建；根布局和列表/进度约束刷新。 | tag 输入草稿、建议筛选、选中建议、滚动、删除 worker/progress、修改标记。 |
| `PluginManagerDialog` | 标题/搜索 placeholder、选中详情的 status/字段/enable-disable 文案；左栏、card、detail panel 的局部主题/缩放 presentation。 | card 实例、选中插件、搜索过滤、列表滚动、toggle 状态；刷新不能调用 `_load_plugins()` 或产生 enable/disable 服务调用。 |

桌面回归覆盖位于：

- `tests/desktop/test_settings_dialog.py`
- `tests/desktop/test_tag_editor_dialog.py`
- `tests/desktop/test_plugin_manager_dialog.py`

这些测试必须继续真实显示 dialog 并通过 signal bus 触发语言/缩放，以覆盖连接、断连、重连和状态保留；直接调用 handler 不能替代生命周期测试。

---

## 3. 尚未完成或应继续验证的方向

以下不是已交付承诺，应作为后续独立、可验证批次处理。

### P0：对外分享与部署验证

- 在真实 LAN、代理、sleep/wake、丢包和多客户端环境观测 WebSocket heartbeat。
- 完成手工浏览器旅程：登录、Browse/Detail、密码分享、原生下载、二维码访问、移动端、forced legacy fallback。
- 跟进 WebUI `npm ci` 报告的依赖漏洞；先评估升级影响，不执行无审查的强制 audit fix。
- 继续审计下载/ZIP 上限、文件名、分享路径、日志中凭据暴露及插件信任模型。

### P1：会话、事件与过渡 API 收口

- 继续缩减 `LibraryContext` / legacy current-library / singleton fallback 的兼容层，只在有明确外部/持久化需求时保留。
- 收敛 domain event 与 `core.signal_bus` 的边界：应用 mutation 只走 session-scoped domain event + Qt bridge。
- 移除剩余 presentation read fallback、service locator 旁路与 inline SQL，但不得为了“清理”破坏 bootstrap-free 测试隔离。

### P1：桌面 UI 生命周期后续批次

- 单独迁移 `SharingSettingsDialog` 的 runtime language/scale refresh。它是自定义多页 shell，不使用 base tabbed button box；必须先为导航、底部按钮和各页静态文本建立原位绑定，禁止全页重建。
- 审计其余 `TabbedDialog` 子类，逐个 opt-in，不允许批量打开 `supports_runtime_refresh`。
- 在已迁移 dialog 中继续补充：运行中 worker/progress、滚动位置、焦点、disabled state 与外部 theme/scale 变化的回归。
- 后续再处理 self-painted Grid 的全局 scale relayout、语义 theme token 统一和可访问性，不与当前 dialog 生命周期批次混合。

### P2：大 UI 模块拆分与产品交互

- 在保持 FileList command boundary 的前提下，继续拆分 Info、Sidebar、FileList orchestration 与 `window.py` 的生命周期协调职责。
- `sharing_settings_dialog.py` 仍是大型模块；优先抽取纯 presentation renderer/页面 controller，再考虑业务行为迁移。
- FileList 后续产品阶段应继续执行明确的操作反馈、批量任务预览、状态呈现和命令帮助计划，而不是再引入平行命令框架。

### P2：性能阈值与真实场景

- 将性能 artifact 从趋势观察升级为带噪声说明的阈值，分别覆盖 1k/10k 目录、冷/热缩略图、搜索、LAN P95 和 Grid 滚动缩放。
- 继续验证目录摘要的 cache-miss N-read fallback、同路径陈旧 summary merge 抑制、桌面 bootstrap cache 注入和 list-view hydration。
- Grid 视觉问题必须用坐标、帧/texture telemetry 和真实库样本复现；此前“空白区域点击”已被坐标测试证明是误判，不应重新引入无证据布局改动。

### P3：产品战略与双前端

- 明确主战略：本地专业资产工作台、LAN 分享网关，或将 application/domain/repository 抽为可复用内核。
- 若继续 WebUI 演进，确定 React SPA 替换旧 `lan/static` 的期限；在此之前，legacy 只维持必要的安全与离线 fallback，不做平行功能开发。
- 建立大库 SLA、首次引导、备份恢复、安装升级和非技术用户错误文案的产品验收标准。

---

## 4. 后续实施规则

每个后续批次应：

1. 先阅读 `docs/agent-quick-map.md`；跨层或高风险变更同时阅读 `docs/agent-architecture-map-deep.md`。
2. 用可复现症状、现有测试或独立 review 确认问题后再修改。
3. 保留 unrelated worktree changes；不要编辑忽略的 `Project/` 备份目录。
4. 为行为变更增加 focused regression，并在涉及 Qt 生命周期时覆盖真实 signal/event path。
5. 使用 `PathGuard`、`validate_path()` 或 `validated_existing_key()` 处理 LAN 路径。
6. 新 UI 像素值使用 `scaled_px()`/`scaled_pt()`，颜色使用 theme token。
7. 完成前运行：

```powershell
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

涉及 WebUI、打包或架构边界时，再按 `docs/testing.md` 增加相应 gate。

---

## 5. 关联文档

| 文档 | 用途 |
| --- | --- |
| `docs/architecture.md` | 当前分层、服务、事件与过渡架构事实。 |
| `docs/architecture-optimization-roadmap-2026-06-19.md` | 历史架构优化路线。 |
| `docs/compose/reports/batch-a-delivery-safety.md` | SPA、打包、认证和 thumbnail 切库安全。 |
| `docs/compose/reports/batch-b-file-operation-consistency.md` | 文件操作和 Undo/Redo 一致性。 |
| `docs/compose/reports/batch-c-lan-webui-reliability.md` | LAN/WebUI、分享与 WebSocket 可靠性。 |
| `docs/compose/reports/batch-d-scoped-library-services.md` | scoped service、session teardown 和异步身份。 |
| `docs/Suggestions/project-assessment-and-roadmap-2026-07-19.md` | 产品/架构中长期建议，非已承诺路线。 |
| `docs/Suggestions/share-system-desktop-DESIGN.md` | Share System 桌面设计依据。 |

## 6. 变更记录

| 日期 | 说明 |
| --- | --- |
| 2026-07-15 | 初版：汇总本会话架构、可靠性、性能、Share System 与桌面 UI 优化，并记录后续分批方向。 |
