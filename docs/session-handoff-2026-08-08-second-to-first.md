# AssetsManager WebUI 迁移会话交接文档

- **文档用途**：将第二会话的工作状态、修复结果、验证结果和后续任务交接回第一会话。
- **交接日期**：2026-08-08
- **目标项目**：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
- **参考新 WebUI**：`D:\~Vibe-Coding\Projects\AssetsManager_New_WebUI`
- **当前工作区状态**：保留所有已有 dirty/untracked 修改；未执行 `git reset`、`git clean`、`git add`、`git commit`。

---

## 一、总目标

将 `AssetsManager_New_WebUI` 的功能和设计迁移到 `AssetsManager_old-bak`，同时满足：

1. 保留旧 WebUI 的历史路由和 API 兼容性；
2. 保留旧 `/store/*`、`/app/*` 和 Token Delivery 页面；
3. 补齐 Storefront、Cart、Wishlist、Checkout、Seller Workspace 等前后端能力；
4. 兼容旧 LAN 鉴权和新的 Seller Session/Receipt/Delivery 权限边界；
5. 使用真实后端、真实数据库、真实商品文件完成浏览器端商业流程验收。

---

## 二、已完成的前端迁移

### Storefront

已完成：

- Storefront 首页；
- 商品列表；
- 商品详情；
- Gallery 首页；
- Gallery Collection；
- Favorites；
- Cart；
- Wishlist；
- Checkout；
- Checkout Group；
- Buyer Orders；
- Receipt Recovery；
- Delivery 页面；
- 下载配额状态展示；
- 新 Header；
- Workspace；
- Command Palette；
- 桌面/移动响应式布局；
- 路由级懒加载和拆包。

主要目录：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\storefront
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\api
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks
```

### Seller Workspace

已完成：

- Seller Dashboard；
- Seller Products；
- 商品创建；
- 商品编辑；
- 商品启用、归档、恢复；
- 商品删除确认；
- Seller Orders；
- Seller Fulfill；
- Delivery Link；
- Delivery Link Recovery；
- Seller Settings；
- Seller Profile；
- Gallery Cover；
- Gallery 图片路径编辑；
- Seller 错误 Toast 和状态反馈。

主要文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\SellerDashboardPage.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\SellerProductsPage.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\SellerOrdersPage.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\SellerSettingsPage.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\storefront\SellerGalleryEditor.tsx
```

### 兼容路由

当前保留或适配：

```text
/storefront
/storefront/products
/storefront/product/:id
/storefront/cart
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
/seller/orders
/seller/settings

/app
/app/items
/app/orders
```

---

## 三、已完成的 Commerce 后端

### 商品和销售授权

已完成：

- 商品创建、查询、更新、删除；
- active/draft/archived 生命周期；
- Cover 和 Gallery Paths；
- 商品路径规范化；
- 授权销售根目录；
- 路径越界保护；
- Buyer DTO / Seller DTO 隔离；
- 商品状态和错误合同。

主要文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_authorization.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\shop_repository.py
```

### Cart / Wishlist

已完成：

- Guest Cart；
- 登录用户 Cart；
- Guest -> User 合并；
- Cart 版本控制；
- 数量更新和删除；
- Wishlist；
- Guest Wishlist；
- User Wishlist；
- Wishlist 合并；
- 价格快照；
- 价格变化检测；
- Checkout 前价格确认；
- Checkout Idempotency-Key；
- Checkout Group；
- Cart 行转换为兼容订单；
- 订单元数据记录 `cart_id`、`cart_line_id`、`checkout_group_id`。

主要文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\shop_buyer_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\shop_buyer_repository.py
```

### Order / Receipt / Delivery

已完成：

```text
pending -> confirmed -> fulfilled
pending -> revoked
confirmed -> revoked
```

并已完成：

- 订单创建；
- Receipt Cookie；
- Receipt Recovery；
- HttpOnly Receipt Cookie；
- Seller Fulfill；
- Delivery Token；
- Delivery Token Rotation；
- Delivery Attempt 幂等；
- Download Quota；
- Token 过期；
- 订单所有者隔离；
- 交付路径保护。

主要文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\order_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\repositories\order_repository.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\shop.py
```

---

## 四、LAN 鉴权边界

曾发现：LAN 开启密码或用户鉴权后，Storefront、Guest Cart、Seller Login 请求会被全局鉴权中间件提前拦截为 `401`。

已修复：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\server.py
```

公共路径包括：

```text
/storefront
/store
/seller
/app
/api/shop/*
/api/quota
/api/auth/seller-status
/api/auth/seller-login
/api/auth/seller-logout
```

敏感操作仍由路由级保护：

- Seller Session；
- `seller_required`；
- `require_seller`；
- Commerce Feature Flag；
- Receipt Cookie；
- Delivery Token；
- Buyer Owner；
- User Principal。

回归测试：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\lan\test_public_commerce_auth.py
```

---

## 五、本第二会话新增修复

### 1. 修复空买家信息 Checkout 失败

问题：当请求中 `buyer_name` 或 `buyer_email` 为 JSON `null`，后端会将 `None` 转换成字符串 `"None"`，导致邮箱校验失败。

修复：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\order_service.py
```

现在以下情况都可以正常 Checkout：

- 字段省略；
- 字段为空字符串；
- 字段为 `null`。

新增测试：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\unit\test_commerce_services.py
```

### 2. 修复非图片商品破损缩略图

问题：商品主文件可能是 `.txt`、`.zip`、`.psd` 等非图片资源，但前端会直接把商品路径请求为 Thumbnail，产生无意义的 `404`。

修复文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks\useCommerce.ts
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\storefront\ProductCard.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\pages\StorefrontProductPage.tsx
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\components\storefront\Storefront.css
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\src\hooks\useCommerce.test.ts
```

现在：

- 只有支持的图片扩展名请求 `/api/thumbnails`；
- 非图片商品显示占位图；
- 非图片商品配置 `cover_path` 时仍使用 Cover；
- 商品详情页没有图片时不会打开空 ImageViewer。

---

## 六、真实后端浏览器验收

使用隔离临时库和真实文件完成了完整链路：

```text
真实商品
  -> Storefront 商品列表
  -> 商品详情
  -> Add to Cart
  -> Guest Cart
  -> Checkout
  -> HttpOnly Receipt Cookie
  -> Buyer Confirm
  -> Seller Login
  -> Seller Fulfill
  -> Buyer Order Polling
  -> Receipt Delivery
  -> 实际文件下载
```

实际下载内容已经验证。

验证输出：

```text
REAL_E2E_SUCCESS
```

附加安全验证：

- 未登录 Seller API 返回 `403`；
- Receipt 在不同浏览器上下文之间隔离；
- 未授权订单不会被枚举；
- 未授权销售根目录返回 `403`；
- Seller Session 不会被误当成买家身份；
- Guest Cart 不会跨浏览器共享。

临时服务器、临时数据库、临时商品文件、测试账号、临时脚本均已清理。

---

## 七、最终验证结果

### Python 全量回归

```text
2703 passed
7 skipped
1 warning
```

### Commerce 定向回归

```text
104 passed
```

### WebUI TypeScript

```text
npm run typecheck
通过
```

### WebUI Vitest

```text
80 个测试文件通过
528 个测试通过
```

### WebUI Build

```text
npm run build
通过
```

构建产物：

```text
主 Bundle：439.23 KB
gzip：130.26 KB
```

### Playwright Mock/Shell E2E

```text
4 passed
```

### 代码检查

```text
git diff --check
通过
```

---

## 八、当前工作区注意事项

当前工作区仍然包含第一会话及此前会话遗留的大量 dirty/untracked 修改。

第二会话没有执行：

```text
git reset
git reset --hard
git clean
git clean -fd
git add
git commit
```

合并回第一会话时不要为了“整理工作区”而直接删除未跟踪文件。

建议先执行：

```powershell
git status --short --untracked-files=all
```

并按功能域检查文件归属。

注意：部分迁移文件当前是新增未跟踪文件，因此不能只依赖普通 `git diff` 查看完整改动。

---

## 九、已知非阻断项和后续建议

### 非阻断项

在 LAN 开启用户鉴权、浏览器未携带 `lan_token` 时，前端会探测：

```text
/api/auth/me
```

该请求会产生一次预期的 `401` 控制台日志，但不会影响：

- Storefront；
- Guest Cart；
- Seller Login；
- Seller Workspace；
- Receipt Delivery。

后续如需要“浏览器控制台零噪声”，可以优化 `AuthContext` 的 Guest 身份探测策略。

### 推荐后续工作

1. 将真实 Commerce E2E 从临时验收脚本提升为正式的可选测试：

   ```text
   D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\e2e\commerce-real-backend.spec.ts
   ```

2. 按功能域拆分和整理未提交修改；
3. 分批 stage 和 commit；
4. 后续再考虑真实支付网关；
5. 后续再考虑正式多商品订单模型 `shop_order_items`；
6. 后续再考虑正式商品图片表 `shop_item_images`；
7. 增加退款、部分退款和更细粒度 Seller 权限。

---

# 第一会话交接提示词

请继续处理当前工作区，不要重新开始迁移，也不要回滚已有改动。

当前目标是将新 WebUI：

```text
D:\~Vibe-Coding\Projects\AssetsManager_New_WebUI
```

继续合并到旧项目：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak
```

请先完整读取并遵循以下交接文档：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\docs\session-handoff-2026-08-08-second-to-first.md
```

重要约束：

1. 不要执行 `git reset`、`git reset --hard`、`git clean` 或 `git clean -fd`；
2. 不要删除已有 dirty/untracked 修改；
3. 不要直接覆盖第一会话已经完成的迁移代码；
4. 修改前先查看 `git status --short --untracked-files=all`；
5. 继续在 `D:\~Vibe-Coding\Projects\AssetsManager_old-bak` 内工作；
6. `D:\~Vibe-Coding\Projects\AssetsManager_New_WebUI` 只作为参考源，不要直接修改；
7. 如果要提交代码，先按功能域整理变更，再分批 stage/commit。

第二会话已经完成：

- Storefront、Cart、Wishlist、Checkout、Checkout Group；
- Buyer Orders、Receipt Recovery、Delivery；
- Seller Dashboard、Products、Orders、Settings；
- Seller Session、Receipt Cookie、Delivery Token、Download Quota；
- Guest Cart/Wishlist 和 Guest -> User 合并；
- LAN Commerce 公共鉴权边界；
- 空买家信息 Checkout 修复；
- 非图片商品 Thumbnail 破损修复；
- 真实无 Mock 购买、确认、履约、下载链路验收。

验证结果：

```text
Python：2703 passed，7 skipped，1 warning
Commerce 定向：104 passed
WebUI：80 个测试文件通过，528 个测试通过
TypeScript typecheck：通过
WebUI build：通过
Playwright Mock/Shell：4 passed
真实后端浏览器 Commerce 流程：REAL_E2E_SUCCESS
```

请下一步：

1. 读取当前工作区状态；
2. 对比交接文档中列出的关键文件；
3. 进行一次变更归属审查；
4. 确认迁移代码没有被回滚或覆盖；
5. 如发现问题，先执行最小修复；
6. 然后规划按功能域分批提交的方案；
7. 暂时不要自动 commit，除非我明确要求提交。

---

## 当前一致性审查补充（2026-08-08）

本交接文档前文的 `Playwright Mock/Shell：4 passed` 是交接时历史快照。后续 Seller Mock E2E 已纳入默认 CI；当前默认 job 运行全部 5 个 spec，共发现 30 个测试，本机结果为 `28 passed, 2 skipped`；其中 Buyer + Seller + Shell Mock/Shell 子集为 12 个测试。

本轮在 Windows / Python 3.14 本机重新运行完整 Python 测试集，结果为：`2760 passed, 7 skipped, 1 warning`。该结果是本机复核证据，不替代远程 Python 3.12/3.13 矩阵。
本轮 WebUI Vitest 全量回归为：`89 个测试文件通过，585 个测试通过`；Playwright 全量为 `28 passed, 2 skipped`（共发现 30 个测试）。

CI hygiene job 已使用 `fetch-depth: 0`，确保 PR base / push-before SHA 在 `git diff --check` 前可用；push 路径使用 before/current 两树比较，缺失 before 或 root push 使用 root-safe `git show --check` fallback。

当前仍保持：479 个 status entries、187 个 tracked modified、292 个 untracked、0 个 staged；没有执行 `git add`、stage、commit、reset 或 clean。


---

## 当前深度审查增量（2026-08-08）

本轮未改变既有迁移目标，只做了五个最小硬化：

- `/api/shop/**` 保持公开 guest 行为，同时解析有效 LAN user principal，使用户级 Buyer cart/wishlist/merge 真正可达；
- `LibraryService.close_session()` / `close()` 完成后统一失效 retained core-store liveness；
- `ShopBuyerProvider` 只在 Commerce feature route subtree 挂载，非 Commerce 页面不再自动请求 Commerce buyer API。
- `SellerAuthService.authenticate()` 每次使用 `seller_session` 都重新读取当前用户；管理员停用或降权后立即拒绝并移除旧 bearer，新增 Seller session 回归测试。
- identity marker 已发布后，legacy/thumb 预备失败不再删除正式 marker；新增 migration/preparation failure marker-retention 回归。

验证：Python 全量 `2760 passed, 7 skipped, 1 warning`；Seller/Commerce regression subset + architecture boundary `39 passed`；identity/database targeted `29 passed`；Commerce/LAN + core session `53 passed`；App route `14 passed`；WebUI Vitest `89 个测试文件 / 585 个测试通过`；Playwright `28 passed, 2 skipped`；WebUI typecheck/build 通过。Seller feature-toggle/event-driven mass revocation、identity `.pending` recovery 和历史 migration DDL 边界仍是后续安全/生命周期任务。仍未执行 stage/commit/reset/clean。

---

## 当前连续深度审查增量（2026-08-09）

本轮继续推进了两个高风险边界：

- identity `.pending` 现在使用 per-slot crash-releasing OS lock；同 identity 的匹配 pending 可恢复，collision/malformed pending fail-closed；
- LAN shutdown 入口批量撤销 Seller sessions，覆盖 cached 与 scoped/injected SellerAuthService；Seller disabled 的 status/logout 在不创建 Commerce service 的前提下，也会尽力撤销已经缓存的 SellerAuthService sessions；
- AppSettings 对 effective Commerce/Seller toggle 维护 monotonic generation，旧 Seller session 即使在关闭窗口内未被使用，重新开启后也不会恢复。

本轮验证：

```text
Python 全量：2767 passed，7 skipped，1 warning
identity/database targeted：31 passed
Seller/Commerce regression：39 passed
LAN shutdown-focused regressions：5 passed
LAN server lifecycle full file：40 passed + 1 known pre-existing timing flaky（同一失败用例 isolated rerun 1 passed）
WebUI Vitest：89 个测试文件，585 个测试通过（上一轮已验证）
Playwright：28 passed，2 skipped（30 tests discovered，上一轮已验证）
Ruff affected files：通过
```

当前仍未执行 `git add`、stage、commit、reset 或 clean。

尚未完全关闭的风险：Seller stop/start 与 startup-failure 的全部终止路径；正式 marker 的 unique-temp no-clobber 发布和目录 durable fsync；历史 migration DDL 冻结；deprecated `get_library_dir()` 兼容边界。

---

## 当前身份协议细化与生命周期竞态记录（2026-08-09）

在上一节 no-clobber 实现基础上又完成了一项最小修正：matching 固定 `.identity.pending` 不再直接 hard-link 成正式 marker；现在会读取并验证 pending 后，用本次调用创建的唯一临时 marker 发布正式 marker，避免 formal marker 与 pending 共享 inode，后续 pending 被重写时不会改变正式 identity。

新增回归：

```text
matching pending recovery does not alias formal marker
```

Identity/database 定向测试当前为 `35 passed`。

### 生命周期 timing flaky 的工程结论

一次完整 Python 回归曾在：

```text
tests/lan/test_server_lifecycle.py::test_startup_exception_retains_owner_thread_until_cleanup_retry
```

触发 `future.result(timeout=8)` 的已知时序失败；该用例单独重跑、生命周期文件 `43 passed`，以及 8 个并发隔离进程均通过，随后一次全量回归也达到：

```text
2782 passed，7 skipped，1 warning
```

专项审查确认这不是简单的 asyncio 死锁，而是 startup-owner cleanup future 的完成状态与 `stop()` 超时检查之间存在发布窗口。后续增量已增加显式 cleanup-attempt 状态/事件与 generation-scoped 单次 retry；当前保留不重叠 shutdown、不无限 retry 的约束。

### 历史记录：当时仍明确未完成的持久化边界（后续增量已修正）

- parent-directory durable fsync / Windows directory handle flush 已在后续增量实现；仍需评估同一调用中新建多级祖先目录的递归 flush 语义；
- marker 的本地恶意 TOCTOU、超大/空 marker 细分错误分类仍属于后续加固项；
- 远程 Python 3.12/3.13、clean checkout PyInstaller 实际构建和 Windows runtime smoke 仍需独立证据。

本轮仍未执行 `git add`、stage、commit、reset 或 clean。

---

## 当前连续审查闭环（2026-08-09，仍不 staging）

### LAN 生命周期普通 stop 失败重试

本轮修复了 `AssetsManager/lan/server.py` 的显式 cleanup protocol：

- 每个 lifecycle generation 使用通用 `_cleanup_retry_used`，而不是只识别 startup cleanup failure；
- 普通 stop 首次失败仍立即向调用方传播，后续生命周期调用允许一次 retry；
- retry 失败后不再无限提交 shutdown；
- startup-owner cleanup 的 `_startup_cleanup_retry_used` 兼容标记保留；
- cleanup attempt 仍由单 owner 发布，保留 bounded wait、线程/loop handle 与不重叠 shutdown 保护。

新增 `tests/lan/test_server_lifecycle.py` 回归，覆盖普通 stop 首次失败、第二次成功，以及第二次仍失败时第三次不再提交；窗口真实场景由 `tests/integration/test_window_lifecycle_lan_failure.py` 验证。

### Identity marker durable 状态

`AssetsManager/core/database.py` 已完成 parent-directory durable flush：POSIX 使用目录 fd `fsync()`，Windows 使用 `CreateFileW(FILE_FLAG_BACKUP_SEMANTICS)` + `FlushFileBuffers()`。目录 flush 失败时保留已经 no-clobber 发布的正式 marker 并 fail-closed；若 `RuntimeData/Shared` 与其祖先目录在同一调用中刚刚创建，仍需后续评估是否递归 flush 全部新建祖先目录。

### 本轮验证

```text
Python 全量：2789 passed，7 skipped，1 warning
LAN lifecycle：46 passed
窗口显式 LAN stop-failure 集成：2 passed
Ruff：All checks passed
compileall：通过
WebUI typecheck：通过
WebUI build：通过
```

本轮未修改 `AssetsManager_New_WebUI`，未执行 `git add`、stage、commit、reset 或 clean。当前状态仍为 `483 entries / 191 tracked modified / 292 untracked / 0 staged`；状态输出中的历史 `.pytest-tmp/` 与 `tmp/pytest-*` 权限告警不作为清理目标。

### 剩余门禁

- 远程 Python 3.12/3.13 矩阵；
- clean checkout 下的 PyInstaller 实际构建与 Windows runtime smoke；
- marker 在同一调用中新建多级祖先目录时的递归 durable flush 语义；
- 按 Batch 1–8 进行人工 hunk 归属审查后再分批 stage/commit。


---

## Identity durable flush closure（2026-08-09，仍不 staging）

本轮继续关闭前文留下的目录持久化边界：

- `AssetsManager/core/database.py` 现在显式记录本次调用新建的 `RuntimeData` / `Shared` 祖先目录；
- marker 通过 no-clobber link 发布后，按 marker 所在目录 → 新建祖先目录 → 最上层已有父目录的顺序执行 durable flush；
- 任意目录 flush 失败时，已发布 formal marker 保留，调用 fail-closed，不回滚删除 marker；
- 目录链已有路径不会被重复创建或扩大 flush 范围；并发创建时只把本调用实际创建的目录纳入祖先链。

新增回归：

```text
test_database_identity_flushes_new_directory_ancestors
```

最终验证更新：

```text
Identity/database 定向：39 passed
Python 全量：2790 passed，7 skipped，1 warning
Pyright：0 errors
Ruff / compileall：通过
```

当前剩余重点缩减为远程 Python 3.12/3.13、clean checkout PyInstaller/Windows runtime smoke，以及提交前人工 hunk 归属审查；本轮仍未执行 `git add`、stage、commit、reset 或 clean。


---

## Package smoke closure（2026-08-09，仍不 staging）

本轮在不创建工作区 `build/` / `dist/`、不删除已有 dirty/untracked 文件的前提下完成本机 Windows package smoke：

```text
PyInstaller：6.19.0
Package contract：15 passed
Bundle resource checker：通过
临时 bundle runtime startup：成功（QT_QPA_PLATFORM=offscreen）
```

同时清理了 `AssetManager.spec` 中两个已不存在的 hidden imports：

```text
 aiohttp.protocol
 AssetsManager.application.thumbnail_repository
```

并在 `tests/core/test_packaging_entrypoints.py` 增加防回归合同。PyInstaller 临时构建目录位于系统 Temp，不属于当前项目工作区；clean checkout 构建、GitHub Windows runner 和远程 Python 3.12/3.13 仍需独立证据。


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

## Deprecated `get_library_dir()` boundary closure（2026-08-09，仍不 staging）

本轮关闭 deprecated path helper 与新 RuntimeData identity/migration protocol 之间的兼容边界：

- `AssetsManager/core/database.py::get_library_dir()` 仍保持 path-only 语义，不构造 `DatabaseManager`、不打开 SQLite connection、不执行 schema/migration；
- helper 现在先调用 canonical `DatabaseManager._ensure_library_data_identity()`，再处理 legacy directory migration，最后准备 hashed data directory；
- legacy migration、reserved RuntimeData directory、legacy+hashed 双目录冲突、migration failure 均与 `open_library()` 保持 fail-closed parity；formal marker 在后续准备失败时保留；
- `tests/core/test_database_metadata.py` 增加 helper 入口 identity marker、legacy migration、formal collision、reserved directory、双目录冲突、migration failure 和无数据库连接回归；
- `tests/unit/test_architecture_boundaries.py` 明确要求 helper 继续保持 path-only，同时不得绕过 identity/migration primitive。

定向验证：

```text
Core identity/database + architecture：120 passed
Ruff：通过
git diff --check：通过（仅保留现有 LF/CRLF 转换提示）
```

本轮没有新增 status path；`AssetsManager/core/database.py`、`tests/core/test_database_metadata.py`、`tests/unit/test_architecture_boundaries.py` 继续沿用既有 core identity / architecture prerequisite 归属，不新增 Batch。

提交前剩余门禁仍为：远程 Python 3.12/3.13/3.14 CI 证据、clean checkout 下 PyInstaller/Windows runtime smoke，以及 Batch 1–8 的人工 hunk 归属审查后分批 stage/commit。


---

## get_library_dir parity and full-suite closure（2026-08-09，仍不 staging）

入口级 parity tests 已补齐 formal marker collision、reserved legacy directory、legacy+hashed 双目录冲突、migration failure 保留 marker，以及更强的 no-connection negative assertions。最终本机 Windows Python 全量验证：

```text
2796 passed，7 skipped，1 warning
```

warning 为既有 zipfile duplicate archive entry；7 个 skip 为当前 Windows symlink privilege / process termination 条件，不是本轮新增失败。当前仍未执行 `git add`、stage、commit、reset 或 clean。


---

## Package startup regression closure: QtSvg / tkinter fallback（2026-08-09，仍不 staging）

本轮 package smoke 发现并修复了一个真实的打包启动缺陷：

- `AssetsManager/core/icons.py` 直接依赖 `PySide6.QtSvg.QSvgRenderer`，但 `D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetManager.spec` 同时把 `PySide6.QtSvg` 列入 excludes，导致 frozen runtime 可能出现 `ModuleNotFoundError: No module named 'PySide6.QtSvg'`；
- `run.py` 的失败提示路径依赖被 bundle 明确排除的 tkinter，导致首个启动异常又被 `ModuleNotFoundError: No module named 'tkinter'` 覆盖；
- 已将 `PySide6.QtSvg` 加入 hidden imports 并从 excludes 移除；
- 已将 `run.py` 的启动错误提示改为使用 bundled Qt `QMessageBox`，Qt 初始化失败时保留 stderr fallback；
- `tests/core/test_packaging_entrypoints.py` 增加防回归合同。

验证：

```text
Packaging/content + icon contract：20 passed
Packaging entrypoint contract：17 passed
PyInstaller 6.19.0：成功
Bundle resource checker：通过
Bundle 内存在 PySide6/QtSvg.pyd
QT_QPA_PLATFORM=offscreen frozen runtime：保持运行 15 秒，无立即启动失败；随后仅终止 smoke 进程
```

本次构建使用系统 Temp 独立 workpath/distpath，没有在项目工作区创建或删除 build/dist。


---

## Package startup fix full-regression closure（2026-08-09，仍不 staging）

QtSvg/package launcher 修复后重新执行 Python 全量：

```text
2798 passed，7 skipped，1 warning
```

并重新确认：Pyright 0 errors、Ruff 通过、compileall 通过、git diff --check 通过。当前工作区新增的两个 tracked status path 是预期的 `run.py` 和本轮 package contract 变更；未产生 staged path。


---

## Ownership correction after package launcher fix（2026-08-09，仍不 staging）

审查记录更正：Qt startup fallback 修复新增了一个 tracked dirty path `run.py`，不是“无新增 status path”。该路径已归入 Batch 8 packaging/launcher hunk；当前工作区为 `484 status entries / 192 tracked modified / 292 untracked / 0 staged`。

---

## 2026-08-09 packaging root and CI dependency closure

### 当前状态基线

```text
485 status entries
193 tracked modified
292 untracked
0 staged
```

本轮没有执行 `git reset`、`git clean`、删除 dirty/untracked 修改、`git add` 或 commit；参考源 `D:\~Vibe-Coding\Projects\AssetsManager_New_WebUI` 仍只读。

### 已完成的最小修复

1. `AssetManager.spec` 使用 PyInstaller spec namespace 提供的 `SPECPATH`：
   ```python
   _root = Path(SPECPATH).resolve()
   ```
   这样从项目目录外调用 PyInstaller 时，datas/hiddenimports/pathex 仍锚定旧项目根目录。
2. `tests/core/test_packaging_entrypoints.py` 同步更新静态合同，防止回退到 `Path.cwd()` 或不存在的 `__file__`。
3. `requirements-dev.txt` 保留 `anyio>=4.0`，使 CI 矩阵可以实际加载 `pytest.mark.anyio` 测试。

### 最新验证

- package contract：`21 passed`；
- 非仓库 cwd 的 PyInstaller `6.19.0` 构建：通过；
- bundle contents checker：通过；
- bundle 中已确认 WebUI/i18n/Themes/Plugins，以及 `QtSvg`、`QtOpenGL`、`QtOpenGLWidgets`；
- offscreen 临时 bundle 启动保持运行 15 秒；
- Python 3.12：`2792 passed，8 skipped，1 warning`；
- Python 3.13：`2792 passed，8 skipped，1 warning`；
- Python 3.14 本机全量基线：`2798 passed，7 skipped，1 warning`。

`async_timeout` 的 PyInstaller warning 是 aiohttp 在当前 Python 版本下的 conditional optional import 提示，不代表缺少必需依赖，也不应重新加入隐藏导入。

### 下一步

- 保持当前 dirty 工作区不变，继续做提交前人工 hunk 归属审查；
- 远程/clean-checkout Python 矩阵和 Windows clean checkout package smoke 仍属于提交前门禁；
- 按 Batch 1–8、Cross-domain、Exclude、Out-of-WebUI-scope 分批准备 staging，但除非用户明确要求，不自动 stage/commit。
---

## 2026-08-09 final local regression closure

完成非仓库 cwd package smoke 后，重新运行当前 dirty 工作区 Python 全量：

```text
2802 passed，7 skipped，1 warning
```

这 4 个新增 package contract 测试已经包含在全量结果中；没有出现回归。warning/skip 原因仍是已知的 zip duplicate-name 测试夹具和 Windows symlink 权限/进程终止限制。

ownership manifest 已更新到当前 `485 / 193 / 292 / 0` 基线，逐路径结果为 0 漏项、0 重复；仍未 stage 或 commit。
---

## 2026-08-09 canonical icon source closure

最终 package hunk 又完成一项跨平台一致性修复：`AssetManager.spec` 的 EXE icon source 已从大小写不一致的 `assets/icons/icon.ico` 统一到 canonical `Assets/icons/icon.ico`，而 bundle 目标目录仍保持兼容的 `assets/icons`。

验证更新：

```text
Package contract：22 passed
PyInstaller non-root build：通过
Bundle resource checker：通过
QtSvg / QtOpenGL / QtOpenGLWidgets / icon.ico：均存在
Offscreen startup smoke：保持运行 15 秒
```

该修复没有改变前序 WebUI 迁移代码归属，仍属于 Batch 8 packaging hunk。
---

## 2026-08-09 final full-suite count after icon closure

在 canonical icon source contract 加入后再次运行 Python 全量：

```text
2803 passed，7 skipped，1 warning
```

package contract：`22 passed`；Ruff、compileall、`git diff --check` 均已通过。此后没有新的生产代码变更。
---

## 2026-08-09 cross-version package gate closure

补做当前工作区的跨 Python 版本 package 定向门禁：

```text
Python 3.12.13：22 passed
Python 3.13.13：22 passed
Pyright：0 errors
```

当前 package 相关验证已覆盖本机 Python 3.14、临时 Python 3.12/3.13、非仓库 cwd PyInstaller bundle 及实际资源存在性检查。
---

## 2026-08-09 bundle runtime binary contract closure

将原始 QtSvg 启动问题转化为真实 bundle 资源门禁：`scripts/check_package_contents.py` 现在验证 canonical icon 以及 `QtSvg`、`QtOpenGL`、`QtOpenGLWidgets` extension binary 的实际存在，而非只验证 spec 文本。

最新结果：

```text
Package contract：26 passed
Python 3.12 package contract：26 passed
Python 3.13 package contract：26 passed
Python 全量：2807 passed，7 skipped，1 warning
真实 bundle checker：通过
```

这样 CI 的 Windows package-smoke 会在 Qt 二进制缺失时直接失败，而不是等用户启动后才出现 `ModuleNotFoundError`。
---

## 2026-08-09 CI foreign-cwd package-smoke closure

为让 CI 真正覆盖 `SPECPATH` 修复，Windows package-smoke 不再从仓库 cwd 构建：它从 `RUNNER_TEMP` 调用绝对路径 spec，并将 dist/work 输出放到临时目录，再使用绝对 bundle 路径运行资源 checker。

新增 workflow static contract 后：

```text
Package contract：27 passed
CI YAML parse：通过
```

这使 CI 能直接捕获“从非仓库 cwd 运行 PyInstaller 时资源丢失”的回归。
---

## 2026-08-09 CI-equivalent foreign-cwd bundle smoke closure

按当前 CI package-smoke 的实际路径重新执行本机验证：

```text
cwd：系统 Temp
spec：旧项目绝对路径/AssetManager.spec
work/dist：系统 Temp 独立目录
PyInstaller：6.19.0 build passed
Bundle checker：passed
Offscreen startup：alive-after-15s
```

这确认 `SPECPATH`、datas、Qt hidden imports 和增强资源 checker 在 CI 等价调用方式下闭环。
---

## 2026-08-09 package contract completeness and cross-domain hunk audit

进一步收紧发布合同：

```text
I18n：en/zh/ja 全部必需
Themes：目录必须含有效文件
Plugins：目录必须含有效文件
Windows regression：安装 requirements-dev.txt
Package contract：31 passed
```

只读 hunk 审查结论：`database.py`、`bootstrap.py`、`file_operation_service.py`、`library_service.py`、`runtime.py` 属于跨域/前置依赖文件，不能整文件 staging。推荐先处理 core identity 与 shared lifecycle，再按 Batch 2→3→4→mainline Gallery→5→8 的顺序选择 hunk。
---

## 2026-08-09 latest Python full-suite closure

补强 bundle 合同后重新执行当前工作区全量 Python：

```text
2812 passed，7 skipped，1 warning
```

当前 package contract：`31 passed`；Python 3.12/3.13：各 `31 passed`。没有出现生产回归。
---

## 2026-08-09 WebUI latest local gate closure

当前工作区 WebUI 重新验证完成：

```text
Vitest：89 files / 585 passed
TypeScript typecheck：通过
Vite production build：通过
Playwright webui-shell：2 passed
```

WebUI 迁移页面、Storefront/Seller 页面、API contract 和移动 viewport shell 均未出现回归。
---

## 2026-08-09 final bundle after latest WebUI build

WebUI build 完成后再次重建 package：

```text
PyInstaller foreign-cwd build：通过
Bundle checker：通过
QtSvg / QtOpenGL / QtOpenGLWidgets / icon / i18n / Themes / Plugins：通过
Offscreen startup：alive-after-15s
```

因此当前 WebUI dist 与 Windows package 入口的本地证据来自同一轮最新工作区状态。
---

## 2026-08-09 full Playwright local gate closure

完整 WebUI E2E suite 当前结果：

```text
30 tests
28 passed
2 skipped
```

通过范围包括 landing/routing/responsive/accessibility/network resilience、Commerce buyer mock、Seller mock 和 migrated Gallery shell。2 个 skip 为没有配置真实后端 URL 的 optional real Commerce acceptance。
---

## 2026-08-09 clean-like snapshot build closure

在独立 Temp snapshot 中完成近似 clean checkout 的跨层验证：

```text
npm ci：成功
WebUI build：成功
PyInstaller foreign-cwd：成功
Bundle checker：通过
Offscreen runtime：alive-after-15s
```

选择性 snapshot 初次未包含 `tests/contracts/lan_public_contracts.json`，导致 WebUI TypeScript 找不到该 tracked fixture；补入该 fixture 后构建通过。由此确认该文件是 WebUI build 的实际仓库级输入，且它已被 Git 跟踪，clean checkout 会包含它。

npm audit 结果：生产依赖 0 vulnerabilities；开发依赖存在 1 moderate + 1 high 的可升级漏洞，暂作为 P2 依赖维护项，不自动修改 package-lock。

---

## 2026-08-09 CI frozen runtime smoke 与 ownership ledger 对齐（仍不 staging）

本轮深度审查确认：

- `run.py` 已完全移除 tkinter 运行时依赖，启动错误使用 bundled Qt `QMessageBox`，Qt 不可初始化时退回 stderr；
- `AssetManager.spec` 继续使用 `Path(SPECPATH).resolve()`，并保留 `PySide6.QtSvg`、`PySide6.QtOpenGL`、`PySide6.QtOpenGLWidgets` hidden imports；
- CI Windows package-smoke 在资源 checker 后增加 15 秒 frozen runtime smoke，覆盖真实 EXE 启动而不只检查文件存在；
- package/static contract 当前为 `32 passed`；本地既有 foreign-cwd bundle offscreen smoke 为 `alive-after-15s`；远程 GitHub runner 证据仍未取得；
- ownership ledger 已由历史 `479` 条修订为当前 `485` 条：`193 tracked modified + 292 untracked + 0 staged`；无 tracked 删除、重命名或复制；
- `AssetManager.spec`、`requirements-dev.txt`、`run.py`、`scripts/check_package_contents.py`、两个 package 测试文件已明确登记为 Batch 8；

仍不执行 `git add`、stage、commit、reset 或 clean。

---

## 2026-08-09 post-smoke Python full-suite closure（仍不 staging）

最终本地 Python 全量回归：

```text
2813 passed，7 skipped，1 warning
package/static contract：32 passed
```

本轮未执行 `git add`、stage、commit、reset 或 clean。

---

## 2026-08-09 package checker 与 Chromium acceptance 稳定性闭环（仍不 staging）

本轮继续发现并修复两项测试/发布门禁问题：

- `scripts/check_package_contents.py` 现在区分 required file 与 required directory，文件被同名目录替代、目录被同名文件替代都会失败；
- `tests/e2e/test_webui_realtime_acceptance.py` 的 LAN server 测试端口过滤 Chromium blocked-port 集合，避免 Windows ephemeral port 随机落到 `6566` 等 unsafe port。

最新验证：

```text
Package checker 定向合同：41 passed
Real Chromium realtime acceptance：6 passed
Python 全量：2822 passed，7 skipped，1 warning
Ruff / compileall：通过
```

`ERR_UNSAFE_PORT` 已不再复现。本轮未执行 `git add`、stage、commit、reset 或 clean。

---

## 2026-08-09 frozen runtime early-exit contract closure（仍不 staging）

继续审查 CI smoke 后发现：原逻辑只在非零退出时失败，EXE 可能静默 `exit 0` 而被误判为成功。已修正：

```text
15 秒内任何提前退出：失败
15 秒后仍存活：通过，随后只终止本次 smoke 进程
```

package/CI contract 当前为 `41 passed`，未触碰业务迁移代码。

---

## 2026-08-09 Python LAN browser CI lane（仍不 staging）

为让真实 Python LAN Chromium acceptance 不再只存在于本地证据，`.github/workflows/ci.yml` 新增独立 Windows job：

```text
python-browser-e2e
→ npm ci + WebUI build
→ 安装 requirements-lan.txt / requirements-dev.txt / Python Playwright
→ python -m playwright install chromium
→ tests/e2e/test_webui_realtime_acceptance.py
```

该 job 不改变通用 Python requirements，只补充浏览器验收专用依赖。当前仍未取得远程 runner 实际结果，需在配置 remote/CI 后验证。

---

## 2026-08-09 final current-worktree Python closure（仍不 staging）

在新增 Windows Python LAN browser CI 合同后，当前工作区重新完成全量 Python：

```text
2823 passed，7 skipped，1 warning
```

当前局部门禁：

```text
Package/CI contract：42 passed
Real Chromium LAN acceptance：6 passed
```

远程 GitHub runner 尚未执行；本地状态仍保持 485 paths、0 staged。

---

## 2026-08-09 Qt binary suffix contract closure（仍不 staging）

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\scripts\check_package_contents.py` 现在要求 Qt extension 文件使用平台二进制后缀：

```text
.pyd / .so / .dylib
```

仅有 `QtSvg.pyi` 等同名前缀 stub 文件不会再被误判为可加载模块。当前 package/browser 变更切片 `51 passed`，全量 Python：

```text
2826 passed，7 skipped，1 warning
```

---

## 2026-08-09 latest clean-like snapshot closure（仍不 staging）

基于当前最新工作区创建独立 snapshot，排除 `.git`、权限异常 artifacts、缓存、旧 build/dist、node_modules 和测试产物，完成：

```text
npm ci：成功
WebUI npm run build：成功
foreign-cwd PyInstaller 6.19.0：成功
最新 bundle checker（含 Qt suffix contract）：通过
frozen runtime offscreen：alive-after-15s
```

本次 snapshot 输出：

```text
C:\Users\86177\AppData\Local\Temp\AssetsManager-clean-current-s61try00
C:\Users\86177\AppData\Local\Temp\AssetsManager-clean-current-package-20260809\dist\AssetManager
```

这进一步证明最新 package 入口不依赖原工作区的 WebUI `node_modules` 或旧 `dist` 缓存。npm audit 仍报告 1 moderate + 1 high 的 dev/build 依赖问题，未自动升级 lockfile。

---

## 2026-08-09 final hunk ownership audit（仍不 staging）

当前高风险文件的提交依赖最终确认如下：

```text
Schema/migration spine
→ Core identity / managed connection
→ Shared LibraryService / LibraryRuntime lifecycle
→ Batch 2 restore / integrity / maintenance
→ Batch 3 reconciliation / index
→ Batch 4 Commerce projection
→ mainline Gallery/Favorite
→ Batch 5 LAN wiring
→ Batch 7 E2E acceptance
→ Batch 8 package cluster / CI
```

必须按 hunk 处理的文件：

```text
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\core\database.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\bootstrap.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\file_operation_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\library_service.py
D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\application\runtime.py
```

Batch 8 package cluster必须保持原子合同：

```text
AssetManager.spec
→ scripts/check_package_contents.py
→ tests/core/test_package_contents.py
→ tests/core/test_packaging_entrypoints.py
→ .github/workflows/ci.yml package-smoke
```

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\webui\playwright.config.ts` 仍是 Batch 7/8 cross-domain，必须 stage once；`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\tests\e2e\test_webui_realtime_acceptance.py` 同时含 LAN preflight/lifecycle 与 blocked-port 修复，不能无条件整文件归入本轮。

---

## 2026-08-09 WebUI lockfile security closure（仍不 staging）

在临时 snapshot 中先验证 `npm audit fix --package-lock-only --ignore-scripts` 的范围后，将同一最小变更同步到原工作区：

```text
nanoid 3.3.16 → 3.3.18
postcss 8.5.19 → 8.5.26
postcss 对 nanoid 的约束：^3.3.12 → ^3.3.17
```

lockfile 仅 14 行变更；`package.json` 未改变。当前：

```text
npm audit：0 vulnerabilities
```

ownership 基线更新为 `486 status paths = 194 tracked modified + 292 untracked`，新增路径归 Batch 8 package/dependency cluster。

---

## 2026-08-09 lockfile security closure final verification（仍不 staging）

更新后的 `webui/package-lock.json` 已完成最终 snapshot 验证：

```text
npm ci：成功
npm audit：0 vulnerabilities
Vitest：89 files / 585 passed
typecheck：通过
build：通过
foreign-cwd PyInstaller：成功
bundle checker：通过
post-lock frozen runtime：alive-after-15s
```

当前工作区基线已更新为：

```text
486 status paths
194 tracked modified
292 untracked
0 staged
```

---

## 2026-08-09 continuous npm audit gate closure（仍不 staging）

`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\.github\workflows\ci.yml` 的 WebUI job 现在在 `npm ci` 后执行：

```text
npm audit --audit-level=moderate
```

更新后的 lockfile 与持续 audit gate 当前均返回：

```text
found 0 vulnerabilities
```

package/CI static contract 当前为 `46 passed`；状态基线仍为 `486 = 194 tracked modified + 292 untracked`。

---

## 2026-08-09 QtSvg / tkinter frozen startup closure（仍不 staging）

针对旧 frozen executable 出现：

```text
ModuleNotFoundError: No module named 'PySide6.QtSvg'
ModuleNotFoundError: No module named 'tkinter'
```

已在当前工作区完成最小闭环：

- `AssetManager.spec` 显式保留 `PySide6.QtSvg`、`PySide6.QtOpenGL`、`PySide6.QtOpenGLWidgets`；
- `run.py` 不再依赖 `tkinter`；
- `run.py --package-smoke` 非交互检查 QtSvg 导入、dock/sidebar 导入链和 SVG icon 渲染；
- `scripts/check_package_contents.py` 同时检查 Qt extension binary 与 `Qt6Svg`、`Qt6OpenGL`、`Qt6OpenGLWidgets` companion runtime library；
- `.github/workflows/ci.yml` 新增 frozen Qt/icon package smoke；
- `tests/core/test_package_contents.py` 与 `tests/core/test_packaging_entrypoints.py` 新增对应合同测试。

当前验证：

```text
定向 package/CI 测试：51 passed
ruff：通过
python run.py --package-smoke：exit code 0
fresh foreign-cwd PyInstaller：成功
bundle checker：通过
fresh frozen --package-smoke：exit code 0
fresh frozen normal runtime：alive-after-15s
```

fresh bundle 输出：

```text
C:\Users\86177\AppData\Local\Temp\AssetsManager-current-package-patch-20260809\dist\AssetManager
```

本次没有新增状态路径；当前基线仍为：

```text
486 status paths = 194 tracked modified + 292 untracked + 0 staged
0 deleted / 0 renamed / 0 conflicts
```

该修复属于 Batch 8 package/CI cluster，仍未执行 staging 或 commit。

---

## 2026-08-09 continuation deep audit closure（仍不 staging）

对交接文档列出的剩余本地风险进行了复核：

- migration DDL 历史版本链、future-schema preflight、v8/v16/v19/v21 边界：无新增缺口；
- deprecated `get_library_dir()` path-only、identity collision、reserved legacy、双目录冲突、迁移失败：现有直接入口测试已覆盖；
- Seller/LAN stop/start 与窗口 startup-failure 相关定向回归：通过；
- ownership manifest 与当前工作区：486/486，0 missing，0 extra，0 duplicate；
- package/launcher/CI static contract：51 passed。

本轮本地定向验证：

```text
migration/database/compatibility cluster：98 passed
LAN lifecycle / window failure / seller routes：50 passed
```

因此当前无需为了已覆盖的 `get_library_dir()` 场景重复添加测试或修改生产代码。剩余非本地门禁仍为远程 runner/clean checkout 证据，以及用户明确授权后的人工 hunk staging/分批提交。

---

## 2026-08-09 continuation hunk ownership audit（仍不 staging）

当前 workspace ownership 已完成提交前 hunk 复核：

```text
486 paths：全部有归属
194 tracked modified
292 untracked
0 staged
25 tracked files：必须 hunk stage
169 tracked files：归属上可整文件 stage 候选
```

最高风险文件：

```text
AssetsManager/core/database.py
AssetsManager/application/bootstrap.py
AssetsManager/application/file_operation_service.py
AssetsManager/application/library_service.py
AssetsManager/application/runtime.py
```

这些文件混合 shared identity/lifecycle、Batch 2 restore/integrity、Batch 3 reconciliation/runtime、Batch 6 Favorite/Gallery wiring，禁止整文件纳入单一批次。真实 stage 前仍需用户明确授权。

---

## 2026-08-09 current-worktree full regression closure（仍不 staging）

在当前完整 dirty workspace 上重新执行全量 Python，覆盖本轮 package/launcher/CI 合同增量：

```text
2832 passed
7 skipped
1 warning
```

本轮同时执行：

```text
Ruff：All checks passed
```

warning 仍为既有 duplicate zip entry 测试夹具；7 个 skip 仍为 Windows symlink/进程终止限制，不是本轮回归。当前状态、ownership 与 staging 约束未改变。
