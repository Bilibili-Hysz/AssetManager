# G15：MetadataRepository / MetadataService strict session binding 与投影一致性

> 日期：2026-08-06  
> 工作区：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
> 分支：`master`  
> 基线 HEAD：`fbf3403 Enforce schema object integrity for v6`

本报告记录 G15 的 MetadataRepository 迁移、会话绑定加固与全量验证结果。当前工作区仍是多会话混合 dirty 状态；本阶段没有执行 staging、commit、reset、checkout 或全量 clean。本报告不是 AssetsManager 整体完成声明。

## 1. 阶段结论

G15 的核心目标已经达到可继续迁移下一批 repository 的质量线：

- `MetadataRepository` 的 canonical `LibrarySession` 绑定、captured root identity、managed connection owner、close/close-drain、raw-to-bound admission 与事务边界已经收口；
- `MetadataService` 保留并使用 strict retained `MetadataRepository`，不再在 bound service 内临时创建 raw repository；
- `ProjectService` 的真实 session 路径不再接受 unmanaged `db_conn`，legacy fake/provider-only 路径仍显式保留；
- 删除文件时的 Tag / Metadata / Favorite / Thumbnail / AssetIndex projection cleanup 现在位于同一个 savepoint；
- 既有 LAN legacy fixture 没有通过放宽生产 strict contract 修复，而是改为 test-only delegate projection；
- 完整 Python 非 E2E 与 WebUI 单元/typecheck/build 门禁均通过。

因此，**G15 可以结束并进入 TagRepository 审查/迁移；但项目整体仍处于 repository 与 runtime 分阶段迁移中，不能宣称 AssetsManager 完成。**

## 2. 主要实现与合同变化

### 2.1 Repository canonical contract

涉及：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\metadata_repository.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\session_contract.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\context.py
```

新增/收口内容：

- `MetadataRepository.for_session(session, library_root=None)`；
- `MetadataRepository(conn, session=..., library_root=...)` 的 strict canonical 绑定；
- `core.session_contract` 只标记真实 `LibrarySession`，拒绝仅具备 `root / operation / connection_for` 外形的 fake session；
- session root identity 在绑定时捕获，后续不以可变/重新解析的 root 替代；
- connection provider、managed owner、connection object identity 三重校验；
- 同 session 绑定幂等，foreign/second-session bind 拒绝；
- raw operation 开始后禁止 raw → bound late bind；
- close 开始后不发布半完成 binding，close 后 repository 在 SQLite statement 前 fail-closed；
- bound path containment 与 explicit library root identity 校验。

raw 兼容仍保留：

```python
MetadataRepository(raw_conn)
```

这条路径不作为 canonical ownership 证明，也没有全局切换 `allow_unmanaged=False`。

### 2.2 Transaction / migration contract

bound writes 使用 savepoint：

```text
caller outer transaction 存在
→ repository savepoint
→ mutation
→ RELEASE SAVEPOINT
→ 不提交 caller transaction
```

无 outer transaction 时，repository 自己结束 transaction；异常时 rollback/release cleanup，不把 cleanup 失败伪装成业务结果。cleanup 阶段也捕获 `BaseException`，保留原始异常并附加 cleanup note。

`migrate_path()` 已收口：

- same-path 是明确 no-op，返回 `0`；
- destination 位于 source subtree 时直接拒绝；
- bound migration 的多行迁移位于 savepoint 内，部分写入后失败会回滚；
- malformed JSON / non-list 的历史兼容读取行为保持；
- cached file count 的 `0` 是有效缓存值，不再被误判为 cache miss。

### 2.3 MetadataService retained repository 与 event boundary

涉及：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\metadata_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\controllers\info_controller.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\bootstrap.py
```

- `MetadataService.for_session(session)` 只接受真实 `LibrarySession`；
- bind 时建立并 retain 一个 bound `MetadataRepository`；
- 后续 `_repo()` 返回 retained repository，避免 service 每次操作回到 raw adapter；
- provider、root identity、repository connection 必须一致；
- `InfoController` 在传入 session 时默认采用 strict MetadataService，并拒绝未绑定 metadata service；
- bound notes/URLs mutation 若发现 caller 已有 outer transaction，会 fail-closed：因为 service 无法在任意 caller commit 之后自动发布 event，不能先发布一个可能回滚的通知；直接需要 outer transaction 的低层调用继续使用 repository 合同。

### 2.4 ProjectService strict connection boundary

涉及：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\project_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_project_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_project_service_session_binding.py
```

真实 `LibrarySession` 路径现在：

- 捕获 session root identity；
- 要求 connection provider 属于该 session；
- 只使用 session-owned managed connection；
- 对显式传入的 unmanaged/foreign `db_conn` fail-closed；
- 仍允许 `_SessionProbe` 等 provider-only legacy probe 走 raw compatibility 分支，避免为 fake fixture 放宽 canonical contract。

### 2.5 Deleted projection cleanup 原子性

涉及：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\file_operation_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\thumbnail_repository.py
```

补齐 `commit=False` 能力后，以下数据库 projection 同时位于一个 savepoint：

```text
TagRepository
MetadataRepository
FavoriteRepository
ThumbnailRepository
AssetIndexRepository
```

late failure 会 rollback 全部 projection，且不提前删除 thumbnail 文件；成功提交后才执行 thumbnail 文件的 best-effort unlink。新增测试覆盖 Favorite、Thumbnail、AssetIndex late failure。

### 2.6 LAN runtime secret rotation

涉及：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\server.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\e2e\test_webui_realtime_acceptance.py
```

E2E 首轮发现：运行时 `_token_secret` 变化后，已派发的 local UI token 仍可能被旧的 `_local_ui_auth_secret` 接受，导致浏览器身份没有 reset。生产 server 现在在认证检查和公开属性读取时根据当前 runtime token secret 动态派生 auth-config-bound local UI secret；同一认证配置下仍稳定，不同 access key/password/auth mode 仍产生不同 secret。

这样 runtime secret rotation 会真正撤销旧 local UI token，同时保留 runtime sharing secret 与 local UI auth secret 的职责分离。

### 2.7 LAN legacy adapter 与架构边界

涉及：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\lan\support\legacy_runtime_adapter.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_architecture_boundaries.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\desktop\test_info_async_identity.py
```

- `core.session_contract` 纳入 repository → core infrastructure 架构 allowlist；
- InfoPanel mock 明确设置 `_session`，不绕过 InfoController strict check；
- LAN legacy adapter 新增 `LegacyBoundServiceProjection`，只对 raw `MetadataService` 做 test-only 委托投影；
- adapter 暴露 `_session` / `_connection_provider` 给 server structural validation，实际方法委托给原 raw service；
- ProjectService 内部 `_metadata_svc` 同样使用 projection，避免直接伪造 strict MetadataService 的 `_root_identity` / `_repository` 状态；
- production `AssetsManager` 没有反向 import `tests` adapter，也没有为 legacy fixture 放宽 strict production contract。

## 3. 回归与质量门禁

### 3.1 完整 Python 非 E2E

命令：

```text
python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
```

最终结果：

```text
2379 passed, 4 skipped, 1 warning
```

4 个 skip 都是当前 Windows 进程缺少 symlink / directory-symlink 权限（WinError 1314），不是测试失败；1 个 warning 是既有 `zipfile` duplicate archive name warning。

### 3.2 WebUI

工作目录：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui
```

命令与结果：

```text
npm test
62 test files passed, 449 tests passed

npm run typecheck
passed

npm run build
passed; Vite production bundle generated
```

本阶段没有修改 `webui/**`，这些结果只用于确认并行会话的 WebUI dirty 状态没有破坏前端门禁。

### 3.3 静态门禁

```text
ruff check AssetsManager tests
All checks passed

pyright
0 errors, 0 warnings, 0 informations

git diff --check
passed
```

pyright 另有“存在新版本”提示，但当前工程版本返回 0 errors。

### 3.4 Python Chromium E2E

命令：

```text
python -m pytest -q --tb=short tests/e2e
```

最终结果：

```text
6 passed
```

首轮 1 个 401 identity-reset 用例暴露 runtime token rotation 对 local UI 派生 secret 的失效传播缺口；修复动态派生后，单测与完整 6 条 E2E 均通过。`tests/e2e/**` 未被修改。

## 4. 工作区一致性状态

当前仍存在多会话混合 dirty：

- `master` 分支；
- 暂存区未主动修改；
- 未执行 staging/commit；
- 没有执行 reset/checkout/clean；
- `webui/**`、`tests/e2e/**`、`tmp/**` 保护域未主动修改；
- 关键新增文件仍显示为 untracked，后续必须和其依赖修改一起审阅、stage、commit，不能遗漏：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\session_contract.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_metadata_repository_session_binding.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_project_service_session_binding.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\lan\support\legacy_runtime_adapter.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_plugin_metadata_repository_lifecycle.py
```

本报告文件本身也尚未 staging。

## 5. 深度复核后仍保留的 P2 / 后续风险

1. LAN `_validate_runtime_service_bindings()` 目前主要验证 `_session`、provider 与结构字段；它不会完整验证 retained MetadataRepository 的内部 repository/root identity。生产 runtime 由 ApplicationBootstrap canonical assembly 生成，legacy delegate 仅在测试中使用；后续可引入不可变 binding descriptor 或更强的 runtime marker。
2. `LegacyBoundServiceProjection` 是 test-only compatibility projection，不得复制到 production。它不应被当作严格 service 的真实 binding。
3. close race 中，in-flight mutation 与 RuntimeEventRouter close 的 publish 顺序仍属于 best-effort event bus 语义；G15 已解决 caller outer transaction 的 metadata event 早发问题，但尚未把全局 event bus 改造为 after-commit/outbox。
4. 当前 Windows 权限导致 symlink/junction 分支未完全执行；CI/具备 SeCreateSymbolicLinkPrivilege 的环境应补跑。
5. raw legacy service/repository capability 仍存在，不能在没有完整调用方盘点前全局切换 `allow_unmanaged=False`。
6. 工作区多个并行会话的修改仍混合在同一个 dirty tree；此阶段报告只记录验证结果，不代表所有 dirty diff 都已归属、审阅或准备提交。

## 6. 下一阶段长期任务

建议严格按以下顺序继续，每阶段保持单一合同、单一写集和全量门禁：

### G16：TagRepository / TagService

- 先审查 raw connection/provider 使用面与 event publication；
- 引入与 MetadataRepository 相同的 real-session marker、captured root identity、managed connection owner、close/close-drain、same-root reopen、second-session/concurrent bind 矩阵；
- 明确 TagService mutation 与 caller outer transaction 的事件边界；
- 再检查 `TagStore` compatibility projection 是否存在双写/缓存分裂。

### G17：AssetIndexRepository / AssetIndexService

- 重点是 `assets` projection 的 commit semantics、batch/index tree 原子性、filesystem scan 与 DB transaction 分界；
- 继续复用本阶段 deleted projection savepoint contract；
- 补齐 symlink/reparse-point 行为的跨平台回归。

### G18：PluginMetadataRepository

- 重点是 plugin lifecycle、foreign root、closed session、plugin unload 与 metadata cache consistency；
- 在不改变插件 raw compatibility 的前提下建立 strict service boundary。

每一阶段完成条件：

```text
定向 contract matrix
→ full non-E2E
→ ruff / pyright / diff-check
→ WebUI test / typecheck / build
→ read-only parallel review
→ report
```

## 7. 阶段质量判断

> G15 的 MetadataRepository / MetadataService strict session contract、ProjectService connection boundary 与 deleted projection transaction contract 已通过 2379 条 Python 非 E2E、6 条 Chromium E2E、449 条 WebUI 测试及静态门禁。该结论只适用于 G15；TagRepository、AssetIndexRepository、PluginMetadataRepository 与混合 dirty 工作区归属审查仍是后续任务。
