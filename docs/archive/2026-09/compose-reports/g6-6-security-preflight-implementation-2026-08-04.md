---
feature: g6-6-security-preflight-implementation-2026-08-04
status: service-gate-history-ui-confirmation-partial
scope: shared LAN start preflight, effective-auth tunnel gate, and entry-point consistency
---

# G6-6 安全 Preflight 实现报告 — 2026-08-04

## 结论

G6-6 已完成服务层首个可验收切片，并在本次 S1 续接中补齐了最小的历史姿态接线：首次分享的安全确认状态、认证状态和公网隧道门禁由共享纯 Python 契约计算，并接入 LanServer、ShareManager、Desktop LanSharingMixin 及独立设置入口。未确认时不会创建或启动服务；取消保持 off；无认证或缺少 auth_status 时公网隧道 fail-closed。

本次还将确认版本改为精确匹配、将取消改为不撤销既有确认、增加 last-successful bind/effective-auth 的严格持久化和 save 失败回滚，并让三个服务入口使用 canonical preflight holder。首次分享确认 helper、原子 ack/trusted 写回、二次预检和 standalone dialog 路径已经接入；真实 GUI 主题/DPI/键盘/截图验收、完整生命周期回归和产品文案签收仍未完成。

## 已交付

- AssetsManager/application/security_preflight.py
  - CURRENT_SHARE_SAFETY_ACK_VERSION = 1；缺失或非法版本按 0 处理。
  - lan_share_safety_ack_version 与 lan_trusted_network_confirmed 的 fail-closed 读取语义。
  - SecurityPreflight、SecuritySnapshot、ShareState、TunnelState。
  - 认证 LAN 与 trusted LAN 两种确认路径相互独立；trusted LAN 不能授权公网隧道。
  - 支持 bind 暴露范围扩大、认证移除和缺少认证状态能力的稳定失败原因。
  - 快照可直接转换为 JSON-safe 字典供 Desktop/LAN/WebUI 消费。

- AssetsManager/lan/__init__.py
  - 公共 LanServer.start(..., preflight=...) 统一执行门禁。
  - 构造后的私有 _LanServerImpl 省略 preflight 也 fail-closed；测试专用的 object.__new__ 生命周期夹具不代表产品构造路径。
  - 原始 tunnel 属性改为受认证门保护的代理，避免通过可见 tunnel 对象绕过 start_tunnel()。
  - 启动后认证复核失败会回滚；回滚失败返回 failed 状态并保留可重试引用。
  - 暴露 auth_status()、security_snapshot 和隧道阻断原因。

- AssetsManager/lan/manager.py
  - ShareManager.start(..., preflight=...) 在创建 LanServer 前执行门禁，并处理启动后认证复核和回滚失败引用保留。
  - ShareManager.start_tunnel() 要求真实可调用的 auth_status；缺失、异常或未认证均不触碰 tunnel。
  - 隧道失败会尝试清理候选资源；清理成功回到 stopped，清理失败保留候选句柄并进入 failed，记录稳定原因并允许重试；成功前不会覆盖仍存活的旧 tunnel。
  - 状态快照包含 share_state、tunnel_state、confirmation_required、failure_reason 和 security。

- AssetsManager/widgets/lan_sharing.py
  - Desktop 入口从持久化字段构造 preflight，在服务创建前阻止未确认启动。
  - user/users 模式通过 Runtime-owned auth service 检查 active users，不再只依据 UI 配置字符串推断认证有效性。
  - 启动结果再次检查，避免服务层状态与 UI 状态分叉。

## 验证证据

- tests/unit/test_security_preflight.py：21 passed。
- tests/lan/test_security_preflight_integration.py：8 passed。
- tests/lan/test_security_preflight_internal.py：5 passed。
- tests/lan/test_share_manager_tunnel_failures.py：16 passed（含启动后回滚、tunnel 失败清理和快照同步）。
- G6-6 与既有 LAN 分享回归：71 passed。
- tests/lan/test_lan_api.py + tests/unit/test_lan_sharing.py：246 passed（使用工作区内 --basetemp；Windows 默认 pytest 临时目录存在权限阻塞）。
- ruff check：通过。
- compileall：通过。
- git diff --check：通过。

## 验证边界

LAN 全套生命周期门禁本轮观察到 395 项通过、1 项按条件排除，另有 1 项既有 SystemExit 启动回滚测试在当前 Windows/Python 3.14 环境中出现线程退出竞态：清理回调已执行时测试立即断言后台线程已退出。该失败位于本轮未修改的 _run/_shutdown 生命周期代码，需单独作为生命周期稳定性任务处理，不能归因于 G6-6 preflight。

## 2026-08-05 S1 续接交付

本次仅修改 AssetsManager 主线安全写域，未触碰 `webui/**`，未暂存或提交：

- `SecurityPreflight` 的 ack 版本现在必须**精确等于** `CURRENT_SHARE_SAFETY_ACK_VERSION`；未来版本不会被当前版本错误接受。
- `SecurityPreflight.cancel()` 只取消当前启动请求，不再清除已有 ack/trusted 状态。
- `AppSettings.save()` 返回可观察的成功/失败结果；LAN 安全历史提交在磁盘写入失败时恢复旧内存值和 dirty 状态。
- 新增 `lan_share_last_successful_bind` 与 `lan_share_last_successful_auth`，只保存 bind 和规范化的 `enabled/mode`，不保存密码、hash、access key 或 token。
- `security_preflight_from_settings()` 作为 canonical factory，Desktop、ShareManager 和 LanServer 未显式注入时均从同一 AppSettings 状态构造 preflight；成功完成真实 auth 复核后才记录 last-successful posture。
- 独立 `SharingSettingsDialog` 的启动分支也显式传递 preflight，并在设置保存失败时不改变服务器状态。

新增/复核证据：

- `tests/unit/test_security_preflight.py`：当前 21 passed；
- `tests/lan/test_security_preflight_integration.py`：当前 12 passed，包含三个入口的 persisted-history gate、holder 复用和成功后历史写回；
- `tests/unit/test_lan_sharing.py`：确认 helper 当前 3 passed，覆盖 Yes/No/commit failure 的 fail-closed 行为；
- `tests/lan/test_share_manager_tunnel_failures.py` + `tests/lan/test_tunnel_security.py`：15 passed；
- `tests/desktop/test_sharing_settings_dialog.py`：6 passed；
- 相关生产/测试写域 Ruff、py_compile 通过。

## 尚未完成

- 确认 helper 已接入服务启动前，但真实 GUI 主题/DPI/键盘焦点/reduced-motion/截图验收和完整产品文案签收仍未完成。
- 设置页对两个确认字段的版本升级失效、用户指导和跨重启验收仍需补齐；服务层原子写回已经接通。
- Desktop 确认对话框和设置页的用户确认写回仍未完成；历史姿态的服务层读取/成功后写回已接通，但真实产品确认入口仍需提供明确的用户决策和取消反馈。
- 真实 GUI 截图、主题、DPI、键盘焦点和 reduced-motion 证据。
- 完整 LAN 生命周期中的既有 SystemExit 线程退出竞态仍需单独处理；该问题位于本轮未修改的 _run/_shutdown 代码。
- 隔离区保留/回滚/清理、半完成文件操作恢复等其他 G6-1/G6-5 子项。

## 下一步

1. Desktop UI 会话实现确认对话框和设置字段持久化，只消费 SecuritySnapshot，不自行决定服务是否可启动。
2. 补齐 previous_bind/认证变更历史的持久化策略和测试。
3. 在固定目标发布机上完成 LAN/隧道及跨端验收。
