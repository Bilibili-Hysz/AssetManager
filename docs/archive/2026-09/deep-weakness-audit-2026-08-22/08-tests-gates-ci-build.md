# 08 · 测试体系·质量门禁·CI/CD·构建打包·性能基础设施审计（2026-08-22）

**范围**：pytest.ini/pyrightconfig.json/ruff.toml/requirements*.txt、tests/ 全目录（抽样）、scripts/check_*.py 门禁脚本、.github/workflows/ci.yml 与 release.yml、build.py/AssetManager.spec/setup_cython.py、cloudflared 二进制处理、tests/performance 与 tests/perf、根目录遗留物版本控制卫生。
**基线**：commit `5fbf930` 脏工作树（118 修改 + 54 未跟踪）。测试规模约 3941 个用例（collect 实测 3924/3941，17 个 e2e/perf 被 deselect）。

## 总体评估

这个项目的质量工程体系在"设计文档层面"相当成熟：8 个 `check_*.py` 门禁脚本全部进了 CI lint job、审计 manifest 校验器（check_audit_reports.py）有 SHA/锚点/超链接/图环校验、契约测试用 golden fixture 双向锁定、conftest 对 RuntimeData 的清理启发式考虑了大量边界。测试目录分层（unit 105 / integration 54 / lan 51 / desktop 37）清晰。

但存在一个压倒性的事实：**该仓库没有任何 git remote**（`git remote -v` 为空，备份走 `mirror/*.bundle`）。README 声称的整套 CI 矩阵——Python 3.12/3.13/3.14、Windows package smoke、浏览器 E2E——**从未在此仓库上实际运行过**，全部是"纸上门禁"。叠加 ci.yml 的触发条件只限 master/main 的 push/PR，当前特性分支上的 172 处变更（大量 fixed-unverified）没有走过任何 CI 验证路径。此外 release 流程（tag 直推构建发布）不依赖任何测试 job，cloudflared 运行时下载无完整性校验，性能门禁（唯一有阈值的 test_baselines.py）被 `-m "not perf"` 永久排除在 CI 之外。

测试可靠性方面：conftest 对 pytest 内部实现做了 monkeypatch、自定义 tmp_path 完全绕开 `--basetemp`、`_cleanup_stores` 只覆盖 2 个全局状态点而生产代码里有 15+ 处模块级可变全局；HANDOVER 文档明确承认 6 个已知失败/偶发测试靠口头约定"不算回归"而非 quarantine 机制。Windows 特有语义（junction、symlink 特权、文件锁）在全量跑的 ubuntu lane 上系统性缺失。

## 主要发现（按严重度排序）

### [P0][CI/CD] 仓库无远程，全部 CI 门禁从未执行过 ✓已复核
- 位置：仓库根（`git remote -v` 输出为空）；docs/HANDOVER-2026-08-15.md:80（"本地 git master（无远程）……提交后刷新 mirror/…bundle"）
- 证据：`.github/workflows/ci.yml` 与 `release.yml` 设计了 8 个 job，但备份机制是本地 bundle 文件（mirror/ 下 5 个 bundle，8/13~8/15）。README:434-440 描述的"Lint/Type Check/Python Test Matrix(3.12/3.13/3.14)/Windows Package Smoke/浏览器 E2E"没有任何一次真实运行记录。
- 影响：所有质量门为未验证状态；`pyright==1.1.410` 钉死、ubuntu-only 全量测试、paths 行为等都无法被证伪；README 对用户/贡献者构成虚假质量承诺。
- 建议：推到 GitHub（或私有 Gitea）使 CI 真实运行；至少在 CI 落地前把 README 的"质量门"章节标注为"目标态"。

### [P0][CI/CD] CI 触发只限 master/main，特性分支零 CI + 172 处变更 fixed-unverified ✓已复核
- 位置：`.github/workflows/ci.yml:3-7`（`branches: [master, main]`）；工作区状态（118 修改 + 54 未跟踪）
- 证据：`on: push/pull_request: branches: [master, main]`；当前分支 feat/quality-audit-2026-08-17 上的变更只有等 PR 才会触发 CI——而本仓库甚至没有远程可发 PR。
- 影响：质量审计分支本身的修复（reconciliation、lan 安全、desktop 面板等大面积改动）从未被矩阵验证，"fixed-unverified"状态无收敛路径。
- 建议：push 触发放宽到 `**` 或至少当前工作分支；配合远端落地。

### [P0][供应链] cloudflared 运行时下载：latest URL + 无哈希/签名校验即执行 ✓已复核
- 位置：`AssetsManager/lan/tunnel.py:25`（`_CLOUDFLARED_URL = ".../releases/latest/download/cloudflared-windows-amd64.exe"`）、`:38-48`
- 证据：`urllib.request.urlopen(_CLOUDFLARED_URL)` 下载后唯一验证是 `--version` 冒烟（:59 "non-empty and executable"），无 sha256 pin、无版本锁定、无签名验证，下载即写入共享目录并在用户会话执行。
- 影响：GitHub release/账号被劫持或中间人（TLS 之外的投毒面）时任意代码进入桌面进程；`latest` 还使行为不可复现。仓库根的 cloudflared-windows-amd64.exe（54MB，未跟踪，已被 ignore）说明本地存在预下载副本，但分发路径不受控。
- 建议：钉死版本 + 内置官方 sha256 清单校验；或改为引导用户 `winget install cloudflare.cloudflared`。

### [P1][CI/CD] release.yml 发布不依赖任何测试/CI 状态，且产物无代码签名
- 位置：`.github/workflows/release.yml:3-5`（`on: push: tags: ["v*"]`）、build-windows job（无 `needs`、无 workflow_run 门）
- 证据：tag 推送直接构建 → `gh release upload`（:114）。没有任何步骤检查该 commit 的 CI 是否通过。产物有 SHA256 校验和文件（:55-56，好实践）但无 Authenticode 签名。
- 影响：可在测试红/未验证的 commit 上发版；无签名的 Windows 桌面发行包会触发 SmartScreen，且用户无来源验证手段。
- 建议：release job 增加 CI 成功前置（如 `workflow_run` 或 gh api 查 check-runs）；引入签名（哪怕自签名 + 校验和页说明）。

### [P1][性能] 性能门禁从未自动执行；test_cython_benchmarks 断言恒真
- 位置：`pytest.ini:9`（`-m "not e2e and not perf"`）；`.github/workflows/ci.yml:257`（`pytest -q --tb=short`，无 `-m perf`）；`tests/performance/test_cython_benchmarks.py:19,33,43,57`（`assert set_ops > 0`）
- 证据：`tests/performance/test_baselines.py:15` 有 `pytestmark = pytest.mark.perf` + 明确阈值（1k 列表 2s、10k 15s 等），但 perf 被默认排除且 CI 无 opt-in job；test_cython_benchmarks.py **无 perf 标记**（默认每次全量都跑）而全部断言是 `> 0` 恒真——名为基准实为无意义开销，也无法区分 Cython .pyd 与纯 Python fallback。README:379/393 把这两个文件描述为性能里程碑。
- 影响：唯一带阈值的性能防线零执行；10x 级回归（历史上真实发生过 PBKDF2 入循环类问题，commit afd2d2b）只能靠手工跑发现。tests/perf/ 下 7 个手工 telemetry runner 的 p50/p95/p99 统计方法本身不错，但无阈值对比，只产出审计 artifact。
- 建议：删掉恒真断言或改为相对基线比率；在 CI 加一个宽松阈值的 nightly perf lane（已有阈值常量，成本极低）。

### [P1][测试盲区] 生产平台是 Windows，全量测试却只在 ubuntu 跑；junction/win32 语义零 CI 覆盖
- 位置：`.github/workflows/ci.yml:232-257`（test job `runs-on: ubuntu-latest`）；`:180-201`（windows-regression 仅 4 个文件 + `-k` 过滤）；`tests/unit/test_library_export_service.py:1284`（`skipif(sys.platform != "win32")` junction 测试）
- 证据：3924 个测试默认在 ubuntu 执行；Windows lane 只有 path_resolver/path_guard/lan_api/undo_service 的 `-k` 子集。junction 测试（win32 专属）在 ubuntu 永远 skip，windows-regression 不包含它；symlink 系列（test_gallery_service.py:157 等 10+ 处 skip）在 ubuntu 以 POSIX symlink 语义跑，而 Windows 生产环境是特权 symlink + junction 混合语义。
- 影响：Windows 文件系统特有行为（锁句柄、junction 解析、大小写不敏感路径、WinError 5/1314）大部分只在开发者本地覆盖；ubuntu 上的"绿"不能外推到生产平台。
- 建议：把 windows lane 扩为按目录选择的全量（至少 unit+integration），或用 marker（如 `@pytest.mark.windows_only`）显式收集 Windows 语义测试进该 job。

### [P1][测试可靠性] 已知 flaky/必失败测试无隔离机制，靠口头约定"不算回归"
- 位置：`docs/HANDOVER-2026-08-15.md:31`、`docs/HANDOVER-PROMPT.md:15`
- 证据："4 个 multiprocessing 命名管道测试必失败（EPERM），属环境限制不算回归；test_dot_entries_and_files_are_ignored（watcher mtime）与 test_share_download_records_response_ready… 偶发（时序）"。
- 影响：红=绿的常态化使真实回归淹没在噪声里；接手者只能靠文档约定判断哪些失败可忽略。tests/ 全目录 time.sleep 123 处/32 文件（如 test_gallery_incremental.py:267 `sleep(0.5)`、:427 `sleep(0.6)`），时序脆弱面广。pytest.ini 无 pytest-timeout，`QThreadPool.globalInstance().waitForDone()`（tests/conftest.py:476）无超时——挂起线程会无限挂住会话。
- 建议：对已知 flaky 用 `pytest.mark.flaky`/xfail(strict=False) 显式登记；引入 pytest-timeout 全局兜底；逐步把 sleep-poll 改为事件等待。

### [P1][测试与生产漂移] LAN 测试用自制中间件 + FakeLan 替换生产装配，生产中间件栈顺序无契约
- 位置：`tests/lan/test_lan_api.py:1053-1125`（`_make_lan_app` 的 `_test_auth_middleware` + `_FakeLan`）；test_lan_api.py 内 monkeypatch 共 114 处（全测试树 1226 处 monkeypatch，56 处直接 setattr 生产模块路径）
- 证据：测试客户端的认证由测试专用中间件完成，从不经过 `lan/server.py` 的真实中间件装配（IP 白名单、安全头、限流顺序）；`_FakeLan` 替换 `LAN_APP_KEY`。生产装配顺序只有 test_security_preflight_integration 等少数文件触及。
- 影响：生产 server.py 中间件顺序调整/新增安全中间件不会被主 API 测试发现；114 处 monkeypatch 使 6526 行的 test_lan_api.py 对重构高度敏感。
- 建议：增加一个"真实装配冒烟"测试：用 `LanServer`（或 `_LanServerImpl`）真实 start 在随机端口，对 3-5 个代表性路由断言响应。

### [P1][全局状态] `_cleanup_stores` 清理覆盖严重不全，新全局状态无登记机制
- 位置：`tests/conftest.py:465-502`（仅 `DatabaseManager.close()` + `event_bus._instance = None`）
- 证据：生产模块级可变全局至少还有——`library_service._root_ownership/_root_generations/_root_restore_recovery`（library_service.py:71-73）、`thumbnail_service._cache`（:29）、`library_lock._held_locks`（:22）、`workers._retained_pools`（:19）、`i18n._current_lang/_translations`、`themes._cached_stylesheet*`、`file_operation_service._path_locks`（:141）、AppSettings/TagLibrary/SignalBus 单例（conftest 只快照恢复 settings.json 等 3 个文件，内存态不清）。且 `mgr._connections`（conftest.py:484）直接访问私有属性。
- 影响：跨测试状态泄漏（thumbnail 缓存、根所有权代数、i18n 语言）依赖各测试文件自律清理；新增全局状态（本次 172 变更里的 reconciliation/import_manifest 等 store）不会自动纳入，xdist 并行下泄漏放大为顺序依赖型 flaky。
- 建议：提供中心化登记 API（如 `register_global_reset(fn)`），conftest 统一调用；对已知全局点补齐 reset。

### [P1][构建] release 与本地/ci-smoke 构建路径三向漂移
- 位置：`build.py:29-54`（`optimize()` 删 Qt DLL/翻译）；`release.yml:32-34`（workspace cwd 直接 `pyinstaller AssetManager.spec`）；`ci.yml:132-147`（package-smoke 从 foreign cwd + 独立 distpath/workpath）；`AssetManager.spec:207 vs 225`（`upx=False` 与 COLLECT `upx=True` 不一致）
- 证据：release 不运行 build.py 的 optimize——本地构建产物比发布产物小（删了 Qt6Quick.dll 等 6 个 DLL + 翻译文件）；check_package_contents.py 无法发现"多了应删的文件"。spec 的 hiddenimports 是 2026-06-10 重构时的手工清单（spec:4），不含本次新增的 reconciliation_queue*/import/favorite/library_watcher 等模块，依赖 PyInstaller 静态分析 + `--package-smoke` 兜底。
- 影响：本地验证过的包 ≠ 发布的包；"foreign cwd 构建"仅 ci-smoke 验证而 release 不验证（路径相关 bug 只在一侧暴露）；upx 不一致属潜在杀软误报面。
- 建议：release 复用与 ci-smoke 完全相同的构建脚本（含 optimize 与 foreign-cwd）；spec 的 upx 统一为 False。

### [P2][CI/CD] pyright 钉死 1.1.410 两年未动 + basic 模式 + 关闭 missingImports
- 位置：`ci.yml:83`（`pip install pyright==1.1.410`，注释"bump deliberately"）；`pyrightconfig.json:28-31`（`typeCheckingMode: basic`、`reportMissingImports: false`）
- 证据：1.1.410 约为 2024 年中的版本，无法检查 3.13/3.14 新类型特性与 stdlib 类型改进；basic 模式 + 关闭缺失导入意味着依赖 API 误用大量漏报。include 是 20 项手工清单（pyrightconfig.json:2-21），新增顶层文件若忘加则静默不查。
- 影响：类型门禁防线下限低且检测能力陈旧；矩阵声称 3.12-3.14 但类型检查只反映旧版语义。
- 建议：有计划地 bump，include 改为目录通配或加 CI 断言"include 覆盖所有顶层模块"。

### [P2][门禁盲区] ruff/compileall 范围与 README 声明漂移；lint job 假设脚本零依赖
- 位置：`ci.yml:27`（`ruff check AssetsManager tests scripts run.py`——不含 build.py，尽管 ruff.toml:49 为它配了 per-file-ignores）；`ci.yml:251`（`compileall AssetsManager`，README:362 声称 `compileall -q AssetsManager tests`）；lint job 仅 `pip install ruff`（:21）
- 证据：gen_ts_types.py 等门禁脚本目前只用 stdlib（ast/argparse/json），lint job 能跑——但这是隐式契约：任何脚本一旦 import 生产模块或第三方库，lint job 立即崩（无依赖安装）。
- 影响：build.py 游离于 ruff 门禁外；tests/ 的语法错误只在 test job 报；脚本依赖契约脆弱。
- 建议：ruff 命令补 build.py；compileall 对齐 README；lint job 加一行注释断言脚本零第三方依赖或直接安装 requirements。

### [P2][测试基建] conftest monkeypatch pytest 内部 + 自定义 tmp_path 绕开 --basetemp
- 位置：`tests/conftest.py:22-34`（替换 `_pytest_tmpdir_plugin.cleanup_dead_symlinks`）；`:427-438`（自定义 `tmp_path` 用 `tempfile.mkdtemp`，非沙盒时不理会 `--basetemp`）
- 证据：对 pytest 私有模块打补丁在 pytest 升级时可能直接 ImportError/失效；`cleanup_dead_symlinks` 吞 PermissionError 也可能掩盖真实权限回归。自定义 tmp_path 丢弃了 pytest 原生 numbered/retention 语义（这正是根目录出现 7 个 `.pytest-tmp*` 目录与 HANDOVER"不传 --basetemp"告诫的根源之一）。
- 影响：测试基建与 pytest 版本强耦合；调试时无法保留测试现场。
- 建议：补丁改为按 pytest 版本探测 + 显式跳过；tmp_path 覆盖仅在沙盒检测分支启用，否则回退内建实现。

### [P2][依赖] requirements 全部下限浮动，无锁定文件，release 构建不可复现
- 位置：`requirements.txt`（`PySide6>=6.6,<7` 等）、`requirements-dev.txt`（`pyinstaller>=6.0`、`pytest>=8.0`）、`requirements-lan.txt`、`requirements-perf.txt`（仅 `PySide6==6.11.0`）
- 证据：CI/release 每次 `pip install` 拿最新版；PyInstaller 大版本变更（6.x → 7）会自动进入发布构建；唯一 pin 是 perf 环境的 PySide6。
- 影响：同一 tag 重跑 release 产物字节不同（校验和失去复现意义）；上游破坏性更新随时可能击穿发版。
- 建议：为发布引入 constraints/lock（pip-compile 或 `pip freeze` 快照），PyInstaller/PySide6 至少 lock 到次版本。

### [P2][e2e] 浏览器 E2E 声明与实际覆盖差距大
- 位置：`tests/e2e/`（仅 1 文件 test_webui_realtime_acceptance.py，306 行 6 测试）；`ci.yml:276-277`（webui-e2e 注释"Mock/Shell; real backend optional"）；`webui/e2e/commerce-real-backend.spec.ts:20`（依赖环境变量，CI 未设置即 skip）
- 证据：Python 侧真实浏览器验收仅覆盖 realtime recovery 一个主题；webui 的 commerce 真后端 spec 在 CI 全部 skip；README 对外表述是"浏览器 E2E"门禁。
- 影响：前后端集成（尤其是 commerce/quota/websocket 组合流）的端到端信心主要来自 mock 层。
- 建议：python-browser-e2e job（已是 Windows+真实 LAN server+Chromium）扩 2-3 个核心用户旅程；webui real-backend spec 在 CI 可选挂一个 Python sidecar。

### [P2 边缘][pytest 配置] stress 标记注释与行为矛盾；无 timeout；markers 少数未注册
- 位置：`pytest.ini:9 vs :14`（addopts 只排除 e2e/perf，stress 注释称"opt in"但 shutdown 压力测试实际每次全量都跑——tests/integration/test_shutdown_stress.py:411 `pytest.mark.stress`）
- 证据：stress 无 deselect；无 pytest-timeout。
- 影响：全量时长被压力测试拖累；文档误导。
- 建议：addopts 补 `and not stress`，或改注释。

## 次要问题清单

- 根目录遗留物（_q1_complete.txt、_q1_gates.txt、_quality_audit_2026_08_17.md、_quality_report.md、crash.log、7 个 .pytest-tmp* 目录、tmp/、mirror/、54MB cloudflared exe）均已确认被 .gitignore 覆盖（`/_*`、`*.log`、`/.pytest-*/` 等规则）——是本地卫生问题而非 git 污染，但建议归档到 docs/ 或删除
- .gitignore:124 的 `/_*` 规则过宽：未来任何下划线开头的应跟踪根文件会被静默忽略
- `DeepSeek Docs/`（含中文路径设计文档）被 git 跟踪且被 check_boundaries.py:4 引用为验收标准来源——文档即门禁依据但命名含空格，脚本引用脆弱
- 整文件 skip：tests/integration/test_reconciliation_queue_process_termination.py:20-22（Windows spawn 非确定性，靠 subprocess 变体替代覆盖）
- collect-only 耗时 236 秒（3941 用例）——收集阶段导入成本高，拖慢每次 CI 与本地迭代
- check_boundaries.py:66 跳过 `__init__.py` 且为 substring 匹配（`"Repository" "("` 拼接可绕过）
- ci.yml 用浮动 tag（actions/checkout@v4）而 release.yml 用 SHA pin——同一仓库两种供应链标准
- hygiene job 只查 whitespace，不查意外提交的大二进制
- pytest.ini:9 两处模块级 DeprecationWarning 特赦无清理期限注释
- fixtures/db/v1_schema.sql 是冻结历史快照（头部标注来源 commit），有 test_db_migrations.py 对账测试兜底，机制尚可，但需注意 `database._SCHEMA` 基线变更时同步重录
- tests/lan/support/legacy_runtime_adapter.py 是"仅为旧 fixture 服务"的测试适配层（171 行），提示 LAN 测试夹具技术债

## 门禁覆盖矩阵

| 脚本 / CI Job | 检查什么 | 进 CI？ | 盲区 |
|---|---|---|---|
| scripts/gen_ts_types.py --check | DTO→TS 契约漂移 | 是（lint）* | 仅映射 9 个 DTO，新公共 DTO 不加映射不报错 |
| scripts/check_boundaries.py | 传输 URL/仓库构造/连接泄漏 + 层 DAG | 是（lint）* | substring 可拼接绕过；跳过 __init__.py |
| scripts/check_layers.py | import DAG 方向 | 是（lint）* | 未登记的新顶层包（parts>2 未知层）静默跳过 |
| scripts/check_style_sources.py | QSS 颜色/字号来自主题令牌 | 是（lint）* | 同为静态扫描类局限 |
| scripts/check_route_capabilities.py | LAN 写路由声明授权能力 | 是（lint）* | 声明与实际 handler 行为的一致性靠测试 |
| scripts/check_frontend_data_fetch.py | 页面禁用直连 api 工厂 | 是（lint）* | grep 型；只扫 pages/ |
| scripts/gen_web_tokens.py --check | Web 设计令牌生成漂移 | 是（lint）* | — |
| scripts/check_doc_stats.py | README 结构计数 | 是（lint）* | README 质量门描述与 CI 实际有多处漂移 |
| scripts/check_audit_reports.py | 审计 manifest 完整性 | 是（lint）*；实测通过（19 manifest） | fixed-unverified 可永久合法存在，无复验 SLA |
| scripts/check_package_contents.py | 打包资源存在性 | 是（package-smoke + release） | 只验"该在的在"，不验"多余的删" |
| icon_render_probe / migrate_legacy_icons / cleanup_undo_zombies.ps1 | 手工工具 | 否 | 手工运行，无强制 |
| pyright | 类型检查 | 是* | 钉 1.1.410（约 2024 年中）；basic 模式；missingImports=false；include 手工清单 |
| ruff | lint | 是* | 不含 build.py；无 S（安全）规则族 |
| compileall | 语法编译 | 是* | 仅 AssetsManager（README 声称含 tests） |
| test（3.12/3.13/3.14, ubuntu） | 全量 pytest（非 e2e/perf） | 是* | Windows 语义缺失；flaky 无隔离 |
| windows-regression | 4 文件 + -k 过滤 | 是* | 覆盖面极窄，不含 junction/symlink 桌面测试 |
| package-smoke | 冻结包导入/图标/15s 存活 | 是* | 不验证功能面；与 release 构建路径漂移 |
| python-browser-e2e | 1 文件 6 测试（Windows+Chromium） | 是* | 单主题（realtime） |
| webui-e2e | Playwright（mock/shell） | 是* | real-backend spec 靠环境变量，CI 恒 skip |
| tests/performance/test_baselines.py | 性能阈值 | **否** | 被默认排除，无 opt-in job——唯一有阈值的性能门禁零执行 |
| tests/perf/* telemetry runners | p50/p95/p99 手工证据 | 否（手工） | 无阈值对比，仅产 artifact |
| release.yml | 构建发布 | 是（tag 触发）* | 不依赖 CI 测试结果；无签名；与 smoke 构建路径不一致 |

\* "进 CI"指 workflow 中已声明；由于仓库无远程且分支不匹配触发条件，**所有带星号的门禁在当前仓库状态下从未真实执行**（见 P0 前两条）。

**最优先行动建议**：1) 推送仓库到真实远端让 CI 首次运行；2) 给 cloudflared 下载加版本+哈希校验；3) release 增加测试前置；4) 在 CI 加一个 perf 阈值 job 并删除恒真断言；5) 扩大 Windows lane 覆盖。
