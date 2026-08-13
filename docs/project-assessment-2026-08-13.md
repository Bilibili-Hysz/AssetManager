# 项目认知与建议（2026-08-13）

> 本文档由外部审视轮（fresh-eyes review）产出，汇总对 AssetsManager 全部代码与模块的认知、亮点、风险与改进建议。
> 审查方式：阅读 README、核心架构文件（DI/生命周期/事件系统/LAN 安全/数据层）、前端 query cache 与 API 封装、CI 配置、审查文档集（docs/full-review/），并实测验证测试收集数。
> 证据日期：2026-08-13，工作区实况。

---

## 1. 项目认知

### 1.1 是什么

一个 **Windows 桌面资产管理器（PySide6/Qt）+ 局域网分享服务器（aiohttp）+ 商城系统（React SPA）** 的复合项目，规模远超普通个人工具：

| 维度 | 规模 |
|---|---|
| Python 主包 `AssetsManager/` | 213 个文件 / ~3.0 MB（五层架构） |
| WebUI `webui/src/` | 217 个 ts/tsx / ~1.2 MB（26 页面、80 组件、27 hooks、32 API 工厂） |
| 测试 | 250 个 py（本机实测 3457/3473 collected，16 deselected）+ 683 个 TS 单测 + 53 个 Playwright E2E（含 axe-core 无障碍门禁） |
| 文档 | 255 篇 md（full-review 审查集 8 篇、ADR 3 篇、compose specs/plans/reports/handoffs） |
| LAN API | 139 条路由、24 个路由模块、6 种 principal、8 位能力掩码 |
| 数据库 | SQLite WAL，迁移 v1-v27（`db_migrations.py` 中 `CURRENT_SCHEMA_VERSION = 27`；README 技术栈表仍写 v1-v26，见 §3 文档漂移） |
| Git | master 单分支、工作区基本干净（1 个已删除的 .mimocode 计划文件）、2 个 stash、1 个与 master 零差异的本地分支 `fix/grid-zoom-interpolation`、**无远程仓库** |

### 1.2 架构认知

分层真实且纪律严明，不是纸面架构：

- **核心闭环**：`ServiceContainer`（自研轻量 DI，见 `AssetsManager/di/__init__.py`）→ `ApplicationBootstrap` 显式装配 → `LibrarySession`（operation 租约）→ `LibraryRuntime`（每库生命周期，epoch/revision/状态机，见 `application/runtime.py`）→ `LibraryScopedServices`（frozen 快照 + `_LanServicesHolder` single-flight 懒投影）。`bootstrap.py` 中锁顺序契约（holder ↔ session condition 单向嵌套）体现了极高的并发处理水准。
- **事件流**：`DomainEvent`（frozen dataclass，`domain/events.py`）→ `EventBus`（线程安全、weakref 订阅防泄漏，`domain/event_bus.py`）→ `RuntimeEventRouter` → WebSocket `projection_invalidated` + 桌面 Qt 桥。前端侧自研 query cache（`webui/src/cache/queryCache.ts`）的订阅者注册表与 entry 分离设计（identity clear 后计数存活）非常精巧。
- **安全主线**（抽查验证过）：
  - `PathGuard`（`lan/path_guard.py`）显式拒绝 C0 控制字符/NUL/NTFS ADS + `is_relative_to` 防逃逸；
  - 认证中间件 fail-closed（无凭据配置才降级 guest，否则 401，`lan/server.py::_auth_middleware`）；
  - HMAC 令牌 `ts.nonce.sig` 全程 `hmac.compare_digest` 时序安全（`domain/auth.py` 等 9 处）；
  - 双层限流（IP 滑动窗口 + LRU 驱逐 + 认证严格档，`lan/security.py`）；
  - 令牌撤销表 + 负缓存。`security.py` 顶部明确写有"无锁对象只能从事件循环线程访问"的并发契约。
- **数据层**：`schema_defs.py` 的 `SchemaObjectContract` fail-closed 校验 + `db_migrations.py` 的 SAVEPOINT 原子迁移、契约回溯校验、未来版本拒绝（`UnsupportedSchemaVersion`）——迁移系统达到生产级。
- **CI**：8 个 job（ruff / git hygiene / pyright / WebUI 单测+审计 / Windows 打包冒烟 / Windows 回归 / 真实后端 Python E2E / 3.12-3.14 测试矩阵 + 前端 Playwright 含 axe-core）。3.14 目前是 `continue-on-error`（见 §3 中危 6）。

## 2. 亮点（值得肯定）

1. **安全工程成熟度罕见**：路径遍历、时序攻击、爆破锁定、配额 CAS 防超卖、投递令牌 rotate/revoke 生命周期闭环、ZIP symlink 拒绝——每一条都有对应测试与审查记录（`docs/full-review/06-audit-results.md`）。
2. **工程卫生**：全库 `TODO/FIXME/XXX` 零残留，ruff 全绿；`main.py`/`run.py` 入口分离了崩溃展示（Qt 弹窗 + stderr 兜底）与 frozen 包冒烟自检（`--package-smoke`）。
3. **文档文化**：`docs/full-review/06-audit-results.md` 逐条记录历史审计结论、文档过时清单、技术债状态——这种"审查证据链"极少见。
4. **打包优化**：PyInstaller 262 MB → 127 MB（延迟下载 cloudflared、剔除未用 Qt 模块）；cloudflared.exe、RuntimeData、tmp、artifacts、build 均已在 .gitignore 内且未入库。
5. **前端工程质量**：`api/client.ts` 错误分类集中（401/403/429/503 单一通道）、超时与用户取消的 Abort 语义区分、429 Retry-After 头转发、非 JSON 响应结构化错误；路由懒加载、feature flag 门控、legacy 别名迁移干净。

## 3. 风险与问题（按严重度）

### 高

1. **无远程仓库 —— 最大单一风险**。全部提交只在本地，README 自述"不 commit/push"的约定意味着没有异地冗余。一旦磁盘故障，3 万行代码 + 2.5 MB 文档全部丢失。建议**立即**建立远程（私有 GitHub/Gitea 或本地裸仓库 `git init --bare` + 定时镜像）。
2. **功能范围失控风险**：完整电商栈（商品/购物车/结账幂等键/订单状态机/投递令牌/卖家面板/匿名分析/心愿单）+ 分享系统 + 资产管理，是单人维护的巨型项目。任一新功能（如 AI 打标）都会叠加测试与文档成本。
3. **超大文件单类多职责**：`library_export_service.py`（2112 行，含备份/恢复/隔离区/快速检查 5 个关注点）、`gallery_service.py`（~1800 行）、`lan/server.py`（1747 行）、`panels/file_list/_base.py`（85 KB）、`_grid_widget.py`（78 KB）。审计文档自己也承认"改动需专属测试覆盖"。

### 中

4. **文档漂移已制度化但未根除**：README 技术栈表写"迁移 v1-v26"，代码实为 v27；README 门禁数字 3469 与本机实测 collect 3457 有出入。最近已有 "document-stats drift gate" 提交，方向正确；建议把 schema 版本这类数字改成从代码注入生成。
5. **路径校验多通道**：主通道是 `routes/_helpers.py` 的 `PathGuard`，但 `image.py`（2 处）、`shares.py`（2 处）、`shop.py`（1 处）仍各自直接 `is_relative_to`。虽有回归测试，未来改动仍有绕过统一防护的回归面——建议收敛为单一入口。
6. **Pyright 在 Python 3.14 有 23 个既有错误**，而 CI 中 3.14 是 `continue-on-error: true`——3.14 实际上不是硬门禁。建议清理错误后将 3.14 转为正式门禁，或明确降级声明。
7. **6 个零消费方桌面 widget**（command_palette/file_picker/pager_overlay/theme_gallery/status_bar/title_bar）长期待接线或删除决策悬而未决。

### 低

8. 插件权限是 advisory（插件即完整 Python 进程权限，README 明示）；metadata TTL 缓存与免费配额表无全局清理（身份无限增长）；2 个 stash 与本地分支 `fix/grid-zoom-interpolation`（与 master 零差异）未清理。

## 4. 建议（按投入产出排序）

1. **【立即】建立远程备份**：私有 remote 或本地镜像仓库，恢复 push 纪律。这是当前最大的生存风险。
2. **【短期】数字类文档自动化**：把 schema 版本、测试数、路由数改为脚本生成（已有 drift gate 雏形，扩展到数字断言）。
3. **【短期】拆分三个超大文件**：`library_export_service` 按备份/恢复/隔离区拆类；`server.py` 的撤销表/负缓存/启动状态机抽独立模块；`_base.py` 与 `_grid_widget.py` 分离渲染与行为。
4. **【短期】路径校验收敛**：image/shares/shop 三处的独立检查改为调 `PathGuard` 或其导出谓词，并补"每条路由只经过一个校验通道"的契约测试。
5. **【中期】为 6 个零消费方 widget 做一次性决策**（接线或删除），避免死代码持续膨胀；清理 2 个 stash 与零差异本地分支。
6. **【中期】可观测性**：`crash_handler.py` 已具备崩溃捕获，可考虑本地崩溃日志聚合（不上传，规避隐私问题），方便远程用户反馈。
7. **【长期】范围治理**：新增能力（如 AI 打标）前先问"这是资产管理器的核心还是商城系统的核心"，警惕把项目变成两个产品。

## 5. 总评

这是一个在架构纪律、安全工程和测试文化上达到团队级水准的单人项目，最突出的矛盾不是代码质量，而是**规模与单一维护者/单一磁盘的生存风险**——建议把精力优先花在备份与自动化门禁上，而非继续扩展功能面。

## 附：审查依据快照（本机实测）

- 代码规模：`AssetsManager` 213 py / 3.0 MB；`webui/src` 217 ts/tsx / 1.2 MB；`tests` 250 py / 2.7 MB；`docs` 255 md / 2.5 MB。
- pytest 收集：`3457/3473 tests collected (16 deselected)`（`python -m pytest --collect-only -q -p no:cacheprovider`）。
- 全库 grep `TODO|FIXME|XXX|HACK|NotImplemented`：0 命中。
- `hmac.compare_digest` 使用点：`domain/auth.py` 6 处、`lan/routes/quota.py` 1 处、`lan/routes/storefront_analytics.py` 2 处。
- Git 状态：master 无远程；工作区仅 1 个已删除的 `.mimocode` 计划文件未提交；2 个 stash；本地分支 `fix/grid-zoom-interpolation` 与 master 无提交差异。
- cloudflared-windows-amd64.exe（54 MB）未被 git 跟踪，已由 .gitignore 排除。
