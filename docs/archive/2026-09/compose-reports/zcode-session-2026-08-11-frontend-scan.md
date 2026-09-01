# ZCode 会话汇总 — webui 前端深度精细扫描轮（2026-08-11）

> **来源会话**：ZCode（deepseek-v4-flash），2026-08-11
> **任务**：主线审查"由后端到前端"最后一环——前端深度精细扫描 + 修复
> **性质**：全程未 commit；改动与预存 WIP 混合在工作区
> **验证**：vitest 585/585 + tsc strict 0 错误 + i18n parity 5/5 + 后端 pytest 3076 passed（xdist 95s）

## 1. 扫描（75 项：2 高 / 24 中 / 49 低）

6 组并行探索覆盖 webui/src 全部 196 文件 / 19837 行；清单 `docs/archive/2026-09/reports-superseded/frontend-fine-scan-2026-08-11.md`。

**高危 2**：main.tsx 无 ErrorBoundary（白屏无恢复）；SellerGalleryEditor 画廊路径行 key 含编辑值 → 输入失焦不可用。

**中危代表**：useCommerceOrders 无竞态守卫、RealtimeContext recover 裸 fetch 无超时、isThumbnailPath 无扩展名误判（Node 实测）、client.ts 全请求无超时、MasonryView 内联 columnCount 使响应式失效、GalleryCard 每卡 useQuota 请求风暴、createOrder/购物车数量无防重、ShareReceivePage 429 误报密码错误、StorefrontDeliveryPage loading 永 true。

## 2. 修复（7 组 + 主代理收尾）

| 组 | 范围 | 关键修复 |
|---|---|---|
| A | hooks 4 文件 | useCommerceOrders 序号守卫、isThumbnailPath 路径段判断、catalog abort、thumb cache LRU+pending 去重+上限、favorites 原位回滚、useInvalidation 稳定依赖 |
| B | api 3 文件 | 全请求超时（30s/下载 5min，手动 AbortController 组合兼容 ES2020）、429 头部透传、非 JSON 体分类、share id 编码（A4 window.open 契约钉死跳过） |
| C | stores 3 文件 | recover 10s 超时+recoveryFailed 暴露、identity useLayoutEffect、SellerAuthContext 503 区分、value useMemo、permissions 死状态收敛 |
| D1 | 核心页面 5 文件 | LoginPage ?key= 自动登录修复（显式传参+authMode 依赖）、注册入口策略、BrowsePage i18n+重试、DetailPage 错误态区分、LandingPage 复数 key、ShareReceivePage form 提交+429 分支 |
| D2 | 商店页面 11 文件 | createOrder 防重、购物车行级在途锁、categories O(n²)→O(n)、8 页错误态+重试、DeliveryPage loading 修复、SellerOrders 单槽守卫、SellerDashboard 骨架 |
| E | 组件 17 文件 | SellerGalleryEditor 失焦（高）、MasonryView 响应式+focus-visible、ImageViewer wheel passive/触摸双击、ContextMenu 实测 clamp+role、Modal aria+滚动锁、TagChip 键盘、ShareDialog i18n+clamp 校验、admin 三组件确认+pending+toast、DownloadButton revoke 延迟+新 key、ProductCard 本地锁 |
| F | 入口/i18n | ErrorBoundary（新建）、NotFoundPage（新建）、懒加载 3 页、FeatureFlagRoute 不再连环跳、FOUC 内联脚本、html lang/文档标题、占位符 replaceAll、parent_path 类型、z-index token |

**i18n**：新增约 25 组三语 key（D1/D2/E 三组并发加 key，parity 测试最终守护 547 key 一致）。

## 3. 关键问题

- **31 个测试配套更新**（主代理）：admin 四文件（Toast mock + confirm stub）、ContextMenu（menuitem role + clamp 实测值）、TagChip（双 button role）、BrowsePage（menuitem + i18n key）、LoginPage（注册入口策略反转）、BuyerDeliveryDownloadButton/StorefrontCheckoutPage（revoke 延迟 + 重试取新 key 语义）。
- **quota cookie flaky 定位**（后端 1/6 概率失败）：测试篡改 HMAC 签名**末尾** base64 字符——32 字节签名的 43 字符 base64 中末字符仅贡献 4 比特，`A`/`B` 高 4 位相同 → ~1/16 概率篡改被解码器忽略、签名仍通过。修复：改篡改 cookie_id 段（hex 必变）。**产品 HMAC 实现正确，纯测试手法缺陷。**
- **vitest 环境**：仓库路径含 `~` 导致 vite-node 拒绝加载（`isFileLoadingAllowed` Windows 检查）——必须用 `node scripts/run-vitest.mjs`（subst 映射）；`npx vitest` 裸跑基线即失败。
- **并发 WIP**：7 组并行改同一工作树（i18n 三文件多组写），以 parity 测试 + 主代理收尾校验解决。

## 4. 后续建议

- **admin 面板接线**（User/Share/InviteManagement 组件已完备+确认/反馈，仅缺路由与菜单 onClick——后端 users/shares/invites API 已存在）
- **A4**：单文件下载 window.open → blob（需同步改契约测试与 BrowsePage handleDownload）
- **A9**：后端 downloads.py/gallery.py 双重 unquote 移除（文件名含字面 %XX 时路径解错）
- **BuyerOrders 分页**（后端 cursor 支持）
- 性能轮：M6a-8 get_home 全表扫描、DB 迁移 v24
