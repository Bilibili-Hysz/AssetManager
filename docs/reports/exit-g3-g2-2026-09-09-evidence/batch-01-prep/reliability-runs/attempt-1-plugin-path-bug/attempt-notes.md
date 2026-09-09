# 尝试记录（保留失败证据，不做"重试直到通过"）

- attempt-1 (normal-exit): 控制器把插件装到 run_dir/runtime，而驱动
  mkdtemp 重定向后的真实运行域是 run_dir/synthetic/runtime → exe 未加载
  观察器；驱动本身 PASS（exit 0），但零 Qt 事件。缺陷：控制器安装路径。
- attempt-2 (normal-exit): 修正安装路径后，控制器预种子
  (run_dir/synthetic/{library,runtime}) 与驱动 main() 内再次
  _build_library/_seed_runtime 冲突 → FileExistsError，驱动 exit 1。
  缺陷：控制器不应预建 library；插件安装应在运行域确定后进行。

修正方案（attempt-3）：控制器不再预建 library/runtime；改为监听驱动
stdout 的 "settings seeded:" 行获得真实运行域路径，再向该域的
Shared/plugins 复制插件——这发生在 exe 启动之前（驱动在种子之后才
Popen exe），插件加载时已在位。

- attempt-3 (normal-exit): shim 字面量路径拼接 bug（str / str）→ 驱动
  mkdtemp 重定向抛 TypeError。缺陷：shim 模板，已修（_P() 包裹）。
- attempt-4 (normal-exit): 插件已正确装入 exe 实际使用的运行域
  （runtime/Shared/plugins/exit-observer + __pycache__ 证明已被加载执行），
  但 exe 的 /api/info 180 秒未就绪 → 驱动 INVALID: /api/info never
  returned 200。可能原因：a) 环境性慢启动（onefile 解压 + 端口绑定慢）；
  b) 本机当时资源紧张。非插件路径问题（插件已被 Python 编译加载）。
  待验证是否稳定可重现；若重现则检查观察器是否在 register() 阶段
  阻塞（_Recorder 构造/emit 同步写状态文件不应阻塞——需要复跑证据）。

- attempt-4/5/6 (normal-exit): stdout 改文件重定向后驱动不再死锁，但三轮一致
  复现：exe GUI 窗口出现（"AssetManager — Open Library"），GUI 线程 6 条全
  Wait、Responding=False、/api/info 从不 200、LAN 端口从未监听。
  插件已被 exe 加载（runtime __pycache__/observer.pyc 生成），说明
  挂起发生在观察器 register() 安装之后、LAN 启动之前——高度怀疑观察器
  本身在 QApplication 主线程（插件加载时机）上安装 native event filter /
  import 钩子导致 Qt 事件循环未启动或 StartupWindow 卡死。这与历史
  observed-08/14 能正常跑通的记载矛盾，需要隔离验证：跑一次无观察器
  （O0 对照）确认候选与驱动本身在本控制器环境可正常工作，再定位观察器
  内阻塞点。PID 树已用 PowerShell Stop-Process 清理（失败后清理）。

- o0-control run-1（无观察插件隔离对照）：全部功能负载通过（info/login/
  font/thumbnail/notes/live change OK），证明 attempt-4/5/6 的 GUI 挂起
  是观察器插件引入的（同一运行域/驱动/控制器，仅去掉插件后负载全通）。
  本轮输在发键阶段：窗口在 Ctrl+Q 前被最小化（window_minimized=True，
  active=21627082 为另一窗口）→ 驱动按合同安全拒绝发送（非超时）。
  与历史失败样本"超时现场窗口已最小化"同型的桌面环境干扰，当前桌面
  存在其他前台活动。控制器 o0 分支当时因 rc 未定义崩溃（已修）。
