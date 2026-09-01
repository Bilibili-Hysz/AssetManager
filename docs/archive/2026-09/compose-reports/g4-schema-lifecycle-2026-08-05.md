# G4 schema-object integrity and retained lifecycle continuation

日期：2026-08-05  
范围：Auth/Share v6 schema object integrity、repository compatibility ensure、DirectoryCache/AssetService/session lifecycle、runtime retained holder。

## 1. 本轮目标

上一轮审查确认两个 P1 缺口：

- 已记录到 v6 的数据库缺少 schema-object replay/integrity 验证；
- retained `DirectoryCache`、`AssetService` 与已 materialize 的 LAN holder 没有统一 session liveness 边界。

本轮采取互斥写域并行处理，未触碰 WebUI、`tests/e2e/**` 或 `tmp/**`。

## 2. Schema-object integrity

共享 manifest/validator 位于：

- `AssetsManager/core/schema_defs.py`
- `AssetsManager/core/db_migrations.py`

覆盖对象：

- `schema_migrations`
- `users`
- `invite_codes`
- `share_links`

校验内容：

- 表存在性；
- 必需列；
- 主键；
- 必需唯一约束。

`migrate()` 在记录版本后以及已记录 v6 的 skip path 都会复核对象形状；Auth/Share raw repository ensure 复用同一 validator，缺表仍保留兼容创建，已有错误表 fail-closed。

为保持 repository layering，repository 只依赖 `core.schema_defs`，不直接导入 `core.db_migrations`；对应 architecture boundary 回归已通过。

## 3. Retained lifecycle

- `DirectoryCache` 支持可选 session/liveness，canonical 构造绑定当前 `LibrarySession`；读、写、root validation 和清理入口均受 scope 保护。
- `AssetService` 支持可选 session，canonical `list_directory()`/`summarize_directories()` 进入 `session_operation`；生命周期错误继续抛出，不降级为空 listing。
- `_LanServicesHolder.get()` 在 ready 快速路径先检查 session；已关闭 session 不再取得 retained LAN services。
- `ApplicationBootstrap.runtime_for()` cache hit 检查 runtime open 状态；`LibraryRuntime.next_revision()` 只允许 open 状态。

## 4. 验证

```text
python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
2183 passed, 4 skipped, 1 warning

ruff check AssetsManager tests
All checks passed!

pyright
0 errors, 0 warnings, 0 informations

AST
297 Python files parsed; 0 errors

git diff --check
通过；仅输出工作树既有 LF/CRLF 转换提示
```

4 条 skip 均为当前 Windows 进程缺少 symlink/directory-symlink 权限；1 条 warning 为既有 zipfile duplicate-name 测试警告。

## 5. 仍然未完成的长期任务

1. LAN 私有 `_allow_legacy_runtime` 仍存在；正常生产 facade 不暴露，但进程内可直接调用。下一波应先处理 `SearchService` provider-only 例外，再把旧 fixture 迁移到 test-only adapter，最后删除生产 fallback。
2. `LibraryContext.db_conn`、`InfoController` raw connection 与其他 retained raw fields 仍需继续 capability/liveness 收口。
3. ProjectService、InfoController、plugin discovery 等业务降级仍可能把 closed connection/schema/lifecycle 错误映射为 `0`、`[]` 或空字符串，应建立异常语义矩阵。
4. `allow_unmanaged=True` 仍是兼容迁移阶段默认值；未来可在所有 legacy 调用点收敛后再评估切换为拒绝默认，但不得直接破坏旧插件/fixture。
5. WebUI/E2E 尚未纳入主线验收，不据此宣称整个项目完成。

## 6. 操作记录

- 当前 HEAD 为 `fbf3403`（由并行代理创建，主会话未授权）；主会话未执行 staging/commit/reset/checkout/clean。
- 工作区仍为多会话混合 dirty 状态；本报告只记录事实，不尝试回滚或覆盖其他会话变更。
