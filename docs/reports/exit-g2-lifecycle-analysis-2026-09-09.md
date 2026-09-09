# G2 生命周期与退出等待分析（2026-09-09 修订）

> 状态：只读分析交付；本轮无生产补丁、无 GUI 重跑。原分析由 G2 快照交付，本版根据主代理源码复核修正。
> 本文替代原版“自致最小化排除”“唯一无超时等待”等判断。具体发现与哈希见[验收复核](exit-g3-g2-acceptance-review-2026-09-09.md)。
> 配套：[采集合同](exit-g2-event-contract-2026-09-09.md)、[下周工作包](../plans/week-2026-09-14-exit-workpack.md)。

## 1. 可以由当前代码确认的主路径

启动时创建 QApplication、单实例服务与 StartupWindow；打开库后创建 MainWindow、绑定库与工作区，显示主窗口并关闭启动窗口。最大化恢复依赖保存状态。窗口创建、Qt 焦点与原生激活是不同事实，不能互作回执。

Ctrl+Q 注册到退出 QAction。MainWindow.request_exit 设置 _force_quit=True 后调用 close；closeEvent 的托盘隐藏分支要求 has_tray 且未 force_quit，因此正常 Ctrl+Q 走真实清理路径。

主路径如下，方法内部调用存在嵌套，箭头不是全部方法进入/返回的严格排列：

```text
Ctrl+Q / 退出 QAction
  → MainWindow.request_exit
    → close / closeEvent
      → _shutdown_resources
        → WindowLifecycleCoordinator.shutdown_resources
        → _save_window_geometry
      → 基类 closeEvent
      → LibraryService.close
        → session teardown / DatabaseManager.close_library
        → DatabaseManager.close
  → 最后窗口关闭相关信号
  → aboutToQuit
  → 事件循环返回及进程退出
  → onefile 父进程结束
```

清理抛出异常时，closeEvent 记录错误并继续后续步骤，必要时调用 app.quit；这不能保护没有返回或抛出的同步等待。库切换/程序性重开与整应用退出共享部分路径，修改必须同时审查两种语义。

## 2. 已证实的无超时等待与其他等待

| 等待 | 当前代码入口 | 实际含义与限制 |
|---|---|---|
| LibraryService 全局关闭互斥 | library_service.py:1379 | 等待 _closing 清除，未传 timeout |
| root/session/restore 所有权 | library_service.py:1381 | 等待 _closing_roots 与 _restore_reservations 清空，未传 timeout |
| 数据库写闸门 | database.py:523 | 等待没有 writer/readers，未传 timeout；close_library:1124 和 close:1097 进入该闸门 |
| Runtime 并发清理 | runtime.py:126、157 | close_adapters/close 内 Condition.wait 无 timeout；需沿实际监听器/适配器路径登记调用条件 |
| Session 活跃操作 | context.py:300 | 有 _FINISH_CLOSE_TIMEOUT_SECONDS；超时返回未 drain，不能据此提前关闭 DB |
| Event router drain | runtime_events.py:335 起 | 有局部 deadline；pending/closing 与 drained 不可混用 |
| LAN / 线程池 / 隧道 | server_lifecycle.py、workers.py、tunnel.py | 有若干局部超时；存在串行等待、重试和锁获取，不能直接当作端到端退出上界 |
| 磁盘与连接锁 | settings、SQLite、teardown listener | 静态调用不保证固定耗时；应按所有者和实际线程评估 |

退出链的直接反例可由源码跟踪：LibraryService._run_owned_teardown → self._db.close_library → _write_gate.write → Condition.wait_for。上述 database/library_service/runtime 与原 G2 快照哈希相同，因此原“唯一等待点”是分析遗漏。

这里没有证明历史失败触发了任一等待。observed-08 的 request_exit 未记录且后续仍有 Qt 窗口事件，对“已经进入这些清理等待”的解释不提供支持。若未来有 ENTER 无 RETURN，需结合进度与线程栈；不能仅凭未返回判死锁。

## 3. 窗口状态和最小化边界

源码检索没有发现显式 showMinimized/WindowMinimized/SW_MINIMIZE 主动调用。该结论限定为所查源码，不覆盖平台内部实现、恢复几何、系统消息及其组合路径。因此不能推出最小化必由外部进程发起，也不能从前台 PID 归责。

window.py:121–125 在还原前记录 was_maximized，临时 showNormal 后保存该原值；原报告“保存为 False”错误。隐藏到托盘走 hide；恢复通过产品显示路径。Win32 ShowWindow 可改变原生可见性而不等同于产品托盘恢复，验收必须观察 Qt 与原生状态。

close 接受事件后通常隐藏窗口，是否删除依赖 WA_DeleteOnClose 等生命周期条件；不能把 closeEvent 返回、不可见或 lastWindowClosed 当作 HWND 已销毁。aboutToQuit 在主事件循环退出前发出，而不是 exec 返回后。参考 [QWidget.close](https://doc.qt.io/qt-6/qwidget.html#close) 和 [QCoreApplication.aboutToQuit](https://doc.qt.io/qtforpython-6.8/PySide6/QtCore/QCoreApplication.html)。

## 4. 后续假设只保留可检验问题

| 方向 | 要补的证据 | 不预设的答案 |
|---|---|---|
| 启动/重启焦点交接 | 目标窗口身份、原生与 Qt 焦点、输入消息的实际顺序 | 不假定输入正在构造栈内丢失 |
| 最小化/前台交互 | 已知干预、实际生效时刻、Q 发送及接收边界 | 不以先后关系单独证明导致失败 |
| 原生到 Qt 映射 | 原生消息已见而 Qt 未见时的健康记录与接收对象 | 不预设键消息低优先级、合并或平台吞键机制 |
| onefile 生命周期 | GUI 子进程与父进程状态、退出时间及归属 | 不预设 bootloader 输入桌面或句柄竞态 |
| 外部窗口行为 | 本批自建辅助窗口干预回执；自然样本中来源仍未知 | 不操作或指认 QQ 等用户应用 |
| 清理预算 | 已进入退出调用后的子步骤、所有者释放与线程栈 | 不预设 LibraryService 是根因或唯一热点 |

原分析中的“最小化先于键消息即可确认 H2”“钩子可直接给出发起者”等判据不再使用。原生消息结构和过滤器本身不提供通用责任归属。

## 5. G2 下一交付

按工作包形成等待所有者、deadline 和失败后状态表。任何防御性修复应保持 session admission、活跃写入、restore reservation、root lock、DB 关闭与重试合同，防止超时后假关闭。没有证据支持生产变更时交评估，不强行产补丁。

本批观察器只记录 MainWindow 三个方法；LibraryService/数据库/Runtime 的细粒度挂点是后续需求，不能写成已有观测事实。
