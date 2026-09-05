# 05 · WebUI 前端层（webui/，React 18 + Vite + TS）

> 状态：**DATED ANALYSIS（2026-09-04 实测快照）** · deep-analysis 系列之一，索引见 [README.md](README.md)。
> 方法：并行只读勘察代理全量扫描 `webui/`（105 个生产 ts/tsx、14,548 行），配置/页面/机制逐文件深读，行号锚点为当前工作树。

---

## 1. 技术栈实测

### 1.1 依赖面（刻意"小而深"）

- **运行时依赖仅 4 个**（package.json）：`react@18.3.1`、`react-dom@18.3.1`、`react-router-dom@7.18.2`、`lucide-react@0.460`。**无 Redux/Zustand/TanStack Query/Axios/msw**，状态/请求/缓存全部自研。
- 脚本：`dev` / `build`（`tsc -b && vite build`）/ `test`（经 `scripts/run-vitest.mjs`）/ `typecheck` / `coverage` / `test:e2e`（Playwright）/ `check:colors`（hex 棘轮门禁）。

### 1.2 配置要点

| 配置 | 要点 |
|---|---|
| vite.config.ts | `@`→`./src` 别名；`preserveSymlinks: true`；dev 代理 `/api`、`/ws`→127.0.0.1:8080；测试段即 Vitest 配置（无独立 vitest.config）；覆盖率阈值 statements 75 / lines 80 / functions 70 / branches 65；CI retry=1 |
| tsconfig.json | `strict + noUnusedLocals + noUnusedParameters + noUncheckedIndexedAccess + noFallthroughCasesInSwitch`；target **ES2020**（注释明示兼容旧浏览器——全库避免 `AbortSignal.timeout`、`replaceAll` 等 ES2021+ API，client.ts:114-123、i18n/index.ts:24-26 有替代实现注释） |
| tailwind.config.ts | `darkMode: 'class'`；brand indigo 色板 + Inter 字体。Tailwind 只承担布局/间距层，品牌色实际走 CSS 变量 + `themes.generated.css`（`data-am-theme` 块） |

---

## 2. src/ 结构全图（行数实测）

```
src/
├── main.tsx            入口（StrictMode + ErrorBoundary + 全局错误上报）
├── App.tsx (145L)      路由 + Provider 嵌套 + Ctrl+K/? 快捷键
├── index.css (405L)    设计变量、motion-safe、storefront 残留类
├── api/        16 文件   948L   15 个领域工厂 + client + errors + degradationBus
├── pages/      10 页面   3271L  10 条路由页面
├── hooks/      17 个    1735L  数据/主题/i18n/缩略图/WS 横切原语
├── stores/      2 个     553L  AuthContext(296) + RealtimeContext(259)
├── components/ 42 组件   5467L  admin/auth/files/gallery/layout/media/shares/tags/ui/viewer
├── i18n/        4 文件   1400L  en/zh/ja 词典 + 运行时
├── cache/       3 文件    219L  自研微型 TanStack-Query（queryCache + invalidation + Context）
├── shortcuts/   1 文件     44L  registry.ts 快捷键单一数据源
├── tokens/      2 生成物         themes.manifest.generated.ts + themes.generated.css
├── types/       2 文件    551L  api.ts(429L 手写) + contracts.ts(122L 自动生成)
└── utils/       4 文件    162L  backoff/concurrency/download/collectionSnapshot
```

组件子域：admin 5（用户/邀请/分享/活动/在线）、auth 1、files 7（Breadcrumb、FileToolbar、LayeredPreview、MasonryView、ProjectCard、ProjectGrid、ProjectList）、gallery 6、layout 9（三栏工作台 + Header/Sidebar/InfoPanel/ResizablePanel/StatusBar/AmbientBackdrop）、media 1、shares 1、tags 1、ui 12（Modal/Toast/CommandPalette/ShortcutsDialog/ContextMenu/BottomSheet/Skeleton/EmptyState/ErrorBoundary/DownloadProgress）、viewer 2（ImageViewer、QuickLookOverlay）。

---

## 3. 核心机制详解

### 3.1 API 工厂层（15 工厂 + 唯一 fetch 出口）

- **架构**：`client.ts`（549L，唯一 fetch 出口）→ 领域工厂 `createXxxApi(api)` 返回类型化方法集（`type XxxApi = ReturnType<typeof createXxxApi>`）→ 页面**禁止直接 import**，由 `hooks/usePageApis.ts` 的 9 个 hook + `usePublicShareApi` 提供。
- **静态门禁**：Python 侧 `scripts/check_frontend_data_fetch.py` 强制 S2 边界（页面不得直连 api/工厂/fetch）。
- **类型双轨**：`types/api.ts`（手写 429L，面向 UI）+ `types/contracts.ts`（**由 `scripts/gen_ts_types.py` 从 `AssetsManager/lan/dto.py` 自动生成**，文件头 "do not edit"）——RuntimeCursor/InvalidationEvent/ProjectionDomain 即此来源。
- **contract 测试层**：15 个 `*.contract.test.ts` + `public-contracts.test.ts` 直接断言后端导出的 golden JSON（`tests/contracts/lan_public_contracts.json`）——"后端多吐一个字段=漂移失败"（如 `expect(user).not.toHaveProperty('password_hash')`）。
- **错误处理**（api/errors.ts 74L + client.ts:261-301）：401→`UnauthorizedError`（触发全局身份重置）、403→`ForbiddenError`、429→带 `Retry-After` 的 ApiError、503→`ServiceUnavailableError`、TypeError/TimeoutError→`NetworkError`；200 但非 JSON→结构化 ApiError。**仅幂等 GET 重试**（指数退避），写请求快速失败；429 优先按 Retry-After 等待。
- **降级总线** degradationBus.ts（50L）：429/503 → 10s/类节流的全局 toast。
- **下载三档超时**（client.ts:41-53, 159-186）：普通请求 30s 硬超时；Blob 下载用"停滞预算"（每 chunk 重置 30s stall + 30min 绝对兜底）；`postBlobWithProgress` 流式进度。
- **分享页客户端隔离**（usePageApis.ts:71-78）：为分享页建独立 ApiClient（无 onUnauthorized）——错误密码的 401 不会误杀访客会话。

### 3.2 两个 Context Store（状态管理取舍）

**AuthContext**（stores/AuthContext.tsx，296L）——会话/身份唯一权威：
- 初始化：`connect()` 先 GET `/api/system/info`（能力位/auth_mode/theme/feature_flags）→ auth_enabled 时再 `/auth/me`（HttpOnly cookie 对 JS 不可见，必须靠探测，:210-213）。
- **identityGeneration**（每次 principal 变化 +1）是全前端缓存隔离枢轴：query cache 清空、缩略图 sessionStorage 清空（`lan_thumb_cache:` 前缀）、WS 重建（RealtimeContext `key={identity}`）。
- 401 白名单 `AUTH_401_PATHS`（login/register/verify_key，:31）：登录失败≠会话过期。
- 网络失败保留 principal + `serviceUnavailable` 标志——**fail-open，不把闪断当登出**（:171-177）。
- 已知死字段 `permissions: []`（B7 注释，:43-51）——显式标注的债。

**RealtimeContext**（stores/RealtimeContext.tsx，259L）——WS 游标协议（见 3.3）。

**取舍**：不引入状态库/请求库的理由是领域语义需要精确控制（identityGeneration 清缓存、WS 恢复代数），代价是 273L 手写 `useCachedQuery`（dedup/GC/乐观更新/轮询/失效全自研）+ 1061L BrowsePage 巨组件。

### 3.3 WebSocket 失效推送消费端（epoch + revision）

- **传输层** `hooks/useWebSocket.ts`（127L）：原生 WS + 指数退避重连（1s→30s 封顶），`WebSocketTransportHost` 单连接扇出。
- **协议**：服务端两种事件——`runtime_ready`（携完整 cursor）与 `projection_invalidated`（epoch/revision/domains/paths）；WS 消息有 `isCursor/isEvent` 手写守卫（RealtimeContext.tsx:37-52，防畸形消息）。
- **单调游标推进**（RealtimeContext.tsx:166-219）：
  - `projection_invalidated` 且 revision 无缺口 → 直接推进 cursor 并按 domains 精准分发。
  - **检测到缺口** → 记录 `RecoveryIntent{targetRevision, retried}` → `recover()`（GET `/api/revision`，10s 超时）——**HTTP 快照为权威**，WS 只是失效提示。
  - **epoch 变更** → 旧数据不可信，先同步 `notify(null)`（消费者立即重取）再 recover。
  - 恢复结果校验：服务器回的 revision 反而 ≤ 本地且未达成目标未重试 → 补发一次 recover（:110-120）；恢复期间本地游标又被推进 → 重新发起。
  - **失败兜底**：恢复失败也 `notify(null)`，强制消费者各自重探（fail-open）。
- **消费端**：`hooks/useInvalidation.ts`（29L）+ `cache/invalidation.ts` 纯函数 `shouldInvalidate`（域交集 + 路径前缀匹配）；null 事件=全量失效。`useCachedQuery` 收到匹配事件 → refresh()（中止 in-flight 重取，旧数据保持可见不闪空态）。

### 3.4 认证流

- `LoginPage.tsx`（476L）三视图 `login | register | key`，由 `/api/info` 的 `auth_mode`（user/password/key/none）决定；注册含邀请码字段。
- 会话为 **HttpOnly cookie**（全部 `credentials: 'same-origin'`），前端无 token 存储。
- `ProtectedRoute.tsx`（23L）按 capability 门禁；auth_enabled=false 时访客有能力直接放行。
- 登出：fire-and-forget POST + generation+1 + 清缩略图缓存 + 身份重置。

### 3.5 两套三视图

| 界面 | 视图 | 实现 |
|---|---|---|
| BrowsePage（工作台） | grid / list / masonry（`am_view` 持久化） | ProjectGrid（分批渲染 80→+60，IntersectionObserver sentinel）、ProjectList、MasonryView（CSS 多列瀑布流） |
| Gallery 系列 | masonry / grid / compact（`am_gallery_view`） | GalleryTiledGrid（**实为等大方格 grid**，注释 "Uniform square grid for predictable artwork scanning"）|

- 目录封面懒注水：`useProjects.hydrateDirectories` POST `/api/files/summaries` 回填，带 listingGeneration 竞态防护（useProjects.ts:113-137）。
- 大列表分页：PAGE_SIZE=500 + loadMore（offset 追加 + path 去重）。

### 3.6 主题体系（三层）+ 三语 i18n

**主题三层**（设计线 A1）：
1. `useTheme.ts`（121L）：访客 light/dark 偏好（`am_theme`，含 legacy key 迁移），`prefers-color-scheme` 兜底。
2. `useServerTheme.ts`（141L）：**follow-the-owner**——`/api/info.theme_name` → `tokens/themes.manifest.generated.ts`（26 主题，由 `scripts/gen_web_tokens.py` 从 `Assets/Themes/*.json` 生成，**与 PySide 桌面端共享主题源**）→ `data-am-theme` 应用调色板；访客偏好只做模式覆盖；`index.html:9-40` 内联预绘脚本防 FOUC；未知主题 fail-open。
3. `App.tsx:48-64 AppAccentSync`：服务器 `theme_color` 退为兜底 accent。

**i18n**（无 i18next）：模块级单例 + `t(key,...args)` 点路径查找 + `{0}` 占位 + 缺 key 回退英文；`useSyncExternalStore` 订阅；`<html lang>`/document.title 随语言同步。实测 leaf keys：**en 417 / zh 419 / ja 419——en 比 zh/ja 少 2 个，存在轻微 key 漂移**（README 的 1060 为三语合计口径，与桌面端 i18n 是两套词典）。

### 3.7 移动端适配

- 单断点 `useMediaQuery('(max-width: 768px)')`（JS 驱动）。
- 面板降级 + **桌面状态记忆**（desktopPanelsRef + wasMobileRef，跨断点往返恢复，BrowsePage.tsx:114-145）；InfoPanel/Sidebar 在移动端装进 `BottomSheet`（**手写 touch 拖拽关闭，含速度判定**，BottomSheet.tsx:46-71）。
- 移动端单击目录即导航（MasonryView.tsx:81-84）；ImageViewer 支持双指 pinch、双击缩放（tap 间隔 <300ms 判定）、拖拽 pan。
- E2E 双向守门（375px 无横向溢出，app.spec.ts:82-93）。

---

## 4. E2E 覆盖表（6 个 Playwright spec，chromium-only）

| Spec | 测试数 | 覆盖场景 | Mock 方式 |
|---|---|---|---|
| app.spec.ts | 13 | 冒烟+韧性：路由 404、`/s/:token` 崩溃测试、响应式 375/1920 无溢出、暗色首绘、Tab 焦点、**API 全挂时不白屏** | 无 mock（专测纯前端降级） |
| a11y.spec.ts | 19 | **axe WCAG 2.1/2.2 A+AA 全路由 × dark/light 矩阵门禁**（violation 必须 `[]`）+ 交互态扫描 | page.route 全量 mock |
| webui-shell.spec.ts | 2 | Ctrl+K 命令面板开/关；375px 无溢出 | page.route |
| commerce-buyer.spec.ts | 7 | **死测试**：测 `/storefront/product/7` 等已剥离路由 | page.route |
| seller.spec.ts | 3 | **死测试**：测 `/seller` 等已剥离路由 | page.route |
| commerce-real-backend.spec.ts | 2 | 真实后端验收（需 `REAL_COMMERCE_BASE_URL` 否则 skip）——**指向已剥离功能** | 无 mock |

**重要发现**：`src/App.tsx:117-130` 根本没有 `/seller`、`/storefront/*` 路由，全 src 无 seller/shop 组件——**商城剥离后三个 commerce spec 未删除，属于会随导航到 NotFoundPage 而失败的死测试套件**（当前分支最明确的测试-代码不同步技术债）。仅 index.css:206-208 残留 `.storefront-*` 类。

---

## 5. 测试体系（Vitest）

- **组织**：同置 co-located 测试（89 个 `.test.ts(x)` 实测）；jsdom 环境。
- **不用 msw**：所有网络 mock 用 `vi.stubGlobal('fetch', ...)` 精确编排（client.test.ts:40-80 覆盖 TypeError→NetworkError、AbortError 保留、GET 退避重试序列、ReadableStream 分块下载超时等 10+ 契约场景）。
- **多层策略**：单元/组件（RTL）→ API contract（golden JSON）→ 样式治理（CSS 直接测试 + hex 棘轮）→ Python 侧静态边界门禁（check_frontend_data_fetch / check_inline_colors / check_boundaries）。
- **Windows 工程化细节**：`scripts/run-vitest.mjs` 用 `subst.exe` 临时映射空闲盘符跑测试再卸载——绕开 Vitest 在路径含 `~#%`（本仓库 `D:\~Vibe-Coding\...`）时的崩溃。

---

## 6. 治理文件

- **DESIGN.md**（91 行）：LandingPage（"Gate"）专属设计契约——视觉 token（`--gate-*`）、可访问性（44px 命中区、reduced-motion、375px 单列）、反模式清单（不做 feature-card 网格、第二 CTA、外链图）、**决策溯源**（每个决策记录 alternatives 与 tradeoff）。
- **webui-style-ledger.json**（9 行）：**内联 hex 颜色棘轮账本**（W0/W1）——每文件 `#hex` 字面量只能减少不能增加（豁免 `var(--name, #fallback)` 形态与带理由的注释），超限即 `check-inline-colors.mjs` exit 1。W3 已完成 113 个插画 hex 全迁 EmptyState.css 变量。

---

## 7. 构建产物托管（Python 端）

- `AssetsManager/lan/routes/pages.py:7 SPA_DIR = .../webui/dist`；七个处理器统一返回 `web.FileResponse(dist/index.html)`；**dist 缺失时 503**（pages.py:16-23）。
- `api.py:372-377 add_static("/assets", dist/assets)`。
- `build.py:35-55 webui_build()`：`npm ci && npm run build`；AssetManager.spec 将 webui/dist 打进 PyInstaller（注释：缺构建会同时打断打包与 LAN 分享）；release.yml 先 Build WebUI 后 PyInstaller。
- **注意**：aiohttp 不做 SPA fallback（`/nonexistent` 真回 404，app.spec.ts 专门测这一点）——页面路由靠 pages.py 逐条注册，**新页面必须前端路由与 pages.py 双注册**。

---

## 8. 弱点与技术债清单

| # | 问题 | 证据锚点 |
|---|---|---|
| 1 | **商城 E2E 死测试**（3 个 spec 指向已剥离路由） | App.tsx:117-130 无此路由；git log "商城剥离收尾" |
| 2 | **BrowsePage 巨组件**：1061 行、20+ useState/useRef，事件 handler 依赖项长达 9 项 | BrowsePage.tsx 全文 |
| 3 | **手写 query cache 复杂度接近临界**：gcTimer/isSameKeyRerun/订阅表独立等注释密度极高，每条注释对应真实踩坑 | queryCache.ts:1-26、useCachedQuery.ts:160-230 |
| 4 | **pages.py 与前端路由双注册耦合**（aiohttp 无 SPA fallback） | pages.py:26-52 |
| 5 | **Dead field `permissions`**（已知待清） | AuthContext.tsx:43-51 |
| 6 | **i18n 三语 key 漂移**：en 417 vs zh/ja 419 leaf keys | 实测 leaf 计数 |
| 7 | **单断点移动适配（768px）**：无平板中间形态 | AppLayout.tsx:48 |
| 8 | **hex 棘轮仅覆盖 1 个文件条目**，`var(--name, #fallback)` 豁免形态仍是迁移中间态 | webui-style-ledger.json、LandingPage.tsx:53-54 |
| 9 | **gallery "masonry" 语义不严谨**：实为 tiled grid；两套视图词汇撞名 | GalleryTiledGrid.tsx:10 |
| 10 | **RealtimeContext 恢复逻辑高复杂度**（RecoveryIntent/retried/responseLeavesGap 嵌套分支），有详尽注释与测试但心智负担大 | RealtimeContext.tsx:87-164 |
| 11 | **环境 workaround 固化**：subst 盘符映射、preserveSymlinks、a11y 硬编码服务器默认值——正确但脆弱 | run-vitest.mjs、a11y.spec.ts:33-44 |
| 12 | **测试 mock 三套词表不共享**：Vitest fetch stub / E2E page.route / contract golden JSON，后端字段改名需三处同步 | client.test.ts vs e2e vs contracts |

---

## 9. 总评

webui 是一个刻意"小而深"的前端：依赖面极小（4 个运行时依赖）、类型与契约纪律极严（生成 DTO + contract golden 测试 + 双重静态门禁）、实时一致性协议（epoch/revision/缺口恢复）与错误分类远超一般内部工具水准。它的弱点几乎全部来自同一根源——**用自研替代生态库后，复杂度没有消失而是搬进了自家代码**（巨页面、手写 cache、高密度坑记录注释），以及一次未完成清理的商城剥离残留（三个死 E2E spec）——后者是当前工作树上最应优先处理的一致性问题。

---

**关联阅读**：WS 协议的服务端 → [04-lan.md](04-lan.md)；DTO 单源生成链 → [06-engineering.md](06-engineering.md)（gen_ts_types.py）；托管与打包 → [08-entry-and-window-assembly.md](08-entry-and-window-assembly.md)。
