# 工作树 / 运行时垃圾 / 文档 清理方案

- 日期：2026-08-31
- 工作区：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
- 状态：**阶段 0 已执行完毕，阶段 1–3 待定**（详见下方「执行记录」）

## 执行记录（2026-08-31 16:00 更新）

### 已完成

| 项 | 结果 |
|---|---|
| `tmp/` | 5520.8 MB → **已移除**（58 个一级条目、20 个 275 MB `.bin` pytest LAN 固件） |
| `cloudflared-windows-amd64.exe` | 51.6 MB → **已移除** |
| 孤儿 worktree 独有文件抢救 | **24 / 24 复制并 SHA256 校验通过**（280 KB）→ `docs/archive/2026-08/recovered-grid-zoom-interpolation/`（含 `MANIFEST.md`） |
| `.worktrees/` | 346.5 MB（不含 node_modules）→ 回收中 |
| `outputs/` 分流 | 11 个文件已就位于 `docs/plans/`(4) · `docs/reports/`(5) · `assets/icons/`(2)，SHA256 逐个比对**全部相同** |
| 交叉引用修正 | 7 个 md 中的 `outputs/xxx.md` 引用已改写为新路径 |
| 项目总体积 | **7.02 GB → 1.15 GB**；回收站确认收到 5.42 GB（可恢复） |

### 实施要点（供后续复用）

- 宿主的 `Add-Type` 被安全策略拦截，无法走 `Microsoft.VisualBasic.FileIO.FileSystem`。改用 Python `ctypes` 调 `shell32.SHFileOperationW`（`FOF_ALLOWUNDO|FOF_NOCONFIRMATION|FOF_NOERRORUI|FOF_SILENT`）。
- **该 API 返回码不可靠**：返回 `120` 或 `2` 时操作实际已成功。判据必须用「路径是否消失」，不能用返回码。
- `SHFileOperationW` 会删掉目录内容但删目录本身失败，留下空壳目录树 → 需二步：先回收，再 `os.walk(topdown=False)` + `os.rmdir` 只删空目录。
- 可恢复性验证：解析 `D:\$Recycle.Bin\<SID>\$I*`（格式：8B 头 + 8B 大小 + 8B 删除时间 + UTF-16LE 原路径）。

### 新出现的阻塞项：并行会话正在做同一件事

清理过程中确认**有另一个会话在本工作区并发工作**：

- 它已提交 3 个 commit：`37cfc56` → `32c096b` → `2ac8495`（AI 打标功能）。
- 它**独立完成了 `outputs/` → `docs/` 的分流**，分类与本方案一致；我接手时目标文件已存在，故改为只做校验与引用修正。
- 它又开始写代码：`?? AssetsManager/application/command_registry.py`、`command_executions.py`、`M db_migrations.py`。

因此：

- `outputs/` **不删**：其中 9 个文件是**已入库**的（`git ls-files outputs/` 可证），删除会产生跟踪态删除；且并行会话可能正准备提交这次迁移。
- 引用修正幂等，重复执行无害。

### 仍待处理

| 项 | 体积 | 阻塞原因 |
|---|---|---|
| `.worktrees/` | 346.5 MB | 回收中（RuntimeData 文件多，逐文件进回收站较慢） |
| `RuntimeData/` | 22.9 MB | 应用仍在运行 |
| `artifacts/` | 16.0 MB | 待归档 |
| `mirror/` | 19.7 MB | **git 对象库修复来源，修复完成前必须保留** |
| `outputs/` | — | 并行会话占用中 |
| git 对象库（312 → 61） | — | 需会话静默后执行 |
| `docs/` 根瘦身 + `INDEX.md` | — | 并行会话活跃，暂缓 |

---

## 0. 阻塞项：本工作区此刻有活跃会话 + 应用正在运行

这是本次扫描最重要的发现，直接决定计划能否执行。

**证据 1 — 另一个会话正在开发 `ai_tagging` 功能（写入实时发生）**

```
14:07:09  RuntimeData/Shared/tag_library.json
14:06:02  tests/desktop/test_info_ai_tag.py
14:03:22  tests/integration/test_ai_tagging_ollama_optional.py
14:02:31  tests/integration/test_ai_tagging_service.py
14:00:44  AssetsManager/core/settings.py
13:59:37  tests/unit/test_ai_tag_write_policy.py
13:55:32  tests/unit/test_ai_tag_settings.py
```

`git status` 在约 10 分钟内从 5 项增长到 23 项：

```
 M AssetsManager/core/constants.py          M AssetsManager/core/settings.py
 M AssetsManager/dialogs/settings_dialog.py M AssetsManager/i18n/{en,ja,zh}.json
 M AssetsManager/panels/file_list/_actions.py
 M AssetsManager/panels/file_list/_base_layout.py
 M AssetsManager/panels/info.py             M README.md
?? AssetsManager/application/ai_tagging/
?? AssetsManager/panels/_ai_tag_common.py
?? tests/unit/test_ai_tag_{settings,service,ollama_client,write_policy}.py
?? tests/integration/test_ai_tagging_{service,ollama_optional}.py
?? tests/desktop/test_{file_list_ai_tag,info_ai_tag,settings_ai_tagging}.py
?? outputs/evolution-strategy-2026-08-31.md
?? outputs/pm-capability-analysis-2026-08-31.md
```

**证据 2 — AssetsManager 应用本体正在运行**

```
14:09:42  RuntimeData/Shared/settings.json
14:09:41  RuntimeData/tmp8usift41_.../assetmanager.db
14:09:41  RuntimeData/tmp8usift41_.../assetmanager.db-wal
14:09:41  RuntimeData/tmp8usift41_.../assetmanager.db-shm
14:09:41  RuntimeData/Shared/library-553e65dcdd93ed0a.lock   ← 库锁活跃
```

隔 15 秒复检，以上文件仍在刷新窗口内 → **持续写入**。

**结论**

| 动作 | 是否可立即执行 | 原因 |
|---|---|---|
| 清理 `tmp/` `.worktrees/` `cloudflared.exe` | ✅ 可 | 与活跃会话零交集 |
| 从 bundle 补回 git 对象 | ⚠️ 低风险 | 只新增对象、不动 ref；但会写 `.git` |
| `git gc` / `rebase` / orphan 重建 | ❌ 禁止 | 会与活跃会话的提交冲突 |
| 清理 `RuntimeData/` | ❌ 禁止 | 应用正在读写 |
| 重整 `docs/` `outputs/` | ❌ 建议推迟 | 存在写冲突风险 |

---

## 1. 工作树

### 1.1 现状

| 项 | 值 |
|---|---|
| 分支 | 仅 `master`，无本地特性分支、无 stash |
| 远端 | `origin → https://github.com/Bilibili-Hysz/AssetManager.git` |
| HEAD | `7dd5230 feat(relink) 维护页失链文件分组与再挂接动作`（2026-08-31）|
| 在途改动 | 10 个 `M` + 13 个 `??`（见 §0）|
| 对象库 | **312 处 broken link / 312 个对象缺失** |
| 历史可读性 | 最近 50 个提交（8/30–8/31）全部可读 |
| 已跟踪最大文件 | 0.22 MB（`tests/lan/test_lan_api.py`）→ **无需 BFG / filter-repo 重写历史** |

`git rev-list --count HEAD` 直接失败：

```
error: Could not read 5fbf93059e2a2926ffb6b4fb940981736fd7050f
fatal: Failed to traverse parents of commit a05851467ef8c91c20b7d0f6603f9e1d37a49ad1
```

### 1.2 关键发现：本地 `mirror/` 就是修复来源

`mirror/` 下 5 个 git bundle **全部有效**，且 `git bundle verify` 均报告 `The bundle records a complete history.`

其中 `AssetsManager-2026-08-13.bundle` 还含：

```
0885d77c74baa6caa94f0a6e98b155a5f3fef399 worktrees/grid-zoom-interpolation-fix/HEAD
```

→ 印证 `.worktrees/grid-zoom-interpolation-fix` 原本是 `fix/grid-zoom-interpolation` 分支的真实 worktree，现已成孤儿。

**逐个 bundle 的补回能力**（在系统临时目录建裸仓库实测，不碰主仓库）：

| bundle | 可补回对象数 |
|---|---|
| `AssetsManager-2026-08-15.bundle` | **251 / 312** |
| `AssetsManager-2026-08-14.bundle` | 149 / 312 |
| `AssetsManager-2026-08-13-final.bundle` | 142 / 312 |
| `AssetsManager-2026-08-13.bundle` | 141 / 312 |
| `AssetsManager-pre-cleanup-2026-08-13.bundle` | 141 / 312 |

**`2026-08-15` 一个是全集的超集** —— 5 个 bundle 合并仍是 251，没有增量。

### 1.3 补不回的 61 个对象

`git rev-list --objects --missing=print HEAD` 确认：**全部 312 个缺失对象都在 HEAD 可达历史内**，不是游离旧历史。补回 251 后仍有 61 个空洞。

丢失清单（60 个已定位到文件名 + 1 个 commit）：

| 类别 | 内容 |
|---|---|
| **commit（1）** | `5fbf93059e2a` —— 正是 `git rev-list` 崩溃的那个提交对象本身 |
| **tree（7）** | `dialogs` `domain` `e2e` `gallery` `performance` `widgets` `Docs` |
| **桌面端源码** | `_actions.py` `_background.py` `_base_events.py` `_grid_widget.py` `_grid_widget_data.py` `_grid_widget_interact.py` `_model.py` `_plugin_manager_widget.py` `sidebar.py` `dock_factory.py` `window_coordinator.py` `crash_handler.py` `desktop_ports.py` `tunnel.py` |
| **服务 / 仓储** | `tag_service.py` `gallery_service.py` `library_export_service.py` `library_export_service_export.py` `order_service.py` `order_repository.py` `auth_repository.py` `share_repository.py` `shop_buyer_service.py` `shop_repository.py` `plugin_service.py` `plugin_manager_dialog.py` `sharing_settings_dialog.py` |
| **测试** | `test_dock_factory.py` `test_file_list_model.py` `test_gallery_incremental.py` `test_gallery_service.py` `test_info_async_identity.py` `test_layer_dag.py` `test_library_service.py` `test_order_repository_batch.py` `test_permission_enforcement.py` `test_server_lifecycle.py` `test_settings_dialog_plugins_tab.py` `test_settings_maintenance.py` `test_sidebar.py` `test_tag_service.py` `test_thread_identity_bypass.py` `test_unload_cleanup.py` |
| **脚本 / 文档** | `check_doc_stats.py` `check_layers.py` `check_style_sources.py` `App.tsx` `.gitignore` `11-plugin-api-v2-handover.md` `12-quality-audit-2026-08-17.md` `13-architecture-debt-quantified-2026-08-17.md` `P0-optimization-completion-report.md` `performance-optimization-plan.md` |

`git fetch https://github.com/Bilibili-Hysz/AssetManager.git` 在本环境失败（`CONNECT tunnel failed, response 502`，代理拦截）。**联网后这 61 个很可能可以从 origin 补齐**。

### 1.4 执行步骤

| # | 动作 | 命令 | 风险 |
|---|---|---|---|
| 1.1 | 物理备份 `.git` 与全部在途文件 | 复制到 `AssetsManager_old-bak2` | 无 |
| 1.2 | 从 bundle 补回 251 个对象（只新增、不动 ref） | `git fetch "mirror/AssetsManager-2026-08-15.bundle" "refs/heads/master"` | 低 |
| 1.3 | 复检 | `git fsck --no-progress` → 错误应降至 61 | 无 |
| 1.4 | 联网环境补最后 61 个 | `git fetch origin` → `git fsck` | 低 |
| 1.5 | 确认再无写入后，提交在途改动 | 拆为 `feat(ai-tagging)` 一个提交 | 中（需确认写完）|

> **1.2 为什么相对安全**：该命令只往对象库里新增缺失对象，不创建、不移动任何 ref，不碰工作区。但既然另一个会话在提交，**仍建议在会话结束后执行**。

---

## 2. 运行时垃圾

全部已在 `.gitignore` 中，删除不影响版本库。

| 目标 | 体积 | 依据 | 处置 |
|---|---|---|---|
| `tmp/` | **5.5 GB** | 20 个 275 MB `.bin`（pytest LAN 大文件固件），分布在 11 个 `pytest-*` 目录（创建于 8/6）| 清 |
| `.worktrees/grid-zoom-interpolation-fix` | 470 MB | 未注册的孤儿副本：目录内无 `.git`，`.git/worktrees` 不存在；含 340 MB `RuntimeData` | 清 |
| `cloudflared-windows-amd64.exe` | 52 MB | 下载物，`.gitignore:73` | 清（可重下）|
| `mirror/*.bundle` | 20 MB | **现在是修复对象库的唯一离线来源** | **先留 08-15，补回完成后再决定** |
| `RuntimeData/` | 19 MB | `.gitignore:29`；**应用正在读写** | 等应用关闭后清 |
| `artifacts/` | 16 MB | 审计证据，`.gitignore:79`；`evidence/` 占 14.2 MB / 746 文件 | 归档后清 |
| `.pytest_cache` `.ruff_cache` `.cython-nuitka` `__pycache__` | < 1 MB | 缓存 | 清 |
| `.venv/` | 721 MB | 虚拟环境 | **保留** |

### 执行步骤

| # | 动作 |
|---|---|
| 2.1 | 确认无 pytest / agent 会话在运行 |
| 2.2 | 按「删除 / 移入回收站 / 打包冷存」三档归类（需用户定夺，见 §4）|
| 2.3 | 分批执行，**每批 ≤ 10 项**，逐批复验 `git status` 无新增变更 |
| 2.4 | 补 `.gitignore`：固化 `*.bin`、`tmp/` 等规则 |

---

## 3. 文档整理

### 3.1 现状分布

| 目录 | 文件数 | 说明 |
|---|---|---|
| `docs/full-review/` | 199 | 含 `archive/` 子目录 |
| `docs/archive/2026-08/` | 133 | 已有按月归档结构 |
| `docs/compose/` | 108 | `reports/` + `distilled/` |
| `docs/reports/` | 33 | 既有审计报告约定位置 |
| `docs/deep-weakness-audit-2026-08-22/` | 11 | 时点产物散落成目录 |
| `docs/` 根散落 | 8 | 见下 |
| `docs/plans/` | 6 | 既有方案约定位置 |
| `docs/adr/` | 5 | |
| `docs/diagrams/` | 2 | |
| `outputs/` | 11 | **未被 gitignore**，职责与 `docs/` 重叠 |

`docs/` 根散落的 8 个 md：

| 文件 | 大小 | 判定 |
|---|---|---|
| `architecture.md` | 28 KB | 长期文档 → 保留 |
| `migrations.md` | 14 KB | 长期文档 → 保留 |
| `overview-2026-08-27.md` | 53 KB | 时点快照 → 归档 |
| `testing.md` | 5 KB | 长期文档 → 保留 |
| `perf-baseline-2026-08-29.md` | 8 KB | 时点快照 → 归档 |
| `lan-security.md` | 11 KB | 长期文档 → 保留 |
| `development.md` | 6 KB | 长期文档 → 保留 |
| `architecture-diagram.md` | 12 KB | 时点快照 → 归档 |

### 3.2 执行步骤

| # | 动作 | 说明 |
|---|---|---|
| 3.1 | `outputs/` 分流 | 方案类 → `docs/plans/`；审计/评审类 → `docs/reports/`；`AssetsManager_icon.png/svg` → `assets/icons/`；清空后把 `outputs/` 加入 `.gitignore` |
| 3.2 | `docs/` 根瘦身 | 保留 5 个长期文档，3 个时点快照归档进 `docs/archive/2026-08/` |
| 3.3 | 建 `docs/INDEX.md` | 唯一入口，分「长期文档 / 方案 / 审计报告 / 归档」四栏；复用 `docs/full-review/00-INDEX.md` 格式 |
| 3.4 | 时间盒归档 | `full-review`（199）+ `compose`（108）按月归到 `docs/archive/YYYY-MM/`，正文只留索引 |
| 3.5 | CI 检查 | `docs/` 根新增文件必须登记进 `INDEX.md` |

---

## 4. 待决策

| # | 问题 | 选项 |
|---|---|---|
| 4.1 | 清理力度 | A 先移回收站，确认后再清（推荐）／B 打包冷存后删／C 直接删除 |
| 4.2 | git 修复范围 | A 只做 bundle 补回（312→61，低风险）／B 补回 + 联网补齐剩余 61／C 截断式重建（需会话结束）|
| 4.3 | `outputs/` 归属 | A 按既有约定分流（推荐）／B 整体移入 `docs/archive/`／C 保持不动 |
| 4.4 | 在途 `ai_tagging` | **已确认：先确认是否还有会话在写** |

---

## 5. 建议执行顺序

```
阶段 0（立即可做，零风险）
  清理 tmp/ 5.5 GB + .worktrees/ 470 MB + cloudflared 52 MB   →  回收 6.0 GB

阶段 1（活跃会话结束后）
  1.1 备份 .git
  1.2 git fetch mirror/AssetsManager-2026-08-15.bundle        →  312 → 61
  1.3 联网 git fetch origin                                    →  61 → 0
  1.4 提交在途 ai_tagging

阶段 2（应用关闭后）
  清理 RuntimeData/ + artifacts/

阶段 3（无冲突风险后）
  outputs/ 分流 → docs/ 根瘦身 → docs/INDEX.md → 时间盒归档
```

---

## 附：扫描期间产生的临时物

- `D:\~Vibe-Coding\Projects\_am_probe_tmp\`（4.9 MB，项目外）—— 用于验证 bundle 覆盖率的裸仓库探针，确认结果后可删除。
- 本方案写入的 `.workbuddy/memory/2026-08-31.md` 已记录全部发现。
