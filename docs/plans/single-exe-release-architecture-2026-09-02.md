---
title: "单 exe 发布架构方案"
type: plan
status: LIVING
date: 2026-09-02
area: packaging / release
owner: agent (提案，未实现)
supersedes: none
---

# 单 exe 发布架构方案（2026-09-02）

> 长期架构任务。本文是**提案**：给出从 onedir+安装器 迁移到"单 exe 分发"的完整路径、代码级改动清单与风险边界。按项目纪律只出方案不动代码；并行会话未提交 WIP 全程避让。

## 1. 背景与目标

### 1.1 现状（已核实）

- 打包形态：PyInstaller **onedir**（`AssetManager.spec:356-368` `COLLECT` → `dist/AssetManager/`），再经 Inno Setup per-user 安装器分发（`installer/assetmanager.iss`、`scripts/build_installer.py`，CI 链见 `.github/workflows/release.yml:57-102`）。
- 数据模型：应用把**所有可写数据**放在"exe 旁 `RuntimeData/`"（`path_resolver.py:117-123`），前提是 per-user 安装目录可写（`installer/assetmanager.iss` 头注：`PrivilegesRequired=lowest` + "writes NEXT TO the executable"）。
- 库根（用户素材目录）由用户选定、不含于 RuntimeData；RuntimeData 内存库 DB、缩略图、收藏、锁、identity 标记、settings、crash 日志、cloudflared 下载缓存。

### 1.2 目标形态

- 分发物 = **单个 `AssetManager.exe`**（双击即用，可放任意目录；升级 = 覆盖替换）。
- 运行期数据不再跟 exe 走，落到用户数据目录（`%LOCALAPPDATA%\AssetManager\`）。
- 对存量 onedir 安装用户：升级后数据**无损迁移**，可回滚（单向降级风险需声明）。

### 1.3 关键认知（一句话）

> 单 exe 只改变"运行期布局"，不改变"仓库布局"。而运行期可写物几乎全部挂在一个函数（`runtime_root()`）下——**数据根独立化是唯一真正断点，先做它；spec 单文件化反而是低风险尾段**。

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

- **F1（疑似现存）**：PyInstaller 6.x 默认 `contents-directory=_internal`，onedir 下 spec datas 落在 `dist/AssetManager/_internal/Assets/Themes`；而 `themes_dir()` frozen 分支在无 `_MEIPASS` 时 fallback **`exe旁/Assets/Themes`**（`path_resolver.py:248`）——该路径在 `_internal` 布局下可能不存在，内置主题或已丢失。**需在实施时于真实 onedir 产物上验证**。
- **F2（onefile 必现）**：onefile 下 `_MEIPASS` 存在 → `themes_dir()` 返回临时解压目录（只读、退出即删）。用户保存/导入自定义主题（`dialogs/settings_dialog.py:490` `dest = themes_dir()/...json`）会写进临时目录——写入失败或写后丢失。主题体系是**单一目录扫描**（`core/theme_loader.py:33-67`、`core/themes.py:156-168` 委托 loader），没有"内置只读 + 用户可写"双层概念。
- **F3**：`plugins_root()` frozen→exe 旁；onedir per-user 安装可写，单 exe 任意放置时不可靠。插件搜索路径为 `[SHARED_DIR/"plugins", addons_dir()]`（`manager.py:201-203`）——前者自动迁移，后者需随 `plugins_root()` 改动。
- **F4（升级残留）**：只要数据在 exe 旁，升级覆盖/目录移动都伴随数据残留或"双份数据"困惑——单 exe 必须消除。

## 3. 目标运行期布局

```
%LOCALAPPDATA%\AssetManager\            ← 新数据根（frozen 态唯一可写区）
├─ RuntimeData\                         ← 原 RuntimeData 整体迁入（内部结构零改动）
│  ├─ Shared\  (settings.json, crash.log, crash.pending, cloudflared 缓存, plugins/)
│  └─ <lib>_<hash>…\  (assetmanager.db, .thumbnails, favorites.json, recent.json, 锁/identity)
├─ Plugins\Addons\                      ← 用户扩展可写位（原 exe旁/Plugins/Addons 迁入）
└─ Themes\                              ← 用户自定义主题（新建；内置主题仍读 _MEIPASS，见 §4.3）
```

**数据根选址论证（LOCALAPPDATA 而非 APPDATA / exe 旁）**：

| 候选 | 评估 |
|---|---|
| `exe 旁`（现状） | 单 exe 可任意放置 → 不可靠；升级残留 |
| `%APPDATA%\AssetManager` | 默认 roaming，素材库数据大且无需漫游同步 |
| `%LOCALAPPDATA%\AssetManager` | ✅ per-user 无 UAC、同机可写、不同步；与安装器 `{localappdata}\Programs` 同基座便于卸载清理 |

**开发态不变**：非 frozen 时 `runtime_root()` 保持 `仓库根/RuntimeData` 推导（`path_resolver.py:123`），使仓库开发、CI、全部单测（`tests/core/test_path_resolver.py` 等以 monkeypatch `runtime_root` 注入 tmp 路径）**零改动、零影响**。

## 4. 改动设计（按里程碑分层）

### 4.1 M1 · 数据根独立化（P0，与单 exe 解耦，先行合入）

1. **新增 `user_data_root()`**（`path_resolver.py`）：frozen → `Path(os.environ["LOCALAPPDATA"])/"AssetManager"`；dev → 保持现状推导（`Path(__file__)...parent.parent.parent`）。`runtime_root()` frozen 分支改为 `user_data_root()/"RuntimeData"`（保持内部名字，迁移零结构改动）。
2. **首启迁移 `migrate_data_root()`**（frozen 且目标不存在而来源存在时执行）：
   - 来源候选：① `exe旁/RuntimeData`（旧 frozen 布局）。开发仓库 RuntimeData **不迁**。
   - 目标：`%LOCALAPPDATA%\AssetManager\RuntimeData`。
   - 时机：`run.py` → `AssetsManager.app.main` 最前、任何 QApplication/AppSettings 实例化之前（settings 模块级即消费 `SHARED_DIR`，见 `settings.py:127` 与 `path_resolver.py:133` 的 import 时序——迁移必须先行）。
   - 幂等：成功后在旧位置写 `.data_root_migrated` 标记；新位置已有数据（非空 Shared/或存在 db）则视为已迁，跳过。
   - 策略：优先 `shutil.move`（同卷原子）；`OSError`（跨卷）→ `copytree` + 校验 + 删除旧目录；失败 **fail-closed**（弹启动错误，不静默继续）。
   - 并发：双开竞争 → 目标 `Shared/` 下 `.migrating` 锁标记 + 重试一次。
3. 迁移后**不自动删除** exe 旁旧 RuntimeData（保守，卸载器/用户处置）；onedir 安装器卸载脚本同步清 `%LOCALAPPDATA%\AssetManager`。

**自动跟随（零改动）**：settings（127）、crash（27-32）、cloudflared 缓存（tunnel 154-162）、库 slot（136-216）、用户插件 `SHARED_DIR/plugins`（manager 201-203）。

**验证**：真机 onedir 安装 → 造数据 → 换新版本（新布局）首启 → 数据完整、旧位有标记；`--package-smoke`（`run.py:27-46`）通过。

### 4.2 M2 · 插件双层（P1）

- `plugins_root()` frozen → `user_data_root()/"Plugins"`（可写扩展位）；`addons_dir()`/`plugins_docs_dir()` 自动跟随。
- 内置种子插件（spec datas `Plugins→Plugins`）若需在单 exe 提供只读基线：`_MEIPASS/Plugins`；实施时核对 `core/plugins/manager.py`/loader 的 manifest 扫描是否需扩展为多源合并（插件搜索路径现为 `[SHARED_DIR/"plugins", addons_dir()]` 双源，天然支持再加内置源）。

### 4.3 M2 · 主题双层（P1，修 F1/F2）

- `themes_dir()` 语义调整：frozen → `user_data_root()/"Themes"`（**可写用户层**）。
- `core/theme_loader.py` 增加内置只读源探测并合并扫描：候选 `_MEIPASS/Assets/Themes`、`exe旁/_internal/Assets/Themes`、`exe旁/Assets/Themes`（按实际解压布局，顺手修 F1）；`scan_directory` 扩展为多目录扫描（用户层优先、内置兜底、同名去重或用户层覆盖）。
- 写路径（`settings_dialog.py:490`、导入/导出主题）全部指向用户层——onefile 下不再写临时目录。
- dev 态不变（`themes_dir` 维持仓库 `Assets/Themes` 单一语义）。

### 4.4 M3 · spec 单文件化（P2）

- `AssetManager.spec`：删除 `COLLECT`（356-368），将 `a.binaries/a.zipfiles/a.datas` 并入 `EXE`（332-354）；`console=False`、icon、version 保持。
- `datas` 目标层级**不改**（§2.3 已证只读资源在 onefile 下全兼容）。
- 决策点：`runtime_tmpdir`（默认 `%TEMP%\_MEIxxxx` 即可，除非需防 AV/清理策略）。
- 预期：单文件体积 ≈ onedir 净体积（PyInstaller 对 DLL 不做压缩），首启解压 3–15s（视磁盘/AV），`%TEMP%` 需 ≥1× 单文件体积的空闲。

### 4.5 M3 · 构建流水线（P2）

| 位置 | 改动 |
|---|---|
| `build.py:51-77` `optimize()` | 删除（针对 `_internal/` 的 Qt 清理在单文件下失效） |
| `build.py` 产物 | `dist/AssetManager/` → `dist/AssetManager.exe` |
| `scripts/check_package_contents.py` | 适配单文件：校验内容从"目录树"改为"spec datas/hiddenimports 一致性"或退役 |
| `scripts/build_installer.py` + `installer/assetmanager.iss` | 二选一：**A 纯绿色分发**（installer 退役，release 只传 exe+sha256）；**B 安装器包一层**（iss 打包单 exe 至 `{localappdata}\Programs\AssetManager`，卸载清 `%LOCALAPPDATA%\AssetManager`） |
| `.github/workflows/release.yml:57-102` | 产物路径/artifact 名同步 |

### 4.6 M3 · 版本 / 升级 / 回滚（P2）

- `APP_VERSION` 单一源（constants.py）不变；spec 镜像机制（`AssetManager.spec:21-25`）不变。
- 数据根独立化需要**新大版本**发布（行为变更），版本号提示用户。
- 回滚声明：旧版（onedir、写 exe 旁）启动时会看到新位置数据但**不迁移回** → 数据分叉风险。策略：新版本发布说明标注"不建议降级"；旧版若检测到 `%LOCALAPPDATA%\AssetManager` 存在可弹一次性提示（可选增强）。

## 5. 风险与验收

### 5.1 风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 并行会话 42–53 份未提交 WIP 全程在改 `AssetsManager/` 源码 | 本方案只落 `docs/plans/`，不落码；实施窗口须在并行会话提交后 |
| R2 | 迁移跨卷失败 / 半途中断 | 复制校验 + fail-closed + 旧位保留可重试 |
| R3 | 双开迁移竞争 | `.migrating` 锁 + 重试 |
| R4 | 内置主题在 onedir `_internal` 布局下是否已丢失（F1） | M2 实施时先在真实产物验证 |
| R5 | 单文件被 AV 误报、启动慢 | 代码签名 + 发布说明；`runtime_tmpdir` 备选 |
| R6 | 旧版回滚数据分叉 | §4.6 版本策略声明 |
| R7 | 测试面 | 全部单测走 monkeypatch `runtime_root`（`tests/conftest.py:232+`、`test_path_resolver.py` 全程 patch）→ 实现细节改动不破坏；新增迁移单测 |

### 5.2 验收（每里程碑 gate）

1. 门禁：`scripts/check_documents.py`、`scripts/check_boundaries.py` exit 0。
2. 单测：pytest 全绿（重点 `tests/core/test_path_resolver.py`、`test_themes.py`）。
3. frozen 冒烟：`AssetManager.exe --package-smoke`（`run.py:27-46`）exit 0。
4. 手工升级路径：干净机安装（onedir 旧版）→ 建库/加收藏/换主题/存 settings → 覆盖为新布局 → 首启迁移 → 数据与偏好完整、主题可保存、LAN 页面可达（SPA 自 `_MEIPASS/webui/dist` serve）。

## 6. 实施顺序摘要

| 里程碑 | 内容 | 性质 |
|---|---|---|
| M1 | 数据根独立化 + 首启迁移（§4.1） | 代码改动面最小、收益最大；先行 |
| M2 | 插件双层 + 主题双层（§4.2/4.3） | 消除 F1/F2/F3 |
| M3 | spec 单文件 + 流水线 + 版本策略（§4.4-4.6） | 低风险尾段 |

每里程碑独立提交 + 双门禁 + 单测 + 手工冒烟。

## 7. 待实施时确认（open questions）

1. PyInstaller 实际版本与 onedir `_internal` 目录布局实测（决定 F1 现存性与 themes 内置源探测顺序）。
2. onedir 存量用户规模（决定迁移兼容优先级与回滚策略强度）。
3. 单 exe 目标体积 / 首启时间可接受阈值（决定是否压内置主题/裁剪 Qt）。
4. `core/plugins/` loader 的 manifest 扫描语义（多源合并复杂度）。
5. 分发方向 A（纯绿色单文件）还是 B（安装器包一层）——影响 installer/ 去留与卸载清理责任。

## 8. 参考文件

- `AssetsManager/core/path_resolver.py`（117-123/126-133/219-223/240-249）
- `AssetsManager/core/settings.py`（127/244）、`crash_handler.py`（27-32）
- `AssetsManager/core/plugins/manager.py`（201-203）
- `AssetsManager/core/theme_loader.py`（33-67）、`core/themes.py`（156-168）
- `AssetsManager/dialogs/settings_dialog.py`（490）
- `AssetsManager/lan/routes/pages.py`（7）、`lan/tunnel.py`（131-168）、`lan/api.py`（373-374）
- `AssetsManager/app.py`（213）、`run.py`、`main.py`
- `AssetManager.spec`（21-25/75-87/332-368）、`build.py`（9-11/51-77）
- `installer/assetmanager.iss`、`scripts/build_installer.py`、`scripts/check_package_contents.py`
- `.github/workflows/release.yml`（44-102）
- `tests/conftest.py`（232+）、`tests/core/test_path_resolver.py`
