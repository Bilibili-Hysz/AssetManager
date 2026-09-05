# 06 · 质量工程体系（tests / CI / 构建 / 门禁 / 规范）

> 状态：**DATED ANALYSIS（2026-09-04 实测快照）** · deep-analysis 系列之一，索引见 [README.md](README.md)。
> 方法：并行只读勘察代理全量阅读 tests/、.github/workflows/、构建脚本、门禁脚本与规范配置；分域统计为 `find` 实测。

---

## 1. tests/ 全景

### 1.1 分域统计（实测）

`find tests -name "test_*.py" | wc -l` = **324** 个测试文件（tests/ 下 .py 总数 346，含 conftest/mocks/观测脚本）。

| 分域 | 文件数 | 职责 |
|---|---|---|
| tests/unit | **114** | 纯 Python 逻辑：domain/controllers/filters/repository 错误契约，含"门禁自测"（test_check_boundaries.py、test_layer_dag.py、test_gen_ts_types.py 等测门禁脚本本身） |
| tests/integration | **63** | SQLite/文件系统/服务集成；reconciliation queue 系列占 14 个文件（cutover/heartbeat/fault-injection/跨进程唤醒） |
| tests/lan | **51** | aiohttp LAN 路由与安全（path_guard/tunnel/限流隔离/principal/公开契约）；tests/contracts/lan_public_contracts.json 为契约快照 |
| tests/desktop | **63** | PySide6 offscreen 部件测试（conftest 强制 `QT_QPA_PLATFORM=offscreen`）；snapshots/ 存 stylekit 工厂快照 |
| tests/core | **17** | 核心基础设施（database/path_resolver 等） |
| tests/plugins | **12** | 插件生命周期（autouse 隔离用户设置） |
| tests/e2e | **2** | 真实 Chromium（Playwright sync API）：实时恢复验收 + 缩略图隐私/中介缓存契约 |
| tests/performance | **2** | test_baselines.py + test_cython_benchmarks.py（`pytestmark = pytest.mark.perf`，默认排除） |
| tests/perf/ | 0（非 test） | 6 个手动观测脚本（见 §2） |

> README 正文"unit 106/integration 55/lan 54/desktop 35"是 2026-08-21 的过期口径；当前实测 114/63/51/63。README 头部 stats 标记 `python_test_files=324` 与实测一致（check_doc_stats.py 机制在发挥作用）。

### 1.2 pytest.ini 关键配置

- **并行**：pytest-xdist `-n auto` + `--dist worksteal`；固定端口测试以 `pytestmark = pytest.mark.xdist_group(name="serial")` 串行。
- **默认排除**：`-m "not e2e and not perf"`——e2e 与 perf 须显式选择加入。
- **basetemp 锚定 `.pytest-tmp`**：规避系统临时目录被特权进程锁定时 xdist 启动即 WinError 5。
- **markers**：smoke/perf/e2e/stress（默认套件内运行，可 `-m "not stress"` 反选）；conftest 动态注册 `real_pbkdf2_cost`。
- **无超时配置**：没有 pytest-timeout（见 §9 缺口）。

### 1.3 conftest.py fixture 体系（681 行）

**autouse 全局夹具**：
- `_tag_store_repository_factory_installed`：向 core.tag_store 注入 TagRepository 工厂 seam。
- `_application_provider_seams_installed`：安装 G3/G4 seams（app_settings_provider / tag_canonicalizer / event_bus provider）。
- `_fast_pbkdf2`：把 PBKDF2 成本从生产值（600k/100k/50k）降到 1k/600/1k，结束还原；`real_pbkdf2_cost` 标记或 `AM_REAL_PBKDF2=1` 可退出。密码哈希格式内嵌成本参数，便宜测试哈希与生产成本哈希互验。
- `_cleanup_stores`：yield 后 processEvents + QThreadPool.waitForDone()、关闭 DatabaseManager 单例、重置 EventBus 单例、删除指向 pytest 临时根的 RuntimeData 数据目录。

**普通夹具**：temp_dir / memory_db（`:memory:` + check_same_thread=False）/ **schema_db**（memory_db 上执行 database._SCHEMA + db_migrations.migrate，得到 v46 全量 schema）/ opened_session（完整 ApplicationBootstrap + 临时库 + open_session）/ isolated_plugin_settings / tmp_path 重写（DSH 沙箱下绕开 0o700 ACL 破坏）。

**会话级 RuntimeData 保护（质量工程亮点）**：pytest_sessionstart 快照 Shared/ 下 settings.json/tag_library.json/tools.json，sessionfinish 还原；会话结束清扫按 identity marker 判定"测试根"→ 删除，无 identity 的孤儿目录读 library_stats 判归属（含用户 sidecar 的保留），24h 年龄兜底；清扫有 **30 秒预算**；monkeypatch cleanup_dead_symlinks 容忍沙箱 PermissionError；xdist worker 跳过会话钩子只在 master 执行。

---

## 2. 性能测试三档定位

| 档 | 载体 | 定位 |
|---|---|---|
| **pytest perf 门禁** | tests/performance/test_baselines.py | 阈值护栏：抓 10 倍级回归不做微基准。目录列表 1k≤2s/10k≤15s；单文件元数据均值≤20ms；全量 tag≤100ms；PathGuard≤1ms；索引搜索≤500ms；批量下载 500MB 上限与生产常量一致性断言（防漂移）；DirectoryCache warm 命中**用 os.scandir 计数代替时钟**（比计时更可靠） |
| **手动 perf 脚本** | tests/perf/ 6 个 | 趋势证据，明令禁止当 PR 阈值：perf_baseline（合成库微基准→Markdown 表）、grid/directory/thumbnail telemetry（JSON+XML 工件）、thumbnail_format_experiment（烘焙格式 A/B）、real_io_directory_benchmark（真实只读数据集，声明 cold≠OS 缓存驱逐） |
| **nightly 工件** | nightly-perf.yml | 每日 03:17 UTC，requirements-perf.txt 钉死 PySide6==6.11.0 保证可比性，grid 遥测上传 30 天保留，continue-on-error 不阻塞 |

另有 tests/perf_real_world.py：真实库端到端计时，**硬编码本机路径**（不可移植，属个人观测残留）。

---

## 3. CI 工作流（3 个文件）

### 3.1 ci.yml（9 job，push/PR → master/main，全局 offscreen）

| Job | Runner | 内容 |
|---|---|---|
| lint | ubuntu, Py3.13 | ruff 全路径 → **13 个门禁脚本串联**（gen_ts_types --check、check_boundaries、check_style_sources、check_inline_styles、check_style_dialects、check_route_capabilities、check_frontend_data_fetch、gen_web_tokens --check、check_web_token_usage、check_layers、check_doc_stats、check_documents、check_audit_reports） |
| hygiene | ubuntu, fetch-depth:0 | git diff --check 白空格（PR/push/单 commit 三态兜底） |
| typecheck | ubuntu, Py3.13 | pyright==1.1.410 钉版；先装 requirements+lan+ci（PySide6 必须可导入否则 Qt stub 全报错） |
| webui | ubuntu, Node 20 | npm ci → audit（moderate 门限）→ check:colors 棘轮 → vitest → coverage 阈值 → typecheck → build |
| package-smoke | windows | 构建 WebUI → **在 %RUNNER_TEMP 外部 cwd** 循环 onefile/onedir 跑 PyInstaller（验证 spec 对 cwd 不敏感）→ check_package_contents ×2 → exe `--package-smoke` 冒烟（Qt 导入 + SVG 图标）→ 冻结运行 15 秒不早退 |
| windows-regression | windows, Py3.13 | Windows 专属子集：**仅 4 个文件**（test_path_resolver/test_path_guard/test_lan_api/test_undo_service）+ 关键词过滤 |
| media-decoders | ubuntu | 可选解码器 lane（psd-tools 必装，rawpy 装失败容忍）；3 个解码器测试文件 |
| python-browser-e2e | windows | 构建 WebUI → playwright≥1.50 + chromium → `pytest -m e2e` 跑 2 个真实 LAN 浏览器验收文件 |
| test | ubuntu, 矩阵 **3.12/3.13/3.14**（fail-fast: false） | npm build → requirements+dev+ci overlay → apt 装 Qt 系统库 → compileall → pytest 默认套件 |

9 个 job 全部**并行、无 needs**（矩阵展开共 11 个执行单元）；无 pip 缓存（只有 npm cache）。

### 3.2 release.yml（tag v* 触发，`permissions: {}`）

```
tag v* → pre-release-tests（ubuntu：ruff + compileall + pytest 全套）
        └─ needs → build-windows（WebUI build → PyInstaller onefile+onedir
                    → check_package_contents ×2 → --package-smoke ×2
                    → choco innosetup → scripts/build_installer.py
                      （版本取自 constants.py，盖章 _version.iss + .iss 静态自检）
                    → win64.zip + win64-portable.zip + 各配 .sha256 sidecar）
                    └─ needs → publish-release（校验"恰好 1 个安装器"、
                        release 必须已存在、资产不重名（重跑不覆盖）、
                        SHA-256 sidecar 逐一复核 → gh release upload）
```

安全细节：actions 全部 SHA 钉版；release 必须预先存在（拒绝创建/改目标）；重跑故意 no-overwrite。

### 3.3 nightly-perf.yml

cron `17 3 * * *` + workflow_dispatch → grid-telemetry job（continue-on-error）→ **只出趋势工件，不做 PR pass/fail**。

---

## 4. 构建体系

### 4.1 管线图（文字版）

```
源码 (AssetsManager/, Plugins/, Assets/icons+Themes, webui/)
  │
  ├─ webui: npm ci && npm run build          ──→ webui/dist（SPA，LAN pages.py 服务）
  │
  ├─ build.py（--clean [--build] [--report] [--mode onefile|onedir|both] [--skip-webui]）
  │     ├─ clean()：删 dist/ + build/
  │     ├─ webui_build()：npm 解析（which('npm') 兼容 Windows npm.cmd）
  │     ├─ build()：每 mode 一次 AM_BUNDLE_MODE=xxx PyInstaller AssetManager.spec
  │     └─ report()：打印 exe 体积
  │
  ├─ AssetManager.spec（双形态单 spec，AM_BUNDLE_MODE 切换）
  │     ├─ 版本：正则读 constants.py 的 APP_VERSION（文本镜像，免导入）→ VSVersionInfo
  │     ├─ datas：Assets/icons、i18n 三语 json、Assets/Themes、webui/dist、Plugins
  │     ├─ hiddenimports：PIL._webp/send2trash + PySide6 五模块 + aiohttp 全家
  │     │   + AssetsManager.lan.** 全枚举（handler 体内懒导入，静态图抓不到）
  │     ├─ excludes：scipy/numpy/pytest/tkinter/matplotlib/pandas + 11 个未用 Qt 模块
  │     │   + 17 个 PIL Stub 插件；排除后再按 C++ DLL 名二次过滤
  │     │   （Qt6Quick/Qml/Pdf/VirtualKeyboard DLL + PortableGit 混入的 OpenSSL）
  │     └─ .qm Qt 翻译裁剪：只保 en/zh_CN/zh_TW/ja
  │
  ├─ run.py（spec 入口；--package-smoke 分支：验证 dock_factory 导入
  │          + QSvgRenderer 最小 SVG + icon('settings') 非空）
  │
  ├─ scripts/check_package_contents.py（bundle 完整性：onefile 解析 CArchive TOC / onedir 走 _internal 树）
  │
  └─ scripts/build_installer.py → installer/assetmanager.iss + _version.iss
        per-user 安装（PrivilegesRequired=lowest, %LOCALAPPDATA%\Programs,
        固定 AppId, no [UninstallDelete] 保用户数据）
        → dist/installer/AssetManager-<ver>-setup.exe + .sha256
```

**文档漂移实测**：README 写的 `build.py --clean --build --optimize --report` 中 **`--optimize` 并不存在**（argparse 仅 --clean/--build/--report/--mode/--skip-webui；该命令实际会因未识别参数报错）；`--package-smoke` 是 run.py/exe 的参数而非 build.py 的；"Cython 编译加速"README 小节正文为空。

### 4.2 .cython-nuitka/（实验性加速目录，未接入任何流水线）

- build_cython.py + setup_cython.py：Cython 编译 **8 个 core 模块**（cache、lru_cache、database、json_store、tag_store、tag_library、color_utils、path_resolver）——README 称 4 个热点，实际列表 8 个。
- Nuitka 三档编译脚本 + PySide6 插件目录 copy + 编译后自测（指南实测：Cache set 2.2x / get 2.5x / hex_to_rgb 3.4x）。
- ACCELERATION_GUIDE.md（16.5KB 中文方案）+ QUICK_REF。release 走 PyInstaller，此目录纯本地实验。

---

## 5. 门禁脚本（scripts/，11×check_* + 2×gen_* + 工具）

| 脚本 | 门禁 | 职责 |
|---|---|---|
| check_boundaries.py | 前后端分离 | 静态扫描：application/ 无 /api/ URL；panels/widgets 不 new Repository；dialogs 无 localhost 业务调用 |
| check_layers.py | 分层 DAG | AST 导入图，12 层 ALLOWED_EDGES 白名单 + **空例外表**（G1-G4 已清零） |
| check_route_capabilities.py | L1 | LAN 写路由必须声明 capabilities（解析 api.py 不导入；词表取自 route_policy.KNOWN_CAPABILITIES 防漂移） |
| check_frontend_data_fetch.py | S2 | webui/src/pages 禁止直接 import api/、createApiClient、裸 fetch |
| check_inline_styles.py | G1 棘轮 | setStyleSheet 调用点只能减不能增（AST 计数 vs style_ledger.json，38 文件配额；--update 降额，--force 才可增） |
| check_style_dialects.py | G3 棘轮 | setStyleSheet 内裸 `t[...]` token 访问**零容忍**（ledger 空 entries 作绊线） |
| check_style_sources.py | QSS 源 | QSS 硬编码 hex/字号必须来自主题 token |
| check_web_token_usage.py | Web token | 每个 `var(--name)` 引用必须有定义（覆盖 css/ts/tsx 与 Tailwind 任意值类） |
| gen_ts_types.py | C1 | AST 解析 lan/dto.py → 生成 webui contracts.ts；--check drift 即 exit 2 |
| gen_web_tokens.py | S4 | 桌面主题 JSON 单一源 → themes.generated.css；--check |
| check_doc_stats.py | D4/D6 | README 结构统计实测 vs `<!-- stats: -->` 标记；--fix 重写 |
| check_documents.py | 文档三态 | LIVING 带 updated 头且 ≤30 天；archive 须在 INDEX.md 注册；FROZEN 不可变 |
| check_audit_reports.py | 审计证据 | 校验 dated 审计 manifest 的报告名/源锚点/输入字节哈希/索引链接，**不把手写计数当执行证据** |

工具脚本：build_installer.py、check_package_contents.py、clean_runtime.py（白名单 + git check-ignore 双保险，默认干跑）、icon_render_probe.py（offscreen 渲染全部图标验证）、migrate_legacy_icons.py（emoji 一次性迁移，dry-run 幂等）、cleanup_undo_zombies.ps1（管理员结束持有 undo 句柄的僵尸进程）。

**门禁元质量**：门禁脚本自身有单元测试（test_layer_dag.py 等 8+ 文件）——"测门禁的门禁"。

---

## 6. 代码规范配置

### ruff.toml
- **只选正确性家族**，刻意排除风格家族（理由写在注释：数万条发现不抓 bug，pyright 已覆盖类型）：E4/E7/E9/F、B、LOG、G、DTZ、PIE、PYI、A、T20、FLY/SLOT/YTT/EXE/INT/NPY/ISC/ICN/TID/FA/PGH。
- ignore：B009/B010（getattr 常量属性——重写会撞 pyright 硬门禁，"强门禁优先"）、B008（Qt 覆写默认参数）。
- per-file-ignores：tests → B018/B017/T201；scripts/build.py/run.py → T201（print 是输出通道）。

### pyrightconfig.json
- include 全 AssetsManager 子树；**typeCheckingMode: "basic"（非 strict）**；关闭三个 reportMissing*（CI 靠真实安装 PySide6 弥补 imports）；CI 钉 pyright==1.1.410。

### .pre-commit-config.yaml（双阶段设计）
- **pre-commit（秒级，防 --no-verify 侵蚀）**：ruff-check + 冲突标记扫描。
- **pre-push（镜像 CI lint job 的慢门禁）**：check_boundaries / check_layers / check_style_sources / check_inline_styles / check_style_dialects / check_route_capabilities / check_frontend_data_fetch / check_doc_stats / check_documents / gen_ts_types --check / gen_web_tokens --check / check_web_token_usage / webui-typecheck（node_modules 缺失自动跳过）。
- 头注释动机：此文件出现前"CI 跑 10 个门禁而本地 README 只列 1 个，9 个门禁在开发者机器上静默不跑"。

### .gitattributes
- 文本类 `text`；**运行时敏感钉死**：.ps1/.bat/.cmd `eol=crlf`（PowerShell 5.1 需要）、.sh `eol=lf`（CI ubuntu 的 CRLF shebang 会立即死）；**二进制保护**：.db/.db-wal/.sqlite（防行尾改写导致库打不开）。

---

## 7. requirements 分层

| 文件 | 内容 | 用途 |
|---|---|---|
| requirements.txt | PySide6>=6.6,<7 / Pillow>=10,<13 / send2trash / requests / segno | 核心；上限是"语义版本守卫" |
| requirements-lan.txt | + aiohttp>=3.9,<4 | LAN 可选层 |
| requirements-dev.txt | + pytest>=8 / pytest-xdist>=3.6 / anyio>=4 / pyinstaller>=6 / ruff>=0.8 / pyright>=1.1 | 开发/测试 |
| requirements-ci.txt | PySide6==6.11.0 / aiohttp==3.14.0 / Pillow==12.2.0 / numpy==2.4.4 / pytest==9.0.2 | **CI 确定性 overlay**（装在最后覆盖解析；升级须带全套本地 run） |
| requirements-media.txt | rawpy>=0.24,<1 / psd-tools>=1.9,<2 | 可选专业格式解码器；缺失优雅降级 |
| requirements-perf.txt | PySide6==6.11.0 | nightly 基准钉版 |

口径不一致：typecheck job 未装 dev 却钉 pyright 版本；release 的 pre-release-tests 无 ci overlay（与 test job 确定性口径不一致）。

---

## 8. 强项

1. **"棘轮 + 零容忍"门禁哲学**：setStyleSheet 配额只减不增、裸 token 访问零例外、layer DAG 例外表清空——技术债冻结在账本里强制单调收敛。
2. **门禁元质量**：门禁脚本自身有测试；README 统计由 check_doc_stats 实测防漂移；文档三态有年龄与注册门禁。
3. **测试基础设施深度**：PBKDF2 降本换全速、会话级用户配置快照还原、带预算的 RuntimeData 增量清扫、xdist 串行组、沙箱兼容 tmp_path。
4. **发布纪律**：release gate 在测试之后；SHA-256 sidecar 全链路复核；恰好一个安装器；不覆盖已有资产；actions SHA 钉版。
5. **确定性分层**：ci overlay 钉版 + perf 钉版，宽约束（用户）与钉死（CI/基准）分离。
6. **性能观测三档定位清晰**（阈值护栏 / 趋势证据 / nightly 工件）；DirectoryCache 测试用 scandir 计数替代时钟。
7. **双形态包冒烟**：onefile/onedir 都跑内容校验 + 冒烟 + 15 秒存活；spec 从外部 cwd 构建验证路径无关性。

---

## 9. 缺口与弱点

**README 自己承认的（2026-08-29 复核，"仍然成立"）**：
1. **CI 触发仅 master/main**：特性分支不开 PR 就不触发 CI，分支覆盖未验证。
2. **perf 门禁默认排除**：阈值护栏从不默认执行，回归只能靠 nightly 趋势肉眼发现。
3. **Windows lane 仅 4 文件子集**：主平台 Windows 上的全套 324 文件默认套件从不在 Windows 上跑（test 全量在 ubuntu offscreen）。

**本次勘察新发现**：
4. **pytest 无超时机制**：挂死测试会拖垮 job。
5. **README 与实现漂移**：`build.py --optimize` 参数不存在；分域计数过期；Cython 小节正文为空。
6. **release gate 与 test job 口径不一致**：pre-release-tests 无 ci overlay、无 Python 矩阵（仅 3.13）——标签打在未跑过 3.12/3.14 的提交上时，矩阵承诺对发布件不成立。
7. **pip 无缓存**：6 个 Python job 每次全量装 PySide6（大包）。
8. **pyright 仅 basic 模式**：类型门禁强度有限。
9. **e2e 覆盖极薄**：仅 2 个文件对比 72 条 LAN 路由面；python-browser-e2e 固定跑在 windows（成本高）。
10. **无 Python 侧覆盖率门禁**：仅 WebUI 有 istanbul 阈值。
11. **.cython-nuitka 未接入流水线**：本地编译过再打包可能引入不一致。
12. tests/perf_real_world.py 硬编码本机路径，不可移植。
13. 三个 Windows job 重复装依赖/构建 WebUI，无 needs 复用。

---

**结论**：该项目的质量体系在"静态架构门禁 + 确定性依赖 + 发布纪律"上达到罕见的深度（棘轮账本、门禁自测、文档统计实测化都是成熟形态），主要短板集中在**执行面覆盖**：性能门禁默认旁路、Windows 全量缺位、e2e 极薄、无超时与覆盖率护栏、release gate 与日常 CI 矩阵口径分裂。

---

**关联阅读**：LAN 安全机制如何被测试锁定 → [04-lan.md](04-lan.md)；webui 三套 mock 词表问题 → [05-webui.md](05-webui.md)；装配链被测试替身消费的方式 → [03-application.md](03-application.md)。
