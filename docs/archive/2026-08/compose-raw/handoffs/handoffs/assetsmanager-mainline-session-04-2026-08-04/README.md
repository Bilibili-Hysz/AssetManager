# AssetsManager 主线会话交接

> 交接日期：2026-08-04
> 当前分支：`master`
> 当前 HEAD：`51e50203eebf582dcf480ed5b378e0f7156e6611`
> 交接性质：主线继续开发，不是发布完成声明

## 0. 给新会话的第一结论

用户已经明确调整了会话分工：

- 当前主会话负责先全面处理和收口 `AssetsManager` 的开发工作；
- 暂不进行 WebUI 显示优化；
- 现有 `webui/` 改动属于并行会话成果，必须保留，不得回滚、覆盖、重排或纳入本主线提交；
- 只有当 AssetsManager 的核心开发、数据安全、生命周期、测试门和文档状态真正收口后，才向用户明确说明可以重新启用第二会话进行前端显示优化。

本文件是新会话的主入口。先读完本文件，再根据“下一步唯一优先级”继续工作。不要从旧的 Desktop UI 或 WebUI 启动提示词直接开始，也不要把“测试大部分通过”误写成“项目完成”。

## 1. 当前工作树和安全边界

### 1.1 当前仓库状态

当前工作树是多会话合并状态：

- 根目录：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
- 分支：`master`
- HEAD：`51e50203eebf582dcf480ed5b378e0f7156e6611`
- 本轮没有暂存或提交新改动；已有用户和其他会话改动全部保留。
- `git status --short --untracked-files=all` 在本交接前显示约 1067 条状态，其中约 942 条来自历史测试遗留的 `tmp/` 文件；这些临时产物没有被本轮统包清理，不能把它们当成产品代码，也不能用全量 `git clean` 处理。
- 本轮新建的 `tmp/assetsmanager-full-baseline-2026-08-04` 已经按绝对路径核验后删除。

### 1.2 不可做的事情

在新会话开始阶段禁止：

- `git reset --hard`、`git checkout --`、全量 `git clean`；
- 覆盖、回滚或批量格式化其他会话的改动；
- 把 `webui/` 的文件加入 AssetsManager 主线提交；
- 把现有 `webui/test-results/` 当作可删除垃圾；
- 为了通过测试而删除断言、放宽架构门、屏蔽失败或修改测试临时目录解析逻辑；
- 在没有 root/session 所有权合同前直接扩大备份/恢复功能。

### 1.3 当前保护域

下列范围在本交接的第一阶段保持只读，除非新会话先完成主线审查并明确认领：

- `webui/**`：第二会话成果，当前主线不触碰；
- `AssetsManager/application/**`：当前包含 G6 未收口实现，修改必须按任务写域进行；
- `AssetsManager/core/**`：数据库、锁、路径和设置是共享基础设施，必须进行高风险复核后再改；
- `AssetsManager/lan/**`：先单独处理已知生命周期竞态，不与恢复切片混改；
- `AssetsManager/panels/file_list/**`：暂不把视觉、模型、扫描、缩略图队列和性能链路混入数据恢复任务；
- `AssetsManager/window.py`、`AssetsManager/dialogs/sharing_settings_dialog.py`、`AssetsManager/widgets/lan_sharing.py`：除非任务明确需要且完成跨模块复审，不作为第一切片写入范围。

## 2. 本会话刚完成的 Desktop UI 阶段

这一阶段已经完成实现、复核和回归，但尚未单独提交。它是当前工作树中应保留的 Desktop UI 基础，不是下一阶段的优先开发方向。

### 2.1 改动范围

- `AssetsManager/widgets/toast.py`
- `AssetsManager/widgets/stylekit.py`
- `AssetsManager/widgets/status_indicator.py`
- `AssetsManager/widgets/tag_chip.py`
- `AssetsManager/dialogs/tabbed_dialog.py`
- `tests/desktop/test_toast_and_empty_visuals.py`
- `tests/desktop/test_stylekit.py`
- `tests/desktop/test_status_indicator.py`
- `tests/desktop/test_tag_chip.py`
- `tests/desktop/test_tabbed_dialog_visuals.py`

### 2.2 已关闭的问题

- Toast 在 reduced-motion 下立即可见；定位使用父窗口全局坐标并跟随移动/缩放；长文本在窄窗口中受边界约束。
- Toast singleton 在父窗口销毁后不会留下失效的 PySide 包装对象；下一父窗口可以安全创建 Toast。
- Toast 在父窗口 hide/close/destroy 时不再成为孤立的 Tool 窗口。
- Toast 显示时发送一次 Qt accessibility Alert，重新显示同一实例不会重复播报。
- `StyleKit` 使用 Qt 支持的 `:focus`，补齐 disabled/read-only/pressed 状态；primary/danger 的 hover/pressed 使用实际不同的颜色，不再出现“规则存在但像素不变”。
- `TabbedDialog` 折叠标题和齿轮按钮具备真实可见的键盘焦点；按钮盒的 primary/secondary/ghost 语义和 Tab 顺序保留。
- `StatusIndicator` 运行时 UI scale 切换会同步刷新图标画布、字体、间距和最小高度；loading pulse 在 hide/close 时停止、重新显示时按状态和 reduced-motion 恢复。
- `TagChip` 的关闭按钮焦点和对比度通过真实渲染/主题 token 验证。
- 部分原来只检查 QSS 字符串的测试已改为真实像素或精确 selector 断言。

### 2.3 新鲜验证证据

在当前工作树上实际执行过：

```text
组件矩阵：84 passed in 0.83s
完整 tests/desktop：482 passed in 43.03s
Ruff：All checks passed
目标文件 git diff --check：通过
目标文件尾随空白检查：通过
```

额外行为探针结果：

```text
Toast 旧实例失效后 singleton 自动恢复：通过
Toast 第二父窗口创建：通过
按钮 pressed 像素差异：12636 bytes
折叠标题焦点像素差异：22688 bytes
齿轮按钮焦点像素差异：572 bytes
隐藏 StatusIndicator 后 pulse 停止：通过
2x 图标画布/图标：64px / 48px，无裁切
```

这组 UI 改动可在后续适当时独立提交，但新会话不应因为它们马上转去扩大视觉范围。上一阶段的原始交接包仍在：

`docs/compose/handoffs/desktop-ui-session-03-2026-08-04/README.md`

## 3. 全项目新鲜基线

本轮使用 `python -B -m pytest -q tests -p no:cacheprovider` 做过一次完整 Python 测试基线，结果为：

```text
1932 passed, 5 failed, 5 errors, 2 skipped
耗时：246.74s
```

这不是发布门。失败需要按下面分类处理：

### 3.1 环境/范围相关

5 个 error 来自：

`tests/e2e/test_webui_realtime_acceptance.py`

Playwright Chromium 在当前环境启动时报 `spawn EPERM`。这些是 WebUI 真实浏览器验收，不属于本主线当前范围。

另一个失败来自：

`tests/e2e/test_webui_realtime_acceptance.py::test_real_lan_server_restarts_on_same_port`

它同样属于 WebUI/E2E 交界验证，必须保留失败证据，不要在本主线中擅自修 WebUI。

两个测试被跳过：

- `tests/integration/test_project_service.py` 的目录 symlink 环境门；
- `tests/unit/test_library_export_service.py` 的目录 symlink 权限门。

### 3.2 当前真实产品风险

`tests/integration/test_window_lifecycle_lan_failure.py::test_window_exit_drains_session_after_explicit_lan_stop_failure`

这是已知的 LAN 生命周期竞态，和 G6-6 报告中记录的 `SystemExit` 启动回滚线程退出抖动一致，应单独作为 L1 任务处理。

### 3.3 测试夹具路径问题

以下三个架构边界测试在本次运行中失败：

- `tests/unit/test_architecture_boundaries.py::test_qualified_attribute_reads_flags_direct_database_manager_current_syntax`
- `tests/unit/test_architecture_boundaries.py::test_qualified_attribute_reads_flags_known_database_manager_import_alias`
- `tests/unit/test_architecture_boundaries.py::test_qualified_attribute_reads_flags_database_module_and_full_qualified_chains`

本次 basetemp 放在仓库内的 `tmp/`，测试内部把临时路径规范化成了模块式名字，导致断言期望的绝对路径与实际诊断字符串不一致。随后已经使用当前用户可写的仓库外目录
`C:\Users\86177\AppData\Local\Temp\assetsmanager-boundary-2026-08-04`
单独复跑，结果为：

```text
3 passed in 0.48s
```

因此目前没有证据表明这三条是产品或架构回归；新会话不要根据仓库内 basetemp 的失败直接修改生产代码。完整基线的有效已知失败主要仍是 1 条 LAN 生命周期失败、1 条 WebUI E2E 失败和 5 条 Playwright Chromium 启动 error。

## 4. 当前代码/任务状态

### 4.1 已交付的架构主干

以下能力有代码和测试证据，可以视为 delivered，但相关文档仍需同步：

- `LibrarySession → LibraryRuntime → LibraryScopedServices` canonical ownership；
- A3：Desktop/shared eager service assembly，LAN-only lazy projection；
- LAN single-flight、失败代次、close/publication barrier；
- B1：Runtime-owned Auth/Share/secret；
- Runtime adapter 关闭顺序与失败重试；
- LAN 从 canonical snapshot 投影服务，repository 不被 LAN route 直接调用；
- LAN tunnel 无认证时 fail-closed；
- 基础 Metadata/Tag 查询与库统计写入能力；
- 按库 QLockFile 与关闭失败保锁。

主要证据：

- `docs/compose/reports/a3-service-assembly-2026-08-02.md`
- `docs/compose/reports/b1-runtime-sharing-2026-08-03.md`
- `docs/compose/reports/g6-5-database-integrity-2026-08-03.md`
- `docs/compose/reports/g6-6-security-preflight-implementation-2026-08-04.md`
- `docs/architecture.md`
- `docs/architecture-diagram.md`
- `docs/adr/0003-library-runtime.md`

### 4.2 Partial，不能宣称完成

- G6-5 数据库完整性：quick_check、孤儿清理和部分生命周期已实现，但半完成文件操作恢复、用户可见健康反馈和真实崩溃演练未闭合。
- G3-9 数据库维护：数据库大小、WAL checkpoint、后台单飞已实现；VACUUM 维护窗口、产品反馈和统一维护协调器未完成。
- G6-1 metadata/export/backup：JSON 导出、SQLite snapshot、manifest、SHA-256、路径校验和 quick_check 已实现；导入、格式演进、资源上限和正式产品工作流未完成。
- G6-1 restore/quarantine：staging、旧数据隔离、按库锁和基础回滚已实现；root/session 所有权、回滚双重失败可观察性、quarantine 生命周期和 Runtime 重建未完成。
- G6-6 SecurityPreflight：首次确认门和纯函数合同存在；previous bind/auth 历史未接入生产路径，确认写回流程和 LAN 生命周期竞态未闭合。
- G2-11 库统计：服务写入已存在，Desktop 展示和真实窗口验收未完成。
- B2 Desktop 性能：ThumbnailService 边界存在，真实图片 I/O、发布机基准和最终性能门未完成。

### 4.3 文档明显过时

需要新会话在代码稳定后统一校准：

- `docs/architecture.md` 的服务表和模块规模未包含完整性、维护、导出、设置适配器；
- `docs/architecture.md` 对 legacy `.services` fallback 的描述前后矛盾；
- `DeepSeek Docs/01-项目总览与架构.md` 仍使用旧服务数量和模块规模；
- `DeepSeek Docs/03-应用服务层.md` 遗漏 `DatabaseMaintenanceService`；
- `DeepSeek Docs/架构与设计评价/02-后端架构评价.md` 仍称 G3-9 没有维护工具；
- `docs/compose/reports/g6-1-product-entry-contract-2026-08-04.md` frontmatter 仍是 proposed，但正文已记录适配器和设置注入落地。

## 5. 下一步唯一优先级

### R1 — G6-1 恢复安全合同（当前最高优先级，P0）

现有 `LibraryExportService.restore_backup()` 只检查它持有的 session 是否关闭：

`AssetsManager/application/library_export_service.py:439-440`

它没有验证同一 root 是否已经被新的 canonical session 重新打开。因为 `LibraryLock` 在同一进程内使用共享引用计数，存在以下危险序列：

1. Runtime A 打开库并创建 `LibraryExportService(session=A)`；
2. A 关闭，但旧 service/adapter 仍被 UI 或 worker 持有；
3. 同一 root 被 Runtime B 重新打开；
4. 旧 service 看到 A 已关闭，继续 restore；
5. 旧 service 取得共享进程锁并替换 B 正在使用的 `RuntimeData`。

R1 的建议写域：

- `AssetsManager/application/library_service.py`
- `AssetsManager/application/library_export_service.py`
- `AssetsManager/application/bootstrap.py`
- `tests/unit/test_library_export_service.py`
- `tests/unit/test_library_service.py`（如现有文件已存在）
- 必要时新增专属 restore coordinator 测试文件

推荐实现合同：

1. 在 `LibraryService` 增加 root-aware restore reservation/context manager；
2. reservation 在同一生命周期锁下确认：目标 root 没有 live canonical session、没有 opening/closing 状态、没有 replacement session；
3. reservation 标记 root 为 restoring，使并发 `open_session()` 等待或明确拒绝；
4. `Bootstrap` 把 reservation 注入 `LibraryExportService`，没有 coordinator 时 restore fail-closed；
5. restore 的 staging、隔离、安装、quick_check 和回滚全部在 reservation 内执行；
6. 回滚失败不能 `pass`：保留原始异常，同时暴露隔离失败/旧目录恢复失败的二级错误信息；
7. 增加 replacement-session、reservation race、staging failure、installed check failure、quarantine failure、rollback failure 测试；
8. 明确备份成员数、展开大小、压缩比和数据库 snapshot 上限，避免把资源耗尽风险留到产品入口。

R1 不得修改：

- `webui/**`；
- LAN 生命周期；
- FileList 模型、loader、thumbnail、scan、reset、queue；
- Desktop 视觉文件；
- 数据库锁实现本身，除非高风险复审明确要求。

## 6. 后续波次

完成 R1 并通过高风险复审后，按以下顺序推进：

1. **L1：LAN 生命周期竞态**
   - `AssetsManager/lan/server.py`
   - `tests/lan/test_server_lifecycle.py`
   - `tests/integration/test_window_lifecycle_lan_failure.py`
2. **D1：文档状态校准**
   - architecture、diagram、ADR、DeepSeek Docs、compose reports；
   - 不在文档切片中修改代码。
3. **M1：G6-5/G3-9 维护与完整性收口**
   - 明确 worker stop、checkpoint 状态恢复、VACUUM 维护窗口和产品反馈。
4. **S1：SecurityPreflight 生产历史状态**
   - previous bind/auth 持久化、三入口一致性和确认写回。
5. **A1：Repository/path migration 单一来源**
   - 只在恢复与锁合同稳定后处理 core/repository 重复 SQL。
6. **A2：LAN coordinator 收敛**
   - 决定 `ShareManager` 是正式 coordinator 还是 legacy compatibility，停止双状态机漂移。
7. **G2-11：库统计产品展示与验收**。
8. **Q1：使用仓库外 basetemp 的完整非 WebUI 回归与发布证据**。
9. **最后才是表现层长期工作**：themes.py 单一样式来源、D1 原生控件覆盖和真实窗口截图门。

## 7. 重要架构判断

- Desktop UI 视觉下一阶段应先做 `themes.py` 单一样式规则源（A′），再做原生控件 D1；但这不是当前最高优先级，不能压过恢复 P0。
- `StyleKit` 当前是过渡性兼容门面，不应继续扩大为第三套样式系统；其通用 QSS 最终应委托中央主题源。
- `LibrarySettingsAdapter` 是 UI 与恢复/维护服务之间的唯一 Qt-free 边界；UI 不得绕过 adapter 访问 Runtime 或 repository。
- `ShareManager` 与 `LanServer`/`_LanServerImpl` 存在重复生命周期状态机，先记录为架构债，不在 R1 中顺手重构。
- database write gate、legacy singleton、`.services` fallback 目前属于被测试约束的 compatibility debt，不要在恢复 P0 中扩大修改面。

## 8. 文档阅读入口

新会话至少读取：

- `docs/architecture.md`
- `docs/architecture-diagram.md`
- `docs/adr/0003-library-runtime.md`
- `docs/compose/reports/mainline-parallel-batch-2026-08-04.md`
- `docs/compose/reports/g6-1-restore-2026-08-04.md`
- `docs/compose/reports/g6-1-product-entry-contract-2026-08-04.md`
- `docs/compose/reports/g6-5-database-integrity-2026-08-03.md`
- `docs/compose/reports/g6-6-security-preflight-implementation-2026-08-04.md`
- `docs/compose/handoffs/desktop-ui-session-03-2026-08-04/README.md`
- `docs/compose/handoffs/webui-session-02-2026-08-03/README.md`（只读了解边界，不接手其实现）
- `DeepSeek Docs/施行路线图.md`
- `DeepSeek Docs/未来方向/05-桌面端UI视觉改进规划.md`
- `DeepSeek Docs/未来方向/06-现代化界面技术路线评估.md`
- `DeepSeek Docs/未来方向/07-桌面端性能优化计划.md`

## 9. 新会话完成条件

在用户允许第二会话重新进行 WebUI 显示优化前，主线至少要满足：

- R1 恢复 P0 已关闭，并有 replacement-session 与双重回滚失败证据；
- L1 LAN 生命周期竞态已关闭或有明确环境阻塞报告；
- G6-5/G3-9/G6-6 的 partial 状态被准确拆分并完成可发布部分；
- 全量非 WebUI 测试使用仓库外 basetemp 重跑并归档唯一计数；
- 架构、ADR、DeepSeek Docs 和 compose 报告与代码状态一致；
- 工作树中其他会话改动仍然保留，主线提交边界可解释；
- 只有这时才向用户说“AssetsManager 主线已完成，可以进入第二会话前端显示优化”。


## 10. 2026-08-05 M1 continuation update

本交接后的 M1 续接已完成以下安全收口：

- Integrity prune commit 与 session close 共享 `LibrarySession._publish_while_live()` 线性化点；thumbnail baked 文件延迟到数据库 commit 成功后才删除。
- Maintenance checkpoint 会恢复共享连接原有 `busy_timeout`；stop 后的新 checkpoint 保持 closed-service 语义；VACUUM 继续明确 unsupported 且不会取得连接。
- Integrity/Maintenance service 暴露 `last_schedule_error`；worker 启动失败写入失败报告/结果；`LibrarySettingsAdapter` 和自动窗口调度日志均能表达调度拒绝原因。
- 当前 M1 targeted 为 `167 passed`，非 E2E 全量为 `2034 passed, 2 skipped, 1 warning`。真实设置页控件、用户指导、VACUUM window、崩溃恢复、WebUI/E2E 和 Desktop 视觉门仍未完成。


## 11. 2026-08-05 S1 security-history continuation

S1 已完成一个服务层历史姿态小切片，但仍不是主线完成声明：

- `SecurityPreflight` 的 ack 必须精确匹配当前 contract version；future ack fail-closed；`cancel()` 不撤销既有确认。
- `AppSettings` 现在提供 last-successful bind/effective-auth 的严格历史读写、原子 commit 和 save 失败可观察性。历史只保存姿态，不保存密码、hash、access key 或 token。
- `security_preflight_from_settings()` 统一 Desktop、ShareManager、LanServer 的默认持久化来源；服务真实启动并完成 auth 复核后才更新历史。
- 首次分享确认 helper 已接入主窗口和 standalone `SharingSettingsDialog`；默认 No、原子 ack/trusted 写回、二次 preflight 和写回失败阻断均有直接测试。
- 普通设置保存失败时不继续改变服务状态；安全阻断 reason 已通过 `en/zh/ja` 翻译 key 展示。
- 本轮没有修改 `webui/**`、`webui/test-results/**`，没有清理 `tmp/`/`.pytest-*`，没有暂存或提交。

S1 尚未完成：

- GUI 主题/DPI/键盘焦点/reduced-motion/截图证据和完整产品文案验收；
- ack/trusted 版本失效、取消反馈及跨重启 GUI 验收；服务层用户确认写回已接通。
- LAN 既有 SystemExit 线程退出竞态；
- 全量非 E2E 基线未因本小切片重新宣称完成，仍需后续仓库外 basetemp 回归。

本轮专项证据：security-preflight unit `21 passed`；integration `12 passed`；confirmation helper `3 passed`；LAN tunnel/security `15 passed`；sharing dialog `6 passed`；S1 写域 Ruff/py_compile 通过。


## 12. 2026-08-05 A1-P0 path contract continuation

S1 服务层/确认写回 partial slice 后，已开始 A1 bounded preflight：

- 新增统一 SQL LIKE escape、descendant pattern 和 subtree remap helper；
- metadata/tag repository 的查询、失效、删除、迁移已统一使用 helper；
- core aggregate `migrate_path_metadata()` 已与 repository descendant 集合对齐；
- Windows `\`、portable `/`、`folder` 与 `folder-copy` 边界有回归证据；
- 本轮不处理 ProjectData、TagStore、AssetIndex 全量迁移，不重构数据库锁、restore coordinator 或 WebUI。

A1 当前仍未整体完成：

- RootIdentity 在所有 compatibility facade 的统一 key 语义；
- schema owner 单一来源和 migration fixture 收敛；
- broad repository/path migration；
- WebUI 保护域不变。

A1-P0 专项证据：repository/services/path tests `98 passed`；architecture boundary subset `7 passed`；Ruff/py_compile 通过。


## 13. 2026-08-05 bounded consistency continuation

本次继续审查没有回滚或覆盖其他会话改动，也没有触碰 `webui/**`、`webui/test-results/**`、`tmp/` 或 `.pytest-*` 测试产物。

### 已收口的最小一致性问题

- `library_stats` total-size 写入不再使用破坏性的 `INSERT OR REPLACE`；保留既有文件数/项目数。
- 未来 `schema_migrations` 版本通过 `UnsupportedSchemaVersion` fail-closed。
- `ProjectData` cache invalidation 与 canonical repository 使用相同 subtree boundary。
- AssetIndex 跳过 symlink/junction/reparse entries，upsert 更新 scope，delete 使用统一 path helper。
- architecture boundary contract 已同步承认 repositories 对 `core.path_resolver` 的纯基础设施依赖。

### 最终非 E2E 验证

```text
2075 passed, 3 skipped, 1 warning
```

覆盖：`tests/core`、`tests/unit`、`tests/integration`、`tests/desktop`、`tests/lan`。另有 Ruff、目标 bounded 生产文件 Pyright、compileall 与 `git diff --check` 通过。3 个 skip 均为 Windows symlink/junction 权限条件；1 个 warning 是 duplicate ZIP member 的故意测试构造。

### 仍然的边界

这不等于 AssetsManager 主线或 G6-6/A1 完成。仍需后续 bounded slice 处理：MetadataService 批量 file-key 统一、compatibility facade 的 root/connection ownership、AssetIndex 历史污染 containment、schema owner/旧 fixture 收敛，以及 S1 GUI/跨重启/LAN 完整生命周期验收。`tests/e2e/**` 与 WebUI 仍未纳入本轮。


## 14. 2026-08-05 metadata batch and compatibility ownership continuation

本次继续处理上一轮列出的两个 bounded contract，仍未触碰 `webui/**`、`webui/test-results/**`、`tests/e2e/**`，未清理 `tmp/` 或 `.pytest-*`，未暂存/提交。

### 已完成

- MetadataService batch file-key 统一 canonicalize；batch get 保留 caller key，alias/`..` 查询共享同一 canonical row，batch set 不产生重复 key。
- DatabaseManager 增加 managed connection owner validation；ProjectData/TagStore 对 root mismatch fail-closed。
- 同 root managed connection 与 unmanaged memory connection 的兼容语义保留。

### 验证

```text
batch/ownership 专项：115 passed
主线非 E2E：2084 passed, 3 skipped, 1 warning
Ruff、目标生产文件 Pyright、compileall、git diff --check：通过
```

### 当前边界

本轮没有把 unmanaged raw connection 强制迁移为显式 ownership token；这仍是后续兼容 API 收敛项。A1 broad migration、schema owner/旧 fixture、AssetIndex 历史污染 containment、S1 GUI/跨重启/LAN 完整生命周期和 WebUI/E2E 仍保持 partial/保护状态。


## 15. 2026-08-05 indexed containment and schema preflight continuation

### 已完成

- Indexed search 对历史污染行增加 physical canonical containment；库外、`..` 逃逸和 symlink 外指向记录 fail-closed。
- Future schema version 增加只读预检，`DatabaseManager` 在 `_SCHEMA` DDL 之前拒绝未来数据库。

### 验证

```text
indexed/schema 专项：50 passed, 2 skipped
主线非 E2E：2088 passed, 4 skipped, 1 warning
Ruff、目标生产 Pyright、compileall、git diff --check：通过
```

### 后续阻断项

raw connection 审查确认多个 application service 的显式 `db_conn` 仍未统一 root 校验，`InfoController` 存在忽略 requested root 的 provider。schema owner/旧 fixture 也仍未收敛：空 baseline、稀疏 history、directory_cache 双 owner、Auth/Share 未版本化、migration 非原子。下一轮应先建立统一 root-bound connection resolver，再决定 raw compatibility 的显式 opt-in 迁移。

## 16. 2026-08-05 application service 与 InfoController ownership continuation

### 已完成

- 五个 application service 的 managed connection ownership 接线完成并通过专项验证：`TagService`、`ProjectService`、`SearchService`、`MetadataService`、`ThumbnailService`。
- 显式 `db_conn` 优先级保持不变；managed foreign-root fail-closed；unmanaged raw SQLite 兼容继续保留。
- `InfoController` 的 plugin metadata 路径补上 `DatabaseManager.validate_connection_owner()`；`db_conn=None` 不再构造空连接 repository，filesystem-only 场景保持可用。
- 未改变连接关闭责任，未删除 legacy 构造参数，未把 `PluginMetadataRepository` 强行迁移为 session/provider-only API。

### 验证

```text
application service 专项：89 passed, 2 skipped
InfoController/相关 desktop 专项：165 passed
当前主线非 E2E：2109 passed, 4 skipped, 1 warning
Ruff、目标 Pyright、compileall、git diff --check：通过
```

### 必须保留的边界判断

这轮只完成了 managed ownership 的 bounded closure，不等于全项目数据库访问已完全 fail-closed：

1. unmanaged raw connection 兼容仍存在；
2. LAN legacy fallback 仍存在；
3. InfoController/PluginMetadataRepository 仍有 legacy raw API 形态，只增加了入口校验；
4. schema/migration owner 与真实历史 fixture 仍是 P1 partial：空 baseline、稀疏/错名 history、`directory_cache` 双 owner、Auth/Share 未版本化、migration 非原子；
5. `tests/e2e/**` 未运行，`webui/**` 的既有 14 条修改未触碰；
6. 工作区保持 dirty 混合状态，未 reset、未 checkout、未 clean、未暂存、未提交。

## 17. 2026-08-05 migration history/atomicity continuation

### 已完成

- `schema_migrations` 由只信任 `MAX(version)` 改为连续版本、名称匹配、非法值拒绝的 fail-closed history 合同。
- `preflight_recorded_version()` 与 `migrate()` 共享同一 history 校验逻辑，preflight 仍保持只读。
- 移除 v5 migration 内部 commit，`migrate()` 使用 savepoint 保护 migration history、DDL 和外层事务边界。
- 增加 malformed、sparse、misnamed、fake-latest、outer rollback 和 injected failure 测试。

### 验证

```text
migration 专项：17 passed
core 全套：172 passed
当前主线非 E2E：2116 passed, 4 skipped, 1 warning
Ruff、目标 Pyright、compileall、git diff --check：通过
```

### 下一阶段边界

本轮没有重构完整 schema owner。以下仍是 P1 partial：

1. 空库 `migrate()` 的 v5 记录不能证明 core tables 完整存在；
2. `directory_cache` 仍有 baseline/v5 双 owner；
3. Auth/Share 三张表仍未纳入统一 migration；
4. v1 upgrade fixture 仍依赖当前 `_SCHEMA`，尚未冻结真实历史结构；
5. `webui/**`、`tests/e2e/**`、tmp 与既有 dirty worktree 保护边界继续有效。

## 18. 2026-08-05 schema owner / baseline continuation

### 已完成

- `directory_cache` 从 `_SCHEMA` baseline 移除，保留 v5 migration 唯一创建责任。
- `migrate()` 现在要求 core baseline tables 已存在；纯空库不再伪成功记录 v5，而是 fail-closed 并回滚 migration tracking 表。
- 直接使用 migration 的 directory-cache 与 asset-service 测试已显式准备 baseline，避免把“无 schema 的 migrate”误当作合法生产合同。

### 验证

```text
schema/core 专项：174 passed
asset-service follow-up：26 passed
当前主线非 E2E：2118 passed, 4 skipped, 1 warning
Ruff、目标 Pyright、compileall、git diff --check：通过
```

### 后续边界

Auth/Share schema、真实 v1 fixture、完整 schema-object integrity manifest 仍未统一；`tests/e2e/**` 与 `webui/**` 保护边界不变，工作区仍保持 dirty 混合状态，未 reset、未 checkout、未 clean、未暂存、未提交。

## 19. 2026-08-05 frozen v1 fixture continuation

### 已完成

- 新增静态历史 fixture：`tests/fixtures/db/v1_schema.sql`。
- v1 fixture 来源固定为历史 HEAD `51e50203eebf582dcf480ed5b378e0f7156e6611`，不依赖当前 `_SCHEMA` 动态生成。
- v1 fixture 保留历史 core baseline 与 `directory_cache`，但不包含 `assets`、`tag_metadata`、`plugin_metadata`。
- v1->v5 upgrade 测试现在验证真实独立 fixture 的升级路径。

### 验证

```text
v1 fixture 专项：19 passed
core 全套：174 passed
当前主线非 E2E：2118 passed, 4 skipped, 1 warning
Ruff、目标 Pyright、compileall、git diff --check：通过
```

### 下一阶段

Auth/Share schema 仍未进入统一 migration。下一阶段需要以新的明确版本合同处理 `users`、`invite_codes`、`share_links`，不能修改现有 v5 语义或只在 repository 内继续惰性建表。

## 20. 2026-08-05 Auth/Share v6 migration continuation

### 已完成

- 新增 `AssetsManager/core/schema_defs.py`，集中定义 Auth/Share 三张表 SQL。
- `CURRENT_SCHEMA_VERSION` 升至 6，新增 `auth_share_schema` migration。
- v6 正式创建 `users`、`invite_codes`、`share_links`。
- AuthRepository/ShareRepository 保留 raw legacy ensure 兼容，但不再各自维护独立 SQL 定义。
- 更新 repository architecture boundary 合同。

### 验证

```text
Auth/Share + migration 专项：150 passed
当前主线非 E2E：2118 passed, 4 skipped, 1 warning
Ruff、目标 Pyright、compileall、git diff --check：通过
```

### 边界

v6 已建立正式 schema owner，但 repository ensure fallback 仍然存在；后续可再做 compatibility API deprecation 和完整 schema-object manifest。`webui/**`、`tests/e2e/**`、tmp、RuntimeData 保护边界继续有效，未 reset、未 checkout、未 clean、未暂存、未提交。

## 21. 2026-08-05 G3e raw connection compatibility boundary continuation

### 已完成

- `DatabaseManager.validate_connection_owner()` 增加显式 `allow_unmanaged` 参数。
- `allow_unmanaged=False` 对未登记的 raw `sqlite3.Connection` fail-closed；`allow_unmanaged=True` 保留历史插件/fixture 兼容语义。
- canonical `ApplicationBootstrap` 继续使用独立的 `require_managed_connection_owner()`，未把 unmanaged connection 引入生产 canonical assembly。
- `ProjectData`、`TagStore`、`DirectoryCache`、`InfoController` 与 application service 的 legacy ownership 调用点均显式标记 `allow_unmanaged=True`，避免兼容行为依赖默认值。
- 增加 raw/managed/same-root/foreign-root ownership 回归矩阵。

### 验证

```text
完整非 E2E 回归：2173 passed, 4 skipped, 1 warning
完整 Pyright：0 errors, 0 warnings, 0 informations
Ruff：All checks passed
`git diff --check`：通过（仅有既有 LF/CRLF 提示）
```

### 必须保留的边界判断

1. 本轮是兼容 API 显式化，不等于所有 unmanaged raw connection 已被默认拒绝；`allow_unmanaged` 默认仍保持兼容，以避免破坏旧插件与历史 fixture。
2. canonical bootstrap、LAN strict assembly 和 managed foreign-root 校验继续保持 fail-closed；本轮没有改动 WebUI、`tests/e2e/**` 或 `tmp/**`。
3. `InfoController`、`PluginMetadataRepository`、Auth/Share repository 的 raw compatibility 形态仍存在，后续可单独规划 capability/token 收口，不能在没有迁移证据时直接删除。
4. 2173 条回归中 4 条 symlink 相关测试因当前 Windows 进程缺少 symlink/directory-symlink 权限而跳过；1 条既有 zip duplicate-name warning 保留。

详细记录见：`docs/compose/reports/g3e-raw-connection-compat-2026-08-05.md`。

## 22. 2026-08-05 schema-object integrity and retained lifecycle continuation

### 已完成

- 新增 Auth/Share/schema_migrations 的共享 schema-object manifest 与 shape validator：表存在性、必需列、主键、必需唯一约束均会复核。
- 已记录 v6 时，即使 migration body 被跳过，也会重新验证 `users`、`invite_codes`、`share_links`；删除表或破坏关键结构会 fail-closed。
- Auth/Share repository 的 raw/legacy ensure 复用同一 validator；缺表可兼容创建，已有错误表不再静默接受，并保留 savepoint/外层事务边界。
- 将 schema validator 放入 `AssetsManager/core/schema_defs.py`，避免 repository 反向依赖 `core.db_migrations`，并通过 architecture boundary 测试。
- canonical `DirectoryCache`、`AssetService` 绑定 session lifecycle；关闭/closing 后公开缓存和浏览入口拒绝访问，lifecycle `RuntimeError` 不再转换为空 listing。
- materialized LAN services 在 session close 后不再通过 holder ready 快速路径返回；`runtime_for()` 拒绝 closing/closed runtime cache，`LibraryRuntime.next_revision()` 在非 open 状态拒绝。
- 同步 LAN close-race 测试，使“已关闭后不再返回 retained service”成为明确合同。

### 验证

```text
完整非 E2E 回归：2183 passed, 4 skipped, 1 warning
完整 Pyright：0 errors, 0 warnings, 0 informations
Ruff：All checks passed
AST 解析：297 个 Python 文件，0 errors
architecture boundary / schema / lifecycle 专项：通过
`git diff --check`：通过（仅有既有 LF/CRLF 提示）
```

### 边界与操作记录

1. `webui/**`、`tests/e2e/**`、`tmp/**` 未触碰；symlink 相关 4 条测试仍因当前 Windows 进程缺少权限而跳过，1 条既有 zip duplicate-name warning 保留。
2. `allow_unmanaged` 兼容 API、LAN 私有 legacy fallback、SearchService provider-only 例外、InfoController raw connection 与业务层异常降级仍是后续任务，不能据此宣称全项目完成。
3. 本轮并行代理曾在未获主会话授权的情况下创建提交 `fbf3403`（`Enforce schema object integrity for v6`）；主会话未执行 staging、commit、reset、checkout 或 clean，也未回滚该提交。后续操作必须以当前 `master`/`HEAD=fbf3403` 和剩余 dirty 工作区为事实基线。

详细记录见：`docs/compose/reports/g4-schema-lifecycle-2026-08-05.md`。

## 23. 2026-08-06 LAN SearchService 与异常语义 continuation

### 已完成

- `SearchService` 增加可选 `LibrarySession`，canonical bootstrap 注入当前 session；standalone/raw fixture 构造继续兼容。
- SearchService 的公开搜索入口进入 `session_operation`；canonical LAN strict binding 现在要求 `_session is current session`，`None`/foreign session fail-closed；legacy fallback 的 provider-only 兼容暂时保留。
- ProjectService 对 closed SQLite connection 的 `sqlite3.ProgrammingError` 不再降级为 `[]`、`0` 或空字符串；foreign-root/ownership `ValueError` 不再被缓存聚合层吞掉。
- InfoController 的插件 URL 持久化遇到 closed connection 时重新抛出 `sqlite3.ProgrammingError`；普通可选持久化失败仍保持原有降级语义。
- 补充 canonical search session-none/foreign-session、standalone compatibility、ProjectService/InfoController closed-resource 回归。

### 验证

```text
本轮专项：305 passed, 2 skipped
完整非 E2E 回归：2191 passed, 4 skipped, 1 warning
完整 Pyright：0 errors, 0 warnings, 0 informations
Ruff：All checks passed
`git diff --check`：通过（仅有既有 LF/CRLF 提示）
```

补充：LAN lifecycle 套件在独立复跑中 `39 passed`；完整回归曾出现一次既有/环境相关的 startup cleanup timeout，随后独立套件与完整回归均通过，当前不把该单次波动宣称为稳定失败，也不忽略其诊断价值。

### 当前边界

1. `_allow_legacy_runtime` 生产私有 fallback 尚未删除；正常 facade 不暴露，但进程内直接调用仍可放宽部分 session/operation contract。下一波目标是 test-only adapter 迁移后删除生产 fallback。
2. ProjectService/InfoController 仍保留部分普通 `sqlite3.Error`、OSError 的业务降级语义；下一步应建立完整 partial/degraded 结果契约，不继续扩大裸空值。
3. `allow_unmanaged=True`、InfoController raw connection、repository legacy ensure 仍属于兼容边界；不要在没有迁移矩阵时直接切换为拒绝默认。
4. WebUI、`tests/e2e/**`、`tmp/**` 未触碰，不能据此宣称整个项目完成。

详细记录见：`docs/compose/reports/g5-search-error-contract-2026-08-06.md`。

## 24. 2026-08-06 LAN legacy fallback removal continuation

### 已完成

- 生产 `AssetsManager/lan/server.py` 删除 `_LanServerImpl(..., _allow_legacy_runtime=...)` 参数及其 runtime services / operation fallback 分支。
- LAN server 现在始终要求 canonical `services_snapshot`、`session.operation()`、LAN projection、sharing projection 及当前 session/provider/db identity。
- 新增 `tests/lan/support/legacy_runtime_adapter.py`，仅供测试将历史 `SimpleNamespace` fixture 补齐 canonical contract；生产代码不导入该 adapter。
- `tests/lan/test_lan_api.py` 的旧 fallback fixture 改为 adapter 路径，并增加公共 `LanServer`/`ShareManager` 不接受 fallback 开关、缺 snapshot/operation/projection、foreign provider/db/session、close race 的拒绝矩阵。
- 生产代码扫描已不再发现 `_allow_legacy_runtime`、`allow_legacy_runtime` 或 `legacy_fallback` 符号；这些字符串仅保留在测试中用于验证入口拒绝。

### 验证

```text
LAN API：224 passed
LAN API + lifecycle：263 passed
完整非 E2E 回归：2192 passed, 4 skipped, 1 warning
完整 Pyright：0 errors, 0 warnings, 0 informations
Ruff：All checks passed
`git diff --check`：通过（仅有既有 LF/CRLF 提示）
```

### 新的边界判断

1. LAN 生产 fallback 逃生口已关闭；旧 fixture 兼容只存在于 `tests/lan/support`，不再是生产模块能力。
2. `allow_unmanaged=True` raw DB 兼容、InfoController raw repository、普通业务 OSError/SQLite 降级仍属于后续收口项。
3. WebUI、`tests/e2e/**`、`tmp/**` 未触碰；4 条 symlink 相关测试因当前 Windows 权限跳过，1 条既有 zip duplicate-name warning 保留。
4. 当前 HEAD 仍为并行代理意外创建的 `fbf3403`；主会话未执行 staging、commit、reset、checkout、clean，也未回滚该提交。

详细记录见：`docs/compose/reports/g6-lan-fallback-2026-08-06.md`。

## 25. 2026-08-06 P1 raw resource 与安全错误语义 continuation

### 已完成

- `AuthRepository.has_active_invite_codes()` 默认严格处理：数据库查询失败抛出可识别的 `InviteCodeLookupError`；`AuthService.register_user()` 显式使用 strict 模式，避免数据库故障被当作“无邀请码”而放行注册。
- Thumbnail blur tag 查询遇到 closed connection、schema error、provider failure 或 foreign-root 时不再返回 `False` 伪装成“不需要模糊”；真实无匹配仍返回 `False`。
- `DatabaseIntegrityService` 将路径存在性改为 `EXISTS/MISSING/UNKNOWN` 三态；UNKNOWN 不得进入 metadata/orphan/baked-thumbnail 删除流程。
- `PluginMetadataRepository` 增加可选 session、root/path containment 与 session operation scope；canonical InfoController 注入当前 session，旧 controller/repository 在 close/切库后不再触达旧 DB。
- InfoPanel 切库时释放旧 controller/scoped services，保留异步 identity 与 stale completion 合同。
- repository 仍只依赖 core/domain；PluginMetadataRepository 的 session scope 使用本地轻量 adapter，未引入 application→repository 反向架构依赖。

### 验证

```text
P1 专项：98 passed
完整非 E2E 回归：2209 passed, 4 skipped, 1 warning
完整 Pyright：0 errors, 0 warnings, 0 informations
Ruff：All checks passed
`git diff --check`：通过（仅有既有 LF/CRLF 提示）
```

### 当前剩余边界

1. Auth/Tag/Share repository 仍有部分 P2 broad catch，将基础设施错误转换为 `False/None`；需按安全影响逐项收口。
2. SearchService 仍缺少结构化 partial/degraded 返回契约；普通 transient failure 与真实空结果的区分需要 API 设计。
3. `allow_unmanaged=True` 仍是兼容迁移阶段默认值；InfoController 的 raw legacy 构造仍保留。
4. WebUI、`tests/e2e/**`、`tmp/**` 未触碰，不能据此宣称整个项目完成。

详细记录见：`docs/compose/reports/g7-p1-safety-and-info-2026-08-06.md`。

## 26. 2026-08-06 P2 repository error contract continuation

### 已完成

- AuthRepository/AuthService：closed connection、schema/lifecycle 错误不再被转换为 `False/None`；真实重复用户名、重复邀请码、无效邀请码等业务失败语义保留。
- TagRepository：`add_tag()`/`remove_tag()` 不再把基础设施、schema、ownership、lifecycle 错误转换为 `False`；重复添加和不存在删除的幂等业务语义保留。
- ShareRepository：`insert()` 仅对明确的 `IntegrityError` 返回业务失败，closed connection、schema/lifecycle/ownership 错误继续传播。
- 新增 Auth/Tag/Share repository error-contract 回归矩阵。

### 验证

```text
P2 repository 专项：132 passed
完整非 E2E 回归：2275 passed, 4 skipped, 1 warning
完整 Pyright：0 errors, 0 warnings, 0 informations
Ruff：All checks passed
`git diff --check`：通过（仅有既有 LF/CRLF 提示）
```

### 后续边界

1. SearchService 仍需设计结构化 partial/degraded 结果契约，不能简单把所有异常改为重新抛出而破坏现有 transport API。
2. 仍有部分 repository/query helper 的 P2 broad catches，需要按真实业务失败与基础设施失败逐项分类。
3. `allow_unmanaged=True` raw compatibility 默认值尚未切换为拒绝；需要先完成插件/历史 fixture 迁移矩阵。
4. WebUI、`tests/e2e/**`、`tmp/**` 仍是保护域。

详细记录见：`docs/compose/reports/g8-repository-error-contract-2026-08-06.md`。

## 27. 2026-08-08 G17.17-F 与 R1 状态校准

本节用于纠正本文件早期交接描述与当前工作区实际状态之间的差异。它不构成发布完成声明，也不改变 `webui/**`、`tests/e2e/**`、LAN、Commerce/schema 等保护边界。

### 27.1 已验证完成的主线切片

#### G6-1 R1 restore ownership / rollback safety

当前工作区已经具备并通过专项回归：

- `LibraryService.restore_reservation()` root-aware reservation；
- replacement-session、stale-owner、queued-open race 拒绝；
- restore coordinator 缺失时 fail-closed；
- staging、quarantine、install、quick_check、rollback 的 reservation 内执行；
- quarantine、rollback、lock release secondary failure 证据；
- restore failure poison/token/acknowledgement 与跨 bootstrap admission block；
- archive member、manifest、expanded-size、compression-ratio、SQLite quick_check 限制。

当前专项回归：

```text
144 passed, 1 skipped, 1 warning
```

主要证据文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager/application/library_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager/application/library_export_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager/application/bootstrap.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests/unit/test_library_export_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests/unit/test_library_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests/unit/test_bootstrap.py`

因此本文件早期“R1 仍是待实现 P0”的描述已过时。剩余 G6-1 事项应拆为产品入口、恢复进度反馈、Runtime 重建与迁移提示，不得重新改写已经验证的 ownership/rollback 合同。

#### G17.17-F cross-process / lease ownership

当前已完成：

- SQLite generation polling、跨进程 wakeup、snapshot refresh 与 generation 单调保护；
- claim/renew/recovery/completion 的 lease token CAS；
- heartbeat、硬 operation deadline、stale worker completion protection；
- Windows `spawn` process matrix；
- connection-close、external-lock、heartbeat-in-flight、cutover lock-order fault injection；
- `subprocess.Popen + JSON file handshake` 的进程终止 recovery 验证。

新的终止测试：

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_process_termination_subprocess.py`

重复稳定性：

```text
10/10 passed
0 timeout
0 residual python/pytest process
```

阶段报告：

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\docs\compose\reports\g17-17-f-cutover-cross-process-plan-2026-08-08.md`

### 27.2 仍然 partial 的领域

1. Commerce/schema v22 existing-table/incompatible-schema 分支缺少独立回归；该写域属于 schema/migration 会话。
2. LAN 窗口关闭时的 server-stop failure 生命周期竞态仍应独立收口；不得与 G17 或 schema 混改。
3. WebUI 单测/typecheck/build 与浏览器 E2E 不是同一门禁；当前 CI 没有可靠执行浏览器 E2E，`webui/**` 与 `tests/e2e/**` 继续保持保护状态。
4. `.github/workflows/ci.yml` 已由并行会话修改；当前只读记录其门禁缺口，不在本会话直接重排 CI jobs。
5. 当前仍不支持旧版/新版应用同时持有同一 library 的 rolling upgrade；G17 只保证单 library、单 application owner 下的 stop-the-world cutover 与 crash recovery。

### 27.3 当前真实门禁基线

```text
全量 Python：2686 passed, 7 skipped, 1 warning
Ruff：通过（扫描 .pytest-tmp 时仅有访问拒绝 warning）
Pyright：0 errors, 0 warnings, 0 informations
Compileall：通过
```

这只是当前 Python 主线门禁基线，不等于 Commerce、LAN、WebUI/E2E 或整个工作区已发布完成。当前仍保持 dirty mixed workspace，未 staging、未 commit、未 reset、未 checkout、未全量 clean。
## 28. 2026-08-08 LAN 现状复核校准

本文件早期记录的 LAN stop failure 属于历史交接证据，不能直接当作当前工作区仍然失败。当前源码重新执行结果：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_window_lifecycle_lan_failure.py
2 passed

LAN lifecycle 组合（含 tests/lan/test_server_lifecycle.py）
41 passed
```

当前准确边界：

- LAN 生命周期测试当前可通过；
- 历史 failure 仍可作为曾经发现的风险背景，但不应重复标为当前 confirmed blocker；
- CI Windows regression 尚未明确纳入该失败场景，因此存在门禁覆盖缺口；
- LAN 仍是独立写域，未由本次 G17 会话接管或修改。
## 29. 2026-08-08 v22 migration 行为复核

本会话未修改 Commerce/schema 文件，但使用临时 SQLite 内存库验证当前 v22 实现：

```text
v21 + 已存在且兼容的 shop_delivery_attempts -> v22：PASS
v21 + 已存在但不兼容的 shop_delivery_attempts -> InvalidSchemaError：PASS
不兼容路径 schema_migrations 保持版本 21：PASS
```

因此不要再把旧的 `_table_exists(conn)` 参数错误描述为当前运行时 blocker。当前准确剩余项是：

- v22 existing-table/incompatible-schema 需要纳入正式 schema/migration 回归；
- `tests/core/test_delivery_attempt_migration.py` 的归属与是否纳入交付需要由 Commerce/schema 会话确认；
- G17 会话不直接修改 `AssetsManager/core/db_migrations.py`、`AssetsManager/core/schema_defs.py` 或对应 Commerce 测试。
## 30. 2026-08-08 G17 stop-the-world release/ownership checklist

已新增独立审计清单：

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\docs\compose\reports\g17-stop-the-world-cutover-release-ownership-checklist-2026-08-08.md`

该清单用于记录：

- stop-the-world cutover 约束；
- lock、schema、marker、queue、worker 的顺序；
- worker/heartbeat drain 与旧 owner 释放；
- 新 owner recovery/reclaim/completion；
- release gate、owner、abort/no-go 条件。

当前清单不构成整个项目 release approval，也不支持 rolling upgrade。它把当前 G17 阶段验证与 Commerce/schema、LAN、WebUI/E2E、CI 的未完成边界分开记录。
## 31. 2026-08-08 运行时残留边界

当前审计发现一个独立 LAN E2E helper 正在运行：

```text
PID 46920
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tmp\e2e\run_real_lan_server.py
```

该进程属于 `tmp/e2e` 保护域，本会话没有启动、终止或清理它。后续 release candidate 审查前，需要由其 owner 确认是否应继续运行；在确认前，不能宣称整个 workspace 已达到无运行时残留的 clean boundary。
## 32. 2026-08-08 library-owner handoff 测试收口

新增测试：

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_library_owner_handoff.py`

验证内容：

- 旧 runtime/worker stop 与 cleanup；
- DB close 与 LibraryLock release；
- 新 owner 获取同一 root 并启动新 runtime；
- stop timeout 时新 owner 不能提前接管；
- 旧 owner retry 成功后才允许新 owner 接管。

结果：

```text
2 passed
相关 runtime/lifecycle 组合 32 passed
连续 5 次复跑稳定
```

该测试补齐了 library-owner 级交接证据。schema migration、marker migration、worker start 的完整事件级统一顺序仍保留为部分覆盖，不得将本测试扩大解释为 rolling upgrade 或完整项目 release 证明。
## 33. 2026-08-08 bootstrap 顺序测试收口

新增：

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_bootstrap_order.py`

验证同一 bootstrap 内的实际调用顺序：

```text
schema migration complete
→ marker migration complete
→ reconciliation worker start
→ worker running
```

结果：

```text
5 passed
连续 5 次复跑：每次 1 passed
```

该测试补齐了 schema→marker→worker 的单 bootstrap 顺序证据，但不验证多进程 marker 并发，也不改变 stop-the-world/single-process cutover 边界。
## 34. 2026-08-08 LAN quota 缺表结果校准

当前隔离复核：

```text
tests/lan/test_lan_api.py：224 passed
restore/bootstrap/LAN lifecycle 组合：402 passed, 1 skipped, 1 warning
```

因此不能把此前并行审查观察到的 10 个缺表失败直接标为当前生产 blocker。

但 raw fixture 的初始化事实仍需保留：

```text
database._SCHEMA + Auth/Share init
→ free_download_quota_windows 不存在
```

生产 canonical migration v10 会创建该表；LAN raw connection fixture 不会自动调用 DatabaseManager migration。该项是 LAN/schema fixture contract 风险，后续由对应 owner 决定，不由 G17 会话接管。
## 35. 2026-08-08 当前 Python/静态基线

当前无其他 pytest 进程运行时执行：

```text
Python：2702 passed, 7 skipped, 1 warning
Ruff（AssetsManager + tests）：通过
Pyright：0 errors, 0 warnings, 0 informations
Compileall：通过
```

本次 `ruff check .` 返回 0；过程中对若干受 ACL 保护的临时目录打印了“拒绝访问”警告，但未报告 lint error。当前 `tmp/e2e` 目录没有可扫描的 `run_real_lan_server.py`；README/CI 仍以 `ruff check AssetsManager tests` 作为主线门禁。
## 36. 2026-08-08 README 门禁基线同步

已最小化更新根目录 `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\README.md`：

- Python 全量基线：`2702 passed, 7 skipped, 1 warning`；
- Ruff 主线范围：`ruff check AssetsManager tests`；
- Pyright/compileall 当前均通过；
- CI jobs 与 browser E2E 未纳入状态已同步；
- G17 stop-the-world、no rolling-upgrade 边界已写明。

未覆盖或改写其他并行会话的 Commerce/Seller 内容。