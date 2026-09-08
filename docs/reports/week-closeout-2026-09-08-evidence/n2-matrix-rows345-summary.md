# N2 恢复验收矩阵 — 行 3–5 执行小结（子代理续做线，2026-09-08）

## 运行环境

- 快照：`.pytest-tmp-lead-snapshots/n2-recovery-ops`（gitignore 子树，与主工作区生产代码零共享写路径）
- 快照基线：主仓库 HEAD `c7d0759`（行 1/2 整合提交），其父即工作包基线 `82b7484`（82b74846）
- 运行命令：`QT_QPA_PLATFORM=offscreen python -m pytest -q -o addopts='' -p no:cacheprovider --junitxml=artifacts/n2-matrix-rows345.xml tests/integration/test_recovery_acceptance_matrix.py`（快照内执行；`-o addopts=''` 关闭 xdist，串行）
- 结果：**7 passed / 0 failed / 0 error，9.52s**（行 1/2 回归 + 行 3 + 行 4 + 行 5×3 全绿）
- 生产代码改动：**0**；主工作区改动：仅本目录三个 `n2-matrix-rows345.*` 证据文件

## 断言组状态表

| 行 | 断言组 | 状态 | 证据 |
|----|--------|------|------|
| 1 | 完整备份/恢复往返（前序线） | PASS（回归确认） | junitxml `test_row1_full_backup_restore_round_trip` |
| 2 | 元数据 JSON 合同（前序线） | PASS（回归确认） | junitxml `test_row2_metadata_json_export_contract` |
| 3 | 恢复覆盖语义 | PASS | `test_row3_restore_overwrite_semantics` |
| 4 | 中断后核对与幂等 | PASS | `test_row4_interrupted_restore_then_idempotent` |
| 5a | ZIP 成员字节篡改（与 manifest digest 不符） | PASS | `test_row5_corrupt_archive_rejected[tampered-member-…]` |
| 5b | manifest.json 截断 | PASS | `test_row5_corrupt_archive_rejected[truncated-manifest-…]` |
| 5c | zip-slip 成员（`data/../evil.txt`） | PASS | `test_row5_corrupt_archive_rejected[zip-slip-member-…]` |
| 6–7 | 建议行（见下） | 未在本工作包范围 | — |

## 各行断言要点（实测通过的产品行为）

### 行 3 · 恢复覆盖语义
- 目的域预置不同投影：hero rating 3（archive=5）、scene 2（archive=0）、unrated 4（archive=NULL）、多余集合成员（manual 含 unrated）、目的域独有集合、旧备注。
- `overwrite_existing=True` 恢复后：全量 DB 投影 == archive 投影；三态逐点断言（0 不被当 false 吞掉且非 NULL、NULL 不回退到目的旧值 4、hero 回 5）；manual 成员集精确被 archive 取代；目的独有集合消失。
- 旧 RuntimeData 整目录隔离于 `RuntimeData/_orphaned/restore-backups/RuntimeData_*`，文件级 digest 与恢复前逐字节一致，隔离副本内 DB 读出的仍是旧 rating 3/2/4。
- intent marker“存在可用于回滚”在安装交换的崩溃窗口期观测（`Path.replace` 观察点）：marker 存在、`version=1`、token 非空、`quarantine_entry` 指向刚隔离出的旧目录（且目录在盘）、`staging` 与即将安装的 staging 路径一致；恢复成功后 marker 按产品合同被消费（与行 1 断言一致）。

### 行 4 · 中断后核对与幂等
- 采用工作包方案 A：子进程恢复 + 父进程击杀。子进程以类级 `Path.replace` 补丁拦截安装交换（条件收紧为“staging 命名源 + 目标为 data-dir 槽位”，隔离 replace 与清扫 replace 均放行），写屏障文件后阻塞；父进程等屏障后 `kill()`。
- 崩溃窗口证据：data_dir 槽位消失、intent marker 在盘、其 `quarantine_entry` 目录在盘且逐字节等于旧态 digest。
- **新进程**（第二个子进程）open 同运行域：`_recover_interrupted_library_restore` 启动恢复触发——marker_before_open=True → 打开后 marker 消失、data_dir 恢复、digest 逐字节等于旧态、投影等于目的域旧投影、隔离区 RuntimeData_* 条目清零（回滚不残留副本）。
- 同一 archive 第二次正常恢复：结果 == archive 投影、file_count 一致、隔离区**恰好 1 条** RuntimeData_* 条目（中断+成功一对无重复堆积）、marker 清零、服务无 poison。

### 行 5 · 损坏归档明确拒绝（3 负例参数化）
- (a) 篡改 `data/assetmanager.db` 成员字节 → `checksum mismatch`；(b) manifest.json 截断 → `Invalid backup manifest`；(c) `data/../evil.txt` 成员 → `Unsafe backup member path`。
- 每个负例均断言：`validate_backup` 报 invalid 且错误文本可判定；`restore_backup` 在 validation 阶段抛 `ValueError`（先于 staging 建目录/任何目的域写入）；目的域旧态文件级 digest 逐字节不变；无 staging 目录、无 intent marker、隔离条目集合不变；`restore_failure_state is None`（拒绝≠中毒，服务仍可用）。

## 与工作包的差异清单

1. **行 3 marker 断言时机**：产品在恢复**成功后**清除 marker（行 1 已钉死该合同），故“marker 存在可用于回滚”只能在两次 replace 之间的崩溃窗口成立——用非阻塞 `Path.replace` 观察点在该时刻断言 marker 存在且 payload 完整可回滚，而非成功后断言（那会与行 1 矛盾且与产品行为不符）。
2. **行 4 恢复后 digest 对比时机**：恢复回滚后的新进程在干净关闭后采集 digest（打开连接产生的 `-wal/-shm` 侧文件会污染打开中状态对比）；断言实质不变（逐字节回滚）。
3. **行 4 进程编排**：父测试内先做目的域旧态种子（进程内），中断恢复在子进程 #1，启动恢复验证在子进程 #2（满足“新进程 open 同运行域”），第二次幂等恢复回父进程。
4. **行 5 损坏构造方式**：三个负例均以“整包重建 + 单点损坏”实现（条目 CRC 自洽），使拒绝路径落在合同层（digest/manifest/结构预检）而非底层 CRC 读错误；zip-slip 成员不写入 manifest，由结构预检拒绝。
5. **超出工作包最低要求的断言**：行 3 隔离副本内 DB 旧值读取；行 4 屏障内容校验、隔离条目清零、file_count 一致；行 5 非 poison 断言。
6. **未发现产品缺陷**：无需停止任何断言组；所有注入均通过测试侧补丁完成，未为测试改动生产代码。
7. 行 4 第二次恢复后，被杀子进程遗留的 staging 目录（`.{slot}.restore-<hex>`，mtime 新鲜）按产品清扫策略保留在位（清扫只归档陈旧项）——属产品既有合同，未计入隔离堆积断言。

## 行 6–7 建议

- **行 6（fail-closed 与自愈边界）**：marker 在盘但 `quarantine_entry` 缺失/不可用 → open 必须拒绝并给出可操作错误（`_recover_interrupted_library_restore` 的 unusable 分支）；corrupt marker 自愈（`quarantine_restore_intent_marker` 原地改名留证 + 最新有效候补自动回装 + 无候补时 fail-closed）。
- **行 7（并发与手动处置面）**：跨进程恢复互斥（一个进程停在安装交换崩溃窗口时，另一进程 open/restore 的 admission 行为）；`restore_intent_status` / `retry_interrupted_restore` / `acknowledge_restore_intent` 的 token 合同（错 token 拒绝、恢复期间 ACK 拒绝）；以及多轮“中断+回滚”循环下隔离区与 staging 残留的上界钉死。

## 产物

- `docs/reports/week-closeout-2026-09-08-evidence/n2-matrix-rows345.xml`（junitxml，7 tests / 0 failures）
- `docs/reports/week-closeout-2026-09-08-evidence/n2-matrix-rows345-output.txt`（pytest 控制台输出）
- 快照内同内容副本：`.pytest-tmp-lead-snapshots/n2-recovery-ops/artifacts/n2-matrix-rows345.{xml,output.txt}`
- 测试代码：快照 `tests/integration/test_recovery_acceptance_matrix.py`（行 1–5 共 7 用例；主工作区测试文件未动，待主代理整合）
