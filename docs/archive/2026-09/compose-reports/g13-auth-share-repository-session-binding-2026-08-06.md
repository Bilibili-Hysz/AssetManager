# G13：AuthRepository / ShareRepository session-root-bound 迁移

> 日期：2026-08-06
> 工作区：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
> 分支：`master`
> 本报告是主线继续开发记录，不是发布完成声明。
> 后续 strict ownership、binding concurrency、close publication 与 savepoint cleanup 加固见 `g14-auth-share-strict-repository-hardening-2026-08-06.md`；本报告保留为过渡阶段证据。

## 1. 阶段目标

承接 G12 的 AuthService / ShareService canonical session contract，继续向 repository 层下沉：

- repository 构造时可声明 `library_root` / `session`；
- canonical connection 与 session 不一致时 fail-closed；
- repository retained object 在 session 关闭后拒绝新操作；
- 保留低层 `Repository(conn)` raw legacy 构造。

## 2. 实现内容

修改：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\auth_repository.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\share_repository.py
```

### 2.1 构造合同

两个 repository 新增可选参数：

```python
AuthRepository(
    conn,
    *,
    library_root=None,
    session=None,
)

ShareRepository(
    conn,
    *,
    library_root=None,
    session=None,
)
```

行为：

- `library_root` 存在时记录 canonical root identity，并执行 connection owner validation；
- `session` 存在时验证 session root 和 connection 对象；
- 同一 repository 不能重新绑定到另一个 session；
- `Repository(conn)` 仍保持 raw legacy 行为。

### 2.2 Repository operation scope

新增 repository-local operation wrapper，不依赖 application 层：

```python
_repository_operation
```

session-bound repository 的公开读写方法进入：

```python
with session.operation():
    ...
```

这样 retained AuthRepository / ShareRepository 在 session closing/closed 后不会继续访问数据库。

raw repository 没有 session 时保持原有行为。

### 2.3 Application service 传递 binding

修改：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\auth_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\share_service.py
```

AuthService / ShareService 的 `_bind_session()` 现在也会将当前 session 传递给内部 repository。

canonical bootstrap 资源图因此变为：

```text
LibrarySession
 ├─ AuthService
 │   └─ AuthRepository(session-bound)
 └─ ShareService
     └─ ShareRepository(session-bound)
```

## 3. 兼容边界

保留：

```python
AuthRepository(raw_conn)
ShareRepository(raw_conn)
AuthService(raw_conn, secret)
ShareService(raw_conn, secret)
```

历史 fake session 若只提供 `root_str`、`event_token`、`operation` 而没有 `connection_for()`，仍可以作为 legacy fixture 使用；canonical `LibrarySession` 则执行严格 connection 校验。

## 4. 新增回归

新增：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_repository_session_binding.py
```

并扩展：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_auth_share_session_binding.py
```

覆盖：

- bootstrap Auth/Share service 内部 repository 绑定当前 session；
- direct AuthRepository / ShareRepository session binding；
- retained repository 在 session close 后拒绝读操作；
- foreign canonical connection 构造失败；
- raw repository 与历史 fake session 兼容；
- 原有 schema、savepoint、错误传播矩阵。

## 5. 定向验证

```text
python -m pytest -q --tb=short tests/unit/test_auth_repository_error_contract.py tests/unit/test_share_repository_error_contract.py tests/integration/test_auth_share_session_binding.py tests/integration/test_repositories.py tests/core/test_db_migrations.py
```

结果：

```text
141 passed
```

新增 binding 测试：

```text
8 passed
```

静态检查：

```text
ruff check 相关文件 -> All checks passed
pyright 相关文件 -> 0 errors, 0 warnings, 0 informations
git diff --check -> 退出码 0
```

## 6. 全量非 E2E 门禁

```text
python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
```

结果：

```text
2303 passed, 4 skipped, 1 warning
```

全量静态门禁：

```text
ruff check AssetsManager tests -> All checks passed
pyright -> 0 errors, 0 warnings, 0 informations
git diff --check -> 退出码 0
```

4 条 skip 仍为 Windows 当前进程缺少 symlink/directory-symlink 权限；1 条 warning 仍为既有 zipfile duplicate-name warning。

## 7. 尚未完成

G13 只迁移 Auth/Share 两个 repository。仍有：

- MetadataRepository；
- TagRepository；
- AssetIndexRepository；
- PluginMetadataRepository raw adapter；
- benchmark、历史 fixture、第三方/历史插件矩阵；
- raw constructor 可观测与静态禁止新增；
- 最后切换 `allow_unmanaged` 默认值。

当前仍不可直接执行：

```python
allow_unmanaged: bool = False
```

## 8. 下一阶段建议

继续按以下顺序：

```text
MetadataRepository / TagRepository / AssetIndexRepository
→ PluginMetadataRepository session/root contract
→ benchmark/history fixture adapter
→ plugin compatibility matrix
→ raw usage static gate
→ 最后 allow_unmanaged 默认切换
```

每个 repository 需同时验证：

- managed same-root；
- managed foreign-root；
- unmanaged raw legacy；
- closed connection；
- session closing/closed；
- retained repository after session reopen。

## 9. 当前质量判断

> G13 已完成 AuthRepository / ShareRepository 的 session/root-bound contract，并通过 2303 条非 E2E 回归和静态门禁。AssetsManager 整体仍未完成，下一阶段进入 MetadataRepository、TagRepository、AssetIndexRepository 迁移。
