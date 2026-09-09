# attempt-5 归因（保留证据）

- 控制器 _pump_output 读线程在首次 read 触发 UnicodeDecodeError 后死亡
  （0xb3 字节——tasklist/GBK 输出混入），此后再无人读驱动 PIPE。
- 驱动 main() 的 print 阻塞在已满的 stdout 管道（块缓冲 8KB +
  自定义 _pump_output 未接手），驱动卡死 → /api/info 等待 180s 逻辑
  实际可能已完成但结果无法送达 → 控制器 420s 后 kill 驱动。
- exe（onefile 父 40492 + GUI 子 35648）因驱动先死而成为孤儿存活；
  控制器 taskkill 用错 PID 清理无效。已手工 PowerShell Stop-Process
  清理（属于失败后清理，不作退出证据）。
- 修复：控制器不再读 PIPE——驱动 stdout 直接重定向到 driver-stdout.log
  文件（Popen stdout=file），消除解码/阻塞/竞态三类问题。
