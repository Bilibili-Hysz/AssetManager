---
feature: mainline-audit-followup-2026-08-05
status: partial-delivered
scope: R1 follow-up, L1 lifecycle verification, D1 documentation calibration, M1 integrity/maintenance closure, S1 security history partial, A1-P0 path contract, bounded consistency closure
verification: non-e2e-2088-passed-4-skipped-1-warning; m1-targeted-167-passed; bounded-static-pass
---

# 主线审计续接报告 — 2026-08-05

## 1. 结论

本报告记录 2026-08-05 对多会话混合工作树的续接审计，不是整体发布完成声明。

R1 的 root/session ownership、restore admission、RuntimeData identity、数据库 teardown 和 backup validation 已通过 targeted 与非 E2E 回归。L1 LAN 生命周期竞态也已由现有实现和独立回归证据覆盖，本轮没有新增 LAN 代码修改。

D1 仅校准文档中已确认的服务清单、测试基线和 G3-9 状态；G6-1/G6-5/G6-6 仍保持 partial，Desktop 设置产品入口、quarantine 生命周期、真实崩溃恢复演练和 WebUI/E2E 发布门禁没有被本报告宣称完成。

## 2. 本轮确认的代码边界

- `LibraryScopedServices` 当前包含 session-bound `DatabaseIntegrityService`、`DatabaseMaintenanceService` 和 `LibraryExportService`。
- `LibrarySettingsAdapter` 是 Qt-free 的设置/恢复边界，不等于设置页控件、异步 worker 或窗口验收已经完成。
- `DatabaseMaintenanceService.stop()` 与 `DatabaseIntegrityService.stop()` 在 cleanup 未 drain 时保留 retryable close 状态。
- RuntimeData 的 `Shared`/`_orphaned` basename 冲突 fail-closed；带 identity marker 的非当前库数据不会被 orphan cleanup 搬移。
- LAN close/publication/SystemExit 竞态已有 generation、owner-thread cleanup、retry 和 session drain 证据。

## 3. 验证证据

使用仓库外 basetemp：

```text
python -m pytest D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests \\
  --ignore=D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\e2e \\
  -q -p no:cacheprovider \\
  --basetemp=C:\Users\86177\AppData\Local\Temp\assetsmanager-non-e2e-final-m1-20260805
```

结果：

```text
M1 补丁后最终非 E2E：2034 passed, 2 skipped, 1 warning
```

专项证据：

- LAN lifecycle：`40 passed`；
- architecture boundary：`76 passed`；
- Integrity/Maintenance/Adapter focused：`35 passed`（Integrity 14、Maintenance 15、Adapter 6）；MainWindow 调度反馈测试：`5 passed`；更广的 M1 targeted（含 Bootstrap、Runtime、LibraryService）为 `167 passed`；
- export/core identity 回归：`79 passed, 1 skipped, 1 warning`；
- Ruff、目标生产 Pyright、compileall、AST、JSON 和 `git diff --check` 通过。

全仓库 Pyright 当前仍有 `83 errors`，集中在其他混合 LAN、panel、widget 和 compatibility 域；目标生产文件本轮为 0 errors。

## 3A. M1（G6-5/G3-9）补丁后证据

- `DatabaseIntegrityService` 的 metadata/thumbnail prune commit 现在通过 `LibrarySession._publish_while_live()` 与 session close 共享线性化点；close 先取得该点时会 rollback，缩略图 baked 文件也延迟到 commit 成功后才删除。
- scheduled worker 在启动前预留 active-run，避免并发 direct `run()` 提前置位 `_run_done`；维护服务继续保持 single-flight、非法 WAL mode 同步拒绝和 retryable stop 边界。
- M1 targeted：`167 passed`；新增 4 个 close/active-run 竞态测试连续 3 次通过；checkpoint timeout restoration、closed-service、VACUUM unsupported 和 schedule feedback 均有回归覆盖。
- M1 相关生产文件目标 Pyright：`0 errors`；全量 Pyright 仍为 `83 errors`，集中在其他混合 LAN、panel、widget 与 compatibility 域。

M1 仍不是整体发布完成声明；设置页真实控件/异步反馈、VACUUM maintenance window、崩溃恢复演练、WebUI/E2E 与 Desktop 视觉门禁仍保持 partial 或保护域状态。

## 4. 仍未收口

- restore poison 仍为 process-local，未提供跨进程/跨重启 recovery journal；
- Windows path-level check 与 open/replace 之间仍有 handle-level TOCTOU residual；
- quarantine 的长期保留、回滚清理、用户可见管理和同进程 listing/restore 并发合同仍未完成；
- G6-5/G3-9/G6-6 仍有产品反馈、VACUUM 窗口、GUI 视觉验收、崩溃演练等 partial 项；S1 已补齐服务层历史 bind/effective-auth、三入口 canonical preflight，以及确认 helper/原子用户决策写回，但完整 GUI/生命周期验收仍未闭合；
- WebUI source/dist、WebUI/E2E 和 Desktop 视觉域属于保护范围，本报告不接手；
- 工作树仍是多会话混合状态，未形成可直接提交的单一主线边界。

## 5. 保护与提交边界

本轮未修改、回滚、暂存或提交 `webui/**`、`webui/test-results/**`，也没有清理历史 `tmp/`、`.pytest-*` 或 RuntimeData 测试产物。

当前报告只记录主线状态，不授权把当前工作树整体提交，也不改变后续 L1/D1/M1/S1 的分工顺序。

## 6. S1 SecurityPreflight 续接（2026-08-05）

本次 S1 只收口服务层历史姿态合同，不将其误写成完整 G6-6 产品完成：

- ack 版本改为精确匹配，future ack fail-closed；取消不再撤销既有确认。
- AppSettings 增加 last-successful bind/effective-auth 的严格读写和原子提交；save 失败可观察并恢复旧内存历史。
- Desktop、ShareManager、LanServer 默认入口统一从 `security_preflight_from_settings()` 构造 holder；成功完成真实 `auth_status()` 复核后才记录历史。
- 首次分享确认 helper 使用默认 No、原子写回和二次 preflight；独立设置对话框启动分支同样传递 preflight；普通设置保存失败时拒绝改变运行中服务状态。
- WebUI、GUI 确认对话框、确认字段用户写回、主题/DPI/焦点/截图证据仍属于未完成或保护域。

本轮专项证据：

```text
security_preflight unit: 21 passed
security_preflight integration: 12 passed
LAN tunnel failure/security: 15 passed
security confirmation helper: 3 passed
sharing settings dialog: 6 passed
Ruff + py_compile (S1 write set): passed
```

全仓库非 E2E 计数仍以 M1 之前记录的 `2034 passed, 2 skipped, 1 warning` 为基线；本轮没有重新将被保护的 WebUI/E2E 域纳入验证，也没有形成单一可提交工作树。

## 7. A1-P0 path key/subtree contract（2026-08-05）

S1 partial 收口后，本轮继续处理 A1 的 bounded preflight slice；没有进入 broad repository migration。

已交付：

- `AssetsManager/core/path_resolver.py` 增加 `path_key_separator()`、`escape_sql_like()`、`sql_like_descendant_pattern()` 和 `remap_path_subtree()`。
- `AssetsManager/repositories/metadata_repository.py` 的 cache invalidation、delete、path migration 使用统一 descendant pattern。
- `AssetsManager/repositories/tag_repository.py` 的 tree query、delete、path migration 使用同一 helper。
- `AssetsManager/core/database.py::migrate_path_metadata()` 与 repository migration 使用相同 descendant boundary 和 remap 语义。
- Windows 反斜杠、portable slash、`folder`/`folder-copy` 边界均有回归测试。

专项验证：

```text
tests/core/test_path_resolver.py + repository/services integration: 88 passed
tests/core/test_database_metadata.py: 10 passed
architecture path/repository boundary subset: 7 passed
Ruff + py_compile (A1-P0 write set): passed
```

仍未宣称 A1 broad migration 完成：RootIdentity 在所有 compatibility facade 的统一使用、schema owner 清单、ProjectData/TagStore/AssetIndex 全量 key 统一仍是后续 bounded slice；不应把本轮 98 项通过写成整个 repository/path 子系统已完成。


## 8. Continuation bounded consistency closure (2026-08-05)

本节是本报告在同一工作树上的后续续接，覆盖 2026-08-05 本会话新增的 bounded 修复与最终非 E2E 回归；不改变前文的 partial 状态，也不构成整体发布完成声明。

### 8.1 已实施的 bounded 修复

- `MetadataRepository.set_library_total_size()` 改为非破坏性 UPSERT：已有 `total_files`、`total_projects` 等统计字段不再因 `INSERT OR REPLACE` 被清零；兼容缺少 `updated_at` 的最小/旧 fixture。
- `db_migrations.migrate()` 与 `current_version()` 对高于 `CURRENT_SCHEMA_VERSION` 的记录抛出 `UnsupportedSchemaVersion`，拒绝旧程序继续写入未来 schema。
- `ProjectData.invalidate_size_cache()` 复用统一 `sql_like_descendant_pattern()`，避免 `folder` 误命中 `folder-copy`，并覆盖 Windows/portable path、`%`/`_` 转义。
- `AssetIndexService` 跳过 symlink/junction/reparse entries；`AssetIndexRepository` 的 upsert 更新 `parent_path`/`library_root`，删除使用统一 subtree boundary。
- 架构边界测试明确允许 repositories 使用 `core.path_resolver` 这一纯基础设施依赖，避免实现已经统一 path contract 后仍被旧测试规则误报。

### 8.2 验证证据

使用仓库外 basetemp，未运行 WebUI/E2E：

```text
python -B -m pytest -q -p no:cacheprovider \
  --basetemp=<external> \
  tests/core tests/unit tests/integration tests/desktop tests/lan

2075 passed, 3 skipped, 1 warning in 139.50s
```

平台相关 skip 为 Windows symlink/junction 权限不足；warning 为故意构造 duplicate ZIP member 的测试 warning。专项静态检查：

```text
Ruff: 通过
Pyright（本次 bounded 生产写域 5 个文件）: 0 errors
compileall: 通过
git diff --check: 通过
```

### 8.3 当前仍不收口的合同

- `MetadataService` 标量/批量接口仍需后续统一 file-key 规范化，不能把本轮 AssetIndex/ProjectData bounded 修复误写成全 compatibility facade 已统一。
- `ProjectData`/`TagStore` raw `db_conn` 的 root ownership 校验、历史 AssetIndex 污染行的严格 containment/search 过滤仍需后续 bounded contract。
- schema owner 仍分为核心 migration、AuthRepository、ShareRepository 三个域；真实旧 schema fixture、optional schema version manifest 和 migration failure/retry fixture 尚未统一。
- S1 的 GUI 真实截图、主题/DPI/键盘焦点/reduced-motion、跨重启确认 UX 与完整 LAN lifecycle/SystemExit 验收仍保持 partial。
- `webui/**`、`webui/test-results/**`、`tests/e2e/**` 未纳入本轮；工作树仍是多会话混合 dirty state，未形成可直接提交的单一主线边界。


## 9. Metadata batch key and compatibility ownership continuation (2026-08-05)

本节继续上一节的 A1 bounded readiness，不进入 broad migration，也不改变 WebUI/E2E 保护边界。

### 9.1 已实施

- `MetadataService.get_cached_stats()`、`batch_get_cached_file_counts()`、`batch_set_cached_file_counts()` 现在统一使用与 scalar API 相同的 `Path.resolve()` canonical key 语义。
- batch get 返回调用者传入的 key，避免 LAN files route 因内部 canonicalization 丢失缓存命中；同一 canonical row 的 alias、`..`、relative 查询均可命中。
- batch set 会将 alias 合并为单一 canonical `file_meta.file_path`，不会写出重复 DB key。
- `DatabaseManager.validate_connection_owner()` 为已注册 managed connection 提供 root ownership 校验；root mismatch fail-closed。
- `ProjectData` 与 `TagStore` 的显式 managed `db_conn` 现在拒绝绑定到其他 library root；同 root managed connection 和未注册的 raw/in-memory compatibility connection 仍保持兼容。

### 9.2 验证

```text
batch/ownership专项：115 passed
主线非 E2E：2084 passed, 3 skipped, 1 warning
Ruff：通过
目标生产文件 Pyright：0 errors
compileall：通过
git diff --check：通过
```

### 9.3 尚未宣称完成

- 未注册 raw connection 仍按兼容策略保留，尚未强制要求显式 ownership token；若未来要完全 fail-closed，需要单独的 API 迁移和调用方收敛。
- ProjectData/TagStore 的 file-key helper 仍与 MetadataService 保持语义一致但尚未抽成唯一公共 helper。
- schema owner/旧 fixture、AssetIndex 历史污染 containment、S1 GUI/跨重启/LAN 完整生命周期，以及 WebUI/E2E 仍未收口。


## 10. Indexed search containment and schema preflight continuation (2026-08-05)

### 10.1 已实施

- `SearchService.search_by_name_indexed()` 现在对 assets 历史行执行 physical canonical containment：
  - 只返回 `kind == "file"`；
  - 库外绝对路径、`..` 逃逸、跨盘路径、库根自身和库内 symlink 指向库外的记录均 fail-closed 过滤；
  - 正常结果、相对路径格式和性能事件语义保持不变。
- `db_migrations.preflight_recorded_version()` 增加只读 future-version 预检。
- `DatabaseManager.open_library()` 在执行 `_SCHEMA` 之前先进行 future-version 检查，避免旧程序先执行 WAL/CREATE TABLE 等 DDL 后才拒绝未来数据库。

### 10.2 验证

```text
indexed/schema 专项：50 passed, 2 skipped
主线非 E2E：2088 passed, 4 skipped, 1 warning
Ruff：通过
目标生产文件 Pyright：0 errors
compileall：通过
git diff --check：通过
```

### 10.3 新确认但尚未处理的 P1

raw connection audit 确认 `TagService`、`SearchService`、`ProjectService`、`ThumbnailService` 的显式 `db_conn` 仍可能绕过 root ownership；`InfoController` 还存在忽略 requested root 的 provider：

```python
lambda _root: db_conn
```

这些路径不能被当前 ProjectData/TagStore managed connection 校验覆盖，下一步应先建立统一 root-bound connection resolver，再按生产调用链逐步迁移。

schema owner 仍存在：稀疏/错名 migration history、空 baseline、directory_cache 双 owner、Auth/Share 未版本化、migration DDL/记录非原子和真实旧库 fixture 缺失。本轮只处理 future-version preflight，没有扩大为 schema owner broad migration。

## 11. Application service and InfoController connection ownership continuation (2026-08-05)

### 11.1 已实施

- `TagService`、`MetadataService`、`SearchService`、`ThumbnailService` 对 managed connection 的显式连接/provider 入口统一调用 `DatabaseManager.validate_connection_owner()`。
- `ProjectService` 仅在 `list_projects()`、`get_home()`、`get_project_detail()` 三个 public DB operation 建立 root-bound connection 边界；未顺手重构原有 metadata、tag、filesystem/cache 业务逻辑。
- 保留显式 `db_conn` 优先于 provider 的既有语义。
- 保留 unmanaged/raw `sqlite3.Connection` 兼容；因此这不是“所有 raw connection 已默认拒绝”，而是 managed foreign-root fail-closed、unmanaged legacy 继续可用。
- `SearchService` 的 ownership mismatch 不再被普通 provider failure 降级路径吞掉；普通 provider/SQLite failure 的原有降级语义保持。
- `ThumbnailService` 的 cache metadata 与 blur-tag 两条 DB 路径均覆盖 root 校验；普通 provider/SQLite failure 继续按原约定降级。
- `InfoController` 对非空 `db_conn` 在构造时执行 root ownership 校验；managed foreign-root fail-closed，same-root 与 unmanaged raw 兼容。
- `InfoController(db_conn=None)` 不再创建 `PluginMetadataRepository(None)`；filesystem-only/plugin-empty 查询保持稳定，且不改变连接关闭责任。

### 11.2 验证证据

```text
application service 专项：89 passed, 2 skipped
InfoController/相关 desktop 专项：165 passed
主线非 E2E：2109 passed, 4 skipped, 1 warning
Ruff：All checks passed
目标 production/test Pyright：0 errors, 0 warnings, 0 informations
compileall：通过
git diff --check：通过
```

其中 4 个 skip 均为当前 Windows 环境无 symlink/directory-symlink 权限；1 个 warning 是既有 zipfile duplicate-name 测试警告，不影响退出码。

### 11.3 当前边界，仍不得宣称完全收口

- unmanaged raw connection compatibility 仍是可达的 legacy/test escape hatch；尚未迁移为显式 opt-in API。
- `InfoController` 的位置参数 `InfoController(library_root, db_conn)` 保留；`PluginMetadataRepository` 仍是 raw connection repository，尚未改造成 session-owned repository。
- LAN legacy fallback、部分 legacy controller/adapter 路径仍需后续单独审查。
- schema/migration P1 仍未处理：空库 `migrate()` 可记录 v5 但缺 core tables、migration history 只信任 `MAX(version)`、`directory_cache` 双 owner、Auth/Share 表未版本化、migration 内部 commit 破坏事务原子性、v1 fixture 非冻结真实旧库。
- 本轮未运行 `tests/e2e/**`，未触碰 `webui/**` 的既有 14 条修改；未执行 reset/checkout/clean，未暂存、未提交。

## 12. Migration history and transaction atomicity continuation (2026-08-05)

### 12.1 已实施

- `schema_migrations` history 现在统一执行 fail-closed 校验：
  - 版本必须从 1 连续到当前记录的最大版本；
  - migration name 必须与代码中的 `MIGRATIONS` 定义一致；
  - 非整数、非正值、重复、稀疏和错名记录拒绝；
  - future version 继续抛出 `UnsupportedSchemaVersion`。
- `preflight_recorded_version()` 复用同一 history 校验，但保持只读，不创建 migration 表、不执行 DDL。
- 移除 v5 migration 内部 `commit()`。
- `migrate()` 改用 savepoint：
  - fresh connection 成功时保持现有提交语义；
  - 外层已有事务时不提交调用方数据；
  - migration 失败时回滚 migration history 与本轮 DDL。
- 新增 malformed/sparse/misnamed/fake-latest、outer rollback 和 injected failure 回归测试。

### 12.2 验证证据

```text
migration 专项：17 passed
core 全套：172 passed
主线非 E2E：2116 passed, 4 skipped, 1 warning
Ruff：All checks passed
目标 Pyright：0 errors, 0 warnings, 0 informations
compileall：通过
git diff --check：通过
```

### 12.3 仍未收口的 schema owner 合同

本轮只处理 migration history 状态可信度和事务边界，没有改变现有 schema owner 架构。以下 P1 仍然保留：

- 空库直接 `migrate()` 可返回 v5 但缺少 core tables；
- `directory_cache` 同时由 baseline `_SCHEMA` 与 v5 migration 声明；
- `users`、`invite_codes`、`share_links` 仍由 Auth/Share repository 惰性建表；
- v1 upgrade 测试仍不是独立冻结的真实历史 fixture。

因此当前可以宣称 migration history 与事务边界已完成 bounded hardening，但不能宣称完整应用 schema owner 已统一。

## 13. Schema owner / baseline contract continuation (2026-08-05)

### 13.1 已实施

- 从 `core.database._SCHEMA` 移除 `directory_cache` 的重复 baseline `CREATE TABLE`。
- 保留 v5 migration `version=5/name='directory_cache'`，使 `directory_cache` 由 v5 作为唯一正式 owner 创建。
- `migrate()` 新增 baseline 完整性检查，要求以下 core tables 已由 `_SCHEMA` 准备：
  - `file_tags`
  - `file_meta`
  - `thumbnail_cache`
  - `library_stats`
- 纯空库直接调用 `migrate()` 现在 fail-closed，并通过 savepoint 回滚 `schema_migrations` 创建，不再返回虚假的 v5。
- 调整直接调用 migration 的 directory-cache / asset-service 测试，使测试显式准备 `_SCHEMA` baseline，固定新的调用合同。

### 13.2 验证证据

```text
schema/core 专项：174 passed
asset-service follow-up：26 passed
主线非 E2E：2118 passed, 4 skipped, 1 warning
Ruff：All checks passed
目标 Pyright：0 errors, 0 warnings, 0 informations
compileall：通过
git diff --check：通过
```

### 13.3 仍未收口

- Auth/Share 的 `users`、`invite_codes`、`share_links` 仍由 repository 初始化，尚未纳入统一 migration。
- 当前 v1 仍是 `_SCHEMA` baseline 记录，不是独立冻结的真实历史 fixture。
- 已有 v5 数据库若历史记录合法但实际缺少某个版本表，尚未建立完整 schema-object replay/integrity manifest。
- 本轮仍不等于完整应用 schema owner 全部统一。

## 14. Frozen v1 baseline fixture continuation (2026-08-05)

### 14.1 已实施

- 新增独立静态 fixture：`tests/fixtures/db/v1_schema.sql`。
- fixture 标注来源为当前历史基线 commit `51e50203eebf582dcf480ed5b378e0f7156e6611`，不再从当前 `database._SCHEMA` 动态生成。
- fixture 忠实保留历史 v1 baseline 的 core tables，包括历史上已经存在的 `directory_cache`。
- fixture 不包含 v2/v3/v4 的增量表：
  - `assets`
  - `tag_metadata`
  - `plugin_metadata`
- v1->v5 测试改为加载静态 fixture，并验证升级后增量表、migration history 和 v5 directory-cache 合同。

### 14.2 验证证据

```text
v1 fixture/migration 专项：19 passed
core 全套：174 passed
主线非 E2E：2118 passed, 4 skipped, 1 warning
Ruff：All checks passed
目标 Pyright：0 errors, 0 warnings, 0 informations
compileall：通过
git diff --check：通过
```

### 14.3 Auth/Share versioning 评估结论

本轮没有直接把 Auth/Share 表硬塞进当前 v5：

- `users`、`invite_codes`、`share_links` 目前由 repository 初始化；
- 若直接修改现有 v5，会破坏已存在数据库的 version/name 合同；
- 正确方向应是新增后续 migration（例如 v6），同时先抽离 schema owner，并改造 repository `init_tables()`/`init_table()` 的兼容职责；
- 在没有冻结 v6 发布合同和迁移真实旧库矩阵前，不进行半迁移。

因此 Auth/Share 版本化仍保持为下一阶段 P1，不宣称已完成。

## 15. Auth/Share v6 migration continuation (2026-08-05)

### 15.1 已实施

- 新增共享 schema 定义：`AssetsManager/core/schema_defs.py`。
- `CURRENT_SCHEMA_VERSION` 从 5 升至 6。
- 新增 migration：

```text
version=6
name=auth_share_schema
```

- v6 正式创建：
  - `users`
  - `invite_codes`
  - `share_links`
- Auth/Share repository 保留原有公开 schema 常量名和 `init_tables()`/`init_table()`，但其 SQL 改为引用共享定义；这些入口现在明确属于 raw/legacy compatibility ensure，正式版本 owner 是 migration v6。
- 更新 architecture boundary allowlist，使 repository 依赖 `core.schema_defs` 合法化。
- v1 fixture、v5 数据库升级和新数据库 open_library 路径均验证到 v6。

### 15.2 验证证据

```text
Auth/Share + migration 专项：150 passed
主线非 E2E：2118 passed, 4 skipped, 1 warning
Ruff：All checks passed
目标 production/test Pyright：0 errors, 0 warnings, 0 informations
compileall：通过
git diff --check：通过
```

完整 Pyright 扫描中仍有两个此前存在、与本轮 v6 无关的测试夹具类型问题，未越权修改：

- `tests/integration/test_repositories.py` 的 `_NullNotesConnection`；
- `tests/integration/test_share_service.py` 的 `SimpleNamespace` session fixture。

### 15.3 仍需保留的兼容边界

- repository `init_tables()`/`init_table()` 仍可在未迁移的 raw connection 上建表，这是明确的兼容 fallback，不是默认生产 owner。
- 真实 v5 数据库升级到 v6 已覆盖，但仍需后续建立 Auth/Share schema-object manifest 和 repository compatibility deprecation 计划。
- 本轮未改变 LAN legacy fallback，也未运行 `tests/e2e/**`。
