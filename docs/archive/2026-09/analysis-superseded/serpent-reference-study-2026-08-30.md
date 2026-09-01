# Serpent 参考项目研究（同类竞品实现方案拆解）
> 状态:**现行(参考)** · 注意:两条结论(以图搜图/AI 对话)已被 serpent-vs-assetmanager-2026-08-30.md 修正 · 状态登记:2026-09-02(文档梳理轮补登)


> 研究日期：2026-08-30
> 研究对象：https://github.com/dolag233/Serpent （MIT License）
> 本地副本：`D:\~Vibe-Coding\Projects\_REF_Serpent`（完整克隆，93 MB，1268 commits）
> 目的：学习同类产品的实现方案，反哺 AssetManager

---

## 一、项目概况

| 项 | Serpent | AssetManager（本项目） |
|---|---|---|
| 定位 | 跨平台数字资产管理，面向**游戏美术 / VFX / 平面与动态设计师** | 资产库管理 + 局域网分享 + 商城 |
| 技术栈 | **Electron 43 + React 19 + Vite 8 + TypeScript 6** | **PySide6 (Qt) + aiohttp + React 18** |
| 数据库 | `better-sqlite3`（同步驱动，性能取向） | SQLite + aiohttp 异步封装，17 个仓库 |
| 规模 | **667 文件 / 10.9 万行 TS** | 282 文件 / 9.6 万行 Python + 224 文件 WebUI |
| 起点 | 2026-07-12 创建（1.5 个月） | 长线演进 |
| 热度 | **257 star / 17 fork** | — |
| 版本 | 0.1.5（1268 commits） | — |
| 文档 | 中英双语 README | — |

**规模基本同量级**（10.9 万 vs 9.6 万行），但 Serpent 用 1.5 个月做到，且是**单一语言栈**——这是技术选型带来的效率差异。

---

## 二、关键实现方案拆解

### 2.1 表设计：三个值得学的决策

Schema 集中在 `src/worker/library-service.ts`（该文件 43,822 行，占全项目 40%）：

**① `human_asset_tags` 与 `ai_asset_tags` 物理分离**
```
索引证据：human_asset_tags_tag_idx / ai_asset_tags_tag_idx
```
人工标签和 AI 标签**存两张表**，各自独立索引。含义：AI 生成的标签永远不会污染用户亲手建立的组织体系；用户可随时清空 AI 标签而不影响人工组织。

> 对 AssetManager 的启发：若将来做 AI 打标，必须采用同样的物理隔离。我此前建议"别做 AI 打标"的理由是"没有向量索引、价值接不住"——**这个理由对，但结论过于保守**，见 §3.2 修正。

**② `collections` 表（合集）**
Serpent 已有集合功能。组织手段是 **标签 + 合集** 双轨，而 AssetManager 只有扁平标签。

**③ `gitignore_ignored_paths` + `explicit_ignored_paths`**
尊重项目原有的 `.gitignore`，而不是另建一套忽略规则。对创作者（很多同时是开发者）是贴心设计。

### 2.2 面向专业场景的深度

- `asset_sequences` / `asset_sequence_frames` —— **序列帧**（EXR / DPX 序列），这是 VFX 与游戏美术的刚需，通用文件管理器不会做
- `asset_color_space_overrides` —— 色彩空间覆盖（ACES / sRGB）
- 支持 3D 模型、音频、文本，不只是图片

**这说明它的产品定位比"看图工具"深得多**——打的是 Eagle / Billfish 这些商业工具的腹地。

### 2.3 AI：接外部 API，而非自建模型

```
src/worker/ai/  →  anthropic-adapter.ts / dashscope-adapter.ts（通义）/ gemini-adapter.ts
src/main/       →  ai-queue-scheduler.ts / ai-search-planner.ts
其他            →  job-abort-registry.ts（任务取消）
                   @modelcontextprotocol/sdk（MCP）
```

多供应商适配器 + 队列调度 + 可取消 + MCP 暴露给外部 Agent。**没有任何自建向量库或模型运行时**。

### 2.4 自动化体系（AssetManager 完全没有的）

`automation-*` 系列文件构成了完整体系：

| 文件 | 作用 |
|---|---|
| `automation-idempotency-store.ts` | 幂等存储（重复执行不产生副作用） |
| `automation-execution-journal.ts` | 执行日志（可追溯） |
| `automation-file-plan-approval.ts` | 文件操作**计划审批**（先出计划，人工确认再执行） |
| `automation-readonly-command-executor.ts` | 只读命令执行器（沙箱） |
| `automation-readonly-dispatch.ts` | 只读分发 |

**"计划审批 + 幂等 + 执行日志"三件套**是关键——脚本化批处理最怕的就是"跑错了没法回退"。这套设计让自动化变得可信。

### 2.5 同步与迁移

- **WebDAV 云同步**：多设备双向同步，可配轮询间隔（`sync_manifest_cache` / `sync_sessions` 表）
- **直接打开 Eagle / Billfish 资源库**：`eagle-library.ts` / `billfish-library.ts`，转换后无缝浏览检索

第二条是极强的**用户获取手段**——竞品用户零成本迁移。

### 2.6 性能相关

- `offscreen-thumbnail.html` —— Electron **离屏渲染**做缩略图
- `@napi-rs/canvas`（Rust canvas）、`koffi`（Node FFI 调原生库）
- `zip-import-stream.ts` —— **流式** ZIP 导入（AssetManager 的批量 ZIP 是非流式、无进度）
- `library_job_leases` 表 —— 任务租约（任务不重复执行、崩溃后可恢复）
- `browse_change_sequence` —— 浏览变更序列（增量更新而非全量刷新）

---

## 三、对我上一版方案的两条修正

> 这两条必须写出来。我上一版给的建议过于保守，Serpent 的实测做法给出了更好的中间路线。

### 3.1 「别做多端同步」→ 修正为「别**自建**同步引擎，但可以走 WebDAV」

原建议理由："几千到几万张大文件，做同步等于重做 Dropbox。"

**这个理由对一半**：自建同步引擎（冲突解决、增量传输、断点续传）确实是重做 Dropbox。但 Serpent 走 **WebDAV**——复用现成协议和服务端（NAS、坚果云、自建 Nextcloud 都支持），客户端只需实现上传下载 + 轮询，成本降一个量级。

**修正后的判断**：
- 若用户群体有 NAS / 自建存储 → WebDAV 同步价值高，成本低
- 若要自建服务端 → 不做

### 3.2 「别做 AI 打标」→ 修正为「别**自建向量索引**，但可以接外部 API + 标签分离」

原建议理由："库里没有任何向量或特征索引，也没有模型运行时；而连按修改时间筛选都还没有。"

**理由成立，但结论过于保守**。Serpent 证明了一条成本极低的路径：
- 接外部 API（Anthropic / 通义 / Gemini），无需本地模型
- **人工标签与 AI 标签物理分表**（`human_asset_tags` / `ai_asset_tags`）—— 这是最关键的设计，AI 永远不会污染人工组织
- 任务可取消（`job-abort-registry`）、有队列调度

**修正后的判断**：
- 前置条件仍然是**先补齐结构化检索**（按时间/大小筛选），这条不变
- 但 AI 分析本身可以低成本启动，且**必须做标签物理隔离**
- 更高性价比的替代：先做 **MCP 暴露**，让外部 Agent 来调用，连 API 成本都不用承担

---

## 四、值得抄的 / 不该抄的

### ✅ 值得抄（按性价比排序）

| 项 | 理由 | 成本 |
|---|---|---|
| **标签物理分表**（人工 / AI / 插件派生） | 防止任何一方污染另一方；`plugin_derived_fields` 表说明插件产物也独立 | 小 |
| **collections 合集** | 本方案 §4 已建议"命名集合"，Serpent 验证了这是刚需 | 中 |
| **gitignore 尊重** | 创作者多为开发者，零学习成本 | 小 |
| **流式 ZIP**（`zip-import-stream.ts`） | 直接对应 AssetManager 批量 ZIP 非流式、无进度的已知问题 | 中 |
| **自动化三件套**（幂等 + 执行日志 + 计划审批） | 批处理可信度的关键 | 中 |
| **MCP 暴露** | 让外部 Agent 控制，无需自建 AI 能力 | 中 |
| **任务租约**（`library_job_leases`） | 防止任务重复执行、崩溃后可恢复 | 中 |

### ⚠️ 需要谨慎（依赖场景）

| 项 | 判断 |
|---|---|
| WebDAV 同步 | 取决于用户是否有 NAS；见 §3.1 |
| AI 分析 | 接外部 API + 标签分离可以做；见 §3.2 |
| 序列帧 / 色彩空间 | 只在 VFX / 游戏美术场景有价值，需确认你的用户群 |

### ❌ 不该抄

| 项 | 理由 |
|---|---|
| **43,822 行单文件**（`library-service.ts`） | 占全项目 40%，这是**反面教材**。AssetManager 已有 1540 行 `database.py`、1700 行 `info.py`，别再往这个方向走 |
| Electron 技术栈 | 你的 PySide6 已稳定运行，重写成本远超收益 |
| 商城链路 | 你的教训是"62% 页面投在商城"，Serpent 完全没有电商功能，这印证了应当聚焦核心 |
| 内置 AI 分析模块 | 维护成本高，优先做 MCP 暴露 |

---

## 五、最刺眼的一个对比

| | Serpent | AssetManager |
|---|---|---|
| Web 页面 / 路由分配 | 无电商链路，全部投入核心能力 | 26 页面 16 个商城（62%），140 路由 59 处 `/api/shop/*` |
| 组织手段 | 标签 + 合集 + 序列 + 插件字段 | 仅扁平标签 |
| 自动化 | 幂等 + 日志 + 审批 + 只读沙箱 | 无 |
| 迁移能力 | 直接打开 Eagle / Billfish 库 | 无 |

Serpent 用 1.5 个月在"核心能力深度"上建立了明显优势（合集、序列帧、自动化、竞品迁移、MCP），而 AssetManager 的资源大量沉淀在电商链路上。**这是"功能重心偏离主用户"判断的最强外部佐证。**

---

## 附：本地副本使用说明

```bash
cd "D:/~Vibe-Coding/Projects/_REF_Serpent"

git branch -a          # main / dev / library-performance
git log --oneline -10  # 最近提交
```

- 完整克隆（含历史），可切换到任意分支查看演进
- `library-performance` 分支相对 main 独有提交数为 0，说明其工作已合并回主干
- 核心入口：`src/worker/library-service.ts`（数据库 + 库服务，43,822 行）
- 建议重点阅读：`src/worker/ai/`、`src/main/automation-*`、`src/worker/eagle-library.ts`
- node_modules 未安装，如需运行请先 `npm install`
