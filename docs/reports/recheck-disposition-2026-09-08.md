# 复核处置报告（2026-09-08）

> 对象：[周任务修复复核](weekly-recheck-2026-09-08.md)（R1–R5）· 处置源码：**`0937a95`**（基于 `dc6bb46`）
> 执行：本会话代理。逐项复现 → 定位 → 修复 → 验证；证据归档于 [evidence/](recheck-disposition-2026-09-08-evidence/)。
> 门禁：全量 xdist **5065 passed / 0 failed / 20 skipped**（[junit](recheck-disposition-2026-09-08-evidence/full-suite-r16.xml)）；13 项静态门禁全绿（ruff / pyright 增量零新增 / doc / i18n / dialects / boundaries / route-capabilities / contracts / style×3 / frontend-fetch）。

## R1 · [P1] 集合/隐私门禁 — ✅ 已修复（产品缺陷，非测试前提问题）

**根因**：`CollectionService._require_event_safe_transaction` / `TagService._require_event_safe_transaction`
在**未持有连接写锁**的情况下窥视 `conn.in_transaction`。LAN 对账 worker（`asset-reconciliation-*`
线程）在共享会话连接上执行短促 `BEGIN…COMMIT` 轮询事务；当该窗口与用户变更重叠时，守卫把
**别的线程的事务**误判为"调用方外部事务"，抛出 `RuntimeError: mutations require a clean transaction
boundary`。这是随机器负载浮动的**生产缺陷**（LAN 侧表现为随机 500，桌面侧表现为随机错误弹窗），
此前仅以"测试里禁用对账 worker"（`test_file_operation_service.py` 的 autouse fixture）掩盖。

**修复**（`0937a95`）：两处守卫改为在 `db_write_lock(repo._conn)` 下采样 —— 与
`FileOperationService._clean_transaction_boundary` 既有配方一致；守卫采样之后才开启的事务仍由
仓库侧 `_write_scope(require_clean_transaction=True)` 在锁内兜底拒绝。错误文案保持不变。

**隐私 e2e 2 项处置**：
- `test_real_browser_namespace_and_private_thumbnail_headers`：失败原因为冷启动缩略图批次
  （读取+渲染+base64）超过固定 500ms 等待 —— Playwright 探针实测 2–5s。改用
  `wait_for_function` 等待 sessionStorage 持久化本身，断言不变。
- `test_intermediary_only_caches_explicit_public_thumbnail_responses`：代码库中已无
  `public, max-age=3600` 任何发射点；现行隐私合同为**所有缩略图响应一律
  `private, no-cache`/`no-store`**（模糊策略每次交付时重查，共享缓存不得复用）。按
  复核指引修正测试而非弱化服务端：断言两次 GET 均为 `private, no-cache` 且代理
  upstream=2 / hit=0，测试更名为 `test_intermediary_does_not_cache_any_single_thumbnail_responses`。

**验证**：最小复现对（iron-law → publishing）修复前 5 跑 4 败，修复后 **10/10 + 8/8 通过**
（[r1-stress-pair.txt](recheck-disposition-2026-09-08-evidence/r1-stress-pair.txt)）；
gen_ts_types + 集合 + 事件发布 + 标签绑定组合 48 passed；file_operation 66 passed；
privacy e2e **3/3 passed**。

## R2 · [P1] 切库探针 — ✅ 已重写（并修出一个真实线程泄漏）

`scripts/perf/w3_switch_roundtrip.py` 按关闭条件重写：
- **真实 A→B→A ×10 轮 = 20 次切换**（原实现仅 10 次切换且输出虚标 20）。
- 每次切换：真实 `LanServer`（密码鉴权 + SecurityPreflight）服务当前库 → 发起**在途 HTTP
  请求**跨越切换边界（必须有界应答，不许悬挂）→ 旧 session 有界等待关闭 → 新库服务器
  `/api/files` 必须列出新库文件且**不含旧库文件**（旧会话数据失效）。
- **失败非零退出**；`--self-check` 注入必然失败的标记，验证失败确实能被上层识别
  （注入未上报则自检自身退出 1）。
- **监听与任务回收**：线程与事件总线监听数在全部拆除后待稳定再计数。
- `AM_RUNTIME_ROOT` 隔离 —— 原实现会把持久化设置里的用户真实库卷进运行（本次运行中实际出现
  `F:\Blender`，已封堵）。

**顺带实锤并修复**（[r2 过程证据](recheck-disposition-2026-09-08-evidence/w3-switch-final.txt)）：
`lan/utils.py::_enumerate_private_ips` 每次调用孵化一条 `gethostbyname` 解析线程，Windows 解析器
对网卡名可阻塞远超 2s join —— 每次服务器启动泄漏一条守护线程（21 次启动 = 泄漏 21 条，探针
线程数 4→28 实测）。修复为单飞（in-flight worker 复用），稳态不随启动次数增长。

**验证**：探针 EXIT=0，20/20 切换全过、在途请求 20/20 应答、线程 4→**2**（回收彻底）、
监听 3→**0**；self-check EXIT=0（注入失败被上报）。

## R3 · [P2] W4 编码 — ✅ 已修复

`scripts/perf/w4_restore_drill.py`：父进程 stdout/stderr `reconfigure(encoding="utf-8")`，
子进程统一注入 `PYTHONIOENCODING=utf-8`。默认 GBK 控制台（不设环境变量）复跑：
**PASS，退出码 0**（[w4-default-encoding-after.txt](recheck-disposition-2026-09-08-evidence/w4-default-encoding-after.txt)）。
覆盖边界说明采纳复核表述：验证对象为 hero 标签/评分/备注、集合名称等代表字段的完整旧态恢复；
集合成员清单逐项核对、设置 UI、其余中断边界、损坏备份与不可写场景仍未覆盖，登记为后续。

## R4 · [P2] W5 断言 — ✅ 已强化（选择补齐容量证据路线）

`scripts/perf/w5_lan_resource_probe.py`：
- **批量缩略图**：50/50 全成员必须返回，且每张 base64 解码为真实 ≤256px PNG（原 `>0` 断言废除）。
- **单文件下载**：100 个文件全字节比对源文件（原仅长度）。
- **ZIP**：`testzip()` CRC 全过 + 20/20 成员齐全 + 逐成员字节等于源文件（原仅 PK 前缀）。
- **取消/回收**：新增 192MB 下载目标，客户端读 1MB 后中断 —— **确实仍在发送**的受控慢客户端；
  记录中断窗口、事后健康检查、取消后 RSS、全字节复下载验证（原 256 字节即关 + 仅健康检查废除）。
- **资源观测**：100ms 守护采样器捕获**请求期 RSS 峰值**（非仅阶段后点采）；事件循环心跳记录
  最大调度迟滞。
- **JSON**：`results.json` 增独立 `rss` 块（`budget_mb`、`peak_during_request_mb`、
  `event_loop_max_lag_ms` 等）与顶层 `verdict`（`bounded` / `unbounded-growth` / `invalid`）——
  消费方不再需要从 `valid` 或退出码推断预算结论。

**验证**：EXIT=0，50 项全解码、20 成员全比对、192MB 慢客户端中断后服务健康且复下载逐字节一致；
RSS 请求期峰值 137.7MB、重复批次增长 0.1MB、事件循环最大迟滞 127.2ms、verdict=bounded
（[w5-final.txt](recheck-disposition-2026-09-08-evidence/w5-final.txt) ·
[results.json](recheck-disposition-2026-09-08-evidence/w5-results.json)）。
范围声明：本轮负载仍为合成小图 + 单 192MB 大对象；大图慢读/持续并发 ZIP 容量边界仍属后续。

## R5 · [P2] 报告修订 — ✅ 已执行

- [w6-package-smoke](performance-audit-2026-09-06/w6-package-smoke.md)：状态降级为
  "启动冒烟通过、包内功能验收未完成"，撤回"四种模式全部可交付"；缺口（哈希绑定、包内开库/
  LAN/实时/首次延迟依赖取证）在文中显式登记。
- [weekly-report-2026-09-07](weekly-report-2026-09-07.md)：历史快照保持原文，顶部加修订头列明
  六项被取代/修正的声明（含 ~8017 重复累加计数）。
- [weekly-result-2026-09-13](weekly-result-2026-09-13.md)：活文档全面改版 —— 版本绑定更新、
  计数改为去重实测、断链修复、W2/W5/W6 状态按本轮证据改写、通过/失败/延期/未运行分列。

## 第三轮复核处置（F1–F5，2026-09-08）

对象：[第三轮质量复核](weekly-recheck-round3-2026-09-08.md)。全部代码/探针修复当日完成并验证：

### F1 · [P1] MetadataService 同根因竞态 — ✅ 已修复 + 全库扫查收口

- `metadata_service.py::_require_event_safe_transaction` 改为在 `db_write_lock` 下采样（与
  Collection/Tag 同配方），错误文案不变。
- **全库 `in_transaction` 锁外采样扫查**（同根因共三处，全部修复）：`asset_index_service.py`
  的 `index_directory_result` / `index_directory_tree_result` 的 `outer_transaction` 采样
  （误判会**静默跳过持久提交**）；`filesystem_projection_repair_service.py` `_require_committed`
  的提交决定（误判会**误提交他人事务**）。
- 确定性并发回归 `tests/integration/test_metadata_service_concurrent_boundary.py`（2 passed，
  Event 屏障控制、无 sleep 竞态控制）：worker 持锁干净完成 → 前台等待后成功、事件仅在提交后
  发布；worker 泄漏事务（不变量破坏）→ 前台 fail-closed 拒绝。
- 审计方复现脚本复核说明：其 `metadata_race_repro.py` 在修复后仍打印 REPRODUCED 系**脚本自身
  清理缺陷**——holder 超时异常路径跳过了 rollback（在 `with` 块内 raise），释放锁却留下未回滚
  事务；前台等待锁 6.01s 后对这个**真实泄漏事务** fail-closed 是正确行为。生产场景（holder
  干净完成）实证：前台等待 2.12s 后成功写入。
- 其余同类采样点（command_executions×3、file_operation×4、repair×2）核查确认均已在锁内。

### F2 · [P2] DNS 单飞结果丢失 — ✅ 已修复 + 确定性单测

`_enumerate_private_ips` 重写为共享 flight 对象：worker、结果容器、完成状态同属一个 flight，
跟随者 join 后读取同一容器（并发等待成功）；worker 结束后下一次调用开启新 flight（完成后重新
枚举）。回归 `tests/unit/test_lan_utils_enumeration.py`（3 passed，合成网卡 + Event 门控，
无真实网络）：并发等待成功 / 超时后仍复用同一线程 / 完成后重新枚举。

### F3 · [P2] W5 指标归属 — ✅ 已修复

- 心跳双轨：客户端 loop 与 **LAN 服务器自身后台 loop**（`run_coroutine_threadsafe` 于
  `server._loop`）各记一条，JSON 分别输出 `client_loop_max_lag_ms` / `server_loop_max_lag_ms`；
  实测 server 183.5ms / client 566.7ms（客户端迟滞包含探针自身哈希/写盘，如实分开呈现）。
- 取消取证读取改为累计至目标字节数，记录实际 `aborted_after_bytes`（不再把读取上限当已收字节）。
- 重试改为**同一大对象流式重下**并 SHA-256 校验（不整块缓冲，避免污染被测 RSS）；源哈希同样
  流式计算（第一次运行时采样器抓到 325.4MB 客户端峰值，即为整块读入所致，已改）。
- 范围声明维持：服务器侧任务计数/在途额度/临时文件未在 LAN 状态接口暴露，`cancel_reclaim_ok`
  的证据边界为"健康恢复 + 同对象完整重试 + RSS 无增长"，服务器侧回收计数器仍属后续。

### F4 · [P2] W3 场景缺口 — ✅ 已补最小集成场景

- **旧服务入口失效断言**（每次切换）：切库后向旧 harness 发起请求，旧端点必须不再返回 200 旧库
  数据。实测 20/20 干净失效（连接拒绝 —— 应用在 session 关闭时自行拆除旧服务器）。
- **活动下载跨切换**（F4 最小场景）：128MB 大文件下载跨越切换边界，有界应答且完整返回
  134217728 字节（无截断、无悬挂）。
- 服务器侧进入屏障（保证请求已进入目标处理阶段）仍未实现，如实登记；50ms 错峰 + 在途观测
  （审计方 `observe_switch.py` 已独立证实请求线程跨越切换）为当前证据。

### F5 · [P2] 报告收口 — ✅ 已执行

- 周汇总范围表述改为实际（09-07 完成 W1–W5 + 汇总，W6 当日仅启动冒烟）；W2 失败归因措辞修正。
- `../performance-audit-...` 断链全部改为同级目录相对路径（复查 0 残留）。
- 证据交付：`.gitignore` 全局 `*.log` 曾吞掉证据日志，已按审计方 `.txt` 约定改名入库
  （处置证据 5 件 + W6 功能证据 + 哈希清单）。
- W6 候选包重绑定：F1/F2 生产修复之后，重建双模式包并**重跑四变体包内功能验收**（新增备注
  评分取证项），哈希清单绑定处置后源码 —— 见 [W6 报告修订 3](performance-audit-2026-09-06/w6-package-smoke.md)。

## 处置后仍开放的事项

| 事项 | 归属/条件 |
|---|---|
| ~~frozen 包内功能验收（开库/LAN/实时/首次延迟依赖 + 哈希绑定）~~ | ✅ 09-08 当日补齐：四变体全 PASS + [哈希清单](performance-audit-2026-09-06/evidence/w6-package-hash-manifest.json)，[W6 报告](performance-audit-2026-09-06/w6-package-smoke.md)第二次修订恢复可交付结论 |
| W4 覆盖扩展（集合成员逐项、设置 UI、损坏备份、不可写场景） | 后续批次 |
| W5 容量边界（大图慢读、持续并发 ZIP、p95 容量曲线） | 后续批次 |
| `test_viewer_opens_psd_through_media_decoder` xdist 高负载偶发（隔离绿，本轮全量第二次运行已过） | 登记观察 |
| 真机验收十六步走查 / M1 观感评审 | 用户 |

无证据即 unverified——本文档自身也是这个纪律的适用对象。
