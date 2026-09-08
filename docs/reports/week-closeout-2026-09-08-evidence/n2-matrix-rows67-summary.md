# N2 恢复验收矩阵 — 行 6–7 执行小结（子代理续做线，2026-09-08）

## 运行环境

- 快照：`.pytest-tmp-lead-snapshots/n2-recovery-ops`（gitignore 子树；行 3–5 已由主代理整合入主仓）
- 运行命令：`QT_QPA_PLATFORM=offscreen python -m pytest -q -o addopts='' -p no:cacheprovider --junitxml=artifacts/n2-matrix-rows67.xml tests/integration/test_recovery_acceptance_matrix.py`（快照内执行，串行）
- 结果：**9 passed / 0 failed / 0 error，20.14s**（行 1–5 回归 + 行 6 + 行 7 全绿；row7 单测 6.7s）
- 生产代码改动：**0**；主工作区改动：仅本目录三个 `n2-matrix-rows67.*` 证据文件

## 断言组状态表

| 行 | 断言组 | 状态 | 与建议的合同差异 |
|----|--------|------|------------------|
| 6a | 健康 marker + 隔离条目缺失 → open 拒绝、无半恢复态 | PASS | 无差异 |
| 6b-i | corrupt marker 原地改名留证（字节保留） | PASS | 无差异 |
| 6b-ii | 最新有效候补自动回装（两个候补中新者胜出，DB 功能正常） | PASS | 无差异 |
| 6b-iii | 无候补 → fail-closed，重复 open 持续拒绝，status=corrupt-quarantined，绝不物化空库 | PASS | 无差异 |
| 7-互斥 | 崩溃窗口期第二进程 open / restore / 手动恢复面 | PASS | **实际合同为快速失败（拒绝），非排队**：`LibraryLock` 用 `QLockFile.tryLock(0)`，第二进程立即得 `LibraryAlreadyOpenError`；已按实际合同钉死 |
| 7-token | status / retry / acknowledge token 合同 | PASS | 1 处合同澄清，见差异清单 #3 |
| 7-循环 | 3 轮"中断+回滚"后残留上界 | PASS | 上界=每轮中断恰好遗留 1 个 staging 残留、隔离区每轮清零（详见差异清单 #4） |

## 各断言组要点（实测通过的产品行为）

### 行 6 · fail-closed 与自愈边界
- **(a)** data_dir 槽位移走 + 健康 marker 指向不存在的隔离条目 → `open_session` 抛 `RuntimeError`（含 "Interrupted library restore detected" 与 "Refusing to open" 指引）；槽位仍缺、marker 原样（token 不变）、隔离区不变、无 staging 残留、移走的旧态逐字节完好——无任何半恢复/空库物化。
- **(b-i)** corrupt marker 打开后被 `quarantine_restore_intent_marker` 原地改名为 `.{slot}.restore-intent.json.corrupt-<时间戳>_<hex>`，损坏字节原样保留为证据，live marker 消失。
- **(b-ii)** 隔离区两个 `{slot}_` 候补（旧 mtime sentinel=OLD / 新 mtime sentinel=NEW）→ 自愈自动回装**最新**候补（sentinel=NEW），digest 与候补一致，`connection_for` 可执行查询；被回装候补从隔离区消失，旧候补保留。
- **(b-iii)** 无候补 + corrupt marker → open 抛错（含 "no validated backup candidate is available" 与 "Manual recovery" 指引）；证据文件保留、**槽位保持缺失（绝不物化空库）**；第二次 open 继续拒绝（corrupt 证据持续守门）；`restore_intent_status` = `{"status": "corrupt-quarantined", "quarantine_entry": None, "token": None}`（无锁读，可在不开 DB 的情况下驱动恢复对话框）。

### 行 7 · 并发互斥、token 合同与循环上界
- **互斥（实际合同=拒绝）**：子进程停在安装交换崩溃窗口（持跨进程库锁）时，第二进程：`open_session` → `LibraryAlreadyOpenError`；已绑会话的 `restore_backup` → `LibraryAlreadyOpenError` 且 `restore_failure_state is None`（拒绝≠中毒）；`retry_interrupted_restore` → `LibraryAlreadyOpenError`；`acknowledge_restore_intent`（任意 token）→ `LibraryAlreadyOpenError`（锁拒绝先于一切校验）。`restore_intent_status` 为无锁读，崩溃窗口内仍返回 `recoverable` + token + 隔离条目路径。子进程仍存活、marker 在盘、隔离条目逐字节完好——两侧状态零损坏。
- **token 合同**：
  - 错 token ACK → `RuntimeError("Restore intent acknowledgement rejected: stale or unknown token")`，marker 保留；
  - **库活跃时**（同进程 live 会话）：ACK → `"Cannot acknowledge restore intent while library is active"`；retry → `"Cannot recover restore intent while library is active"`；
  - **崩溃窗口（槽位缺失）不可被 ACK 掉**：即使 token 正确 → `"Restore intent acknowledgement requires a verified RuntimeData directory"`，marker 保留（唯一出路是回滚或人工处置，不能凭空确认）；
  - 合法路径（槽位在、marker 陈旧、锁空闲）：正确 token ACK → marker 清除、数据 digest 不变、status 归 None。
- **循环上界（3 轮）**：每轮"子进程停在安装交换→击杀→open 触发启动回滚"——回滚后隔离区 RuntimeData_* 条目**每轮清零**（0 净堆积）；staging 残留**每轮恰好 +1**（3 轮后 ==3，全部匹配产品清扫自身的命名合同 `^\.{slot}\.restore-[0-9a-f]{32}$`）；第 3 轮后同一 archive 正常恢复成功（投影==archive 投影、file_count 一致、隔离区恰 1 条且逐字节等于旧态）、raw 资产逐字节不变。

## 与产品的差异清单（按实际合同钉死处）

1. **互斥语义**：工作包允许"拒绝或排队"——实测合同为**拒绝**（`QLockFile.tryLock(0)` 快速失败，无排队无等待），测试按拒绝钉死。Windows 侧被杀进程的锁由 `_pid_is_alive` 陈旧锁恢复回收，第 2 轮子进程/父进程 open 均可立即获得锁。
2. **ACK 的锁优先级**：崩溃窗口内第二进程 ACK 得到的是 `LibraryAlreadyOpenError`（锁拒绝先于 token/槽位校验）；"requires a verified RuntimeData directory" 分支仅在锁空闲（击杀子进程后）可达——两处均按实际顺序钉死。
3. **"恢复进行中 ACK 拒绝"的可达形态**：产品检查的是**本进程规范所有权**（`key in _root_ownership`，live 会话 → 拒绝），而跨进程占用者持锁时 ACK 先被锁拒绝——两种形态各自独立钉死，语义不同（所有权拒绝 vs 锁拒绝）。
4. **staging 残留"上界"的实际合同**：清扫按 **7 天年龄门**只归档不删除（陈旧项移入隔离区，从不原地删除），新鲜残留**有意保留在位**。因此钉死的上界是：**每次中断恰好遗留 1 个 staging 目录（第 N 轮后恰 N 个），隔离区条目每轮回滚清零；成功恢复恰新增 1 条隔离条目**——即残留量与中断次数严格线性、与成功恢复次数一致，不发生无界堆积。防御性计数帽（`_QUARANTINE_ACTIVE_MAX=8`、`_EXPIRED_MAX=32`）在本场景未触发（隔离区始终 ≤1），未在本行断言。
5. **digest 对比口径**：回滚/自愈打开后的槽位会因活动连接出现 `-wal/-shm` 侧文件，对比一律采用剔除侧文件的 digest 口径（与"关闭后快照"同条件）；回滚实质仍为逐字节恢复（隔离条目未被打开过，digest 原样相等）。
6. **未发现产品缺陷**：所有分支行为与设计意图一致；零生产改动，全部注入为测试侧补丁/子进程编排。
7. 行 6/7 均在 tmp_path 与快照内完成；击杀子进程使用 `TerminateProcess`（模拟真实进程死亡）；未 commit/push。

## N2 收口建议

1. **矩阵已达覆盖饱和**：行 1–7 覆盖了备份/恢复往返、元数据 JSON 合同、覆盖语义、中断回滚、损坏拒绝、fail-closed/自愈、并发互斥与残留上界。恢复链路上剩余未钉死的面仅有：真实 GUI 驱动的恢复对话框（desktop 层）与 `_expired` 计数帽的强制裁剪路径——后者需要人为构造 >8 个隔离条目（纯测试编排，建议仅在需要时以单元级测试覆盖）。
2. **可收口结论**：N2 恢复可靠性工作包的验收矩阵 9/9 全绿，"中断必留证、回滚必完整、拒绝必先行、自愈必最新、并发必快速失败、残留必有界"六条性质全部有自动化钉死，建议按周收口关闭 N2。
3. 若后续重构 `library_service._recover_interrupted_library_restore` 或 `LibraryLock`，行 4/6/7 是回归边界；行 7 的 `_STAGING_RESIDUE_PATTERN`/`_QUARANTINE_ACTIVE_MAX`/`_RESTORE_RESIDUE_STALE_SECONDS` 常量若调整需同步测试。

## 产物

- `docs/reports/week-closeout-2026-09-08-evidence/n2-matrix-rows67.xml`（junitxml，9 tests / 0 failures，含行 1–5 回归）
- `docs/reports/week-closeout-2026-09-08-evidence/n2-matrix-rows67-output.txt`（pytest 控制台输出）
- 快照内同内容副本：`.pytest-tmp-lead-snapshots/n2-recovery-ops/artifacts/n2-matrix-rows67.{xml,output.txt}`
- 测试代码：快照 `tests/integration/test_recovery_acceptance_matrix.py`（行 1–7 共 9 用例；主工作区测试文件未动，待主代理整合）
