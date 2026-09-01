---
feature: mainline-parallel-batch-2026-08-04
status: partial-delivered
scope: G2-11, G3-9, G6-6, G6-1 quarantine listing, FileList reset evidence
verification: 626-passed-1-skipped
---

# 主线并行任务阶段报告 — 2026-08-04

## 1. 阶段结论

本阶段采用多个子代理并行处理主线任务，按文件域隔离并在阶段结束后完成主会话复核。当前结果可以继续推进，但仍不是 Desktop/LAN/WebUI 整体发布门禁。

## 2. 已完成

### G2-11 库统计

- NavigationMixin 在切换库根目录后异步触发统计。
- 使用当前 LibraryScopedServices 的 MetadataService 计算库根目录大小。
- 新增 MetadataService.set_library_total_size()，实际写入 library_stats。
- 校验 Runtime session 与目标库根目录一致，避免陈旧快照跨库写入。
- UI 仍需展示统计值并完成真实窗口验收。

### G6-6 分享/隧道安全

- LanServer.start_tunnel() 在无 access key、password 或 active user 时拒绝公网隧道。
- 旧 ShareManager.start_tunnel() 入口同步增加安全门，避免绕过。
- 保留 auth_mode=none 的局域网 guest 兼容语义；没有认证的公网隧道返回 None 并记录 authentication_required。
- 首次分享确认、局域网可信确认和设置持久化语义仍未实现。

### G3-9 数据库维护

- DatabaseMaintenanceService 已实现数据库大小读取和 WAL checkpoint 的受控操作。
- 支持 PASSIVE、FULL、RESTART、TRUNCATE，返回 busy、log_frames 和 checkpointed_frames。
- 已接入 LibraryScopedServices，并注册 Runtime lifecycle adapter。
- Runtime close 会按 integrity → maintenance 顺序停止服务，失败时保持可重试关闭语义。
- VACUUM 明确返回 unsupported；在维护窗口、写入暂停和排他锁语义冻结前不执行。
- 设置页入口和用户反馈仍未实现。

### G6-1 恢复隔离区

- 新增只读 RestoreQuarantineEntry 和 list_restore_quarantine()。
- 只列举 restore-backups 的直接真实目录，拒绝 symlink/junction、非目录、路径越界和递归扫描。
- 当前没有删除或回滚 API，避免在保留策略和 TOCTOU 语义未冻结前扩大误删风险。

### 性能线

- reset/refresh 线补充了无变化刷新、变化刷新、排序和过滤的状态/reset 证据。
- 证明现有模型在无变化 refresh 时可以复用状态；本阶段没有冒险删除首次 loading reset，也没有修改生产 FileList model。

## 3. 质量修正

- 修复 G2-11 代理发现的真实接口缺口：MetadataService 原先缺少 set_library_total_size()。
- 更新 LAN 生命周期旧测试，使其区分 G6-5 已存在的 integrity adapter 与本次 LAN server adapter。
- 保留现有 WebUI 和 Desktop UI V2 未提交改动，未回滚、覆盖或暂存其他会话文件。

## 4. 验证结果

| Gate | Result |
|---|---|
| 主线相关 Python 回归 | 626 passed, 1 skipped |
| Ruff | passed |
| compileall | passed |
| git diff --check | passed |
| symlink 测试 | 1 skipped，Windows 当前环境 WinError 1314 无目录 symlink 权限 |
| pytest 警告 | 既有 .pytest_cache WinError 183，不影响测试 |

另有一个真实 LAN 窗口切换集成场景在本机 30 秒子进程窗口内超时，暂记为环境/集成阻塞，不作为本阶段功能通过证据。

## 5. 下一阶段

1. 主会话已实现 G6-1 Qt-free SettingsAdapter 和 SettingsDialog 注入点；继续补齐异步 worker、取消和结果反馈。
2. 第二会话实现恢复/维护入口的纯 UI 和截图证据，不修改 Runtime 生命周期。
3. 继续补 G6-1 隔离区保留、回滚和清理策略，先做产品策略再做破坏性 API。
4. 设计显式数据库维护窗口后再评估 VACUUM。
5. 真实图片 IO/目录基准协议入口已提供；下一步在固定发布机数据集上执行并归档结果。
6. 完成 Desktop/LAN/WebUI 跨端验收。

当前发布判断：**主线基础能力继续收敛，G6 数据安全和性能阶段仍为 partial-delivered。**
