# G16 TagRepository / TagService session binding — 深度审查报告

**日期：** 2026-08-06  
**工作区：** `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`  
**基线：** `master` / `fbf3403 Enforce schema object integrity for v6`  
**状态：** G16 后端与桌面核心已完成本轮收敛；工作区仍处于多会话混合 dirty，未 staging、未 commit。

## 1. 本轮目标

本轮从 G16 的唯一全量失败开始，完成以下收敛：

1. 修复真实 `LibrarySession` 下 sibling runtime service 的 connection-provider identity 丢失；
2. 继续深审 TagRepository / TagService / TagStore 的 ownership、事务、事件和关闭生命周期；
3. 不放宽 strict contract，不回滚其他并行会话，不修改保护域：
   - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\**`
   - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\e2e\**`
   - `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tmp\**`

## 2. G16 已确认/完成内容

### 2.1 Provider identity 与 strict session

`SearchService` 与 `ThumbnailService` 在验证 provider 属于真实 session 后，保留运行时传入的**同一个 provider 对象**，不再重新读取新的 bound-method 对象。Python 每次访问 `session.connection_for` 可能得到不同的对象；保留传入对象解决了：

- runtime sibling service 的 provider identity 断裂；
- LAN server 构造时的 no-rebind 检查失败；
- 多 LibrarySession 之间 provider capability 混淆。

同时保留 strict root/session/connection 校验，未把该修复降级成 raw compatibility。

### 2.2 Thumbnail strict cache metadata hardening

`ThumbnailService` 的 strict session 路径现在会：

- 校验 requested root 与 captured root identity 一致；
- 调用 retained provider 后要求返回值是 session canonical connection object；
- 使用 `DatabaseManager.require_managed_connection_owner()`；
- provider 被替换为 unmanaged connection 时 fail-closed。

增加了回归测试，覆盖 provider 被篡改为 unmanaged connection 的情况。

### 2.3 TagRepository / TagService

本轮保留并继续强化了以下不变量：

- `TagRepository.for_session(session)` 只接受真实 `LibrarySession`；
- captured `RootIdentity`、managed connection owner、root containment；
- same-session 幂等、foreign-session 拒绝、raw operation 后禁止 late bind；
- bound writes 使用 savepoint，并保留 caller outer transaction；
- `migrate_path(old == new)` no-op，禁止 subtree overlap；
- `delete_tag()` 同步清理 `tag_metadata`；
- `TagService.for_session(fake)` 明确拒绝；
- `InfoController` 在真实 session 下默认使用 session-bound `TagService`，真实 `TagService` 注入时校验 session ownership；
- eventful tag mutation 将 clean-transaction admission 下沉到 repository write lock 内，降低 outer transaction TOCTOU 窗口。

### 2.4 文件投影与事件

- session-bound 文件移动在 filesystem mutation 前拒绝 caller outer transaction，避免后续 projection/index commit 意外提交无关事务；
- `migrate_path_metadata()` 不再无条件提交调用方已有的 outer transaction；
- 删除投影清理 tag 行后发布 session-scoped `TagCatalogChanged`，避免 TagTree/catalog 计数长期陈旧；
- 增加 move outer-transaction、metadata migration transaction preservation、delete tag catalog invalidation 回归测试。

### 2.5 未跟踪 commerce 工作线的静态门禁补丁

工作区同时存在并行未跟踪 commerce 文件。为恢复全量 pyright 门禁，做了不改变业务语义的类型安全修复：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\order_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_service.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\shop.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\shop_repository.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\order_repository.py`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\quota_repository.py`

主要是 None/rowid 防护、SQLite row 类型标注、请求参数缺失校验和 principal optional narrowing。

## 3. 验证结果

### 3.1 Python

```text
python -m pytest -q --tb=short tests/core tests/unit tests/integration tests/desktop tests/lan
2411 passed, 4 skipped, 1 warning, 1 failed
```

唯一失败不是 G16 Python 核心逻辑，而是既有架构门禁扫描到并行未跟踪 WebUI commerce 类型，见第 4 节。

本轮定向验证：

```text
G16 / controller / file-operation / database metadata focused set: 47 passed
file-operation + metadata + tag focused set: 92 passed
commerce repository tests: 7 passed
thumbnail provider hardening tests: 28 passed
```

Windows 当前用户无 symlink 权限导致的 4 个 skip 保持不变（WinError 1314）。zipfile duplicate-name warning 为既有 warning。

### 3.2 静态门禁

```text
ruff check AssetsManager tests       PASS
pyright                              0 errors
 git diff --check -- AssetsManager tests PASS
```

全量 `git diff --check` 仍不能作为本混合工作区的统一门禁，因为保护域并行修改含 trailing whitespace / extra blank line；未修改这些文件。

### 3.3 WebUI

```text
npm test              PASS — 63 test files, 452 tests
npm run typecheck     PASS
npm run build         PASS
```

### 3.4 Chromium E2E

```text
5 passed, 1 failed
```

失败测试：

```text
tests/e2e/test_webui_realtime_acceptance.py::test_browser_logout_redirects_and_closes_realtime
```

该测试按 `get_by_role("button", name="Logout")` 查找。当前 LAN browse 页面实际由并行未跟踪的 `webui/src/components/layout/AppHeader.tsx` 提供菜单，Logout 元素声明为 `role="menuitem"`，因此 protected E2E locator 等待超时。未修改 `webui/**` 或 `tests/e2e/**`。

## 4. 当前明确阻塞项（不可宣称全工作区绿）

### 4.1 P1：WebUI commerce 类型破坏 bearer-token 架构门禁

失败位置：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_architecture_boundaries.py:710
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\types\api.ts:450
```

当前未跟踪/并行 commerce 类型包含：

```ts
delivery_token: string | null;
```

现有架构测试扫描整个 `api.ts`，要求浏览器 auth contract 不出现 `token:`。即使该字段属于 delivery credential 而不是 LAN auth，它仍是 bearer-like secret，不应出现在管理员订单投影或共享 auth type 文件中。

**后续处理建议（由 WebUI/commerce 工作线负责）：**

- 优先从 `ShopOrder` 管理列表投影移除原始 delivery token；
- 使用一次性 URL/显式下载操作返回短生命周期结果，不要在普通订单列表缓存 bearer secret；
- 将非认证的 delivery DTO 与 auth 类型彻底分离；
- 处理后重新跑 architecture boundary、WebUI contract、E2E。

本轮不修改保护域，不通过修改测试来掩盖该风险。

### 4.2 P1：E2E Logout role contract 不一致

当前并行未跟踪 `AppHeader` 使用 ARIA menu semantics；protected E2E 按 native button role 查找 Logout。需要在 WebUI 工作线统一：

- 要么使用原生 button role（保持 protected E2E contract）；
- 要么正式更新受保护 E2E contract 与 accessibility 断言。

不能让 build 后页面和 acceptance test 使用两套可访问性角色语义。

### 4.3 Global diff-check 保护域阻塞

`git diff --check` 仍被以下保护域修改阻塞：

- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\i18n\en.ts`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\i18n\ja.ts`
- `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\i18n\zh.ts`

本轮只使用了 `git diff --check -- AssetsManager tests`，没有清理或覆盖并行 WebUI 修改。

## 5. G16 尚未完全关闭的残余风险

以下问题已识别但不应伪装成已完成：

1. Tag event 的“读取旧状态 → mutation → 再读取新状态 → publish”仍跨多个 repository operation；repository-level clean admission 已降低风险，但要完全消除 TOCTOU，需要原子 command / outbox。
2. Runtime close 顺序仍需继续验证 event router drain 与 in-flight session mutation 的 commit-after-event 时序。
3. `TagStore` 的 symlink/junction resolve cache 需要在 reparse-point 变化或 move/delete 时失效。
4. 文件系统 move 与多 projection DB migration 仍不是真正的跨系统原子事务；当前策略是对 outer transaction fail-closed，并保留 DB 事务边界。
5. raw compatibility 继续存在，必须明确区分：raw 对象不提供 session lease，不得借用真实 session managed connection 而伪装成 canonical。

## 6. 后续长期任务规划

### G17 — AssetIndexRepository / AssetIndexService

按以下顺序执行：

1. 建立 `AssetIndexRepository.for_session()` 与真实 `LibrarySession` marker、captured root、managed owner、operation lease；
2. 收口 `AssetIndexService` 为 session-scoped service，移除容器级 singleton 跨 session 复用；
3. 删除 `SearchService` 中直接构造 `AssetIndexRepository` 的路径，改用 retained strict service/repository；
4. 所有 index read/write 统一 root containment，删除 SQL 增加 root predicate；
5. `replace_parent_entries()` / tree indexing 改为显式 savepoint/commit contract，避免逐目录 commit；
6. force scan 增加 generation/version admission，防止旧扫描快照覆盖新结果；
7. 与 FileOperationService move/delete projection cleanup 统一 transaction boundary；
8. 增加跨 session、foreign root、close race、失败回滚、并发旧快照测试。

### G18 — PluginMetadataService

必须先锁定 contract 再实现：

1. 保留 `PluginMetadataRepository(raw_conn)` legacy path，但新增真实 session canonical factory；
2. 引入 `PluginMetadataService.for_session()`，让 `InfoController` 不再直接持有 repository；
3. 明确 read/cache-miss 是否允许 parse+write；禁止隐式跨多个独立 commit 产生 partial state；
4. upsert 改为 replace semantics，清理 parser 已删除的 stale fields；
5. move/delete projection 覆盖 `plugin_metadata` subtree；
6. Windows path 复用统一 descendant/LIKE escape helper；
7. plugin unload/disable 与 in-flight parse 引入 generation/lease contract；
8. 定义 commit-after-event/cache invalidation 语义，再接入 desktop/LAN/WebUI；
9. 增加 lifecycle、outer transaction、stale fields、move/delete、Windows path、plugin concurrency 测试。

## 7. 结论

G16 的后端/桌面核心 session-binding 方向已经通过全量 Python 逻辑回归、静态门禁和定向事务测试；但**整个工作区尚未完全一致，也不能宣称项目完成**。当前首要阻塞来自并行未跟踪 WebUI commerce/gallery 工作线，且属于保护域，必须由该工作线先处理 `delivery_token` 架构门禁和 Logout role contract。

本报告不执行 staging/commit，不回滚、不删除任何其他会话产物。
