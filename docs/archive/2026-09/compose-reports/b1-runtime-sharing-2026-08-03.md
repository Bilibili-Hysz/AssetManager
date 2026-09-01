---
feature: b1-runtime-sharing-2026-08-03
status: delivered
as_of: 2026-08-03
scope: Runtime-owned Auth/Share services and Desktop direct share creation
verification: focused-rerun-passed; full-and-e2e-rerun-pending
---

# B1 Runtime Sharing 交付报告 — 2026-08-03

## 1. 结论

**B1 delivered。**

B1 已将认证与分享的运行时所有权收敛到每个 live `LibrarySession` 对应的唯一 `LibraryRuntime`：同一 session 的 Runtime、`RuntimeSharingServices`、`AuthService`、`ShareService` 与 `token_secret` 均复用；不同 library/session 之间相互隔离。LAN server 只消费 Runtime 已组装的服务投影，不再为路由重新创建 Auth/Share 服务，也不生成第二份 secret。

本报告只覆盖 B1 交付边界。真实性能阈值、发布机验收以及 B3 最终跨端验收仍是后续工作，不因 B1 delivered 而提前宣称完成。

## 2. 可审计的实现事实

### 2.1 RuntimeSharingServices 所有权

- `ApplicationBootstrap.runtime_for(session)` 对同一个由该 Bootstrap 所拥有的 live canonical session 返回同一个 `LibraryRuntime`（`AssetsManager/application/bootstrap.py:297-349`）。
- `LibraryScopedServices` 持有不可变的 `RuntimeSharingServices`（`AssetsManager/application/bootstrap.py:171-189`）。`LibraryRuntime.sharing_services` 只是该 Runtime snapshot 的明确读入口（`AssetsManager/application/runtime.py:29-44`）。
- `RuntimeSharingServices` 是 frozen dataclass，包含 `token_secret`、`auth_service` 和 `share_service`；secret 不进入 repr（`AssetsManager/application/bootstrap.py:44-50`）。
- LAN `_LanServerImpl` 从 `runtime.services_snapshot.sharing_services` 取出服务与 secret，并把同一对象挂入 `LanScopedServices`；不会重新组装（`AssetsManager/lan/server.py:239-342`）。

因此，B1 的所有权关系是：

```text
live LibrarySession
  -> one LibraryRuntime
     -> one LibraryScopedServices snapshot
        -> one RuntimeSharingServices
           -> one token_secret
           -> one AuthService
           -> one ShareService
        -> LAN projection references the same services
```

### 2.2 token_secret 生命周期、复用与失效

- 每次创建 Runtime 时，在 `session.operation()` lease 内调用 `secrets.token_hex(32)`，并用同一个 secret 构造 Auth/Share 服务（`AssetsManager/application/bootstrap.py:351-362`）。
- 同一 Runtime 的 LAN stop/start 只停止并重新启动生命周期 adapter；不会重建 Runtime 或 Runtime snapshot，因此 secret、AuthService、ShareService 和已持久化的 share records 复用。Runtime adapter 的 stop 由 `LibraryRuntime.close_adapters()` 负责（`AssetsManager/application/runtime.py:86-120`）。
- session close 后，Auth/Share public methods 通过 `session_operation` 无法重新取得 operation lease，因而失败；Runtime 也会从 Bootstrap cache 清理（`AssetsManager/application/context.py:182-215,217-260`；`AssetsManager/application/bootstrap.py:415-429`）。这使该 Runtime 的 secret 在语义上失效，不能跨 session 继续使用。
- secret 只存在于 Runtime/service/server 对象内；当前实现没有把它写入 settings、library 文件或数据库。数据库中持久化的是分享记录及其业务字段，不是 Runtime 的 token secret。
- 同根目录重新打开也得到新的 session/Runtime/secret，而不是复用旧 Runtime；跨 library 的测试明确要求 secret 与 DB connection 均不同（`tests/unit/test_library_runtime.py:29-54`）。

### 2.3 Auth/Share 表初始化与幂等性

Runtime 创建阶段执行：

```python
with session.operation():
    connection = session.connection_for(session.root)
    token_secret = secrets.token_hex(32)
    ...
    auth_service.init_tables()
    share_service.init_table()
```

证据位置：`AssetsManager/application/bootstrap.py:351-362`。

`AuthService.init_tables()` 与 `ShareService.init_table()` 本身都由 `@session_operation` 包裹（`AssetsManager/application/auth_service.py:64-68`；`AssetsManager/application/share_service.py:99-102`）。因此，初始化既发生在 Runtime 创建的完整 session operation lease 内，服务后续单独调用也不会绕过 session 生命周期边界。底层 repository 的表创建使用既有幂等 schema 初始化契约；架构边界测试同时锁定了“由 Bootstrap 初始化、LAN server 不重复初始化”的约束（`tests/unit/test_architecture_boundaries.py:487-525`）。

## 3. 关闭顺序与失败语义

正常 session close 的顺序如下：

```text
session.close()
  -> session._begin_close()
  -> closing listeners
     -> Runtime.close_adapters()
        -> LAN stop()
  -> drain 已有 operation lease
  -> session-close listeners
     -> Runtime.close()
        -> adapter/runtime-owned cleanup
     -> Bootstrap 移除 Runtime cache
  -> DatabaseManager 关闭 DB connection
  -> LibrarySession cache cleanup
```

代码证据：`LibrarySession.close()` 先调用 `session._begin_close()`，再通知 closing listeners；`ApplicationBootstrap` 的 closing listener 调用 `Runtime.close_adapters()`（LAN stop），随后 session drain operation lease；session-close listener 再调用 `Runtime.close()` 并移除 cache，最后由 `DatabaseManager` 关闭 DB connection（`AssetsManager/application/context.py:217-260`；`AssetsManager/application/bootstrap.py:229-234,415-429`）。

这个顺序保证 LAN stop 发生在 session 仍可用时，Runtime close 发生在 adapter 已停之后，DB close 发生在 Runtime/session 清理之后。若 LAN stop 或后续 cleanup 失败，session/runtime/DB 会保留到可重试状态；相关测试覆盖 adapter stop failure、post-close failure、并发 close 与 teardown-once 语义（`tests/unit/test_library_runtime.py:407-614`）。

## 4. Desktop、HTTP 管理与远端分享协议

### 4.1 Desktop ShareCreationTask 直接调用 ShareService

Desktop `ShareCreationTask` 不再通过 HTTP 回调本机管理 API 创建分享。它直接调用注入的 `share_service.create_share(paths=..., **options)`，随后把返回的 `ShareLink` 转成公开 payload 并补上 `/s/{id}` URL（`AssetsManager/dialogs/_share_api.py:58-91`）。`ShareLinkDialog` 从当前 session 的 canonical Runtime 取得 `sharing_services.share_service`，再创建该 task（`AssetsManager/widgets/lan_sharing.py:248-302`；`AssetsManager/dialogs/share_link_dialog.py:155-194`）。

这保留了 Desktop 的异步 UI 行为，同时消除了 Desktop 为创建分享而绕行 HTTP、重新认证或依赖 LAN server 已经启动的必要。

### 4.2 HTTP 管理与远端分享协议保留

B1 没有删除或替换现有 HTTP/LAN 协议：

- 管理 API 仍保留 `POST/GET/DELETE /api/shares`；
- 远端分享仍保留 `/s/{id}` 页面，以及 password verify、download、preview、info API；
- LAN route 继续通过同一个 Runtime-owned `ShareService` 处理请求（`AssetsManager/lan/api.py:134-141`；`AssetsManager/lan/routes/shares.py:56-170,202-367`）。

因此，Desktop 直调只改变本地创建路径；HTTP 管理与远端消费协议仍是兼容表面。

### 4.3 Desktop offline URL

Desktop 在 LAN 未运行时仍可从当前 session 的 `ShareService` 创建并持久化 share record；UI 根据当前配置的 SSL certificate/key、LAN IP 与 configured port 预先构造 `http(s)://<local-ip>:<port>/s/<id>` base URL。LAN 之后启动时，会从同一 library DB 读到该 share record，因此 share 可见性不依赖“创建时 server 已运行”。实现位置：`AssetsManager/widgets/lan_sharing.py:273-301`；对应回归测试为 `tests/lan/test_lan_api.py:2089-2119`。

这里的 offline URL 是“LAN server 当前未运行时仍可生成的本地 endpoint URL”，不是公网 URL，也不代表远端在 server 未启动期间可访问。

## 5. 多库隔离与 legacy fallback 限制

### 5.1 多库隔离

每个 session 通过自己的 `session.connection_for` 获取 DB connection；Auth/Share service、LAN server、scanner 和其他 scoped service 均要求绑定到该 session/provider。LAN server 还拒绝请求不同 library root 的 connection（`AssetsManager/application/context.py:63-67`；`AssetsManager/lan/server.py:289-305,732-740`）。

测试证据覆盖：

- 同一 session 的 Runtime sharing bundle 单例与 service identity 复用（`tests/unit/test_library_runtime.py:29-39`）；
- 不同 library 的 secret、Auth/Share service 与 DB connection 隔离（`tests/unit/test_library_runtime.py:42-54`）；
- LAN injection 不重新绑定 runtime provider，且深层 session binding mismatch 被拒绝（`tests/lan/test_lan_api.py:2272-2399`）。

### 5.2 legacy fallback 的边界

兼容 fallback 只允许轻量 legacy test double：当 `services_snapshot` 在类型/实例上完全不存在时，才读取 `.services`；真实 `LibraryRuntime` 没有 operation boundary 时直接报错，不能用无条件 `nullcontext` 掩盖生命周期问题（`AssetsManager/lan/server.py:28-48`）。

以下情况不会 fallback，而是拒绝组装：

- `services_snapshot` 存在但值为 `None`；
- `services_snapshot` getter 抛错；
- canonical snapshot 与当前 session 不一致；
- snapshot 没有显式 LAN projection 或 sharing projection；
- Runtime service 的 connection provider、session、DB connection 或 secret 不匹配。

对应测试：`tests/lan/test_lan_api.py:2122-2260`。该 fallback 是迁移旧 fixture 的临时兼容层，不是生产服务定位器，也不允许生产代码回到 route-level service assembly。

## 6. 独立复核发现与修复

独立复核发现两类需要明确收口的问题，已在当前实现中修复并补测试：

1. **Connection lease / publication 问题。** Runtime sharing service assembly、LAN service projection 与 server binding 不能在 session close 竞争期间裸读 connection 或发布半成品。修复为：Runtime 创建和表初始化放入 `session.operation()`；LAN 组合使用 `_runtime_operation()`；真实 Runtime 缺少 operation boundary 时拒绝；最终字段通过 `session._publish_while_live()` 在 close admission 同一条件下原子发布。证据：`AssetsManager/application/bootstrap.py:351-362`、`AssetsManager/application/context.py:182-215`、`AssetsManager/lan/server.py:37-48,239-350`；竞态测试：`tests/lan/test_lan_api.py:2306-2379`。

2. **HTTPS endpoint 问题。** server status 与 Desktop 离线创建路径必须使用同一有效 endpoint 协议。修复为 status 根据 cert/key 返回 `https://...`，否则返回 `http://...`；Desktop offline URL 使用同样的 cert/key 判断；LAN share route 也按相同协议生成 `/s/{id}` URL。证据：`AssetsManager/lan/server.py:674-692,930-1007`、`AssetsManager/widgets/lan_sharing.py:281-301`、`AssetsManager/lan/routes/shares.py:139-170`；测试：`tests/lan/test_lan_api.py:2073-2087`。

## 7. 测试证据状态

### 已运行的既有证据（不是本次最终 B1 重跑）

截至 A3 收口报告，父基线曾运行过 A3/Runtime/LAN 相关聚焦矩阵 `347 passed`、Task D Runtime/Desktop 矩阵 `431 passed`、当前 Desktop/LAN/Chromium 矩阵 `190 passed`，以及 Python 全量 `1695 passed, 1 skipped`；另有 Ruff、compileall 与 `git diff --check` 通过记录（`docs/archive/2026-09/compose-reports/a3-service-assembly-2026-08-02.md:88-99`）。这些数字证明父基线质量，但发生在 B1 当前工作树改动之前，不能冒充 B1 最终验收结果。

本报告还核对了当前 B1 新增/修改测试的测试意图与断言，包括 Runtime sharing bundle、table initialization、session-close invalidation、multi-library isolation、LAN injection reuse、offline HTTP visibility、HTTPS status、fallback rejection、close race 和 Desktop direct-call 等；随后在当前工作树使用仓库外可写 pytest basetemp 重新执行了 B1 聚焦矩阵，结果为 `478 passed`；该结果不包含完整 Python 和 Chromium 最终发布门禁。

### 剩余验证

B1 的聚焦矩阵已在当前工作树重跑并通过 `478 passed`。以下是尚未作为最终发布证据归档的独立门禁：

- 当前工作树的完整 Python suite（建议使用显式可写 basetemp）；
- `tests/e2e/test_webui_realtime_acceptance.py` Chromium/真实浏览器门禁；
- 发布环境的真实 HTTPS 证书、端口占用、多客户端、重启恢复和打包运行验收；
- 最终 B3 跨端状态一致性验收；
- 重新归档完整 Python、Chromium、Ruff/compileall 与 `git diff --check` 结果。

最终重跑还应确认 Windows 环境下 Qt/网络测试的既有平台门槛，以及没有把临时 test-double fallback 误判为生产路径。

## 8. 后续工作与非目标

- **真实性能阈值：** 仍需定义并测量 Runtime 创建、LAN stop/start、share create/list/download、首个 LAN 请求与 session close 的真实性能阈值；B1 目前没有性能达标声明。
- **B3 最终跨端验收：** Desktop、LAN/WebUI、跨 session/library 切换、share lifecycle 与事件/状态同步的最终端到端验收仍待完成。
- **发布机/部署验收：** HTTPS 真实证书加载、端口占用、LAN 多客户端、重启恢复和打包运行仍需在目标发布环境验证。
- **旧 fixture 清理：** legacy `.services` fallback 仅为迁移兼容，待所有旧 test doubles 暴露 canonical `services_snapshot` 后删除。

## 9. 实际修改文件

本次 B1 文档同步实际覆盖上方列出的 13 份文档；当前工作树还包含其他工作者既有的代码、测试与文档改动，本报告不将其归因于本次同步。

### Postscript

A3 收口报告与跟进报告中的历史事实、历史测试矩阵和未完成项继续保留，作为当时状态的追踪材料；其中的 `114/1590` 必须按历史快照理解。当前 collected 为 1713 tests；本次可发布性判断只引用当前 B1 `478 passed` 聚焦矩阵，以及其内部覆盖的 Runtime、LAN、路径和 Desktop 分享切片结果。完整 Python/Chromium 发布门禁受环境限制尚未完成，因此不合并成未经验证的总数。

工作区中其他未提交改动均为既有改动，本次未回滚、未修改、未纳入本报告变更。
