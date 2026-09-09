# G3/G2 本轮验收与交接复核（2026-09-09）

> 当前裁决：接受“本批次未定位、观察干扰对照未复现”的阶段交付；历史 Ctrl+Q 失效根因保持开放。以下修正替代交付摘要中超出证据的结论。
> 本轮复核为源码、归档脚本和原始 JSON/JSONL 的只读检查。未重跑 GUI、pytest 或性能实验，未修改生产代码、候选包及哈希绑定的原始证据。
> 下周唯一排期入口：[2026-09-14—09-20 周计划](../plans/weekly-priorities-2026-09-14.md)。

## 1. 接受的成果与边界

- 正式矩阵登记为 12 周期、24 次退出，O0/O1/O2 各 4 周期，各轮退出码均为 0，预算记录为 42.8/90 分钟。准备、sanity 和正式矩阵分开计数。
- O1/O2 的 16 个进程事件流提供了正常退出的主要层级记录；O0 没有应用内事件流，不能计入该覆盖数。
- 准备期观察器持锁自死锁及其修正是诊断工具的有效成果。它说明该版观察器可以制造 GUI 停摆，不能据此认定历史 observed-08 或无插件失败也由同一缺陷造成。
- 本轮没有历史目标故障样本，不要求为了修改报告而重跑矩阵，也不把通过次数累计为可靠性保证。

证据入口：[正式分析](exit-g3-g2-2026-09-09-evidence/batch-02-matrix/analysis.md)、[原始汇总](exit-g3-g2-2026-09-09-evidence/batch-02-matrix/summary.json)、[清单](exit-g3-g2-2026-09-09-evidence/batch-02-matrix/manifest.json)。上述归档保持原样，下面记录其解释限制。

## 2. 必须修正的判读

### R1：源码零命中不能排除所有应用相关最小化路径

检索支持“所查生产源码未发现显式主动最小化调用”。它不穷尽 Qt/平台插件、窗口恢复、窗口管理与输入的交互，不能推出“最小化来源必在应用外”。最小化触发者、触发时刻及与输入的因果关系均保持未知；前台 PID 不能定责。

### R2：LibraryService.close 不是唯一无超时同步等待

`LibraryService.close` 的两处条件等待确实未传 timeout（当前源码 1379、1381 行）。但实际退出调用还包括：

```text
MainWindow.closeEvent
  → LibraryService.close
    → _run_owned_teardown
      → DatabaseManager.close_library
        → _write_gate.write
          → Condition.wait_for(...)  # 未传 timeout
    → DatabaseManager.close
      → _write_gate.write            # 同一等待点
```

对应代码：[库服务](../../AssetsManager/application/library_service.py)、[数据库写闸门与关闭](../../AssetsManager/core/database.py)。数据库 `write()` 的等待位于 523 行，`close_library()`/`close()` 分别在 1124/1097 行进入该闸门。

此外 `LibraryRuntime.close()`/`close_adapters()` 有条件等待（157/126 行），应随实际 listener/adapter 路径继续审查。锁竞争、文件 I/O 和多个有界等待的累计时间也不能从退出预算中忽略。此处证明的是静态等待点存在，未证明任何一个点在历史失败中被触发。

为排除“审核后新增代码”的解释，以下文件与 G2 快照逐字节一致：

| 文件 | 当前工作区与 g2-analysis 快照共同 SHA-256 |
|---|---|
| application/library_service.py | `943d8e83038cce59aec137b05c7954192776a219c9b16589c7fc39d2f7339cb9` |
| core/database.py | `cac451e1f777aa8d60c1a87ee536562a5fdde399e1a836fd5e6558d5f372eefd` |
| application/runtime.py | `4544b2b73f3118e0905036db017623621a9c951009ccff8cf8f9c86ba8bc282f` |

因此，下周只安排退出预算和资源所有权评估，不直接给 wait_for 加超时。超时后若仍有操作持有数据库、root reservation 或租约，不能提前释放，也不能将 pending 标为 closed。

### R3：首尾前台 PID 相同不等于周期内没有竞争

[runner](exit-g3-g2-2026-09-09-evidence/batch-02-matrix/run_matrix_cycle.py) 的 `foreground_changed`（600–601 行）只比较周期前后的 `foreground_pid`。相同 PID 不证明同一 HWND，更不证明中间未发生切换；测试期间目标本身就需要获得前台。

正确表述为：“12 周期首尾前台 PID 相同；已有输入与事件采样未提供本轮历史故障复现证据。”不得据此写“所有通过批次均无前台竞争”，也不能把跨批次稀疏采样合成强相关性结论。受控前台实验可用于补齐观测，优先级不依赖这项未经证实的概括。

### R4：六层主要记录不等于 G2 细粒度合同全部实现

[正式观察器](exit-g3-g2-2026-09-09-evidence/batch-02-matrix/observer-plugin/observer.py) 的 `_install_monitor`（527–528 行）仅监控 MainWindow 的 `request_exit`、`closeEvent`、`_shutdown_resources`。它没有逐个监控 LibraryService、数据库闸门、LAN stop 或 LifecycleCoordinator 的子步骤。

下次若退出调用已进入而未返回，现有记录可定位到粗粒度区间；内部卡点仍需额外挂点或目标线程栈。不能声称 LibraryService.close 的触发或返回已由本批事件直接验证。

采集合同还需区分：Qt eventFilter 与应用内 QAbstractNativeEventFilter 是不同观察机制。后者可以在应用进程内看到 Windows MSG，不是“仅外部可见”。收到 MSG 不自动给出发起者身份。参考 [Qt 原生过滤器文档](https://doc.qt.io/qt-6.8/qabstractnativeeventfilter.html)。

### R5：记录健康指标有明确观察截止点

两次启动的普通记录都使用 `first-exit`，调用记录又将 phase 用作 enter/return；当前须按 PID 和驱动结果映射相位。下一版使用独立的 `launch_phase` 与 `call_phase` 字段，并记录 PID 创建身份，保留原始数据。

O1/O2 共用采集代码，但 O1 额外启用 exporter/atexit，O2 状态停留在最后一次心跳。因此两者比较的是包含这些导出路径的实际模式，不能宣称除了单次写盘动作外全部机制完全相同。`seq` 连续和最后记录的 dropped/error 为零支持现有日志完整性检查，不能证明之后没有漏记事件，也不能单独排除观察器持锁停摆。

本批次 O1 实际没有 export-ack 或 events-export，8 相靠 events-final-flush 保全；不能称正式矩阵验证了失败时导出握手。O2 的状态序号只有 106–192，实际流末序号为 249–265，8 个状态均 alive=true 且无 terminated。流内未见错误记录，和“退出末态错误计数确定为零”是不同结论。

### R6：修正生命周期语义，避免下一轮误判

`_save_window_geometry` 保存的是还原前的 `was_maximized`，并非固定保存 False（window.py:121–125）。正常 `close()` 接受事件后隐藏窗口，是否删除还依赖属性/生命周期；`aboutToQuit` 在退出主事件循环前发出，不能写成 `exec()` 返回之后。分别见 [QWidget.close](https://doc.qt.io/qt-6/qwidget.html#close) 与 [QCoreApplication.aboutToQuit](https://doc.qt.io/qtforpython-6.8/PySide6/QtCore/QCoreApplication.html)。

G2 原分析中关于键消息低优先级、合并丢弃、bootloader 输入桌面交互等具体机制尚无本地样本或权威实现证据，只能作为待验证问题，不构成硬结论。

## 3. 本轮收口处置

1. 阶段成果接受；生产缺陷修复数为 0；主案保持开放。
2. 当前收口报告及 G2 合同/分析顶部同步本复核结论，原始矩阵与 manifest 不改写、不重新计算历史证据。
3. 下一周先完成用户可感知的交付缺口；顽疾线以有限的受控实验和退出预算评估继续，预算耗尽可按“未定位”交付。
4. WebUI Runtime Phase 1 已存在工作区代码与测试改动，尚未由本轮验收；纳入下一周同版本验收。G3 旧候选包通过不能覆盖这些新增源码。

## 4. 本轮验证范围

本轮执行了归档 JSON/JSONL 核对、脚本和源码阅读、G2 快照哈希对比及文档检查。没有把历史 5110 项测试、W6 六场景或 G3 24 次退出写成本轮重跑结果。

独立 Terra 子代理全量复算结果：81 个 JSON、16 个 JSONL 共 3,924 条非空记录均可解析；16 相序号连续。12 个正式 cycle-result 均 PASS、driver_exit=0、exit_codes=[0,0]；O0/O1/O2 各 4 周期；最后预算字段 42.8 分钟。预登记、observer、delta patch、runner、summary、analysis 六项清单哈希均匹配。16 流主要退出层级记录在场；O2 流内无 recorder_error/partial，dropped_so_far 为零。该复算支持阶段结果，并保留 R1–R6 限制。

死锁原始证据复核：坏版观察器 SHA-256 为 `81eb20407008472a126d3c410f4700deb71642a8ad149bef48e36697df0b4a3e`，Lock:123 → emit 持锁:140 → _maybe_status:263 调 status → status 再取锁:192。对应 register-trace 停在 recorder_built。修复版 SHA-256 为 `49f91dc499a40c54f2a9ab561608c4aacbb8470e26518eefa89f56f769160ccb`，改为锁内直接构造状态；后续同步采集轮有 W6 PASS 和两次退出码 0。此证据足以确认该工具缺陷；不将准备期混有解码/PIPE 问题的所有失败轮统一归为同一种死锁。

收尾检查：10 份本轮文档的 66 个本地链接均有效，代码围栏成对、UTF-8 可读；定向 git diff --check 通过。主代理再次核对正式 manifest 六项哈希、12 个周期结果入口、16 个事件流入口；官方 W6 的 bd8142 哈希及旧候选的 1d568fb8 哈希保持匹配。周计划预算合计 40h。未执行下一周工作包。
