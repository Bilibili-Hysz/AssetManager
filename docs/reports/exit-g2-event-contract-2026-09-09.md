# G2 事件链采集合同（Ctrl+Q 失效定位 · 2026-09-09）

> 执行线：G2 合同交付物。本文把联合定位方案 §4 的六层事件表落成可执行采集规格：给出**生产代码中的具体挂点**（类/方法/信号），标明每层"应用内可见"还是"只能外部观测"，供 G3 实现观察器（O1/O2 条件）。
> 约束继承方案 §4：每条记录至少含 run_id、相位（首退/重启）、PID/TID、窗口标识、事件类型、序号、单调时间；跨进程时钟须先验证可比性。**禁止提前导入 MainWindow、替换生产方法对象、改变信号连接**（方案 §5 O1/O2 派生规则）。
> 生命周期与退出链的语义分析见配套文档：[G2 生命周期分析](exit-g2-lifecycle-analysis-2026-09-09.md)。

## 1. 总挂点表（层级 → 生产挂点 → 可见性）

可见性分三类：
- **应用内可见（Qt）**：Qt 信号/eventFilter，O1/O2 插件可在进程内记录；
- **应用内可见（sys.monitoring）**：不触碰 Qt 对象、仅靠 code 事件的局部观测（observed-08 先例）；
- **仅外部可见**：应用内插件**看不到**的边界（方案 §4 原生窗口消息层判读边界原文："应用内过滤器看不到消息，不自动证明 OS 未生成"）。

| # | 层级（方案 §4） | 生产挂点 | 观测机制 | 可见性 |
|---|---|---|---|---|
| L0 | 输入生成（Ctrl/Q down/up、扫描码、插入数量） | 无生产挂点——发生在 W6 驱动进程 | 驱动自身记录（SendInput 返回值、keybd_event 无回执） | 仅外部（驱动侧；G1 线范围） |
| L1 | 原生窗口消息（WM_KEYDOWN/UP、激活/最小化/销毁） | 无生产挂点——Qt 消息泵之前的 Windows 层 | 目标进程专用 Win32 消息钩子（observed-14 式原生过滤器 / GetQueueStatus 状态采样） | 仅外部；应用内 Qt eventFilter **无法**覆盖 |
| L2 | Qt 输入（KeyPress/Release、ShortcutOverride、Shortcut、焦点） | `MainWindow.eventFilter`（无生产实现——观察器需新建）；键事件在 QWidget 事件流内；QShortcut/QAction 匹配无信号出口 | Qt eventFilter 装在 QApplication（不预导入 MainWindow 也可以在 StartupWindow 阶段装）；ShortcutOverride/QEvent.Shortcut 在 `QApplication.notify` 层 | 应用内可见（Qt），但 **Shortcut 匹配的歧义标志/最终接收者** 无生产信号，需 eventFilter 记录 ShortcutOverride + 后续 activated；不能伪造"Qt 回执"（方案 §4 输入生成行） |
| L3 | 退出调用（request_exit/closeEvent/shutdown_resources 进出、force_quit、close 接受状态） | `AssetsManager.window.MainWindow.request_exit`（window.py:1649）；`MainWindow.closeEvent`（window.py:1675）；`MainWindow._shutdown_resources`（window.py:1667）；`WindowLifecycleCoordinator.shutdown_resources`（window_lifecycle_coordinator.py:379）；`LibraryService.close`（library_service.py:1367） | sys.monitoring 本地 code 事件（observed-08 先例：只启用目标 code，不替换方法对象）；或 Qt 无关的装饰封装（**违反方案 O1/O2 派生规则，禁止**） | 应用内可见（sys.monitoring）：**进入/返回**两点都可观测（RETURN 事件）；"方法未返回≠死锁"判据见 §4 |
| L4 | 应用终止（lastWindowClosed、aboutToQuit、子进程/父进程退出码） | `QApplication.lastWindowClosed`（生产未显式 connect——观察器可安全 connect，不改变既有连接）；`app.aboutToQuit`（生产已 connect `owner_lock.release`，app.py:135——观察器**追加** connect 即可，顺序在 owner_lock 之后，不改变行为）；`app.exec()` 返回点 = `AssetsManager.app.main` 末行 return | Qt 信号 connect（追加）；进程退出码只能外部（W6 驱动/父进程监视） | 信号部分应用内可见；退出码/onefile 父进程仅外部 |
| L5 | 窗口状态（原生 IsWindow/IsIconic/IsZoomed/可见性；Qt 状态及状态事件） | Qt 侧：`MainWindow.showEvent/resizeEvent`（window.py:362/443，生产已有，无信号出口——观察器用 QApplication 级 eventFilter 捕 QEvent.Show/WindowStateChange/Hide/Close 即可，不改生产方法）；`QWidget.windowState()` 读取可随时进行 | Qt：应用级 eventFilter + 定期采样；原生四 API（IsWindow/IsIconic/IsZoomed/IsWindowVisible）：外部 ctypes 采样（W6 驱动已具备）或应用内 ctypes 查询（只读，不改状态） | Qt 状态事件：应用内可见；原生四值：应用内可读（只读查询）+ 外部采样（超时后唯一存活通道） |

**"应用内插件看不到"的边界清单**（G3 实现时必须明确，防判读越界）：

1. L0/L1 全部：外部发送与原生消息投递/取出。observed-08 缺的正是 L1，方案已明确其"没有原生消息过滤器"是历史条件，不能当作 O1/O2 等价物。
2. Shortcut 的最终匹配决策：Qt 无"shortcut 匹配失败/成功"公共信号；eventFilter 能记录 ShortcutOverride 与 KeyPress，但**无法记录 QShortcutMap 内部匹配过程**——只能由"L2 有 KeyPress + L3 有/无 request_exit"的差集推断（方案 §6 第 3 行判读边界）。
3. 最小化/激活的原生发起者：eventFilter 能看到 QEvent.WindowStateChange（Qt 侧翻译结果），**看不到触发它的 WM_SYSCOMMAND 及其发送者 PID/TID**。
4. onefile 父进程（bootloader）的一切：应用内观察器只存在于 GUI 子进程，父进程等待/清理仅外部可见（方案 §4 应用终止行"分辨 GUI 已结束但 onefile 父进程仍未结束"）。
5. 导出机制不能依赖被观测的 GUI 主线程（方案 §4 记录可靠性节）：超时后事件导出走外部控制器/独立线程。

## 2. 分层采集规格

### L2 Qt 输入层（O1/O2 核心）

| 采集项 | 挂点 | 实现 | 备注 |
|---|---|---|---|
| Ctrl/Q KeyPress/Release | QApplication 级 eventFilter（对象=任意 watched，type=KeyPress/KeyRelease，key∈{Qt.Key_Q}，mods 含 Control） | 追加安装，不动生产 | 必须同时记录 `QApplication.focusWindow()`/`activeWindow()` 标识与事件的接收 widget（方案 §4："记录 Qt 实际 focusWindow/activeWindow；与原生焦点区别描述"） |
| ShortcutOverride | 同上（type=ShortcutOverride） | 追加 | 记录 key/mods 与 accept 状态（过滤器需只记录不消耗：return False） |
| Shortcut 激活 | 无生产信号；用 L3 request_exit 进入事件代替（sys.monitoring） | — | 不可伪造"Qt Shortcut 回执" |
| StartupWindow 覆盖 | StartupWindow 是独立 QMainWindow（dialogs/startup.py:438）——QApplication 级 eventFilter 天然覆盖，**无需预导入 MainWindow** | 追加 | 修复 observed-08 的盲区：键若被投给 StartupWindow（无快捷键），QApplication 级过滤仍能记录到 KeyPress |

安装时机约束（对齐方案 §5）：eventFilter 只能在 QApplication 存在后安装；`app.main` 内最早的稳定点在 `AssetsManager.app.main` 进入时（QApplication 构造后立即），通过 sys.monitoring 监听该函数进入或插件注入点完成，**不提前 import MainWindow**。

### L3 退出调用层（sys.monitoring code 事件清单）

每个目标记录 ENTER + RETURN（"方法未返回≠死锁"的判据=RETURN 事件缺失时需配合后续进度/线程栈，见 §4）：

| 目标 code 对象 | 位置 | 观测问题 |
|---|---|---|
| `MainWindow.request_exit` | window.py:1649 | Ctrl+Q 的直接下游 |
| `MainWindow.closeEvent` | window.py:1675 | 区分 hide-to-tray 分支（has_tray&&!_force_quit）与真退出分支；可加监听 `_force_quit` 属性读取点 |
| `MainWindow._shutdown_resources` | window.py:1667 | 进入/返回 |
| `WindowLifecycleCoordinator.shutdown_resources` | window_lifecycle_coordinator.py:379 | 同步总清理；RETURN 缺失 + 后续窗口事件存在 = 清理卡点候选（LAN stop 8s×2 / wait_for） |
| `WindowLifecycleCoordinator.cleanup_lan` 内嵌闭包 | 同上 :392 | LAN stop 的进入（注意：闭包 code 对象可用限定名区分；若不可行，用 `lan/__init__.py LanServer.stop` (:140) 与 `server_lifecycle.py stop` (:73) 作为替代挂点） |
| `LibraryService.close` | library_service.py:1367 | 退出链 6 号位；**唯一无超时 `wait_for`**（:1373/:1379）——RETURN 缺失时的重点栈位 |
| `MainWindow._save_window_geometry` | window.py:112 | 4c：含 showNormal()——**退出时唯一窗口状态改变点**，IsZoomed 采样应跨此点 |
| `MainWindow.showEvent` / `_restore_window_geometry` | window.py:362 / :144 | 启动相：showMaximized 时机（B2.5） |

sys.monitoring 配置：仅上述 code 的本地事件（方案 §5"仅启用目标 code 的本地事件，不启用全局追踪"）。

### L4 应用终止层

| 采集项 | 挂点 | 方式 |
|---|---|---|
| lastWindowClosed | `QApplication.lastWindowClosed` 信号 | 观察器追加 connect（生产未 connect，零干扰） |
| aboutToQuit | `QApplication.aboutToQuit` | 观察器追加 connect（生产已 connect owner_lock.release；追加不改变其行为；观察器回调不得假设在 owner_lock.release 之前） |
| exec 返回 / Python 退出 | `AssetsManager.app.main` RETURN（sys.monitoring）+ `run.py` 尾部 | code 事件；进程退出码只能外部 |
| onefile 父进程退出/解包清理 | 无应用内挂点 | W6 驱动/控制器记录父子进程 exit 时刻差（仅外部） |

### L5 窗口状态层

| 采集项 | 挂点 | 方式 | 频率/触发 |
|---|---|---|---|
| Qt WindowStateChange/Show/Hide/Close/ActivationChange | QApplication 级 eventFilter（type 过滤） | 应用内 | 事件驱动 |
| Qt windowState()/isMaximized/isMinimized | QGuiApplication 所有 topLevelWindows 轮询 | 应用内只读 | 事件驱动 + 定期（如 250ms） |
| 原生 IsWindow/IsIconic/IsZoomed/IsWindowVisible | QApplication.topLevelWindows 的 winId() → ctypes 只读查询 | 应用内只读（不改状态；确认无 ShowWindow 类副作用） | 与上同步 |
| 超时后现场快照 | 同上四 API | **外部**（W6 驱动 `_exit_timeout_observation` 已具备） | 30s 超时触发；应用内通道此时可能已死，导出不得依赖 Qt 主线程（方案 §4） |

时钟合同：应用内事件用 `time.perf_counter_ns()` + 周期对齐点（如每次定时器采样同时记录 `ctypes.GetTickCount64()`）与驱动侧时钟核对误差；无法对齐时只给部分序（方案 §4 跨进程时钟条款）。

## 3. 失败现场判读表 → 采集字段映射（G2 版，对应方案 §6）

| 现场（方案 §6 行） | 本合同提供的判据字段 | 不可直接推导（沿用方案） |
|---|---|---|
| 只有外部发送记录，无原生/Qt 输入 | L0 驱动回执 + L1 外部消息钩子 + L2 Qt 键事件三者交集 | 不能认定 Qt 或关闭逻辑有错 |
| 原生 Ctrl/Q 消息存在，Qt 输入缺失 | L1 WM_KEYDOWN 时刻 vs L2 KeyPress 时刻 + 焦点字段 | 不能认定外部应用吞键 |
| Qt Key/ShortcutOverride 存在，Shortcut 缺失 | L2 ShortcutOverride + L3 request_exit 差集 | 不直接加全局快捷键绕过 |
| Shortcut 存在，request_exit 缺失 | L3 ENTER 缺失 + L2 Shortcut（由 request_exit 前置推断） | 不先加无条件 app.quit |
| 退出调用进入但未完成 | L3 ENTER/RETURN 各 code + L4 lastWindowClosed/aboutToQuit + 超时后外部线程栈 | 不把窗口不可见当进程结束 |
| GUI 子进程结束，onefile 父进程仍在 | L4 应用内 quit 信号 vs 驱动侧父进程存活时刻 | 不把父进程等待归责于 QAction |
| 最小化/失焦与输入相邻 | L5 IsIconic/WindowStateChange 序列 + L1 WM_SYSCOMMAND（外部）+ L2 键事件次序 | 前台占据者≠事件发起者 |

## 4. "方法未返回 ≠ 死锁"判据（L3 执行细则）

1. 每个退出链 code 记 ENTER/RETURN + 单调时间；RETURN 缺失本身不构成死锁结论。
2. 必须并列观察：30s 窗口内是否仍有 L2 窗口事件（observed-08 形态="退出调用未进入但 GUI 活着"→ 排除死锁，指向 L2 之前）；或 L5 状态事件持续（GUI 活着但清理未返回 → 栈采样目标）。
3. 超时后先请求外部导出（不依赖 Qt 主线程），再采集目标进程线程栈（仅目标 PID）：预期热点栈位——`library_service.py` `wait_for`（无超时）、`server_lifecycle.py stop` future/join（8s 超时×可重试）、`tunnel.py stop` 子进程 wait（5s+5s）。
4. 缓冲模式：所有 L2/L5 事件先入有界内存缓冲，容量上限 + 溢出计数（方案 §4 记录可靠性）；每事件流写启动/序号/丢失数/结束状态；"无日志"与"零事件"分开标注。

## 5. 观察点对生产行为的影响面评估（供 G3 的 O0/O1/O2 对照参考）

- eventFilter 追加（L2/L5）：每个事件一次 Python 回调 + 缓冲 append；键/状态事件频率低（<10/s 量级），主要风险在启动淡入动画与 resizeEvent 高频期的 Hide/Show/WindowStateChange 洪峰——过滤应限定 window 标识（测试窗口）+ 事件类型白名单（方案 §4"采集范围限测试窗口和相关事件"）。
- sys.monitoring（L3）：局部 code 事件，成本集中在 ENTER/RETURN 转换；目标 code 全在冷路径（退出链），运行期近零。风险点是 `closeEvent` 每次 hide-to-tray close 都会触发（W6 正常路径不走该分支）。
- 信号追加 connect（L4）：两个信号各一个无操作槽，影响可忽略；注意不要打断 owner_lock.release 的既有连接顺序。
- 禁止项重申：不替换生产方法对象（早期观察器教训）、不预导入 MainWindow、不改信号连接、不改窗口状态（L5 原生查询只读）。

## 6. 交付状态

本合同为规格交付，未实现观察器（G3 线职责）。未修改任何生产/测试文件；未运行 GUI；未动主工作区。生产补丁：无（合同线无证据支持生产缺陷）。
