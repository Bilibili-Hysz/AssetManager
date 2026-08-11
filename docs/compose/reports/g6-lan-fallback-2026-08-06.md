# G6 LAN legacy fallback removal

日期：2026-08-06  
范围：LAN server canonical runtime contract、test-only legacy runtime adapter、SearchService session binding、non-E2E 回归。

## 1. 处置目标

上一轮审查确认：正常生产入口不会开启 `_allow_legacy_runtime`，但私有 `_LanServerImpl` 仍可由进程内代码显式启用，从而绕过 `services_snapshot`、session operation 和部分 service-session identity contract。

本轮将兼容责任移出生产实现，而不是继续扩大生产 fallback。

## 2. 生产变更

`AssetsManager/lan/server.py`：

- 删除 `_LanServerImpl` 的 `_allow_legacy_runtime` 参数；
- 删除 runtime `.services` fallback；
- 删除 session 缺少 `operation()` 时的 `nullcontext()` fallback；
- 始终要求 canonical：
  - `runtime.services_snapshot`；
  - `session.operation()`；
  - `lan_services` projection；
  - `sharing_services` projection；
  - current session/provider/db identity。

`SearchService` 已在前一波加入可选 session，canonical bootstrap 注入当前 session，LAN strict binding 要求 canonical SearchService 绑定当前 session；standalone/raw fixture 仍可在测试适配层兼容。

## 3. Test-only adapter

新增：

- `tests/lan/support/legacy_runtime_adapter.py`
- `tests/lan/support/__init__.py`

adapter 只为历史 `SimpleNamespace` fixture 补齐 canonical runtime contract：session operation、services snapshot、LAN/sharing projection、legacy provider-only SearchService 的 session binding，以及旧 ShareService fixture 的 root/token 元数据。

生产代码没有导入测试 adapter；测试仍覆盖旧 fixture 的行为，但不再通过生产 fallback 参数启动服务器。

## 4. 回归证据

```text
python -m pytest -q --tb=short tests/lan/test_lan_api.py
224 passed

python -m pytest -q --tb=short tests/lan/test_server_lifecycle.py tests/lan/test_lan_api.py
263 passed

python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
2192 passed, 4 skipped, 1 warning
```

静态：

```text
ruff check AssetsManager tests
All checks passed

pyright
0 errors, 0 warnings, 0 informations

git diff --check
通过；仅有工作树既有 LF/CRLF 转换提示
```

## 5. 后续长期任务

- raw DB compatibility：评估将 `DatabaseManager.validate_connection_owner(..., allow_unmanaged=True)` 从兼容迁移默认值改为拒绝默认，前提是插件/fixture 迁移矩阵完整。
- InfoController/PluginMetadataRepository：继续把 raw repository 能力收口为 session/capability-bound API。
- 业务 degraded contract：为普通 OSError/SQLite transient error 建立显式 `partial/degraded` 结果，不把不完整数据伪装成正常空值。
- retained raw fields：继续处理 `LibraryContext.db_conn` 与其他 retained raw resource 读取入口。
- WebUI/E2E：仍是保护域，未纳入本主线验收。

## 6. 工作区事实

- 当前分支：`master`。
- 当前 HEAD：`fbf3403`，该提交由并行代理创建；主会话未执行 staging/commit/reset/checkout/clean。
- 当前工作区仍为多会话混合 dirty 状态；暂存区为空。
