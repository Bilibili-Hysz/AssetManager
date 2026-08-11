# G11：ProjectData / TagStore canonical session-bound 迁移

> 日期：2026-08-06
> 工作区：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
> 分支：`master`
> 本报告是主线继续开发记录，不是发布完成声明。

## 1. 阶段目标

承接 G3e/G10 的 raw connection 迁移路线，处理 canonical library session 中仍以 legacy-shaped constructor 存在的两个 core store：

```text
ProjectData
TagStore
```

本阶段目标不是删除 raw compatibility，而是建立可验证的 session binding，并保留历史构造行为。

## 2. 实现内容

### 2.1 `ProjectData`

修改：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\project_data.py
```

新增可选构造参数：

```python
ProjectData(root, db_conn=None, *, session=None)
```

session-aware 路径：

- `session` 存在且未显式传入 `db_conn` 时，从 `session.connection_for(root)` 获取连接；
- 显式 `db_conn` 与 session 同时存在时，校验连接对象必须是当前 session 的 connection；
- 保存当前 session binding；
- 从 session context 继承 liveness token；
- 不改变现有 notes、URL、directory-size 等业务方法的 raw API。

新增内部绑定方法：

```python
_bind_session(session)
```

它拒绝：

- 同一 ProjectData 重新绑定到另一个 session；
- 传入 foreign/unmanaged 且不属于当前 session 的 connection。

### 2.2 `TagStore`

修改：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\tag_store.py
```

新增同构支持：

```python
TagStore(root, db_conn=None, *, session=None)
```

保留：

- TagRepository 现有调用链；
- raw `TagStore(root, db_conn=raw_conn)` 兼容；
- 现有 resolve cache；
- 现有 liveness 失效语义。

### 2.3 `LibraryService` canonical assembly

修改：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\library_service.py
```

由于当前 `LibraryContext` 先于 `LibrarySession` 创建，不能在初始构造时直接传入 session。因此采用安全的两阶段绑定：

```text
构造 managed connection + core stores
→ 创建 LibraryContext
→ 创建 LibrarySession
→ 调用两个 store 的 _bind_session(session)
→ 发布 canonical session
```

绑定发生在 session 发布前，绑定失败会进入既有 opening cleanup，不会发布半初始化 session。

## 3. Legacy 兼容边界

以下路径仍然保留：

```python
ProjectData(root)
ProjectData(root, db_conn=raw_conn)
TagStore(root)
TagStore(root, db_conn=raw_conn)
```

本阶段没有：

- 修改 `DatabaseManager.validate_connection_owner()` 默认值；
- 禁止 raw in-memory fixtures；
- 移除 `get_project_data()` / `get_store()`；
- 将第三方插件或历史 benchmark 强行迁移。

## 4. 新增回归

新增：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_core_store_session_binding.py
```

覆盖：

1. LibraryService canonical context 中 ProjectData/TagStore 绑定当前 session；
2. session-aware constructor 复用 session connection；
3. session 关闭后 retained core store 拒绝操作；
4. session-aware constructor 拒绝 unmanaged foreign connection；
5. 既有 raw store 单元测试和 legacy fixture 继续通过。

## 5. 定向验证

```text
python -m pytest -q --tb=short tests/integration/test_core_store_session_binding.py tests/unit/test_project_data.py tests/core/test_tag_store.py
```

结果：

```text
33 passed
```

```text
python -m pytest -q --tb=short tests/integration/test_library_service.py tests/integration/test_undo_service.py tests/integration/test_core_store_session_binding.py
```

结果：

```text
91 passed
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
2295 passed, 4 skipped, 1 warning
```

全量静态门禁：

```text
ruff check AssetsManager tests -> All checks passed
pyright -> 0 errors, 0 warnings, 0 informations
git diff --check -> 退出码 0
```

skip 仍是 Windows 当前进程缺少 symlink/directory-symlink 权限；warning 仍是既有 zipfile duplicate-name warning。

## 7. 尚未完成

本阶段只完成 core store 的 session binding，raw connection migration 仍未完成。剩余重点：

- Auth/Share service 的 canonical session 强制；
- repositories 的 session/root-bound constructor；
- `PluginMetadataRepository` raw compatibility 迁移；
- benchmark、历史 fixture、第三方/历史插件矩阵；
- raw adapter 可观测与静态禁止新增；
- 最后才切换 `allow_unmanaged` 默认值。

仍不可直接执行：

```python
allow_unmanaged: bool = False
```

## 8. 当前质量判断

> G11 已完成 ProjectData/TagStore 的 canonical session binding，并保持 raw legacy 兼容；完整非 E2E 回归与静态门禁通过。AssetsManager 整体仍未完成，下一阶段应处理 Auth/Share service 的 canonical session contract，再进入 repository 迁移。
