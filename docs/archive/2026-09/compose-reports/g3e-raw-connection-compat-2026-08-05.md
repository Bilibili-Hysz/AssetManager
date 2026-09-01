# G3e raw connection compatibility boundary

日期：2026-08-05  
范围：`DatabaseManager` ownership API、legacy core/controller 构造点、application service provider 校验、非 E2E 回归。

## 目标

在不破坏旧插件和历史 fixture 的前提下，把 unmanaged raw SQLite connection 的兼容语义从隐式行为改为显式 API 语义，并保持 canonical service assembly 的严格 owner contract。

## 实现

- `DatabaseManager.validate_connection_owner(root, conn, *, allow_unmanaged=True)`：
  - managed connection 继续校验 captured root identity；
  - managed foreign-root connection 抛出 `ValueError`；
  - unmanaged connection 在 `allow_unmanaged=False` 时抛出 `RuntimeError`；
  - `allow_unmanaged=True` 保留 raw compatibility，并原样返回 connection。
- `DatabaseManager.require_managed_connection_owner()` 继续作为 canonical strict boundary，不接受 unmanaged connection。
- 以下 legacy 调用点明确传入 `allow_unmanaged=True`：
  - `AssetsManager/core/project_data.py`
  - `AssetsManager/core/tag_store.py`
  - `AssetsManager/core/directory_cache.py`
  - `AssetsManager/controllers/info_controller.py`
  - `AssetsManager/application/metadata_service.py`
  - `AssetsManager/application/project_service.py`
  - `AssetsManager/application/search_service.py`
  - `AssetsManager/application/tag_service.py`
  - `AssetsManager/application/thumbnail_service.py`
  - `AssetsManager/application/library_export_service.py`
  - `AssetsManager/application/database_integrity_service.py`
  - `AssetsManager/application/database_maintenance_service.py`
- ownership 测试覆盖 unmanaged opt-in、unmanaged reject、managed same-root、managed foreign-root 与 canonical strict API。

## 验证证据

命令：

```text
python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
```

结果：`2173 passed, 4 skipped, 1 warning`。

```text
ruff check AssetsManager tests
All checks passed!

pyright
0 errors, 0 warnings, 0 informations

git diff --check
通过；输出仅包含工作树既有 LF/CRLF 转换提示
```

4 条 skip 均为当前 Windows 环境缺少 symlink/directory-symlink 权限；1 条 warning 为既有 zipfile duplicate-name 测试警告。

## 未解决边界

- `allow_unmanaged` 默认仍为 `True`，这是兼容迁移阶段的有意决策，不应表述为“所有 raw connection 默认拒绝”。
- `InfoController` 与 `PluginMetadataRepository` 等 raw compatibility API 仍需要后续 capability/token 或专用 legacy adapter 设计。
- WebUI、`tests/e2e/**`、`tmp/**` 保护域未触碰，也未据此宣称整个项目完成。
- 工作区仍是其他会话混合 dirty 状态；本轮未 staging、未 commit、未 reset、未 checkout、未 clean。
