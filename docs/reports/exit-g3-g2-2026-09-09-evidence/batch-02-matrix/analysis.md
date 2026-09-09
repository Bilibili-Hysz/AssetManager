# batch-02-matrix 分析：O0/O1/O2 观察干扰对照

> 执行：2026-09-09，G3 执行线。预登记：`../batch-01-prep/preregistration.md`
> （主代理已批准）。矩阵 12 周期全部执行，无停止条件触发。
> 结论状态：**本批次未复现**（预登记 §4 措辞纪律——不宣称观察器无影响、
> 输入原因排除或故障率为零）。

## 1. 执行清单

- 区组顺序 1→2→3→4 全部执行；每周期 = 完整 W6 负载 + 首退 Ctrl+Q +
  重启 + 重启退 Ctrl+Q（f989 驱动合同，一次退出只发一次 Q）。
- 12 周期 / 24 次退出全部完成：**24/24 退出码为 0**；O0/O1/O2 各
  4 周期 8 退出，全部 PASS，无 FAIL / INVALID / NOT_RUN。
- 预算：90 分钟上限，实际 ~42.8 分钟（含每轮前台快照与收集开销）。
- 纪律 a（主代理附加）：每周期前台快照已归档
  （`runs/cycle-*/foreground-before.json` / `foreground-after.json`）。
  12 轮周期开始时前台均为 ChatGPT.exe（用户常驻窗口），**周期内前台
  无变化**（foreground_changed=False × 12）——本轮矩阵未观测到历史
  失败现场的"前台竞争/最小化"干扰。
- 纪律 b：未触发（无目标失败），未启动任何第二阶段区分实验。

## 2. 分组结果

| 组别 | 周期 | 退出码 | 失败数 |
|---|---|---|---|
| O0（无插件激活） | 1, 6, 8, 10 | [0,0]×4 | 0 |
| O1（有界内存缓冲） | 2, 4, 9, 12 | [0,0]×4 | 0 |
| O2（同步写盘） | 3, 5, 7, 11 | [0,0]×4 | 0 |

## 3. 日志完整性统计（观察器健康）

O1/O2 共 16 个观察相（每周期首退 + 重启各一个 GUI pid）：

- **序号连续**：16/16 相 seq 连续无断裂（O1 依赖 final-flush/导出并集，
  O2 即逐条落盘本体）。
- **缓冲丢弃**：16/16 相 dropped=0（上限 20000 未触发）。
- **记录器错误**：16/16 相 error_count=0。
- **每相事件量**：222–265 条（含 recorder_startup、插件安装状态、
  native_event 126 条左右、Qt event 100 条左右、call 6 条左右、
  application 2 条）。
- **终止快照语义差**（判读须知，非故障）：O1 的观察器注册了 atexit
  终止快照（terminated=true × 8）；O2（synced）按实现不注册 atexit
  （逐条落盘本身即证据），其状态文件停在最后一次 1Hz 心跳
  （alive=true）——O2 的完整性以落盘日志本体判读：**16 相日志全部
  完整收尾**（退出链在流内，末条为窗口销毁期的 WM_DESTROY 系原生
  消息，合法）。
- batch-02 观察器修订（PID 后缀分相 + 终止快照）已生效：batch-01 中
  "phase-2 final flush 覆盖 phase-1 文件"的丢失路径在本矩阵中未再
  出现（16 相各自独立文件）。

## 4. 事件链首落点摘要（正常轮判读）

8 个 O1/O2 周期的全部 16 相，事件链完整：

- Qt 输入层：ShortcutOverride/KeyPress 在场，**Shortcut 在场**（16/16）；
- 原生层：Ctrl/Q 的 WM_KEYDOWN/UP 在场（16/16）；
- 退出调用：request_exit 进入+返回、closeEvent、_shutdown_resources
  全部捕获（16/16），application 信号 aboutToQuit+lastWindowClosed
  在场（16/16）。
- 即：**正常轮的完整链条 原生键消息 → Qt Key/ShortcutOverride →
  Shortcut → request_exit → closeEvent → shutdown_resources →
  lastWindowClosed → aboutToQuit → 进程退出码 0 全部有事件佐证**，
  无任何一层缺失。O0 无应用内日志是设计限制（驱动侧四阶段输入采样
  在 driver-stdout.log，退出码 [0,0]）。

## 5. 观察干扰对照

- O0/O1/O2 在本批次均无失败；**未复现**历史间歇性 Ctrl+Q 失效。
- 由本批次不能推出"观察器无影响"（样本 12 周期；且 batch-01 准备期
  曾实测观察器缺陷可让 GUI 完全停摆——观察器改变时序的能力是真实
  的，本轮未触发不代表不可能）。
- O1 与 O2 的记录出口差异（内存缓冲 vs 逐条落盘）在本批次未造成
  可分辨的结果差异（全部通过、每相事件量同量级、耗时无肉眼差异）。
- 顺序偏差已按预登记交错设计减轻；时间与环境未被完全控制。

## 6. 环境登记与限制

- **phase 字段限制**：runner 对整周期只设一次 `AM_G3_PHASE=first-exit`，
  重启相 exe 继承同一环境 → 观察器两相的 phase 字段都记 first-exit。
  分相判读依据 **GUI pid + 文件时间序**（首退 pid 先创建）而非 phase
  字段。此为 runner 环境设计限制，不影响事件本体与完整性；后续批次
  如需 phase 字段精确，须让驱动以环境区分两相（不可行，驱动 Popen
  同一 env）或由控制器按 pid 时间序标注（本汇总即如此处理）。
- **桌面环境**：12 轮前台均 ChatGPT.exe（用户常驻）；QQ.exe（PID
  4212，历史失败现场前台占用者）仍在可见窗口集合中但未在本批次
  争抢目标前台。所有周期 foreground_changed=False。
- **时钟**：观察器单调毫秒 + 驱动 monotonic_s 同源 QPC，跨进程可比
  （亚毫秒级采样误差）；本报告未做跨进程硬拼接因果链，事件判读以
  同进程序号顺序为准。
- **链路边界**：正常轮无缺失层，"最早缺失层"判读（方案 §6 表）在
  本批次无适用样本。

## 7. 证据索引

- 每周期：`runs/cycle-NN-<cond>/cycle-result.json`（状态/原因/退出码/
  分相链判读）、`foreground-before|after.json`（纪律 a）、
  `synthetic/driver-stdout.log`（驱动四阶段输入采样 + close 证据）、
  `synthetic/recorder-status.<pid>.json`（观察器状态/心跳/终止快照）、
  `synthetic/qt-events.<pid>.jsonl`（O2 逐条落盘）、
  `synthetic/events-final-flush.<pid>.jsonl`（O1 atexit 保全）、
  `synthetic/events-export.<pid>.jsonl` + `export-ack.<pid>.json`
  （O1 控制器请求导出通道）。
- 汇总：`summary.json`（每轮 PASS/原因/退出码/链完整性/前台变化）。
- sanity 预热轮（不计入矩阵）：`runs/sanity-cycle-00-o0-not-counted/`。

## 8. 不确定性与下一步（交主代理）

1. 12 周期未复现：如需继续，须由主代理批准新批次（预登记续跑或环境
   变化重现条件，如前台竞争注入）；本线不自动扩大长跑。
2. batch-01 准备期发现的"观察器缺陷可停摆 GUI"提示：正式矩阵轮的
   失败判读必须先核对观察器健康（status error_count/心跳），再谈
   应用层缺失——已写入判读纪律，本轮未用到。
3. phase 字段 runner 限制（见 §6）——若下一批次需要按字段分相，
   需要控制器后处理标注或驱动环境改造（涉及驱动冻结约束，需批准）。
