# 预登记草案：O0/O1/O2 观察干扰对照矩阵（batch-01）

> 状态：**待主代理批准后执行**。本文件在执行前冻结顺序与停止条件；
> 未获批准前不运行任何正式矩阵周期。
> 承接方案：`docs/plans/exit-g3-g2-investigation-plan-2026-09-09.md` §5。
> 准备批次：`docs/reports/exit-g3-g2-2026-09-09-evidence/batch-01-prep/`。

## 1. 固定条件（全部周期不变）

| 条件 | 值 |
|---|---|
| 候选 onefile exe | `artifacts/weekly-repair-2026-09-08-103f119/AssetManager.exe`，SHA-256 `1d568fb80ef6dcb78f9d8001ea68c521367638938a3463cf2964e51960372c5a`（不改名） |
| 诊断驱动 | `scripts/perf/w6_g2g3_diagnostic.py`（f989 派生基底，见 manifest 哈希） |
| 正式对照驱动 | `scripts/perf/w6_package_functional.py`（bd8142…，不用于诊断组） |
| 观察器插件 | batch-01-prep/observer-plugin（单一实现，见 manifest 哈希） |
| 输入方式 | f989 驱动内置 keybd_event/scan=0 Ctrl+Q（一次退出只发一次 Q，不补发） |
| 模式 | onefile + 最大化 + `--auto-open`（完整 W6 负载顺序不变） |
| 运行域 | 每周期独立 AM_RUNTIME_ROOT / 合成库 / 端口；同周期重启复用该域 |
| 超时 | 首退与重启退出均 30 秒；超时即失败，不延长、不强杀代替断言 |

## 2. 组别定义

- **O0**：无诊断插件。运行域 `Shared/plugins` 不含任何观察插件；无
  AM_EXIT_DIAGNOSTIC_LOG 环境变量。没有 Qt 记录是该组的设计限制，
  不得据此推断 Qt 事件没有发生。
- **O1**：同一观察点实现，事件先写入有界内存缓冲（默认上限 20000 条，
  `AM_G3_BUFFER_LIMIT` 显式定义）；失败/超时或正常收尾由控制器进程通过
  文件请求（`AM_G3_EXPORT_REQUEST`）触发导出，观察器后台守护线程
  （不经 Qt 主线程）回执 `AM_G3_EXPORT_ACK`；另有 atexit 后备
  （`AM_G3_FINAL_FLUSH`）保全"请求未出现"的正常退出事件。
- **O2**：与 O1 完全相同的观察点、字段、过滤与导入时机，唯一差异是
  同步写盘（`AM_G3_OBSERVE_MODE=synced`，逐条 flush）。

O1/O2 从同一 observer.py 派生；模式选择只改记录出口（`_Recorder` 内
分支），不改观察点。不提前导入 MainWindow、不替换生产方法对象、不改
信号连接；sys.monitoring 只启用目标 code（request_exit / closeEvent /
_shutdown_resources）的本地事件。

## 3. 区组与顺序（执行前冻结）

| 区组 | 顺序 |
|---|---|
| 1 | O0 → O1 → O2 |
| 2 | O1 → O2 → O0 |
| 3 | O2 → O0 → O1 |
| 4 | O0 → O2 → O1 |

- 每组一次运行 = 一个周期；每周期包含**首退 + 重启退出**两次 Ctrl+Q
  （驱动内置行为，与 f989 一致）。
- 上限：**12 周期 / 24 次退出**。区组执行顺序为 1→2→3→4；任一停止
  条件触发时剩余格标记 NOT_RUN。
- 这是减轻顺序偏差的交错设计，不代表时间或环境已被完全控制。

## 4. 判定与记录

- 每周期驱动退出码 0 = PASS；超时/输入无效 = FAIL（先保全后分析）；
  驱动/缓冲/证据错误 = INVALID（该轮不计入对照，需修正后新批次）。
- O1 每周期分相保存：首退与重启的事件导出 JSONL、导出 ack、recorder
  状态、控制器日志、驱动 stdout、退出码与清理记录。
- O2 保存同步日志文件本体 + 事后 ack 确认。
- O0 无应用内日志（设计限制），只保存驱动侧输入四阶段采样与退出结果。
- 汇总报告周期数、首退/重启失败数、输入无效数、日志完整性
  （startup/install/连续序号/shutdown 或 final flush）、耗时分布。
- 小样本全部通过只写"本批次未复现"；不宣称观察器无影响、输入原因
  排除或故障率为零。

## 5. 停止条件

1. **任一轮目标失败（退出超时或输入无效）即停止整个批次**，转失败
   分析（方案 §6）；后续周期不运行并标记 NOT_RUN。
2. 驱动、缓冲或证据缺陷被发现（如序号断裂、导出丢失、观察器异常）：
   该轮 INVALID，暂停正式实验；修正后以新版本、新批次目录重新预登记。
3. 独占 GUI 时段超过 **90 分钟** 即终止本次运行段，剩余格改期，
   已完成轮保留。
4. 12 周期无复现：结束批次，交付覆盖与不确定性，不自动扩到 30/100 轮。
5. 捕获失败：先保全并分析；最多追加 4 个有假设的区分周期（另行登记）。

## 6. 执行前置条件（全部满足才可开始）

- [x] 基线哈希核对（manifest.json）
- [x] O1/O2 观察器实现冻结 + source-diff.patch
- [x] 记录器可靠性五场景验证通过（reliability-runs/summary.json）
- [ ] **主代理批准本预登记**
- [ ] 主代理分配独占 GUI 时段（≤90 分钟，无其他执行线占用桌面）

## 7. 批准后的执行命令（记录用，不在本轮运行）

```
# 每周期（区组顺序见上表；<cond> ∈ {o0,o1,o2}，<block> 1..4，<cycle> 全局编号）
python docs/reports/exit-g3-g2-2026-09-09-evidence/<batch>/run_matrix_cycle.py \
    --block <block> --cond <cond> --cycle <cycle>
```

矩阵 runner 脚本将在批准后、执行前放入正式批次目录并登记哈希；
本轮 batch-01-prep 不包含矩阵 runner，也不运行任何矩阵周期。

## 8. 准备阶段实际发现（2026-09-09，batch-01-prep，执行前补充）

- **观察器实现缺陷已发现并修复**：首版 observer.py 在 `emit()` 持锁路径
  内调用 `_maybe_status()→status()` 造成非重入锁自死锁，曾使候选 exe
  GUI 事件循环停摆（attempt-4/5/6，证据归档 attempt-1-plugin-path-bug/
  synced-capture-4-deadlock-located：register-trace 停在 recorder_built、
  synced 日志仅落 seq 1）。修复后 synced-capture 与五场景全部通过。
  该缺陷只存在于诊断设施，生产代码与候选 exe 未受影响；这也说明
  **观察器有能力让 GUI 完全停摆**，O1/O2 组的解释必须始终对照观察器
  自身健康状态（状态文件 alive/error_count）。
- **记录器可靠性五场景结论**：见 reliability-runs/summary.json。
  S2/S5 中导出请求与失败清理存在竞态窗口（守护线程随 PID 树被杀），
  结果按方案 §4 标注"日志不完整"，不据此认定事件没有发生；S3 的丢弃
  计数以观察器主动汇报的状态文件为准。
- **桌面环境噪声（实测记录）**：执行机器当前前台/可见窗口包含 QQ.exe
  （PID 4212，与历史失败现场前台占用者一致）、Steam、多个浏览器与
  资源管理器窗口；O0 对照轮出现发键前窗口被最小化（另一窗口抢占
  active），驱动按合同安全拒绝发送。这正是历史间歇性失败的同类环境
  特征——正式矩阵必须预登记"桌面前台竞争"为已知环境变量，轮次结果
  不得在未记录前台占用者的情况下判读输入层缺失。
- **时钟**：perf_counter 与 monotonic 同源（QPC），跨进程可比性误差为
  采样间隔（亚毫秒级），各场景 clock-check.json 已存证。

以上发现不改变第 1–7 节的预登记设计；正式矩阵执行前需主代理批准并
分配独占 GUI 时段（桌面当前含用户常驻应用，"独占"指无其他自动化执行
线，不等于无人桌面）。
