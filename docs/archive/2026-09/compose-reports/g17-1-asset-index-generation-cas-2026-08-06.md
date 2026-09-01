# G17.1 Asset Index Generation / CAS — 深度审查与收口报告

**日期：** 2026-08-06  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**基线：** `master` / `fbf3403 Enforce schema object integrity for v6`  
**状态：** G17.1 本轮已完成最小安全收口；工作区仍是多会话混合 dirty，未 staging、未 commit，不能宣称整个项目完成。

## 1. 当前工作树变化

在本轮开始时，其他并行会话已经向 core 写域加入了 asset-index revision 骨架：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\schema_defs.py`
  - `asset_index_state(library_root, revision, updated_at)`；
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\db_migrations.py`
  - migration v9 `asset_index_state`；
  - 当前 schema version 已继续包含并行 commerce 的 v10 quota migration。

本轮不回滚这些改动，只审查并收口 asset-index repository/service 与 FileOperationService 的相关写域。

## 2. 已确认的 CAS 骨架

现有实现已经具备：

1. `AssetIndexService.index_directory()` 在 filesystem scan 前读取 root revision；
2. `AssetIndexRepository.replace_parent_entries()` 在同一 transaction scope 内执行 expected-revision CAS，再进行 rows replacement；
3. `index_directory_tree()` 在 scan 前读取一次 revision，首个 replacement 推进 revision，后续 parent replacement 不重复推进；
4. scan failure / `os.walk(onerror)` 不进入 destructive publish；
5. migration v9 后 canonical database 会拥有 `asset_index_state` 表。

这些骨架方向正确，但原实现仍存在三个会导致数据一致性问题的 P1 缺口。

## 3. 本轮完成的 P1 修复

### 3.1 raw delete 不再静默绕过 revision

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\asset_index_repository.py`

问题：

```text
AssetIndexRepository(conn)
AssetIndexService.remove_entry(conn, path)
```

这种 legacy raw delete 没有 bound root，原先会删除 assets row 但不推进 `asset_index_state.revision`，旧 scan 可能重新插入已删除条目。

修复：

- unbound `delete_entry()` / `delete_path()` 在同一事务内先发现受影响 rows 的 `library_root`；
- 对每个受影响 root 推进 revision，再执行 raw delete；
- 旧数据库没有 `asset_index_state` 时保留 legacy compatibility，不让历史 raw fixture 因缺表直接崩溃；
- bound repository 仍使用 captured root identity，不依赖 SQL 推断。

### 3.2 tree publish 清理完整 subtree 的旧 rows

问题：

原 tree publish 只替换本次 `os.walk()` 实际访问到的 parent。若旧目录在 scan 前被删除，该 parent 不再出现在 snapshots 中，旧 `assets` rows 会永久残留。

修复：

- 新增 repository-level `clear_subtree()`；
- tree CAS savepoint 内先清理目标 subtree 的 descendants；
- 保留 scan target 自身的 directory row，避免从父目录投影中误删目标目录；
- 再按 snapshots 写入当前 filesystem 结果；
- scan 未完成、发生 `onerror` 或 CAS conflict 时不执行 destructive clear；
- clear、revision advance、rows replacement 处于同一个 DB savepoint/commit boundary。

### 3.3 CAS conflict 不再让已完成的 filesystem mutation 失败

文件：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\file_operation_service.py`

问题：

filesystem move/copy 完成后，asset-index refresh 可能因其他 writer 已发布更新而发生 `AssetIndexRevisionConflict`。如果异常直接冒泡，调用方会看到文件操作失败，但 filesystem 已经不可回滚。

修复：

- `_refresh_parents()` 捕获 revision conflict，接受新 revision 胜出；
- `_refresh_directory_tree()` 同样捕获并忽略 stale writer conflict；
- 其他 OSError、数据库异常仍不被吞掉；
- 这只处理“新 writer 已成功发布”的 CAS conflict，不把一般索引错误伪装成成功。

## 4. 新增回归测试

新增/扩展：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_asset_index_repository_session_binding.py`
  - bound revision CAS 拒绝 stale writer；
  - revision 在 bound delete 后推进；
  - raw unbound delete 能根据受影响 root 推进 revision；
  - commit/savepoint failure rollback。
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_asset_index_service.py`
  - stale scan 在 publish 前被 CAS 拒绝；
  - 完整 tree refresh 清理已经消失的 descendant rows；
  - tree failure 整体 rollback。
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_file_operation_service.py`
  - filesystem rename 完成后 asset-index revision conflict 不再反向报告 rename 失败。

## 5. 验证结果

### 5.1 G17.1 定向回归

```text
python -m pytest -q \
  tests/core/test_db_migrations.py \
  tests/integration/test_asset_index_repository_session_binding.py \
  tests/integration/test_asset_index_service.py \
  tests/integration/test_search_service.py \
  tests/integration/test_file_operation_service.py \
  tests/lan/test_lan_api.py --tb=short

360 passed, 2 skipped
```

跳过项是 Windows 当前进程没有创建 symlink 的权限（WinError 1314）。

### 5.2 全量 Python 回归

```text
python -m pytest -q tests/core tests/unit tests/integration tests/desktop tests/lan --tb=short

2445 passed, 4 skipped, 1 failed, 1 warning
```

唯一失败仍来自保护域 WebUI：

```text
tests/unit/test_architecture_boundaries.py::test_browser_auth_contract_has_no_bearer_token_state
```

当前并行 WebUI 类型投影仍含：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\types\api.ts
    delivery_token: string;
    delivery_url: string;
```

本轮未修改 `webui\**`，也未放宽架构断言。

### 5.3 静态门禁

```text
ruff check AssetsManager tests
All checks passed

git diff --check -- AssetsManager tests
All checks passed

pyright
2 errors
```

剩余 Pyright 错误均在并行 commerce 工作线：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\order_service.py:68
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\order_service.py:72
```

都是 `Connection | None` 传给需要 `Connection` 的 repository 构造函数。本轮不擅自修改该并行写域。

## 6. 尚未完全关闭的风险

### P2：跨 process / SQLite busy retry 仍未完全覆盖

本轮已增加两个 SQLite connections 指向同一 file-backed database 的 stale-writer 回归：

1. writer A scan 后暂停；
2. writer B publish 并推进 revision；
3. writer A CAS 失败；
4. writer A transaction rollback，既有 rows/revision 不被半完成写入污染。

尚未覆盖真正独立 process 的锁竞争、busy timeout、进程崩溃恢复与 retry policy，后续仍需补充。

### P2：schema contract 尚未验证列类型、NOT NULL 与 CHECK

`asset_index_state` contract 当前主要验证列名、primary key 等结构，尚未对已有不兼容同名表严格验证：

- `revision INTEGER`；
- `revision NOT NULL`；
- `revision >= 0` CHECK；
- `updated_at REAL NOT NULL`。

正常 migration 路径已通过测试，但异常旧数据库的 schema integrity 仍需增强。

### P2：跨 projection mutation 的 revision admission

asset-index 自身的 replacement/delete 已推进 revision，但外部 projection（metadata、tags、favorites、thumbnail cache）并非全部共享同一个 asset-index CAS command。filesystem 与多个 DB projection 也仍不是跨系统原子事务，后续需要 reconciliation/generation marker。

## 7. 下一步计划

### G17.2

1. 增加独立 process / SQLite busy-lock 回归；
2. 继续扩展 CAS conflict 后 SQLite transaction state / rows / revision 断言；
3. 为 `asset_index_state` 增加严格 schema integrity contract；
4. 明确 busy/locked retry 与 bounded retry policy；
5. 将 FileOperationService 的冲突降级结果纳入可观测 telemetry，而不是静默 continue；
6. 评估是否为 canonical scan API 增加 `AssetIndexPublishResult`，区分 published、empty、scan_failed、stale。

## 8. 结论

G17.1 的 persistent revision/CAS 骨架已从“只推进 revision”进一步收口到：

- raw mutation 不再静默绕过 revision；
- 完整 tree refresh 不再保留已消失 descendant rows；
- filesystem mutation 不再被已经胜出的新 index writer 反向判定为失败；
- session binding、transaction rollback、migration wiring 与现有 LAN compatibility 回归保持通过。

但当前仍不能宣称整个工程完成：WebUI 保护域仍有 1 个架构失败，full Pyright 仍有 2 个并行 commerce 错误，G17.2 真实双 connection 并发测试与强 schema validation 尚未完成。

本报告不执行 staging/commit，不回滚、不删除任何其他会话产物。
