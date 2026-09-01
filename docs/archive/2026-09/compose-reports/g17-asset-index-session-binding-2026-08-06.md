# G17 AssetIndexRepository / AssetIndexService session binding — 深度审查报告

**日期：** 2026-08-06
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
**分支 / HEAD：** `master` / `fbf3403 Enforce schema object integrity for v6`
**状态：** G17 本轮后端收敛已完成并通过可执行回归；工作区仍是多会话混合 dirty，未 staging、未 commit，不能宣称整个项目完成。

## 1. 本轮边界与安全约束

本轮只处理 G17 资产索引及其 canonical wiring，保留其他会话的未完成改动，不执行：

- `git reset`、`git checkout`、全量 `git clean`；
- 回滚、覆盖或批量格式化其他会话改动；
- 修改保护域：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\**`；
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\e2e\**`；
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tmp\**`。

并行只读审查确认，LAN/commerce 工作线仍在变动；本轮没有认领其写域。

## 2. G17 已完成内容

### 2.1 AssetIndexRepository canonical contract

`AssetsManager/repositories/asset_index_repository.py` 现提供：

1. `AssetIndexRepository.for_session(session)` canonical factory；
2. 真实 `LibrarySession` marker、captured `RootIdentity` 与 managed connection owner 校验；
3. same-session 幂等、foreign-session / foreign-root 拒绝；
4. repository operation lease 与关闭后的 fail-closed 行为；
5. bound-root containment，bound `get_entry` / delete SQL 均带 `library_root` predicate；
6. `AssetIndexRepository(conn)` raw compatibility path 保留，但不伪装成 canonical session object；
7. `transaction_scope(commit, savepoint)` 下沉所有 asset-index transaction primitives；
8. `replace_parent_entries`、`delete_entry`、`delete_path` 统一经过 repository transaction scope。

本轮额外修复了 commit failure 清理：

- 无 savepoint scope 在自身开启事务时，异常或 commit 失败会 rollback；
- savepoint scope 在无 outer transaction 时先 `BEGIN`，避免释放 outermost SQLite savepoint 时隐式提交；
- commit 失败会回滚整个 scope 所拥有的事务；
- 调用方已有 outer transaction 时仍保持 caller ownership，不由 bound session 擅自 commit。

### 2.2 AssetIndexService bound facade

`AssetsManager/application/asset_index_service.py` 现提供：

- `AssetIndexService.for_session(session)`；
- canonical bound facade 的 index/query/search/remove/count/get API；
- raw compatibility API 保留，且 raw managed connection 会经过 owner/root 校验；
- tree indexing 使用 repository-level savepoint，逐目录 replacement 使用 `commit=False`，失败时整体 rollback；
- service 不再直接执行 `conn.execute` / `SAVEPOINT` / `ROLLBACK TO` / `RELEASE SAVEPOINT`；
- 同一 canonical root 的多个 facade 共享 refresh lock，不再只按 session object 分片。

### 2.3 SearchService / Bootstrap / FileOperation wiring

- `ApplicationBootstrap` 为真实 session 创建并注入 session-bound `AssetIndexService`；
- LAN lazy holder 恢复为兼容既有 factory monkeypatch 的精确 partial：
  `partial(self._build_lan_services, connection_provider=provider)`；
- `_build_lan_services()` 仍能在真实 session 下自建 bound index service，fake session 维持兼容 raw container fallback；
- `SearchService` 在真实 `LibrarySession` 构造且未显式注入 index service 时自动创建 `AssetIndexService.for_session(session)`；注入的 index service 若属于其他 session 则 fail-closed；
- `FileOperationService` 复用 Bootstrap 创建的 bound AssetIndexService，move/delete projection 与 index transaction boundary 保持现有集成。

## 3. 新增/强化回归测试

新增或扩展：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_asset_index_repository_session_binding.py`
  - canonical binding、foreign root/session、close、outer transaction；
  - no-savepoint commit failure rollback；
  - savepoint commit failure rollback；
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_asset_index_service.py`
  - canonical facade index/query/search/remove；
  - same-session 与 same-root refresh lock；
  - caller outer transaction preservation；
  - tree replacement failure 全体 rollback；
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_search_service.py`
  - real session 下 SearchService 自动绑定 AssetIndexService。

## 4. 验证结果

### 4.1 定向 G17 与 LAN compatibility

```text
python -m pytest -q \
  tests/integration/test_asset_index_repository_session_binding.py \
  tests/integration/test_asset_index_service.py \
  tests/integration/test_search_service.py \
  tests/integration/test_file_operation_service.py \
  tests/lan/test_lan_api.py --tb=short

308 passed, 2 skipped
```

跳过项均为 Windows 当前进程没有创建 symlink 的权限（WinError 1314），不是 G17 逻辑失败。

### 4.2 全量 Python 回归

```text
python -m pytest -q tests/core tests/unit tests/integration tests/desktop tests/lan --tb=short

2424 passed, 4 skipped, 1 failed, 1 warning
```

唯一失败：

```text
tests/unit/test_architecture_boundaries.py::test_browser_auth_contract_has_no_bearer_token_state
```

失败来自保护域 WebUI 类型投影：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\types\api.ts:450
    delivery_token: string | null;
```

本轮没有修改该文件，也没有放宽架构断言。

### 4.3 收集与静态门禁

```text
python -m pytest --collect-only -q -p no:cacheprovider
2449 tests collected

ruff check <G17 写域>
All checks passed

pyright <G17 写域>
0 errors, 0 warnings, 0 informations
```

全量静态门禁当前受并行 commerce 工作线阻塞，而非 G17：

```text
pyright
AssetsManager/application/order_service.py:68
AssetsManager/application/order_service.py:72
Connection | None -> Connection

ruff check AssetsManager tests
AssetsManager/lan/routes/seller_auth.py:7 unused get_lan
 tests/unit/test_commerce_services.py:3 unused sqlite3
```

同时 `git diff --check -- AssetsManager tests` 在当前并行写入快照中报告：

```text
AssetsManager/lan/api.py:291 new blank line at EOF
AssetsManager/lan/routes/__init__.py:174 new blank line at EOF
```

这些文件属于并行 LAN/commerce 工作线，本轮不代为修复或格式化。

## 5. 当前未关闭的工程风险

### P1：generation/CAS 尚未实现

当前 refresh lock 只能保证同一 canonical root 的进程内临界区（在当前 Python runtime registry 内）互斥，不能保证：

- 不同进程之间共享 scan generation；
- filesystem scan 与 DB publish 之间的 revision compare-and-swap；
- 旧 scan 在较新 revision 后拒绝覆盖；
- indexed search 明确返回 stale/degraded 状态。

下一阶段需要新增持久化的 per-root/per-parent revision contract（建议单独 migration 与 repository API），并在 scan 前读取 revision、publish 前 CAS；不要用内存锁冒充跨进程 generation guarantee。

### P1：scan failure 的结果 contract 尚未显式化

`index_directory()` 对 `os.scandir()` 的 `OSError` 仍返回 `0`，tree `os.walk()` 也没有统一的 `onerror` / degraded result contract。这样可以保留旧索引避免误删，但调用方无法区分：

- 不存在；
- 不可读；
- 成功扫描到空目录；
- 递归扫描部分失败。

下一阶段应先定义返回/异常 contract，再决定 stale rows 的保留与清理，不能简单把失败当空目录。

### P2：raw compatibility refresh lock 未跨 service instance 共享

canonical session facade 已按 root identity 共享锁；`AssetIndexService()` raw compatibility 实例仍各自持有本地锁。若 raw caller 继续需要并发安全，应以 managed connection/root key 建立独立 registry；否则必须在文档中明确 raw path 不提供跨实例 refresh serialization。

### P2：SearchService fake-session compatibility 仍是显式旁路

真实 `LibrarySession` 已自动绑定 strict AssetIndexService；结构性 fake session 为兼容既有 LAN injection tests 仍走旧 provider/raw path。该旁路不能进入 canonical Bootstrap production path，后续应统一测试 doubles 与 session contract，而不是扩大 raw fallback。

### P2：跨系统原子性仍未解决

filesystem move/delete 与多个 DB projection 不是跨系统原子事务；当前策略仍是：

- session-bound move 拒绝 caller outer transaction；
- projection cleanup 与 asset index 使用 DB savepoint/commit boundary；
- 若 filesystem mutation 成功后 DB projection 失败，需要后续 reconciliation / generation marker。

## 6. 并行工作线/保护域阻塞

1. WebUI auth type 将 `delivery_token` 放在浏览器 auth contract 中，触发架构边界失败；保护域不能由本轮修改。
2. WebUI AppHeader Logout role 与 protected E2E button-role contract 不一致（继承 G16 审查结论）；保护域不能由本轮修改。
3. LAN/commerce 工作线仍是未完成交接的混合 dirty：未跟踪 service/route 文件、runtime/bootstrap 正式投影未完全收口；本轮只做收集/静态观察，不回滚或替换其实现。

## 7. 长期任务规划

### G17.1 — generation/CAS

1. 设计 `asset_index_state`（或等价）持久化对象，按 canonical root 与 parent subtree 保存 revision；
2. 添加 migration/schema contract 与 repository-level read/advance/CAS API；
3. scan 读取 revision；filesystem enumeration 完成后在同一 DB transaction 内 CAS；
4. CAS 失败时丢弃旧快照并返回显式 stale/degraded 状态；
5. 增加多 facade、跨 runtime、commit failure、scan failure、stale writer 回归测试；
6. 与 FileOperationService move/delete projection cleanup 统一 revision admission。

### G18 — PluginMetadataService

G17 完成后再推进 G18；先锁定 plugin metadata canonical contract、cache miss 写入边界和 move/delete projection，不与 commerce runtime 接线混做。

## 8. 结论

G17 的 session/root/transaction wiring 已收口，G17 定向与全量 Python 回归均未发现 G17 失败。当前仍不能宣称整个工程一致：全量 Python 仅剩保护域 WebUI 架构失败；全量 pyright/ruff/diff-check 还受并行 commerce/LAN 未完成交接阻塞。下一步应先让并行线冻结并交接，再按 G17.1 实现 generation/CAS，之后进入 G18。

本报告不执行 staging/commit，不回滚、不删除任何其他会话产物。
