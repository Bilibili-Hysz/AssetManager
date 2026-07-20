# AssetsManager 项目评估与路线建议

> **状态**：方向未定，仅供参考
> **日期**：2026-07-19
> **范围**：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak` 只读审阅（结构、文档、依赖、核心模块、测试与 CI）
> **说明**：本文不代表已选定产品方向；在明确主目标前，建议以本仓为基线参考，避免并行大重写。

---

## 1. 项目画像（当前状态）

| 维度 | 现状 |
|------|------|
| 定位 | **本地资产库桌面端（PySide6）+ 局域网/外网分享（aiohttp）** 双端一体 |
| 规模 | 约 174 源码 py + 约 96 测试 py，合计约 **5.7 万行**；测试约 **2.2 万行** |
| 质量门禁 | 文档记录 **603 passed / 0 warnings**；ruff 全仓、pyright 有范围、architecture boundary 测试 |
| 演进阶段 | 已完成大量分层重构（约 156 个 phase 记录），处于 **迁移后期 / 收口阶段**，不是从零原型 |
| 目录语境 | `old-bak` + 旁侧有 `Seeker`、`AssetsManager_Web_Gate_Design`、多个 bundle/zip → 更像 **成熟备份/基线**，而非废弃玩具 |

**技术栈核心：**

- Python 3.12–3.14
- PySide6（桌面）
- SQLite（WAL）
- aiohttp（LAN API + WebSocket）
- Pillow / segno
- 可选 Cython 热点加速
- PyInstaller 打包
- React + Vite 新 WebUI（与旧 `lan/static` 并存）

**双端共享业务的方向**已在 `docs/architecture.md` 中明确：Desktop 与 LAN 应共用 application services，而不是复制业务逻辑。

---

## 2. 优势

### 2.1 产品差异化清晰

- 不是“又一个文件管理器”，而是 **资产库工作台**：标签、元数据、缩略图、项目视图、撤销、多库切换。
- **桌面管理 + LAN/分享** 同一套业务服务，方向正确。
- 分享链路完整：用户/邀请码、分享链接、QR、Cloudflare Tunnel、下载/ZIP、WebSocket。

### 2.2 工程成熟度高于典型个人项目

- 明确分层：`domain` → `application` → `repositories` → presentation（desktop / LAN）。
- **DI / LibrarySession / scoped services** 方向已落地，并有 ADR（0001 / 0002）。
- **架构边界测试**（`tests/unit/test_architecture_boundaries.py`）把分层从口号变成可执行约束。
- 测试从约 90 → **603**，覆盖 unit / integration / desktop / lan / perf。
- CI 覆盖 lint、typecheck、webui、Windows 打包 smoke、多 Python 版本。
- 安全与并发已做过专门 pass（path guard、auth middleware、write lock、资源清理等）。

### 2.3 性能意识与可观测性

- Cython 编译热点（如 `cache` / `color_utils` / `format_utils` / `asset_filters`）。
- 有 perf baseline、nightly perf workflow、目录扫描去重、缩略图 key 缓存、LAN `to_thread` 等。
- 崩溃处理、主题/HiDPI、插件宿主 API 具备可产品化雏形。

### 2.4 文档与协作资产厚

- `architecture`、`development`、`testing`、`lan-security`、roadmap、session handoff、agent map 齐全。
- 对 AI / 多人接力开发友好（这也是能走到 150+ phase 的原因之一）。

---

## 3. 短板与风险（按优先级）

### P0 — 安全与信任边界（对外能力相关）

仓库内 `docs/architecture-optimization-roadmap-2026-06-19.md` 已点名，仍需持续关注：

- WebSocket 认证 / 连接治理。
- 查询参数鉴权（`?token=` / `?key=`）有泄露到日志/历史/Referer 的风险，应弃用。
- 插件实质是 **本机全权 Python 代码**；若权限只 warn 不 block，容易产生“假隔离”错觉。
- 下载文件名头、分享路径规范化、ZIP 体积上限等边角。

> 对“纯局域网工具”可接受；一旦强调 **外网 tunnel / 多用户**，这些就是产品级风险。

### P1 — 架构过渡态未完全收敛

- `LibrarySession` / `LibraryContext` / legacy current-library **三态并存**。
- `domain.event_bus` 与 `core.signal_bus` **双事件系统**，存在重复或漏通知风险。
- `UndoService` 仍偏全局，而撤销历史应按库 / session 隔离。
- 部分 service 仍有 inline SQL；Auth / Share 职责仍有交叉。
- Presentation 仍有 fallback allowlist（边界测试在“容忍迁移”，不是“已干净”）。

### P2 — UI 复杂度集中（维护成本）

最大文件仍偏“上帝组件”，例如：

- `panels/info.py` ~1286 行
- `panels/file_list/_grid_widget.py` ~1499 行
- `panels/file_list/_base.py` ~1079 行
- `panels/sidebar.py` ~906 行
- `window.py` ~658 行
- `dialogs/sharing_settings_dialog.py` ~1715 行

file_list 虽用 mixin 拆文件，但 **业务编排仍散落在 UI**，测试也跟着变重。

### P3 — 双前端与产品焦点

- 旧：`AssetsManager/lan/static`（大体积 vanilla JS/CSS）
- 新：`webui/`（React + TS + Tailwind，CI 已构建）
- `lan/routes/pages.py` 优先 SPA、否则回退旧 static → **迁移中双栈**，长期拖累一致性与打包体积。

### P4 — 平台 / 生态约束

- 重度 Windows + PySide6；跨平台不是第一公民。
- Python 3.14 很前卫，但生态 / 打包 / Cython 二进制兼容成本更高。
- 插件生态几乎为空（`booth_link`、`download_tracker` 级别），API 文档多于真实插件市场。
- 目录名 `old-bak` + 多备份包，说明 **主线叙事 / 产品身份** 可能已开始分流（例如旁侧 `Seeker`）。

### P5 — 产品层尚未“封顶”

工程强，但若目标是给他人用，仍缺：

- 稳定版本语义与升级承诺
- 大库（10 万+ 资产）真实场景 SLA
- 一键安装体验、首次引导、备份恢复
- 非技术用户的错误与权限文案

---

## 4. 建议未来路线（可执行，方向未定时可作参考）

与 `docs/architecture-optimization-roadmap-2026-06-19.md` 对齐，并补上产品层优先级。

### 4.1 近端（约 2–4 周）：收口与安全

1. **LAN / WS / 下载 / 分享路径** 安全项闭环（Roadmap Phase 1）。
2. **LibrarySession 唯一公开边界** + 面板注入 scoped services + Undo 按库隔离（Phase 2）。
3. 事件收敛：业务只发 domain event，UI 只经 `_event_bridge`（Phase 3）。
4. 明确插件信任模型：写成用户可见的 **“受信任本地扩展”**；高危权限改为硬拒绝。
5. 质量门禁保持：

```powershell
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
python -m pytest tests/unit/test_architecture_boundaries.py -q
```

### 4.2 中端（约 1–2 月）：产品主路径变薄

1. **选定单一 Web 前端**：完成 React SPA 替换，删除或归档 `lan/static` 旧栈。
2. 拆 `InfoPanel` / file_list actions / SidebarController / 继续瘦 `MainWindow`（Phase 6）。
3. SQL 全部进 repository；Auth vs Share 职责切开（Phase 4 / 5）。
4. 性能基线升级为 **阈值**：1k/10k 列表、冷/热缩略图、LAN P95、搜索 P95（Phase 8）。
5. 打包产物只保留必要资源，减小 dist。

### 4.3 远端（季度级）：选一条主战略，避免“全能但散”

三条互斥程度较高的路线，建议最终只主攻一条：

| 路线 | 适合 | 做什么 | 不做 / 少做 |
|------|------|--------|-------------|
| **A. 本地专业资产工作台** | 个人 / 小工作室创作资产 | 标签体系、预览、插件、撤销、性能、主题 | 弱化多用户 / 公网 |
| **B. 局域网共享网关** | 工作室内资产分发 | 权限、审计、分享、移动端体验、tunnel 稳健 | 弱化重桌面特效 |
| **C. 平台内核 + 多壳** | 长期 Seeker / 新壳复用 | 抽出 headless `application + domain + repo` 为库 | 避免桌面 / Web 再复制业务 |

旁侧已有 `Seeker` 与 `AssetsManager_Web_Gate_Design` 时，**中长期较合理的默认**往往是：

> **C：把 AssetsManager 当稳定内核 / 参考实现**，新产品只做 presentation，而不是再复制一套服务层。

---

## 5. 战略判断（结合 `old-bak` 现状）

**优点一句话：**
这是一个 **架构自觉、测试扎实、双端共享服务** 的中型桌面 + LAN 资产平台，工程资产价值很高。

**短板一句话：**
仍处在 **迁移收口 + 双前端 + 大 UI 模块 + 对外安全边角** 的阶段；若没有清晰产品主线，容易继续“重构很强、对外叙事模糊”。

**在方向未定时，对本仓最有价值的用法：**

1. 当作 **行为与架构基线（golden reference）**，不要轻易大重写。
2. 若 `Seeker`（或其它新项目）是下一代：优先 **复用 / 移植 application 服务与 domain 模型**，而不是从 UI 重画。
3. 若继续打磨本仓：严格按 **安全 → Session → 事件 → 单前端 → 拆 UI → 性能阈值** 执行，停止再开平行架构实验。

---

## 6. 待决定的 3 个方向问题

在动手任何较大改造前，这三点会决定路线取舍：

1. **主目标**：继续产品化 AssetsManager，还是为 Seeker / 新项目抽内核？
2. **主要用户场景**：本机单人资产库，还是 LAN / 外网多人分享？
3. **Web 前端决策**：是否承诺在一个版本内淘汰 `lan/static`，只保留 `webui`？

---

## 7. 与仓库既有文档的关系

| 文档 | 关系 |
|------|------|
| `docs/architecture.md` | 当前架构事实来源 |
| `docs/architecture-optimization-roadmap-2026-06-19.md` | 工程侧可执行优化路线；本文与之对齐并补充产品/战略层 |
| `docs/refactor-baseline.md` | 历史重构进度与测试增长记录 |
| `docs/development.md` / `docs/testing.md` | 开发与质量门禁规则 |
| `docs/lan-security.md` | LAN 安全模型细节 |
| `docs/adr/*` | 架构决策（含 LibrarySession） |

本文 **不替代** 上述文档，只作为 **产品/架构评估建议** 归档。

---

## 8. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-07-19 | 初版：基于对仓库的只读审阅整理优势、短板与路线建议；方向未定 |
