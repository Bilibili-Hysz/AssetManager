# G5 LAN SearchService 与异常语义 continuation

日期：2026-08-06  
范围：SearchService session binding、LAN canonical strict binding、ProjectService/InfoController lifecycle/schema error propagation。

## 1. SearchService contract

`SearchService` 现在支持可选 `LibrarySession`：

- standalone `SearchService()` 与 raw fixture 继续允许 `_session is None`；
- canonical bootstrap 传入当前 session；
- `search_by_tags()`、`search_by_name()`、`search_by_name_indexed()` 通过 `session_operation` 取得 session operation lease；
- canonical LAN binding 要求 SearchService `_session is current session`；`None` 或 foreign session fail-closed；
- legacy fallback 仍允许 provider-only SearchService，作为尚未迁移完成的兼容边界。

## 2. Business error semantics

ProjectService 的聚合 helper 对 `sqlite3.ProgrammingError`（典型 closed connection）统一重新抛出，避免将资源生命周期错误映射成空数据；foreign-root/ownership `ValueError` 也不再被缓存聚合层外层吞掉。

InfoController 的 plugin URL 持久化对 `sqlite3.ProgrammingError` 重新抛出；普通 `OSError` 与可选 plugin persistence 的一般 SQLite 错误仍按旧的“记录并继续”语义处理。

本轮没有改变真实无数据返回 `[]`/`0`/`""` 的正常语义，也没有把所有普通文件系统故障强行升级。

## 3. 验证证据

专项：

```text
python -m pytest -q --tb=short \
  tests/integration/test_search_service.py \
  tests/lan/test_lan_api.py \
  tests/integration/test_project_service.py \
  tests/unit/test_info_controller.py
305 passed, 2 skipped
```

完整非 E2E：

```text
python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
2191 passed, 4 skipped, 1 warning
```

静态：

```text
ruff check AssetsManager tests
All checks passed!

pyright
0 errors, 0 warnings, 0 informations

git diff --check
通过；仅有工作树既有 LF/CRLF 转换提示
```

4 条 skip 为当前 Windows 缺少 symlink/directory-symlink 权限；1 条 warning 为既有 zipfile duplicate-name 测试警告。

## 4. 未完成长期边界

- LAN `_allow_legacy_runtime` 尚未移出生产实现；下一波应先把 `tests/lan/test_lan_api.py` 的旧 fixture 改为 test-only canonical adapter，再删除生产 fallback。
- ProjectService/InfoController 仍需更完整的 `partial/degraded` 业务结果契约，尤其是普通 OSError/SQLite transient error 与 lifecycle/schema error 的区分。
- retained `LibraryContext.db_conn`、InfoController raw repository 与 legacy raw connection API 仍未完全 capability 化。
- WebUI、`tests/e2e/**`、`tmp/**` 继续保持保护域。

## 5. 工作区事实

- 当前分支：`master`。
- 当前 HEAD：`fbf3403`，该提交由并行代理在未获主会话授权时创建；本主会话未执行 staging/commit/reset/checkout/clean，未回滚该提交。
- 工作区仍为多会话混合 dirty 状态，暂存区为空。
