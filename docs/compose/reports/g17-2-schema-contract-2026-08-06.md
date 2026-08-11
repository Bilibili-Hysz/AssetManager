# G17.2 Asset Index Schema Contract — 深度审查报告

**日期：** 2026-08-06  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**基线：** `master` / `fbf3403 Enforce schema object integrity for v6`  
**状态：** G17.2 schema-contract 与双 connection stale-writer 回归已完成；工作区仍是多会话混合 dirty，未 staging、未 commit。

## 1. 本轮目标

在 G17.1 persistent revision/CAS 基础上继续收口：

1. 严格验证 `asset_index_state` 的列类型、NOT NULL 和 revision CHECK；
2. 验证两个 SQLite connections 对同一 file-backed database 的 stale-writer 行为；
3. 保持 raw compatibility、session binding、FileOperationService conflict handling 不回归；
4. 不修改 WebUI 保护域，不接管并行 commerce 业务写域。

## 2. 已完成

### 2.1 严格 schema contract

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\schema_defs.py`

扩展 `SchemaObjectContract`：

- `column_contracts`：列类型与 NOT NULL 要求；
- `checks`：表级 CHECK 要求。

`asset_index_state` 现在要求：

```text
library_root TEXT NOT NULL PRIMARY KEY
revision     INTEGER NOT NULL
updated_at   REAL NOT NULL
CHECK (revision >= 0)
```

既有同名但类型、NOT NULL 或 CHECK 不兼容的表会在 migration/schema validation 阶段 fail-closed，不再等到 repository 读写时才暴露异常。

同时修复了 schema foreign-key validator 的 Pyright 类型问题：

```text
AssetsManager/core/schema_defs.py
```

### 2.2 双 connection stale-writer 验证

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_asset_index_service.py`

新增 file-backed SQLite 测试：

1. writer A 读取 revision 并暂停在 filesystem scan 后；
2. writer B 使用第二个 SQLite connection 成功 publish；
3. writer A 的 expected revision 失效并抛出 `AssetIndexRevisionConflict`；
4. writer A transaction rollback；
5. writer B 的 rows/revision 保持完整。

### 2.3 保留 G17.1 修复

本轮继续保留并验证：

- raw delete revision admission；
- tree subtree stale-row 清理；
- filesystem mutation 后 CAS conflict 不反向判定文件操作失败；
- repository transaction/savepoint failure rollback；
- canonical root/session/connection binding。

## 3. 验证结果

### 定向验证

```text
python -m pytest -q \
  tests/core/test_db_migrations.py \
  tests/integration/test_asset_index_repository_session_binding.py \
  tests/integration/test_asset_index_service.py \
  tests/integration/test_search_service.py \
  tests/integration/test_file_operation_service.py \
  tests/lan/test_lan_api.py --tb=short

362 passed, 2 skipped
```

跳过项仍是 Windows symlink 权限限制（WinError 1314）。

### 全量 Python 回归

```text
python -m pytest -q tests/core tests/unit tests/integration tests/desktop tests/lan --tb=short

2446 passed, 4 skipped, 1 failed, 1 warning
```

唯一失败仍是保护域 WebUI 架构边界：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_architecture_boundaries.py
::test_browser_auth_contract_has_no_bearer_token_state
```

触发文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\types\api.ts
```

其中仍存在 `delivery_token` / `delivery_url` 类型投影。本轮未修改 `webui\**`。

### 静态检查

```text
ruff check AssetsManager tests
通过

git diff --check -- AssetsManager tests
通过
```

全量 Pyright 仍只有并行 commerce 工作线的两个错误：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\order_service.py:68
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\order_service.py:72
```

## 4. 当前剩余风险

### P2：busy-lock / retry policy 尚未实现

双 connection CAS 测试验证了正常竞争窗口，但没有定义：

- SQLite `database is locked` 的 bounded retry；
- 独立进程锁竞争；
- retry 时是否重新读取 revision；
- retry 后是否重新 scan 或只重试 publish；
- busy failure 对 FileOperationService 的可观测结果。

下一阶段应先定义 retry contract，再实现，不能在 repository 层盲目吞掉 `OperationalError`。

### P2：publish result 仍是 int compatibility API

`index_directory()` / `index_directory_tree()` 仍主要返回 `int`，无法严格区分：

- published；
- empty；
- scan_failed；
- stale/conflict。

FileOperationService 当前对已经胜出的新 writer conflict 做 best-effort continue，但还没有 telemetry/result projection。

### P2：跨 projection revision 尚未统一

asset-index 的 revision 已覆盖自身 replacement/delete；metadata、tags、favorites、thumbnail 等 projection 仍不是同一个 atomic CAS command。filesystem mutation 与 DB projection 也不是真正跨系统原子事务。

## 5. 下一步 G17.3

1. 设计 `AssetIndexPublishResult`，保留现有 int API 作为 compatibility wrapper；
2. 明确 scan failure/stale/empty 的状态和调用方处理；
3. 增加 bounded busy-lock retry，retry 前重新读取 revision；
4. 将 FileOperationService 的 conflict/scan degradation 写入 telemetry；
5. 评估 asset-index 与 metadata/tag projection 的统一 command/outbox 或 reconciliation marker。

## 6. 结论

G17.2 已完成 `asset_index_state` 严格 schema validation，并验证了 file-backed 双 connection stale-writer CAS 行为；当前 G17.2 写域没有新增 Python 逻辑失败。整个项目仍受保护域 WebUI 架构失败和并行 commerce Pyright 错误阻塞，不能宣称工作区完全一致或完成。

本报告不执行 staging/commit，不回滚、不删除任何其他会话产物。
