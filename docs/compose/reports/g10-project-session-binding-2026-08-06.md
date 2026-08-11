# G10：ProjectService 内部 DirectoryCache session-bound 收口

> 日期：2026-08-06
> 工作区：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
> 分支：`master`
> 本报告是主线继续开发记录，不是发布完成声明。

## 1. 背景与风险

G3e/G9 的 raw connection 迁移审查确认，`ProjectService` 虽然自身已经支持 `LibrarySession`，但 `get_home()` 内部仍有 legacy-shaped 构造：

```python
DirectoryCache(db_conn)
```

这使得 canonical session graph 中的 retained/cache-like helper 没有显式绑定当前 session。若该对象在生命周期边界外被保留或在操作期间发生关闭竞态，单靠外层 service 的 `session_operation` 不足以表达 cache 自身的 ownership/liveness contract。

## 2. 本阶段实现

修改：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\project_service.py
```

### 2.1 Canonical session 路径

当 `ProjectService` 绑定 `LibrarySession` 时，`get_home()` 的 directory cache 现在使用：

```python
DirectoryCache(
    db_conn,
    library_root=root,
    session=self._session,
)
```

因此 cache 的：

- root identity；
- connection validation；
- `session.operation()` 生命周期租约；

都与当前 service session 对齐。

### 2.2 Legacy/standalone 兼容

当 `ProjectService(session=None)` 时仍保留：

```python
DirectoryCache(db_conn)
```

这是有意保留的兼容边界，用于：

- raw in-memory fixture；
- 历史 LAN adapter；
- 旧测试 double；
- standalone service 调用。

本阶段没有扩大 `allow_unmanaged`，也没有将 raw constructor 全面禁用。

### 2.3 其他已有 dirty 修改

当前 `ProjectService` 工作树中还存在来自更早会话的变更，例如：

- `_connection()` ownership helper；
- 项目扫描 warning；
- SQLite `ProgrammingError`/`sqlite3.Error` 错误边界调整。

本阶段没有回滚、重排或覆盖这些既有修改，只在 `_attach_cached_thumbnails()` 增加 session-bound 分支。

## 3. 新增回归

新增：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_project_service_session_binding.py
```

覆盖：

1. session-bound `ProjectService` 构造 `DirectoryCache(..., session=current_session)`；
2. canonical `ProjectService` 在 session 关闭后拒绝 `get_home()`；
3. 既有 standalone `DirectoryCache(conn)` test double 仍兼容。

## 4. 验证证据

### ProjectService 定向回归

```text
python -m pytest -q --tb=short tests/integration/test_project_service.py tests/integration/test_project_service_session_binding.py
```

结果：

```text
34 passed, 1 skipped
```

skip 仍为 Windows 当前进程缺少 directory symlink 权限。

### 新增测试独立运行

```text
python -m pytest -q --tb=short tests/integration/test_project_service_session_binding.py
```

结果：

```text
2 passed
```

### 静态门禁

```text
ruff check AssetsManager/application/project_service.py tests/integration/test_project_service_session_binding.py
pyright AssetsManager/application/project_service.py
git diff --check
```

结果：

```text
All checks passed
0 errors, 0 warnings, 0 informations
退出码 0
```

## 5. 尚未完成

本阶段只收口了 `ProjectService` 内部一个 canonical raw-shaped helper，不代表 raw connection migration 完成。仍有：

- `ProjectData` / `TagStore` raw constructors；
- raw `DirectoryCache` compatibility；
- Auth/Share/Tag/Metadata/AssetIndex/PluginMetadata repositories 的 raw constructors；
- Auth/Share service `session=None`；
- benchmark、历史 fixture、第三方/历史插件矩阵。

因此仍不能直接执行：

```python
allow_unmanaged: bool = False
```

## 6. 下一切片建议

继续按低风险顺序：

```text
ProjectData/TagStore canonical session-bound constructor
→ Auth/Share service canonical session enforcement
→ repository session/root-bound constructors
→ benchmark/history fixture legacy adapter
→ plugin compatibility matrix
→ 最后切换 allow_unmanaged 默认值
```

每一步都必须同时提供：

- canonical managed/same-root；
- managed foreign-root；
- unmanaged legacy；
- closed connection；
- session closing/closed；
- old object retained after reopen；

回归矩阵。

## 7. 当前质量判断

> G10 已完成 ProjectService 内部 DirectoryCache 的 canonical session binding，且保持 legacy standalone 兼容；AssetsManager 项目整体仍未完成，raw connection 收口和插件/历史 fixture 迁移必须继续推进。

## 8. G10 后全量非 E2E 门禁

```text
python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
```

结果：

```text
2290 passed, 4 skipped, 1 warning
```

G10 新增 2 条测试已包含在上述结果中。当前 4 条 skip 仍全部来自 Windows symlink/directory-symlink 权限限制；1 条 warning 仍为既有 zipfile duplicate-name warning。

全量静态门禁：

```text
ruff check AssetsManager tests    -> All checks passed
pyright                           -> 0 errors, 0 warnings, 0 informations
git diff --check                 -> 退出码 0
```
