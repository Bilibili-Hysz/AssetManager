# 前端审查（05-frontend.md）

> 审查日期：2026-08-11 · 工作区实况 · webui/src 共 196 ts/tsx（90 测试 + 106 源）

## 1. 技术栈与构建

- **依赖**：react 18.3.1 / react-router-dom 7.18.2（锁定）/ lucide-react / vite 7.3.6 / typescript 5.6 / tailwindcss 3.4 / vitest 3.2.6 / @testing-library/react / @playwright/test；Node `^20.19.0 || >=22.12.0`
- **scripts**：`dev`（vite，代理 /api→8080、/ws→ws://8080）/ `build`（tsc -b && vite build）/ `test`（scripts/run-vitest.mjs，Windows subst 盘符 workaround 规避 `~#%` 路径）/ `test:e2e` / `typecheck`
- **托管**：`lan/routes/pages.py` SPA_DIR=webui/dist，全部页面路由回退 `_spa_response()`（无 dist → 503）；vite.config 显式排除 `api/contracts.test.ts`（fixture 模块）

## 2. src 目录地图

```
api/        client.ts(308) + errors.ts + 13 工厂 + 18 测试
stores/     AuthContext / RealtimeContext / SellerAuthContext
hooks/      13 源文件（useCommerce 导出 3 hook，共 21 个导出）
pages/      24 页面组件 + 20 测试
components/ 10 子域（admin/auth/files/gallery/layout/shares/storefront/tags/ui/viewer）
types/      api.ts（666 行约 90 DTO，镜像 LAN 路由 JSON）
i18n/       index.ts + en/zh/ja.ts（useSyncExternalStore + localStorage am_lang）
```

## 3. API 客户端层

**client.ts 基类**（createApiClient）：
- `request<T>(method, path, body?, params?, signal?)`：URL 基于 `window.location.origin`；params 过滤空值；**`credentials: 'same-origin'`**（HttpOnly cookie，无 bearer）
- 错误映射：fetch TypeError→NetworkError；AbortError 透传；401→onUnauthorized+UnauthorizedError；403→ForbiddenError；429→ApiError('Rate limited')；503→ServiceUnavailableError；其余→ApiError(body.error)
- 下载：`postBlobWithProgress`（ReadableStream 逐块 + onProgress）、`getBlobWithMetadata`（Content-Disposition `filename*=UTF-8''` 解析）
- 12 个公开方法 + buildUrl/buildWebSocketUrl（自动 ws/wss 协商）

**13 个领域工厂**：auth（login/register/verifyKey/me）、files（list/summaries/download/batchDownload）、gallery（home/collection/resolve）、tags（list/add/remove/rename/delete）、metadata（getProjectDetail/getMeta/search/getTree/getHome）、notes（save）、thumbnails（batch）、shares（create/list/delete/getInfo/verifyPassword/getDownloadUrl/getPreviewUrl，路径逐段 encode）、favorites、quicksearch、system（getInfo/getStats/getQuota/getTunnelStatus）、users（list/toggle/invites/activity/online）、shop（最大约 37 方法：商品/店铺/购物车版本锁/结账幂等键/愿望单/订单/投递含 Idempotency-Key 下载）

**契约测试**：14 个 `.contract.test.ts`（mock ApiClient 断言精确 path/params/body）+ `public-contracts.test.ts`（对照 `tests/contracts/lan_public_contracts.json` 断言 DTO 归一化：password_hash 剔除、active 布尔化等）

## 4. 状态管理（全 Context，无状态库）

| Context | State | 机制要点 |
|---|---|---|
| AuthContext | user/role/permissions/principal/capabilities/isAuthenticated/identityGeneration/authMode/serverInfo | 启动 GET /api/info 引导；identityGeneration 供子域清缓存；handleUnauthorized 清 guest+缩略图缓存；inFlightMeRef 去重 |
| RealtimeContext | cursor{epoch,revision}/status | 见 04 §5（缺口恢复） |
| SellerAuthContext | enabled/authenticated/loading | **独立 ApiClient**（无 401 全局重置钩子）；login/logout/refresh |
| ShopBuyerContext | cart/wishlist/loading | 身份代际护栏 StaleBuyerIdentityError；enqueueBuyerOperation 串行化；登录自动 mergeBuyerState；降级清空重取 |
| Toast / DownloadProgress | — | 4s 三态通知 / 顶部 1px 进度条（indeterminate/determinate） |

## 5. Hooks（21 个导出）

| Hook | 要点 |
|---|---|
| useProjects | files 列表+排序/导航/refresh/hydrateDirectories（summaries 回填 size/thumbnail）；identityGeneration 清数据；AbortController 竞态 |
| useSearch | quicksearch 200ms 防抖；失效重查 |
| useFavorites | localStorage 缓存（am_favorites_cache:v2 按身份键）；乐观更新+串行队列+失败回滚 |
| useQuota | fail-open；剩余 0 阻止下载、≤2 提示 |
| useThumbnailCache | batch 256px base64；sessionStorage 300 LRU；identity 清空 |
| useI18n / useTheme | useSyncExternalStore；am_theme + 旧键迁移 + prefers-color-scheme 跟随 |
| useWebSocket | 重连退避 1s→30s；WebSocketTransportHost fanout |
| useInvalidation | 域失效注册（见 04 §5） |
| useCommerce×3 | catalog 分页 / catalog 管理态 / orders+stats；注册 ['shop']/['orders','quota'] 失效 |
| 其他 | useMediaQuery/useDialogFocus（焦点陷阱+还原） |

## 6. 路由与页面（App.tsx，32 条 Route / 24 页面）

Provider 嵌套：`BrowserRouter > AuthProvider > RealtimeProvider > Toast > DownloadProgress > Suspense`（CommandPalette 条件渲染）。

- `/` LandingPage（Gate 模糊缩略图墙）、`/login`
- `ProtectedRoute capability="browse"`：/browse /detail /gallery /gallery/collection /gallery/favorites
- `FeatureFlagRoute feature="commerce"` > CommerceBuyerRoute：/storefront 全套（products/cart/wishlist/orders/product/:id/product/path/*/checkout/group/checkout/:orderId/delivery/:token）+ 兼容别名 /store→/storefront、/store/gallery/:tag、/store/checkout、/store/delivery/:token、/store/*
- `FeatureFlagRoute feature="seller"` > SellerProviderRoute > SellerAccessGate：/seller 全套 + 兼容 /app 系列
- `/s/:shareId` ShareReceivePage；`*`→`/`

**FeatureFlagRoute**：`serverInfo.feature_flags?.commerce && flags[feature]` 双条件，不满足重定向 /gallery；feature_flags 仅 App.tsx 使用。

**守卫**：ProtectedRoute（未认证→/login；能力缺失→/）；SellerAccessGate（未启用→/storefront；未认证内联 SellerLoginPage）。

## 7. 组件地图（关键）

- **layout/**：AppLayout（三栏壳）/Sidebar（树展开+TagChip 过滤）/InfoPanel/ResizablePanel/AppHeader
- **files/**：ProjectGrid/ProjectList/ProjectCard（300ms 单击双击区分）/MasonryView/FileToolbar/Breadcrumb/LayeredPreview
- **gallery/**：GalleryLayout/Section/Card/TiledGrid/ViewControls（视图持久化 am_gallery_view）
- **shares/**：ShareDialog（密码/预览/限次+焦点还原）
- **viewer/**：ImageViewer 灯箱
- **ui/**：CommandPalette（Ctrl+K quicksearch 双跳转）/ContextMenu/Modal/Skeleton/Toast/DownloadProgress
- **admin/**：UserManagement/InviteManagement/ShareManagement/OnlineUsers/ActivityLogView
- **storefront/**：StorefrontShell/ProductCard/SellerAccessGate/SellerGalleryEditor（路径校验）/ShopBuyerContext/BuyerDeliveryDownloadButton（幂等 key+文件名解析）

## 8. 实时协议客户端（见 04 §5，此处补前端实现细节）

- `useWebSocket`：独立模式 + Bridge 模式（`WebSocketTransportHost` 单实例 transport，`key={identity}` 强制重建）
- `RealtimeContext`：asEvent 白名单校验（15 域+paths）、缺口检测（revision > current+1 → recover）、recover 幂等（pending.promise 单代际去重）
- `useInvalidation`：`domains.join('|')` effect 依赖；恢复期 `event === null` 全量重取

## 9. 测试

- **Vitest 90 文件**：api 契约 14 + client/errors + RealtimeContext(~23)/useWebSocket(~18)/useInvalidation/useFavorites/useQuota/useThumbnailCache/useCommerce + 组件测试（App 路由全 mock、各页面）+ CSS 契约测试（index.css.test.ts readFileSync 断言样式）
- **Playwright 5 spec**：app（Landing/路由/响应式 375px+1920px/键盘可达性/CSS/网络容错 ~17 测试）、webui-shell（Gallery 壳+CommandPalette+mock 路由）、seller、commerce-buyer（mock 全链路）、commerce-real-backend（真实后端 buyer→seller fulfill→buyer delivery 全链路，**无环境变量默认跳过**）
- playwright.config：baseURL 4173（vite preview webServer）、本地 chromium 覆盖

## 10. 审查发现（前端侧）

1. `src/components/admin/AdminManagement.test.tsx` **无对应源组件**（孤儿测试）
2. `StorefrontMediaFallback.test.tsx` 纯测试文件（无独立源组件）
3. `GalleryHomePage` 未使用 feature_flags（storefront 入口依赖路由守卫）
4. `command_palette.ts` 等 6 个桌面组件零生产消费方（待接线）
5. 前端 15 投影域含 `stats`——服务端不下发该域（白名单校验仅前端）；服务端实际 14 域

## 11. 深度精细扫描轮（2026-08-11，75 项）

6 组并行探索（api/stores+hooks/pages/核心组件/业务组件/入口+i18n），清单见 `docs/reports/frontend-fine-scan-2026-08-11.md`。修复 7 组全部落地：

- **高危 2**：main.tsx 加 ErrorBoundary（白屏恢复）；SellerGalleryEditor key 含编辑值导致输入失焦
- **竞态治理**：useCommerceOrders 请求序号守卫、RealtimeContext recover 10s 超时+失败暴露、StorefrontCartPage 行级在途锁、SellerOrdersPage 单槽守卫、useThumbnailCache pending 去重+LRU
- **错误面**：Browse/Detail/Checkout/Delivery/Wishlist/BuyerOrders 等 8 页补错误态+重试；ShareReceivePage 429 分支；SellerAuthContext 503/网络错误区分
- **契约**：client.ts 全请求超时（30s/下载 5min）+ 429 头部透传 + 非 JSON 体分类；shares.ts id 编码
- **入口**：BrowsePage/DetailPage/GalleryHomePage 懒加载；catch-all 404 页；FeatureFlagRoute 禁用不再连环跳 /login；index.html 内联主题脚本消除 FOUC；html lang 随语言更新
- **i18n**：新增约 25 组三语 key（parity 测试守护 547 key 一致）；t() 占位符 replaceAll；app.title 接入 document.title
- **a11y**：ContextMenu role=menu/menuitem+实测 clamp、TagChip 键盘可达、Modal aria+body 滚动锁、FileToolbar aria-label、StorefrontShell aria-expanded

**未修（记录）**：admin 组件未挂路由（D2 接线项）、单文件下载 window.open 契约（A4，被契约测试钉死）、后端双重 unquote（A9 契约风险）、BuyerOrders 分页（需后端 cursor）。

**验证**：vitest 585/585 + tsc strict 0 错误 + i18n parity 5/5 + 后端 pytest 全量绿。
