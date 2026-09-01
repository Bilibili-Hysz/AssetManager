# WebUI 迁移分批提交计划（Dry-run）

- 日期：2026-08-08
- 工作区：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
- 参考源：`D:\~Vibe-Coding\Projects\AssetsManager_New_WebUI`（只读）
- 当前 HEAD：`fbf3403 Enforce schema object integrity for v6`
- 计划生成时状态：467 个变更项；187 个 tracked modified；280 个 untracked；0 个 staged
- 本轮复核状态（2026-08-09）：486 个变更项；194 个 tracked modified；292 个 untracked；0 个 staged；无删除/重命名；`git diff --cached` 为空。上面的 467/280 与 479/187/292 均为历史生成快照。
- 本文件只记录归属和提交顺序，不执行 `git add`、stage 或 commit。

## 1. 永不自动纳入提交的内容

以下内容必须在任何批次外单独保留或确认：

```text
tmp/node-repl-test.txt
tmp/server.diff
webui/test-results/.last-run.json
tmp/pytest-*/
tmp/*-test*/
webui/test-results/
webui/playwright-report/
coverage/
dist/
build/
*.log
```

当前工作区的临时文件不得通过 `git clean` 处理；本计划不删除它们。

### 1.1 归属审查补充

为覆盖首会话和第二会话共同留下的 WebUI dirty/untracked 文件，提交时按以下完整规则归属，不能只按下面的代表文件列表机械执行：

- **Batch 6** 的完整范围是 `webui/src/**` 中除 Batch 7 规则命中的 Commerce/Seller 文件之外的 shared、legacy、Gallery、旧 LAN API contract、App integration 和对应测试；这包括 `components/gallery/*`、`pages/Gallery*.tsx`、`pages/Browse*.tsx`、`pages/Detail*.tsx`、`api/*`、`stores/*`、`types/*` 等首会话迁移文件。
- **Batch 7** 的完整范围是 storefront/seller Commerce API、hooks、`components/storefront/*`、`pages/Storefront*.tsx`、`pages/LegacyStorefront*.tsx`、`pages/Seller*.tsx` 及其测试和 Mock/Shell E2E。
- `webui/playwright.config.ts` 只提交一次；若与 Batch 7 同批处理，Batch 8 不得重复 stage。
- `ruff.toml` 是 Batch 8 的 CI/tooling 配置，必须和 `.github/workflows/ci.yml` 的 lint 门禁一起审查；不能因它不是 WebUI 文件而遗漏。
- `DeepSeek Docs/**`、`tmp/**`、`webui/test-results/**` 以及不属于上述迁移域的既有 AssetsManager/tests 改动，不得被 WebUI 批次的宽泛命令带入；它们必须单独保留或在独立功能域中处理。

## 2. 推荐提交顺序

### Batch 1：Schema / migrations

基础文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\db_migrations.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\schema_defs.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\core\test_db_migrations.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\core\test_delivery_attempt_migration.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\core\test_commerce_migration_matrix.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\core\test_reconciliation_queue_migration.py
```

注意：`db_migrations.py` 同时包含 Commerce、delivery-attempt 和 G17 migration，必须使用 hunk staging。

验证：

```text
python -m pytest -q -p no:cacheprovider tests/core/test_db_migrations.py tests/core/test_delivery_attempt_migration.py tests/core/test_commerce_migration_matrix.py tests/core/test_reconciliation_queue_migration.py
```

### Batch 2：Restore / integrity / maintenance

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\database_integrity_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\database_maintenance_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\library_export_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\library_settings_adapter.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_core_store_session_binding.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_database_integrity_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_database_maintenance_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_library_export_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_library_settings_adapter.py
```

`database.py`、`library_service.py`、`file_operation_service.py` 如同时包含其他主线改动，只能按 hunk 纳入。

### Batch 3：G17 reconciliation

实现：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\asset_index_reconciliation_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue_migration.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\reconciliation_queue_store.py
```

测试：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_asset_index_reconciliation_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_queue.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_queue_migration.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_queue_sqlite_store.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_reconciliation_supervisor_conflicts.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_bootstrap_order.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_cutover_lock_order.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_library_owner_handoff.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_cross_process_wakeup.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_external_lock.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_fault_injection.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_heartbeat_inflight.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_process_matrix.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_process_termination.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_process_termination_subprocess.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_queue_sqlite_runtime.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_runtime_cutover.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\integration\test_reconciliation_runtime_lifecycle.py
```

G17 相关 tracked 文件（`bootstrap.py`、`runtime.py`、`database.py`、`db_migrations.py` 等）必须按 hunk staging。

### Batch 4：Commerce backend

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_authorization.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_buyer_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\order_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\quota_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\free_download_quota_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\seller_auth_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\seller_profile_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\storefront_analytics_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\favorite_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\shop_repository.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\shop_buyer_repository.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\order_repository.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\quota_repository.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\free_download_quota_repository.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\seller_profile_repository.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\storefront_analytics_repository.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\favorite_repository.py
```

Commerce unit/integration tests应随对应实现同批或紧随其后。

### Batch 5：LAN Commerce routes / auth

新增 Commerce 路由：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\commerce_policy.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\favorites.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\gallery.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\quota.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\seller_auth.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\seller_profile.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\shop.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\storefront_analytics.py
```

跨域入口：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\api.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\server.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\principal.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\__init__.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\_helpers.py
```

`server.py` 至少拆成：公共页面、Commerce API、旧 LAN auth/下载兼容三组 hunk。

### Batch 6：WebUI shared / integration

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\App.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\App.test.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\client.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\client.test.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\types\api.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\stores\AuthContext.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\stores\RealtimeContext.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\layout\AppLayout.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\layout\AppHeader.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\layout\Header.css
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\layout\Workspace.css
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\ui\CommandPalette.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\ui\CommandPalette.css
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\stores\SellerAuthContext.tsx
```

`App.tsx`、`client.ts`、`types/api.ts`、`AuthContext.tsx` 必须单独审查 integration hunk。

### Batch 7：WebUI Storefront / Seller

API/hooks：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\favorites.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\gallery.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks\useCommerce.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks\useFavorites.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks\useQuota.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\storefront\*
```

页面、测试和 E2E：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\Storefront*.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\LegacyStorefront*.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\Seller*.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-buyer.spec.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\seller.spec.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\webui-shell.spec.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-real-backend.spec.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\playwright.config.ts
```

- `commerce-real-backend.spec.ts` 是可选真实后端验收，不进入默认 CI；只有在设置 `REAL_COMMERCE_BASE_URL`、`REAL_COMMERCE_SELLER_PASSWORD` 并准备隔离后端数据后才运行。

本轮新增的非图片资源修复和测试也属于此批：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\StorefrontMediaFallback.test.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\StorefrontProductPage.test.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\StorefrontProductsPage.test.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\StorefrontDeliveryPage.test.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\StorefrontWishlistPage.test.tsx
```

### Batch 8：CI / docs

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\.github\workflows\ci.yml
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\ruff.toml
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\README.md
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\docs\session-handoff-2026-08-08-second-to-first.md
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\docs\compose\reports\webui-migration-batch-commit-plan-2026-08-08.md
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\docs\compose\reports\webui-migration-ownership-manifest-2026-08-08.md
```

Batch 8 主清单为上述 6 个 primary files。`webui/playwright.config.ts` 不重复列入 Batch 8 主清单，改由下面的 Cross-domain hunk ledger 处理；最终只能进入一次提交。

### Cross-domain — `webui/playwright.config.ts` hunk ledger（stage once）

```text
lines 1-17  : Batch 7 E2E/local Chromium portability hunk
lines 19-23 : Batch 8 CI webServer/preview integration hunk
```

同一 tracked 文件不得在 Batch 7、Batch 8 中重复 `git add`。若需要拆分提交，必须人工使用 `git add -p -- webui/playwright.config.ts`；更安全的默认方案是将两个 hunk 作为一个 cross-domain commit 一次处理。

`README.md` 也是 mixed-domain tracked file；Batch 8 只 stage CI/tooling/verification hunks。Commerce/Seller/LAN 说明必须用 `git add -p` 单独判断归属，禁止整文件 stage。

## 3. 每批 stage 前固定检查

```powershell
git status --short --untracked-files=all
git diff --check
git diff --name-only
git ls-files --others --exclude-standard
```

跨域 tracked 文件使用：

```powershell
git add -p -- <file>
```

禁止：

```powershell
git add .
git add AssetsManager
git add webui
git clean
git reset
```

## 4. 验证顺序

1. Batch 1：migration/schema focused tests；
2. Batch 2：restore/integrity focused tests；
3. Batch 3：G17 focused and process tests；
4. Batch 4/5：Commerce + LAN tests；
5. Batch 6/7：WebUI unit/typecheck/build + Playwright Mock/Shell；
6. 如具备隔离真实后端，额外运行 `webui/e2e/commerce-real-backend.spec.ts`；
7. 全量 Python +静态门禁；
8. 最后才进行 release/owner/reviewer/evidence sign-off。

当前本文件仅为提交计划，未执行任何 staging 或 commit。

## 5. 2026-08-08 Batch 1 hunk-level dry run (no staging)

本节是对 `AssetsManager/core/db_migrations.py` 的实际当前 diff 进行的只读预演；本轮没有执行 `git add`、`git reset`、`git clean` 或 commit。

### 5.1 实际 hunk 计数与边界

- `git diff --unified=0 -- AssetsManager/core/db_migrations.py`：15 个文本 hunk；
- `git diff --unified=8`：6 个展示 hunk；
- 逻辑上可归并为：迁移/校验基础设施、v7–v22 migration 实现、MIGRATIONS 注册表、最终 runner 校验。
- 因此不能把“8 个 hunk”理解为 8 个可安全独立提交单元；其中新增 migration 实现是一个 309 行连续大 hunk。

### 5.2 15 个文本 hunk 的归属预演

| hunk | 当前新增/删除内容 | 逻辑归属 | 预演结论 |
|---:|---|---|---|
| 1 | `Any` / `cast` 类型导入 | shared migration spine | 与 schema/migration 基础一起处理 |
| 2–7 | schema 定义导入、校验函数兼容导出、`CURRENT_SCHEMA_VERSION=22` | shared schema/migration spine | 不宜按 Commerce/G17 拆开；版本上限和导入集合共同定义 runner |
| 8 | 删除 `db_migrations.py` 内重复 `InvalidSchemaError` | shared schema validation | Batch 1 schema spine |
| 9 | `_reconciliation_tasks_contract()` | G17 v14–v17 compatibility | 依赖 shared contract；若单独放 Batch 3，必须连同依赖 hunk 一起处理 |
| 10 | 删除本地 `validate_schema_object(s)`，改用 `schema_defs` | shared schema validation | Batch 1 schema spine |
| 11 | v7–v22 函数集中新增（见 5.3） | mixed | 不能直接整 hunk 归入某一个功能域 |
| 12 | 注册 migration 7–22 | mixed/shared runner | 必须保持版本连续，不能只 stage Commerce 版本 |
| 13 | 跳过高于当前版本的 migration | shared runner | 与版本注册表同批处理 |
| 14 | `required_objects` 扩展及 v14–v16 legacy contract 分支 | mixed/shared runner | G17 兼容分支与 Commerce 对象清单逻辑交错 |
| 15 | v14–v16 的无 `lease_token` contract 最终校验 | G17 compatibility | 依赖 hunk 9 与 v14/v15/v17 schema |

### 5.3 hunk 11 的可定位逻辑区间（当前文件新行）

| 当前新行 | migration | 归属预演 |
|---:|---|---|
| 411–461 | v7 `library_favorites`、v8 Commerce、v9 `asset_index_state` | v7/v8 为 Schema/Commerce；v9 历史上由 G17.1 引入 |
| 462–485 | v14 `reconciliation_tasks`、v15 `reconciliation_queue_state` | G17 schema |
| 487–545 | v10 quota、v11 receipts、v12 seller profile、v13 analytics | Schema/Commerce |
| 546–598 | v16 cart/wishlist | Schema/Commerce |
| 601–655 | v19 checkout generation | Schema/Commerce |
| 658–666 | v21 checkout fingerprint | Schema/Commerce |
| 669–679 | v22 delivery attempts | Schema/Commerce/delivery |
| 682–688 | v20 receipt recovery | Schema/Commerce |
| 691–706 | v18 buyer owner | Schema/Commerce |
| 708–718 | v17 reconciliation lease token | G17 schema |

### 5.4 安全分批结论

`schema_migrations` 历史必须从 1 连续到当前版本；如果 Batch 1 只 stage v7–v13、v16、v18–v22，而把 v9/v14/v15/v17 的注册项留到 Batch 3，工作区会出现缺失版本，后续 `_validate_history()` 会拒绝非连续 history。故当前推荐：

1. 将 `AssetsManager/core/schema_defs.py` 与 `AssetsManager/core/db_migrations.py` 视为一个 **Schema migration spine**，在 Batch 1 一次性纳入完整的 v1–v22 迁移注册、contract 与 runner 校验；不要把 registry hunk 拆成不连续版本。
2. Batch 1 继续纳入四个 core migration 测试文件；当前定向验证为 `68 passed`。
3. Batch 3 只纳入 G17 的 application/runtime/store/queue 文件；除非另立“Schema spine prerequisite”提交，不要再次触碰 `db_migrations.py` 的版本注册表。
4. 如果 owner 仍要求按历史会话把 v9/v14/v15/v17 归入 Batch 3，则先创建一个独立的 `Schema spine` 前置批次，保证每个中间 commit 都有连续 migration history；不得使用普通 `git add -p` 直接把一个 309 行 hunk 粗暴拆成不可运行的版本集合。

### 5.5 当前高优先级测试缺口（只记录，不在本轮扩大 scope）

- `test_v14_creates_and_validates_reconciliation_tasks()` 当前默认迁移到 v22，不能证明 v14 边界；
- v15 缺少独立正向边界测试；
- v22 当前只检查列集合，尚未正式覆盖 compatible/incompatible pre-existing table、FK、CHECK、唯一约束、索引、回滚和幂等；
- v18 “without backfill” 测试尚未插入迁移前订单，名称与证据不完全一致。

这些属于后续 Batch 1 migration test hardening，不改变本轮 0 staged 结论。

### 5.6 本轮最小测试修复（已完成，未改变生产代码）

针对 5.5 的高优先级误覆盖，已在未 stage 的工作区补齐最小测试证据：

- `tests/core/test_reconciliation_queue_migration.py`：将 v14 正向测试固定到 `CURRENT_SCHEMA_VERSION=14`，明确确认 v14 不含 `lease_token`；新增 v15 正向边界测试；
- `tests/core/test_delivery_attempt_migration.py`：新增 v22 compatible pre-existing table 路径与 incompatible table 回滚路径；
- 定向组合当前结果：`71 passed`；
- 目标测试文件 `ruff check`：通过；
- 生产实现文件未因本轮测试修复而改写；仍保持 `0 staged`、未 commit。

剩余的 v18 legacy-schema 数据保留、v13/v16/v20/v21/v22 完整 contract 行为测试仍列为后续 hardening，不应在后续提交时被误报为已完全覆盖。

## 6. 2026-08-08 legacy-boundary migration hardening (minimal fix)

本轮深度复核发现并修复了一个真实的 schema boundary 问题：旧版 v8/v17 数据库中的 `shop_orders` 可能尚未有 `buyer_owner_type` / `buyer_owner_key`，而 runner 在中间目标版本使用当前 v22 contract 做最终校验，会在 v18 migration 尚未执行前错误拒绝合法旧表；购物车 v16/v19 与 reconciliation v14–v16 也存在同类“当前形状/边界形状”并存场景。

最小修复位于：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\db_migrations.py
```

修复内容：

- 新增按 migration boundary 生成 contract 的校验路径；
- 校验时优先接受当前 canonical shape，若当前 shape 尚未在该 boundary 生效，则回退到该版本的 legacy contract；
- v8 Commerce preflight、v16 cart/wishlist、v19 checkout-generation、runner 最终 required-object 校验均使用该兼容路径；
- 不改变 migration 版本号、历史记录格式或已有数据迁移顺序。

新增回归证据：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\core\test_commerce_migration_matrix.py
```

覆盖：旧 v8 `shop_orders` → v17（owner 字段尚未升级）→ v22（v18 正式补列）。

验证结果：

```text
Migration/schema 定向：72 passed
Ruff（目标 migration/test 文件）：通过
Pyright（目标 migration/test 文件）：0 errors, 0 warnings, 0 informations
```

该修复已完成但仍保持 `0 staged`、未 commit；尚未宣称完整项目 release-ready。

### 6.1 全量 Python 回归（修复后）

```text
2716 passed, 7 skipped, 1 warning
```

该结果覆盖了 legacy-boundary 修复后的完整 Python 测试集；7 个 skip 均为当前 Windows symlink/spawn 能力边界，未新增失败。

### 6.2 v8 future-index compatibility补充

在 legacy regression 中又复现了一个相邻问题：旧 `shop_orders` 缺少 owner 字段时，v8 当前 Commerce DDL 若直接执行 owner index 会报 `no such column: buyer_owner_type`。已在同一最小修复中增加 deferred-index 判断：只有目标列已经存在时才创建该 future index，后续 v18 migration 负责正式创建 owner index；同理保护 v16 旧 checkout index 的 future generation 列。

修复后再次验证：

```text
Migration/schema 定向：72 passed
Python 全量：2716 passed, 7 skipped, 1 warning
Ruff：通过
Pyright（目标 migration/test 文件）：0 errors, 0 warnings, 0 informations
```

## 7. 2026-08-08 migration contract behavior hardening

继续补齐 Batch 1 的行为性回归：

- v13 storefront analytics：负计数、visitor hash 长度等 CHECK；
- v20 receipt recovery：有效期顺序与 order 外键；
- v22 delivery attempts：完整 shared contract、关键索引与非法 hash/state 拒绝；
- v18 legacy owner upgrade：插入真实旧订单，验证 v18/v22 不回填 owner 字段；
- 保持 fresh target 1–22 与 v1 fixture target 1–22 全部可迁移。

当前验证：

```text
Migration/schema 定向：74 passed
Python 全量：2718 passed, 7 skipped, 1 warning
Ruff：通过
Pyright（目标 migration/test 文件）：0 errors, 0 warnings, 0 informations
```

新增测试仍未 stage；后续提交时必须与 `db_migrations.py` / `schema_defs.py` 的 Schema spine 一起按 Batch 1 处理。

## 8. 2026-08-08 cross-domain tracked hunk audit — bootstrap/runtime

已完成对以下 tracked 文件的只读归属审查，未 stage/commit：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\bootstrap.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\runtime.py
```

结论：

- `bootstrap.py:324–365`、`394–466`、`518–519`、`571–585` 主要是 G17 runtime/ownership/reconciliation；
- `bootstrap.py:486–494` 同时含 Batch 2 integrity/maintenance/export wiring；
- `bootstrap.py:407–432` 是 G17 ownership 与 restore generation/token 的交叉块；
- `bootstrap.py:529–562` 同时包含 session-bound service、Favorite/Gallery/LAN wiring 与 G17 provider/queue 注入；
- `runtime.py:51–117` 是 lifecycle adapter、closing 状态和 runtime cleanup 边界，应与 G17 单独复核；
- `bootstrap.py` 与 `runtime.py` 均不得整文件 stage。

最危险的人工 staging 区域：

1. `bootstrap.py:407–520`；
2. `bootstrap.py:352–387` 与 `564–585`；
3. `bootstrap.py:529–562` 联合 `runtime.py:51–117`。

上述审查不改变代码内容，只补充后续手工 stage 的归属证据。

## 9. 2026-08-08 cross-domain tracked hunk audit — database/library/file operations

继续完成三类共享 tracked 文件的归属预演：

### `AssetsManager/core/database.py`

主要混合块：

- `_WriteGate` reader/writer admission、managed connection owner、close safety：G17/runtime ownership；
- `DatabaseManager.open_library()`、identity marker、preflight/migrate：Schema spine + runtime/G17 交叉依赖；
- RuntimeData legacy identity/orphan quarantine：Batch 2 restore/integrity/maintenance；
- `migrate_path_metadata()`：Batch 2/file restore 与 session transaction boundary；
- 不能按整文件 staging；至少拆出 managed-connection/G17、restore/orphan、path metadata 三组逻辑。

### `AssetsManager/application/library_service.py`

- root identity、cross-process lock、open/close/teardown、generation/ownership：G17 与 Batch 2 restore 交叉；
- restore reservation、rollback/poison/admission、listener teardown：Batch 2 Restore/integrity；
- session/context/cache alias compatibility：既有 runtime wiring；
- 该文件包含大段连续新增，不能使用整文件或宽泛目录 staging。

### `AssetsManager/application/file_operation_service.py`

- `FileOperationWarning`、degraded/partial diagnostics：主线文件操作/observability；
- reconciliation queue、asset-index refresh、revision conflict：G17；
- savepoint、projection cleanup、favorites/tags/cache：Batch 2/文件操作恢复；
- `FileOperationResult` 返回结构与 refresh telemetry 属于跨功能 API，必须单独检查调用方兼容性。

建议人工 staging 顺序：

1. 先 stage/验证 Schema migration spine；
2. 再拆 Batch 2 restore/integrity/file-operation hunk；
3. 再拆 G17 queue/ownership/reconciliation hunk；
4. 最后复核跨域调用方和全量 Python 回归；
5. 禁止对上述三文件执行整文件 `git add`。

## 10. Cross-domain hunk staging map (dry run, no staging)

以下是当前 `git diff --unified=0` 的逻辑分组，不是直接可执行的宽泛命令：

### `AssetsManager/core/database.py`

| 逻辑区间 | 归属 | staging 规则 |
|---|---|---|
| imports、RootIdentity、migration preflight wiring | Schema/G17 shared spine | 与 Schema/managed connection 一起审查 |
| `_ConnectionWriteState`、`_WriteGate.current_thread_is_reader` | G17 connection ownership | 单独 hunk |
| `_identity()`、identity marker、legacy reserved-dir guard | Batch 2 + G17 ownership | 不与 Commerce/WebUI 混入 |
| `DatabaseManager.open_library()` | mixed：Schema migration + G17 owner + restore admission | 必须手工拆逻辑块，不能整 hunk 粗放纳入 |
| `require_managed_connection_owner()`、`validate_connection_owner()`、close safety | G17/runtime | 与 G17 runtime wiring 一起验证 |
| orphan quarantine / `_orphaned` cleanup | Batch 2 restore/integrity/maintenance | 单独 stage |
| `migrate_path_metadata()` transaction/path projection | Batch 2 file restore + file operation | 与 `file_operation_service.py` 对照 stage |

### `AssetsManager/application/library_service.py`

| 逻辑区间 | 归属 | staging 规则 |
|---|---|---|
| `_RootOwnership`、canonical root maps、root identity/lock | G17 + restore ownership | 单独复核 lock/owner contract |
| listener teardown、closing/closed progress | Batch 2 restore + runtime lifecycle | 不直接归 G17 |
| `open_library()` / generation claim / admission | G17 + Batch 2 restore | 混合大块，按函数内逻辑手工拆分 |
| restore reservation、rollback/poison、reopen admission | Batch 2 Restore/integrity | 与 restore tests 配套 |
| cache/session alias compatibility | existing runtime wiring | 不带入 WebUI batch |

### `AssetsManager/application/file_operation_service.py`

| 逻辑区间 | 归属 | staging 规则 |
|---|---|---|
| `FileOperationWarning`、degraded/partial result、refresh diagnostics | file-operation/mainline observability | 与调用方返回契约一起审查 |
| reconciliation queue injection、revision conflict、index refresh result API | G17 | 与 queue/reconciliation tests 配套 |
| savepoint、projection cleanup、favorites/tags/cache | Batch 2/file restore | 单独 stage，避免带入 G17 全块 |
| `FileOperationResult` 所有调用点返回 warnings | cross-domain API | 需与所有调用方合并后再提交 |

推荐 order：Schema spine → Batch 2 restore/integrity/file operations → G17 runtime/queue → LAN/Commerce → WebUI。当前仍不执行 staging。

## 11. Batch dependency graph

根据当前 imports 与调用边界，Batch 2/3 不能简单按文件列表独立提交：

```text
Batch 1 Schema migration spine
        │
        ▼
Core ownership foundation
(database.py managed connection/db_write_lock/RootIdentity slices)
        │
        ├── Batch 2 restore/integrity/maintenance
        │      ├── database_integrity_service.py
        │      ├── database_maintenance_service.py
        │      ├── library_export_service.py
        │      └── library_settings_adapter.py
        │
        └── Batch 3 G17 reconciliation/runtime
               ├── reconciliation_queue_store.py
               ├── reconciliation_queue_migration.py
               ├── asset_index_reconciliation_service.py
               └── bootstrap/runtime/library_service selected hunks
```

重要依赖证据：

- Batch 2 integrity/maintenance/export 直接调用 `DatabaseManager.validate_connection_owner()` 与 `db_write_lock()`；
- Batch 3 queue store 直接调用 `DatabaseManager` 与 `db_write_lock()`；
- `library_settings_adapter.py` 依赖 Batch 2 三个 service；
- `reconciliation_queue_migration.py` 依赖 queue 与 SQLite store；
- `bootstrap.py` 同时组装 Batch 2 与 Batch 3 service，必须最后进行跨域 hunk 合并。

因此长期提交顺序应在 Batch 1 与 Batch 2 之间增加一个可审查的 **Core ownership foundation** 边界，或者明确把该 foundation 作为 Batch 2/3 的共同前置 hunk；不能让任何中间 commit 缺少 `DatabaseManager` owner contract、`db_write_lock` 或 `RootIdentity` 支撑。

## 12. 2026-08-08 Core ownership foundation hardening

在审查 `RootIdentity` / `LibraryContext` / `LibrarySession` / `DatabaseManager` 契约时发现一个真实但仅影响 legacy/manual context 的缺口：`LibraryContext.root_identity` 在未提供 `root_key` 时会返回空 `map_key`，而同一 context 的 `connection_for()` 会自行回退到规范化 root key。

已完成最小修复：

- `LibraryContext.root_identity` 在 `root_key` 为空时使用 `root_identity(self.root, strict=False)`；
- canonical `LibraryService` 路径仍保留已捕获的 root key，不改变正常 owner contract；
- 新增手工构造 context 的回归测试。

验证：

```text
Core ownership/session 定向：119 passed
Ruff：通过
Pyright（context + session binding）：0 errors, 0 warnings, 0 informations
```

确认没有发现 `RootIdentity.map_key`、`session.connection_for()`、`DatabaseManager.validate_connection_owner()` 与 `db_write_lock(conn)` 之间的 canonical owner 断裂。`db_write_lock(conn)` 仍仅负责 connection-level serialization，root owner 校验必须由上游 session/DatabaseManager API 完成。

### 12.1 Full regression after Core ownership fix

`LibraryContext.root_identity` fallback 修复后重新运行完整 Python 测试集：

```text
2719 passed, 7 skipped, 1 warning
```

Core ownership/session 定向组合保持 `119 passed`；未执行 staging 或 commit。


## 2026-08-08 deep lifecycle audit addendum (continued, no staging)

本轮在既有 migration/WebUI 归属审查基础上继续完成 G17 runtime/ownership、DatabaseManager 和 file-operation clean-boundary 的深度检查。工作区仍保持：

```text
471 status entries
187 tracked modifications
284 untracked entries
0 staged
```

未执行 `git reset`、`git clean`、`git add` 或 `git commit`；`AssetsManager_New_WebUI` 仍仅作为只读参考。

### 本轮最小修复（均未 stage）

1. `AssetsManager/application/bootstrap.py`
   - `_build_services()` 改用 `session.context.root_identity`，不再直接从可能为空的 `root_key` 构造 `RootIdentity`；
   - runtime 构建在 session live 检查后、`_runtime_lock` 保护下启动 reconciliation worker，再发布 runtime，避免 close/start race；
   - runtime 构建或 reconciliation `start()` 失败时，主动关闭临时 Runtime，保留 session 可重试；
   - 新增 manual/legacy context identity 与 reconciliation startup failure 回归。

2. `AssetsManager/core/database.py`
   - thumbnail directory 在 managed SQLite connection 发布前创建；目录创建失败不会残留 manager/global connection registry；
   - `validate_connection_owner()` / `require_managed_connection_owner()` 对已标记 `closed` 的 managed connection fail-closed，返回 cleanup-pending；
   - 新增对应失败路径和 owner lifecycle 回归。

3. `AssetsManager/application/file_operation_service.py`
   - `delete_permanent()` 和 `delete_to_trash()` 在文件系统变更前复用 clean transaction boundary；调用方已有 outer SQLite transaction 时拒绝执行，避免“文件已删除、projection 仍可 rollback”的跨系统不一致；
   - 新增 permanent/trash 两种路径的回归。

### 定向验证

```text
bootstrap/runtime/reconciliation：81 passed
Database metadata/migration/concurrency：83 passed
File operation/favorites/event：61 passed
Ruff（本轮目标文件）：通过
Pyright（AssetsManager/application/bootstrap.py）：0 errors, 0 warnings, 0 informations
```

全量 Python 回归本轮首次运行得到：

```text
2724 passed, 7 skipped, 1 failed, 1 warning
```

失败为 `tests/lan/test_server_lifecycle.py::test_startup_cleanup_base_exception_retains_owner_thread_until_stop_retry[cleanup_error1]`；该测试随后单独两参数运行 `2 passed`，完整 `tests/lan/test_server_lifecycle.py` 运行 `39 passed`，判定为现有 LAN 生命周期测试的时序性 flaky failure，而非本轮修改的直接失败。后续若要宣称全量绿，仍应再执行一次完整回归确认。

### 仍保留为后续长期任务的真实风险

这些问题已确认但本轮没有扩大修复范围，必须在长期计划中保持可见：

- `DatabaseManager.migrate_path_metadata()` 同时移动 thumbnail 文件和提交 SQLite 事务，文件系统 rename 与 SQLite commit 不具备原子性；需要后续设计补偿/可重建 cache 策略，并覆盖 thumbnail rows + outer rollback/commit failure；
- `migrate_path_metadata(conn, thumb_dir, ...)` 目前没有验证 managed connection 与 thumbnail directory 是否属于同一 library；
- explicit connection write lock 与 legacy global write lock 的 reader→writer upgrade、多个 connection 的反向嵌套顺序；
- 多个 `DatabaseManager` 可打开同一 root，各自拥有独立 per-connection lock；“每 root 一个 connection/lock”目前是 canonical `LibraryService` invariant，不是 DatabaseManager 自身强制；
- orphan cleanup 与 open/restore 的 TOCTOU admission；
- `_build_services()` 已创建的 canonical `AssetIndexService` 与 LAN projection 可能重复实例化；该项属于低风险一致性优化，尚未为避免扩大测试 monkeypatch 面而改动；
- delete/trash clean-boundary 已修复，但 move/copy/restore 与 projection/file-system 其他跨系统边界仍需专项审计。

### 安全 staging 顺序更新

后续手工 staging 时：

1. Schema spine (`schema_defs.py` + 完整 `db_migrations.py`)；
2. Core ownership foundation（`context.py`、`database.py` managed owner/close 子集、`library_service.py` canonical lifecycle 子集）；
3. G17 runtime/bootstrap/race cleanup 子集；
4. Batch 2 file-operation/projection clean-boundary 子集；
5. Commerce/WebUI 新增文件及其契约测试；
6. 最后再处理 docs/evidence 与临时产物排除。

上述顺序只是人工 `git add -p` 规划，当前继续保持 `0 staged`，不得整文件 stage 混合域文件。


### Full regression follow-up after the audit fixes

在上述首次全量运行出现一次 LAN lifecycle 时序失败后，立即再次运行完整 Python 回归，结果为：

```text
2725 passed, 7 skipped, 1 warning
```

同时，`tests/lan/test_server_lifecycle.py` 单独运行结果为 `39 passed`；当前以第二次完整回归作为本轮最终基线。warning 仍为测试构造重复 ZIP entry 的既有 `UserWarning`，7 个 skip 均为 Windows symlink/spawn 能力边界。


## 2026-08-08 Commerce/WebUI hunk ledger consistency audit (no staging)

### 1. Manifest completeness check

针对当前工作区的 `AssetsManager/`、`webui/`、`tests/`、`.github/`、`README.md`、`ruff.toml` 和交接文档相关状态项进行了机械比对：

```text
relevant status paths：383
ownership manifest 未列出的 relevant path：0
Batch 4–7 跨 batch 重复归属：0
当前 staged：0
```

因此当前 manifest 没有发现遗漏文件或同一文件被错误分配到多个功能批次的问题。以下内容仍必须排除：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tmp\node-repl-test.txt
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tmp\server.diff
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\test-results\.last-run.json
```

### 2. Commerce backend dependency ledger

Commerce 后端不应按目录直接 staging，安全依赖顺序为：

```text
Schema spine
  → Core ownership foundation
  → shop_repository.py
  → domain repositories
  → application services
  → commerce policy/helpers
  → route handlers
  → routes/__init__.py exports
  → lan/api.py registration
  → lan/server.py middleware/runtime binding
```

核心文件归属：

- Storefront：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_authorization.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\storefront_analytics_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\shop_repository.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\storefront_analytics_repository.py`
- Cart/Wishlist：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_buyer_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\shop_buyer_repository.py`
- Checkout/Orders：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\order_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\order_repository.py`
  - 与 `shop_buyer_service.py` 共享 checkout/cart 转换逻辑。
- Delivery：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\quota_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\free_download_quota_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\quota_repository.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\free_download_quota_repository.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\downloads.py` 的相关 quota hunk。
- Seller：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\seller_auth_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\seller_profile_service.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\seller_profile_repository.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_service.py` 的 seller-only 函数族。
- LAN Commerce：
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\commerce_policy.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\shop.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\seller_auth.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\seller_profile.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\api.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\__init__.py`
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\server.py` 的 public-path/auth/runtime hunk。

明确的 mixed 文件：

```text
AssetsManager/application/order_service.py
AssetsManager/lan/routes/shop.py
AssetsManager/lan/api.py
AssetsManager/lan/routes/__init__.py
AssetsManager/lan/server.py
AssetsManager/application/bootstrap.py
AssetsManager/core/database.py
```

这些文件不得整文件归入单一 Commerce 批次或整文件 staging。特别是 `shop.py` 同时承载 Storefront、Cart/Wishlist、Checkout、Orders、Delivery、Seller 六个域；`order_service.py` 同时承载 Orders、Checkout、Delivery 和 Seller fulfill/revoke。

### 3. WebUI route/API closure check

当前 `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\App.tsx` 已覆盖交接文档中的主要路由：

```text
/storefront
/storefront/products
/storefront/product/:id
/storefront/cart
/storefront/wishlist
/storefront/orders
/storefront/checkout/:orderId
/storefront/checkout/group
/storefront/delivery/:token
/store
/store/gallery/:tag
/store/checkout
/store/delivery/:token
/store/*
/seller
/seller/products
/seller/products/new
/seller/products/:id
/seller/orders
/seller/settings
/app
/app/items
/app/orders
```

前端 Commerce API 静态路径与 `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\api.py` 的注册结果一致；动态路径包括：

```text
shop/items/{item_id} (GET public active-only；PUT/DELETE seller-only)
shop/cart/items/{line_id}
shop/wishlist/items/{item_id}
shop/order/{order_id}/...
shop/cart/checkout/{checkout_group_id}
shop/delivery/{token}/...
```

对应的前端 API/契约测试集中在：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.contract.test.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks\useCommerce.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks\useCommerce.test.ts
```

Seller/Buyer 页面与测试成对存在，真实浏览器验收文件仍保留：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-buyer.spec.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-real-backend.spec.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\webui-shell.spec.ts
```

### 4. 当前需要继续关注的共享边界

1. `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\shop.py` 通过 `get_commerce_services()` lazy 组装 Commerce service；下一轮需确认其 lifetime 与 `LibraryRuntime` close 的清理顺序。
2. `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\server.py::connection_for()` 仍使用 `Path.resolve()` 做 active-root 比较，而 Core ownership 使用 `RootIdentity.map_key`；当前 canonical 路径工作正常，但应在正式提交前统一 ownership boundary 或补充明确的兼容说明。
3. `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\downloads.py` 是 Delivery 与既有下载功能的 mixed tracked file，只能按函数/hunk staging。
4. Gallery favorites (`favorite_*`) 与 Commerce wishlist (`shop_buyer_*`) 是不同 schema、owner 和 API，不得按名称合并。

本次只完成 ledger 与一致性核验，没有扩大到上述 shared-lifecycle 重构，也没有执行 staging/commit。

## 2026-08-08 WebUI concurrency/deep-link follow-up (no staging)

本轮在上一节 G17/runtime 与 Commerce/WebUI ledger 基础上继续做运行时竞态、catalog 生命周期和深链一致性审查。未执行 staging 或 commit。

### 已完成的最小修复

- `webui/src/components/storefront/ShopBuyerContext.tsx`：buyer-state 操作统一进入 generation-aware serial queue；身份切换会切断旧队列并清空 cart version；stale response、loading finally、clear/checkout/wishlist mutation 均有身份保护。
- `webui/src/components/storefront/ShopBuyerContext.test.tsx`：新增 stale refresh 与 cart version serialization 回归。
- `webui/src/pages/StorefrontProductPage.tsx`：区分 catalog loading、catalog error 和 settled not-found；避免深链在慢请求/网络失败期间误报商品不存在。
- `webui/src/pages/StorefrontProductPage.test.tsx`：新增 4 个页面生命周期测试；该路径归入 Batch 7。
- `webui/src/i18n/en.ts`、`webui/src/i18n/ja.ts`、`webui/src/i18n/zh.ts`：补齐 product loading/error 文案，仍归入 WebUI shared/storefront 迁移域，实际 staging 时按 hunk 审查。

### 本轮验证基线

```text
WebUI：82 test files passed，538 tests passed
TypeScript typecheck：通过
WebUI build：通过
Playwright Mock/Shell：4 passed
LAN Commerce targeted：237 passed
Python：2725 passed，7 skipped，1 warning
```

### 仍需进入长期任务而非本轮直接扩大范围的风险

- public catalog 默认 limit=500；该上限仍影响目录列表，但 numeric `/storefront/product/:id` 已通过 active-only detail API 读取 catalog 之外的 active 商品。
- 不应把参考项目的 metadata-based `/store/:itemPath(*)` 直接替换当前 Commerce `/storefront/product/:id`，因为 Commerce 商品允许任意可下载文件，不等同于 metadata project detail。
- 页面级/E2E 覆盖仍需继续扩展到 Wishlist、Delivery、Seller 和 catalog-out-of-list deep link；真实后端 E2E 仍必须显式设置隔离环境。

当前仍是 dry-run：`git diff --cached` 为空，`staged = 0`。
## 2026-08-08 public item detail endpoint follow-up (no staging)

已完成上一轮长期风险中的 active-only public detail 闭环：

- Batch 4/5 的 backend/LAN mixed files 新增 `GET /api/shop/items/{item_id}`，仅返回 active、enabled 且位于授权销售根目录内的商品。
- Batch 7 的 `webui/src/api/shop.ts` 与 `webui/src/pages/StorefrontProductPage.tsx` 对 catalog settled miss 的 numeric ID 增加 detail fallback。
- 不修改旧 `/store/*` metadata 兼容路由；Commerce 任意文件商品继续使用 `/storefront/product/:id`，避免把 project metadata detail 错当成商品 detail。

验证基线：53 个 Commerce/backend 定向测试、WebUI 82/539、typecheck/build、Python 2728/7/1 全部通过。

后续仍需处理：非 numeric slug/path 深链契约、目录列表 limit 的产品级分页/搜索策略、Wishlist/Delivery/Seller 页面级和默认 E2E 覆盖。
当前仍保持 dry-run，`git diff --cached` 为空，`staged = 0`。
## 2026-08-08 product detail response-race follow-up (no staging)

Batch 7 页面测试新增 route parameter 切换竞态回归，确认旧详情响应不会覆盖新商品页面。最新 WebUI 基线为 82 个测试文件、540 个测试通过；typecheck 通过。

本轮仍不改变 manifest 数量，不改变 mixed-file staging 顺序，不执行 `git add` 或 commit。
## 2026-08-08 Wishlist/Delivery page coverage follow-up (no staging)

Batch 7 新增：`StorefrontWishlistPage.test.tsx` 与 `StorefrontDeliveryPage.test.tsx`。

验证结果：WebUI 84 个测试文件、544 个测试通过；typecheck 通过。

当前仍保持 dry-run：不执行 `git add`、stage 或 commit；后续 Seller Dashboard/Login 和真实后端 E2E 仍是独立覆盖任务。
## 2026-08-08 Seller page coverage follow-up (no staging)

Batch 7 新增页面级覆盖：

- `webui/src/pages/SellerDashboardPage.test.tsx`：stats、recent products/orders（最多 4 条）、empty state、navigation；
- `webui/src/pages/SellerLoginPage.test.tsx`：空密码/空白密码、成功登录、失败 toast、提交 loading 与重复提交保护。

验证结果：

```text
WebUI 定向：2 个测试文件、8 个测试通过
WebUI 全量：86 个测试文件、552 个测试通过
typecheck：通过
build：通过
```

本轮仅新增测试与归属文档，没有修改 Seller 生产页面，没有执行 `git add`、stage 或 commit。Batch 7 manifest 数量更新为 58；当前仍保持 `staged = 0`。

下一步仍需处理：`BuyerDeliveryDownloadButton`、`SellerGalleryEditor` 的组件级覆盖；Wishlist/Delivery/Seller 默认 Playwright E2E；catalog-out-of-list numeric detail fallback 的浏览器回归；真实后端 E2E 的隔离环境验收；非 numeric slug/path 深链契约与 catalog 分页/搜索策略。
## 2026-08-08 storefront/seller component coverage follow-up (no staging)

Batch 7 新增组件级覆盖：

- `webui/src/components/storefront/BuyerDeliveryDownloadButton.test.tsx`：幂等 request key、Blob/Object URL、下载文件名、revoke、loading/重复点击、错误 toast、卸载保护；
- `webui/src/components/storefront/SellerGalleryEditor.test.tsx`：cover/gallery 编辑、相对路径/重复校验、添加/删除/排序、ArrowUp/ArrowDown/Delete 键盘操作、预览 URL 与失败回退。

验证结果：

```text
组件定向：2 个测试文件、10 个测试通过
WebUI 全量：88 个测试文件、562 个测试通过
typecheck：通过
build：通过
```

本轮仅新增测试与测试归属记录，没有修改生产组件，没有执行 `git add`、stage 或 commit。Batch 7 manifest 数量更新为 60；当前仍保持 `staged = 0`。

下一步：补 Wishlist/Delivery/Seller 默认 Playwright E2E 与 catalog-out-of-list numeric detail fallback 浏览器回归；在隔离环境复验真实后端 Commerce E2E；明确非 numeric slug/path 深链契约和 catalog 分页/搜索策略。组件级测试当前已覆盖本轮交接中列出的两个主要缺口。
## 2026-08-08 Mock E2E coverage follow-up (no staging)

Batch 7 Playwright 覆盖继续扩展：

- `webui/e2e/commerce-buyer.spec.ts`：Wishlist 保存/展示/移除、Checkout Group receipt 中的 Buyer Delivery 下载、catalog 缺少 numeric 商品时的 detail endpoint fallback；原有商品/购物车/Checkout 测试保持通过；
- `webui/e2e/seller.spec.ts`：Seller 登录进入 Dashboard、Dashboard 导航到 Products、catalog API 失败时 Dashboard 不白屏。

验证结果：

```text
Buyer + Seller：8 passed
Buyer + Seller + WebUI shell：10 passed
typecheck/build 基线：已通过
```

本轮仅新增/扩展 Mock E2E 与归属记录，没有修改生产代码，没有执行 `git add`、stage 或 commit。Batch 7 manifest 数量更新为 61；当前仍保持 `staged = 0`。

环境说明：Mock E2E 期间 Vite 对缩略图或未启动的本地后端 `127.0.0.1:8080` 输出 proxy warning，但不影响测试断言；真实后端 Commerce E2E 仍需隔离后端环境变量后单独验收。

下一步：在隔离环境运行真实后端 Commerce E2E；继续确认 legacy `/store/*` 与新 Commerce `/storefront/*` 契约不冲突；再决定是否引入非 numeric slug/path detail API 与 catalog 分页/搜索策略。
## 2026-08-08 real backend E2E environment check (no staging)

已执行：

```text
npm run test:e2e -- e2e/commerce-real-backend.spec.ts
```

结果：`1 skipped`。当前 shell 未设置 `REAL_COMMERCE_BASE_URL` 或 `REAL_COMMERCE_SELLER_PASSWORD`，因此没有冒险连接未知后端，也没有改变隔离环境。真实 buyer checkout → seller fulfillment → buyer delivery 仍列为下一阶段的显式环境任务。

本次没有修改代码、没有执行 `git add`、stage 或 commit；`staged = 0`。
## 2026-08-08 Commerce contract risk audit (read-only, no staging)

并行只读审查确认两项长期风险不应在没有产品契约的情况下直接改生产代码：

1. **非 numeric detail**：当前 `shop_items` 没有独立 slug，Repository 只有 `get_by_path()`，Service/API/前端仍是 numeric ID contract。推荐新增显式 `GET /api/shop/items/by-path?path=...` 与 `/storefront/product/path/*`，保持 `/api/shop/items/{item_id}`、`/storefront/product/:id` 和 legacy `/store/*` 不变；public path detail 复用 active/enabled/authorized-root 与统一 404 语义。
2. **catalog 分页/搜索**：当前 `/api/shop/items` 无显式 limit/offset/search，Repository 默认 500，Service 负责授权路径过滤，WebUI 对已加载结果做本地过滤；没有可复用的 Commerce pagination DTO。推荐新增 buyer 专用 `/api/shop/catalog`（limit/offset/q/category/tags/sort + total/has_more），不要直接改变现有 `/api/shop/items` 或 legacy `/api/search`；实现前必须保证 items/total 与授权过滤一致，避免分页空洞和数量侧信道。

结论：本轮不做这两项生产改造，只把 API、权限、错误语义、兼容边界和测试清单记录下来，等待明确的产品契约后再拆分后端/前端/测试批次。`staged = 0`。
## 2026-08-08 Seller Login accessibility label follow-up (no staging)

深度复查发现 `SellerLoginPage` 的 username 与 password 两个字段原先都使用 `header.login` 作为 label，导致两个输入控件的可访问名称相同且语义错误。已做最小修复：

- `webui/src/pages/SellerLoginPage.tsx`：改用 `auth.username` 与 `auth.password`；
- `webui/src/pages/SellerLoginPage.test.tsx`：新增 distinct accessible labels 回归测试。

验证结果：

```text
SellerLoginPage：6 passed
WebUI 全量：88 个测试文件、563 个测试通过
typecheck：通过
build：通过
Seller Mock E2E：3 passed
```

本轮仍未执行 `git add`、stage 或 commit；`staged = 0`。Python/backend 全量基线未因该 WebUI 小修复重复执行，下一次生产后端变更时再重新跑对应后端门禁。
## 2026-08-08 Seller Gallery localization follow-up (no staging)

深度 UI 审查发现 `SellerGalleryEditor` 内仍有未经过 i18n 的中文校验文案、Cover/Gallery 字段和键盘操作 aria-label。已完成最小适配：

- `webui/src/components/storefront/SellerGalleryEditor.tsx`：改用 seller gallery 专用 i18n keys；
- `webui/src/i18n/en.ts`、`webui/src/i18n/zh.ts`、`webui/src/i18n/ja.ts`：补齐三种语言的 label、校验、预览与排序操作文案；
- 受影响的 SellerProducts/MediaFallback 测试 mock 已同步补齐参数化翻译。

验证结果：

```text
SellerGalleryEditor + i18n：10 passed
SellerProducts + MediaFallback：17 passed
WebUI 全量：88 个测试文件、563 个测试通过
typecheck：通过
build：通过
```

本轮仍未执行 `git add`、stage 或 commit；`staged = 0`。Python/backend 全量仍沿用之前的基线，因为本轮只改动 WebUI 生产/UI 文案和对应测试。
## 2026-08-08 path-detail contract follow-up (no staging)

上一版计划将非 numeric 商品深链记录为待决策项；本轮已在不改变既有 numeric/legacy 契约的前提下完成显式 path-detail contract。该实现属于 Batch 4/5/7 的跨层变更，提交时必须按功能域和 mixed-file hunk ledger 拆分，不得用宽泛路径一次性 stage。

### 归属边界

- **Batch 4 — Commerce backend**
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_service.py`：`ShopService.get_public_item_by_path()`；复用相对路径规范化、授权销售根目录、public DTO 和 active/enabled 过滤。
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_commerce_services.py`：path lookup、状态和授权语义回归。
- **Batch 5 — LAN Commerce / auth**
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\shop.py`：`handle_public_shop_item_by_path()`。
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\__init__.py`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\api.py`：导出和路由注册；by-path 静态路由必须保持在 numeric `/{item_id}` 之前。
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\lan\test_commerce_routes.py`：HTTP 错误/feature-gate/404 contract。
- **Batch 7 — WebUI Storefront / Seller**
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.ts`：`getItemByPath(path)`，由 `URLSearchParams` 负责编码。
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\StorefrontProductPage.tsx`：wildcard path route、loading/error/not-found、stale response 防护；numeric detail fallback 和 legacy `/store/*` 保持不变。
  - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\StorefrontProductPage.test.tsx`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api\shop.contract.test.ts`、`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-buyer.spec.ts`：contract、生命周期、deep-link 回归。

### 契约语义

- `GET /api/shop/items/by-path?path=<URL-encoded-relative-path>` 为新的明确接口；缺失或非法 path 返回 validation `400`。
- 不存在、draft、archived、disabled、未授权销售根目录的 path 统一返回 public `404`，不泄漏存在性；Commerce disabled 仍返回既有 `503`。
- `GET /api/shop/items/{item_id}`、`/storefront/product/:id` 和 legacy `/store/*` 不改变；新前端 canonical route 为 `/storefront/product/path/*`。

### 当前验证与状态

- Backend path contract：12 passed；WebUI API/detail targeted：20 passed；path deep-link 已纳入 Buyer Playwright suite。
- WebUI 当前 targeted/full 基线：88 个测试文件、566 个测试通过；typecheck/build 通过。
- 当前状态基线：478 status entries / 187 tracked modified / 291 untracked / 0 staged；ownership manifest 逐路径闭合 478/478；未执行 `git add`、stage、commit、reset 或 clean。

后续提交顺序仍为 Batch 1 → 8，path-detail 不创建独立提交名额，而是按上述三层归属与依赖顺序拆分后再手工 stage。
## 2026-08-08 Commerce public media hardening follow-up (no staging)

深度审查发现公共商品 JSON/页面是 Commerce public contract，而商品图片仍指向普通 `/api/thumbnails/*`，在 LAN 鉴权或 `lan_guest_preview=false` 时会产生 401/403 断层。本轮完成以下最小修复；提交时必须按功能域和 mixed-file hunk ledger 拆分。

### 推荐拆分

- **Batch 4 — Commerce backend**：`AssetsManager/application/shop_service.py` 的 cover/gallery authorized-root 校验与 public media slot resolver；对应 `tests/unit/test_commerce_services.py`。
- **Batch 5 — LAN Commerce / auth**：`AssetsManager/lan/routes/shop.py`、`AssetsManager/lan/routes/__init__.py`、`AssetsManager/lan/api.py` 的 public media route；对应 `tests/lan/test_commerce_routes.py`。
- **Shared LAN/image hunk**：`AssetsManager/lan/routes/image.py` 与 `tests/lan/test_image_routes.py` 的安全 raster/thumbnail/blur helper；不能把整个文件作为 Commerce 批次宽泛 stage，应按 hunk 与既有 image contract 分离审查。
- **Batch 7 — WebUI Commerce**：`webui/src/hooks/useCommerce.ts`、其测试和 `webui/e2e/commerce-buyer.spec.ts` 的专用 media URL、slot、Mock E2E 断言；普通图库 `/api/thumbnails` fallback 保持。

### Contract

- `GET /api/shop/items/{item_id}/media/{cover|gallery-N}?size=...` 是受 Commerce gate、active/enabled/public-authorized item 和商品自身媒体槽位约束的公开图片接口。
- 不接受任意文件路径；无效槽位、越界、未授权、非图片、缺失和 stale item media 统一 `404`；不改变 `/api/thumbnails`、`/api/image` 或 `lan_guest_preview`。
- `/storefront/product/path/*` 直接刷新由服务端 SPA route 承接；前端 path canonicalization 与 catalog 最新响应保护已补齐。

### 最新门禁

- Python full：`2736 passed / 7 skipped / 1 warning`。
- Commerce/media backend targeted：`30 passed`，Ruff 通过。
- WebUI：`88 files / 573 tests`，typecheck/build 通过。
- Playwright Buyer：`6 passed`；此前 Buyer + Seller + WebUI Shell 合计 `11 passed`。
- 当前状态：`478 entries / 187 tracked / 291 untracked / 0 staged`；ownership manifest `478/478` 闭合；无自动 commit。
## 2026-08-08 real backend E2E and catalog contract follow-up (no staging)

### Optional real-backend E2E hardening

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-real-backend.spec.ts` 新增独立只读测试，不插入既有 checkout/fulfillment 状态机：

- 从真实 `/api/shop/items` 选择 active/enabled 商品；
- 显式验证 `/api/shop/items/by-path` 返回同一商品；
- 直接访问 `/storefront/product/path/{item_path}` 并验证 SPA/商品标题；
- 仅在 `cover_path` 或 gallery entry 存在时验证 `/api/shop/items/{id}/media/{slot}` 返回 `image/*`；
- 复用现有 `REAL_COMMERCE_BASE_URL` 与 `REAL_COMMERCE_SELLER_PASSWORD` describe-level skip。

当前环境没有设置真实凭据，因此该 spec 当前结果为 `2 skipped`；Playwright 编译和 skip 行为已验证。真实后端环境可用时，该测试将作为只读前置验收，不会创建订单或改变 seller 状态。

### Catalog contract audit

只读审查确认当前 Commerce catalog 仍不是分页/搜索 API：

- `ShopRepository.list_items()` 默认 SQL `LIMIT 500`，没有 offset/cursor/total；
- 状态过滤和 service authorized-root 过滤发生在初始 LIMIT 之后，可能造成结果不足和漏项；
- `/api/shop/items` 只接受既有 `status/include_disabled` 语义，public 强制 active；
- WebUI 的 q/category/sort 仍全部对已加载商品做本地过滤；
- 没有正式 catalog pagination DTO，legacy `/api/search` 是文件/资产搜索，不能替代 Commerce catalog。

本轮不直接修改现有 `/api/shop/items`，避免破坏旧 response shape、numeric detail、by-path、public media、legacy `/api/search` 和 `/store/*` 兼容。下一阶段建议先冻结独立 `GET /api/shop/catalog` 合同：第一批只承诺 q/title+description、page/page_size、稳定 newest sort 和 public active-only；category/tags/featured 等字段需先明确 metadata/schema 来源。

当前长期任务仍为：合同冻结 → repository/service SQL-side filtering 与稳定分页 → WebUI hook/page 迁移 → 大目录性能和安全回归。`staged = 0`。
## 2026-08-08 current ownership closure audit (no staging)

本轮重新执行 `git status --short --untracked-files=all`，当前状态为：

```text
479 status entries
187 tracked dirty
292 untracked
0 staged
```

修正项：

- `webui/src/pages/StorefrontProductsPage.test.tsx` 已显式加入 Batch 7 测试 ledger；
- Batch 7 文件计数由 61 修正为 62；
- 当前 manifest 与 batch plan 的最新基线均为 479/187/292/0；
- `tmp/**`、`webui/test-results/**`、`webui/playwright-report/**` 仍属于排除项，不能通过宽泛命令纳入；
- 未执行任何 `git add`、stage、commit、reset 或 clean。

### Schema spine verification

按 Batch 1 计划运行：

```text
python -m pytest -q -p no:cacheprovider tests/core/test_db_migrations.py tests/core/test_delivery_attempt_migration.py tests/core/test_commerce_migration_matrix.py tests/core/test_reconciliation_queue_migration.py
75 passed
```

`AssetsManager/core/db_migrations.py` 与 `AssetsManager/core/schema_defs.py` 仍必须作为完整 migration spine 审查；不能把 registry hunk 拆成非连续的中间提交。

## 2026-08-08 Batch 2/3 shared prerequisite audit (no staging)

逐文件审查发现，Batch 2 与 Batch 3 不能只按各自新增文件独立提交；两批都依赖当前工作区的 shared session/identity/connection-owner contract。

### 必须先闭合的 shared hunk

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\session_contract.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\path_resolver.py       # RootIdentity / root_identity / path remap hunk
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\context.py      # session liveness / root identity / registration hunk
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\database.py       # validate_connection_owner / managed owner / identity-aware connection hunk
```

证据：

- Batch 2 的 integrity、maintenance、export service 直接调用 `DatabaseManager.validate_connection_owner(..., allow_unmanaged=True)`、`db_write_lock` 和当前 `LibrarySession` liveness API；
- `AssetsManager/application/context.py` 当前 hunk 引入 `AssetsManager.core.session_contract.register_library_session`，如果不同时纳入 `AssetsManager/core/session_contract.py`，中间提交会在 import 阶段失败；
- Batch 2 的 export service 使用 `RootIdentity`、`root_identity`、identity-aware data/lock paths；
- Batch 3 的 `reconciliation_queue_store.py` 同样调用 connection-owner validation 和 connection-bound `db_write_lock`；
- Batch 3 的 runtime/bootstrap 集成还依赖当前 `LibrarySession`、`LibraryRuntime` 和 `DatabaseManager` 的生命周期 hunk。

### 安全提交顺序修正

建议将顺序解释为：

```text
Batch 1 Schema spine
→ Shared session/identity/connection-owner prerequisite（按 hunk + session_contract.py）
→ Batch 2 Restore/integrity/maintenance
→ Batch 3 G17 reconciliation/runtime
```

或将 shared prerequisite 与 Batch 2/3 的首个功能提交绑定，但不能把 Batch 2/3 新增文件单独提交到仍缺少上述 API 的 HEAD。`database.py`、`context.py`、`path_resolver.py`、`bootstrap.py`、`runtime.py` 仍禁止整文件 stage。

本轮没有执行 staging、commit、reset 或 clean。


### Batch 2/3 targeted verification

```text
198 passed，2 skipped，1 warning
```

Skip 为 Windows symlink/进程边界；warning 为既有 zipfile duplicate-name warning。


## 2026-08-08 Batch 4/5 Commerce/LAN closure audit (no staging)

### 文件闭合

当前清单中 Batch 4 的 31 个文件和 Batch 5 的 23 个文件全部存在，并全部出现在当前 `git status --short --untracked-files=all` 结果中。

### Commerce backend 依赖

Batch 4 的新增 service/repository 文件主要依赖：

```text
AssetsManager/application/context.py
AssetsManager/core/database.py
AssetsManager/core/path_resolver.py
AssetsManager/core/schema_defs.py
AssetsManager/application/auth_service.py
AssetsManager/repositories/auth_repository.py
```

其中：

- `shop_service.py`、`order_service.py`、`shop_buyer_service.py` 和多个 repository 使用当前 connection-owner validation；
- `seller_auth_service.py` 依赖当前 `AuthService`；
- 当前 `AuthService`/`AuthRepository` 的 session-binding hunk 又依赖 shared `LibrarySession`、`session_contract.py` 和 `RootIdentity`；
- 因此 Batch 4 不能作为完全脱离 shared auth/session prerequisite 的孤立提交。

### LAN Commerce 依赖

Batch 5 的新增路由文件通过以下 mixed tracked 文件接入旧 LAN：

```text
AssetsManager/lan/api.py
AssetsManager/lan/routes/__init__.py
AssetsManager/lan/routes/_helpers.py
AssetsManager/lan/server.py
AssetsManager/lan/principal.py
```

安全边界审查结果：

- route registration 中 `/api/shop/catalog` 的 GET 路由唯一；
- selected Commerce/Seller/public route 共 80 条，未发现同一 method/path 重复注册；
- `/api/shop` 由 server public-prefix 放行，但 Seller mutation/auth 仍由 handler-level `commerce_policy`/seller gate 保护；
- 旧 LAN 页面、旧下载、旧 `/store/*` 路由仍与 Commerce 新 handler 分离。

### 定向验证

```text
Batch 4/5 Commerce + LAN：149 passed
```

本轮没有修改 Commerce/LAN 生产代码，没有执行 staging、commit、reset 或 clean。


## 2026-08-08 Batch 6/7 WebUI closure audit (no staging)

### 依赖与批次边界

Batch 6 的 tracked integration 文件不能简单作为独立、先于 Batch 7 的提交：

- `webui/src/App.tsx` 直接导入 Batch 7 的 `SellerAuthContext`、`SellerAccessGate`、`ShopBuyerContext`，以及所有 Storefront/Seller lazy pages；
- `webui/src/types/api.ts` 同时包含 shared API types 与 Commerce types，必须按 hunk 或作为 shared type prerequisite 处理；
- `webui/src/api/client.ts`、`webui/src/stores/AuthContext.tsx`、`webui/src/stores/RealtimeContext.tsx` 是 Batch 6/7 共用边界，应先审查其 shared hunk；
- `webui/playwright.config.ts` 同时连接 Batch 7 E2E 与 Batch 8 CI，必须只 stage 一次；
- `App.tsx` 的 33 个相对导入、AuthContext 的 5 个相对导入、RealtimeContext 的 2 个相对导入，以及 Storefront/Seller 关键页面导入均已解析，无缺失目标。

安全顺序应调整为：

```text
Batch 6 shared API/types/auth/realtime prerequisite
→ Batch 7 Storefront/Seller implementation and tests
→ App.tsx route integration hunk
→ Playwright/CI cross-domain hunk（只提交一次）
```

如果要保持 Batch 6→Batch 7 的提交顺序，则 `App.tsx` 的 Commerce route integration 必须延后到 Batch 7 完成后，不能整文件提前提交。

### 当前验证

```text
WebUI full：89 个测试文件，583 个测试通过
TypeScript typecheck：通过
WebUI build：通过
Playwright Mock/Shell：12 passed
```

本轮没有修改 WebUI 业务代码，没有执行 staging、commit、reset 或 clean。


## 2026-08-08 Batch 8 CI/tooling closure audit (minimal repair, no staging)

### 本轮最小修复

修改文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\.github\workflows\ci.yml
```

修复内容：

- `hygiene` job 不再对干净 checkout 执行无效的空 diff；现在按 pull request base、push before 或当前 commit parent 选择真实变更范围执行 `git diff --check`；
- WebUI CI E2E 现在同时运行 Commerce Buyer、Seller 和 WebUI Shell 三组 Mock/Shell spec，不再漏掉 Seller E2E。

### Cross-domain 审查

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\playwright.config.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\.github\workflows\ci.yml
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\ruff.toml
```

- Playwright config 的本地 Chromium 路径有 `existsSync` fallback，Linux CI 不会被 Windows 路径硬失败；
- `webServer` 使用 WebUI preview，CI E2E 可自包含启动；
- `webui/package-lock.json` 存在，`npm ci` 依赖锁定有效；
- `ruff.toml` 的临时目录排除与当前 `tmp/**` 工作区边界一致。

### 本地门禁验证

```text
CI YAML parse：通过
Ruff check AssetsManager tests scripts run.py：通过
Python compileall：通过
git diff --check：通过（仅既有 LF/CRLF 提示）
WebUI full：89 个测试文件，583 个测试通过
WebUI typecheck/build：通过
Playwright full：28 passed，2 skipped（30 tests discovered；Mock/Shell subset 12 passed）
```

本地没有运行 GitHub-hosted Windows package smoke 或 Ubuntu/Windows CI runner 本身；这些仍需在远程 CI 环境执行。没有执行 staging、commit、reset 或 clean。

## 2026-08-08 final consistency addendum (no staging)

- Batch 7 E2E ledger now explicitly includes `webui/e2e/seller.spec.ts`; it is untracked, runs in default CI, and is not Batch 8.
- `.github/workflows/ci.yml` hygiene checkout now uses `fetch-depth: 0`, so PR base and push-before SHAs used by `git diff --check` are available in the runner.
- Default Mock/Shell subset is Buyer + Seller + Shell: 12 tests. The default CI job now discovers all 5 spec files (30 tests); the two real-backend tests skip without configured environment variables. Earlier `4 passed` values in the handoff are historical snapshots.
- Local full Python verification on 2026-08-08 (Windows, Python 3.14) completed with `2760 passed, 7 skipped, 1 warning`; this is local evidence and does not replace the remote Python 3.12/3.13 matrix.
- Local full WebUI Vitest verification completed with `89 test files passed, 585 tests passed`; Playwright full discovery remains `28 passed, 2 skipped` across 30 tests.
- Current status baseline remains 479 entries: 187 tracked modified, 292 untracked, 0 staged. Permission-denied warnings for historical pytest temp directories remain known and are not cleanup targets.
- Clean prerequisites such as `webui/package.json`, `webui/package-lock.json`, `requirements*.txt`, `scripts/check_package_contents.py`, and `.github/workflows/nightly-perf.yml` are not dirty files and must not be force-added by broad staging commands.

本轮仍未执行 `git add`、stage、commit、reset 或 clean。


## 2026-08-08 CI coverage follow-up (no staging)

- Push hygiene now compares the recorded `PUSH_BEFORE` and `CURRENT_SHA` tree objects directly. If the before object is unavailable (for example after a force-push), or the event is an initial/root push, the workflow falls back to root-safe `git show --check --format= CURRENT_SHA` instead of using a missing parent or an incorrect three-dot range.
- `webui-e2e` now runs Playwright's complete discovery instead of a three-file whitelist: 5 spec files, 30 discovered tests. Local result on 2026-08-08 was `28 passed, 2 skipped`; the two skipped tests are the optional real-backend cases without configured credentials/base URL. The Mock/Shell subset remains 12 passed.
- Ruff CI coverage now includes `AssetsManager`, `tests`, `scripts`, and `run.py`; the expanded local check passed.

本轮仍未执行 `git add`、stage、commit、reset 或 clean。


## 2026-08-08 final manual staging order and hunk checklist (no staging)

### A. 固定前置检查

每个实际 staging 批次开始前必须重新执行：

```powershell
git status --short --untracked-files=all
git diff --check
git diff --name-only
git diff --cached --name-only
```

要求：确认没有意外 staged 内容；禁止 `git add .`、`git add -A`、目录级宽泛 stage；临时目录和历史 dirty 文件不做清理。

### B. 推荐人工 staging 顺序

```text
1. Batch 1  Schema migration spine
   schema_defs.py + db_migrations.py 的连续 registry/contract/runner hunk + migration tests
2. Shared session/identity/connection-owner prerequisite
   session_contract.py；context.py、path_resolver.py、database.py 的对应 hunk；必要的 AuthService/AuthRepository session-binding hunk
3. Batch 2  Restore / integrity / maintenance
4. Batch 3  G17 reconciliation/runtime
5. Batch 4  Commerce backend service/repository + tests
6. Batch 5  LAN Commerce routes/auth + registration hunk
7. Batch 6  WebUI shared API/types/auth/realtime prerequisite
8. Batch 7  Storefront/Seller pages, providers, APIs, tests, all E2E specs
9. App.tsx Commerce/Seller route integration hunk（在 Batch 7 页面和 provider 完整后）
10. Cross-domain Playwright/CI hunk（playwright.config.ts 只 stage 一次）
11. Batch 8  CI/docs/tooling primary files及其明确 verification hunks
```

每一批都应先完成对应定向测试，再考虑下一批；每一批可独立运行的中间提交不得留下 import/runtime 缺口。

### C. Mixed-file hunk ledger

```text
AssetsManager/core/db_migrations.py
  Schema migration spine 必须保持连续；不要把 registry/required_objects 拆成会使 _validate_history() 失败的中间态。
AssetsManager/application/bootstrap.py
  G17 ownership/runtime、Batch 2 restore/integrity、LAN/Favorite/Gallery/session wiring；只按 hunk。
AssetsManager/application/runtime.py
  G17 runtime、legacy lifecycle、LAN/session wiring；只按 hunk。
AssetsManager/core/database.py
  schema/migration、connection-owner/db_write_lock、既有 database changes；只按 hunk。
AssetsManager/core/path_resolver.py
  RootIdentity/root remap prerequisite 与既有路径行为分开；只按 hunk。
AssetsManager/application/context.py
  session liveness/root registration prerequisite 与既有 context wiring 分开；只按 hunk。
AssetsManager/application/auth_service.py
AssetsManager/repositories/auth_repository.py
  session-binding hunk 先于 SellerAuthService；不要整文件替换旧 Auth 行为。
AssetsManager/lan/api.py
AssetsManager/lan/server.py
AssetsManager/lan/principal.py
AssetsManager/lan/routes/__init__.py
AssetsManager/lan/routes/_helpers.py
  Commerce registration/public-prefix、Seller gate、legacy LAN 页面/auth/download 三组边界分开。
webui/src/App.tsx
  shared providers/legacy routes 与 Commerce/Seller lazy route integration 分开；Commerce hunk 后置。
webui/src/types/api.ts
webui/src/api/client.ts
webui/src/stores/AuthContext.tsx
webui/src/stores/RealtimeContext.tsx
  shared API/auth/realtime prerequisite 与 Commerce additions 分开。
webui/playwright.config.ts
  lines 1-17 = Batch 7 local Chromium portability；lines 19-23 = Batch 8 CI webServer；同一文件只 stage 一次。
README.md
  只 stage CI/tooling/verification hunks；Commerce/Seller/LAN 说明须人工判断，禁止整文件 stage。
```

### D. 明确排除

```text
tmp/node-repl-test.txt
tmp/server.diff
webui/test-results/.last-run.json
tmp/pytest-*/
tmp/*-test*/
webui/playwright-report/
coverage/
dist/
build/
```

这些项目不得通过宽泛命令进入任何迁移批次，也不得使用 `git clean` 处理。

本清单只生成人工操作顺序；本轮仍未执行 `git add`、stage 或 commit。


## 2026-08-08 deep audit hardening follow-up (minimal fixes, no staging)

### 已完成的最小修复

1. `AssetsManager/lan/server.py`
   - `/api/shop/**` 继续保持 guest/public 可访问；
   - 但如果请求携带有效 Bearer/`lan_token`，middleware 现在会尝试解析 access-key、local-ui、user 或 password principal；
   - 无凭据/无效凭据仍回落 guest，不会把公开 catalog/cart/receipt/delivery 变成全局 401；
   - 新回归位于 `tests/lan/test_public_commerce_auth.py`。
2. `AssetsManager/application/library_service.py`
   - canonical `close_session()` / `close()` teardown 完成后统一失效 context/tag-store/project-data liveness；
   - 新回归位于 `tests/integration/test_core_store_session_binding.py`。
3. `webui/src/App.tsx`
   - `ShopBuyerProvider` 从全局 App wrapper 移入 Commerce feature route subtree；
   - `/`、`/gallery`、旧非 Commerce 页面不再因为全局 provider 自动触发 `/api/shop/cart`、`/api/shop/wishlist`；
   - `webui/src/App.test.tsx` 增加 provider route-scope 回归。
4. `AssetsManager/application/auth_service.py` + `AssetsManager/application/seller_auth_service.py`
   - Seller session 每次 authenticate 都重新读取当前用户；
   - 管理员停用或降权后旧 seller bearer fail closed 并从内存 session 中移除；
   - `tests/unit/test_commerce_services.py` 增加停用、重新激活和降权回归。
5. `AssetsManager/core/database.py`
   - identity marker 发布后，legacy migration、library/thumb 目录准备失败不会再删除正式 marker；
   - `tests/core/test_path_resolver.py` 与 `tests/core/test_database_metadata.py` 覆盖 marker retention。

### 本轮验证

```text
Python full：2760 passed，7 skipped，1 warning
Seller/Commerce regression subset + architecture boundary：39 passed
identity/database targeted：29 passed
Commerce/LAN + core session targeted：53 passed
App route tests：14 passed
WebUI full Vitest：89 个测试文件，585 个测试通过
WebUI typecheck：通过
WebUI build：通过
Playwright full：28 passed，2 skipped（30 tests discovered）
Ruff affected Python files：通过
```

### 尚未处理、列为下一轮安全/生命周期任务

- Seller feature toggle 的事件驱动批量撤销，以及与服务生命周期绑定的 token 清理；管理员停用/降权的按请求 fail-closed revalidation 已完成；
- identity marker `.pending` 的 stale-owner recovery；
- v8/v16/v19 等 migration 使用冻结版本 DDL，避免历史 schema 语义提前泄漏；
- deprecated `get_library_dir()` 与 identity/migration protocol 的兼容边界；
- 干净 checkout 中逐批 import smoke 和远程 CI/package-smoke。

本轮仍未执行 `git add`、stage、commit、reset 或 clean。

## 2026-08-09 continuation audit (no staging)

### 本轮完成

- `AssetsManager/core/database.py` 将固定 `.identity.pending` claim 纳入 per-slot crash-releasing OS lock；matching stale pending 可在锁内恢复，mismatched/malformed pending 不得接管；
- `AssetsManager/application/seller_auth_service.py` 增加 `revoke_all()`；`AssetsManager/lan/server.py` 在 shutdown 早期撤销 cached 与 scoped/injected Seller sessions；
- `AssetsManager/lan/routes/commerce_policy.py` 在 Seller disabled 的 status/logout 路径只检查已缓存服务，不创建新的 Commerce service，并执行幂等撤销；
- `AssetsManager/core/settings.py` 与 `SellerAuthService` 绑定 effective Commerce/Seller toggle generation，关闭再开启不会恢复 dormant Seller bearer；
- 回归覆盖位于 `tests/core/test_path_resolver.py`、`tests/core/test_database_metadata.py`、`tests/unit/test_commerce_services.py`、`tests/lan/test_server_lifecycle.py`、`tests/lan/test_commerce_policy.py`。

### 本轮验证

```text
Python full：2767 passed，7 skipped，1 warning
identity/database targeted：31 passed
Seller/Commerce regression：39 passed
LAN shutdown-focused regressions：5 passed
LAN server lifecycle full file：40 passed + 1 known pre-existing timing flaky（同一失败用例 isolated rerun 1 passed）
Ruff affected files：通过
```

### 下一轮必须保持显式设计的边界

- Seller stop/start 与 startup-failure 的全部终止路径；
- unique temporary marker + atomic no-clobber publication；
- marker symlink/corruption 与 parent-directory durable fsync；
- 不得以固定超时删除 `.pending`，不得执行宽泛清理。

本轮仍未执行 `git add`、stage、commit、reset 或 clean。

---

## 2026-08-09 后续硬化批次（仍不 staging）

### Batch 8 增量：PyInstaller / package resource contract

新增 dirty 路径：

```text
AssetManager.spec
requirements-dev.txt
run.py
scripts/check_package_contents.py
tests/core/test_package_contents.py
tests/core/test_packaging_entrypoints.py
```

处理结果：

- 稳定资源仍由 package smoke 强制检查：WebUI SPA、`AssetsManager/i18n/en.json`、`Assets/Themes`、`Plugins`；
- `RuntimeData/Shared` 是首次启动时创建的可写运行时目录，不再作为 PyInstaller datas 或 bundle 必需资源；
- PyInstaller 的 icon source 改用已跟踪的 `Assets/icons`，目标路径保持 `assets/icons` 以兼容 `AssetsManager/app.py`；
- 定向 package tests：`14 passed`。
- CI package-smoke 在资源 checker 后增加 frozen runtime smoke：启动 `AssetManager.exe`，等待 15 秒，非零提前退出失败；健康长驻进程由步骤结束时终止。

### Batch 1 增量：migration spine 历史 DDL

v8/v16/v19 的历史 DDL snapshot 与 checkpoint matrix 已完成定向验证：

```text
75 passed
```

该部分必须和完整 `AssetsManager/core/schema_defs.py`、`AssetsManager/core/db_migrations.py` registry/contract/runner 一起进入连续 Schema spine 批次，不能拆成会让 `_validate_history()` 失败的中间提交。

### 当前提交前门禁

```text
Identity/database + LAN lifecycle/policy：89 passed
Migration matrix：75 passed
Package contract：14 passed
Python full run：2781 passed，7 skipped，1 warning；另有 1 个已知 LAN lifecycle timing flaky，单文件/隔离重跑通过
WebUI：89 files / 585 tests；Playwright：28 passed / 2 skipped；typecheck/build：通过（上一轮基线）
```

当前状态为 `483 entries / 191 tracked modified / 292 untracked / 0 staged`。不得使用 `git add .`、`git add -A`、`git clean` 或 `git reset`；提交前仍需按功能域人工 hunk staging。

---

## 2026-08-09 identity/lifecycle follow-up（仍不 staging）

- Identity prerequisite：matching `.pending` 恢复改为新建临时 marker 后 no-clobber 发布，避免正式 marker 与 pending 共享 inode；定向 `35 passed`；
- Durable persistence：parent-directory fsync/Windows directory flush 仍作为独立后续任务，不应在提交说明中宣称 fully durable；
- LAN lifecycle：该段记录 cleanup-attempt 状态协议实现前的跨线程状态发布窗口；后续已完成显式状态/事件与普通 stop 单次 retry，禁止简单放宽 timeout 或无条件重复 shutdown 的约束仍然保留。

---

## 2026-08-09 LAN lifecycle closure（仍不 staging）

### Batch 5 变更归属

本轮修复只涉及已有 Batch 5 / cross-domain 路径，不应拆成独立的“迁移重做”：

```text
AssetsManager/lan/server.py
 tests/lan/test_server_lifecycle.py
 tests/integration/test_window_lifecycle_lan_failure.py
```

建议的人工 staging 顺序：

1. 先审查 shared session/runtime prerequisite 与 LAN registration hunk；
2. 再审查 `server.py` 的 cleanup attempt state、generation-scoped `_cleanup_retry_used`、startup compatibility marker 和 stop reservation；
3. 同批纳入 LAN lifecycle unit tests 与 window switch/exit integration tests；
4. 最后再处理 LAN routes/auth 与 WebUI/desktop cross-domain hunk，避免把失败重试协议拆成不能运行的中间提交。

本轮没有自动 stage 或 commit。

### 当前门禁

```text
Python full：2789 passed，7 skipped，1 warning
LAN lifecycle：46 passed
Window explicit LAN stop-failure integration：2 passed
Ruff：通过
compileall：通过
WebUI typecheck/build：通过
WebUI baseline：Vitest 89 files / 585 tests；Playwright 28 passed / 2 skipped
```

### 风险状态更新

- LAN cleanup attempt 发布竞态与普通 stop failure retry：已由显式状态/事件协议闭环；不再以放宽 timeout 或无条件重复 shutdown 处理；
- identity unique-temp/no-clobber 与 parent-directory flush：已实现；多级新建祖先目录的递归 flush 仍需独立设计/验证；
- v8/v16/v19 historical DDL 与 package resource contract：已有定向门禁，提交时仍必须保持 schema spine/package hunk 连续；
- 远程 Python 矩阵、clean checkout PyInstaller/Windows smoke：仍为提交前外部门禁。

本轮仍未执行 `git add`、stage、commit、reset 或 clean。


---

## 2026-08-09 identity durable flush closure（仍不 staging）

### Core identity prerequisite staging 约束

新增的目录链 durable flush 仍属于现有 core identity prerequisite，不应拆成独立提交。人工审查顺序：

1. `AssetsManager/core/path_resolver.py` 的 runtime/shared 路径合同；
2. `AssetsManager/core/database.py` 的 marker claim、pending recovery、no-clobber publish 与 directory-chain flush；
3. `tests/core/test_path_resolver.py` 的 formal/pending/collision/durability/ancestor-chain 回归；
4. `tests/core/test_database_metadata.py` 的 open/legacy migration/connection ownership 回归。

### 当前门禁

```text
Identity/database：39 passed
Python full：2790 passed，7 skipped，1 warning
Pyright：0 errors
Ruff / compileall：通过
```

目录链边界已由代码和回归覆盖；剩余提交前门禁仍是远程 Python 矩阵、clean checkout PyInstaller/Windows smoke，以及跨 Batch 的人工 hunk 顺序。没有自动 stage 或 commit。


---

## 2026-08-09 package smoke closure（仍不 staging）

### Batch 8 当前证据

```text
Package contract：15 passed
PyInstaller 6.19.0：bundle build passed
Bundle resource checker：passed
临时 bundle runtime startup：passed
```

本次 smoke 使用系统 Temp 的独立 `distpath/workpath`，没有在项目工作区生成或删除 `build/`、`dist/`；因此它证明当前 dirty 工作区的 package 入口可构建，但不替代 clean checkout / GitHub Windows runner 证据。

`AssetManager.spec` 的 stale hidden import 清理与 `tests/core/test_packaging_entrypoints.py` 防回归测试应和 Batch 8 现有 package resource contract 一起人工 hunk stage；本轮未自动 stage 或 commit。


---

## 2026-08-09 manifest coverage audit（仍不 staging）

以当前 `git status --porcelain=v1 --untracked-files=all` 和本清单逐路径比对：

```text
Current status paths：483
Manifest listed paths：483
Current paths absent from manifest：0
Manifest paths absent from current status：0
Duplicate Batch assignment：0
```

初始 Batch 1–8 之外的路径均已落入 Cross-domain、Exclude 或 Out-of-WebUI-scope 分类；没有发现 package smoke 新增路径遗漏。该核对只读当前状态，不执行 stage、commit、reset 或 clean。


---

## 2026-08-09 deprecated path-helper closure（仍不 staging）

### Core identity prerequisite 归属

`get_library_dir()` 的兼容修复不得拆成新的迁移批次，也不得覆盖前序 identity hunk。人工审查时按以下顺序检查：

1. `AssetsManager/core/database.py`：path-only helper、formal identity marker、legacy migration 与 `open_library()` parity；
2. `tests/core/test_database_metadata.py`：helper 入口的 no-connection、marker、collision、reserved、双目录和 failure 回归；
3. `tests/unit/test_architecture_boundaries.py`：path-only/identity protocol boundary contract。

本轮没有新增 status path，仍为已有 core identity prerequisite / architecture boundary 归属；没有自动 stage 或 commit。

### 本轮门禁

```text
定向 core identity/database + architecture：120 passed
Python full（在新增 helper parity tests 前）：2792 passed，7 skipped，1 warning
Ruff：通过
git diff --check：通过（仅有既有 LF/CRLF 转换提示）
```

新增 parity tests 后的 Python full 将在本轮收尾重新执行；远程 Python 3.12/3.13/3.14、clean checkout PyInstaller/Windows runtime smoke 和人工 hunk staging 仍是提交前任务。


---

## 2026-08-09 full-suite closure after helper parity tests（仍不 staging）

入口级 parity tests 完成后重新执行 Python 全量：

```text
2796 passed，7 skipped，1 warning
```

因此当前 dirty 工作区的 Python 门禁已重新闭环；warning/skip 原因与前述 Windows 环境基线一致。剩余工作不再是本地生产修复，而是远程 Python 3.12/3.13/3.14 证据、clean checkout PyInstaller/Windows runtime smoke 和提交前按功能域人工 hunk staging。


---

## 2026-08-09 package startup dependency closure（仍不 staging）

### Batch 8 / package hunk

本轮发现 `AssetManager.spec` 的 `PySide6.QtSvg` exclude 与 `AssetsManager/core/icons.py` 的直接依赖相冲突，同时 `run.py` 的 tkinter error fallback 与 package excludes 冲突。修复范围保持在既有 Batch 8 package/entrypoint hunk：

- `AssetManager.spec`：保留 QtSvg，移除错误 exclude；
- `run.py`：使用 Qt QMessageBox，不再导入 tkinter；
- `tests/core/test_packaging_entrypoints.py`：增加静态依赖合同。

验证证据：PyInstaller 6.19.0 bundle、resource checker、QtSvg binary presence、offscreen 15 秒 runtime smoke 均通过；没有自动 stage 或 commit。


---

## 2026-08-09 package startup fix full-regression closure（仍不 staging）

QtSvg hidden-import/exclude 修复与 Qt startup error fallback 修复后，Python full 重新通过：`2798 passed, 7 skipped, 1 warning`。Batch 8 package contract、WebUI 89 files / 585 tests、typecheck/build、PyInstaller/resource/runtime smoke 证据均已更新；仍未自动 stage 或 commit。


---

## 2026-08-09 ownership correction after package launcher fix（仍不 staging）

`run.py` 是本轮 package launcher 修复新增的 tracked dirty path，应与 `AssetManager.spec` 和 package contract tests 一起归入 Batch 8。当前 status 基线为 `484 / 192 / 292 / 0`；前文关于“没有新增 status path”的历史描述不再作为当前基线。

---

## 2026-08-09 后续执行记录：非仓库构建与依赖矩阵

### 已完成

- 修复 `AssetManager.spec` 的构建根路径：从 `Path.cwd()` 改为 `Path(SPECPATH).resolve()`；
- 更新 package entrypoint static contract；
- 保持 `requirements-dev.txt` 的 `anyio>=4.0`，闭合 Python 3.12/3.13 AnyIO 插件依赖；
- 非仓库 cwd 实际构建 PyInstaller bundle；
- 运行 bundle resource checker，并核对 WebUI、i18n、Themes、Plugins、QtSvg、QtOpenGL、QtOpenGLWidgets；
- offscreen 启动 smoke 运行 15 秒后受控终止；
- 未执行 stage、commit、reset、clean，也未修改参考源。

### 分批提交规划（仅规划，不自动执行）

1. **Batch 1 — Schema / migrations**：先 stage 数据库 schema/migration 及其直接回归；
2. **Batch 2 — Restore / integrity / maintenance**：数据库完整性、维护、导出、设置适配；
3. **Batch 3 — G17 reconciliation**：索引重建、队列、worker/supervisor、SQLite 生命周期；
4. **Batch 4 — Commerce backend**：favorite/quota/order/seller/shop/storefront 服务与 repository；
5. **Batch 5 — LAN Commerce / auth**：鉴权边界、路由、delivery/download/session 生命周期；
6. **Batch 6 — WebUI shared / Gallery / legacy**：共享 API/hooks/layout/gallery/legacy 页面；
7. **Batch 7 — WebUI Storefront / Seller**：买家 storefront、checkout、orders、delivery、seller dashboard/products/orders/settings；
8. **Batch 8 — CI / docs / tooling / packaging**：CI、requirements-dev、PyInstaller spec/launcher、package contracts、handoff/ownership/commit-plan 文档；
9. **Cross-domain**：Playwright config 只 stage 一次；`git add -p` 处理同时承载多个批次的 tracked 文件；
10. **Exclude / Out-of-WebUI-scope**：不被批次宽泛命令带入，继续保持原有 dirty/untracked 归属。

### 提交前门禁

- Python 3.12/3.13/3.14 矩阵；
- Ruff、compileall、Pyright；
- WebUI Vitest、TypeScript typecheck、build；
- Playwright mock/shell 与真实后端 Commerce 流程；
- clean-checkout PyInstaller build/resource/runtime smoke；
- 最终 `git diff --check` 与按 hunk 的人工审查。

---

## 2026-08-09 最终本地回归闭环

- Python 全量：`2802 passed，7 skipped，1 warning`；
- Ruff、compileall、`git diff --check`：通过；
- package contract：`21 passed`；
- PyInstaller 非仓库 cwd build/resource/runtime smoke：通过；
- manifest：485 status paths / 485 unique ownership paths / 0 missing / 0 duplicate；
- 当前仍不自动 stage/commit；下一阶段是 clean-checkout/远程门禁与人工按 hunk staging。
---

## 2026-08-09 packaging canonical source finalization

- `AssetManager.spec` 的 `EXE(icon=...)` source 统一到 `Assets/icons/icon.ico`；
- package contract：`22 passed`；
- 非仓库 cwd bundle 重新构建，资源 checker 与 offscreen runtime smoke 通过；
- 该项仍与 QtSvg/QtOpenGL/tkinter launcher 修复放在 Batch 8 packaging hunk，暂不自动 stage/commit。
---

## 2026-08-09 final gate count

当前本地最终证据：Python `2803 passed，7 skipped，1 warning`；package contract `22 passed`；非仓库 cwd PyInstaller/resource/runtime smoke 通过。剩余任务仅为远程/clean-checkout 门禁和用户明确授权后的按功能域 hunk staging，不自动提交。
---

## 2026-08-09 跨版本 package 门禁补强

已在 Python 3.12.13 和 3.13.13 临时环境执行当前 package contract，均为 `22 passed`。因此当前剩余门禁不再是本地 Python package contract，而是 clean checkout / Windows GitHub runner 的最终环境复现和后续人工 hunk staging。
---

## 2026-08-09 bundle checker runtime contract

将 `QtSvg`、`QtOpenGL`、`QtOpenGLWidgets` 和 canonical icon 纳入实际 bundle checker；当前 package contract 为 `26 passed`，Python 3.12/3.13 均通过。该项完成后，剩余重点转为 clean-checkout/远程 runner 复现与人工 hunk staging。
---

## 2026-08-09 CI package-smoke foreign-cwd enforcement

将 Windows package-smoke 的构建 cwd 固定到 `RUNNER_TEMP`，并保留绝对 spec/dist/work 路径；package contract 增加 workflow contract，当前为 `27 passed`。这项门禁已从本地手工验证推进到 CI 配置级回归保护。
---

## 2026-08-09 CI-equivalent bundle smoke finalization

完成本机 CI 等价 foreign-cwd PyInstaller build、增强 bundle checker 和 offscreen startup smoke。剩余未闭环项仅是远程/clean-checkout 环境本身的证据，以及用户授权后的分批 staging。
---

## 2026-08-09 package contract completeness and hunk staging audit

当前 package checker 已覆盖三种 i18n、非空 Themes/Plugins、Qt 二进制和 icon；package contract 为 `31 passed`。跨域 tracked 文件的人工 staging 顺序固定为：core identity → shared lifecycle → Batch 2 → Batch 3 → Batch 4 → mainline Gallery → Batch 5 → Batch 8。不得整文件宽泛 staging `bootstrap.py`、`database.py`、`file_operation_service.py`、`library_service.py`、`runtime.py` 或 `.github/workflows/ci.yml`。
---

## 2026-08-09 current full-suite evidence

最新当前工作区 Python 全量为 `2812 passed，7 skipped，1 warning`；package contract 为 `31 passed`，3.12/3.13 均通过。下一步仍是外部 clean-checkout/远程证据与按 hunk staging，不自动提交。
---

## 2026-08-09 WebUI local gate refresh

当前 WebUI 门禁重新闭环：Vitest `89 files / 585 passed`、typecheck/build 通过、migrated shell Playwright `2 passed`。前后端本地验证证据保持一致，剩余仍是远程/clean-checkout 与按 hunk staging。
---

## 2026-08-09 final package after WebUI build

最新 WebUI dist 已重新打入 foreign-cwd PyInstaller bundle，并通过增强 checker 与 15 秒 offscreen startup smoke。当前本地跨层证据闭环；剩余是远程/clean-checkout 和人工 staging。
---

## 2026-08-09 full Playwright gate refresh

完整 Playwright suite 已重新执行：`28 passed / 2 skipped`。skip 仅来自没有 `REAL_COMMERCE_BASE_URL` 的 optional real-backend tests；mock/shell/frontend browser gates 全部通过。
---

## 2026-08-09 clean-like snapshot verification

在排除原工作区缓存/依赖后重建 snapshot，补入 tracked `tests/contracts/lan_public_contracts.json`，完成 npm ci、WebUI build、foreign-cwd PyInstaller、checker 和 runtime smoke。生产 npm 依赖无漏洞；dev 依赖漏洞作为 P2 维护项记录，不在当前迁移批次中自动升级。

---

## 2026-08-09 CI frozen runtime smoke closure（仍不 staging）

为直接覆盖 `QtSvg`/`tkinter` 启动回归，`.github/workflows/ci.yml` 的 Windows package-smoke 在 bundle resource checker 之后新增 frozen runtime smoke：

```text
Start-Process AssetManager.exe（WindowStyle Hidden）
等待 15 秒；若提前以非零退出则失败
若进程健康长驻，步骤结束时只终止本次测试进程
```

当前本地证据：

```text
package/static contract：32 passed
已有 foreign-cwd bundle offscreen runtime：alive-after-15s
远程 GitHub Windows runner：尚未实际执行，仍是外部剩余门禁
```

本轮未执行 stage、commit、reset 或 clean。

---

## 2026-08-09 post-smoke Python full-suite closure（仍不 staging）

在加入 CI frozen runtime smoke static contract 后重新执行当前工作区 Python 全量：

```text
2813 passed，7 skipped，1 warning
package/static contract：32 passed
```

ownership ledger 已与 `485` 个当前 status paths 对齐；远程 GitHub Windows runner 仍未执行，暂不自动 stage/commit。

---

## 2026-08-09 package checker 与 Chromium acceptance 稳定性闭环（仍不 staging）

### Batch 8 package contract

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\scripts\check_package_contents.py` 已将稳定资源合同细化为 file/directory kind contract；新增回归覆盖同名文件/目录替换，防止 `Path.exists()` 造成假阳性。

### Batch 7 / Batch 8 realtime acceptance

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\e2e\test_webui_realtime_acceptance.py` 现在过滤 Chromium blocked ports。此前随机获得 `6566` 时会出现 `ERR_UNSAFE_PORT`，当前真实 acceptance 已恢复：

```text
6 passed
```

### 当前门禁

```text
Package checker：41 passed
Python full：2822 passed，7 skipped，1 warning
Ruff / compileall：通过
```

这两项修改均未触碰 Commerce/迁移业务逻辑，仍属于现有 package/acceptance 测试归属。本轮未执行 stage、commit、reset 或 clean。

---

## 2026-08-09 frozen runtime early-exit contract closure（仍不 staging）

`.github/workflows/ci.yml` 的 frozen runtime smoke 已从“非零提前退出失败”收紧为“任何提前退出失败”。这样可以捕获 EXE 静默 `exit 0` 的启动回归，只有等待 15 秒仍存活才通过。

对应静态 contract 与 package checker 当前均通过：

```text
41 passed
```

本轮仍未执行 stage、commit、reset 或 clean。

---

## 2026-08-09 Python LAN browser CI lane（仍不 staging）

Batch 8 CI/tooling 新增独立 Windows `python-browser-e2e` job，覆盖此前仅本地执行的真实 Python LAN Chromium acceptance：

```text
WebUI npm ci/build
Python LAN/dev dependencies + Playwright
Python Playwright Chromium install
6-test realtime acceptance file
```

不将 Playwright 加入通用 Python matrix，避免普通单元/集成矩阵隐式下载浏览器；该 job 的远程 runner 结果仍是待取得的外部门禁。

---

## 2026-08-09 final current-worktree Python closure（仍不 staging）

当前工作区在 Python LAN browser CI lane 合同加入后重新验证：

```text
Python full：2823 passed，7 skipped，1 warning
Package/CI contract：42 passed
Real Chromium LAN acceptance：6 passed
```

这证明当前本地 dirty worktree 未因 CI 门禁增量产生生产回归；远程 Windows runner 与用户授权后的 hunk staging 仍是后续任务。

---

## 2026-08-09 Qt binary suffix contract closure（仍不 staging）

Batch 8 package checker 进一步收紧 Qt 模块合同：只接受 `.pyd`、`.so`、`.dylib` 平台扩展，拒绝 `.pyi` 等 stub 文件冒充运行时 binary。对应参数化回归已加入 package tests。

当前本地证据：

```text
Package/browser/quality slice：51 passed
Python full：2826 passed，7 skipped，1 warning
```

---

## 2026-08-09 latest clean-like snapshot closure（仍不 staging）

当前最新 dirty worktree 已复制到独立 Temp snapshot（排除 `.git`、权限异常 artifacts、缓存、旧 build/dist、node_modules 和测试产物），并重新完成：

```text
npm ci
WebUI build
foreign-cwd PyInstaller
最新 bundle checker
frozen runtime offscreen 15 秒
```

全部通过。该结果是当前本地 clean-like 证据，不替代真正 GitHub runner，但已排除原工作区 WebUI 依赖缓存与旧构建产物。

---

## 2026-08-09 final hunk ownership audit（仍不 staging）

### 推荐依赖顺序

```text
Batch 1 schema/migration spine
→ Core identity / managed connection
→ Shared LibraryService / LibraryRuntime lifecycle
→ Batch 2 restore/integrity
→ Batch 3 reconciliation/index
→ Batch 4 Commerce projection
→ mainline Gallery/Favorite
→ Batch 5 LAN wiring
→ Batch 7 E2E acceptance
→ Batch 8 package cluster / CI
```

### 关键约束

- `AssetsManager/core/database.py`：schema、identity、connection owner、close lifecycle、Batch 2 metadata migration 混合，不能整文件 stage；
- `AssetsManager/application/bootstrap.py`：imports、Batch 2/3 wiring、Gallery/Favorite、LAN composition 混合，必须 `s/e`；
- `AssetsManager/application/file_operation_service.py`、`AssetsManager/application/library_service.py`：事务 projection、reconciliation、restore、teardown 依赖混合，不能按文件整体归属；
- `AssetsManager/application/runtime.py`：可作为 shared lifecycle prerequisite，但必须先于 Batch 3 worker；
- `webui/playwright.config.ts`：Batch 7/8 cross-domain，只 stage once；
- `tests/e2e/test_webui_realtime_acceptance.py`：LAN preflight/lifecycle 与本轮 blocked-port 修复混合，须按依赖或精细 hunk 处理；
- Batch 8 package cluster必须保持 `AssetManager.spec → checker → tests → CI` 的原子顺序。

本节只记录 staging 配方，不执行任何 stage/commit/reset/clean。

---

## 2026-08-09 WebUI lockfile security closure（仍不 staging）

Batch 8 dependency maintenance 完成最小 lockfile 修复：

```text
webui/package-lock.json
nanoid 3.3.16 → 3.3.18
postcss 8.5.19 → 8.5.26
postcss dependency range → ^3.3.17
```

`package.json` 未改变，snapshot 与当前工作区 `npm audit` 均为 `0 vulnerabilities`。当前 status 基线为 `486` 条；该路径必须与 WebUI package/CI cluster 一起审查，仍未自动 stage/commit。

---

## 2026-08-09 lockfile security closure final verification（仍不 staging）

`webui/package-lock.json` 的最小安全更新已在独立 snapshot 中完成完整验证：

```text
npm ci
npm audit：0 vulnerabilities
Vitest 89 files / 585 passed
typecheck/build
foreign-cwd PyInstaller
bundle checker
post-lock runtime smoke 15 秒
```

当前 status 基线为 `486 = 194 tracked modified + 292 untracked`；package-lock 归 Batch 8 dependency/package cluster，未自动 stage/commit。

---

## 2026-08-09 continuous npm audit gate closure（仍不 staging）

Batch 8 WebUI job 在 `npm ci` 后新增持续依赖门禁：

```text
npm audit --audit-level=moderate
```

它与 `webui/package-lock.json` 的最小安全更新配套，当前 snapshot 实测 `0 vulnerabilities`。对应 package/CI static contract 为 `46 passed`，未自动 stage/commit。

---

## 2026-08-09 continuation deep audit closure（仍不 staging）

提交前审查继续保持以下门禁：

```text
migration/database/compatibility：98 passed
LAN lifecycle/window failure/seller routes：50 passed
package/CI static contract：51 passed
状态基线：486 paths / 194 tracked modified / 292 untracked / 0 staged
```

上述验证不改变 Batch 1–8 的提交顺序，也不授权自动 staging/commit。

---

## 2026-08-09 continuation hunk ownership audit（仍不 staging）

当前 `194` 个 tracked modified 中：

```text
25 个必须 git add -p / patch-edit
169 个在归属层面可整文件 stage 候选
```

25 个必须 hunk stage 的文件：

```text
AssetsManager/application/bootstrap.py
AssetsManager/application/file_operation_service.py
AssetsManager/application/library_service.py
AssetsManager/application/runtime.py
AssetsManager/core/database.py
AssetsManager/core/db_migrations.py
AssetsManager/core/path_resolver.py
AssetsManager/application/context.py
AssetsManager/application/auth_service.py
AssetsManager/repositories/auth_repository.py
AssetsManager/lan/api.py
AssetsManager/lan/server.py
AssetsManager/lan/principal.py
AssetsManager/lan/routes/__init__.py
AssetsManager/lan/routes/_helpers.py
AssetsManager/lan/routes/downloads.py
webui/src/App.tsx
webui/src/api/client.ts
webui/src/types/api.ts
webui/src/stores/AuthContext.tsx
webui/src/stores/RealtimeContext.tsx
webui/playwright.config.ts
tests/e2e/test_webui_realtime_acceptance.py
.github/workflows/ci.yml
README.md
```

依赖顺序保持：

```text
Batch 1 schema/migration
→ shared identity/session/managed connection
→ Batch 2 restore/integrity
→ Batch 3 reconciliation/runtime
→ Batch 6 shared/Favorite/Gallery wiring
→ Batch 4 Commerce backend
→ Batch 5 LAN Commerce/auth
→ Batch 7 E2E
→ Batch 8 package/CI
```

高风险文件禁止整文件 stage；`webui/playwright.config.ts` 只能 stage 一次；`tests/e2e/test_webui_realtime_acceptance.py`、`.github/workflows/ci.yml`、`README.md` 必须按 hunk 归属处理。当前不执行 staging。

---

## 2026-08-09 current-worktree full regression closure（仍不 staging）

当前完整 dirty workspace 最新 Python 证据：

```text
2832 passed，7 skipped，1 warning
Ruff：All checks passed
```

该结果包含当前 package/launcher/CI 增量；没有改变 486 paths、194 tracked modified、292 untracked、0 staged 的状态基线。
