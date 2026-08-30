# AssetManager WebUI 架构与设计评审报告

> 日期：2026-08-29 · 对象：`webui/`（React 18.3 + Vite 7 + TS 5.6 strict + Tailwind 3，aiohttp LAN 托管 SPA）
> 方法：2 路代码审查（架构数据层 / 设计模式 a11y i18n 响应式）+ 本机验证（`npm run build` ✓、自带 axe 门禁 23 扫描全绿、Playwright 真实 Chromium 截图 10 张）+ 未定义令牌等关键结论经主会话 grep 复核
> 视觉证据：`tmp/ux_review/webui/*.png`（mock API + vite preview；截图脚本 `webui/e2e/_ux_shots.spec.ts`，未跟踪，留删自便）

---

## 一、总评

**架构成熟度显著高于典型个人项目：零重量依赖 + 三层契约防漂移门禁 + axe 自动化可达性门禁，是这套 WebUI 最强的三块资产。** 数据层自研但质量接近生产级库。主要问题集中在：**5 个被引用却从未定义的 CSS 令牌（功能性 bug）**、**RealtimeContext 全树重渲染隐患**、**卖家表单静默校验失败**、以及**三套并行样式体系导致的主题覆盖债**。

## 二、架构评审

### 依赖与构建
- 运行时依赖仅 4 个：react / react-dom / react-router-dom 7.18 / lucide-react。**无 redux/react-query/axios**，查询缓存自研（`src/cache/queryCache.ts` + `useCachedQuery` + `QueryCacheContext`）。
- 自研查询层覆盖 TanStack Query 核心子集：JSON key、in-flight 去重、useSyncExternalStore 细粒度订阅、gc 300s、乐观更新、错误保留旧数据；且 `scripts/check_frontend_data_fetch.py` **禁止 pages 直接 import api//fetch**，强制走共享数据层。
- 构建：26 页全部 `React.lazy` 按页分包；主 bundle 348K（gzip 109K），dist 共 859K——LAN 单机场景合理。`npm run build` 本机实测通过（6.1s）。
- TS 全套最严格（strict + noUncheckedIndexedAccess 等）；覆盖率门禁 statements 75/lines 80。

### 防漂移体系（同类项目中罕见的三层契约门禁）
1. `scripts/gen_ts_types.py`：AST 解析后端 `lan/dto.py` 冻结 dataclass → 生成 `src/types/contracts.ts`，CI `--check` 漂移即红；
2. `src/api/public-contracts.test.ts`：以 `tests/contracts/lan_public_contracts.json` golden 做 key 集合全等断言；
3. `scripts/gen_web_tokens.py --check`：主题令牌从 `Assets/Themes/*.json`（与桌面共享单一来源，dark=D_Navy / light=L_Dawn）生成 CSS 变量，pre-commit + CI 双防。
- CI lint job 另有 9 项静态门禁（boundaries/layers/route_capabilities/doc_stats 等）。

### API 层（src/api/，13 个工厂模式完全统一）
- fetch 包装：30s 默认超时（AbortController 手工实现，ES2020 约束）；Blob 下载**双预算**（30s 空转 stall + 30min 绝对上限）——优于常见固定超时；仅幂等 GET 重试（1+2 次、指数退避、尊重 Retry-After）；单点错误分类（401/403/429/503→专用错误类）；200 非 JSON 体转结构化 ApiError。
- 429/503 经 `degradationBus` 节流 10s 桥接全局 toast。

### 实时链路
- `useWebSocket`：退避重连 1s→30s 封顶、无限重试、无 jitter；支持单连接多订阅者 fanout。
- `RealtimeContext` 完整实现"HTTP `/api/revision` 权威游标 + WS 仅失效提示"：epoch/revision 缺口检测 + 恢复意图重试一次、恢复超时 10s、恢复失败 fail-open 通知消费者、身份翻转用 `key={identity}` 强制重建连接——设计完善且有详注。
- **缺陷**：每 tab 一条独立 WS（无 SharedWorker/BroadcastChannel；favorites 已用 storage 事件跨 tab，WS 却没有）。

### 状态与安全
- 4 个 Context（Auth/SellerAuth/Realtime/ShopBuyer）职责清晰；卖家用独立 ApiClient 刻意不挂全局 401（独立 cookie 会话）。
- **无任何 JS 可读凭证**：HttpOnly cookie 会话；localStorage 只存偏好；sessionStorage 缩略图缓存按身份命名空间隔离、登出清除。XSS 面小。
- **性能隐患（本报告最重的架构问题）**：`RealtimeContext` 的 cursor 在 context value 里（RealtimeContext.tsx:246），而全部数据组件经 `useInvalidation`→`useRealtimeContext` 订阅它——**每条 WS 失效事件都重建 value，触发全 app 数据组件重渲染**（快照引用相等使 render 便宜，但函数体全量执行；gallery 千级条目下是隐患）。修法：cursor 拆独立 context 或改外部 store + useSyncExternalStore（queryCache 已有现成模式）。
- AuthProvider 包全树、value 15 字段，任何状态变化级联；与 RealtimeProvider 形成层级硬耦合（App.tsx:132-138 的缩进错位已暴露嵌套复杂度）。

## 三、设计评审

### 令牌与主题
- 管线正确且有纪律：生成令牌 + `--color-accent-text` 文本安全色（index.css:18-42，WCAG ≥4.6:1）+ 对比度修正上收主题 JSON 单源。
- **【功能性 bug，已双人独立确认 + 主会话 grep 复核】5 个被引用令牌全仓零定义**：
  - `--color-overlay`：Modal.tsx:35、AppLayout.tsx:89,144（移动抽屉遮罩）、CommandPalette.css:10、index.css:294 引用 → **模态/抽屉/命令面板遮罩背景透明**，只剩 backdrop-blur；light 下 `bg-black/95` 反向映射到该未定义变量后完全透明；
  - `--color-panel` / `--color-heading`：AdminPage.tsx:37,39,52,56（生成器已把旧 JSON 键改名映射为 surface/text）→ 管理页面板无底色；
  - `--color-surface-muted`：SellerGalleryEditor.tsx:101-114。
  - 修法：生成器补 overlay/surface-muted 令牌 + 清理 AdminPage 旧名；`var(--color-overlay, rgba(0,0,0,.5))` 兜底亦可，但应修生成器为本。
- **三套样式体系并行**：工作区 Tailwind 手拼、storefront/gallery 各自 CSS 类系统、AdminPage 全内联 style。184 处 `slate-/indigo-` 原生色类依赖 index.css:158-295 约 **130 条 light 反向映射选择器**打补丁；`dark:` 前缀 0 处；z-index 三种写法并存（index.css:97-106 注释自认）；断点十档不统一（375/390/430/650/680/700/760/768/900/1100）。
- 无共享基础组件（无 Button/Input/Card/IconButton）：同一品牌色三处独立定义（ErrorBoundary.tsx:60 与 NotFoundPage.tsx:22 内联 `#4f46e5` vs tailwind `brand-600`）。

### 可达性
- **axe 门禁真实有效**：`wcag2a/aa + 21a/aa` 全量断言零违规，10 路由 × 明暗双主题 + 3 交互态，本机复跑 23 passed。
- 键盘质量高：useDialogFocus 焦点陷阱 + Esc + 焦点返还（Modal/CommandPalette/移动抽屉全接入）、ContextMenu roving focus、**面板拖拽把手支持键盘调宽**（AppLayout.tsx:76-79）、单键快捷键按 WCAG 2.1.4 限定作用域。
- **缺口**：DESIGN.md:31 的 44px 承诺只在 Gate 兑现——MasonryView 收藏钮 24×24（:146）、InfoPanel 图标钮 ~22-26px（:123,164,185）、Storefront 图标钮 40×40；axe 规则集未含 target-size，所以测试绿。a11y 扫描未覆盖 /admin、cart/checkout/delivery、**任何 Modal 打开态**——遮罩透明 bug 正是从这个缺口漏网的。

### i18n
- 机制强于桌面端：en.ts 定义 `I18nDict` 类型，zh/ja 强类型跟随；i18n.test.ts 断言**键集完全相等 + 占位符集合跨语言一致**——键奇偶由测试+类型双保险。
- 残留：InfoPanel.tsx:139,141（"Loading preview"/"Preview unavailable"）、LandingPage.tsx:485 sr-only、SellerGalleryEditor.tsx:101,104 aria-label、StorefrontCheckoutPage.tsx:152 订单状态英文枚举直出（同族 CheckoutGroupPage.tsx:14-22 已有 statusLabel 未复用）、BrowsePage.tsx:699 原始错误直出；动态键 `t(\`seller.status_${order.status}\`)`（SellerOrdersPage.tsx:92）不在守护内。无复数支持。

### 响应式与状态设计
- 工作区三栏↔抽屉切换处理细致（useMediaQuery 768px 单点、桌面面板状态还原）；375px 有 e2e 断言无横向溢出；移动底栏 + `.touch-target`。缺口：AdminPage 无任何窄屏适配；断点值未归一。
- 骨架屏为主（带 role=status + reduced-motion 降级）；storefront 空态带 CTA 是范本；**BrowsePage 空态仅一行文案无动作**（:708-711）。
- 结账流程质量高：行内 in-flight 锁防连点、幂等键按 cartId 持久化 sessionStorage、409 价格变更专门 UI、组收据退避轮询 1s→8s。**卖家表单校验全部静默 return**（SellerProductsPage.tsx:79-93）——用户只见按钮无响应，是全 UI 最差反馈点。投递页无"下载将消耗配额"事前警示。

### 视觉抽样实证（真实 Chromium 截图）
1. **Gate 文案连体 bug（根因已定位）**：渲染为"**Open Workspace**Search folders, filter tags…"且下方重复一个无样式"Open Workspace"链接——`LandingPage.tsx:498-504` 使用 `.gate-workspace-option/-copy/-link` 三个类，**LandingPage.css 里一条对应规则都不存在**，strong/span 内联粘连。明暗主题均复现。
2. Gate 明色下缩略图墙可见、暗色下几乎不可见（DESIGN.md 的签名元素在暗色失效，需真机复核强度参数）。
3. 移动端 375px：单列 + 底部动作栏（Menu/View/Info/Select）成立，但**卡片占位高约 420px 大面积空白**，"Reconnecting…"提示与底栏叠放。
4. WS 断线"Reconnecting…"琥珀点状态指示清晰；未 mock 的 `/api/tree` 失败时侧栏优雅降级（"No matching directories"）不白屏。
5. 商城页在残缺 mock 下触发 ErrorBoundary："An unexpected error occurred + Retry + Back to gallery"，兜底干净（该页 axe 未扫、且无逐段降级——数据形状异常即整页错误）。
6. 画廊 featured hero（渐变封面+三 CTA 分层：primary/secondary/ghost）视觉出色；详情页 hero/标签/备注结构完整。
7. mock 局限声明：BrowsePage 卡片缩略图未渲染（其走 useThumbnailCache/sessionStorage 路径，mock URL 形状未满足），该点不计入结论。

## 四、修复优先级建议

**P0（功能 bug，都是小修）**
1. 生成器补 `--color-overlay`（建议 rgba(0,0,0,.55)）/`--color-surface-muted` 令牌；AdminPage 旧名 `--color-panel/--color-heading/--color-muted` 改为新令牌（或生成器加别名）；顺手把 Modal 打开态纳入 a11y.spec 扫描（本次漏网主因）。
2. Gate `.gate-workspace-*` 补 CSS（copy 区改 flex column + gap）或删冗余重复链接。
3. 卖家表单校验加字段级错误 + aria-invalid，至少 toast 原因。

**P1（结构性）**
4. RealtimeContext cursor 拆独立 context/外部 store（消除全树重渲染）。
5. 抽 3-4 个基础组件（Button/IconButton/Input/EmptyState）+ 新组件强制语义令牌；z-index 与断点归一。
6. `.touch-target` 收口小图标钮 + axe 规则集加 wcag22 target-size。

**P2（打磨）**
7. i18n 残留清零 + 动态键测试；BrowsePage 空态行动化；投递页配额事前警示；WS 加 jitter + BroadcastChannel 共享；AdminPage 窄屏适配。

## 五、不应改动的优点（保持）

自研查询层与三层契约门禁不要替换成外部库——它们与 9 项 CI 门禁、check_frontend_data_fetch 强制已成体系；cookie 会话模型与身份翻转失效边界（QueryCacheContext.tsx:6-21 三条契约）保持现状；fail-open 缓存错误策略与降级 toast 节流是正确取舍。
