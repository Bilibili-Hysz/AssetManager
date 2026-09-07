# 开发统筹与首轮核验

> 状态：B00 至 B05 的修复批次已完成，后续继续推进新的开发任务。2026-09-06。用户授权主代理负责范围、优先级、架构判断和最终验收；执行子代理统一使用 `gpt-5.6-terra`。
> 源码基准：首轮 HEAD `6c70153b642f9d7a139937ae5d73da94325eebd8`；第二批核对 HEAD `0ce0406bed67f33b76c412521d1133c3796413c7`，均加捕获时未提交工作区。现有 LAN、媒体及桌面视觉变更仍在工作树，不能与本轮新增修复混同。

## 工作方式

1. 主代理选择一个有明确触发和验收条件的问题，规定文件所有权及不扩展的边界。
2. Terra 子代理核对代码、复现问题、补充能在旧实现上失败的回归，再实施最小修复。
3. 主代理独立审查行为语义、兼容性和 diff，核对针对性测试及静态检查结果。
4. 每批记录已完成项、剩余问题和实际验证限制。测试通过仅说明覆盖场景成立，不替代真实界面、性能或发布验证。

## 当前优先级

| 编号 | 优先级 | 问题与验收目标 | 状态 |
|---|---|---|---|
| B00 | 验收前置 | Python 测试拥有独立源码根和 RuntimeData，避免并行清理互相干扰 | 已完成：每进程/worker/嵌套 pytest 独占运行域，普通子进程继承 |
| B01 | P1 | 删除并撤销后评分保留；覆盖 0、普通评分、未评分、目录子项、redo/undo 和旧快照 | 已完成，两个生产模块与撤销集成测试；主代理复核通过 |
| B02 | P2 | 新库打开后面板绑定/导航失败须恢复一致会话和界面，并支持重试 | 已完成，45 项相关测试与主代理复核通过 |
| B03 | P2 | 评分写入进入运行时失效链；集合依赖变化刷新计数及已展开成员，并拒绝迟到旧请求 | 已完成：123 项后端、46 项前端及 7 项真实浏览器测试通过 |
| B04 | P2 | 当前 ZIP 诊断 DTO 与生成的 TypeScript 契约保持一致 | 已完成：可选非 null 字段、两层嵌套 DTO；4 项测试及主代理复核通过 |
| B05 | P2 | LAN 正确提供构建产物中的自托管字体 | 已完成，限定 /fonts 静态目录，14 项相关 HTTP 测试通过 |

P1 表示用户元数据保留受到影响；本表 P2 表示跨端陈旧显示、恢复可靠性或工程契约缺口。下一批优先 B00：将本次源码快照隔离经验落实为正式测试运行时隔离，随后确定下一项用户工作流。静态门禁通过不能代替具体行为验证。

## 首轮发现与证据

### B00：测试隔离（历史缺陷记录）

以下描述记录修复前行为，仅用于说明缺陷来源；现行实现与验收结果见文末“B00 永久测试隔离验收”。

`tests/conftest.py` 在 `pytest_sessionstart` 保存 Shared 设置，并在 `pytest_sessionfinish` 恢复；运行结束还扫描并清理 RuntimeData 下其他 pytest 库和固定的 `.pytest-tmp-paths`。不同 `--basetemp` 并不隔离这些共享路径。

三个子代理在获知此问题时均尚未启动 pytest。随后复制生产代码、测试、脚本、主题与插件，排除用户 RuntimeData，为三个执行者分配独立根目录。每次运行前检查 `AssetsManager.__file__` 和 `path_resolver.runtime_root()` 确认落在各自快照。

捕获工具与哈希清单：[capture.py](../reports/development-baseline-2026-09-06-evidence/capture.py)、[snapshot-manifest.json](../reports/development-baseline-2026-09-06-evidence/snapshot-manifest.json)。快照编号 `3bcf0b01`，位于仓库 `.pytest-tmp-lead-snapshots/3bcf0b01/{sync,lifecycle,ops}`。这是本次验收隔离措施，未修改项目原有 fixture。

### B01：删除撤销遗漏评分

旧 `UndoService._snapshot_projection` 仅保存 `file_meta` 的路径、备注、缓存统计和 URL 六字段；`FileOperationService._restore_projection_snapshot` 也只恢复这六项。正常删除清除整个元数据行，所以撤销后没有恢复原来的 `rating`。正常移动/重命名的路径迁移已经带评分，不能把缺陷泛化成所有文件操作丢元数据。

源码：[undo_service.py](../../AssetsManager/application/undo_service.py)、[file_operation_service.py](../../AssetsManager/application/file_operation_service.py)。目标测试：[test_undo_service.py](../../tests/integration/test_undo_service.py)。恢复时要区分旧格式根本没有评分字段与新格式显式 `null`，并按已有路径冲突规则决定合并语义。

### B02：切库后半程失败没有补偿

`WindowLifecycleCoordinator.switch_library` 只给 `_open_library_session` 加了回滚处理；后续 `_apply_scoped_services`、侧栏和文件面板导航在该处理之外。新库打开已经把窗口 session 指向新库，此时旧库关闭完成。该后半程没有显式异常补偿，但实际界面结果需要沿 Qt 信号链验证。

子代理最初使用 stub 将异常后的 tab 模拟回选旧库；主代理复核发现这一点不符合常规 Qt tab 点击。`WorkspaceBar.currentChanged` 在当前 tab 已切换后才发送 `library_switched`，所以 `MainWindow._on_switch_library` 中读取的 `previous` 通常已是目标库，而且真实 `setCurrentIndex` 可能再次发信号。子代理据此撤回“真实旧 tab / 新 session”的结论和 P1 定性。

该 stub 只能说明 coordinator 本身在此异常分支不主动关闭新会话；它不证明最终 tab、面板状态、真实数据库/锁泄漏或用户误写。

第二批使用真实 QApplication、WorkspaceSection/WorkspaceBar、MainWindow 生产切换方法及 ApplicationBootstrap session，并在初始旧库完整绑定和导航后注入一次 file_list 绑定失败。实测标签页和当前会话均指向新库，info 已绑定新会话，其余记录面板仍持有已关闭的旧会话；直接重试当前库被 coordinator 的同根判断跳过，切回旧 tab 再切新 tab 才恢复。观察到的信号路径为 new/old/new，没有递归信号。面板是记录型 QWidget 测试替身，因此这证明编排和绑定状态，不代表已验证真实面板渲染或发生数据损失。现按 P2 稳定性缺陷修复，并增加绑定及导航失败回滚用例。

源码：[window_lifecycle_coordinator.py](../../AssetsManager/window_lifecycle_coordinator.py)、[window.py](../../AssetsManager/window.py)、[workspace_bar.py](../../AssetsManager/widgets/workspace_bar.py)。

### B03：评分与集合失效链

`MetadataService.set_rating` 发布 `AssetRatingChanged`，但 `RuntimeEventRouter.EVENT_DOMAINS` 和路径提取未处理它，因而评分变化本身不推进 runtime revision。智能集合支持标签、FTS、评分、收藏等条件，但相关写操作不完整地失效 `collections`。WebUI `Sidebar` 只在 collections 事件后刷新集合清单，已缓存的 `collectionMembers` 不会因此清除，展开结果仍可能陈旧。

第二批主代理沿真实消费链发现 `RealtimeContext.tsx` 的 `projectionDomains` 白名单也遗漏 `collections`，`asEvent` 会拒绝包含该域的整条通知。必须同时修正接收器并通过真实 Provider 测试验证，否则扩大后端映射反而会让相关文件和标签通知一并丢弃。另核对 notes/tags 的 FTS 写入与发布通知的顺序，要求通知回调中已经能读到最终查询状态。

源码：[runtime_events.py](../../AssetsManager/application/runtime_events.py)、[collection_service.py](../../AssetsManager/application/collection_service.py)、[Sidebar.tsx](../../webui/src/components/layout/Sidebar.tsx)。验收必须同时覆盖服务事件映射和已展开集合重取；只添加一个 mapping 不能闭环。

### B04：既有 ZIP DTO 漂移

当前 `StatsResponse` 增加 `zip_resources`，生成契约检查要求增加 `ZipResourcesResponse | null`，当前 `contracts.ts` 没有该字段。生成器的类型注册也需核对嵌套的资源与清理诊断类型，不能只再生文件而不运行类型检查。本项来源于本轮之前已在工作树中的 LAN 改动，不属于 B01 引入的回归。

## 验证记录

以下测试集合不合并计数。Python 测试使用捕获的当前工作区快照，未运行原库中的测试清理逻辑，未操作真实用户资产。

| 范围 | 结果 |
|---|---|
| sync：runtime events + metadata/tag routes | 22 passed，0 skipped，exit 0 |
| lifecycle：指定 session/runtime/reconciliation 场景 | 6 passed，0 skipped，exit 0 |
| lifecycle：window switching + LAN failure 场景 | 23 passed，0 skipped，exit 0 |
| 原工作区 `python scripts/check_boundaries.py` | exit 0 |
| 原工作区 `python scripts/check_route_capabilities.py` | exit 0，0 violation |
| 原工作区 `python scripts/check_frontend_data_fetch.py` | exit 0，10 pages / 0 violation |
| 原工作区 `python scripts/gen_ts_types.py --check` | exit 1，B04 所述既有漂移 |

sync 快照命令：

```powershell
pytest -o addopts='' -p no:cacheprovider --basetemp=.pytest-tmp-sync tests/integration/test_runtime_events.py tests/lan/test_metadata_tag_mutation_routes.py
```

lifecycle 快照命令：

```powershell
python -m pytest -q -o addopts='' -p no:cacheprovider --basetemp=.pytest-tmp-lifecycle tests/integration/test_library_service.py::test_close_session_serializes_same_root_reopen_through_db_teardown tests/integration/test_library_service.py::test_failed_close_keeps_library_lock_until_retry_succeeds tests/unit/test_library_runtime.py::test_session_close_stops_runtime_adapter_before_drain_and_cache_release tests/unit/test_library_runtime.py::test_close_session_retains_runtime_and_database_after_adapter_stop_failure tests/integration/test_reconciliation_runtime_lifecycle.py
python -m pytest -q -o addopts='' -p no:cacheprovider --basetemp=.pytest-tmp-lifecycle tests/unit/test_window_session_switching.py tests/integration/test_window_lifecycle_lan_failure.py
```

上述既有测试没有覆盖本次新发现的所有行为，因此通过不反驳缺陷。

## B01 实施与最终验收

执行：Terra 文件操作子代理。审查：主代理。生产改动严格限制在 `undo_service.py` 和 `file_operation_service.py`；测试在 `tests/integration/test_undo_service.py`。

- 新 snapshot 的 `file_meta` 行追加 `rating`，保留现有 snapshot 格式标记；恢复器兼容六字段旧行和七字段新行。
- 旧行没有评分意图：新插入的元数据为未评分，发生路径冲突时保留已有评分。
- 新行明确保存评分：恢复 `0..5`，也准确恢复显式 `None`，不会用 truthiness 或 COALESCE 丢掉清空语义。其他元数据合并规则不变。
- 新增回归覆盖完整 delete/undo/redo/undo、目录子文件、旧格式缺行与已有评分、新格式显式未评分。

红灯阶段在 ops 快照运行最小临时测试 `test_delete_undo_restores_rating`（随后被最终参数化用例取代）：

```powershell
python -m pytest -o addopts='' -p no:cacheprovider --basetemp=.pytest-tmp-ops tests/integration/test_undo_service.py::test_delete_undo_restores_rating
```

结果 exit 1，断言为 `None == 4`。直接合成文件流程也得到 `before=4 / after_delete=None / undone=True / after_undo=None`。该红灯不是只验证内部 tuple 形状。

最终 ops 快照运行：

```powershell
python -m pytest -q -o addopts='' -p no:cacheprovider --basetemp=.pytest-tmp-ops tests/integration/test_undo_service.py tests/integration/test_file_operation_service.py
```

收集 128 项、执行到 100%、退出码 0；工具未返回尾部 pass/skip 摘要，因此本记录不将 128 宣称为独立通过数。此前针对性回归 12 passed / exit 0，后续补充的旧格式参数化已包含在最终两个完整模块中。以后验收首次运行应同时保存 JUnit 结果，减少输出截断导致的证据缺口。

主代理最终检查：

```powershell
python -m ruff check AssetsManager/application/undo_service.py AssetsManager/application/file_operation_service.py tests/integration/test_undo_service.py
python -m pyright AssetsManager/application/undo_service.py AssetsManager/application/file_operation_service.py
git diff --check -- AssetsManager/application/undo_service.py AssetsManager/application/file_operation_service.py tests/integration/test_undo_service.py
```

Ruff 通过；Pyright 为 0 errors / 0 warnings；diff check 退出 0。未运行 GUI、性能压测或全仓库发布验收。`gen_ts_types.py --check` 的既有 ZIP 漂移仍存在。

平台：Windows 11 build 26220，Python 3.14.3，pytest 9.0.2，PySide6 6.11.0，aiohttp 3.14.0。

主代理独立比对最终工作树与执行快照，以下 SHA-256 全部相同：

| 文件 | SHA-256 |
|---|---|
| `AssetsManager/application/undo_service.py` | `46B796020601DC28F18B5F1F938EE5EB356FCC77560CCDBED6297CBBEC2968C9` |
| `AssetsManager/application/file_operation_service.py` | `14AD1C8FF52548762FA4920E52B5F6D1ABC92F4C4193D2E97BD4D0430880DA3F` |
| `tests/integration/test_undo_service.py` | `E7B8EA3CD76A6583F586691EE8F82F8714857234A892FB784C287FC8E5261073` |

## 第二批验收记录

快照 `41417927` 捕获 949 个源码与配置文件，隔离根仍为 sync/lifecycle/ops；新增 WebUI 源码与 package.json 捕获，清单为 [snapshot-41417927-manifest.json](../reports/development-baseline-2026-09-06-evidence/snapshot-41417927-manifest.json)。浏览器测试使用另外同步的 production dist；主代理比对当前 dist 共 23 个文件与浏览器快照，全部哈希一致。

B03 后端最终运行（sync 独立根）：

```powershell
python -m pytest -q -o addopts='' -p no:cacheprovider --basetemp=.pytest-tmp-b03-backend-final2 --junitxml=b03-backend-final2.xml tests/integration/test_runtime_events.py tests/lan/test_runtime_realtime.py tests/unit/test_search_index_service.py tests/integration/test_metadata_service.py tests/integration/test_tag_service.py
```

结果 123 passed / 0 failed / 0 skipped，主代理直接解析 JUnit 并核对五个变动文件与快照 SHA-256 全部相同。回归包括真实评分服务到 runtime router 和 LAN WebSocket，及通知回调中同步读取 notes、tag 增删改名和清空后的 FTS 集合结果。原评分路由和原通知顺序的红灯证据分别为 [b03-red-rating.xml](../reports/development-baseline-2026-09-06-evidence/b03-red-rating.xml)、[b03-fts-order-red.xml](../reports/development-baseline-2026-09-06-evidence/b03-fts-order-red.xml)；最终 [b03-backend-final2.xml](../reports/development-baseline-2026-09-06-evidence/b03-backend-final2.xml)。

前端首轮 Sidebar + RealtimeProvider 共 44 项通过；随后增加身份变更后的迟到 create/delete 响应回归，最终两模块 46 项通过，主代理解析 JUnit 确认 0 failures/errors。相关 Python 生产文件的 Ruff、Pyright，以及当前 TypeScript 契约生成检查均通过。

### B03 全链路验收

侧栏收到集合失效后清除成员缓存，并刷新仍展开的集合；请求代次阻止旧成员响应和跨身份的 create/delete 响应覆盖当前状态。RealtimeProvider 接受 collections 域，包含 files 等其他域的同条通知也能正常分发。最新集合清单请求完成时会补齐展开成员，避免后发的 mutation 刷新覆盖 invalidation 请求后留下空列表。

最终前端命令：

```powershell
npm test -- src/components/layout/Sidebar.test.tsx src/stores/RealtimeContext.test.tsx --reporter=junit --outputFile=b03-final.junit.xml
npm run typecheck
```

46 passed，记录归档为 [b03-frontend-final.xml](../reports/development-baseline-2026-09-06-evidence/b03-frontend-final.xml)；typecheck 和 production build 通过。

ops 独立源码根中的完整实时浏览器模块运行结果为 7 passed / 0 skipped，见 [b03-e2e.xml](../reports/development-baseline-2026-09-06-evidence/b03-e2e.xml)。最终严格评分用例额外独立通过，见 [b03-e2e-focused.xml](../reports/development-baseline-2026-09-06-evidence/b03-e2e-focused.xml)；两次结果不合并计数。真实 `MetadataService.set_rating` 经 LAN WebSocket 让智能集合计数和已展开成员从 0 到 1 再回到 0，全程没有页面重载和模拟失效。脚本、控制台及 HTTP 资源错误列表均为空，包括 B05 字体修复。

执行代理确认 Python 始终从 ops 独立根运行。主代理核对最终 E2E 源码、四个关键后端模块以及全部 23 个 dist 文件与该快照一致。截图：[桌面展开成员](../reports/development-baseline-2026-09-06-evidence/b03-e2e-screenshots/desktop-rating-member.png)、[手机主界面](../reports/development-baseline-2026-09-06-evidence/b03-e2e-screenshots/mobile-main-after-rating.png)。桌面 1280x720 与手机 390x844 的截图均已查看，未见重叠；手机截图与横向溢出检查不等于已验收移动侧栏集合交互，退出成员的断言回到桌面完成。

### B04 最终验收

生成器注册 `ZipResourcesResponse`、`ZipCleanupDiagnosticsResponse`；`StatsResponse.zip_resources` 的线格式为 `zip_resources?: ZipResourcesResponse`，因为后端 `None` 会省略字段，不会输出显式 null。新增回归同时核对生成声明、缺省字段省略和真实嵌套 `to_dict()` 输出。主代理拒绝了第一版不够准确的 optional nullable 声明后，执行代理按线格式收紧类型。

ops 快照运行完整 `tests/unit/test_gen_ts_types.py`，4 passed / 0 failed / 0 skipped，见 [b04-contract-green.xml](../reports/development-baseline-2026-09-06-evidence/b04-contract-green.xml)。`gen_ts_types.py --check`、WebUI typecheck、Ruff 通过。主代理比对三个最终文件与测试快照 SHA-256 全部相同：

| 文件 | SHA-256 |
|---|---|
| `scripts/gen_ts_types.py` | `C0D3F847E1B8585978F1B49700CD49A4EFB9C4F81326AB147DA3CACDE534EF0D` |
| `webui/src/types/contracts.ts` | `95C09DA7CD7EB2A970D5AAA33E1ED7E7880F65308BB77C6D3B1330C578553BCC` |
| `tests/unit/test_gen_ts_types.py` | `9EF20F07085C4108B9F62E1B37999851B4A2539F93520146BF0190AF79BC74EC` |

### B02 最终验收

切库后半程的绑定或导航失败，现在先停止面板任务、关闭失败的新会话，再重开旧库并完整绑定和导航。无法安全完成清理时保留会话句柄和恢复标记，禁用未完成绑定的面板；再次点击当前标签页可重试，成功后重新启用。旧库也无法打开时不伪装有活跃会话，保留目标标签页作为重试入口。主窗口以实际会话决定失败后的标签页选择，回滚选择阻断向外的切库信号；指示条使用信号处理后实际选中的索引。

真实 Qt 核验确认 `QTabBar.setCurrentIndex(-1)` 不能清空非空标签栏，因此未采用此实现，也没有删除用户标签页。重试信号仅在左键按下前已选中、且在同一标签页释放时发出，首次点击新标签页不会同次释放立即隐式重试。

最终 lifecycle 快照命令：

```powershell
python -m pytest -q -o addopts='' -p no:cacheprovider --basetemp=.pytest-tmp-b02 --junitxml=artifacts/b02-window-switch-final.xml tests/integration/test_window_lifecycle_lan_failure.py tests/integration/test_window_switch_failure_recovery.py tests/unit/test_window_session_switching.py tests/unit/test_workspace_bar.py tests/unit/test_low_batch_window.py
```

45 passed / 0 failed / 0 skipped，主代理直接解析 [b02-window-switch-final.xml](../reports/development-baseline-2026-09-06-evidence/b02-window-switch-final.xml) 并核对五个修改文件与快照哈希全部一致。新增 7 个场景涵盖绑定、两处导航、关闭失败保留、恢复绑定失败、打开失败回滚、无会话后的真实鼠标重试。Ruff、相关 Pyright、边界与路由权限检查通过。

局限：新增测试的 QApplication、WorkspaceSection、Qt 信号、QTest 点击和库会话均为真实实现，但面板是记录型 QWidget 替身；不据此宣称验证了每个真实面板的渲染和全部工作线程。初始缺陷观察见 [b02-window-switch-probe.xml](../reports/development-baseline-2026-09-06-evidence/b02-window-switch-probe.xml)。

### B05 字体静态路由

真实 Chromium 验收发现 `/fonts/inter-var-latin.woff2` 返回 404。主代理确认字体文件在原仓库 public、production dist 和隔离 dist 中均存在，根因为 `lan/api.py` 只挂载 Vite assets，没有挂载 fonts。按现有静态资源策略补上仅指向 `SPA_DIR/fonts` 的 `/fonts`，关闭目录列表。

sync 快照执行 `tests/lan/test_spa_font_assets.py tests/lan/test_t2_t4_contracts.py`，14 passed / 0 failed / 0 skipped。新回归验证字体字节、200 和 `font/woff2`，以及目录不列举、编码越界不泄露邻近文件；红灯 [b05-font-red.xml](../reports/development-baseline-2026-09-06-evidence/b05-font-red.xml)，绿灯 [b05-font-green.xml](../reports/development-baseline-2026-09-06-evidence/b05-font-green.xml)。主代理核对两个修改文件与 sync 快照哈希相同；浏览器已同步该修复，以不含字体错误白名单的严格断言通过。

本批未运行全仓库发布验收或性能压测，也没有提交、合并或发布工作树。架构图集仍是生成时的源码快照；本台账补充其后修复的行为和验收证据。

### B00 永久测试隔离验收

根 `tests/conftest.py` 在导入任何 `AssetsManager` 模块之前创建唯一的 `.pytest-runtime/<pid>-<uuid>` 运行域，并设置 `AM_RUNTIME_ROOT`、`TMP`、`TEMP`、`TMPDIR` 和 `tempfile.tempdir`。普通应用子进程继承同一运行域，嵌套 pytest 创建兄弟运行域；显式 `AM_KEEP_TEST_RUNTIME_DATA=1` 可保留诊断目录。`pytest.ini` 不再指定共享的固定 `--basetemp`，默认 basetemp 绑定到当前运行域；sessionfinish 不提前删除目录，由带 owner token 的 atexit 清理。

最新独立源码快照 `38fa2509` 验证记录：

- 路径解析、导入时常量、普通子进程继承及嵌套 pytest：49 passed，见 [b00-path-isolation-38fa2509.xml](../reports/development-baseline-2026-09-06-evidence/b00-path-isolation-38fa2509.xml)。
- xdist `--dist=each -n 2`：16 passed；两个 worker 的运行域不同且退出后清理，见 [b00-xdist-each-38fa2509.xml](../reports/development-baseline-2026-09-06-evidence/b00-xdist-each-38fa2509.xml)。
- xdist 组合探针：10 passed，见 [b00-xdist-workers-38fa2509.xml](../reports/development-baseline-2026-09-06-evidence/b00-xdist-workers-38fa2509.xml)；嵌套/覆盖配置回归 2 passed，见 [b00-xdist-final-38fa2509.xml](../reports/development-baseline-2026-09-06-evidence/b00-xdist-final-38fa2509.xml)。

所有 Python 验收均从独立源码快照运行，未运行原工作区 pytest。快照验收后工作树又收紧了清理异常处理并修正文档字符串；当前最新 SHA-256：`tests/conftest.py` `D5B517B923B60816B81A04A9589C55579F17A900D55D3C8D8AD72239E332CC80A`、`tests/test_support/runtime_isolation.py` `3BC4B376578B66DE6769C2621235BA569554CA7B682F87EBFAFCEDC33528D1DD`。其余快照文件仍为 `tests/test_support/test_runtime_isolation.py` `13059080ADBD913F90762259B2BAF74BAC74E840D4A79AC0979A9CA307112258`、`pytest.ini` `4A55323381F56B7107F563DD208AC7A706D2F7231DFC5B8F4A59F5B249307FC`、`AssetsManager/core/path_resolver.py` `B8503C403916E962C0B714FDD0B2EC991B58CBD1EB76721E0B4569B72714AF96`、`tests/core/test_path_resolver.py` `CF70FCDF237C80C2D8753C5197A6B572DFB704023AC3A9CDF95DBB7BA73FFF8E`。Ruff、Pyright 和 diff check 通过。

已知边界：若用户显式传入同一个 `--basetemp` 给多个并发 pytest 进程，调用方仍需自行保证目录独占；默认路径和应用子进程路径已由测试设施隔离。测试运行域容器本身可能保留为空目录，但每个带 owner token 的运行域都会在进程退出时删除。
