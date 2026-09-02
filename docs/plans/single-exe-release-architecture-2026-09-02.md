---
title: "单 exe 发布架构方案"
type: plan
status: LIVING
date: 2026-09-02
area: packaging / release
owner: agent（M1/M2/M3 全部已实施）
supersedes: none
---

# 单 exe 发布架构方案（2026-09-02）

> 长期架构任务。给出从 onedir+安装器 迁移到"单 exe 分发"的完整路径、代码级改动清单与风险边界。**M1（数据根便携化）、M2（插件/主题双层）、M3（spec 双形态 + build.py 双构建 + 校验器/installer/CI/release 双产物适配）已全部实施合入**；仅剩 §7 的产品决策（Q2 存量用户规模、Q3 体积阈值）待 owner 拍板。

> **⚠️ 2026-09-02 设计反转（重要）**：早期方案（§3 / §4.1 原始稿）曾设计「frozen 数据根落 `%LOCALAPPDATA%\AssetManager` + 首启 `migrate_data_root()`」。实机验证后 **反转**：数据根改为 **exe 旁便携式**，并 **删除全部迁移逻辑**；打包形态由「仅 onefile」扩展为 **onefile + onedir 双形态都产出**。正文各处已标注最终态；历史 `LOCALAPPDATA` 表述仅作演进记录保留。

## 1. 背景与目标

### 1.1 现状（已核实）

- 打包形态（最终态）：PyInstaller **双形态** —— onefile（`dist/AssetManager.exe`）与 onedir（`dist/AssetManager/`，exe 旁 `_internal/`）。单一 `AssetManager.spec` 经 `AM_BUNDLE_MODE` 环境变量选形态（`AssetManager.spec:25-29`、`344-371`），`build.py --mode onefile|onedir|both` 连跑（`build.py:55-70`）；再经 Inno Setup per-user 安装器把 **onefile exe** 包一层分发（`installer/assetmanager.iss`、`scripts/build_installer.py`，CI 链见 `.github/workflows/ci.yml:124-190`、`.github/workflows/release.yml:55-132`）。
- 数据模型：应用把**所有可写数据**放在"exe 旁 `RuntimeData/`"（`path_resolver.py:117-123`），前提是 per-user 安装目录可写（`installer/assetmanager.iss` 头注：`PrivilegesRequired=lowest` + "writes NEXT TO the executable"）。
- 库根（用户素材目录）由用户选定、不含于 RuntimeData；RuntimeData 内存库 DB、缩略图、收藏、锁、identity 标记、settings、crash 日志、cloudflared 下载缓存。

### 1.2 目标形态

- 分发物（最终态）= 双形态各一份：**单个 `AssetManager.exe`**（onefile，双击即用，可放任意目录）＋ **`AssetManager/` 便携目录**（onedir，exe 旁 `_internal/`）。
- 运行期数据**跟随 exe**（便携式）：frozen 下 `user_data_root()` = `Path(sys.executable).parent`，RuntimeData/Plugins/Themes 均落 exe 旁（onefile 为 exe 所在目录、onedir 为 `dist/AssetManager/`）。移动 exe 即移动数据；**无首启迁移**。
- 升级 = 覆盖替换 exe（onefile）或整个便携目录（onedir）；数据与程序同目录，无 `%LOCALAPPDATA%` 分离带来的残留困惑。

### 1.3 关键认知（一句话）

> 单 exe 只改变"运行期布局"，不改变"仓库布局"。而运行期可写物几乎全部挂在一个函数（`runtime_root()`）下——**数据根语义（便携式 exe 旁）是唯一真正断点，先做它；spec 双形态化反而是低风险尾段**。

## 2. 现状路径体系全景（证据锚点）

### 2.1 锚点层：`AssetsManager/core/path_resolver.py`（唯一路径中枢）

| 函数 | 行 | 行为（frozen / dev） | 单 exe 评估 |
|---|---|---|---|
| `runtime_root()` | 117-123 | frozen→`exe旁/RuntimeData`；dev→`仓库根/RuntimeData` | ❌ **核心断点**：数据跟 exe 走 |
| `shared_dir()` | 126-130 | `runtime_root()/Shared`（模块级 `SHARED_DIR=shared_dir()` @133） | ✅ 挂 runtime_root → 自动跟随迁移 |
| `plugins_root()` | 219-223 | frozen→`exe旁/Plugins`；dev→`仓库根/Plugins` | ❌ 可写扩展位跟 exe 走 |
| `themes_dir()` | 240-249 | frozen→`_MEIPASS/Assets/Themes`（存在时）否则 `exe旁/Assets/Themes`；dev→仓库 `Assets/Themes` | ⚠️ 见裂缝 F1/F2 |

### 2.2 所有可写持久化物 → 全部挂在 `runtime_root()/SHARED_DIR`

| 物 | 位置 | 证据 |
|---|---|---|
| settings.json | `SHARED_DIR/settings.json` | `settings.py:127` |
| 旧版 settings 迁移（~/.assetmanager） | 已有先例 | `settings.py:244` |
| crash.log / crash.pending | `SHARED_DIR/` | `crash_handler.py:27-32` |
| cloudflared 下载缓存 | `shared_dir()/cloudflared-*` | `lan/tunnel.py:154-162` |
| 库 DB / 缩略图 / 收藏 / recent / 锁 / identity | `runtime_root()/<hash slot>` | `path_resolver.py:136-216`、`plugin manager` |
| 用户级插件 | `SHARED_DIR/plugins/` | `core/plugins/manager.py:201-203` |

> **推论**：`runtime_root()` 的 frozen 分支一改，上表全部自动迁往新数据根。这是"单点改动、全项目跟随"的结构红利。

### 2.3 只读资源点 → 已天然兼容 onefile（`_MEIPASS`）

spec `datas`（`AssetManager.spec:75-87`）目标刻意镜像仓库相对层级，使 `__file__` 相对推导在 onedir/onefile 下一致成立：

| 资源 | 定位方式 | 兼容 |
|---|---|---|
| 窗口图标 icon.ico | `app.py:213` `Path(__file__).parent.parent/"assets/icons"` → `_MEIPASS/assets/icons` | ✅ |
| i18n JSON | `i18n/__init__.py:17` `Path(__file__).parent` | ✅ |
| Web SPA（webui/dist） | `lan/routes/pages.py:7` `Path(__file__).parent*4/"webui/dist"` → `_MEIPASS/webui/dist` | ✅ |
| cloudflared 捆绑二进制 | `lan/tunnel.py:135-144` 已自处理 `_MEIPASS` + `_internal` 双布局 | ✅ |

### 2.4 现存裂缝（方案必须先修，与单 exe 无关）

- **F1（已实证：不成立）**：原疑"PyInstaller 6.x `_internal` 布局下内置主题丢失"。2026-09-02 真实 onedir 探针（PyInstaller 6.19.0 + 相同 datas/COLLECT 结构）证实：onedir 下 `sys._MEIPASS` **恒指向 `dist/<name>/_internal`**，`themes_dir()` 主分支 `_MEIPASS/Assets/Themes` 命中 24 个内置主题；fallback `exe旁/Assets/Themes` 是死代码（该路径不存在但永不触发）。故 F1 不构成"内置主题丢失"，内置源仅 `_MEIPASS/Assets/Themes` 一处即可（onefile/onedir 通吃）。
- **F2（onefile 必现，M2 已修）**：onefile 下 `_MEIPASS` 是临时解压目录（只读、退出即删），原 `themes_dir()` 直接返回它 → 保存/导入自定义主题（`settings_dialog.py:490`）写进临时目录丢失。主题体系原为**单一目录扫描**，无"内置只读 + 用户可写"双层。
- **F3（M2 已修）**：`plugins_root()` frozen→exe 旁；单 exe 任意放置不可靠。且 spec datas `Plugins→Plugins` 在 `_internal` 布局下落 `_MEIPASS/Plugins`，原 `addons_dir()=exe旁/Plugins/Addons` 找不到内置种子插件。
- **F4（升级残留，已被便携式决策覆盖）**：原以为"只要数据在 exe 旁，升级覆盖/目录移动就伴随数据残留或双份数据困惑"。最终决策反向采纳便携式：数据随 exe 同目录，升级 = 整体覆盖（onefile 覆盖 exe、onedir 覆盖目录），"双份数据"由用户显式移动目录解决，而非程序静默迁移。此裂缝在便携式语义下**不构成缺陷**。

## 3. 目标运行期布局（最终态：便携式）

```
<exe 所在目录>\                        ← 数据根 = Path(sys.executable).parent（frozen 态唯一可写区）
├─ AssetManager.exe                     ← onefile 时即 exe 本身；onedir 时位于 dist/AssetManager/ 内
├─ RuntimeData\                         ← 与仓库开发态同构（内部结构零改动）
│  ├─ Shared\  (settings.json, crash.log, crash.pending, cloudflared 缓存, plugins/)
│  └─ <lib>_<hash>…\  (assetmanager.db, .thumbnails, favorites.json, recent.json, 锁/identity)
├─ Plugins\Addons\                      ← 用户扩展可写位（frozen 下 = exe旁/Plugins）
└─ Themes\                              ← 用户自定义主题（内置主题仍读 _MEIPASS，见 §4.3）
```

**数据根选址论证（最终：exe 旁便携式，推翻早前 LOCALAPPDATA 方案）**：

| 候选 | 评估 |
|---|---|
| `exe 旁`（最终采纳） | ✅ 全便携、移动即随行、升级=覆盖替换、无隐藏数据目录；代价：需安装目录可写（安装器装到 `{localappdata}\Programs` 已满足，见 `path_resolver.py:127-130` 说明） |
| `%APPDATA%\AssetManager` | 默认 roaming，素材库数据大且无需漫游同步 |
| `%LOCALAPPDATA%\AssetManager`（早前方案，已废弃） | 曾选定；后被便携式推翻——首启迁移引入失败面（跨卷/并发/回滚分叉），而便携式"数据随 exe"更贴合素材库"库随目录走"的心智 |

**开发态不变**：非 frozen 时 `runtime_root()` 保持 `仓库根/RuntimeData` 推导（`path_resolver.py:134`），使仓库开发、CI、全部单测（`tests/core/test_path_resolver.py` 等以 monkeypatch `runtime_root` 注入 tmp 路径）**零改动、零影响**。

## 4. 改动设计（按里程碑分层）

### 4.1 M1 · 数据根独立化（P0，与单 exe 解耦，先行合入）

> **状态：已实施并反转（2026-09-02）。** 早期实现按本节原始稿「frozen 数据根 → `%LOCALAPPDATA%\AssetManager` + 首启迁移 `migrate_data_root()`」。实机验证后 **反转**（见 §1 顶部设计反转说明）：**frozen 数据根改为 exe 旁便携式，且删除全部迁移逻辑**。最终实现如下：

- **`user_data_root()`（`path_resolver.py:117-134`）**：frozen → `Path(sys.executable).resolve().parent`（onefile 为 exe 所在目录、onedir 为 `dist/AssetManager/`）；dev → `Path(__file__).resolve().parent.parent.parent`（仓库根）。`runtime_root()` frozen 分支随之 = `user_data_root()/"RuntimeData"`（`path_resolver.py:137-139`）。
- **删除迁移逻辑**：`migrate_data_root()`、`_data_root_migration_looks_complete()`、模块级 `migrate_data_root()` 调用、`shutil`/`logging` 导入全部删除。便携式语义下 exe 目录即数据根，**无「首启迁移」概念**（不存在旧布局到新布局的跨目录搬运）。
- **代价声明**：便携式要求安装目录可写（`path_resolver.py:127-130` docstring 已注明）。安装器把 onefile exe 装到 `{localappdata}\Programs\AssetManager`（用户可写），故成立；若用户把便携版放到只读位置（如 Program Files），程序按设计**不静默迁移到隐藏目录**，而是启动失败——此为有意取舍。

**自动跟随（零改动，逻辑不变）**：settings（`settings.py:127`）、crash（`crash_handler.py:27-32`）、cloudflared 缓存（`lan/tunnel.py:154-162`）、库 slot（`path_resolver.py`）、用户插件 `SHARED_DIR/plugins`（`manager.py:201-203`）——全部挂 `runtime_root()/SHARED_DIR`，便携化只改 frozen 分支这一处即全项目跟随。

**验证**：`tests/core/test_path_resolver.py` 便携式断言（frozen→exe旁，onefile/onedir 各一）36 例通过；`--package-smoke`（`run.py`）exit 0。

### 4.2 M2 · 插件双层（P1）

> **状态：已实施（`2591463`，2026-09-02）。** `plugins_root()` frozen→`user_data_root()/"Plugins"`；新增 `builtin_plugins_addons_dir()`（frozen→`_MEIPASS/Plugins/Addons`，dev→None）；`default_search_paths()` 追加内置只读种子源。**决策**：采用「只读搜索源」而非「首启拷贝种子」——插件 enable/disable 状态持久化在 `AppSettings.plugin_disabled_ids`（不回写 manifest，`manager.py:264-278/343-352`），种子插件写状态到 `SHARED_DIR` 而非自身目录，故只读源可行且免去运行时拷贝代码的脆弱性。同名插件 id 跨源冲突仍按既有语义判 INVALID（fail-closed）。

- `plugins_root()` frozen → `user_data_root()/"Plugins"`（可写扩展位）；`addons_dir()`/`plugins_docs_dir()` 自动跟随。
- 内置种子插件（spec datas `Plugins→Plugins`）在 `_internal`/onefile 布局下落 `_MEIPASS/Plugins/Addons`，作为 `default_search_paths()` 的第三源（只读）。

### 4.3 M2 · 主题双层（P1，修 F2）

> **状态：已实施（`2591463`，2026-09-02）。** 实证后简化内置源探测：onedir 6.19.0 下 `_MEIPASS` 恒指向 `_internal`，故内置源仅 `_MEIPASS/Assets/Themes` 一处即可（onefile 与 onedir 通吃），无需三层候选。

- `themes_dir()` 语义调整：frozen → `user_data_root()/"Themes"`（**可写用户层**，mkdir）。
- 新增 `builtin_themes_dir()`：frozen → `_MEIPASS/Assets/Themes`（缺失时 fallback `exe旁/Assets/Themes` 旧布局），dev → None（与用户层同目录，无需分离）。
- `core/theme_loader.py`：`scan_directory` 扩展为「内置先、用户层同名覆盖」多目录扫描；`ThemeLoader` 默认构造解析双层，显式 `themes_dir`（单目录调用/测试）保持单目录语义。
- 写路径（`settings_dialog.py:490`、`theme_loader` 的 create/save/delete）全部指向用户层——onefile 下不再写临时目录。
- dev 态不变（`themes_dir` 维持仓库 `Assets/Themes` 单一语义）。

### 4.4 M3 · spec 单文件化（P2）

> **状态：已实施（双形态分支，2026-09-02）。** 相对下文的实现差异：① 实证发现当前 spec 的 `EXE` 本就无 `exclude_binaries=True`（已是 onefile 形态），只是额外挂了 `COLLECT` 把同样 binaries/datas 再拷一份到 `_internal`（重复打包）——故修复 = 删旧 `COLLECT` + 去掉死参数 `a.zipfiles`/`a.zipped_data`（PyInstaller 6.x 恒为空）；② spec `excludes` 移除 `distutils`（Python 3.12+ 由 setuptools vendored，冲突致 `ValueError`）；③ 清理 24 个过时 hiddenimports（shop/order/quota/seller 已从代码库删除）。**最终态扩展为双形态**：单一 spec 用 `AM_BUNDLE_MODE` 选择形态，`Analysis`/datas/hiddenimports 完全共享，不重复。

- `AssetManager.spec:25-29` 读 `AM_BUNDLE_MODE`（`onefile` 默认 / `onedir`），非法值 `raise SystemExit`。
- `AssetManager.spec:344-371` 分支：`onedir` → `EXE(pyz, a.scripts, [], exclude_binaries=True, **_exe_kwargs)` + `COLLECT(exe, a.binaries, a.datas, name='AssetManager')`（exe 旁 `_internal/`）；`onefile` → `EXE(pyz, a.scripts, a.binaries, a.datas, [], **_exe_kwargs)`。
- `datas` 目标层级**不改**（§2.3 已证只读资源在 onefile/onedir 下全兼容；注意 onedir 下 Windows 大小写不敏感文件系统会把 `assets/icons` 与 `Assets/Themes` 合并，校验器按 `case_insensitive=True` 处理）。
- 预期：onefile ≈ 71MB；onedir 为同体积目录树（exe 旁 `_internal/`）。首启解压 3–15s（仅 onefile）。

### 4.5 M3 · 构建流水线（P2）

> **状态：已全部实施（`6c3c385` spec 单文件化 + build.py；`8a486d3` check_package_contents / installer B / CI 同步）。**

| 位置 | 改动（最终态：双形态） | 状态 |
|---|---|---|
| `build.py` | `--mode onefile\|onedir\|both`（默认 both）连跑 PyInstaller 各一次；`_run_pyinstaller()` 注入 `AM_BUNDLE_MODE` 环境变量；`report()` 双产物报告；`ONEFILE_EXE`/`ONEDIR_EXE` 常量 | ✅ 已实施 |
| `AssetManager.spec` | `AM_BUNDLE_MODE` 分支（§4.4）；`Analysis`/datas/hiddenimports 共享 | ✅ 已实施 |
| `scripts/check_package_contents.py` | 三层校验：`check_exe`（onefile：PE 魔数 + 体积下限 + CArchive TOC）、`check_onedir`（`_internal` 树 walk，`case_insensitive=True`）、`check_spec`（datas 源存在 + `AssetsManager.*` hiddenimports 解析）；`check_bundle` 按 path 类型分派（file→exe，dir→onedir） | ✅ 已实施 |
| `scripts/build_installer.py` + `installer/assetmanager.iss` | **B 安装器包一层（onefile exe）**：iss `[Files] Source: "..\dist\AssetManager.exe"` → `{localappdata}\Programs\AssetManager`；注释同步便携式语义（RuntimeData 在 exe 旁 = 在 `{app}` 内） | ✅ 已实施（Q5 已定 B） |
| `.github/workflows/ci.yml` `package-smoke` | 显式双形态构建（`AM_BUNDLE_MODE` 循环）+ 分别 `check_package_contents.py` 校验 + 分别 `--package-smoke`/运行时 smoke | ✅ 已实施 |
| `.github/workflows/release.yml` | 产出三类 artifact：onefile zip（`AssetManager-<tag>-win64.zip`）+ onedir portable zip（`AssetManager-<tag>-win64-portable.zip`，顶层 `AssetManager/`）+ installer；`publish-release` 校验/上传 6 文件 | ✅ 已实施 |

### 4.6 M3 · 版本 / 升级 / 回滚（P2）

- `APP_VERSION` 单一源（constants.py）不变；spec 镜像机制（`AssetManager.spec:31-42`）不变。
- 便携式数据根下，升级 = 覆盖替换 exe（onefile）或整个便携目录（onedir）；**无跨目录迁移**，故回滚/降级无数据分叉风险（数据始终与程序同目录）。
- 安装器路径：升级即重装到同 `{localappdata}\Programs\AssetManager`，Inno `ignoreversion` 覆盖 exe；`[UninstallDelete]` 保持空（便携式下 RuntimeData 在 `{app}` 内，卸载器移除 exe 但保留其从未创建的 RuntimeData，不丢用户数据）。

## 5. 风险与验收

### 5.1 风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 并行会话未提交 WIP 全程在改 `AssetsManager/` 源码 | 本方案只落 `docs/plans/`，不落码；实施窗口须在并行会话提交后 |
| R2 | ~~迁移跨卷失败 / 半途中断~~（已消除：便携式无迁移） | 删除迁移逻辑 |
| R3 | ~~双开迁移竞争~~（已消除） | 删除迁移逻辑 |
| R4 | 内置主题在 onedir `_internal` 布局下是否已丢失（F1） | M2 实证不成立（§2.4） |
| R5 | 单文件被 AV 误报、启动慢 | 代码签名 + 发布说明；`runtime_tmpdir` 备选 |
| R6 | ~~旧版回滚数据分叉~~（已消除：数据随 exe 同目录） | §4.6 便携式升级策略 |
| R7 | 测试面 | 全部单测走 monkeypatch `runtime_root`（`tests/conftest.py:232+`、`test_path_resolver.py` 全程 patch）→ 实现细节改动不破坏；新增便携式 onedir/onefile 断言 |
| R8 | 便携式数据根要求 exe 目录可写 | 安装器装到 `{localappdata}\Programs`；只读目录按设计 fail（不静默迁移），docstring 已声明 |

### 5.2 验收（每里程碑 gate）

1. 门禁：`scripts/check_documents.py`、`scripts/check_boundaries.py` exit 0。
2. 单测：pytest 全绿（重点 `tests/core/test_path_resolver.py`、`test_themes.py`、`test_package_contents.py`、`test_packaging_entrypoints.py`）。
3. frozen 冒烟：onefile `AssetManager.exe --package-smoke` 与 onedir `dist/AssetManager/AssetManager.exe --package-smoke` 均 exit 0（`run.py`）。
4. 手工验证：干净机分别跑 onefile 与 onedir 产物 → 建库/加收藏/换主题/存 settings → 覆盖替换升级 → 数据与偏好完整（数据随 exe 同目录）、主题可保存、LAN 页面可达（SPA 自 `_MEIPASS/webui/dist` serve）。

## 6. 实施顺序摘要

| 里程碑 | 内容 | 性质 |
|---|---|---|
| M1 | 数据根便携化（exe 旁）——§4.1（原「LOCALAPPDATA+迁移」已反转） | ✅ 已实施 |
| M2 | 插件双层 + 主题双层（§4.2/4.3） | ✅ 已实施；修 F2/F3，F1 实证不成立 |
| M3 | spec 双形态 + build.py 双构建 + 校验器/installer/CI/release 双产物（§4.4/4.5） | ✅ 已实施 |

每里程碑独立提交 + 双门禁 + 单测 + 手工冒烟。

## 7. 待实施时确认（open questions）

> 2026-09-02 更新：Q1/Q4 已静态核实并给出结论（见下）；Q5 已定 B（安装器包一层）并实施；Q2/Q3 为产品决策，待 owner 拍板。

1. **PyInstaller 布局（已实证）**：本机 Python 3.14 已装 **PyInstaller 6.19.0**；onedir 默认 `contents_directory=_internal` → spec `datas` 落 `dist/AssetManager/_internal/`。2026-09-02 真实 onedir 探针证实 `sys._MEIPASS` 恒指向 `dist/<name>/_internal`，故 `themes_dir()` 主分支 `_MEIPASS/Assets/Themes` 直接命中内置主题——**原 F1「内置主题丢失」不成立**；其它只读资源（icon `app.py:213`、SPA `pages.py:7`、i18n）用 `__file__` 相对推导亦不受影响。**结论**：内置主题源仅 `_MEIPASS/Assets/Themes` 一处（onefile/onedir 通吃），M2 已按此实现（`builtin_themes_dir()`）。
2. onedir 存量用户规模（决定迁移兼容优先级与回滚策略强度）——**待 owner**。
3. 单 exe 目标体积 / 首启时间可接受阈值（决定是否压内置主题/裁剪 Qt）——**待 owner**。
4. **plugins loader 语义（已核实）**：`core/plugins/manager.py:200-203` `default_search_paths() = [SHARED_DIR/"plugins", addons_dir()]`；`discover_plugins` 逐目录 `iterdir` 并以 `dict[plugin_id]` 聚合（同名后者覆盖）→ **多源合并复杂度低**：M2 给 frozen 加内置种子源只需在 `default_search_paths` 前插 `_MEIPASS/Plugins`（若存在）。注意点：内置源只读、插件实例化可能写盘（配置/状态）→ 建议内置源仅作"首次运行拷贝到用户层"的种子，而非运行源；此项 M2 细化时敲定。
5. 分发方向 A（纯绿色单文件）还是 B（安装器包一层）——影响 installer/ 去留与卸载清理责任——**已定 B**（安装器包一层单 exe，`installer/assetmanager.iss` `[Files] Source: "..\dist\AssetManager.exe"`，已实施于 `8a486d3`）。

## 8. 参考文件

- `AssetsManager/core/path_resolver.py`（117-134 user_data_root、137-139 runtime_root、235-243 plugins_root、282-315 themes_dir）
- `AssetsManager/core/settings.py`（127/244）、`crash_handler.py`（27-32）
- `AssetsManager/core/plugins/manager.py`（201-203）
- `AssetsManager/core/theme_loader.py`（33-67）、`core/themes.py`（156-168）
- `AssetsManager/dialogs/settings_dialog.py`（490）
- `AssetsManager/lan/routes/pages.py`（7）、`lan/tunnel.py`（131-168）、`lan/api.py`（373-374）
- `AssetsManager/app.py`（213）、`run.py`、`main.py`
- `AssetManager.spec`（25-29 AM_BUNDLE_MODE、31-42 version、88-321 Analysis、344-371 双形态分支）、`build.py`（55-70 _run_pyinstaller/build）
- `installer/assetmanager.iss`、`scripts/build_installer.py`、`scripts/check_package_contents.py`
- `.github/workflows/ci.yml`（124-190 package-smoke）、`.github/workflows/release.yml`（55-132 build-windows）
- `tests/conftest.py`（232+）、`tests/core/test_path_resolver.py`
