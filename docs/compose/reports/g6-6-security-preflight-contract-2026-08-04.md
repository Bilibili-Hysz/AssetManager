---
feature: g6-6-security-preflight-contract-2026-08-04
status: service-gate-delivered-ui-pending
scope: first-share confirmation, trusted-LAN confirmation, and tunnel preflight
---

> 2026-08-04 实现更新：纯 Python 契约已落地，并已接入公共 LanServer、ShareManager 与 Desktop LanSharingMixin；未确认时阻止服务创建/启动，公网隧道继续要求真实有效认证。确认对话框、设置页写入和完整 GUI 验收仍待 Desktop UI 会话完成。详见 g6-6-security-preflight-implementation-2026-08-04.md。

# G6-6 安全 Preflight 契约 — 2026-08-04

## 1. 当前状态

当前已交付服务层门禁：公网隧道必须存在有效认证；LanServer、ShareManager 和 Desktop LanSharingMixin 在创建/启动前共享 SecurityPreflight；构造后的私有 LanServer 实现和可见 tunnel 属性也不能绕过认证门；启动后认证复核失败会回滚，回滚失败保留可重试引用。

仍未完成的是产品确认闭环：首次开启分享确认对话框、设置页写入确认字段、bind 历史范围持久化和完整 GUI 验收。不能把 lan_auth_mode、lan_guest_list、lan_guest_preview、lan_guest_download 或历史上曾经启动过服务当成用户已经确认风险。

## 2. 已落地的最小持久化字段

已落地：lan_share_safety_ack_version: int，以及 lan_trusted_network_confirmed: bool。

当前默认值与失效规则：

- 缺失 ack version 按 0 处理；
- 缺失 trusted flag 按 False 处理；
- 当前首版 CURRENT_SHARE_SAFETY_ACK_VERSION = 1；
- ack version 小于当前版本时重新要求确认。

旧配置不得自动迁移为可信确认。认证有效、历史启动过服务、bind 为 0.0.0.0 或 guest 能力开启，都不能替代用户确认。

## 3. 运行时状态

建议由主会话/服务层拥有以下状态快照：

- share_state：off、confirmation_required、starting、local_active、failed；
- tunnel_state：stopped、starting、public_active、blocked、failed；
- effective_auth：enabled 和 none/password/key/user 模式；
- confirmation_required；
- trusted_network_confirmed；
- failure_reason。

其中 effective_auth 必须来自服务端真实 auth_status，而不是仅根据 lan_auth_mode 推断。

## 4. 状态转换

首次启动建议为：off → confirmation_required → starting → local_active。

确认结果：

- 配置有效认证：允许 LAN 启动，但不自动把 trusted flag 设为 True；
- 确认局域网可信：允许无认证 LAN 启动，但 effective_auth.enabled 仍为 False；
- 取消：保持 off，不能创建或启动 LanServer。

隧道启动必须独立检查认证：

- trusted_network_confirmed=True 仍然不能启动 tunnel；
- effective_auth.enabled=True 才允许启动 tunnel。

如果认证被移除，或 bind 从本机扩大到局域网，是否重新要求确认必须固定并测试；建议在暴露范围扩大时重新确认。

## 5. 责任边界

主会话负责：

- AppSettings 新字段的默认值和版本语义；
- LanServer 或统一 ShareManager 的 preflight；
- 所有启动入口的 fail-closed 门禁；
- effective_auth 和安全状态快照；
- 认证移除、bind 扩大和 ack 版本升级时的失效规则。

第二会话负责：

- 首次确认对话框；
- 配置认证与确认局域网可信的选择界面；
- 访问范围、认证状态、隧道阻断原因和取消反馈；
- keyboard/focus、reduced-motion、截图和 UI 测试。

第二会话不得自行决定无认证 LAN 是否可启动，也不得用 UI 隐藏按钮替代服务门禁。

## 6. 必须补的契约测试

- 缺失确认字段首次启动进入 confirmation_required；
- 取消时不创建、不启动 LanServer；
- trusted-LAN 确认允许局域网启动但不能启动 tunnel；
- 有效密码、access key 或 active user 都能被 effective_auth 正确识别；
- 认证移除或 bind 扩大时按既定规则重新确认；
- 旧配置不被自动视为已确认；
- LanSharingMixin、ShareManager、直接 LanServer 不能绕过同一 preflight；
- 缺少 auth_status 能力时隧道启动 fail-closed。

当前状态：**服务层 preflight 与新增设置字段已实现；Desktop 确认 UI、历史暴露范围持久化和完整产品验收仍未完成。**
