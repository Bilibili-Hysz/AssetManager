# 验证基线（07-verification.md）

> 审查日期：2026-08-11 · 全部为**现场实测**（本机 Windows / Python 3.13）

## 1. 实测基线

| 检查 | 命令 | 结果 |
|---|---|---|
| Python 全量测试 | `python -m pytest tests -q` | **2952 passed, 7 skipped, 3 warnings**（304.26s） |
| 静态检查 | `python -m ruff check AssetsManager tests scripts run.py` | **All checks passed** |
| Python 编译 | `python -m compileall`（CI 执行） | CI 全绿（本地未复跑） |
| 类型检查 | pyright（白名单 scope，basic） | CI 0 errors（本地未复跑） |
| 前端单测 | `npm test`（90 Vitest 文件） | CI 全绿 |
| 前端类型 | `npm run typecheck` | CI 全绿 |
| 前端构建 | `npm run build` | CI 全绿 |
| E2E | Playwright 30 用例 | 28 passed / 2 skipped（真实后端 spec 需环境变量） |

**7 个 skip 分布**（全部为 Windows 环境性）：symlink 特权不足（WinError 1314）×6、进程终止非确定性 ×1。

**历史基线链**：603（重构早期）→ 1590（08-01）→ 2034（08-05）→ 2790（08-09）→ 2839（08-11 会话1收尾）→ 2865（审计遗留项轮）→ **2952（P1 轮后）**

## 2. Python 测试体系

| 目录 | 文件数 | 内容 |
|---|---|---|
| tests/unit/ | 57 | 纯逻辑/边界/领域/架构边界（test_architecture_boundaries.py ast 扫描） |
| tests/integration/ | 46 | SQLite/文件系统/服务集成/迁移/对账队列系列 |
| tests/lan/ | 30 | aiohttp 路由/安全/PathGuard/WS/契约（对照 lan_public_contracts.json） |
| tests/desktop/ | 34 | PySide6 offscreen 组件/窗口 |
| tests/core/ | 17 | 数据库/迁移/打包/路径/插件/主题/设置 |
| tests/performance/ | 2 | 基线/cython 基准（对齐 .pyd） |
| tests/e2e/ | 1 | 真实 LAN + Playwright Chromium 实时验收 |
| tests/perf/ | 7 | 基准脚本（非 pytest 用例：grid/thumbnail/directory telemetry） |

**fixtures**（tests/conftest.py）：`temp_dir`/`memory_db`/`schema_db`（_SCHEMA+migrate 完整 schema）+ autouse `_cleanup_stores`（QThreadPool 排空 → close_all_dbs → 重置 EventBus 单例 → 清理 pytest/tmp RuntimeData）。

**markers**：`smoke`/`perf`（pytest.ini：testpaths=tests、pythonpath=AssetsManager、忽略 ResourceWarning+2 个 DeprecationWarning）。

### 测试运行时产物清理（tests/conftest.py）

测试会在 `RuntimeData/` 产生海量残留（曾达 10.5 万目录）。`tests/conftest.py` 提供双层保护：

| 机制 | 时机 | 内容 |
|---|---|---|
| `_preserve_shared_config` | `pytest_sessionstart` | 快照用户配置（settings.json/tag_library.json/tools.json），测试结束后恢复——测试不再永久污染用户配置 |
| `_cleanup_stores`（autouse） | 每个测试后 | 关闭 DB/QThreadPool、重置 EventBus、**从 LibraryService 模块级 `_root_ownership` 移除测试库条目**（防止 session/连接跨测试泄漏与复用已失效会话）、清理本次打开的测试库数据目录（`_is_test_root`：系统 temp 前缀或含 "pytest"） |
| `_cleanup_test_runtime_data` | `pytest_sessionfinish` | ① 有 identity 且 root 在 pytest 工作区 → 删库目录+identity+pending.lock（失败保留 identity 对，下轮新进程重试）；② 孤儿 identity（目录不存在 + test root）→ 删；③ session 窗口内的 `library-*.lock`；④ session 窗口内的 `AssetsManager_undo_*` 备份；⑤ 无 identity 孤儿：纯 `.thumbnails` 立即删、裸 db 经 `library_stats` 反查 root（不可查则 24h 缓冲）、窗口内创建的立即删 |

- **安全边界**：真实用户库（identity 指向非 temp 路径，如 `h:\vrchat\avatars（角色）`、`d:\test\library`）绝不被触碰；无 identity 且含用户侧车文件（favorites.json 等）的目录保留。
- **稳态行为**：reconciliation worker 为 daemon 线程，测试结束时仍持有库连接句柄（同进程无法释放）→ 每轮 sessionfinish 会残留约 190 个"identity 对"（目录+标记），**下一轮 pytest（新进程，无句柄）自动清除**——总量不增长、收敛到稳态。
- **调试开关**：`AM_KEEP_TEST_RUNTIME_DATA=1` 跳过全部清理。
- **已知环境限制**：历史挂起测试进程曾锁死系统 temp 下的 undo 目录（PermissionError WinError 5，cmd/PowerShell 均删不掉；重启后仍锁，疑似 Defender/索引服务）。需管理员执行 `scripts/cleanup_undo_zombies.ps1` 或使用系统磁盘清理。

## 3. 前端测试

- **Vitest 90 文件**（src 内 *.test.ts(x)）：api 契约 14 + client/errors + RealtimeContext(~23)/useWebSocket(~18) + 各 hook/组件/页面 + CSS 契约测试；`run-vitest.mjs` Windows subst workaround
- **Playwright 5 spec**（webui/e2e/）：app（~17 测试，含 375px/1920px 响应式、键盘可达性）、webui-shell、seller、commerce-buyer（mock）、commerce-real-backend（真实后端全链路，需环境变量否则 skip）

## 4. CI（.github/workflows/ci.yml，9 job）

| Job | 平台 | 内容 |
|---|---|---|
| lint | ubuntu | ruff check AssetsManager tests scripts run.py |
| hygiene | ubuntu | git diff --check（PR/push 双模式） |
| typecheck | ubuntu | pyright（pyrightconfig 白名单：application/controllers/core(部分)/di/domain/lan/repositories + 选定 panels/widgets/dialogs；basic 模式；reportMissingImports 关） |
| webui | ubuntu | npm ci + audit + test + typecheck + build |
| package-smoke | windows | webui build → PyInstaller（外部 cwd）→ check_package_contents.py → `--package-smoke`（Qt/图标）→ 15s 冻结运行冒烟 |
| windows-regression | windows | `-k` 定向（library_lock/path_guard/lan_server/share_manager/undo 等平台相关） |
| python-browser-e2e | windows | webui build + tests/e2e/test_webui_realtime_acceptance.py（Chromium 真实 LAN） |
| test | ubuntu | Python 3.12/3.13/3.14 矩阵（3.14 continue-on-error）：compileall + 全量 pytest |
| webui-e2e | ubuntu | Playwright chromium + npm run test:e2e（vite preview） |

全部 `QT_QPA_PLATFORM=offscreen`。

**nightly-perf.yml**：每日 03:17 UTC，requirements-perf.txt（PySide6==6.11.0 锁定）跑 `tests/perf/grid_telemetry_benchmark.py` → artifacts/perf/grid（30 天趋势）。

## 5. 构建打包

- **build.py**：clean → PyInstaller（AssetManager.spec --noconfirm）→ optimize（删非白名单 Qt 翻译保留 en/zh_CN/zh_TW/ja；删 opengl32sw.dll；删 Qt6Quick/Qml/Pdf/OpenGL DLL）→ report（体积统计；历史 127MB 级）
- **AssetManager.spec**：入口 run.py（console=False，EXE AssetManager，icon=Assets/icons/icon.ico）；datas：Assets/icons、i18n 三语言、Assets/Themes、**webui/dist**、Plugins；hiddenimports：PIL/send2trash/PySide6 全家 + aiohttp 全子模块（含 C 扩展 multidict/yarl/aiosignal/frozenlist）+ 全部 lan/application 模块树；excludes：scipy/numpy/pytest/tkinter/QtWebEngine 等
- **--package-smoke**（run.py:27-48）：冻结态验证 QtSvg renderer + icon("settings") 非空，失败 exit 1
- **scripts/check_package_contents.py**：CI 打包资源完整性校验

## 6. 质量门速查命令

```bash
python -m ruff check AssetsManager tests scripts run.py
python -m pytest tests -q                          # 2952 passed 基线（约 5 分钟）
python -m pytest tests/lan -q                      # LAN 全量（约 1.5 分钟）
python -m pytest tests/unit tests/integration -q   # 核心+集成
cd webui && npm test && npm run typecheck && npm run build
```

## 7. 已知测试陷阱（复用索引）

- Windows 挂起诊断：事件循环内同步 DNS（gethostbyname 网卡名）永久挂起——用 daemon 线程+join(timeout)+进程级缓存；faulthandler timeout 无效
- bound 族测试：验证外层事务边界时，`runtime_for` 后必须先 `reconciliation_service.stop()` 再 BEGIN（worker 启动短暂持事务）
- 骨架测试：`object.__new__(_LanServerImpl)` 绕过 __init__，server 新增实例状态（_revoked_tokens 等）需补测试字段
- 测试文件路径易错：workspace_bar 在 tests/unit/；tag_service 在 tests/integration/；undo 在 tests/integration/test_undo_service.py；tag_library 在 tests/unit/；startup 是 test_startup_window.py
- 夹具时钟坑：`_service(now=1000.0)` mock clock 与数据库默认 strftime 基准不同——令牌"最新"判定用 rowid 排序（已免疫）
- tag_metadata 表仅 v3 迁移创建：仅 _SCHEMA 的夹具必须显式建表（_init_lan_schemas 已补）
- tag rename 冲突抛 DuplicateError（非 ValidationError）：路由需单独捕获转 409（已修）
- `QPixmap.fill(0)` 是不透明黑——透明必须 `fill(Qt.GlobalColor.transparent)`
