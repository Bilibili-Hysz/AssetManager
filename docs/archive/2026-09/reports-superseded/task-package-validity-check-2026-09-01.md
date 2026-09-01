# 任务包时效性检验（2026-09-01 12:10）
> 状态:**已完结** · task-package-2026-09-01(v2)打包当时点的时效性检验快照 · 状态登记:2026-09-02(文档梳理轮补登)


> 检验对象：`docs/plans/task-package-2026-09-01.md`（凌晨 04:00 打包）
> 检验基线：HEAD 仍为 `be146da`（**无新提交**）／工作区 37 M + 27 ??（较凌晨 +2，为我新增的文档）
> 方法：提交时间线 → 关键文件 mtime → 源码行号重验 → 逐任务裁定。**仅静态复核，未运行测试。**

---

## 0. 结论先行

**任务包整体仍然有效，且是"活的"**：检验中发现它已被并行会话就地同步过（§1 速览表的 v44-v46/disposition 描述、B2/B5 的"已实施"状态、新增 B6 lease heartbeat 均为 04:00 之后写入，非我原稿）。因此本轮**不是判定失效，而是校准**。

| 裁定 | 数量 | 任务 |
|---|---|---|
| 🟢 **完全有效**（前提未变） | 14 | A1 A2 A4 A5 A6｜D1 D2 D3 D4｜C1 C2 C3 C4 C5 |
| 🟡 **有效但改法须修正**（本轮实质贡献） | 1 | **A3**：档位已存在（无需新增 media 档）→ 改为改挂既有 browse 档；且 `test_route_policy*` 已把 media skip 固化为契约断言，必须与代码同改 |
| 🔵 **已实现，任务包已标注**（并行会话同步，无需动作） | 3 | B2（canonical consumer）、B5（退避/v45 死信）、B6（lease heartbeat） |
| 🔵 **已实现，本轮补全标注** | 2 | B1（`reconciliation_queue.py:174-182,970-979`）、B4（v45 quarantine `store.py:1001`） |
| 🟠 **部分实现，剩余有效** | 2 | B3（退避参数已落地，**无后台调度**）、C6（README 已改，spec 未动） |

**总判定：**
1. **发布红线 A 批次零进展、改动区与并行会话零重叠** → 仍是当下最安全、优先级最高的施工面。
2. **B 批次仅剩 B3（后台 drainer）待写**，其余转"验证 + 提交"。
3. **A3 是本轮唯一需要修改改法的任务**，且发现一处会导致门禁红的隐藏依赖（测试契约）。

**已对任务包就地修订**：A3 改法替换、B1/B4 补状态标注（保留原文案为"原证据/原改法"以便追溯）。

---

## 1. 全局状态：无新提交，但工作区在快速膨胀

- **HEAD 未推进**：`be146da`（08-31 17:03）仍是最新提交 → 所有"已提交"的基线未变。
- **工作区改动重心已明确转向 H1 恢复一致性**（并行会话在跑）：

| 文件 | 改动规模 | 内容 |
|---|---|---|
| `application/import_manifest_store.py` | +1933 / -49 | manifest 存储重写 |
| `tests/unit/test_reconciliation_queue_sqlite_store.py` | +1599（新文件） | queue store 专测 |
| `application/reconciliation_queue.py` | +925 / -10 | disposition / consumer / backoff |
| `application/reconciliation_queue_store.py` | +895 / -27 | quarantine / dead-letter |
| `tests/unit/test_import_manifest_store.py` | +853（新文件） | manifest 专测 |
| `application/import_service.py` | +772 / -97 | 导入服务 |
| `core/db_migrations.py` | +109 | **v45 死信表 / v46 投递进避** |
| `core/schema_defs.py` | +193 | schema 契约 |

- **P0 相关文件 mtime 与凌晨完全一致**（`loader.py` 08-20、`auth.py` 08-29、`safe_open.py`/`security.py` 08-30 20:15、`server.py` 08-30 21:21、`api.py` 08-31 19:14、`spec` 08-31 04:33、`build.py` 08-20）→ **发布红线零进展**。
- 迁移版本已推进至 **v45 / v46**（工作区未提交）；README 未提交 diff 的 stats 已对齐 `schema_version=46`。

---

## 2. 逐项时效裁定

### 2.1 批次 A（发布红线）：🟢 完全有效，但 A3 需修正改法

| 任务 | 关键证据（本轮重验） | 裁定 |
|---|---|---|
| A1/A2 插件 | `core/plugins/loader.py:89,93` exec_module 未动（mtime 08-20） | 🟢 有效 |
| **A3 skip 限流** | `api.py:225,235,236,276,291,307,377` 仍挂 skip（`_SKIP`/`_PREVIEW_WRITE_SKIP`/`_PUBLIC_SKIP`/内联）；`security.py:186` skip 分支未动 | 🟡 **有效但改法须修正**（见 §3.1） |
| A4 流式读 | `lan/safe_open.py:54-60` 仍无 max_bytes（mtime 08-30 20:15） | 🟢 有效 |
| A5 密码令牌 | `domain/auth.py:155` `hmac.new(password_hash.encode(), ...)` 原样（mtime 08-29） | 🟢 有效 |
| A6 泄露/绑定 | 工作区无任何相关改动 | 🟢 有效 |

### 2.2 批次 B（恢复一致性）：🔴 4 项已被实现，1 项剩余

| 任务 | 当前实现（工作区，未提交） | 裁定 |
|---|---|---|
| B1 listener disposition | `reconciliation_queue.py:174-182` 定义 `ReconciliationTransitionDisposition`（APPLIED/STALE/RETRY）；`:970-979` 仅前两者 ACK，RETRY 不 ACK | 🔴 **已实现** |
| B2 consumer group | `reconciliation_queue.py:784` "Set the sole consumer whose disposition may acknowledge outbox rows" | 🔴 **已实现**（取"仅服务一个内建 consumer group"方案） |
| B3 后台 drainer | 退避参数已落地：`reconciliation_backoff`（`:2335`）、`next_attempt_at`（`:2106`）、v46 迁移；**但 `drain_transition_outbox` 仅 5 处被动调用**（`:461,820,888,1324,1378`，均在 mutation/注册/显式 recovery 时），**无独立后台调度** | 🟠 **剩余有效** |
| B4 poison 隔离 | `reconciliation_queue_store.py:1001` 明确使用 **v45 quarantine**；`:963` 限制单次 claim 的 poison 扫描量 | 🔴 **已实现** |
| B5 退避/死信/ACK 清理 | `db_migrations.py:1146` v45 死信表、`:1160` v46 投递进避；`max_attempts`（`queue.py:272`）、`dead_letter`/`next_delivery_at`（`store.py:209,216`） | 🔴 **已实现** |

### 2.3 批次 D（收尾与治理）：🟢 全部有效，D1 更紧迫

| 任务 | 当前状态 | 裁定 |
|---|---|---|
| D1 WIP 收尾 | 工作区 37 M + 27 ??；改动规模较凌晨显著扩大（见 §1 表） | 🟢 有效，**紧迫性上升** |
| D2 MCP 限流 | `lan/mcp_server.py` 存在（08-31 20:34）；`api.py:255-256` 注册 `/mcp`，policy 未显式声明 rate_limit | 🟢 有效 |
| D3 U-6 写路径触发 | `thumbnail_service.py` / `library_governance.py` **未被改动**（不在 M 列表） | 🟢 有效 |
| D4 新功能审计 | AI 打标/relink/commands 已提交（`37cfc56`…`be146da`），仍无安全审计记录 | 🟢 有效 |

### 2.4 批次 C（结构性）：🟢 有效，C6 部分推进

| 任务 | 当前状态 | 判定 |
|---|---|---|
| C1 DI 收敛 | 无相关改动 | 🟢 有效 |
| C2 domain→core 反依赖 | 无相关改动（`domain/events.py:11` 仍在） | 🟢 有效 |
| C3 巨文件拆分 | 无相关改动；**注意** `reconciliation_queue.py` 正膨胀至 2000+ 行，成为新的拆分候选 | 🟢 有效（范围应新增此文件） |
| C4 类型补全 + spec/Cython | `AssetManager.spec:177-182` 幽灵模块未动；`build.py` 0 处 cython | 🟢 有效 |
| C5 webui undo | `grep -rli "undo" webui/src` **0 命中**（桌面端 `e974a17` 的撤销历史面板 ≠ webui） | 🟢 有效 |
| C6 文档收敛 | README 未提交 diff 已含 ADR 0005 商城剥离声明 + stats 对齐 v46；**spec 幽灵模块未动** | 🟠 部分推进 |

---

## 3. 需要修订的三处（任务包已同步更新）

### 3.1 A3 改法修正：从"新增 media 档"改为"改挂既有 browse 档"

- **新发现**：限流档位基础设施**已经具备三档**——`auth_strict`（`api.py:137-139`）、`browse`（`:163-164`）、`skip`（`:134-136`），语义见 `security.py:181-182` 注释，处理分支在 `:282`（auth_strict）与 `:297-300`（browse）。
- **修正**：原方案"新增 media 档（2000/60s/IP）"不必要，直接把 7 条 skip 路由改挂 `_BROWSE` 系档位即可，工作量减半。
- **⚠️ 新增前置依赖**：`tests/lan/test_route_policy*.py:26` 断言注释 "only media/status polling stays skip-open"、`:81` 返回 `"skip"` —— **测试契约已把 media 保持 skip 固化**。改 A3 必须**同步改该文件**，否则 `check_route_capabilities` 门禁红。这是原方案未识别的隐藏依赖。
- A3 方案 B（PBKDF2 前置"格式预检 + 失败计数桶"）前提仍在：认证流程 `server.py:1125-1140` 为 revoked→access_key→local_ui 顺序，预检位未加。

### 3.2 B 批次校准：任务包已被并行会话同步，本轮补全 B1/B4 两处缺失标注

- **并行会话已同步的**：B2（canonical consumer 最小模型已实施）、B5（`next_delivery_at` 指数退避 + 八次尝试 + v45 dead-letter 已实施）、**B6（delivery lease heartbeat 已实施，为 04:00 后新增条目）**。
- **本轮补全的**（任务包中仍为"待改"文案，易造成重复劳动，已就地改为"已实施 + 转验收验证项"）：
  - B1 → `reconciliation_queue.py:174-182` 定义 disposition 三态、`:970-979` 仅 APPLIED/STALE 放行 ACK；
  - B4 → `reconciliation_queue_store.py:1001` 显式使用 v45 quarantine、`:963` 限制单次 claim 的 poison 扫描量。
- **唯一仍需新写代码**：B3 后台 drainer 调度——`drain_transition_outbox` 仅 5 处被动调用（`:461,820,888,1324,1378`，均在 mutation/注册/显式 recovery 时），无独立后台调度器。
- **流程含义**：B 批次的正确动作是"跑测试验证 → 补 H1 退出条件证据 → 提交 → 只补 B3"，而不是重做。

### 3.3 版本号与表述更新

- 任务包中"迁移 v44"应更新为 **v46**（v45 死信表、v46 投递进避）。
- C3 应把 `application/reconciliation_queue.py`（现 2000+ 行）纳入拆分候选清单。
- 9-01 复核报告对 H1 的定级（B1 为 P0）已被代码证实为准确判断——并行会话按同一方向推进。

---

## 4. 新增风险（本轮检验发现）

| 风险 | 说明 | 建议 |
|---|---|---|
| **R-新1 工作区改动规模失控** | H1 相关未提交改动累计约 7.5k 行（含 2.4k 新增测试），与 P0 批次 A 的改动区**无重叠**（不同文件），风险可控；但未提交时间越长，与并行会话冲突概率越高 | 优先提交 B 批次已完成项，缩短窗口 |
| **R-新2 测试契约固化 skip** | `tests/lan/test_route_policy*.py:26,81` 将 media skip 写成契约断言 | A3 必须同步修改该文件（见 §3.1） |
| **R-新3 巨文件新生** | `reconciliation_queue.py` 由 ~1400 行膨胀至 2000+ 行，在"拆巨文件"任务进行中反向增长 | C3 纳入该文件；H1 收尾即拆 |
| **R-新4 版本号漂移** | README/任务包/复核报告中的 schema 版本（42/44/46）分散在多处未提交文档 | 提交时统一以 `db_migrations.py` 实际最高版本为准 |

---

## 5. 修订后的执行建议

1. **批次 A 优先级不变且为最高**：P0 五项零进展、改动区与并行会话**零重叠**，是当下最安全的施工面。执行顺序 A3（注意同步测试契约）→ A4 → A5 → A6 → A1 → A2。
2. **批次 B 改为"验证+提交"**：先跑 `tests/unit/test_reconciliation_queue*.py`、 `tests/unit/test_import_manifest_store.py`、 `tests/integration/*`，确认 H1 退出条件达成后提交，再补 B3 后台调度。
3. **批次 D 提前**：D1（收尾）与 D2（MCP 限流定型）宜在 B 批次提交时一并处理，减少提交批次。
4. **批次 C 保持穿插**：C5（webui undo）与 C4（spec 幽灵）为低成本项可先行。
5. **下一轮检验触发条件**：HEAD 推进（新提交出现）或工作区 M 文件数显著变化（>45 或 <20）时重新核验。

---

*本检验为任务包 v2 的时效性复核。任务包 `docs/plans/task-package-2026-09-01.md` 已按 §3 同步修订（B 批次标注状态、A3 改法替换、版本号更新）。*
