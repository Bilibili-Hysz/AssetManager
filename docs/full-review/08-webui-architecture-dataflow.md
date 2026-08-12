# WebUI 数据流与设计架构审查（08-webui-architecture-dataflow.md）

> 审查日期：2026-08-12 · 基于工作区实况（webui/ 26400 行 TS/TSX）
> 技术栈：React 18.3 + react-router-dom 7.18 + Tailwind 3.4 + Vite 7 + Vitest 3.2 + Playwright
> 范围：数据流（请求管线、状态、缓存、失效、实时链路）与设计架构（分层、路由、Context、契约）

---

## 1. 架构总览

### 1.1 技术决策

| 决策 | 现状 | 评价 |
|---|---|---|
| 状态管理 | **无状态库**（无 Redux/Zustand/Jotai）；Context + hooks | 合理——应用规模（51 页面、4 全局 Context）未到需要状态库的程度 |
| 数据获取 | **无请求库**（无 React Query/SWR）；手写 fetch 封装 + AbortController | 每 hook 自维护竞态防护，质量高但重复代码多 |
| 认证 | **Cookie-only**（无 token 落 JS）；HttpOnly cookie + `/auth/me` 会话恢复 | 安全最佳实践；`credentials: 'same-origin'`（client.ts:158,233,313） |
| 实时 | 单 WebSocket + 投影失效广播（`projection_invalidated`） | 与后端 EventBus→RuntimeEventRouter→WS 链路对称 |
| 契约 | 双轨：golden JSON 快照（跨栈）+ per-module mock 测试（前端自洽） | 见 §5 覆盖盲区 |

### 1.2 分层

```
pages/（51）        路由页面——数据消费 + 局部编排
components/（81）   展示组件——多数不直接 fetch（admin 面板例外：自读 context）
hooks/（25）        数据获取/UI 状态——每实例独立 fetch + generation/AbortController
stores/（4 处）     AuthContext / RealtimeContext / SellerAuthContext（stores/）
                    ShopBuyerContext（components/storefront/，位置不一致）
api/（33）          领域模块工厂 createXxxApi(api) → {methods}；返回裸 DTO
                    client.ts：fetch 封装（超时/错误映射/401 hook）
types/api.ts        手工镜像后端 DTO（单文件 672 行，Shop 占 40%）
```

### 1.3 路由与 Provider（App.tsx:108-172）

```
BrowserRouter → AuthProvider → RealtimeProvider → ToastProvider → DownloadProgressProvider → Suspense → Routes
   ├─ 公开：/、/login、/s/:shareId、*
   ├─ 主区：ProtectedRoute capability="browse"（/browse、/detail、/gallery*）
   ├─ 管理：ProtectedRoute capability="manage_users"（/admin）
   ├─ 商城：FeatureFlagRoute feature="commerce" → ShopBuyerProvider（/storefront*，11 条）
   └─ 卖家：feature="seller" → SellerAuthProvider → SellerAccessGate（/seller*）
```

- 25 页面全 `React.lazy` + 单全局 Suspense（App.tsx:11-35,113）
- **好的分层决策**：Seller/ShopBuyer 是路由作用域 Provider（App.tsx:55-69），不污染全局；`key={identity}` 强制身份切换整体 remount（RealtimeContext.tsx:238）

---

## 2. 数据流全景

### 2.1 请求管线（client.ts，406 行）

```
组件/hook → api 领域模块 → client.ts
                            ├─ URL: baseUrl/api/{path}，null/''/undefined 参数丢弃（:137-143）
                            ├─ 超时: 30s（下载 5min）AbortController+setTimeout，TimeoutError 与用户取消区分（:61-80）
                            ├─ 401 → onUnauthorized?.() + UnauthorizedError（:161-164）→ AuthContext 全局身份重置
                            ├─ 403 → ForbiddenError；429 → rateLimitErrorFrom（转发 Retry-After/X-RateLimit-*）
                            ├─ 503 → ServiceUnavailableError（带 body.error）
                            └─ 2xx 非 JSON → ApiError('Invalid JSON response (HTTP n)')（:103-122）
```

错误类型层次：`ApiError(status, body)` ← `UnauthorizedError/ForbiddenError/ServiceUnavailableError`；`NetworkError` 独立 extends Error（errors.ts:35）。

**无重试/退避**：429 头解析后丢弃（client.ts:83-95），Retry-After 无人消费；上层仅 LandingPage.retryConnect 手动重试。

### 2.2 状态模型——"每实例独立 fetch + 广播失效"

除 Auth/Realtime/Toast/DownloadProgress/cart/wishlist 外，**所有数据 hook 每挂载实例独立 fetch**：

```
同一数据的 N 个消费者 = N 份网络请求 + N 份本地状态
同步唯一手段：WS projection_invalidated → RealtimeContext.notify → 各实例 refetch
```

每个 hook 的统一防护四件套（高质量模式，useProjects.ts:38-66 为范本）：
1. `identityGeneration`（AuthContext 身份代数）——身份切换时重置数据
2. `registerInvalidation(domains, cb)`——WS 失效订阅（useInvalidation.ts 只依赖 registerInvalidation/epoch/status，设计正确）
3. `AbortController`——卸载/重取时 abort 在途请求
4. `requestSequence/generation ref`——过期响应丢弃

### 2.3 实时失效链路

```
后端 EventBus → RuntimeEventRouter → WS {type: projection_invalidated, domains, paths, revision}
  → RealtimeContext（cursor: {epoch, revision}）
     ├─ gap 检测：revision > current+1 → recover()（/api/revision 补缺口，10s 超时，裸 fetch 绕过 client）
     └─ notify(event) → 按 domains∩注册表分发
  → 各 hook 回调 → 重新 fetch
```

- recover 成功 → `notify(null)` **全量惊群刷新**（RealtimeContext.tsx:146）
- 无心跳 ping（useWebSocket.ts:57-77），半死连接靠 TCP 超时才能发现

### 2.4 写操作数据流

| 域 | 模式 | 并发控制 |
|---|---|---|
| 收藏 useFavorites | **乐观更新 + 串行队列 + 失败回滚**（L187-262） | promise 尾链 mutationQueueRef |
| 购物车/心愿单 ShopBuyerContext | **非乐观**：服务端响应后 commitCart | cart.version + StaleBuyerIdentityError + enqueueBuyerOperation 串行化（L99-111） |
| 标签变更 BrowsePage | 手动连环刷新（refresh + refreshSelected + runTagSearch） | WS 事件到达时再刷一次（双路径） |

---

## 3. 状态管理细节

### 3.1 四个 Context

| Context | 作用域 | 重渲染面 | 备注 |
|---|---|---|---|
| AuthContext（stores/，243 行） | 全局 | **全 App**；value 已 useMemo（13 项依赖） | `identityGeneration` 全局数据版本号；A8 未决：401 无路径上下文 |
| RealtimeContext（stores/，249 行） | 全局 | 每 WS 事件全量（value 含 cursor） | 消费方靠 useInvalidation 收窄依赖 |
| SellerAuthContext（stores/，99 行） | /seller/* | 路由子树 | 独立 client，无全局 401 handler（设计有意，注释 :19-20） |
| ShopBuyerContext（components/storefront/，359 行） | /storefront/* | 路由子树 | **位置不一致**（应入 stores/）；实现质量最高（版本并发控制） |

### 3.2 每-hook 状态与缓存

| hook | 状态 | 缓存 | 失效 |
|---|---|---|---|
| useFavorites | paths/items/loading/error | localStorage（am_favorites_cache:v2 + origin + 身份键） | identity、WS favorites、乐观写 |
| useCommerceCatalogPage/Catalog/Orders | products/orders/page/total | 无 | WS shop/orders/quota |
| useProjects | 目录列表 + sort + listingGeneration | 无（hydrateDirectories 批量合并摘要） | identity、WS files、手动 |
| useSearch | query/results | 无；200ms 防抖 | identity、WS files/metadata |
| useThumbnailCache | 缩略图 | 内存 LRU 300 + sessionStorage | identity、`revision: cache` 触发重建 |
| useQuota | quota | 无；guardDownload 惰性 + fail-open | identity、WS quota、下载后手动 |

---

## 4. 发现的问题清单

### 4.1 契约漂移（前后端真实不一致）

| # | 问题 | 位置 | 严重度 |
|---|---|---|---|
| C1 | **`ProjectItem` 缺 `is_project` 字段**：后端文件列表每条目都发（files.py:93,108），前端类型未声明 → BrowsePage 用 `'is_project' in item` 运行时探测绕过类型（BrowsePage.tsx:398,407） | api.ts:82-96 | ~~高~~ ✅ 已修（2026-08-12）：ProjectItem 补 `is_project?: boolean`，探测简化为 `item?.is_project` |
| C2 | **幽灵字段**：`view_only/downloadable/password_protected`（ProjectItem:93-95）在后端全库无发送者——旧 web UI 残留超集 | api.ts:93-95,267-269 | 中（维持）：ProjectCard.tsx:59-61 有徽章读取逻辑（值恒 false 不显示）——UI 防御性读取保留，删字段会破坏编译，记录为契约超集 |
| C3 | **`summaries` 字符串真值语义脆弱**：后端 `files.py:45` `== "true"`（任何非 'true' 皆 False）；测试值 `'1'`（files.contract.test.ts:57）与生产值 `'false'` 都与默认语义无对应 | files.py:45 | 低（运行期无害） |
| C4 | 类型超集 | api.ts:12,22-23,625 | ~~低~~ ✅ 已修（2026-08-12）：删除 ServerInfo 的 asset_root_id/total_collections/total_artworks（后端无此概念）并简化 useFavorites 库身份；StorefrontBuyerOrdersPage total 改为 `response.total ?? orders.length` fallback（后端 keyset 分页不发总数）；过时注释修正（后端已支持 cursor） |

### 4.2 架构分层

| # | 问题 | 位置 | 严重度 |
|---|---|---|---|
| A1 | **hooks 绕过领域模块直接拼端点**：useCommerce.ts 直写 `'shop/catalog'`/`'shop/items'`/`'shop/orders'`/`'shop/stats'`（:199-204,255,295-296）+ 内联宽松类型 `RawShopItem = Partial<ShopItem>`（:7-17），而 shop.ts:38-50 已有 `catalog()` 方法——端点字符串与 DTO 两层重复定义，**类型漂移最大风险点** | useCommerce.ts | ~~高~~ ✅ 已修（2026-08-12）：useCommerce 三 hook 改用 `createShopApi` 领域方法（list/catalog/listOrders/getStats 增补 signal 参数）；宽松类型精确化为 `ShopItemInput`/`ShopOrderInput`（Partial + 防御字段），useCommerceOrders 顺手补 AbortController |
| A2 | **API 层做 DOM 副作用**：files.ts `download`/`batchDownload` 执行 createObjectURL + link.click + setTimeout revoke（:27-32,44-49），双份复制粘贴——下载触发属 UI 职责 | files.ts:18-54 | ~~中~~ ✅ 已修（2026-08-12）：api 层只返回数据（download→{blob,filename}、batchDownload→Blob）；新增 `src/utils/download.ts#triggerBlobDownload` 持有 DOM 副作用；BrowsePage 两处调用点更新 |
| A3 | **三个 ApiClient 实例**：AuthContext / SellerAuthContext（有意）/ ShareReceivePage.tsx:14——后者无 onUnauthorized，公开分享页 401 静默不重置会话，语义不一致且无注释 | ShareReceivePage.tsx:14 | ~~中~~ ✅ 已修（2026-08-12）：确认独立 client 为有意设计（分享验证 401 不应重置访客身份），补意图注释 |
| A4 | **contracts.test.ts 是死代码 fixture**：被 vite.config.ts:32-33 显式排除出测试，文件内注释仍声称"kept dependency-free until the SPA adds a test runner"（:7）——陈旧注释 + 不运行的共享 fixture（projectFileDownloadPath 等无引用方） | contracts.test.ts | ~~低~~ ✅ 已删（2026-08-12）：确认无任何引用后删除文件 + vite.config exclude 清理 |
| A5 | **notes.ts 内联 DTO**（:3-7 SaveNotesResponse）未入 types/api.ts | notes.ts | ~~低~~ ✅ 已修（2026-08-12）：移入 types/api.ts Metadata 区块 |
| A6 | ShopBuyerContext 放 components/storefront/ 而非 stores/（与另外三个 Context 分居） | components/storefront/ShopBuyerContext.tsx | ~~低~~ ✅ 已修（2026-08-12）：移至 stores/ShopBuyerContext.tsx（含测试），9 处 import 同步 |

### 4.3 数据流

| # | 问题 | 位置 | 严重度 |
|---|---|---|---|
| D1 | **结构性重复 fetch**：useFavorites 4 挂载点（Sidebar:124、GalleryFavoritesPage:27、GalleryHomePage:39、GalleryCollectionPage:30）同屏最多 4 并发 `GET /api/favorites`；useCommerceCatalog() 在 StorefrontPage:24 + StorefrontProductPage:25 重复；useSearch 在 Header:14 + AppHeader:35 同时挂载时重复搜索 | 各 hook | ~~高（请求放大）~~ ✅ 已修（2026-08-12）：favorites 与 search 模块级 in-flight 去重（同 query 共享 promise，实例各自 generation 守卫）；catalog 实为路由互斥（非同屏并发），记为 P3 缓存策略 |
| D2 | **localStorage 收藏缓存每实例快照**：一个实例 toggle 后同屏其他实例不读 storage 事件，只能等 WS；`capabilities.realtime=false` 时 Sidebar 永久陈旧 | useFavorites.ts | ~~中~~ ✅ 已修（2026-08-12）：storage 事件监听（跨 tab 同步；同 tab 实例由 D1 共享请求保证一致） |
| D3 | **recover() 惊群**：断线恢复/epoch 切换时 notify(null) 全量刷新所有注册者（+ useInvalidation 在 status 变化时重注册叠加） | RealtimeContext.tsx:146 | 中（抖动连接下成批重复请求） |
| D4 | **BrowsePage 标签变更双路径刷新**：手动连环刷新（:362-380）与 WS 失效回调（:382-390）各自全刷，实时关闭时仅手动路径、开启时两路径叠加 | BrowsePage.tsx | 中 |
| D5 | **无 AbortController 的 hook**：useCommerceOrders（:282-327）、useSearch（:26-37）卸载后请求仍在飞（仅序列号防 setState） | useCommerce.ts, useSearch.ts | 低 |
| D6 | **useCommerceCatalogPage 分页双源**：URL searchParams 是页面源，hook 内 page/pageSize 另存一份（:178-179,207-208），StorefrontProductsPage 只用 URL，hook 内 setPage 死写 | useCommerce.ts | 低 |
| D7 | 下载后 refreshQuota 与 guardDownload 预取叠加（BrowsePage:434,491）→ 一次点击 2 次 quota 请求 | BrowsePage.tsx | 低 |
| D8 | WebSocket 无心跳 ping，半死连接无法快速重连 | useWebSocket.ts | ✅ 澄清（2026-08-12）：**后端已有**心跳检测（lan/ws.py `_heartbeat_cycle` 协议级 ping/pong + 超时清理），半死连接由服务端关闭触发前端 onclose 重连——前端无需主动 ping |

### 4.4 认证/安全

| # | 问题 | 位置 | 严重度 |
|---|---|---|---|
| S1 | **A8 已修（2026-08-12）**：client `onUnauthorized(path)` 带请求路径；AuthContext 跳过 auth/login、auth/register、auth/verify_key（失败登录不再登出用户/清缩略图缓存）；新增回归测试 | AuthContext.tsx | 中 |
| S2 | Storefront 路由无 capability 门禁（仅 feature flag），与 /browse 的 capability 门禁不对称——若需"只看不下载"访客级能力此处是缺口 | App.tsx:127 | 低（设计取舍） |

---

## 5. 契约测试体系评估

### 5.1 三层结构

1. **per-module contract 测试（14 个）**：mock ApiClient 断言路径/query/body/编码——**纯前端自洽**，不启动后端、不核对后端路由；后端改路由只有后端 pytest 或人工比对能发现
2. **golden 快照（跨栈唯一锚点）**：`tests/contracts/lan_public_contracts.json`（1565B，6 个 DTO：User/Invite/Tag/Tree/Stats）——后端 test_public_contracts.py 断言 DTO 序列化 === 快照；前端 public-contracts.test.ts 断言快照与类型一致。**手工维护、只读不写、无生成步骤**
3. **client/errors 单测**：真实 fetch 层（URL 拼接/query 过滤/超时/进度/Content-Disposition）

### 5.2 盲区

- 快照覆盖 8 个 DTO/契约（2026-08-12 扩展）：新增 files_item（文件列表条目 10 字段精确 key + is_project 值）与 info（ServerInfo envelope）；后端新增两个 HTTP 契约测试锁定 /api/files item key 集合与 /api/info envelope（含 guest principal 附加语义）
- `public-contracts.test.ts:37` `expect(stats).toEqual(contracts.responses.stats)` 自比较恒真（StatsResponse 形状零钉死）
- `system.contract.test.ts` 用 `{library_name: ...}` sentinel 透传（后端字段是 share_name），/api/info 形状零保护
- **coverage 配置已补（2026-08-12）**：@vitest/coverage-istanbul@3.2.6 + vite.config coverage（istanbul provider，jsdom 兼容；v8 provider 在 jsdom worker 不收集）+ `npm run coverage` script。基线：600 tests / 74.16% statements / 78.04% lines / 62.72% branch

---

## 6. 正面实践（保留）

1. Cookie-only 认证 + AuthContext 单点持有 client 与全局 401 handler
2. Context 分全局（Auth/Realtime）与路由作用域（Seller/ShopBuyer）的分层决策
3. useFavorites 乐观更新 + 串行队列 + 失败按位回滚（L187-262）
4. ShopBuyerContext version 并发控制 + StaleBuyerIdentityError + 尾链串行化（L99-111）
5. RealtimeContext gap 检测 + recover 超时（L186-203, L39）
6. useThumbnailCache pending 去重 + LRU 触达序刷新 + sessionStorage 持久化（L5-96）
7. 各 hook 统一的 generation + AbortController 竞态防护
8. useInvalidation 只依赖 registerInvalidation/epoch/status 避免 revision 抖动重注册（L18-21）
9. 卖家会话独立 client（不触发全局身份重置）

---

## 7. 建议优先级

| 批次 | 内容 |
|---|---|
| P1（高） | C1 is_project 补类型；A1 useCommerce 改用 shop.ts 领域方法（消除端点双源） |
| P2（中） | D1 favorites/catalog/search 去重（context 级共享或 module-level 请求去重）；A2 下载副作用移出 api 层；A3 ShareReceivePage client 统一语义；D2 favorites 缓存 storage 事件同步；S1 A8 401 路径上下文 |
| P3（低） | ~~类型清理/死代码/契约扩展/coverage~~ ✅ 全部完成（2026-08-12，提交 5431076 + 后续）；剩余维持项：D3 惊群/D4 双路径/D6 分页双源/D7 quota 重复（设计使然，见 §4） |

## 附：关键文件索引

- `src/api/client.ts`、`src/api/errors.ts`、`src/types/api.ts`
- `src/App.tsx`、`src/main.tsx`
- `src/stores/{AuthContext,RealtimeContext,SellerAuthContext}.tsx`、`src/hooks/{useCommerce,useProjects,useSearch,useFavorites,useQuota,useThumbnailCache,useWebSocket,useInvalidation}.ts`
- `src/components/storefront/{ShopBuyerContext,SellerAccessGate}.tsx`、`src/components/auth/ProtectedRoute.tsx`
- `src/pages/{BrowsePage,StorefrontPage,AdminPage,ShareReceivePage}.tsx`
- `tests/contracts/lan_public_contracts.json`、`tests/lan/test_public_contracts.py`、`webui/src/api/public-contracts.test.ts`
