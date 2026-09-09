# G2 事件采集合同与实现差距（2026-09-09 修订）

> 当前版本与[正式观察器](exit-g3-g2-2026-09-09-evidence/batch-02-matrix/observer-plugin/observer.py)逐项对照，取代原合同中“原生消息仅外部可见”及“所有退出子步骤已覆盖”的表述。
> 本文是采集合同和差距登记，本轮未实现新观察器。[验收复核](exit-g3-g2-acceptance-review-2026-09-09.md)规定结论边界。

## 1. 观察层与当前实现

| 层 | 当前 batch-02 实际实现 | 能证明 / 尚缺什么 |
|---|---|---|
| L0 输入生成 | W6 驱动逐键调用与安全检查 | keybd_event 无成功回执；输入生成不等于应用接收 |
| L1 原生消息 | 应用内 QAbstractNativeEventFilter 记录选定 Windows MSG | 能看到该过滤器收到的 Ctrl/Q、激活/状态/系统命令等；不能证明没有记录的消息未生成，也不能自动识别发起者 |
| L2 Qt 输入 | QApplication 级 eventFilter；Ctrl/Q、ShortcutOverride、Shortcut 及焦点/状态 | 可直接记录 QEvent.Shortcut；不能观察完整 QShortcutMap 匹配决策；禁止用 request_exit 反推 Shortcut 再拿同一事件证明因果 |
| L3 退出调用 | sys.monitoring 只挂 MainWindow.request_exit、closeEvent、_shutdown_resources | 有粗粒度 enter/return/unwind；无 LibraryService、LifecycleCoordinator、数据库及 LAN 子步骤独立进出 |
| L4 终止 | lastWindowClosed/aboutToQuit 追加观察槽；外部驱动退出记录 | GUI 内信号不证明 onefile 父进程结束；进程退出要核对外部证据 |
| L5 窗口/前台 | Qt 状态与原生只读状态、驱动发键采样、周期首尾前台快照 | 快照不是连续轨迹；不可见、最小化、销毁分别判定 |

Qt eventFilter 与 QAbstractNativeEventFilter 都可以在应用进程内安装，前者接收 Qt 事件，后者接收原生事件。Windows 下后者可获得 MSG；它不等价于 OS 全局输入队列观察器。见 [Qt 文档](https://doc.qt.io/qt-6.8/qabstractnativeeventfilter.html)。

QObject::connect 追加观察槽也有执行成本；本批健康结果不能称“零干扰”。保持原方法身份、不提前导入 MainWindow，不意味着完全没有时序影响。

## 2. 下一版事件字段

公共字段至少包含：schema_version、run_id、launch_phase、PID 与创建身份、TID、目标 HWND、seq、进程内单调时间、record_type。调用记录另用 call_phase=enter/return/unwind；不得覆盖 launch_phase。

每条流提供安装开始/完成/失败、缓冲容量、丢失数、记录器错误数、退出末态或明确缺失原因。若有线程/进程间排序，先记录时钟测量方法与误差界；同源时钟不自动意味着采样误差已知。

历史 batch-02 的普通 phase 都是 first-exit，call 记录为 enter/return 等。读旧数据时按 PID 与驱动结果映射，并记录派生规则；禁止回填覆盖原始日志。

## 3. L3 子步骤扩展清单

以下都属于**待实现或按失败需要启用**，不算 batch-02 已覆盖：

- WindowLifecycleCoordinator.shutdown_resources 与关键子步骤；
- LibraryService.close、_run_owned_teardown；
- DatabaseManager.close/close_library 和写闸门等待边界；
- 实际参与退出的 Runtime.close/close_adapters、session drain、event router drain；
- LAN stop、导入池与隧道停止；
- _save_window_geometry 与必要启动/恢复边界。

目标方法可能经惰性导入获得。每一挂点必须核对模块版本、方法身份与代码对象，记录安装清单，不能为了挂点提前导入生产模块或替换方法。挂点失败即标缺失。只启用选定 code 的局部事件，不启用全局追踪。

不在所有正常轮默认加载所有扩展；先按失败区间选最少必要点，并将观察条件变化登记为新版本。方法进入与返回的嵌套关系按真实序号呈现，不能排序成预设“漂亮链条”。

## 4. 失败保全与健康判读

| 情况 | 当前证据 | 下一版要求 |
|---|---|---|
| O1 正常退出 | 8 相 final-flush，status 有终止记录 | 保持分 PID 文件与完整序号校验 |
| O1 超时导出 | 正式矩阵没有 export-ack/events-export | 专用可靠性场景实际请求并核对 ack、序号、文件与响应截止时间 |
| O2 正常退出 | 流连续，末条 WM_DESTROY；status 留在较早心跳 | 最终状态与最后序号可对齐；若未产生末态明确标“终止健康未知” |
| GUI 卡住 | 可能无法处理 Qt 回调 | 导出/探活不能只依赖 Qt 主线程 |
| 观察器锁卡住 | 最后一个健康计数可能仍为零 | 外部检查进度与截止时间；失联即不完整，不能推出“零事件” |
| 缓冲溢出/写盘失败 | 正常轮未发生 | 明确计数、错误与退出状态；禁止静默当完整流 |
| 前台竞争 | 只有首尾 PID 与输入点快照 | 增加局部事件轨迹和已知干预回执，标明覆盖范围与盲区 |

独立导出线程仍可能与记录器共用锁，不能只因线程独立就认为不会被卡住。用可控锁停顿验证外部失败报告；不要求在记录器本身失效时还能恢复不存在的事件。

## 5. 分层判读

1. 输入生成有记录、原生/Qt 无记录：先查插件安装、日志健康、目标身份和覆盖范围；不能归生产退出缺陷。
2. 原生键消息存在、Qt 输入缺失：核对过滤器覆盖、接收 HWND、Qt 焦点与健康；不能直接归责外部应用。
3. Qt 键事件存在、Shortcut 缺失：查上下文、修饰键和事件消费；不自动注册全局快捷键。
4. Shortcut 存在、request_exit 缺失：用独立事件记录核对绑定、接收者与调用挂点。
5. 退出已进入、子步骤未结束：保全 ENTER/RETURN/进度和目标线程栈，明确等待的所有者；未返回不自动等于死锁。
6. GUI 子进程已结束、onefile 父进程未结束：查父进程等待/清理，不归 QAction。
7. 最小化/失焦相邻：记录先后和覆盖；前台占据者不等于触发者，时间相邻也不是因果证明。

## 6. 验收要求

所有可靠性用例在合成运行域执行。历史通过与下一版验证分开；正常流、超时流、记录器故障、导出失败、进程提前结束都要有可解释结果。只有上述门槛满足，才进入[下周有限前台干预](../plans/week-2026-09-14-exit-workpack.md)。
