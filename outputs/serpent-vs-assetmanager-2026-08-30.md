# AssetManager ↔ Serpent 全维度差异对照（2026-08-30）

> 方法：Serpent 侧为只读探索代理的全维度事实清点（八板块、全部带 `_REF_Serpent` 内文件证据）；AssetManager 侧基于本会话多轮评审/实施的一手认知（file:line 见 outputs/ 下各评审与调研文档）。本文只做对照与判断，事实细节以两边证据为准。
> 提醒：此前 `docs/reports/serpent-reference-study-2026-08-30.md` 的两条认知被本次清点修正——Serpent **没有**以图搜图（文档明示"不提供 AI 搜索"，`docs/user-guide/ai.md:70`），也**没有** AI 对话；其 AI 仅覆盖描述/打标/评分三类分析任务。

---

## 一、一句话定位

| | AssetManager | Serpent |
|---|---|---|
| 定位 | **本地资产库的管理台 + 局域网分享门户 + 素材商城**（三种用户：库主/访客/买卖家） | **单机专业级 DAM 工作站**（游戏美术/VFX/设计师自用，零网络协作面） |
| 技术栈 | PySide6(Qt) + aiohttp + React 18，Python 单语言后端 | Electron 43 + React 19 + TS 6 单语言全栈，better-sqlite3 同步驱动 |
| 规模 | 282 py / 9.6 万行 + 224 ts | 667 ts/tsx / 21.5 万行（src 下实测，含 renderer 12,863 行 App.tsx） |
| 成熟度 | 长线演进，371 篇文档，CI 13 job | 7 周 1,268 commits 冲出来的新品（v0.1.5，257 star），文档双语+官网 |

---

## 二、功能差异矩阵（逐域）

### 1. 库管理
| 能力 | AssetManager | Serpent |
|---|---|---|
| 多库 | ✅ 多库切换（每库独立 DB+会话，单实例锁） | ✅ 创建/打开/关闭/重命名/最近/移除/从盘删除（84 条自动化命令含全生命周期） |
| 打开外部格式库 | ❌ | ✅ 直接打开 Eagle / Billfish 库（`eagle-library.ts`/`billfish-library.ts`，零成本迁移） |
| 库导出/导入 | ✅ 备份/恢复（.assetbackup，v36 契约校验） | ✅ 导出文件夹/ZIP + 导入（`library.export/import-*`） |
| 忽略规则 | 过滤管线 hidden/exclude/类型/深度/类别六项 | ✅ `.serpentignore`（gitignore 语法+`!` 否定）物化进表，浏览/搜索/计数统一生效 |
| 链接文件夹（库外原位引用） | ❌（拖入即复制/移动） | ✅ linked_folders + 规则 + relink + 可转托管 |

### 2. 浏览与查看器
| 能力 | AssetManager | Serpent |
|---|---|---|
| 视图 | 网格 + 详情（两种；README 宣称的列表视图缺位） | 网格 + 瀑布流 + 文件夹/合集卡片（**无列表视图**）；虚拟化画布 |
| 查看器 | 图片：缩放/平移/旋转；视频走 ffmpeg 池 | 图片/SVG/RAW(8 家)/PSD/EXR(多 plane)/TIFF/TGA/视频(webm 代理)/音频(波形)/3D(three.js+HDRI+PBR)/PDF(pdf.js)/文本/HTML |
| 序列帧 | ❌ | ✅ 自动检测导入、播放器、可设 FPS、表 `asset_sequences` |
| 色彩空间 | ❌ | ✅ 读取/切换/用户覆盖（`asset_color_space_overrides`） |
| 派生物 | 缩略图（含视频 ffmpeg 池、批量分片） | 9 类：thumbnail/viewer_image/poster/contact_sheet/webm_proxy/audio_proxy/extracted_metadata/palette/model_glb |

### 3. 组织手段
| 能力 | AssetManager | Serpent |
|---|---|---|
| 标签 | ✅ 扁平+别名（全局规范名）；**本会话刚做人工/AI/插件三源物理分表（v36，基建就绪无 AI 写入方）** | ✅ 人工/AI 分表（同思路）+ 标签管理工作台 + 共现图命令 |
| 合集/智能合集 | ❌（最大组织缺口，只有标签单轨） | ✅ collections 多对多拖入 + smart_collections（保存查询实时算） |
| 评分/喜欢 | ❌ | ✅ 0-5 评分 + favorite（列+命令+过滤） |
| 描述/来源/作者 | ✅ 备注+URL（单文件） | ✅ 人工/AI 描述分离 + source_url + EXIF 作者 |
| 主色 | ❌ | ✅ palette/dominant_hue 提取→过滤+排序（非手动色标） |
| 回收站 | ✅ send2trash + 撤销备份（data_dir 90 天） | ✅ trashed_managed_folders 墓碑表 |

### 4. 检索（本轮 T7 后的最新格局）
| 能力 | AssetManager | Serpent |
|---|---|---|
| 名称子串 | ✅ 三源合并（scanner→indexed→merge），桌面高级过滤面板 + Web q 通路（刚落地） | ✅ FTS5 全文虚表（filename/tags/description/source/folder/metadata_text） |
| 结构化维度 | ✅ ext/size/mtime 区间（刚落地，indexed-only） | ✅ 颜色/标签/宽高比/评分/格式/喜欢/丢失/长边宽高时长 + 高级语法（AND/OR/排除/短语/字段限定 `name: tag: …`） |
| 全文/FTS | ❌（无 FTS 表） | ✅ FTS5 + contentless 索引 |
| 保存的搜索 | ❌ | ✅ =智能合集 |
| 以图搜图 | ❌ | ❌（文档明示无） |

### 5. AI
| 能力 | AssetManager | Serpent |
|---|---|---|
| 路线 | 本地 Ollama（requirements 注释：qwen2.5vl），可选依赖 | 4 家 5 种外部 API 适配器（OpenAI×2/Anthropic/Gemini/DashScope），用户自带 Key |
| 任务 | 打标（基建 v36 已就位） | 描述/打标（可限已有标签）/评分；视频发联系表、3D 发四视图；输出语言 4 选 |
| 工程化 | ❌ 无队列/取消 | ✅ 队列调度（批量+指数退避+抖动）、中断注册表、并发限流、进度节流、任务窗口暂停/取消/重试、新资产自动分析开关+豁免表 |

### 6. 自动化 / MCP / 插件（差异最大的板块）
| 能力 | AssetManager | Serpent |
|---|---|---|
| 自动化命令面 | ❌ 无命令网关（桌面操作只有 GUI 入口） | ✅ 84 命令注册表（library/file/asset/folder/tag/collection/smart-collection/media.jobs/ai/history.*），全写命令强制 idempotencyKey |
| 审批 | ❌（T8 缓办中） | ✅ execution/plan/none 三档（41/9/4）；危险操作 challengeId+planHash 二次确认 |
| 执行日志 | ✅ 刚落地（activity_log，桌面操作+LAN 事件） | ✅ execution journal + history.status/undo/redo 命令（**跨端共享可撤销操作历史含 redo LIFO**） |
| 只读沙箱 | ❌ | ✅ Worker 层 25 命令白名单只读执行器 |
| MCP | ❌ | ✅ 内嵌 MCP 服务器（127.0.0.1:47342/mcp），每客户端独立凭据可撤销、权限代理+策略存储、工具带 riskTier/destructiveHint 注解 |
| 插件 | ✅ v2 体系（无沙箱、同解释器，权限门禁为意图边界） | ✅ QuickJS 沙箱脚本（依赖限额、预览）+ 插件可成 MCP 工具提供方 |

### 7. 分享 / 协作 / 电商（AssetManager 独有半壁）
| 能力 | AssetManager | Serpent |
|---|---|---|
| 局域网分享 | ✅ 140 路由：六种 principal+8 位能力、分享链接（密码≥8/限时/限次/撤销）、WebSocket 失效推送、移动端适配、Cloudflare 隧道 | ❌ 完全没有 |
| 电商 | ✅ 16/26 页面：目录/购物车/幂等结账/订单状态机/投递令牌(claim/rotate)/卖家工作台/分析 | ❌ 完全没有 |
| 多用户 | ✅ 管理员/注册用户/访客 + 邀请码 | ❌（MCP 凭据是本机服务，非远程多人） |
| 云同步 | ❌ | ✅ WebDAV 双向（5s 轮询、冲突存副本、sync_id 跨设备身份、凭据入钥匙串/DPAPI） |

### 8. 外观与集成
| 能力 | AssetManager | Serpent |
|---|---|---|
| 主题 | ✅ 24 主题（WCAG 全绿）+ 背景特效（blur/mosaic/kuwahara/shader）+ Web 跟随库主 | 3 profile × 明暗 2 tone + 自定义 token + 背景图 |
| i18n | ✅ en/zh/ja 三语 874 键全对齐（桌面+Web） | en + zh-CN 两种 |
| 系统集成 | ✅ 托盘、多标签工作区、单一实例锁（刚加）、云隧道 | 托盘（windows-tray）、浏览器扩展（独立仓库+内置）、全局缩放 |
| 平台 | Windows 为主（Python 跨平台理论可行） | 仅 macOS arm64 + Windows x64（构建期硬校验），无 Linux |

---

## 三、架构差异（本质差异在并发与变更模型）

| 维度 | AssetManager | Serpent |
|---|---|---|
| 进程模型 | **单进程**：Qt GUI + asyncio LAN 线程 + QThreadPool 池；SQLite 单库单连接 + 连接级读写门（WAL 多读并发等于没开，T10 缓办中） | **四类进程**：Main/Preload/Renderer/Worker(UtilityProcess)；better-sqlite3 同步驱动整体放 Worker，IPC 单命令通道 + 多事件通道 |
| 写协调 | `db_write_lock`（61 处 @locked_read + ~90 处写锁） | `library_write_leases` 跨进程写租约 |
| 变更通知 | RuntimeEventRouter → 领域事件 → Qt 信号（UI）/WS 失效帧（Web），HTTP /api/revision 权威游标 | `library_change_sequence`/`browse_change_sequence` 由 **20+ 张表的触发器**同事务推进（"never best-effort"），MCP 事件回显序号 |
| 长任务 | QThreadPool/BoundedPool + generation 取消 | `library_job_leases` 持久租约 + fencing token + 心跳（崩溃可接管） |
| 请求治理 | 无准入分级 | **7 条性能 lane**（interactive-control/visible-media/…）+ 截止时间信封 + 启动突发门（首屏前不放后台任务） |
| 迁移纪律 | v1→v36 SAVEPOINT 整体包裹 + 契约回溯校验 + 冻结历史名 | v1→v48 每版 **SHA256 checksum** + 整表重建常态 + 专门的迁移纪律测试脚本 |
| 内存治理 | 无统一预算（缩略图池有并发上限） | 进程级 384MB 原生解码预算 + 64MP 上限 + 暂存上限 + 资源守卫 |

两边在同一问题上给出了不同答案：AssetManager 用"单进程+锁门"换简单；Serpent 用"多进程+租约+lane 准入"换并发与可观测。Serpent 的触发器式变更序号与租约模型明显更工程化；AssetManager 的单进程模型则免去了 IPC 序列化与跨进程调试成本。

---

## 四、数据模型差异

- **Serpent 55 张表**（含历次重建表）：核心是 assets（managed|linked 双位置+path_identity+sync_id）+ revisions 版本链 + revision_artifacts 九类派生物 + asset_metadata + FTS + 标签三表 + 合集三表 + jobs/leases/operation_history（自动化）+ sync 两表 + 序列/色彩/忽略五表。
- **AssetManager** 约 30+ 张表：file_tags/tag_metadata（+v36 两张来源表）、file_meta（备注/计数缓存）、assets 索引、favorites、activity_log、shop_* 十余张（商城域）、import_manifests、reconciliation_*（跨进程队列）、thumbnail_cache、share/auth/users 等 LAN 域。
- 形态差异：Serpent 把**版本链（revisions）和派生物登记（revision_artifacts）**做成一等公民——AssetManager 的缩略图是缓存语义（可重建、FIFO 逐出），Serpent 的派生物是资产履历语义（带 kind CHECK 登记）。AssetManager 把**人/权限/订单**做成一等公民（users/invites/shop_orders/delivery_tokens），Serpent 完全没有。

---

## 五、测试 / CI / 打包

| 维度 | AssetManager | Serpent |
|---|---|---|
| 测试 | pytest 4317+（unit/integration/lan/desktop/e2e/perf 分域）+ vitest 760 + axe a11y 门禁 + Playwright 6 spec | Vitest 567 文件 / 4028 用例（worker 测试跑在 Electron 内）+ Playwright 53 e2e（含隔离模式/打包产物/大库性能基准三档） |
| CI | ✅ GitHub Actions 13 job（3.12-3.14 矩阵 + webui + e2e + 打包冒烟） | ❌ **无 GitHub Actions**（main/dev 均无 workflows）；发布门禁是本地 release pipeline（verify/media/package/e2e/make/checksums 五阶段）+ pre-commit 分支守卫 |
| 静态门禁 | 12+ 自研 AST 门禁（分层 DAG/边界/QSS px/token 用量/doc-stats/路由能力…）+ ruff/pyright | ESLint 10 + tsc（无 prettier、无自研结构门禁）；代码内 TODO/FIXME 全库仅 2 处 |
| 打包 | PyInstaller onedir（127MB 量级）+ Cython 热点 + `--package-smoke` | Electron Forge + Inno Setup（WiX 回退有事故注释）+ 自研更新器（GitHub Releases+SHA256+2GB 上限）；仅 darwin-arm64/win32-x64 |
| 加速 | Cython 4 热点模块 | napi-rs canvas、ufbx 编译 WASM、离屏渲染窗口 |

---

## 六、项目健康

- **Serpent**：7 周 1,268 commits（月活 522→746，单人主导 98%），6 个 tag，README 双语+9 篇用户手册+扩展手册 2,072 行+33 篇 ADR（dev 分支）+Docusaurus 官网；但 main 分支 README 链接的 developer 文档缺失、无 CI、43,822 行单文件被 94 个测试文件直接引用。
- **AssetManager**：长线项目，文档 371 篇（含冻结审计/ADR/证据账本体系）、13 job CI、多轮全库审计闭环；弱点是商城占比 62% 的功能重心偏移（上游方案核心判断）、文档数字漂移史（本轮已在修）。

---

## 七、净结论

### AssetManager 的护城河（Serpent 完全没有）
1. **局域网分享门户**：权限模型/分享链接/移动端/隧道——这是产品级差异，不是功能差异。
2. **商城全链路**（但要警惕上游判断的"62% 偏科"）。
3. **工程治理面**：CI 矩阵、AST 分层门禁、i18n 三语全对齐、a11y axe 门禁、文档证据体系——Serpent 无 CI 无这些门禁。
4. 刚落地的撤销复合 entry + 90 天库内备份，在"安全网"上反超（Serpent 的 operation_history 支持跨端共享撤销，路线不同但目标相同）。

### Serpent 的护城河（AssetManager 没有的）
1. **专业深度**：RAW/EXR/PSD/3D(HDRI+PBR)/序列帧/色彩空间/音频波形——打的是 VFX/游戏美术腹地。
2. **自动化三件套 + MCP**：84 命令/幂等强制/计划审批/只读沙箱/风险注解——脚本化批处理可信度，AssetManager 的 T8 只是其子集。
3. **组织双轨**：合集+智能合集+评分——AssetManager 只剩标签单轨。
4. **检索深度**：FTS5 全文+高级语法+保存搜索（=智能合集）——T7 只补到结构化过滤。
5. **并发与性能工程**：租约/lane 准入/触发器变更序号/覆盖索引（NAS 实测数据）/内存预算。

### 对照此前"值得抄"清单的更新（serpent-reference-study §四）
| 项 | 状态 |
|---|---|
| 标签物理分表 | ✅ **已吸收**（T4，v36） |
| 自动化三件套 | 🔶 执行日志半吸收（T6=activity_log）；幂等+审批=T8，仍缓办 |
| 结构化检索 | 🔶 部分吸收（T7）；FTS 全文/高级语法/保存搜索未做 |
| 流式 ZIP / collections / gitignore / WebDAV / MCP / 任务租约 | ❌ 未做（原判断维持：WebDAV 看 NAS 用户占比、MCP 是高性价比替代 AI 的路线） |
| 序列帧/色彩空间/竞品迁移（Eagle/Billfish） | 新增候选——竞品迁移是"用户获取手段"（原研究 §2.5），值得排期评估 |
| **不该抄**：4.3 万行单文件、Electron 重写、内置 AI 分析模块（接 API+MCP 才是路线）、商城链路 | ✅ 判断不变，且本次清点强化（43,822 行文件波及 94 个测试文件） |
