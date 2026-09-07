# ZIP 清理恢复与诊断

## 范围

本轮接续进程级 ZIP 资源预算，处理暂时无法关闭/删除归档导致容量持续占用的问题。主代理负责接口与审查，三个 GPT-5.6-terra 子代理分别实现重试服务、响应恢复、管理员诊断。前端不在本轮范围内。

## 实现

- `zip_cleanup.py` 提供进程级有界队列，最多保存 1024 个清理意图。单个后台线程按需启动；无待办时退出。首次延迟 1 秒，失败间隔指数增加至最多 60 秒；持续失败继续保留待办。
- 只重试当前进程明确登记的归档，不遍历系统临时目录，也不删除推测属于本程序的旧文件。
- 路由在配额/响应构造前退出以及压缩取消后的清理，均登记自己的释放回调。清理成功或确认文件已不存在后才释放租约；失败时保留资源额度。
- 临时响应保留文件句柄、身份与完成回调。关闭/删除失败会登记重试；默认 executor 已拒绝提交时也能转入恢复队列。
- 重试检查文件身份。路径指向替换文件、原身份无法确认或读取状态失败时，不删除未知文件，不虚假返还额度。外部已删除归档时可以完成清理。
- 重试回调在队列锁外执行，同一个 key 不会并发重试或被新回调覆盖。错误诊断保留类型，不保存异常消息到 API。

## 管理员诊断

现有 `GET /api/stats` 增加 `zip_resources`，保持原字段和权限要求：

```json
{
  "active_jobs": 0,
  "reserved_bytes": 0,
  "max_jobs": 4,
  "max_reserved_bytes": 2147483648,
  "cleanup": {
    "pending_count": 0,
    "retry_attempts": 0,
    "completed_count": 0,
    "oldest_pending_seconds": 0,
    "last_error_type": null
  }
}
```

计数在本进程生命周期内有效。`retry_attempts` 是累计后台尝试数，`completed_count` 是完成的重试意图数，不等于下载次数；正常首次清理成功不进入这两个统计。多个所有者可对同一归档登记各自的幂等释放意图，因此 `pending_count` 也不一定等于文件数。

## 审查与验证

主审发现并要求修复：文件状态读取失败与缺失混淆、永久失败指数溢出、线程退出与新入队的竞态、手工重试已占有全部条目时工作线程空集合错误，以及首次删除前路径替换导致异常覆盖原路由结果。收尾复核补充了线程启动失败保留待办、重复登记重新启动、响应重试复用已核验身份，以及需要构造参数的异常仍能保留真实类型。

定向验证已覆盖路由/worker 暂时删除失败后自动返还额度、真实后台线程自动重试、响应句柄关闭失败、路径替换保护、外部删除、执行器拒绝兜底与管理员权限隔离。清理服务定向测试 20 项、响应恢复定向测试 8 项通过。

最终完整 LAN、架构边界及打包配置门禁：

```powershell
python -m pytest tests/lan tests/core/test_package_contents.py tests/unit/test_architecture_boundaries.py tests/unit/test_build_installer.py -n 2 --basetemp=.pytest-tmp-quality-round5-final -o cache_dir=.pytest-cache-quality-round5-final -q
```

结果：**1001 passed, 2 skipped，exit 0，130.30 秒**。跳过项为 `test_safe_open.py` 和 `test_helpers.py` 中受 Windows 符号链接创建权限限制的测试（WinError 1314）；真实 junction 测试通过。

静态检查及入口验证：

```powershell
python -m ruff check AssetsManager/lan/zip_cleanup.py AssetsManager/lan/temporary_file_response.py AssetsManager/lan/routes/_helpers.py AssetsManager/lan/routes/downloads.py AssetsManager/lan/routes/system.py AssetsManager/lan/dto.py tests/lan
python -m pyright AssetsManager/lan/zip_cleanup.py AssetsManager/lan/temporary_file_response.py AssetsManager/lan/routes/_helpers.py AssetsManager/lan/routes/downloads.py AssetsManager/lan/routes/system.py AssetsManager/lan/dto.py
python run.py --package-smoke
git diff --check
```

以上均通过；Pyright 为 0 errors、0 warnings。本轮在上述范围内验收通过，工作区保留未提交改动。

## 边界

- 清理队列属于当前进程，进程终止不会持久保存回调。崩溃遗留文件回收仍未实现，需要带归属信息的独立设计。
- 操作系统长时间阻塞的单次 close/unlink 不能被强行中断；当前单个清理线程可能被此类调用延迟。
- 无法确认原身份或路径被替换时保留待办和额度，等待明确的外部处理；不通过放宽检查自动删除。
- 身份核验与 `unlink` 不是一个原子操作；本轮防护针对重试时可观测的身份变化，不声称解决所有本机文件替换竞态。
- 队列满时记录警告且不接受更多重试意图，既有待办仍保留，未清理资源不会被宣称已释放。被拒绝的意图没有自动恢复保证，当前生产 ZIP 准入上限为 4，正常所有权流程不会积累到 1024 个待办。
- 后台线程启动被运行时拒绝时保留待办并记录错误类型；后续登记可以重新尝试启动，持续拒绝时无法承诺自动恢复。
- 本轮没有性能压测、跨进程磁盘配额或安装包实机验证。
