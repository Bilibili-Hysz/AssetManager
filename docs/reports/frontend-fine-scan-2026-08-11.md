# webui 前端深度精细扫描清单（2026-08-11）

> 6 组并行探索（api / stores+hooks / pages / 核心组件 / 业务组件 / 入口+i18n），覆盖 webui/src 全部 196 文件 / 19837 行。
> 共 **75 项**：高 2 / 中 24 / 低 49（3 处跨组重复已合并：LoginPage ?key=、SellerProductsPage 中文确认、admin 未接线）。
> 前端测试：vitest 3.2.6 + @testing-library/react；后端 pytest 基线 3076 passed（xdist）。

## 高危（2）

| # | 位置 | 问题 |
|---|---|---|
| H1 | `main.tsx:1-10` | 无 ErrorBoundary：React.lazy chunk 加载失败/运行时错误 → 整树卸载白屏无恢复（Suspense 不捕获 lazy 错误） |
| H2 | `components/storefront/SellerGalleryEditor.tsx:126` | 画廊路径行 key=`${index}-${path}` 含编辑值：每敲一键 key 变化 → 整行卸载重挂 → 输入框失焦，路径输入不可用 |

## 组1 api 层（中 2 / 低 7）

| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| A1 | 中 | `api/client.ts:39-265` | 所有请求（JSON/Blob/进度流）无超时：后端半死时 fetch 永久挂起，loading/进度条无限转 |
| A2 | 中 | `hooks/useThumbnailCache.ts:39-60` | 内存缓存无上限（MAX_CACHE=300 只约束 sessionStorage 副本）；persist 失败后保留无界 map |
| A3 | 低 | `api/client.ts:105` | 200 + 非 JSON 体时 json() 裸抛 SyntaxError，绕过 ApiError 体系 |
| A4 | 低 | `api/files.ts:18-21` | 单文件下载用 window.open：403/429/503 时新标签页显示 JSON，无错误面 |
| A5 | 低 | `api/files.ts:35` | revokeObjectURL 在 click 后 0ms 释放，Firefox/Safari 大文件下载可能中止 |
| A6 | 低 | `api/shares.ts:13-16` | share id 未 encodeURIComponent（shop.ts 全部编码，不一致） |
| A7 | 低 | `api/client.ts:84-86` | 429 硬编码 "Rate limited"，丢失 Retry-After/配额细节 |
| A8 | 低 | `stores/AuthContext.tsx:84-89` | 任何 401（含登录失败）触发全局身份重置：密码错时清缓存+全组件级联重挂载 |
| A9 | 低 | 后端 `routes/downloads.py:117`、`gallery.py:26-32` | 对 match_info 已解码路径再 unquote（双重解码）——文件名含字面 %XX 序列时路径解错（契约风险，前端编码正确） |

## 组2 stores+hooks（中 4 / 低 8）

| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| B1 | 中 | `hooks/useCommerce.ts:273-295` | useCommerceOrders.refresh 无请求序号/abort 守卫：并发刷新旧响应覆盖新数据 |
| B2 | 中 | `hooks/useCommerce.ts:51-57` | isThumbnailPath 对无扩展名路径误判 false（`lastIndexOf('.')===-1` 时 slice(-1) 取尾字符，死分支）：无扩展名封面全部缺失（Node 实测） |
| B3 | 中 | `stores/SellerAuthContext.tsx:41-44` | refresh catch-all 把 503/网络错误当"未启用"：SellerAccessGate 误显示"功能未启用"，无重试 |
| B4 | 中 | `stores/RealtimeContext.tsx:94-144` | recover() 裸 fetch：无超时/abort，失败被 catch 静默吞 → recoveryRef 持挂起 promise，后续 invalidation 全部去重到同一挂起点，页面数据持续陈旧 |
| B5 | 低 | `stores/AuthContext.tsx:181-199` | value 无 useMemo：App 级 state 变化（如 Ctrl+K）触发全树消费者重渲染 |
| B6 | 低 | `stores/AuthContext.tsx:165-179` | 非 503/网络错误（500/me 失败）静默降级 guest 无提示；重连成功不广播刷新 |
| B7 | 低 | `stores/AuthContext.tsx:52,70` | permissions 死状态：初始 [] 从未填充，调用方误以为有权限数据 |
| B8 | 低 | `stores/RealtimeContext.tsx:191-200` | identity 变更 effect 渲染后运行：变更帧内新 identity+旧 cursor；注册表条目依赖卸载清理 |
| B9 | 低 | `hooks/useCommerce.ts:241-256` | useCommerceCatalog 有序列号无 abort：unmount 后 in-flight 继续 setState |
| B10 | 低 | `hooks/useThumbnailCache.ts:48-63` | 并发 loadThumbnails 重叠路径无去重（重复 batch）；持久化按插入序淘汰非 LRU |
| B11 | 低 | `hooks/useFavorites.ts:224-233` | remove 失败回滚 append 到末尾而非原位（removedIndex 未用） |
| B12 | 低 | `hooks/useInvalidation.ts:12` | effect 依赖整个 realtime context value：每次 cursor 变化全量重新注册 |

## 组3 pages（中 6 / 低 12）

| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| C1 | 中 | `pages/LoginPage.tsx:57-65` | URL ?key= 自动登录失效（effect 闭包 accessKey 仍空串 + authMode 初值 none）【组3+组4 重复】 |
| C2 | 中 | `pages/StorefrontProductPage.tsx:105-113` | createOrder 无进行中防重：连点弹窗按钮/免费获取按钮 → 重复订单 |
| C3 | 中 | `pages/StorefrontCartPage.tsx:136` | 数量每次按键立即发请求无防抖无在途锁：响应乱序覆盖成错误数量 |
| C4 | 中 | `pages/SellerProductsPage.tsx:93` | 硬编码中文 window.confirm【组3+组6 重复】 |
| C5 | 中 | `pages/BrowsePage.tsx:353-742` | 多处硬编码英文（Failed to filter by tag / Download link copied / Tag: / Copy download link） |
| C6 | 中 | `pages/StorefrontPage.tsx:26` | categories 每次渲染 O(n²)（map 内 filter 全列表）未 memo |
| C7 | 低 | `pages/BrowsePage.tsx:665-669` | 列表加载错误态无重试按钮 |
| C8 | 低 | `pages/DetailPage.tsx:60-61,309` | catch 一律 setData(null)：网络错误与不存在混淆显示 not_found，无重试 |
| C9 | 低 | `pages/StorefrontCheckoutGroupPage.tsx:167-175` | loadFailed 无重试；描述行误用 checkout_group_missing 文案 |
| C10 | 低 | `pages/StorefrontCheckoutPage.tsx:125` | 订单加载失败显示"未找到"无重试 |
| C11 | 低 | `pages/StorefrontDeliveryPage.tsx:20-38` | token 缺失时 loading 永 true（初始 true effect 提前 return 不复位）；失败无重试 |
| C12 | 低 | `pages/StorefrontBuyerOrdersPage.tsx:105-106` | loadFailed 无重试；ORDER_LIMIT=50 无分页，超 50 条无法查看 |
| C13 | 低 | `pages/StorefrontWishlistPage.tsx:18-20` | 收藏加载失败静默吞（catch 空），空列表误导 |
| C14 | 低 | `pages/ShareReceivePage.tsx:91-108` | 密码输入框不在 form 内回车无法提交；getInfo 失败无重试 |
| C15 | 低 | `pages/LandingPage.tsx:103-105` | summaryText 硬编码 'asset(s)' 单复数未走 t() |
| C16 | 低 | `pages/SellerOrdersPage.tsx:24-67` | pendingId 单槽：A 行 finally 提前解锁 B 行按钮，可并发提交 |
| C17 | 低 | `pages/SellerDashboardPage.tsx:15-18` | 统计卡片加载前渲染 0 值无 loading/error 态 |

## 组4 核心组件（中 4 / 低 8）

| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| D1 | 中 | `pages/LoginPage.tsx:57-65` | 【同 C1】 |
| D2 | 中 | `layout/AppHeader.tsx:188` + `App.tsx` | Admin 按钮无 onClick 且无 /admin 路由：管理界面 UI 完全不可达【组4+组5 印证 admin 未接线】 |
| D3 | 中 | `files/MasonryView.tsx:173-204` | 内联 columnCount=4 优先级高于 <style> 媒体查询：三个响应式断点全失效 |
| D4 | 中 | `gallery/GalleryCard.tsx:30` | 每卡各自 useQuota（挂载即请求）：几百卡片 = 几百次重复配额请求；无 memo |
| D5 | 低 | `viewer/ImageViewer.tsx:18` | React 18 wheel passive 监听：preventDefault 无效，滚轮缩放时背景滚动 |
| D6 | 低 | `viewer/ImageViewer.tsx:18` | 触摸双击缩放被 dblclick 事件抵消（pointerup 放大后浏览器合成 dblclick 又反转） |
| D7 | 低 | `layout/AppHeader.tsx:87-92` | Escape 关闭菜单 onKeyDown 挂在菜单 div（焦点在触发按钮时无效），与 Header.tsx 行为不一致 |
| D8 | 低 | `files/MasonryView.tsx:145` | 收藏按钮 opacity 仅 hover 驱动，无 focus-visible 规则（键盘聚焦不可见） |
| D9 | 低 | `pages/LoginPage.tsx:331-447` | key 模式仍显示注册入口；password 模式访客链接死链（被 ProtectedRoute 弹回） |
| D10 | 低 | `pages/DetailPage.tsx:256` | 项目缩略图 <img> 无 loading="lazy"：大项目进页全量请求 |
| D11 | 低 | `files/FileToolbar.tsx:51-62` | 升/降序按钮无 aria-label；排序 select 无 label |
| D12 | 低 | `pages/LoginPage.tsx:238` | key 输入框 Enter 直调 handleKeyLogin 绕过 loading 检查，连按并发提交 |

## 组5 业务组件（高 1 / 中 7 / 低 6）

| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| H2 | 高 | `storefront/SellerGalleryEditor.tsx:126` | key 含编辑值 → 输入失焦（见高危表） |
| E1 | 中 | `pages/ShareReceivePage.tsx:54-58` | 口令验证 catch 全当密码错误：429 显示 "Invalid password" 误导；i18n rate_limited key 无引用（死 key） |
| E2 | 中 | `admin/UserManagement.tsx:37-42` | 停用/启用无确认无 pending 无失败反馈；连点发相反请求 |
| E3 | 中 | `admin/ShareManagement.tsx:37-42` | 删除链接（永久）无确认无加载态静默失败；连点重复删除 |
| E4 | 中 | `admin/InviteManagement.tsx:47-52` | 撤销邀请码无确认失败静默；连点双 revoke；admin 组件整体未挂载路由（死代码待核实） |
| E5 | 中 | `storefront/BuyerDeliveryDownloadButton.tsx:72` | revokeObjectURL 在 setTimeout 0 后立即撤销（Firefox 大文件可能取消）；失败重试 key 不清空（一次性 ZIP 重试被拒） |
| E6 | 中 | `shares/ShareDialog.tsx:39-92` | 多处硬编码英文；expiresHours/maxDownloads 仅靠 HTML min/max 不阻止超界值（-5/99999 直接提交） |
| E7 | 中 | `ui/Modal.tsx:33,51` | aria-label 硬编码英文；打开期间无 body 滚动锁 |
| E8 | 低 | `tags/TagChip.tsx:21-26` | span 无 role=button/tabIndex/键盘事件；移除按钮无 aria-label |
| E9 | 低 | `ui/ContextMenu.tsx:55-69` | 视口裁剪硬编码估算（innerWidth-200、items*40）小窗口越界；无 role=menu 语义 |
| E10 | 低 | `ui/DownloadProgress.tsx:24` | total===0 时 NaN 宽度（防御性缺失，当前调用方已转 null） |
| E11 | 低 | `storefront/StorefrontShell.tsx:63` | 移动端菜单无 aria-expanded/aria-controls；外部点击/Escape 不关闭 |
| E12 | 低 | `admin/OnlineUsers.tsx:45` + `storefront/ProductCard.tsx:76-96` | key 用索引；生命周期按钮连点双发（删除有 confirm 兜底，归档/恢复无） |

## 组6 入口+i18n（高 1 / 中 1 / 低 9）

| # | 严重度 | 位置 | 问题 |
|---|---|---|---|
| H1 | 高 | `main.tsx:1-10` | 无 ErrorBoundary（见高危表） |
| F1 | 中 | `App.tsx:8-12` | 懒加载不彻底：BrowsePage(763 行)/DetailPage/GalleryHomePage eager 打进主包（445KB 首屏） |
| F2 | 低 | `index.html:2` + `i18n/index.ts:41-46` | html lang 硬编码 en 且 setLang 不更新；无内联主题脚本 → 浅色主题 FOUC |
| F3 | 低 | `App.tsx:154` | catch-all 无 404 页静默跳首页；FeatureFlagRoute 禁用时连环跳 /login |
| F4 | 低 | `pages/LoginPage.tsx:82,97,142` | 非 Error 分支英文 fallback 未走 t()（auth.login_failed 已存在） |
| F5 | 低 | `types/api.ts:111` | GalleryEntry.parent_path 标 string|null 但后端恒为字符串 ""（语义混淆，无实际 bug） |
| F6 | 低 | `i18n/index.ts:35` | t() 占位符 replace 只替换首个出现（当前无重复占位符用例，潜伏） |
| F7 | 低 | `i18n/en.ts:2` | app.title 死 key（document.title 从未更新） |
| F8 | 低 | `index.css:104-106` | --z-drawer=50 与 --z-modal=50 同值；DownloadProgress 硬编码 z-[60] 而 token 定义 --z-progress=80：z 语义脱节 |
| F9 | 低 | `types/api.ts` 等 | 后端 files 列表额外返回 is_project 字段前端未声明（无害） |

## 修复分组建议（文件集互不相交）

| 组 | 文件 | 项 |
|---|---|---|
| A | `hooks/useCommerce.ts`、`hooks/useThumbnailCache.ts`、`hooks/useFavorites.ts`、`hooks/useInvalidation.ts` | B1、B2、B9-B12、A2、B10 |
| B | `api/client.ts`、`api/files.ts`、`api/shares.ts` | A1、A3-A7 |
| C | `stores/AuthContext.tsx`、`stores/RealtimeContext.tsx`、`stores/SellerAuthContext.tsx` | B3-B8、A8 |
| D | `pages/` 13 文件 | C1-C17、D9、D12、F4 |
| E | `components/` 15 文件 | H2、D2-D8、D10-D11、E1-E12 |
| F | `main.tsx`、`App.tsx`、`i18n/index.ts`、`types/api.ts`、`index.css`、`index.html` | H1、F1-F3、F5-F8 |

**确认无问题**：i18n 三语 547 key 完全一致（含 parity 测试守护）；路由守卫稳健；API 契约抽查（info/cart/catalog/orders/gallery/favorites）全部吻合；tsconfig strict 全开；XSS（页面层无 dangerouslySetInnerHTML、InfoPanel 外链白名单）；WS 指数退避；登出 identityGeneration 全状态重置。
