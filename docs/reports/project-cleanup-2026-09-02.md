# 项目整理记录（安全缓存清理）— 2026-09-02

> 状态：LIVING · created: 2026-09-02
> 范围：`D:/~Vibe-Coding/Projects/AssetsManager_old-bak`
> 依据：`workspace-cleanup-windows` 技能铁律（先扫描后动手、走回收站不用 `rm`、删前证明可重建、避让并发会话）

## 一、扫描结论（整理前真实状态）

会话开头那张旧目录快照（webui 10000+ 文件、artifacts 839 文件等）已严重失实。实际项目结构：

| 类别 | 体积 | 文件数 | 处置 |
|---|---:|---:|---|
| `AssetsManager/`（源码 `.py`） | 9.4 MB | 480 | 保留 |
| `docs/`（收敛后 50 活跃 + 210 归档） | 6.0 MB | 608 | 保留 |
| `RuntimeData/`（**真实素材库 DB**） | 5.4 MB | 94 | **不动** |
| `tests/` | 5.1 MB | 345 | 保留 |
| `webui/`（源码，node_modules 已剪枝） | 1.4 MB | 212 | 保留 |
| **`webui/node_modules`（前端依赖）** | **158 MB** | 11339 | 待授权（可 `npm ci` 重建） |
| `.git` | 9.1 MB | 441 | 不动 |
| `outputs/` | 空目录 | 0 | 不动 |

**关键事实**
- `artifacts/`、`mirror/`、`webui/dist` 已不存在（早先轮次或用户已清理）。
- `RuntimeData/Avatars（角色）_d5cd47e2cd/assetmanager.db`（1.09 MB）+ `.db-wal`（4.14 MB）是真实数据库，含撤销备份、缩略图、设置——**不可删**。
- `webui/package-lock.json`（173.6 KB）存在 → node_modules 可精确重建。
- **42 份未提交改动**（41 `M` + 3 `??`）属并行会话在途工作，最后写入约 6.7 小时前；其目录（含 `AssetsManager/` 代码、`tests/`、`docs/architecture.md`、`docs/overview-*`、`README.md` 等）全程避让。

## 二、本轮清理（用户授权：仅安全缓存）

清理对象全部为**可重建产物**，零风险、不影响并行 WIP：

| 类型 | 数量 | 体积 | 重建方式 |
|---|---:|---:|---|
| `__pycache__` 目录 | 29 | 5.89 MB | Python 自动重编译 |
| `.pyc` / `.pyo` 散落文件 | 0（已含于上） | — | 同上 |
| `.ruff_cache` / `.pytest_cache` | 2 目录 | ≈0 | 工具自动再生 |
| `.cython-nuitka` | 1 目录 | ≈0 | 构建再生 |
| `*.tsbuildinfo`（含 node_modules 内 4 个） | 5 文件 | ≈0 | `tsc`/`npm ci` 再生 |

涉及目录：`AssetsManager/**/__pycache__`（22 处）、`tests/**/__pycache__`（3 处）、根/脚本/Plugins 各 1 处、`webui/tsconfig.tsbuildinfo` 等。

## 三、执行结果

- **回收方式**：`SHFileOperationW` + `FOF_ALLOWUNDO`（进回收站，非 `rm`）；回收后二次清理空壳目录（`os.rmdir` 仅空目录）。
- **清除**：34/34 目标全部移除（最终复扫 `LEFTOVER_TARGETS_AFTER=0`）。`AssetsManager/core/__pycache__` 一度 `rc=120`（Windows 对"文件曾被占用"的假失败码），空壳清理后已彻底消失，实际成功。
- **净释放**：约 **5.89 MB**（回收站内，清空回收站才真正释放磁盘）。
- **并行 WIP 零影响**：未删除任何 `.py`/`.ts`/`.md` 源码或文档。

## 四、未清理与风险边界

| 项目 | 体积 | 状态 |
|---|---:|---|
| `webui/node_modules` | 158 MB | 待你明确授权（可 `npm ci` 重建；若并行 dev server 在跑会被打断） |
| 42 份并行未提交 WIP | — | 避让，由其会话自行提交 |
| `RuntimeData/`（数据库+设置+撤销备份） | 5.4 MB | 不动 |
| `.git` 对象库 | 9.1 MB | 不动 |

## 五、后续建议

1. **若要进一步释放 158 MB**：确认无 webui dev/build 进程运行后，授权回收 `webui/node_modules`（有 `package-lock.json` 兜底）。
2. **并行会话收尾后**：其 42 份 WIP 提交后，可复跑文档门禁 `scripts/check_documents.py` 与断链扫描，确认无回归。
3. **定期**：`.pyc`/`__pycache__` 类缓存可随时按本记录流程重清，无副作用。
