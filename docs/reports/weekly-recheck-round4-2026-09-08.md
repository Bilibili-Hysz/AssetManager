# 第四轮独立复核（2026-09-08）

> 对象：[09-08 周报](weekly-report-2026-09-08.md)、[自深度审查](self-review-2026-09-08.md)。按连续复核理解本轮文件提交，报告中的指令及完成声明仅作审核材料。
> HEAD：`817419a2f23b1b60a0c3fc2783e31833b7d293e0`；本轮主要代码提交 `68ab0e4`，此后 AssetsManager / WebUI / tests 无变化。开始时工作树干净。
> 结论：**主要修复通过，可以进入明确范围的合成库/测试库试用；“全部 P1/P2 关闭、完整包验收完成”仍表述过满。** 本轮未确认新的普通对账 worker 误拒问题，发现一处 P2 事务边界防护遗漏，另需补包状态断言与证据同步。

## 1. 已通过的独立核查

| 项目 | 结果与证据 |
|---|---|
| Metadata / DNS 新增回归 + 集合与元数据集成组合 | **45 passed，19.56 秒，退出 0**：[JUnit](weekly-recheck-round4-2026-09-08-evidence/targeted.xml)、[输出](weekly-recheck-round4-2026-09-08-evidence/targeted.txt) |
| 真实对账 worker 下守卫压测 | **50 轮，0 误拒、0 其他错误**；worker running=True，退出 0：[输出](weekly-recheck-round4-2026-09-08-evidence/guard-stress.txt) |
| 候选包及 WebUI 哈希 | 对用户清单逐项复核 **286 个文件，0 不匹配**：onefile 1、onedir 262、WebUI 23；[核对结果](weekly-recheck-round4-2026-09-08-evidence/package-hash-check.json) |
| 用户归档 r17 全量 JUnit | XML 为 tests=5090、failures=0、errors=0、skipped=20，即 **5070 passed**。本轮核查原始 XML，未再跑全量 |
| W5 最新探针独立运行 | **退出 0，当前断言通过**：客户端/服务器双循环心跳、实际取消量、同一大对象流式重试已实现；[输出](weekly-recheck-round4-2026-09-08-evidence/w5.txt)、[JSON](weekly-recheck-round4-2026-09-08-evidence/w5-results.json) |

据此关闭上轮的正常 worker 事务被 MetadataService 误读，以及 DNS 跟随者丢失结果两个问题。新增 asset_index / projection repair 锁修改也经只读调用链复核，本轮未找到另一处可证实的新生产回归。

W5 本次实际取消读取 **1,102,848 字节**，同对象重试 **201,326,592 字节**，大小与 SHA-256 相符；采样 RSS 峰值 **139.3 MiB**，重复批次增长 **0.1 MiB**，服务器循环最大迟滞 **347.7 ms**，客户端 **664.3 ms**。此处最大值不等同于 p95，不能直接用计划中的 p95 提案判定超限；`bounded` 仅对应脚本的重复批次 RSS 增长判据，不证明所有资源预算均通过。W5 在本轮其他动态验证结束后单独执行，未对整台机器所有背景负载作排除。

## 2. [P2] 元数据 guard 与实际写入之间仍有事务边界缺口

定位：`AssetsManager/application/metadata_service.py:254–255,291–294`；`AssetsManager/repositories/metadata_repository.py:139`；`AssetsManager/repositories/_common.py:334–354`。

MetadataService 在连接锁内确认没有事务后释放锁，随后才调用仓库写入。MetadataRepository 的写入调用没有设置 `require_clean_transaction=True`；若在此窗口出现仍开放的外层事务，仓库会保留它，服务却照常发布已变更事件。自审将三种服务一概描述为“仓库再次检查 clean transaction”，对 metadata 并不成立。

本轮用真实隔离 session、两线程与 Event 屏障复现：guard 先通过，另一个调用者持连接锁 BEGIN，离开锁范围却继续保留该外层事务；元数据写入成功、事件发布 **1 次**，随后该外层事务 rollback，备注从 `ephemeral` 变为空。[原始结果](weekly-recheck-round4-2026-09-08-evidence/metadata-guard-toctou.txt)、[观察脚本](weekly-recheck-round4-2026-09-08-evidence/observe_metadata_guard_toctou.py)。脚本退出 0 表示已复现边界缺口。

**触发限制必须保留：** 该演练依赖“释放连接锁却保留外层事务”的调用方式/不变量破坏。正常 reconciliation 在释放同一锁前 commit/rollback，不能触发此演练。因此这是 fail-closed 防线遗漏，不应重新描述为普通后台对账造成的随机误拒，也未量化生产发生频率。

建议：在服务需要发布事件的元数据写路径上，实现仓库锁内原子 clean-boundary 检查，或以适当的锁范围覆盖检查和写入；保留原始仓库对合法调用方事务的兼容语义，不要将所有 raw 写入直接改为强制提交。补 guard 后插入外层事务的测试，要求拒绝且无事件；再验证正常写入只在自身提交后发事件。

## 3. [P2] W6 的最大化与正常退出尚不能由现有探针证明

定位：`scripts/perf/w6_package_functional.py:78,143,292–323`。

包内开库、登录、字体、缩略图、备注评分读写与新增文件可见的证据有效；候选包哈希也确实匹配，应认可从存活检查到功能冒烟的进展。但以下判定仍越过了实际观测：

- `maximized` 仅来自命令行参数与种子 settings，JSON 没有主窗口实际最大化状态。即使程序忽略最大化恢复，只要 API 可用，也可 PASS。
- `taskkill /PID ... /T` 后等待 8 秒超时，直接写 `hidden_to_tray`；没有检查命令结果、窗口是否隐藏、托盘是否存在。挂住或关闭消息未成功送达也能走此分支。
- 四份归档 JSON 均为 `hidden_to_tray` + 强制结束码 1，没有正常应用退出、退出后重开或几何保存的验证。即使走正常退出分支，`geometry_persisted` 也只是记录，未把不满足持久化合同变为失败。
- 当前 `live_change` 是轮询目录接口发现新文件；不能替代 WebUI 订阅收到实时集合变化的验证。

建议补一个最小真实包闭环：记录主窗口实际最大化；验证隐藏/托盘恢复；通过应用的正常退出入口结束并重开，确认评分备注与窗口状态仍在。若短期不补，W6 状态应为“哈希绑定包内功能冒烟通过，窗口恢复/完整退出/实时前端待验收”。本轮未启动 GUI 包重新操作，因此不把这些证据缺口当成已确认包故障。

## 4. [P2] 回归测试与证据归档需要最后收口

### 测试合同

`tests/integration/test_metadata_service_concurrent_boundary.py` 收集了 `events`，但没有断言事件数、发布时的事务状态或独立连接可见性。当前测试只能证明操作等待后成功，不能证明自审声称的“事件仅在提交后发布”。负例在持锁线程等待 release 时调用服务，却直到 finally 才 set release，实际依赖 holder 自身 10 秒超时释放锁；不应描述为精确屏障控制的泄漏事务演练。

`tests/unit/test_lan_utils_enumeration.py` 的 follower 测试先 gate.set，再进入第二次枚举；worker 可能已完成，生产逻辑此时合法创建新 flight，却会被“必须同一 flight”的断言判失败。应先确认跟随调用取得同一 flight，再释放 resolver 屏障；不要将合法调度差异当产品回归。本轮 45 项都通过，以上是测试可靠性/覆盖缺口，未声称本轮发生测试失败。

### 版本与证据

- `recheck-disposition-2026-09-08-evidence/w5-results.json` 与 `w5-final.txt` 仍保存旧数据：`aborted_after_mb`、单项 `event_loop_max_lag_ms=127.2`。报告正文写双循环与同对象重试，链接却不对应。
- 本地 ignored `artifacts/perf/w5-lan-resources/results.json` 有更新的双循环运行，不能称“从未执行”；它记录峰值 325.4 MiB，仍是报告所说改流式源哈希前的运行。本轮已另行归档最新源码独立复跑结果，避免混用。
- `weekly-result-2026-09-13.md` 顶部仍写最终源码 `0937a95`，正文已写 `68ab0e4`；W2 行仍引用 r16/5065，另处使用 r17/5070。历史结果可保留，但应明确时点，提供唯一当前基准。
- W5 服务器任务数/额度/临时文件回收已明确登记后续，可接受延期；应使用“取消后健康与同对象重试通过”的名称，避免 `cancel_reclaim_ok` 被下游理解为资源回收证明。

## 5. 推荐下一步

1. **小范围修正元数据事件边界及对应测试**：先复现、再修复，包含真实外层事务拒绝与提交后事件断言。无需重开整体架构改造。
2. **补一条主要交付包的正常退出—重开闭环**，连同实际最大化、托盘恢复与元数据持久化留证；如涉及新的生产修复，重建并重新绑定候选包。
3. **统一报告与当前证据**，将 W4 扩展、W5 容量/回收计数明确留作后续，再进入小范围真机试用。全组件视觉矩阵和新增功能可放在试用反馈后。

可以结束围绕旧 DNS/普通 worker 误拒的重复修复；仍不宜将“测试通过”扩展成“所有交付边界都已验证”。本轮新增意见集中在一个 P2 代码边界与验收收口，不要求把历史全量计划重新执行一遍。

## 6. 审核范围与复现

隔离快照 `b1a6743b` 共 **973 文件**，复跑后与原树 SHA-256 核对 **0 差异**：[源码清单](weekly-recheck-round4-2026-09-08-evidence/source-manifest.json)。本轮未修改生产代码、原测试/探针及用户报告，未提交或推送。gpt-5.6-terra 子代理负责生产 diff 独立复核与 P2 边界复现，主代理核对结论、执行定向回归/压测/W5/哈希检查。

定向命令（在独立 ops 副本、QT_QPA_PLATFORM=offscreen 下）：

```powershell
python -m pytest -q -o addopts='' -p no:cacheprovider --junitxml=artifacts/round4-targeted.xml tests/integration/test_metadata_service_concurrent_boundary.py tests/unit/test_lan_utils_enumeration.py tests/integration/test_collection_service.py tests/integration/test_metadata_service.py
python scripts/perf/guard_stress.py
```

W5 在独立 sync 副本单独运行 `python scripts/perf/w5_lan_resource_probe.py`。观察脚本归档副本需放回独立源码 `scripts/perf/`，按其输出文件所记命令、在导入前设置隔离 AM_RUNTIME_ROOT 与 PYTHONPATH 执行；不要在原用户库运行。正常压力测试与特定外层事务屏障观察证明的场景不同，结果不可相互替代。
