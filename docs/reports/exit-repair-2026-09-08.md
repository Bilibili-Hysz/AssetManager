# 单文件最大化重启退出：诊断与修复（2026-09-08）

> 状态：验收驱动修复完成；最终六项受控 W6 包验收通过。历史超时的唯一根因未确定，不宣称已修复生产死锁或全部发布场景通过。
> 承接 [上一轮收口](weekly-repair-closeout-2026-09-08.md) 中 onefile 最大化重启 Ctrl+Q 30 秒超时的阻断。

## 当前结论与交接

最终驱动在关闭应用内观察插件的条件下，一次执行预先固定的六项矩阵，**6/6 通过**，包括 onefile 最大化启动→退出→重启→再退出三次。每次首次退出和重启退出均为 0；成功记录没有强制清理。评分、备注、几何与最大化状态的持久化断言均保留。此前失败未被覆盖，分别归档如下。

本轮关闭的是 W6 当前受控验收阻断，修复点位于测试驱动，生产代码和两种 EXE 均未变更。旧失败未投递样本与修后通过样本支持输入链路需要修正，但不足以将历史故障唯一归因于某个 API 或扫描码。下一步转入真实托盘恢复与活动下载场景；N3 仍需独占机器测量。

## 已确认的事实

本轮直接使用上一轮候选 EXE，未修改生产代码或重新构建：onefile SHA-256 为 `1d568fb80ef6dcb78f9d8001ea68c521367638938a3463cf2964e51960372c5a`；onedir SHA-256 为 `6afcf6635c59119f321e9e441972bb991f3cb3678110669401f87d5c72578f12`。全部运行仅使用新建合成库和独立 AM_RUNTIME_ROOT。

生产审查未发现 Ctrl+Q 的重复注册或退出标志重置。该快捷键由菜单 QAction 调用 `request_exit()`，设置 `_force_quit=True` 后正常关闭窗口，资源清理与库关闭仍按既有流程执行。

通过合成运行域内的临时插件被动记录 Qt 事件和退出调用，两轮完整观察、一轮稀疏观察均通过首次退出与最大化重启退出。稀疏观察移除了心跳和原生句柄访问，以减少观察对时序的影响。记录证明相应运行中发生了 `Shortcut → request_exit → closeEvent → shutdown_resources → lastWindowClosed → aboutToQuit`，没有发现资源关闭卡住。

随后完全关闭观察插件，分别用工作区合成目录和原始临时目录对照，两轮同样通过。因此，本轮不能把上一轮超时认定为已复现的生产死锁，也不能声称已经找到其唯一根因。此前证据缺少输入送达过程；超时后的失焦状态不能倒推出发键时的状态。

## 本轮修复范围

W6 探针原先只在发键前确认前台窗口，Ctrl 按下、Q 按下、释放之间没有目标检查，且 `keybd_event` 没有应用接收回执。输入失败与退出超时缺少可区分的原始记录。这是本轮确定修复的缺口。

修复维持真实 Ctrl+Q 与原 30 秒正常退出断言，不添加强制退出作为通过条件，不用延长超时或重复发 Q 掩盖问题。输入记录只证明原生输入阶段观察，不冒称 Qt QAction 已触发；实际应用调用链另由诊断记录证明。临时观察插件不进入发行包或用户运行域。

最终修改仅涉及 `scripts/perf/w6_package_functional.py` 及对应合同测试：

- 聚焦不再调用 `ShowWindow`，拒绝隐藏、禁用窗口，不改变待验收的窗口状态；发送前检查期望最大化状态与用户预先按住的修饰键/Q。
- Ctrl 按下后再次核查前台，失焦时不发送 Q；只释放探针自己尝试过的键。Q 之后失焦可能来自正常退出，保留不确定性并由实际退出结果判定。
- Ctrl/Q 与启动页 Enter 改为逐键 `SendInput`，保留 VK 语义，使用目标线程键盘布局取得非零扫描码；完整 INPUT 联合体在 x64 为 40 字节。插入数量不为 1、无扫描码或释放失败均不能通过，Q 不自动重发。
- 输入阶段与超时现场记录前台、窗口状态、修饰键、GUI 线程焦点；超时另保留自有进程窗口库存，区分最小化、隐藏和最大化状态。

## 验证范围

| 最终检查 | 结果 | 原始证据 |
|---|---|---|
| onedir 普通/最大化；onefile 普通/最大化 ×3 | 6/6 PASS，12 次正常退出码均为 0 | [矩阵汇总](exit-repair-2026-09-08-evidence/final-matrix-sendinput/summary.json) |
| W6 + N1 探针合同，独立源码快照 | 26 passed，1.72s | [JUnit](exit-repair-2026-09-08-evidence/final-probe-contracts.xml)、[输出](exit-repair-2026-09-08-evidence/final-probe-contracts.txt) |
| 本轮驱动和测试 Ruff / Pyright | 通过；0 errors | [Ruff](exit-repair-2026-09-08-evidence/final-ruff.txt)、[Pyright](exit-repair-2026-09-08-evidence/final-pyright.txt) |
| SendInput 真实消息对照 | 首次与重启均有非零扫描码、Qt Ctrl+Q Shortcut 与正常退出 | [observed-14](exit-repair-2026-09-08-evidence/observed-14-sendinput/qt-events.jsonl) |

最终驱动 SHA-256：`bd8142231fe874b7db4fcd90e70cad8d1ef6d71092353709297d932986237441`。矩阵目录保留执行时驱动与最终测试源码。最终复查发现测试替身直接赋值引起 Pyright 类型错误，改用 pytest monkeypatch 后重新执行上述合同与静态检查；仅测试改变，不影响已冻结 GUI 驱动。上一轮 5110 passed / 20 skipped 为当时生产修复的全量结果，不合并为本轮测试总数。

独立 Terra 复核逐个核对六份结果、正常退出码与输入插入记录，未发现阻断当前 W6 结论的问题。插入数量不是 Qt 回执；本次端到端通过依据是后续进程正常退出和持久化核对。

### 未通过的复验与调用链证据

- 首轮输入增强矩阵在 onedir 最大化退出失败：发键前原生最大化状态已改变。随后移除聚焦中的无条件 `ShowWindow`，并增加期望窗口状态校验。
- [移除 ShowWindow 后的矩阵](exit-repair-2026-09-08-evidence/final-matrix-after-focus-fix/summary.json)：onedir 普通、onedir 最大化、onefile 普通通过；onefile 最大化第 1 次的重启退出超时，剩余两次按预定规则未运行。成功案例不抵消失败案例。
- [observed-08 原包复现](exit-repair-2026-09-08-evidence/observed-08-monitoring/onefile-maximized.json) 使用本地 `sys.monitoring` code 事件，未替换生产方法对象，也未提前导入主窗口。[Qt 调用记录](exit-repair-2026-09-08-evidence/observed-08-monitoring/qt-events.jsonl) 显示首次退出有完整 Shortcut/退出/资源关闭/quit 信号；重启发键后没有 Ctrl/Q 的 Qt 键事件、Shortcut 或 `request_exit`，但后续仍持续处理焦点与窗口状态事件。当前记录不支持将该次失败归因于退出清理死锁。
- 该次重启输入四个阶段都记录前台为目标、visible/enabled/maximized 为 true、无预先按住的修饰键；超时后自有进程窗口库存没有可见模态对话框。前台窗口成立仍不足以证明键盘输入已送达 Qt，因此后续补查原生线程焦点与消息接收。
- 原生消息观察 observed-09–12 共四次通过；关闭插件的 unobserved-13 也通过。它们属于诊断对照，不抵消后续失败。
- [原生焦点矩阵](exit-repair-2026-09-08-evidence/final-matrix-native-focus/summary.json) 前五项通过，最后 onefile 最大化第 3 次的重启退出超时。此次输入阶段 `GetGUIThreadInfo` 的 active/focus 均为目标 HWND、flags 为 0；没有 capture/menu/move-size，也未最小化。超时后 `IsIconic=true`，说明当时窗口最小化，不能再把 `IsZoomed=false` 解读为清理中的 showNormal。探针源码 SHA-256 为 `f989e271d1a6c7546b76f8a1aed513ae1cd87fcaca4616f8705380b60f435d6e`，原文件随矩阵归档。

### 输入接口修正依据

现有 `keybd_event` 没有返回值，探针无法确认插入数量，而且输入扫描码一直为 0。改用 `SendInput` 并检查插入数量，可以把明确的输入失败与应用退出超时区分开；成功插入仍不等于 Qt 已接收。此变更有独立的验收可靠性价值，尚不把旧接口认定为历史间歇性失败的唯一原因。接口依据：[Microsoft keybd_event](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-keybd_event)、[SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)。

## 仍保留的边界

- 成功对照不能抹去历史无效运行；历史记录保留在上一轮证据目录。
- 不把键盘输入观察等同于 Qt 接收确认，也不把失焦当作通过。
- 本轮不包含真实托盘恢复、浏览器实时订阅或 N3 容量测量。
- 所有修复保持未提交、未推送。
