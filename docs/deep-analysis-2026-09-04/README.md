# AssetManager 庖丁解牛 · 全库深度分析（2026-09-04）

> 状态：**DATED SNAPSHOT（2026-09-04 全库深读）** · 本目录是该日"庖丁解牛"式全项目深度分析的完整交付物。
> **方法**：主会话自营入口链/窗口装配/面板挂载层实读 + **7 个并行只读勘察代理**分域全覆盖（core / domain+repositories / application / lan / webui / 质量工程 / dialogs+widgets+i18n），代理报告经主会话整合重写为编号文档；所有规模数字为当日本工作树 `wc -l`/`find` 实测，所有机制描述附 file:line 锚点。
> **验证边界**：本文系是静态勘察快照，不是运行验证；运行结果结论仍以 dated evidence（commit+命令+平台+digest）为准。

---

## 目录

| # | 文档 | 覆盖域 | 规模实测 |
|---|---|---|---|
| 01 | [01-core.md](01-core.md) | core/ 基础设施（数据库/迁移/锁/路径/主题/图标/并发/插件宿主） | 44 文件 · 15,005 行 |
| 02 | [02-domain-repositories.md](02-domain-repositories.md) | domain/ 值对象+事件+密码学 + repositories/ 12 SQL 仓库 | 8+14 文件 · 7,187 行 |
| 03 | [03-application.md](03-application.md) | application/ 应用服务层（装配链/对账队列/导入导出/undo/gallery） | 60 文件 · 37,268 行 |
| 04 | [04-lan.md](04-lan.md) | lan/ aiohttp 分享服务器（认证/限流/WS/隧道/72 路由） | 46 文件 · 12,624 行 |
| 05 | [05-webui.md](05-webui.md) | webui/ React 18 SPA（api 工厂/Context store/WS 游标/E2E） | 105 ts/tsx · 14,548 行 |
| 06 | [06-engineering.md](06-engineering.md) | 质量工程（tests 324 文件 / CI 3 工作流 / 构建管线 / 13 门禁） | tests 97k+ 行 |
| 07 | [07-desktop-ui.md](07-desktop-ui.md) | 桌面 UI 剩余（dialogs 32 / widgets 19 / i18n / background / panels 辅助） | 9,356+6,764+784 行 |
| 08 | [08-entry-and-window-assembly.md](08-entry-and-window-assembly.md) | 入口链 / MainWindow / dock_factory / 窗口生命周期协调 | 主会话自营实读 |

主包总计：**288 个 .py，109,842 行**（另 webui 105 个 ts/tsx、tests 324 个 test 文件）。

---

## 1. 一张图看懂全库

```
main.py ─ faulthandler + 日志
└─ app.py main() ─ 单实例锁(fail-open) → ApplicationBootstrap(DI) → 托盘 → StartupWindow
   └─ MainWindow (LanSharingMixin + QMainWindow)                    ← 08 号文档
      ├─ 中央画布 FileListPanel（5 mixin + 5 面板 + 网格渲染子系统）
      ├─ dock_factory：PANELS 注册表挂 sidebar/info/tag_tree/image_viewer/empty
      │   └─ 插件 dock 动态挂载（tool_windows）
      │
      │  ┌─ 应用层（每库 LibraryRuntime 作用域）                      ← 03 号文档
      │  │   bootstrap → runtime_for(session) → LibraryScopedServices(frozen)
      │  │   ├─ 资产域：tag/metadata/thumbnail/favorite/search/collection
      │  │   ├─ 对账域：reconciliation queue（世代 CAS + lease + outbox + 死信）
      │  │   ├─ 导入导出域：import manifest（claim/lease）+ export/restore 预约
      │  │   ├─ undo（90 天备份 + 投影快照 + 毒化条目）
      │  │   └─ 分享认证域（每 Runtime 独享 token_secret）
      │  │
      │  ├─ repositories（12 个 SQL 仓库）                            ← 02 号文档
      │  │   统一 for_session 绑定 + SAVEPOINT + CAS + guarded_commit
      │  │   （三套会话方言并存——已识别技术债）
      │  │
      │  ├─ domain（零基础设施）                                       ← 02 号文档
      │  │   15 个冻结领域事件 + 同步 EventBus + 值对象 + 纯密码学
      │  │
      │  └─ core（基础设施）                                           ← 01 号文档
      │      DatabaseManager（每库单连接 + 读写门 + 身份标记）
      │      db_migrations v46（savepoint 原子 + 历史不可变）
      │      LibraryLock（fail-closed PID 探测）/ PathGuard / 主题 / 图标
      │      插件宿主（ContextVar 门禁——诚实边界非沙箱）
      │
      ├─ LAN 服务器（同进程 aiohttp，构造强制 runtime=）               ← 04 号文档
      │   72 路由 + security→metrics→auth→error 中间件链
      │   六 principal / HMAC 令牌 / 撤销三层 fail-closed
      │   WS 50 连接 + epoch/revision 失效推送（HTTP 快照为权威）
      │   PathGuard + Pillow verify 内容门 + 模糊门 + Cloudflare 隧道
      │
      └─ webui/dist（React SPA，pages.py 托管）                       ← 05 号文档
          4 个运行时依赖 / 双 Context store / 自研 query cache
          epoch+revision 缺口恢复 / contract golden 测试
                                                              质量工程 → 06 号文档
```

---

## 2. 全库实测数字 vs README 声明（交叉校验）

| 项 | README/文档声明 | 2026-09-04 实测 | 判定 |
|---|---|---|---|
| 主包规模 | 270 py / 9.2 万行（08-27） | **288 py / 109,842 行** | 漂移（增长） |
| application | 52 模块 / 2.77 万行 | **60 文件 / 37,268 行** | 漂移 |
| core | 34 模块 | **44 文件 / 15,005 行** | 漂移 |
| lan | 核心 16 模块 | **根目录 22 个 .py + routes 22** | 概数过时 |
| repositories | 12 个（架构图却写 17） | **12 个仓库 + _common** | ~~README 内部自相矛盾~~ 已修正（架构图改 12，2026-09-04） |
| panels | 38 文件 | **39 文件 / 17,656 行** | 基本一致 |
| dialogs | 24 个 | **26 顶层 + 6 分包** | 漂移 |
| 测试 | 283 文件（分域 106/55/54/35） | **325 文件（115/63/51/63/17/12/2/2）** | 正文已改实测值；stats 行 --fix 同步（09-04） |
| 迁移版本 | v46 | **v46**（db_migrations.py:54） | ✅ 一致 |
| 路由数 | 72 | **72**（api.py _add 实测） | ✅ 一致 |
| i18n | 1060 keys × 3 | **1060 × 3 完全对齐** | ✅ 一致 |
| 图标 | 56 | **48 基础 + 10 别名 = 58 命名** | 口径不明（stats 行自有口径） |
| schema 契约 | — | **44 张表** | — |
| webui 测试 | 103 Vitest | **89 个 .test + 3 Playwright spec** | 死 spec 已删（2026-09-04，见 05 §4 附注） |
| build 命令 | `--optimize` | **参数不存在** | ~~已修正~~（README 09-04） |
| Cython | 4 个热点模块 | **8 个 core 模块** | ~~已修正~~（README 09-04） |

> **2026-09-04 修正执行记录**：上表"已修正"项由方言统一 P0 批次落地（`docs/plans/dialect-unification-plan-2026-09-04.md` §P0）——README 架构图/命令/分域数字校正、stats 行经 check_doc_stats --fix（e2e_specs 6→3、python_test_files 324→325）、三个死 commerce spec 删除、`tr(default=)` 幻觉参数转正（71 处调用点获得真实回退）。

---

## 3. 全库跨层发现（每份文档的弱点清单汇总）

### 3.1 高优先级（正确性/一致性）

1. **webui 三个商城 E2E spec 是死测试**（05 §4）：`/seller`、`/storefront/*` 路由已随 ADR 0005 商城剥离移除，spec 仍会导航到 NotFoundPage 而失败——当前工作树最明确的不一致。
2. **`tr(key, default=...)` 幻觉参数**（07 §4）：i18n.tr 不识别 default，全库 6+ 处依赖不存在的回退，缺键时 UI 显示原始点号键名。
3. **文档数字大面积漂移**（06 §9 / 04 §11 / 02 §8）：`build.py --optimize` 参数不存在（README 命令会报错）；lan-security.md 仍描述已剥离的 shop 路由；README 分域测试数、"17 个仓库"vs"12 个"等矛盾。check_doc_stats.py 守护的是 stats 行，正文数字不在其管辖内。
4. **仓库层三套会话绑定方言 + 100 行样板 × 4 文件复制**（02 §8 W-2/W-3）：同一契约三份实现，且 `_CommerceRepository` 基类已存在却只有 1 个使用者。

### 3.2 结构性技术债（已识别、受控）

5. **超大模块 Top-6**：reconciliation_queue.py 2733 行（102 def）、reconciliation_queue_store.py 2591、import_manifest_store.py 2557（双类同文件）、settings_dialog.py 2052、schema_defs.py 1975、database.py 1610；settings_dialog 是桌面侧巨石（07 W4）。
6. **HTTP 自环分层**（07 W2）：SharingSettingsDialog 用 requests 打自己进程内的 LAN 服务器——应有进程内端口直调。
7. **6/12 仓库无 for_session 绑定**（02 W-4）：thumbnail/favorite/gallery_home/revoked_token 仅 raw conn；raw 通道根校验是空操作（W-5）。
8. **LAN 读路由能力单层**（04 §11）：写面已声明 capabilities，读面靠 handler 守卫——handler 忘写即 fail-open。
9. **语言热刷新覆盖不全**（07 W3）：多个对话框未声明 supports_runtime_refresh，语言切换后已开窗文案冻结。
10. **CI 执行面缺口**（06 §9）：perf 门禁默认排除、Windows 全量从不在 Windows 跑、e2e 仅 2 文件、无 pytest 超时、无 Python 覆盖率门禁、release gate 与 test 矩阵口径分裂。
11. **i18n 三语对齐靠纪律非机制**（07 W12）；webui 侧 en 比 zh/ja 少 2 个 leaf key（05 §8-6）——桌面/前端是两套词典。
12. **_common.py 商城遗产**（02 W-6）：类名/docstring/迁移 v11-v25 全为 shop 系，运行时已剥离。

### 3.3 值得肯定的全库共性（多份报告独立得出同一结论）

- **fail-closed 贯穿**：撤销读取失败即拒、模糊处理失败即 500、TLS 缺一半即拒、未知路由即 required、邀请码查询失败即关闭注册、PID 探测不出即当活锁、AI 标注非 True 即关——分布在 01/02/03/04/07 五个域。
- **持久化诚实**：目录 fsync（Windows ctypes）、标记发布后永不回收、"无法证明已释放就不谎报成功"。
- **有界一切**：全部缓存/队列/记录器/注册表都有上限或修剪策略（200 任务队列、1024 backlog、4096 图标缓存、50 WS 连接、500 relink 行、256 undo 目录）。
- **每处并发契约都有书面锁序注释**：_LanServicesHolder、gallery close、migration 读路径——高强度并发代码的可维护性投资。
- **诚实边界哲学**：undo 面板不假装回收站、_PLANNED_ONLY_SETTINGS 明示未接服务端、插件门禁自称"诚实边界非沙箱"。
- **防漂移机制机械化**：棘轮账本、门禁自测、golden contract、frozen_history_signature、gen_ts_types --check。

### 3.4 建议重构方向（按投入产出排序）

1. 删除 webui 三个死 commerce spec + 清理 storefront CSS/i18n 残迹（半天，消除最响的红）。
2. 修 i18n.tr 支持 default 或删除全部幻觉用法（小改动，防用户看到原始键名）。
3. README 数字与实现校准（--optimize 命令、分域计数、17→12 仓库）+ lan-security.md 商城段落归档标注。
4. 仓库层统一到 RootIdentity 方言 + 提取共享基类（消 4×100 行样板；中期）。
5. SharingSettingsDialog 改进程内端口直调，消 HTTP 自环（中期）。
6. reconciliation 三件套按 gallery 的"门面+子包"模式拆分（长期）。

---

## 4. 各层速查

| 想了解 | 去处 |
|---|---|
| 启动流程/单实例/开库/退出编排 | [08-entry-and-window-assembly.md](08-entry-and-window-assembly.md) §1、§4 |
| dock 挂载协议/拆分克隆/合帧刷新 | 同上 §3 |
| SQLite 单连接读写门/身份标记 | [01-core.md](01-core.md) §2.1 |
| 迁移体系（v46/历史不可变/savepoint） | [01-core.md](01-core.md) §2.2 |
| 15 个领域事件与投影域映射 | [02-domain-repositories.md](02-domain-repositories.md) §2.4 |
| CAS 的五类实例代码 | 同上 §4.3 |
| 每库服务装配链/LAN 惰性投影 | [03-application.md](03-application.md) §2 |
| G17 对账队列（cutover/lease/stale-worker） | 同上 §3.2 |
| LAN 认证六 principal/令牌撤销/限流四档 | [04-lan.md](04-lan.md) §3-§4 |
| 32 项安全机制锚点表 | 同上 §10 |
| 前端 WS 缺口恢复协议 | [05-webui.md](05-webui.md) §3.3 |
| 三套 mock 词表与 hex 棘轮 | 同上 §5-§6 |
| CI 9 job/发布纪律/缺口 | [06-engineering.md](06-engineering.md) §3、§9 |
| 门禁脚本 13 个的职责 | 同上 §5 |
| 对话框基类/设置六页/共享设置 | [07-desktop-ui.md](07-desktop-ui.md) §2 |
| 插件宿主 ContextVar 门禁 | [01-core.md](01-core.md) §2.9 |

---

## 5. 本文档系的使用与维护约定

- 本目录为 **DATED SNAPSHOT**：与 `docs/overview-2026-08-27.md`（结构地图）、`docs/reports/`（dated 复核）构成三层文档体系；引用本系数字时请注明"2026-09-04 实测"。
- 各文档弱点清单的编号（W1/W-2/…）在各文档内局部有效，跨文档引用请带文档号。
- 后续仓库演进后，以同方法重跑实测（7 域并行代理 + 主会话自营）刷新本系，不要在旧快照上局部改写。

*生成于 2026-09-04 · 主会话：ZCode（f9f55210）· 勘察代理：7 并行 Explore*
