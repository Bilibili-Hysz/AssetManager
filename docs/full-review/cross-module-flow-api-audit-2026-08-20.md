# AssetsManager 跨模块信息流、数据流与 API 加固审计（2026-08-20）

## 1. 执行摘要

本报告是对 `full-scan-2026-08-20.md` 的跨模块补充，不重复单模块报告中的同一根因，而是追踪数据如何穿过 Desktop、WebUI、LAN HTTP/WS、middleware、application service、repository、SQLite、文件系统、runtime event 和前端缓存。

本轮完成 7 个细分组的只读审计：

1. Route policy 到 service authorization。
2. Token、cookie、身份切换与 WebSocket 生命周期。
3. HTTP DTO、错误和分页契约。
4. Realtime、缓存与 HTTP snapshot 一致性。
5. 文件系统、投影、索引、缩略图和补偿。
6. session/runtime/connection/worker 所有权与关闭顺序。
7. 跨层测试和 CI 门禁映射。

**静态结论**：未发现新的 P0。跨模块 P1 主要集中在三类边界：

- 身份失效没有贯穿 HTTP 与已建立 WebSocket；seller logout 误连到主 LAN 身份域。
- 文件系统权威副作用、SQLite projection、索引/缩略图和事件通知无法形成原子或可重放的失败合同。
- session lease/后台 worker drain 与 DB/LibraryLock teardown 没有统一硬门，超时可能被当作“已停止”。

另有一组 P1 API 契约问题：错误 envelope 在部分真实异常路径被 aiohttp 默认响应替代，前端错误类型丢失后端 code/details，gallery 202 和 buyer order total 等实际响应与前端声明不一致。

**动态证据边界**：本轮未修改代码、未安装依赖、未启动服务、未运行 pytest/vitest/E2E、未做浏览器代理、SQLite busy、文件故障注入、跨进程或压力测试。报告中的“高置信度”表示静态调用链已闭合，不等于已经在运行环境复现。

## 2. 端到端数据流

```text
Desktop / WebUI
    |
    | fetch + same-origin cookies / Authorization / WS handshake
    v
LAN aiohttp app
    |
    +--> security middleware: IP policy + rate tier
    +--> auth middleware: credential -> SessionPrincipal
    +--> route policy/capability middleware
    v
LAN handler / response builder
    |
    +--> application service (session/root-bound)
    |       |
    |       +--> domain validation / owner predicate / CAS
    |       +--> repository -> managed SQLite connection
    |       +--> filesystem / thumbnail / ffmpeg
    |       +--> DomainEvent after commit (部分路径)
    |
    +--> FileResponse / JSON DTO / error envelope

Filesystem mutation
    |
    +--> metadata/tag/favorite/project projection
    +--> asset index + reconciliation queue
    +--> thumbnail bytes + thumbnail_cache row
    +--> runtime event router (epoch/revision/domain/path)
              |
              +--> LAN WS invalidation
              +--> WebUI query invalidation -> HTTP snapshot
              +--> Desktop queued Qt refresh
```

架构中有三条不同的“权威”：文件系统是文件操作的权威副作用，SQLite 是大多数业务 projection 的权威，runtime revision/WS 只是失效通知而不是持久事件日志。任何加固都必须明确操作完成意味着哪一条权威已提交。

## 3. 身份与权限传播矩阵

| 凭据/身份 | 签发/存储 | HTTP 传播 | WS 传播 | 失效源 | 主要跨层风险 |
|---|---|---|---|---|---|
| LAN user/password token | HttpOnly `lan_token` / HMAC | middleware -> `SessionPrincipal` -> route capability | admission 保存 authority，heartbeat 重验证 | logout/revoke/user disable/TTL | 普通 logout 只查 HTTP revocation，未驱逐既有 WS |
| access key/local UI | HttpOnly cookie/header/HMAC | principal/capability | admission + validator | 配置变化/TTL/server close | token revocation 与 WS authority 边界不统一 |
| share token | share-scoped HttpOnly cookie/HMAC | share handler 校验 share id/scope | share authority | share TTL/revoke/server close | protected GET 缓存策略不统一 |
| seller session | HttpOnly `seller_session`，服务端存 hash | `require_seller()` -> seller owner | 不作为主 LAN identity | seller logout/revoke/TTL/restart | seller UI logout 调用了主 LAN logout |
| buyer cart/wishlist owner | HttpOnly匿名 cookie或 user owner key | service/repository owner predicate | 当前没有 cart/wishlist realtime consumer | merge/TTL/clear | 跨 tab/device 不刷新 |
| receipt/delivery credential | scoped receipt cookie / one-time bearer | route + repository CAS | 不进入普通 WS | revoke/expiry/download quota | 现有 owner/CAS 防护较完整 |

### 已确认跨层问题

#### XAUTH-01：HTTP logout 不会切断已建立的 WebSocket（P1，高置信度）

- **端到端链**：
  `auth.py:103-109` 删除 cookie并写入撤销表 -> `server.py:1601-1633` 后续 HTTP 请求检查 revoked -> `websocket.py:23-80` 既有 socket 保存 authority，heartbeat `ws.py:517-550` 只重新验证 HMAC/用户状态，不检查 token revocation -> WS 继续接收 projection invalidation。
- **影响**：HTTP 已经 401，但已有 WS 仍可推送私有失效事件、占用 presence/连接，前端可能误以为已退出。尤其 password/access-key/local-ui 没有 user disable 的 authority revoke 路径。
- **加固**：把 logout/revoke 绑定到统一 credential authority；撤销时调用 `ws_manager.revoke_authority()` 或 token fingerprint 到 socket 索引；heartbeat/admission/broadcast 使用同一 revocation predicate；关闭使用 1008/session-expired 语义。
- **最小测试**：每类身份登录 -> 建立 WS -> HTTP logout -> 同时断言 HTTP 401、WS 1008 close、manager 无 connection/presence。

#### XAUTH-02：seller 门户 logout 调错身份域（P1，高置信度）

- **端到端链**：seller login `api.py:368-369` -> `seller_session` -> `SellerAuthContext` -> `StorefrontShell.tsx:109-116` sellerMode 按钮调用 `AuthContext.logout` -> 只删除 `lan_token` -> `seller_session` 留存 -> `require_seller()` 继续允许商品/订单/履约操作。
- **附加问题**：按钮显示条件使用主 `isAuthenticated`，seller 独立登录且主身份为 guest 时没有 logout 控件。
- **加固**：sellerMode 绑定 `useSellerAuth().logout`；明确 seller-only/global logout 语义；seller logout 失败可见且清理/重试；按钮根据 seller `authenticated` 显示。
- **最小测试**：StorefrontShell 注入两个 context，点击 seller logout 只调用 seller endpoint；真实 seller cookie 删除后 `require_seller()` 必须失败；覆盖 seller-only 与 global logout 两种产品策略。

#### XAUTH-03：主 logout 失败时前端显示 guest，旧 cookie/WS 可恢复（P1，中高置信度）

- **端到端链**：`AuthContext.tsx:141-147` fire-and-forget logout并吞错 -> 清 principal/generation -> `lan_token` 未被服务端删除 -> `/api/info`/`auth/me` 或 WS 重连重新读取旧 cookie。
- **影响**：用户看到“已退出”但刷新后恢复旧会话；与 XAUTH-01 叠加时旧 WS 也可能存活。
- **加固**：logout 成为可观察状态；失败显示 incomplete/retry，不得静默完成；服务端提供 session tombstone/epoch 或明确失败；pending connect/WS 必须被 abort/generation 阻断。
- **最小测试**：logout reject/timeout、延迟 response、刷新/重连三组场景。

#### XAUTH-04：身份绑定 GET 缺少统一 `private, no-store`（P2，部署条件性）

- **链**：cookie principal -> `/api/auth/me`、认证态 `/api/info`、password share info/preview -> 浏览器/代理按 URL 缓存 -> 另一身份命中相同 URL。
- **位置**：`AssetsManager/lan/routes/auth.py:112-120`、`system.py:48-117`、`shares.py:356-409`。
- **影响**：共享代理配置不当时跨用户泄露 principal/capability/share paths；前端可能将缓存 principal 当权威。
- **加固**：认证态 GET 明确 `private, no-store`；必要时 `Vary: Cookie, Authorization`；公开无身份与 principal-specific info 拆分。

### 授权契约缺口

#### XAUTH-05：seller actor 只在 handler 校验，service mutation 不接 actor（P3）

seller route 经过 policy -> `enforce_capabilities()` -> `require_seller()` -> `OrderService.fulfill/revoke`，但 `order_service.py:559-567` 不接收/验证 actor。当前 HTTP 入口没有直接绕过；未来插件、job 或 Desktop adapter 直接调用 service 时，调用者无需 seller actor 即可变更订单。应将 seller actor/command context 设为必填，并加 service-level denial tests。

### 已确认防护

- LAN/share cookie 基本是 HttpOnly、SameSite=Lax、scoped path、secure 绑定 TLS。
- receipt/delivery owner predicate、one-time CAS、quota、rotation/revoke 链路已有较完整测试。
- seller session 与 LAN token 的服务端隔离本身正确；问题是 UI logout wiring。
- WebSocket access-key admission 已 offload PBKDF2；password/local-ui/share token 是 HMAC，不能误报为 WS PBKDF2。

## 4. HTTP API 设计与契约审计

### 4.1 现有契约来源

- LAN DTO：`AssetsManager/lan/dto.py`。
- 路由事实注册：`AssetsManager/lan/api.py`。
- 生成 TS DTO：`scripts/gen_ts_types.py` -> `webui/src/types/contracts.ts`。
- 手写业务类型：`webui/src/types/api.ts`。
- Python/TS golden fixture：`tests/contracts/lan_public_contracts.json`。
- 前端错误/请求实现：`webui/src/api/client.ts`、`errors.ts`。

目前 DTO 生成链只覆盖一部分公共 DTO，Commerce/Gallery/Order 大量类型仍手写；因此“生成器通过”不能证明完整 API 契约一致。

### 已确认跨层问题

#### XAPI-01：真实 HTTP 异常路径绕过 canonical error envelope（P1，高置信度）

- **链**：`validate_path()`/gallery/favorites 服务错误 -> route 原样 `raise web.HTTPException` -> aiohttp 默认文本/HTML -> WebUI client 按 `{error,code,details}` 解析。
- **位置**：`AssetsManager/lan/routes/_helpers.py:393-404`、`gallery.py:85,113`、`favorites.py:105,122`、`lan/routes/_errors.py:47`、`webui/src/api/client.ts:175-180`。
- **影响**：非法路径、缺失资源、服务未就绪和收藏格式错误的错误机器码/字段丢失，前端无法稳定分支；某些 503/404 甚至不是 JSON。
- **加固**：LAN 最外层 middleware 捕获所有 `web.HTTPException` 并转换 canonical JSON；或统一禁止 route re-raise。二进制媒体 endpoint 可有明确的空响应例外，但 JSON API 不得返回默认 HTML。
- **最小测试**：真实 aiohttp client 覆盖 400/401/403/404/409/503，断言 JSON、`error/code/details` 和 `Content-Type`。

#### XAPI-02：前端 ErrorResponse/ApiError 丢失后端 code/details/field（P1，高置信度）

后端 `_errors.py:77-84,132-145,187-205` 支持 `code/details/field/retry_after/limit/item_id`；前端 `webui/src/types/api.ts:394-396` 只声明 `error`，`webui/src/api/errors.ts:2-24` 的 `ApiError` 只保留 `unknown body`。跨层调用无法类型安全地处理 409/410/429 业务错误。

**加固**：定义完整 discriminated `ErrorResponse`/`ApiError`，规范化 body 与 headers，保留 `code/details/field/retry_after`；UI 按 code 分支，status 仅 fallback。

#### XAPI-03：429 body 信息被直接丢弃（P1，高置信度）

share claim 等 route 同时返回 JSON `retry_after` 和 header `Retry-After`；`client.ts:102-115,158-166` 对 429 直接生成新错误，只读取 header。header 缺失时服务端的 JSON retry hint、code/details 丢失。header/body 冲突也没有统一优先级。

**加固**：解析 canonical body；header 优先、body fallback；保留完整错误用于 UI/telemetry。

#### XAPI-04：空 404、feature-disabled 响应与 canonical error 不一致（P1，高置信度）

- `commerce_policy.py:18-24,57-62` 的 feature body 缺 `details`。
- `shop/catalog.py:150-158`、`image.py:60`、`thumbnails.py:48,53` 直接返回空状态。

JSON endpoint 无法区分 feature disabled、not found 和媒体错误。建议统一 error factory；若二进制端点保留空 404，需在 client 类型/文档中明确是 binary exception。

#### XAPI-05：buyer orders 的 `total` 是前端虚假语义（P1，高置信度）

后端 `cart.py:21-36` + `order_service.py:457-487` 使用 keyset cursor，仅返回 `orders`/`next_cursor`；前端 `types/api.ts:625-629` 声明可选 total，页面 `StorefrontBuyerOrdersPage.tsx:61-74` 将当前页长度作为 total fallback。UI 的“total”不是总订单数。

**加固**：删除 total 类型和总数文案，或后端提供准确 owner-filtered count，并用 contract test 固定。

#### XAPI-06：gallery 202 building 不属于声明类型（P1，高置信度）

后端 `gallery.py:49-55` 返回 `202 {building:true}`；API 类型 `types/api.ts:126-137` 声明完整 home；页面 `GalleryHomePage.tsx:16-20,50-53` 通过 cast 绕过。应使用 `{building:true}`/完整 home 的 discriminated union。

#### XAPI-07：generated contracts 与手写 api types 冲突（P1，中高置信度）

`contracts.ts:56-62` 要求 `TreeItem.children`，`types/api.ts:215-220` 将其设为可选；生成器只覆盖公共 DTO，手写 Commerce/Gallery/Order 未纳入 parity gate。应禁止重复基础 DTO，业务类型从生成合同扩展，并添加 source/golden parity test。

#### XAPI-08：大量 route 直接 `web.json_response`，response allowlist 漂移（P2，高置信度）

代表位置：`files.py:117-124`、`metadata.py:50-55`、`users.py:118-124`、`shop/orders.py:73,156`、`system.py:117-141`。动态 service dict 直接进入 response，当前 golden tests 无法锁住所有 route envelope/nested keys。应使用 response builders/projections 和静态禁止规则。

#### XAPI-09：401/403 body 被前端丢弃（P2，高置信度）

`client.ts:158-164` 对 401/403 直接生成 status error，不解析 server code/details。wrong password、share password、buyer merge、seller missing 等业务都只能按 status 粗分。应保留 typed body，专用 client 按 code 决策而不是清主身份。

#### XAPI-10：分页/排序约束没有统一 HTTP parser（P2）

`shop/catalog.py:78-95` 只做 `int()`，范围在 service；quicksearch/orders/thumbnail/share 使用不同上限。gallery sort 只允许运行时字符串，未定义同值 tie-breaker；`gallery.ts` 使用任意 string。应集中严格 query DTO、上限矩阵和稳定排序键。

### 现有契约防护

- DTO allowlist、tree 深度/字段校验、公共 golden fixture 和 commerce error helper 测试已存在。
- shop catalog/buyer orders 的 SQL 排序键已使用 `created_at,id` 复合稳定排序；未发现当前 buyer cursor 的确定性跳过/重复。
- 不能把 `gen_ts_types.py --check` 解释为覆盖手写 Commerce/Gallery/Order 类型。

## 5. Realtime、缓存与快照一致性

### 已确认跨层问题

#### XRT-01：buyer cart/wishlist 写入没有 realtime 传播（P2，高置信度）

- **链**：cart/wishlist HTTP mutation -> `ShopBuyerService` repository commit -> 不发布 DomainEvent -> 无 runtime revision/WS -> 其他 tab/device `ShopBuyerContext` 不 refresh。
- **位置**：`application/shop_buyer_service.py:337,609`、`runtime_events.py:94-116`、`webui/src/stores/ShopBuyerContext.tsx:120-155`。
- **影响**：同一客户端本地状态通常正常，其他设备/标签页 cart badge/items/wishlist 陈旧。
- **加固**：事务提交后发布 `BuyerCartChanged`/`BuyerWishlistChanged` 或 buyer domain；WebUI consumer 注册并刷新；保留 identity generation guard。

#### XRT-02：oversized WS invalidation 截断 paths 但推进原 revision（P2，高置信度）

- **链**：批量写入 -> runtime revision -> WS 超过 frame budget -> `ws.py:551-590` 保留前缀 paths -> WebUI `RealtimeContext.tsx:179-205` 认为 revision 连续 -> path-filtered query/detail 不刷新且不会 gap recovery。
- **影响**：广域 domain consumer 可能刷新，依赖具体 path 的 Browse/Detail 仍陈旧。
- **加固**：超限 revision 发送 `paths=[]` 全域失效，或拆分 revision；不要静默语义截断。新增 `paths_truncated` 时必须强制 null recovery。

#### XRT-03：文件变化不会使商城 projection 失效（P2，高置信度/产品契约待确认）

- **链**：文件 move/delete -> `FileSystemChanged` -> `runtime_events.py:95-99` domains 不含 shop -> WebUI commerce consumer 只订阅 shop -> catalog 保留旧 item/path，后续 media 可能 404。
- **影响**：若产品允许文件操作影响 shop item，商城数据与文件系统不一致；若产品禁止此类关联，应在 service 层明确拒绝/拆离。
- **加固**：把相关文件变化映射到 SHOP，或 move/delete 时执行 shop projection reconciliation，并发布专用事件；新增产品契约测试锁定预期。

#### XRT-04：reconnect registration window 可能吞掉连续事件（P2，中置信度）

`useInvalidation` 在 status/epoch 变化时 cleanup，重连后只在 passive effect 再注册；server 在 WS open 后立即发送 runtime_ready/事件。事件可能推进 cursor 但无 query callback，revision 没 gap，永久不刷新。

加固：保持 registration 跨 status；或 registration 恢复时强制一次 null recovery/重放最新 cursor。需要 React 调度与真实 WS 黑盒验证。

#### XRT-05：identity 切换后旧 recovery 只污染 `recoveryFailed`（P3，中高置信度）

cursor 有 generation guard，但 `RealtimeContext.tsx:104-107,150-153,207-216` 更新 recovery flag 只看 mounted，旧 identity 的失败可影响新 identity。切换时应 abort recovery，并在写 flag 时校验 generation。

### 文件/事件失败一致性根因

#### XRT-06：runtime event 是失效通知，不是 durable event log（P2，中高置信度）

EventBus 同步分发，LAN/desktop 只在当时的 subscribers 上执行，断线客户端没有 replay/ack；runtime revision 是进程内内存序列，不等价于 DB projection revision。若 projection 同时失败或 subscriber 不在线，重连端没有 freshness barrier，只能依赖偶发刷新。

加固：after-commit outbox + durable revision/ack/replay；重连携带 last known projection revision，服务端低于 freshness 时强制 snapshot rebuild。当前现有 gap recovery 只处理观测到 revision gap，不能恢复完全漏掉的事件。

## 6. 文件系统、数据库投影与补偿 failure matrix

| 操作 | 权威副作用 | projection/缓存 | 事件 | 失败后当前状态 | 主要缺口 |
|---|---|---|---|---|---|
| move | FS move | tags/meta/fav/thumb migration + index | moved FileSystemChanged | FS 成功，projection 可能部分写入；常只入 index queue | 无统一 projection repair，migrate 无独立 savepoint |
| delete/trash | FS delete/move | savepoint 清 tags/meta/fav/thumb/index | deleted | FS 成功，cleanup rollback/失败只 log | 无 durable cleanup task；maintenance 覆盖不全 |
| restore | FS restore | snapshot tags/meta/fav，不含完整 thumb row | restored | FS 成功，snapshot/commit 失败仍可能广播 | 无 restore projection repair |
| copy/duplicate | FS copy | 不迁移源 tags/meta/fav/thumb（需明确产品语义） | copied/created | partial target 可存在，index 失败只尝试 index queue | 缺 batch manifest/失败语义 |
| import | 多文件 FS copy | 逐文件部分成功 | import 即使 failed 非空也发布 | partial success 仅在返回对象，失败文件无 repair | 无 per-file durable task/明确 partial event |
| external watcher | 外部 FS | 只发 invalidation，不刷新 index | external_watch | 无 UI/WS subscriber 时无修复；目录 mtime 还漏原地覆盖 | watcher 不产生 reconciliation |
| thumbnail bake/clear | bytes 与 DB row 分开 | `os.replace`/DB upsert 或 DB clear/unlink | 局部 cache events | crash/失败可 bytes-only 或 row-only | 无双向 durable reconciliation |

### 已确认跨层问题

#### XFS-01：move 成功后 projection migration 失败无完整 durable repair（P1，高置信度）

- **链**：`file_operation_service.py:537-559` FS move 成功 -> `core/database.py:1310-1431` 多表 migration/thumbnail rename -> 异常捕获 -> 只记录/入 `ASSET_INDEX_ROOT_RESCAN` -> 继续 index/event。
- **影响**：新路径文件存在但 tags/meta/favorites/thumbnail row/bytes 留在旧路径或部分迁移；后续无任务修复，任意无关 commit 还可能提交 partial transaction。
- **加固**：统一 operation/repair envelope；projection migration savepoint+rollback；写 durable repair intent；repair worker 以 FS 为权威重建 projection，完成后才发布完成事件。

#### XFS-02：delete 成功后 projection cleanup 失败无 durable repair（P1，高置信度）

- **链**：FS delete/trash -> `_clear_deleted_projection` savepoint rollback/异常 -> 只 log -> 仍发布 deleted；integrity maintenance 只覆盖部分 metadata/thumbnail，不覆盖 tags/favorites/assets index。
- **影响**：indexed search、tag search、favorites 和 project count 保留残留，且 event 表示比实际 projection 更完整。
- **加固**：先写 durable cleanup intent；失败入 queue；扩展 integrity maintenance；区分 filesystem_deleted 与 projection_cleanup_succeeded。

#### XFS-03：外部 watcher 只发 invalidation，不触发 index/reconciliation（P1，中高置信度）

- **链**：外部 create/delete/overwrite -> 目录 mtime watcher -> FileSystemChanged(external_watch) -> desktop/LAN 只 refresh/invalidate -> 不入 index/reconciliation。
- **影响**：无 UI/WS 订阅时永久陈旧；原地覆盖可能连目录 mtime 都不变；indexed search/project count 继续旧值。
- **加固**：watcher 检测后 enqueue parent/root rescan；为外部变更写 durable marker；增加 size/mtime/fingerprint 或平台 journal；启动/轮询执行 bounded reconciliation。

#### XFS-04：index refresh failure 不保证 durable repair（P1，中高置信度）

- **链**：refresh degraded -> enqueue 尝试 -> queue full/unavailable/terminal -> warning/telemetry -> indexed reads 无 freshness barrier。
- **影响**：FS 已成功但 index 永久旧，读端没有 degraded 状态或 fallback。
- **加固**：queue 失败写独立 append-only marker；terminal 设 `repair_failed` 并可观测；读端携带 freshness/revision，不满足时 fallback FS 或显式 degraded。

#### XFS-05：`remove_url` 在外层事务 commit 前发布事件（P1，高置信度）

- **链**：caller outer transaction -> `MetadataService.remove_url()` 未调用 event-safe guard -> repository 保留 outer txn -> publish `AssetUrlsChanged` -> router/clients refresh -> caller rollback。
- **影响**：事件/缓存永久认为 URL 已删除，实际 DB 仍保留；与 set_notes/add_url 的 commit-before-event 约束不一致。
- **加固**：拒绝 outer transaction，或 after-commit outbox；事件携带 DB revision。

#### XFS-06：restore/move 可能在 outer transaction 下提前发布事件（P1，中高置信度）

restore 不调用 clean transaction boundary；move 初始检查与 FS IO 之间可形成新的 outer transaction，projection/index/event 仍继续。必须在 FS 操作前后验证 clean boundary，所有完成事件统一 after-commit。

#### XFS-07：thumbnail bytes/DB row crash state 不可重放（P2，高置信度）

bake 先 `os.replace` 后 DB upsert；clear 先删 DB row 后删 bytes。崩溃或任一失败会产生 bytes-only、row-only、dangling-new-row/orphan-old-bytes，现有清理只覆盖部分 orphan，不能保证双向修复。需 thumbnail operation journal 或双向 reconciliation。

#### XFS-08：import partial failure 仍发布成功形态事件（P2，高置信度）

ImportResult 记录 failed，但 service 仍 refresh/emit import，refresh failure 被忽略；没有 per-file durable retry/manifest，空目录也可能残留。事件应携带 operation_id/copied/failed/degraded，失败进入 queue。

#### XFS-09：FavoriteService 直接 commit caller 的外层事务（P2，高置信度）

FavoriteService 没有 clean transaction guard，repository 直接 `conn.commit()`。调用者未提交的 unrelated projection 会被一起提交，破坏跨服务事务所有权；应统一 savepoint/commit owner 与 post-commit event。

#### XFS-10：事件无 durable delivery/ack/replay（P2，中高置信度）

EventBus/RuntimeEventRouter/WS 仅服务当前 subscribers；断线/关闭/广播失败没有 durable event log/replay/freshness barrier。runtime revision 只是内存失效序列，不能证明 projection 已提交或客户端已收敛。

## 7. Runtime/session/connection 所有权矩阵

| 资源 | 创建者 | 当前持有者 | 关闭动作 | 超时后的当前语义 | 加固硬门 |
|---|---|---|---|---|---|
| LibrarySession lease | handler/worker | `session.operation()` | drain + invalidate | 可能继续下游 DB teardown | active operation=0 才能关 DB |
| managed SQLite connection | DatabaseManager | session/services + raw fallbacks | close library | 一些独立 worker 仍可能运行 | 所有 DB task 纳入 lease/owner |
| LibraryLock | LibraryService | process/runtime | release after DB close | 应保留至所有 worker drain | teardown pending 时不得 release |
| LAN server/WS | LanServer | aiohttp runner/WS manager | stop runner/close_all | committed broadcast futures 未完全 drain | stop subscription -> drain futures -> close WS |
| Gallery background worker | GalleryService | daemon thread | cancel + bounded join | timeout 后 runtime 可继续 close | worker 全程 lease，timeout 阻止 DB close |
| Integrity quick check | IntegrityService | raw sqlite connection | interrupt + 10s wait | 独立连接可能继续 | managed owner 或独立 hard gate |
| LibraryWatcher | bootstrap/runtime | daemon thread | set stop event | stop 不 join，旧线程可发布事件 | join + generation check，未 drain 禁止 reopen |
| Reconciliation sweeper | ReconciliationService | daemon thread | event + 2s join | sweeper 可能继续 SQL | sweeper 与 worker 都 hard drain |
| ZIP executor | LanServer | thread pool | `wait=False` | running build 继续读/写 | future registry + bounded drain |
| Desktop ffmpeg pool | process/global | multiple loaders | global `waitForDone` | 旧 runtime 任务继续回调 | per-runtime ownership/generation |
| RuntimeEventRouter | LibraryRuntime | subscribers | close | inflight callback 可能无限等待 | bounded drain + failed/pending state |

### 已确认跨层问题

#### XOWN-01：session lease 超时后仍关闭 SQLite/LibraryLock（P1，高置信度）

- **链**：worker持有 `session.operation()` -> `LibraryService.close_session()` -> `context.py:287` 有界等待 -> timeout 后 `_invalidate` -> `DatabaseManager.close_library()` -> worker finally 仍触碰 raw connection。
- **影响**：`ProgrammingError`、SQLite/native race，Windows 文件句柄和跨层关闭尤为敏感。
- **加固**：`active_operations != 0` 时 close 必须返回 pending/failed，不能提交 DB close 或 lock release；取消/排空后显式 retry。

#### XOWN-02：独立 Integrity quick check 不受 managed connection/session lease（P1，中高置信度）

`database_integrity_service.py:328` 直接 `sqlite3.connect`，stop 超时仍允许 canonical DB teardown。要么使用 managed connection + session lease，要么把独立连接注册为独立 owner，stop 未 drain 时阻止 teardown。

#### XOWN-03：ActivityLog 固化 raw DB connection 且路由无 lease（P1，中高置信度）

`server.py:184-260` 捕获 raw `db_conn` 注入 lambda；`_helpers.py:62-140`、`users.py:115-119` 直接读写。connection lock 不能替代 lifetime lease。应改 session-aware provider/operation boundary。

#### XOWN-04：Gallery background worker 未纳入 session lease（P1，高置信度）

`gallery_service.py:136,336` daemon worker 直接执行 repository SQL；close 最多 join 5 秒，超时后 runtime/DB 仍可继续 teardown。worker 全程应持 lease，超时应是 hard gate。

#### XOWN-05：adapter stop 失败后重试会重复停止已完成 adapter（P1，中高置信度）

`runtime.py:97` 混合 adapters cleanup；单个 stop 失败后进入 failed，重试缺少每 adapter completion state。可能导致 close 长期卡在 closing、DB/lock 残留。应按 adapter 阶段持久/内存记录进度，成功项幂等跳过。

#### XOWN-06：watcher/reconciliation/maintenance/integrity/scanner/ZIP stop 超时仍报告 stopped（P2，高置信度）

代表位置：`library_watcher_service.py:81`、`asset_index_reconciliation_service.py:236`、`database_maintenance_service.py:252`、`database_integrity_service.py:265`、`lan/scanner.py:48`、`lan/server.py:1379`。未 drain 的后台线程/任务仍可能访问文件/SQLite或发布事件。应统一 `StopResult(drained, pending_handles, retryable)`，runtime 只有 drained 才能释放 owner。

#### XOWN-07：RuntimeEventRouter.close 可能无限等待 inflight callback（P2，中置信度）

`runtime_events.py:297` 自身无 deadline；单个外部 subscriber 阻塞时可绕过 session close bound。应 bounded drain，超时保留 closing ownership。

#### XOWN-08：LAN realtime 已提交 broadcast future 未 drain（P2，中置信度）

`api.py:127-143,395-449` 只等待 dispatching，不追踪已提交 future；随后 close WS，存在 send/close race。应 future registry + bounded gather/cancel。

#### XOWN-09：lazy LAN service bundle ready 分支没有 borrow lease（P3）

`bootstrap.py:120` 只检查 `session.is_closed` 后返回 retained bundle；多数公开 service 方法自行加 lease，因此不是立即 UAF，但 ownership API 不完整。应提供 scoped borrow token 或要求调用方在 `session.operation()` 内取得/使用。

### 已确认防护

- canonical bootstrap 有 root ownership、LibraryLock、managed connection owner、session operation、runtime identity validation、close retry。
- reconciliation queue 有 generation/lease/heartbeat/sweeper/CAS；SQLite 有 connection lock 和 close admission。
- Runtime event 有 epoch/revision/root/session-token filtering；WS 有 admission barrier；desktop bridge 使用 queued signal/generation。
- 不把 raw compatibility fallback、PID reuse、正常 restart route lifecycle或所有 `db_write_lock` 误报为关闭安全问题。

## 8. 跨层测试与门禁映射

| 链路 | 现有覆盖 | 断链/缺口 | 最小新增测试 | 门禁建议 |
|---|---|---|---|---|
| HTTP logout -> existing WS | `tests/e2e/test_webui_realtime_acceptance.py:202`；`tests/lan/test_runtime_realtime.py:197` | E2E 未将真实 logout handler/cookie revoke 与既有 WS 因果串起来 | browser E2E 捕获 logout + WS close/HTTP 401 | Python LAN browser E2E hard gate |
| seller logout wiring | `SellerAuthContext.test.tsx:42-52`；seller mock E2E | 未测 StorefrontShell 实际按钮/context | `StorefrontShell.test.tsx` + seller cookie integration | npm test hard gate |
| canonical HTTP errors | `_errors` helper tests、部分 route tests | 未覆盖真实 aiohttp 异常路径与前端 parser | `tests/lan/test_http_error_envelope.py` | Python default hard gate |
| gallery 202/orders total/type parity | gallery route 202 integration；orders mock | 未把真实 buyer orders/202 union 与前端 types 串起来 | LAN contract + TS parity tests | default contract/lint gate |
| buyer cart/wishlist realtime | ShopBuyerContext unit + mock E2E | 无真实 WS domain/consumer 链 | provider invalidation test + optional browser E2E | npm test；真实 E2E 可单独 hard gate |
| oversized WS invalidation | manager frame-size unit | 无真实 aiohttp wire + frontend path-filter test | real WS oversized frame contract | default LAN smoke |
| file move/delete -> shop | file event/service tests | 无 SHOP domain refresh/产品契约 | `test_shop_file_invalidation.py` | Python integration hard gate |
| remove_url outer transaction | happy-path round trip | 无 outer BEGIN/rollback/event test | metadata + event publishing integration | default integration |
| projection repair | FS+SQLite integration覆盖局部操作 | 无故障注入后最终 gallery/shop/HTTP oracle | `test_projection_repair_e2e.py` | default integration/smoke |
| watcher -> index repair | watcher/index/reconciliation 分测 | 无真实 end-to-end repair chain | `test_watcher_index_repair.py` | default integration |
| session close hard gate | 单组件 timeout/lease tests | 无统一 close->all adapters->DB/lock gate | top-level lifecycle integration | default hard gate |
| background worker drain | reconciliation/worker unit、shutdown stress | gallery/watcher/maintenance/ZIP 未统一 drain | `test_background_worker_drain.py` | deterministic default; stress/nightly supplemental |

CI 注意：`pytest.ini` 默认排除 `e2e`/`perf`；真实 LAN browser gate 在 `.github/workflows/ci.yml:201-228`，WebUI mock E2E 在 `:257-275`。不能将默认 pytest 通过等同于完整跨层验收。

## 9. 分阶段加固路线

### Phase A：统一安全与契约边界

1. 建立 credential authority：HTTP logout/revoke 与 WS eviction 使用同一 token/authority 事实；修复 seller logout wiring。
2. 建立 canonical HTTP error middleware；定义完整 `ErrorResponse`/`ApiError`，统一 429 header/body 和 401/403 code。
3. 用 discriminated unions 替代 gallery 202 cast；修正 buyer orders total 语义；删除 generated/handwritten 基础 DTO 重复。
4. 统一所有认证态 GET cache headers；明确 public 与 principal-specific response 的缓存分界。
5. 对 seller service mutations 引入 actor/command context，防止未来非 HTTP adapter 绕过 handler 授权。

### Phase B：事件与数据一致性

1. 所有 mutation 采用 after-commit event/outbox；优先修 `remove_url`、restore/move 的 outer transaction 事件。
2. 将 `FileSystemChanged` 与 shop projection 关系产品化；明确文件操作是否能影响商品，随后补 domain mapping/reconciliation。
3. 为 move/delete/restore/import 建立统一 durable projection repair envelope，覆盖 tags/meta/favorites/index/thumbnail；queue failure/terminal 必须可见。
4. watcher 从“只通知”升级为“通知 + bounded reconciliation producer”；对目录 mtime 不敏感的原地内容修改引入 fingerprint/journal。
5. 处理 WS 超限事件时发送全域失效或强制 recovery，不推进一个语义被截断的正常 revision；重连 registration 和 identity recovery 要求 generation/重放。
6. buyer cart/wishlist 增加 after-commit buyer-domain invalidation，跨 tab/device 刷新。

### Phase C：所有权与关停硬门

1. 定义统一 `StopResult`/`DrainResult`：任何 worker、adapter、executor、subscription 超时都返回 pending，不得伪装 stopped。
2. `LibrarySession.active_operations == 0` 才允许 DB close、LibraryLock release；超时保留 closing ownership 并支持 retry。
3. 所有 DB-facing worker（integrity、gallery、ActivityLog、reconciliation、maintenance）纳入 session lease 或显式独立 owner。
4. watcher/scanner/sweeper/ZIP/ffmpeg/router/broadcast future 建立可观测 registry 和 bounded drain。
5. runtime adapter 按子适配器记录 completion，重试只执行未完成项。

### Phase D：测试与发布门禁

1. 先加入 canonical error、seller logout、logout/WS、remove_url、projection repair、watcher/index、close hard gate 的确定性 integration tests。
2. 再加入真实 aiohttp WS、浏览器 cookie/代理缓存、跨身份 query cache、Windows reparse/POSIX symlink、SQLite busy、ffmpeg/ZIP cancel 的动态测试。
3. `gen_ts_types.py --check` 之外新增 handwritten business type parity gate；所有 JSON route 加 exact response fixture。
4. 默认 pytest 仍可排除重型 E2E，但 CI 必须明确列出并阻断真实 LAN browser、WebUI E2E 和 package/runtime 验收；skip 数量单独门禁。
5. 发布 workflow 必须依赖完整 CI、错误契约、projection repair 和 lifecycle gate；修复单模块问题前先落地跨层回归，防止局部修复破坏另一条数据流。

## 10. 不应误报的已确认设计防护

- Route policy 已按 app 保存，`_declared_patterns` 不是跨 app/restart 污染；正常新 app restart 不重复定性。
- buyer receipt/delivery/order CAS、share scope/token、seller session 服务端隔离和主 token 不落 localStorage 目前有有效防护。
- `PathGuard` 文本/containment、image blur fail-closed、订单复合排序、migration savepoint、reconciliation CAS/lease 不能因本轮跨层缺口而被整体否定；报告指出的是它们之间缺少统一上层合同。
- WebSocket password/local-ui/share `verify_token` 是 HMAC；access-key PBKDF2 已 offload。
- Desktop queued bridge、generation/session/token 检查能阻止多数旧事件回写；未将未确认的重复 repaint升级为漏洞。
- `db_write_lock` 解决 SQL 访问串行，不自动解决 connection lifetime；raw compatibility fallback 也不等于所有路径都不安全。

## 11. 审计边界

本报告是静态跨模块审计与加固基线。每条发现均应在修复前通过对应动态测试确认，尤其是：

- 真实 aiohttp/Chromium cookie 与 WS 关闭行为。
- 代理缓存对 Cookie/Authorization 的处理。
- POSIX/Windows 文件系统故障和 reparse/symlink。
- SQLite busy、连接关闭和多线程事件循环 heartbeat。
- crash injection、partial projection repair、watcher/index reconciliation。
- React passive effect/reconnect scheduling、超限 WS wire payload。
- ffmpeg、ZIP、gallery worker 的取消和停服 drain。

本轮未修改已有生产/测试文件，未运行测试或服务。