# G14：Auth / Share strict repository-session contract 加固

> 日期：2026-08-06
> 工作区：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
> 分支：`master`
> 基线 HEAD：`fbf3403 Enforce schema object integrity for v6`
> 本报告记录 G13 的严格化与工程一致性验证；它不是 AssetsManager 整体完成声明。

## 1. 背景与结论

G13 已把 AuthRepository / ShareRepository 接入 LibrarySession，但交叉审查确认当时仍属于过渡实现：

- canonical binding 仍可能接受 unmanaged connection；
- service 通过可选私有绑定存在 fail-open / 半绑定风险；
- repository/service binding 状态发布与 session close 存在竞态；
- 并发 second-session bind 可能发生 check-then-set 覆盖；
- Share duplicate insert 的事务恢复与 cleanup failure 语义不完整；
- 生命周期矩阵缺少 close-drain、same-root reopen、真实 foreign managed owner 等覆盖。

本阶段已完成上述 G13 blocker 的加固。当前判断：

> AuthRepository / ShareRepository 的 canonical session/root ownership 与 retained-object lifecycle 主合同已经达到可继续迁移下一批 repository 的质量线；raw legacy 兼容仍保留。AssetsManager 全项目仍处于迁移中，不能切换全局 `allow_unmanaged=False`，也不能宣称项目完成。

## 2. Strict canonical repository factory

修改：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\auth_repository.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\share_repository.py
```

新增：

```python
AuthRepository.for_session(session)
ShareRepository.for_session(session)
```

canonical factory 的固定顺序：

```text
session.operation() lease
→ 捕获 session root/root_str
→ session.connection_for(session root)
→ DatabaseManager.require_managed_connection_owner(...)
→ strict _bind_session()
→ session._publish_while_live(...) 发布绑定
```

安全性质：

- unmanaged raw connection 不能冒充 canonical connection；
- managed foreign-root connection 被拒绝；
- 显式 `library_root` 必须与 `session.root` 的 `root_identity.map_key` 相同；
- connection object 必须就是 session 的 canonical connection；
- session 已进入 closing 时，不发布 repository binding；
- `_session` 最后写入，作为 operation scope 的 readiness flag。

兼容边界保持：

```python
AuthRepository(raw_conn)
ShareRepository(raw_conn)
```

单独 `library_root=...` 仍只属于过渡期 legacy compatibility，不作为 canonical ownership 证明。

## 3. Binding 并发与 close 线性化

两个 repository 与两个 service 均增加 per-instance `threading.RLock`，绑定过程在锁内完成：

```text
already-bound 检查
→ root/provider/owner 验证
→ live publication
```

因此：

- 同一 session 重绑为显式幂等；
- 并发绑定第二个 session 不再可能覆盖第一个 session；
- repository/service 状态不会在 validation 失败后留下半绑定；
- 使用 `LibrarySession._publish_while_live()` 与 close admission 建立明确发布点；
- close 已开始时，临时构造的 bound repository/service snapshot 不会发布给 retained object。

## 4. AuthService / ShareService fail-open 收口

修改：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\auth_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\share_service.py
```

canonical 分支不再使用：

```python
getattr(repository, "_bind_session", None)
```

而是直接使用 strict factory：

```python
AuthRepository.for_session(session)
ShareRepository.for_session(session)
```

service 先完整构造并验证 bound repository，再发布：

```text
_repo
_library_root
_session_token
_session  # readiness flag，最后发布
```

### 4.1 Legacy fake session 的明确边界

历史测试/adapter 中存在只提供：

```text
root_str + event_token + operation()
```

而完全没有 `connection_for` 属性的 fake session。该形态继续作为显式 legacy compatibility：

- service 进入 fake session operation scope；
- 内部 repository 保持 raw/unbound；
- service 保留历史 root/path/event 语义。

以下 malformed session 不再静默降级为 raw：

- `connection_for` 属性存在但不可调用；
- 缺少 callable `operation()`；
- 缺少 `root` / `root_str`。

## 5. ShareRepository duplicate/savepoint 合同

`ShareRepository.insert()` 现在为每次 insert 建立独立 savepoint。

### 5.1 无 caller outer transaction

```text
INSERT success  → transaction 完整结束
duplicate       → rollback/release，本次调用后 in_transaction=False
```

### 5.2 存在 caller outer transaction

```text
caller 之前写入
→ repository savepoint
→ duplicate
→ 只 rollback repository insert
→ caller 之前写入保留
→ caller transaction 继续 active
```

成功 insert 同样不会擅自 commit caller outer transaction。

### 5.3 Cleanup failure 不得伪装为业务失败

仅当约束失败且事务边界成功恢复时，duplicate 才返回 `False`。

以下情况作为 infrastructure failure 传播：

- `ROLLBACK TO SAVEPOINT` 失败；
- `RELEASE SAVEPOINT` 失败；
- rollback 后 transaction boundary 与调用前不一致；
- 无 outer transaction 时无法结束残留 transaction。

非 duplicate 的原始 lifecycle / SQLite / infrastructure 异常继续抛出；cleanup 的附加失败被记录，但不会覆盖原始异常。

## 6. 生命周期与并发回归矩阵

新增/扩展：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_repository_session_binding.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_auth_share_session_binding.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_share_repository_error_contract.py
```

覆盖：

- strict factory same-root managed success；
- strict constructor `Repository(conn, session=real_session)`；
- unmanaged connection 拒绝；
- 两个真实 LibrarySession 的 foreign managed connection 拒绝；
- explicit `library_root != session.root` 拒绝；
- same-session 重绑幂等；
- second-session 重绑拒绝；
- concurrent second-session bind 被 binding lock 串行化；
- session close 后 read/write/init 在 SQLite statement 前拒绝；
- in-flight repository operation 持有 lease，close 确实等待 drain；
- begin-close 后新 operation 立即拒绝；
- same-root close/reopen 后旧 repository 永久拒绝、新 repository 可用；
- closing publication gate 拒绝 repository/service 状态发布；
- malformed service session 不静默降级；
- service close 后 mutation 不执行、event 不发布；
- duplicate 后无 outer transaction；
- duplicate 后 caller outer transaction 保留；
- savepoint cleanup failure 不转换为 `False`。

并发测试使用 `threading.Event` 协调，并在失败清理路径无条件 release/join，未使用依赖调度时序的 `sleep`。

## 7. LAN fixture 一致性修复

完整非 E2E 首轮暴露 8 个 LAN fixture 失败。根因不是生产 canonical runtime，而是：

```text
object()/unmanaged connection
+ fake session.connection_for
+ 真实 AuthService/ShareService canonical constructor
```

该 fixture 把 unmanaged object 冒充 DatabaseManager-owned canonical resource。处理方式不是放宽 production strict ownership，而是修改：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\lan\test_lan_api.py
```

LAN runtime injection 测试现在使用显式 sharing binding projection，仅表达它实际要验证的：

```text
_conn identity
_secret identity
_session identity
snapshot wiring
```

真实 Auth/Share persistence/session contract 继续由专门 integration tests 验证。

## 8. 工作区全量一致性门禁

### 8.1 Auth/Share 扩大定向矩阵

```text
python -m pytest -q --tb=short \
  tests/integration/test_repository_session_binding.py \
  tests/integration/test_auth_share_session_binding.py \
  tests/unit/test_auth_repository_error_contract.py \
  tests/unit/test_share_repository_error_contract.py \
  tests/integration/test_auth_service.py \
  tests/integration/test_share_service.py \
  tests/integration/test_repositories.py \
  tests/core/test_db_migrations.py
```

结果：

```text
229 passed
```

### 8.2 完整非 E2E

```text
python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
```

结果：

```text
2339 passed, 4 skipped, 1 warning
```

4 条 skip 均为当前 Windows 进程缺少 symlink/directory-symlink 权限；1 条 warning 仍为既有 zipfile duplicate-name warning。

### 8.3 静态门禁

```text
ruff check AssetsManager tests
All checks passed

pyright
0 errors, 0 warnings, 0 informations

git diff --check
退出码 0
```

### 8.4 并行工作树额外一致性修复

全量 pyright 曾发现并行工作树中新加入、尚未跟踪的：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\gallery_service.py
```

存在 4 个 `list[Never]` 类型错误。仅增加局部 `list[dict[str, Any]]` 注解，不改变运行时逻辑；随后验证：

```text
python -m pytest -q --tb=short \
  tests/integration/test_gallery_service.py \
  tests/lan/test_gallery_routes.py

7 passed
```

## 9. 仍然保留的风险与后续约束

本阶段没有处理以下更广泛问题：

1. `AuthService.db_conn` 仍是 legacy raw capability escape；后续需完成调用方盘点后 deprecated/收口。
2. AuthRepository 若干历史 mutation 仍使用 broad catch 与 whole-connection rollback；需要单独事务合同阶段处理，不能在本阶段无证据扩张修改。
3. ShareService 若被调用方 outer transaction 包裹，best-effort event 可能早于 caller commit；需要明确 service-owned transaction、禁止 outer transaction，或设计 after-commit/outbox。
4. `for_session()` 与 `_bind_session()` 仍有重复 provider/owner 验证；安全但可在 API 稳定后收敛。
5. event bus 当前是 best-effort projection，不是数据库原子 outbox。
6. 工作区仍是多会话混合 dirty 状态，测试与报告中仍有未跟踪文件；本阶段没有 staging/commit。

## 10. 下一阶段顺序

可以继续迁移，但仍按单 repository、单合同、完整 lifecycle matrix 推进：

```text
MetadataRepository
→ TagRepository
→ AssetIndexRepository
→ PluginMetadataRepository
```

每一阶段至少验证：

```text
managed same-root
managed foreign-root
unmanaged raw legacy
explicit root mismatch
session close/close-drain
same-root reopen old-object rejection
second-session/concurrent bind
closed connection/infrastructure error propagation
transaction boundary
service/event publication boundary
```

最终阶段才允许评估：

```python
allow_unmanaged: bool = False
```

当前仍禁止直接切换该默认值。

## 11. 阶段质量判断

> G14 已完成 Auth/Share canonical repository-session strict contract 的 blocker 加固，并通过 2339 条完整非 E2E 回归与全量静态门禁。该结论仅适用于 Auth/Share 迁移阶段；AssetsManager 其余 repository、legacy/raw capability、事务与插件兼容工作仍未完成。
