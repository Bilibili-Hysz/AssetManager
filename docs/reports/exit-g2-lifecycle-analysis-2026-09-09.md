# G2 生命周期时序与退出链分析：间歇性 Ctrl+Q 失效（2026-09-09）

> 执行线：G2（Qt 生命周期与事件链合同线）。只读代码分析，未运行 GUI，未修改任何生产/测试文件。
> 分析对象：`D:/~Vibe-Coding/Projects/AssetsManager_old-bak/.pytest-tmp-lead-snapshots/g2-analysis` 内的生产代码快照。
> 依据：[G3/G2 联合定位方案](../plans/exit-g3-g2-investigation-plan-2026-09-09.md)、[顽疾工作包](../plans/stubborn-exit-investigation-2026-09-08.md)、[退出验收驱动修复报告](exit-repair-2026-09-08.md)。
> 配套文档：[事件链采集合同](exit-g2-event-contract-2026-09-09.md)。

## 1. 启动到退出全周期时序（文字时序图）

以"外部驱动发 Enter 打开库 → W6 负载 → Ctrl+Q 退出 → 重启"为完整周期。所有编号步骤默认在 **GUI 线程**（Qt 主线程）执行；例外单独标注。

### 1.1 阶段 A：进程启动（GUI 线程，事件循环启动前）

```
A1  run.py: __main__ → faulthandler.enable → import AssetsManager.app.main
A2  app.main():
    - install_crash_handler()
    - QApplication(sys.argv)（创建 Qt 事件循环对象，GUI 线程）
    - i18n.init()
    - _bind_single_instance(app):
        * _acquire_single_instance_owner_lock → LibraryLock(QLockFile 磁盘租约)  [GUI 线程，同步]
        * app.aboutToQuit.connect(owner_lock.release)          ← 退出链挂点①
        * QLocalServer.listen + _wire_probe_echo（newConnection→echo）
    - ApplicationBootstrap 创建（服务容器，不含窗口）
    - SystemTrayManager 构造：QSystemTrayIcon.show()（若系统托盘可用）
    - StartupWindow() 构造（QMainWindow；__init__ 内同步完成 _setup_ui/_populate）
    - startup.library_opened.connect(_on_open)
    - QTimer.singleShot(0, _deferred_startup)  ← 排队到事件循环（插件发现 + GL 预热）
    - return app.exec()  → GUI 线程进入事件循环
```

线程归属要点：
- 上述全部为 GUI 线程同步代码；`QApplication` 构造后、`app.exec()` 前没有任何窗口 `show()`。
- `_deferred_startup`（插件发现、GL 预热）在事件循环的第一个 0ms 定时器回调里**同步跑完**；`app.py` 注释明确"Qt 不能在槽执行期间投递用户输入"，因此 `_on_open`（唯一消费者）不可能在发现完成前触发。

### 1.2 阶段 B：打开库 → MainWindow 交接（全部 GUI 线程，一次同步调用栈内）

```
B1  StartupWindow._accept(path)                    [dialogs/startup.py:773]
    - _save_recent(path)（磁盘写 settings）
    - library_opened.emit(path)   ── 同步直连 ──►
B2  app.main()._on_open(path)                      [app.py:334]
    - window = MainWindow(bootstrap)              [window.py:222]
        构造内顺序（关键时序）：
        B2.1  super().__init__()；setWindowTitle；resize(1200x800)
        B2.2  _bg_* / _startup_anim 预置（防 resizeEvent 早触发崩溃）
        B2.3  _restore_window_geometry(self)
              - restoreGeometry(hex)              ← 首次几何
              - self._pending_maximized = settings["window_maximized"]  ← 只记标志，不立即最大化
        B2.4  _setup_ui()：菜单栏/QAction(含 menu.exit→request_exit)/中央区/两个 dock/状态栏
              - _setup_menu → _register_window_shortcuts
                → ShortcutManager.register_action(_menu_act_exit, "Ctrl+Q", ...)
                → action.setShortcut(QKeySequence("Ctrl+Q"))
                  ── Ctrl+Q 在此挂到 QAction 上，WindowShortcut 上下文（QAction 默认）──
              - _restore_dock_layout / _restore_workspace_tabs
        B2.5  if _pending_maximized: showMaximized()   ← 恢复相"最大化"的唯一生产路径（window.py:270-272）
              （showMaximized 触发 showEvent→启动淡入动画、resizeEvent→_bg_resize_timer）
        B2.6  _bind_plugin_host / _connect_bus / _force_quit=False / LAN 端口注入（惰性）
    - window._workspace.add_library(path)（发 library_switched→switch_library，同步）
    - window.show()                                ← StartupWindow 仍可见
    - QTimer.singleShot(0, 崩溃对话框)（可选）
    - window._tray_manager = tray
    - startup.close()                              ← StartupWindow 关闭（closeEvent 断开 bus 连接；不 deleteLater）
    - auto_start（若 lan_auto_start）: QTimer.singleShot(1000, _start_sharing_later)
```

**交接顺序结论：MainWindow.show() → StartupWindow.close()，中间没有 hide-to-tray 语义**（StartupWindow 的 closeEvent 不含 tray 判断，`has_tray` 分支只在 `MainWindow.closeEvent`）。StartupWindow 关闭后作为 Python 局部对象仍存活（`app.main` 闭包持有 `startup` 引用），但 Qt 可见性为 hidden。

原生焦点一致性风险点（B 阶段）：
- B2.5 `showMaximized()` 与 B2.6 `window.show()` 之间，StartupWindow 仍是原生前台窗口；MainWindow 的 HWND 已创建（showMaximized 即创建原生窗口）但激活顺序由 Qt/OS 决定，代码里没有任何 `activateWindow()`/`raise_()` 调用。
- `_on_open` 全程是一个同步槽：从 `library_opened.emit` 到 `startup.close()` 返回之间，GUI 线程不处理任何用户输入（Qt 事件循环被占用），原生消息（含键盘）只能排队。**W6 重启相在此栈内**：Enter 键的 keyPressEvent → `_accept` → 上述全链，直到栈返回事件循环，Ctrl+Q 才有被处理的机会。这是"重启相窗口恢复时序竞态"假设的代码基础（见 §5 H1）。
- `StartupWindow.showEvent` 会把 Qt 键盘焦点设到列表卡片（`target.setFocus()`）；MainWindow.show 后 Qt 焦点应迁移，但原生焦点窗口与 `QApplication.focusWindow()` 在 B 阶段中段可能短暂不一致（无生产代码显式对齐）。

### 1.3 阶段 C：延迟启动 LAN（若 auto_start）

```
C1  QTimer.singleShot(1000) 到期                    [GUI 线程]
    - shiboken6.isValid(target) 检查（窗口可能已销毁）
    - target._toggle_sharing()
        - security_preflight 快照 + 可能的模态确认框（QMessageBox.exec —— 阻塞 GUI 线程直至用户/超时）
        - LAN server start：后台线程（web.AppRunner + aiohttp 线程）
        - （cloudflared 隧道为子进程，独立）
```

LAN 启动本身在 LAN 专用线程；`_toggle_sharing` 的前置检查/模态框在 GUI 线程。

### 1.4 阶段 D：Ctrl+Q 退出（详见 §2 调用链合同）

```
D1  Ctrl+Q QAction 触发 → request_exit → close → closeEvent
D2  shutdown_resources（面板停机、LAN stop、几何保存）
D3  super().closeEvent → QWidget 销毁序列 → lastWindowClosed
D4  app.exec() 返回 → aboutToQuit（owner_lock.release 等）→ 解释器 teardown
D5  onefile 模式：GUI 子进程退出后，父进程（bootloader）做解包目录清理再退出
```

### 1.5 阶段 E：重启（W6 重启相 = 重复 A→D，差异点如下）

- 单实例 QLockFile 租约：上一进程退出时 `aboutToQuit → owner_lock.release`；若上一进程被强杀（超时清理），租约靠 OS 释放（`LibraryLock` 用 OpenProcess 探活，`core/library_lock.py:35-45`）。
- `_pending_maximized` 从磁盘恢复 `window_maximized=true` → B2.5 `showMaximized()`。
- 历史失败集中在重启相（observed-08、final-matrix-native-focus/onefile-maximized-3），与 B 阶段时序最重的路径重合。

## 2. 退出调用链合同（逐级：同步性/线程/阻塞点/保护机制）

调用链主线（GUI 线程，全部同步，除非单独标注）：

| # | 层级 | 生产挂点 | 同步/异步 | 线程 | 可能阻塞点 | 已有超时/保护 |
|---|---|---|---|---|---|---|
| 1 | Shortcut 触发 | `_menu_act_exit` QAction（`window.py:501` `addAction(tr("menu.exit"), self.request_exit)`；快捷键经 `shortcut_manager.py:127` `action.setShortcut(QKeySequence("Ctrl+Q"))`） | 同步信号 | GUI | 无 | — |
| 2 | `request_exit` | `window.py:1649`：`self._force_quit = True; self.close()` | 同步 | GUI | 无 | — |
| 3 | `closeEvent` 入口 | `window.py:1675`：`has_tray and not _force_quit` 分支——**Ctrl+Q 路径必为 False**（`_force_quit=True`），跳过 hide-to-tray | 同步 | GUI | 无 | — |
| 4a | `_shutdown_resources` → `_share_status_timer.stop()` | `window.py:1667` | 同步 | GUI | 无 | — |
| 4b | `lifecycle_coordinator.shutdown_resources` | `window_lifecycle_coordinator.py:379` | 同步 | GUI | 见 4b-1..4b-6 | 每步独立 try/except，首错记录后继续 |
| 4b-1 | LAN stop | `cleanup_lan` → `lan_server.stop()`（`lan/__init__.py:140` → `server_lifecycle.py:73`） | 同步等待 | GUI 线程**等待** LAN 线程 | aiohttp 关闭 future（`future.result(timeout=8)` ×可能重试一次）、`thread.join(timeout=8)`、`_lifecycle_lock` 竞争 | 每处 8s 超时；超时→`lifecycle_state="failed"` 并 raise（被 4b 外层捕获） |
| 4b-2 | 隧道 stop | `stop_tunnel` → `tunnel.py:350` | 同步 | GUI | cloudflared 子进程 `terminate→wait(5)`，失败 `kill→wait(5)` | 5s+5s 超时，吞异常 |
| 4b-3 | import pool 清理 | `cleanup_import` → `BoundedPool.close(3000)`（`workers.py:161`） | 同步等待 | GUI 等待 worker | `pool.waitForDone(3000)` | 3s 超时；超时后台 daemon reaper 接管，**不阻塞调用方** |
| 4b-4 | 面板 shutdown ×3 | info/sidebar/tag_tree（`SHUTDOWN_BEFORE_SAVE_PANELS`）→ 各自 `shutdown()`：停 QTimer、`prepare_library_switch`、`_invalidate_async_requests` | 同步 | GUI | info 面板 `_layout_save_timer` 落盘；均为本地操作 | try/except 逐面板 |
| 4b-5 | dock/workspace 状态保存 | `_save_dock_layout`（`saveState` hex 落盘）+ `_save_workspace_tabs` | 同步 | GUI | AppSettings.save() 磁盘写 | try/except |
| 4b-6 | file_list shutdown | `_base.py:145`：关 cover-scan pool、停 5 个 QTimer、断 bus、fs watcher removePaths、`_loader.wait_for_runtime(generation)` | 同步 | GUI | loader 线程合并等待（`wait_for_runtime`） | generation 失效机制 |
| 4c | `_save_window_geometry` | `window.py:112`：**若 isMaximized() → showNormal()**（原生还原到普通几何）→ saveGeometry → 落盘 `window_maximized=False` | 同步 | GUI | AppSettings.save 磁盘写 | try/except |
| 5 | `super().closeEvent(event)` | QWidget/QMainWindow 基类（`window.py:1693`） | 同步 | GUI | C++ 销毁子窗口 | try/except |
| 6 | `_library_service().close()` | `library_service.py:1367`：`_lifecycle` 条件锁 `wait_for(not _closing)`、逐 session `_run_owned_teardown`、`self._db.close()` | 同步 | GUI | **`wait_for` 无超时参数**（见下）；SQLite 关闭；session teardown 内部 IO | 会抛 `RuntimeError("Cannot close from an active operation")`；close 内各 session teardown 有 try/except；**条件等待本身未见超时** |
| 7 | lastWindowClosed → exec 返回 | QApplication 默认 `quitOnLastWindowClosed=True`（生产代码未改） | 事件驱动 | GUI | 无可见窗口时 quit；**StartupWindow 已 hidden 未销毁——隐藏窗口不触发 lastWindowClosed**，依赖 MainWindow close 后无可见窗口 | — |
| 8 | aboutToQuit | `app.py:135` `owner_lock.release`（QLockFile 释放）；tray/signal bus 清理 | 同步 | GUI | QLockFile.release 磁盘操作 | — |
| 9 | 进程结束 | `app.exec()` 返回 → run.py `sys.exit(main())` → 解释器 teardown（daemon 线程被丢弃；BoundedPool reaper 是 daemon） | 同步 | 主线程 | daemon 线程不 join；onefile 下另有 bootloader 父进程清理临时目录 | — |
| 10 | onefile 父进程退出 | PyInstaller bootloader（非本仓库代码） | 外部 | 父进程 | 等待 GUI 子进程 + 解包目录清理 | 外部观测层（退出码/父子进程时间差） |

**判定"方法未返回 ≠ 死锁"所需判据**（对齐方案 §4"退出调用"层）：
1. 4b-1 LAN stop 有两条 8s 硬超时 + join(8)；两轮合计理论 ≤~34s 可超限 30s 验收窗口，但超时**必然 raise** 并被外层捕获打印 `Resource shutdown failed`，随后链路继续——所以"Qt 零键记录 + 事后仍处理窗口事件"与"卡在 LAN stop"矛盾（LAN stop 期间 GUI 线程被占用，无法处理任何窗口事件，除非卡在无超时的 `wait_for`）。
2. `library_service.close()` 的 `wait_for(...)` 是**无超时条件等待**（`library_service.py:1373/1379`）——这是退出链中唯一没有显式超时的同步等待；若 `_closing`/`_closing_roots`/`_restore_reservations` 卡住，GUI 线程会无限期停在 6 号位，且**期间不处理任何 Qt 事件**，与 observed-08"超时后 Qt 仍持续处理焦点/状态事件"不符。
3. 因此判据是：**进入标记（sys.monitoring code 事件/方法包装记录）+ 30s 窗口内后续进度事件（aboutToQuit/quit 信号/窗口事件）+ 超时后线程栈**三者组合；仅"closeEvent 未返回"不能区分正常慢清理与死锁（方案 §6 第 5 行原文）。
4. 特别的程序性出口：`app._on_open` 重开库时先 `window._force_quit=True; window.close()`——closeEvent 走真退出分支执行完整 `shutdown_resources`；成功后**不调用 app.quit**（依赖 closeEvent 尾部正常路径）。teardown_failed 时才显式 `app.quit()`（`window.py:1702-1709`）。

## 3. 窗口状态四象限：读/写位置与时机

区分四个状态轴：Qt 窗口状态标志（isMaximized/isMinimized/windowState）｜原生 IsZoomed/IsIconic（WS_MAXIMIZE/WS_MINIMIZE）｜QWidget 可见性（isVisible/isHidden）｜HWND 可见性（IsWindowVisible）。

| 状态轴 | 生产读写点 | 时机 | 说明 |
|---|---|---|---|
| Qt `window_maximized` 持久标志 | 写：`window.py:125`（`_save_window_geometry`，读 `isMaximized()` 后写 settings）；读：`window.py:161`（`_restore_window_geometry`）→ B2.5 `showMaximized()`（`window.py:272`） | 退出时写、构造时读 | 唯一的自致最大化/还原对：退出 4c 的 `showNormal()` + 启动 B2.5 的 `showMaximized()` |
| Qt `showNormal()` | `window.py:123`（`_save_window_geometry` 内，仅当 `was_maximized`） | closeEvent→4c | **保存几何前的临时还原**；进程随后即退出，用户不可见 |
| Qt `showMaximized()` | `window.py:272`（构造尾） | B2.5 | 恢复相唯一最大化入口 |
| 原生 IsZoomed | 生产代码**零直接访问**（只在 W6 驱动/诊断脚本用 ctypes 查询） | — | 见 §4 自致最小化检索 |
| 原生 IsIconic | 生产代码**零直接访问** | — | 同上 |
| `QWidget.hide()` | `window.py:1680`（closeEvent 的 hide-to-tray 分支，**Ctrl+Q 路径不执行**）；另有 dock/子面板级 setVisible（非顶层窗口） | close(非退出) | hide 后 HWND IsWindowVisible=false 但窗口未销毁 |
| `QWidget.show()` | `app.py:405`（MainWindow 首次显示）、`app.py:461`（托盘恢复 `_tray_show`：`window.show()` 或 `startup.show()`） | B2 后 | 托盘恢复**只调 show()**，不 showNormal/showMaximized——若曾最大化，Qt 记忆的 maximized 标志由 show() 尊重，但原生状态取决于 hide 时的快照 |
| HWND 可见性 | 生产代码零直接访问（无 IsWindowVisible/ShowWindow ctypes 调用） | — | 只有 W6 驱动 `scripts/perf/w6_package_functional.py:415` 有 `ShowWindow(hwnd, SW_SHOW)`（`_restore_window`，仅 `--observe-hide` 诊断模式） |

**hide 与 show 的 Qt/原生分裂风险**：`QWidget.hide()` 之后再被外部 `ShowWindow(SW_SHOW)`（如 W6 `--observe-hide` 模式，驱动注释 `w6_package_functional.py:938` 明确记载）会出现"HWND 可见而 QWidget 仍 hidden"的分裂态。正式验收路径不用 `--observe-hide`，但该事实证明两轴可独立漂移——观察器必须同时记录两轴，不能互推。

## 4. 自致最小化路径检索结论

**问题：有没有任何代码路径会调用 showMinimized / setWindowState(Qt.WindowMinimized) / SW_MINIMIZE？**

**结论：未发现。** 生产代码与随包测试代码均不存在任何自致最小化路径。检索范围与方式：

| 检索范围 | 检索内容 | 结果 |
|---|---|---|
| `AssetsManager/`（全部 .py，含 panels/widgets/dialogs/lan/core/application） | `showMinimized`、`setWindowState`、`Qt.WindowMinimized`、`WindowMinimized`、`SW_MINIMIZE`、`SW_SHOWMINIMIZED`、`ShowWindow`、`CloseWindow`、`minimize/minimi[sz]`（不区分大小写） | 零命中（"minimize" 命中仅为托盘提示文案与图标名 `"minimize": '<path d="M5 12h14"/>'`，`core/icons.py:61`，SVG 路径数据非行为） |
| `Plugins/`（booth_link/download_tracker） | 同上 | 零命中 |
| `main.py`、`run.py` | 同上 | 零命中 |
| 生产代码中的 Win32 API 引用 | `ctypes/windll/user32` 全文排查 | 命中仅四处且均与窗口状态无关：`library_export_io.py`（路径长度 API）、`undo_service.py`（OpenProcess 探活）、`database.py`（FlushFileBuffers）、`library_lock.py`（OpenProcess 探活）。**没有任何 user32 窗口/消息 API 调用** |
| `scripts/perf/w6_package_functional.py`（正式 W6 驱动，非生产代码） | `ShowWindow` | 仅 `_restore_window` 中 `ShowWindow(hwnd, 5 /* SW_SHOW */)`，且**只在 `--observe-hide` 诊断模式**执行；SW_SHOW 保持现状不最小化/不还原。`_focus_window` 明确注释"never shows, restores"。正式验收路径不调用 `_restore_window` |

因此：**失败现场的 IsIconic=true 不可能由本应用生产代码或正式 W6 驱动主动造成**。最小化的来源只能在这几类外部实体中：OS 外壳（如 Win+D/Win+M、任务栏操作）、其他前台应用（QQ.exe 两次占据失败现场前台，但其行为责任未知——本分析按方案不预设其角色）、onefile bootloader 的窗口归属交互、或输入注入本身引发的系统行为。按方案 §6"最小化/失焦与输入相邻"行：触发来源在获得消息级证据前保持未知，不可从前台 PID 直接归责。

## 5. 间歇性候选机制假设登记（只登记，不预设）

以下假设均以"Ctrl+Q 四相完美（原生焦点/可见/最大化/无预按键全对）但 Qt 零键记录 + 超时后 IsIconic=true"为待解释现象。每个假设给出：代码证据、缺失观测、最小区分实验。**不把 QQ、退出死锁、扫描码预设为根因。**

### H1 重启相窗口恢复时序竞态（showMaximized 同步栈内输入丢失）

- **机制**：重启相 Enter 打开库后，`_on_open` 在一个同步调用栈内完成 MainWindow 构造（含 B2.5 `showMaximized()`、showEvent→淡入动画、resizeEvent→`_bg_resize_timer.start()`）→ show → workspace add_library（同步 switch_library）→ `startup.close()`。若外部 Ctrl+Q 在该栈执行期间到达（W6 驱动在负载后即发键，等待窗口出现的判定只查原生可见性），键消息排队于 GUI 线程消息队列；栈返回后 Qt 需先处理 show 引发的原生激活/绘制消息序列。若在此窗口期发生**最小化**（外部触发），恢复最大化的后续原生消息（如 WM_SIZE/WM_ACTIVATE）与排队的键事件次序取决于系统，Qt 的快捷键匹配要求"接收键时焦点窗口为含该 QAction 的窗口"——焦点窗口瞬变（StartupWindow 关闭、MainWindow 激活未完成、又最小化）可能使 KeyPress 被丢弃或投给已 hidden 的 StartupWindow（其无 Ctrl+Q action），而事件不被记录为"Shortcut 歧义"，Qt eventFilter 亦可能根本收不到（observed-08 观察器靠 Qt 事件，零记录意味着事件未进 Qt 或进的是另一窗口）。
- **代码证据**：B 阶段无 `activateWindow()`/`raise_()` 对齐原生与 Qt 焦点；`startup.close()` 在 `window.show()` 之后、同栈内（`app.py:405/430`）；`showMaximized` 在构造尾（`window.py:272`）先于 `_on_open` 后续步骤；`_bg_resize_timer` 150ms 后还会再触发一轮 GUI 工作。
- **缺失观测**：B 阶段毫秒级的原生激活消息序列（WM_ACTIVATE/WM_SIZE/WM_SETFOCUS）与键消息的相对次序；Qt focusWindow 在键到达瞬间的值（observed-08 未记录 focusWindow 快照与键的配对）。
- **最小区分实验**：O1 条件下在 `app._on_open` 入口/出口、`startup.close()` 前后、`showMaximized()` 前后打点（sys.monitoring code 事件），配合外部原生消息钩子记录 WM_KEYDOWN 相对次序；若失败样本中 Ctrl 的 WM_KEYDOWN 早于 MainWindow 完成激活（或落在 StartupWindow 生命周期内），支持 H1。

### H2 最小化与快捷键 context 的交互（最小化窗口的 WindowShortcut 不触发）

- **机制**：`_menu_act_exit` 的快捷键走 QAction 默认 `Qt::WindowShortcut` 上下文——只在其父窗口（MainWindow）为活动窗口时匹配。**Qt 对最小化窗口的键盘事件处理**：原生 IsIconic 状态下系统通常把键投给前台窗口；若 MainWindow 已最小化且无其他前台者，Qt 侧 shortcut 匹配可能静默不命中。observed-08 现场正是"Qt 零键记录 + IsIconic=true"——若最小化发生在**发键之前**的极短窗口（四相采样在发键前一刻为最大化，但采样是离散的），则键进入系统后前台/焦点已换，Qt 不产生 KeyPress 记录。四相完美只约束采样时刻，不约束采样后到实际投递的间隙。
- **代码证据**：`shortcut_manager.py:127` `action.setShortcut(...)` 未设置 ShortcutContext（默认 WindowShortcut）；历史报告记载"输入阶段 GetGUIThreadInfo active/focus 均为目标、flags=0、未最小化；超时后 IsIconic=true"（exit-repair-2026-09-08.md:55）——**最小化必然发生在发键采样与超时判定之间**，而生产代码无自致最小化（§4），即最小化在本窗口内由外部触发且未留应用内痕迹。
- **缺失观测**：最小化的精确时刻与触发消息（WM_SYSCOMMAND SC_MINIMIZE？SC_HOTKEY？外部 ShowWindow(SW_MINIMIZE)?）——应用内过滤器看不到原生消息（方案 §4 原生窗口消息层判读边界）；最小化与 Ctrl/Q 消息的相对次序。
- **最小区分实验**：observed-14 式原生消息记录（SendMessage/ GetMessageHook 或 WH_CALLWNDPROC 目标进程钩子）+ IsIconic 事件级采样：捕获 WM_SYSCOMMAND(SC_MINIMIZE) 或对应消息的时刻与发送者线程/进程 ID。若最小化先于 Q 的 WM_KEYDOWN，H2 成立且链路是"输入被最小化夺走"；若最小化后于 Q 的 WM_KEYDOWN 且 Qt 仍零记录，H2 被削弱、指向 H1/H3。

### H3 输入队列与 Qt 事件处理不同步（消息在队列被合并/丢弃）

- **机制**：Windows 键盘输入对最小化/非活动窗口走低位优先级（WM_KEYDOWN 可能进队列但被系统在窗口最小化时降级或与其它消息合并）；Qt 在 Windows 上经 QPA 消息泵翻译 WM_KEYDOWN→QKeyEvent，翻译依赖焦点窗口表。若消息到达时 Qt 焦点映射处于过渡态（StartupWindow 关闭/MainWindow 激活竞争），QKeyEvent 可能构造后因无接收者被丢弃（不会出现在任何 eventFilter 里，因为过滤器只挂在已注册对象上）。该机制不需要任何生产代码缺陷，是纯平台时序假设。
- **代码证据**：间接——observed-08 中"后续仍持续处理焦点与窗口状态事件"证明 GUI 线程活着且在处理事件，但键类事件零记录；生产端 Ctrl+Q 注册唯一、无歧义注册（方案已审查"未发现重复注册"）。
- **缺失观测**：目标线程消息队列的原生消息级记录（GetMessage 顺序、消息被谁取走）；Qt focusWindow/activeWindow 与每个到达的 QEvent 的配对。
- **最小区分实验**：外部 WH_JOURNALRECORD 或目标进程专用消息钩子记录 Ctrl/Q WM_KEYDOWN 是否进入目标线程队列及取出时刻；应用内同时记录 Qt focusWindow 序列。键消息在队列中存在但 Qt 零记录 → 支持 H3；键消息不在队列 → 转向输入生成层（G1 范围）。

### H4 onefile 父进程/子进程窗口归属竞态

- **机制**：onefile 模式 GUI 是 bootloader 的子进程；历史失败全部发生在 onefile+最大化（onedir 无失败记录）。若最小化与退出探测窗口期存在父子进程交互（bootloader 控制台句柄继承、父子共享输入桌面差异导致 AttachThreadInput 类行为），可能出现子进程窗口被系统判断为非前台而键降级。此假设只登记，因为失败模式与 onefile 的相关性可能只是负载差异。
- **代码证据**：仅统计相关性（历史两次失败均 onefile 最大化）；本仓库无 bootloader 源码。
- **缺失观测**：父子进程在发键窗口期的窗口/前台变化记录；onefile vs onedir 同条件失败率对照（现有矩阵 onedir 从未失败，但样本极小）。
- **最小区分实验**：O1/O2 在 onefile 与 onedir 各跑相同区组（如 2+2 周期），事件合同采集两轴状态。若 onedir 也出现"Qt 零键记录+IsIconic"，H4 削弱。

### H5 外部进程窗口管理交互（含 QQ 前台占据，责任未知）

- **机制**：两次失败现场前台占据者是 QQ.exe（PID 4212）。QQ 的窗口管理（截图热键、会话窗激活、自身前台抢夺）若恰在发键窗口内把目标最小化或夺取焦点，可解释 IsIconic 与 Qt 零记录。**按方案，QQ 在场不区分成败（G1 v2），本假设不预设其为根因**，仅登记"外部进程主动窗口操作"这一机制类。
- **代码证据**：相关性记录（v2 报告）；生产代码零相关（§4 已证明无自致最小化）。
- **缺失观测**：最小化发起者的消息源（H2 的实验同源）；QQ 在失败时刻的行为轨迹（超出本 G2 范围，归环境线）。
- **最小区分实验**：与 H2 相同的原生消息级最小化触发记录（发送者 PID/TID）；或环境对照（临时移除 QQ 的独立桌面会话跑同区组——需主代理/环境线协调，非 G2 单方面执行）。

## 6. 观察点核对（对 G3 的三条确认）

1. **Ctrl+Q 唯一注册**：生产仅 `window.py:714`（register_action → `setShortcut`）；command_palette 的 "Ctrl+Q" 字符串（`command_palette.py:608`）只是**显示用 shortcut 标签**，不注册第二个快捷键——无歧义触发基础。
2. **StartupWindow 无任何快捷键注册**——若键被投给已关闭/隐藏的 StartupWindow，不会产生任何应用内记录，与 observed-08 的零记录形态一致。观察器应覆盖 StartupWindow 的键事件（当前 observed-08 只装在主窗口相关 code 对象上）。
3. **退出链应用内可挂点**已全部列入事件合同（见配套文档 §表）。

## 7. G2 交付状态

本轮为只读代码分析（合同线）：交付生命周期时序、退出链阻塞点清单、窗口状态四象限、自致最小化检索结论（未发现）、候选机制登记。未修改任何生产/测试文件，未运行 GUI，未动主工作区。生产补丁：本轮无（无证据支持任何生产缺陷；§4 的"未发现自致最小化"反而排除了一个候选方向）。
