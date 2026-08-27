# AssetsManager 性能开销与时序审计（2026-08-20）

## 1. 执行摘要

本报告在模块内扫描和跨模块数据流审计之上，专门审查 Python 后端、Desktop、WebUI 及其事件/关闭协议的性能开销与时序正确性。

审计按 10 个细分组执行：LAN request/event loop、SQLite/队列、Pillow/ffmpeg/ZIP、gallery/scanner/watcher、前端 query/retry、React 列表/商城、浏览器图片/下载、EventBus/WS 顺序、shutdown/drain、性能观测与 CI。

**静态结论**：没有将实际吞吐、p95/p99、RSS、浏览器帧率未经运行测量地写成事实；但已确认以下结构性根因会在输入规模、并发或慢设备条件下放大成本或引入时序错误：

- 用户登录/注册、Commerce、tag、ActivityLog 等同步路径仍可在 aiohttp event loop 上做 PBKDF2、SQLite 或长锁等待。
- 缩略图 batch、ZIP、Pillow/ffmpeg、全树扫描与 Gallery build 存在聚合、全量落盘、串行处理或无界 queue 成本。
- 前端 realtime 事件可导致全局 context 重渲染和同 query 的 abort/restart；QueryCache GC 不删除历史 key；买家读请求被 mutation queue 串行化。
- Browse/Gallery/旧商城路径使用全量 payload/DOM；缩略图 batch 上限前后端不一致；下载和 preview pool 会放大浏览器内存、网络和 render 工作。
- revision 分配有序但跨线程 WS 投递无序；广播与 desktop bridge 缺少有界合并/背压。
- shutdown 的总预算小于串行子步骤预算，部分 router/DB 阶段无 deadline；现有 recorder、nightly 和 CI 没有覆盖跨端 tail latency、事件循环 lag、React commit、WS queue 或 drain 状态。

本轮**未运行**服务、pytest/vitest、benchmark、浏览器性能分析、故障注入或网络测试。所有需要实际量化的结论在第 8 节单独列为动态验证矩阵。

## 2. 性能时序模型

```text
HTTP request
  -> middleware/auth/rate policy
  -> route validation
  -> synchronous service / to_thread boundary
  -> SQLite gate / filesystem / media worker
  -> DTO/JSON or FileResponse
  -> browser cache/query state

Desktop or service mutation
  -> EventBus synchronous dispatch
  -> RuntimeEventRouter revision
  -> LAN run_coroutine_threadsafe
  -> WS serialize/send
  -> RealtimeContext cursor/invalidation
  -> query abort/refetch
  -> React commit / image decode

Close
  -> Window/LAN/runtime adapter stop
  -> worker cancel/join
  -> Event router drain
  -> session lease drain
  -> DB gate/connection close
  -> LibraryLock release
```

审计中必须区分四种时间：CPU service time、lock/queue wait、I/O wait，以及关闭/取消后仍在后台消耗的 straggler time。现有记录主要覆盖部分 handler wall-clock，无法将四者关联。

## 3. 已确认 P1 性能与时序问题

### PT-01 登录/注册把 PBKDF2、SQLite 和审计写入留在 aiohttp event loop

- **置信度**：高。
- **位置**：`D:\~Vibe-Coding\Projects\AssetsManager_old-bak\AssetsManager\lan\routes\auth.py:19-75`；`domain/auth.py:55,115`；`lan/routes/_helpers.py:86-117`。
- **时序链**：`request.json -> authenticate_user/register_user -> AuthRepository SQLite -> 600k PBKDF2 -> optional rehash/commit -> ActivityLog.add/commit -> response`。
- **成本**：登录至少一次 PBKDF2；注册为 hash 后再次认证。成功旧 hash 还会重 hash/写库。所有工作发生在 event loop，导致其他 API、WS heartbeat/广播与 shutdown 共享 stall。
- **已有防护**：login/register 有严格 per-IP rate limit；access-key 已使用 `asyncio.to_thread()`。
- **加固**：将完整 service 链而非单个 hash 放到有界 crypto/DB executor；ActivityLog 同步完成或使用有界后台队列；记录 queue wait、PBKDF2、DB 和 route 分段耗时。
- **最小测试**：10 并发生产成本登录，采集 loop lag、HTTP p50/p95/p99 与 queue wait；静态测试断言 user login/register 经 to_thread。

### PT-02 Commerce/tag/activity 同步 SQLite 和锁等待会阻塞 event loop

- **置信度**：高。
- **位置**：`lan/routes/shop/catalog.py:50-99`、`shop/cart.py:123`、`shop/orders.py:73,162`、`tags.py:22-133`、`users.py:115`；gate `core/database.py:1175-1295`。
- **时序链**：`async handler -> direct application service -> shared SQLite connection -> db_write_lock/transaction -> fetchall/DTO projection -> JSON`。
- **成本**：catalog COUNT+page，checkout 多行写，tag rename/delete 按文件数读取/发布，seller orders 可达 1,000，CSV export 可达 5,000。等待共享连接锁时，handler 仍在 loop。
- **加固**：对完整同步 service 调用建立一致 to_thread 边界；保留连接锁，但让等待不冻结 loop；增加 request/route 与 `db.write_lock.wait/hold` 的关联。
- **测试**：外部 worker 持 DB lock 250ms，同时调用 catalog/tags/checkout，断言 loop ticker 正常推进；测高基数 tag、1,000 order list、CSV export p95。

### PT-03 Shop catalog 读绕过 connection gate，且 CSV export 在锁内扫描无关 token

- **置信度**：高。
- **位置**：`repositories/shop_repository.py:450-580`；`repositories/order_repository.py:1389`；`application/order_service.py:1040`。
- **成本/时序**：`list_catalog()` 缺 `@locked_read`，可与共享 connection 写重叠；export 在读锁中加载最多 5,000 orders 并无条件扫描全部 delivery token，复杂度为 `O(5000 + T)`，T 为全库 token 数。
- **影响**：并发 cursor/lock 错误风险之外，还会使读锁 hold 随无关历史 token 增长，拖慢写与读取。
- **加固**：catalog 加 gate；export token 查询限定 order id 并分块；SQL rows 脱离 gate 后再构造 CSV；大导出改流式或异步 job。
- **测试**：5k orders 配 5k/50k/500k 无关 token，采集 export wall、RSS、gate hold 与并行写 p99。

### PT-04 Tag rename/delete 是按影响文件数线性 SQL 与事件 fan-out

- **置信度**：高。
- **位置**：`application/tag_service.py:305-320`。
- **时序链**：集合 mutation -> 每个关联 path `get_tags` -> 每个 path publish event。
- **成本**：`O(F + R)`，F 为受影响文件数，R 为 tag rows；单 connection 下额外 F 次读取会拉长串行化时间，事件又会触发 desktop/WebUI refresh。
- **加固**：一次性 `get_tags_for_files(paths)` + 分批投影；发 batch/catalog invalidation 而非 F 个 event；高 F 时后台任务/进度。
- **测试**：1k/10k/100k file tag，记录 SQL statement、gate hold、event 数与并发 get_tags p99。

### PT-05 LAN batch thumbnail 把 CPU/RSS/默认 executor queue 放大到 100 项上限

- **置信度**：高。
- **位置**：`lan/routes/thumbnails.py:141-180`；`application/thumbnail_service.py:287-321`；policy `lan/api.py:287`。
- **时序链**：`POST batch -> single to_thread -> 100 * (resolve/blur DB/Pillow decode-resize-encode/base64) -> aggregate dict -> JSON response`。
- **成本**：每项同时/先后保留 WebP bytes、base64 text、JSON object；base64 至少增加约 33%。请求级 worker 使用默认 executor，无专用并发/queue 预算；取消只取消 await，不停止线程内循环；路由为 skip rate tier。
- **加固**：总输出字节、像素和项数三重预算；媒体专用 bounded executor；8-16 小批、取消检查、可视优先；返回 URL 或分块结果而非大 base64 JSON。
- **测试**：100 张混合大图、20-50 并发 batch，记录 RSS、encoded bytes、queue wait、loop lag、取消后未启动项数。

### PT-06 ZIP 完整落盘后才首字节发送，构建和取消成本无界

- **置信度**：高。
- **位置**：`lan/routes/downloads.py:170-214,272-318`；`lan/routes/_helpers.py:542-607`；`lan/server.py:94-97,1379`。
- **时序链**：完整 size walk -> `mkstemp` -> 2-worker ZIP executor -> 完整 archive 临时文件 -> `FileResponse` 才首字节发送。
- **成本**：目录被遍历两次；500 MiB source 产生接近同量临时 archive，两个 worker 约可并行占 1 GiB；已运行 `zipfile.write()` 不可协作取消，`shutdown(wait=False)` 不能中止。
- **加固**：await build 立即受 try/finally 清理；worker cancellation event/分文件检查；记录 queue wait、build、TTFB、archive/source bytes、temp disk peak；设置全局 temp byte/active build budget；评估 streaming ZIP 与 MIME-aware stored compression。
- **测试**：慢 zip write/cancel，断言临时文件清理；两个大 archive 记录 TTFB、临时卷峰值和 stop-to-cleanup。

### PT-07 Desktop 全局 stderr 锁使 QImageReader decode 实际并发度为 1

- **置信度**：高。
- **位置**：`panels/file_list/_loader.py:102,936,256`；`panels/image_viewer.py:85,216`。
- **时序链**：FileList 或 ImageViewer worker -> `_suppress_libpng_warnings()` -> global FD2 lock -> `QImageReader.read()`/resize -> unlock。
- **成本**：FileList 3 worker 与 Viewer 2 worker 均被同一全局锁串行化；慢网络盘/大图 decode 持锁期间，grid 和 viewer 互相阻塞。
- **加固**：限定抑制到确实会触发 libpng 警告的格式，避免解码周围全局 FD 锁；记录 lock wait/hold；基准确认后移除或替代重定向。
- **测试**：两 loader + viewer 的受控慢 decode，证明基线并发度和改后吞吐。

### PT-08 Desktop ffmpeg 提帧 queue 无 admission，关闭可阻塞 GUI

- **置信度**：高。
- **位置**：`panels/file_list/_loader.py:37,806,847-890`；`application/thumbnail_service.py:272`；`panels/file_list/_base.py:179`。
- **成本**：活跃 ffmpeg 最多 2，但 QThreadPool pending 数无上限；同路径没有 complete single-flight；任务可运行 30 秒。panel shutdown 在 GUI 生命周期调用 `waitForDone(10s)`。
- **加固**：以 `(path, cache key, generation)` single-flight；队列 cap、离屏丢弃、Popen cancellation；关闭只短 bounded drain，不等待完整全局 queue。
- **测试**：100 视频快速滚动、同视频重复请求、关闭/切库；记录 active/pending、子进程、GUI close latency、stale delivery。

### PT-09 Watcher 宽树 BFS 是二次复杂度，外部变更会放大 Gallery full rebuild

- **置信度**：高。
- **位置**：`application/library_watcher_service.py:72,144,199`；`application/gallery/_incremental.py:78,168,365`。
- **时序链**：120 秒 watcher -> list `pop(0)` -> external_watch event -> Gallery 不支持该 kind -> 清 projection -> 30 秒 timer -> full library rebuild。
- **成本**：50k 宽树 FIFO 理论 `O(D²)`；每个非空 watcher round 都可能触发全库 `O(entries + sorting + decode)` rebuild，持续写入会不断推迟 warm cache。
- **加固**：watcher 使用 `deque.popleft()`；external_watch 采用 dirty prefix/目录级增量或 dirty generation，不重复删除 cache；记录 scan/rebuild duration、pending dirs、changed paths、cache-miss duration。
- **测试**：10k/50k 宽树、连续 watcher events，统计 rebuild rate、full build time 与 cache unavailable ratio。

### PT-10 Gallery burst 增量 apply 对全局状态重复排序/重组

- **置信度**：高。
- **位置**：`application/gallery/_incremental.py:253,692,820,899`。
- **时序链**：2 秒内合并每个 change -> per event image/ancestor sort -> per event `_recompose_home()` -> 全 refs/state traversal/tag read。
- **成本**：约 `O(E × (R log R + N))`，而非批末一次；change folding 本身反向 list scan 最坏 `O(E²)`。50-500 文件 burst 即可放大 CPU、对象分配与 tag/Pillow read。
- **加固**：先 apply whole batch，批末一次 recompose；受影响 parent 集合统一排序；recent top-K；path index 替换反向 scan。
- **测试**：E=1/10/100/500、R=10k/70k，记录 CPU、apply p95、sort 次数、tag query 次数。

### PT-11 Asset index tree reconciliation 完整快照常驻内存并单大事务落库

- **置信度**：高。
- **位置**：`application/asset_index_service.py:496-538`。
- **时序链**：worker claim -> os.walk -> all directory snapshots -> one `clear_subtree + replace` publication。
- **成本**：`O(F)` snapshots 内存 + `O(F)` publish；大 subtree 同时承受文件扫描、RSS 峰值和长 SQLite write window。
- **加固**：staging generation 分块写入，最终小事务切 revision；记录 scan/persist 分段、RSS、row count、transaction duration、busy retry。
- **测试**：10k/70k/150k 文件，测 RSS、transaction hold、并发 UI query p95。

### PT-12 Realtime event 更新全局 context，并在 burst 中 abort/restart 同一 query

- **置信度**：高。
- **位置**：`webui/src/stores/RealtimeContext.tsx:202,232`；`webui/src/hooks/useCachedQuery.ts:146,221`；`BrowsePage.tsx:391`。
- **时序链**：WS event -> setCursor -> Provider value 更新 -> 所有 realtime consumers render -> notify -> matching query refresh -> abort old GET/start new GET。
- **成本**：每事件 `O(all context consumers + matching registrations)`；事件频率高于 response 时，同 key 产生 N 次 request、N-1 abort，GET retry 会继续放大。
- **加固**：cursor/status 与 invalidation dispatcher split context或 selector store；in-flight query 标 dirty，落地后最多补一次；50-250ms trailing coalescing；路径过滤保留。
- **测试**：100 consumers、1,000 events，断言不匹配 consumers 不 rerender；10 same-domain events 对一个 deferred query 至多两次调用。

### PT-13 QueryCache GC 不删除历史 entry，长会话高基数 key 累积

- **置信度**：高。
- **位置**：`webui/src/cache/queryCache.ts:192`。
- **时序链**：unique search/path/sort key -> Map entry -> unsubscribe -> 300s GC 仅清 snapshot -> entry/key 留存 -> identity clear 遍历历史 key。
- **成本**：内存和 clear 时间随整个会话历史 key 增长，非 live query 数；没有 LRU/容量上限。
- **加固**：GC 在 identity/entry/subscriber 校验后 `entries.delete(rawKey)`；暴露 cache size/eviction metrics，必要时 LRU。
- **测试**：1,000 unique key GC 后 `peekEntry` undefined，clear 不遍历旧 entry；长导航 heap baseline。

### PT-14 Buyer 读请求被 mutation queue 串行化，空 wishlist 可重复 GET

- **置信度**：高。
- **位置**：`webui/src/stores/ShopBuyerContext.tsx:106,120,138`；`components/storefront/StorefrontShell.tsx:53`；`pages/StorefrontWishlistPage.tsx:20`。
- **时序链**：Shell mount `refreshCart + refreshWishlist` -> shared tail 使 GET 串行 -> empty wishlist page 用 `length===0` 再 refresh。
- **成本**：首屏从 `max(RTT)` 退化为 `sum(RTT)`；慢 mutation 阻塞无依赖 read；空 wishlist 至少可能两个 GET。
- **加固**：cart write 与 cart read lane 分离；wishlist 独立 lane；read single-flight；以 hasLoaded/fetchedGeneration 而非数组长度判断。
- **测试**：两个 deferred GET 同时发出；连续 cart mutation 仍串行；Shell+empty wishlist 一次 GET。

### PT-15 Browse/Gallery/商城仍有全量 payload/DOM 路径，缩略图上限不一致

- **置信度**：高。
- **位置**：`lan/routes/files.py:48-124`；`webui/src/pages/BrowsePage.tsx:463,546,713`；`components/files/ProjectGrid.tsx:43`、`ProjectList.tsx:86`、`MasonryView.tsx:182`；`gallery_service.py:460-508`；`GalleryCollectionPage.tsx:153`；`StorefrontPage.tsx:22,38`、`StorefrontProductPage.tsx:25,44,97`、`SellerProductsPage.tsx:25,163`。
- **成本**：Browse 没有 cursor/limit，三视图完整 map；Gallery collection 无分页且 next_cursor 未落实；首页/详情/seller 仍用旧全量 catalog（默认上限 5,000）。Browse 全量 image path 一次 batch，但 server limit 100；>100 时整个请求 400 且重复导航重试失败。
- **加固**：服务端 cursor/limit；前端 virtual list；visible overscan 分块 thumbnail（<=100/批）；详情直取单 item；首页摘要 endpoint；seller server-side filter/paging。
- **测试**：100/500/2000 fixture 的 React Profiler；101/300/1000 image 无 400；detail 不等待全量 catalog。

### PT-16 浏览器下载全量聚合及高频 global progress 更新

- **置信度**：高。
- **位置**：`webui/src/api/client.ts:357-368`；`components/ui/DownloadProgress.tsx:22`；`App.tsx:137`。
- **时序链**：ReadableStream chunks -> chunks array -> final Blob -> object URL；每 chunk progress setState -> provider 包含整个路由树。
- **成本**：大 ZIP JS heap 同时保留 chunks/Blob/object URL，峰值约文件大小 1x-2x+；高吞吐 chunk 导致数百/数千 provider update 和 route subtree render。
- **加固**：native navigation/attachment 或 file stream；progress rAF/100-250ms 节流并隔离 context；浏览器内存预算与 fallback。
- **验证**：0.5/1GiB slow ZIP 的 long task、heap、GC、commit 次数；进度 <=10Hz。

### PT-17 Landing preview pool 无端到端候选/预加载上限

- **置信度**：高。
- **位置**：`application/project_service.py:382`；`webui/src/pages/LandingPage.tsx:168,223,457`。
- **时序链**：server 返回全部 preview pool -> client 对每项 new Image -> 同时墙面最多 72 img。
- **成本**：大库入口可排队任意图片请求/decode；explicit preload 不受 `loading=lazy` 约束，竞争 LCP/网络/显存。
- **加固**：server cap 24-48；只 preload 首屏 6 + 1-2 前瞻；受控并发/hidden/unmount 废弃；decode 后提交和解除引用。
- **验证**：500/2000 pool 冷热缓存，测 LCP、请求数、decode、GPU/heap。

### PT-18 Revision 有序分配但跨线程 WS 投递无序；broadcast queue 无界

- **置信度**：高。
- **位置**：`domain/event_bus.py:119`；`application/runtime_events.py:251`；`lan/api.py:407-429`；`lan/ws.py:639-678`；`webui/src/stores/RealtimeContext.tsx:182`。
- **时序链**：thread A 分配 rev1但未投递 -> thread B 分配/投递 rev2 -> loop/socket 先见 rev2 -> client gap recovery + all-consumer fanout。每 event 还创建 broadcast coroutine，dispatching 只表示提交片段，慢 consumer/burst 可积压 task。
- **加固**：runtime revision ordered outbox；有界 queue/latest-wins coalescing/resync_required；记录 enqueue age/depth/out-of-order/gap recovery。
- **测试**：barrier 固定 rev2 先投递，socket 必须仍见 1,2；阻塞 send 后发布数千 event，queue 有界且 shutdown timely。

### PT-19 同 authority 慢 socket 会阻塞健康 socket并可能误驱逐

- **置信度**：高。
- **位置**：`lan/ws.py:648,669,678`。
- **时序链**：slow socket 在 authority lock 内 send -> healthy same-authority socket 等锁 -> shared 5s timeout 覆盖 lock wait + send -> gather 当作 dead 一起 evict。
- **成本**：同用户多标签健康连接被慢标签牵连；该 authority 后续 broadcast 最长 HOL 5s。
- **加固**：authority state lock 与 transport send 分离；per-socket bounded sender；分别记录 lock wait/send timeout，不将 lock wait 判 transport dead。
- **测试**：同 authority 两 socket，第一阻塞，第二必须可发且不被 evict；revoke 后仍不发 revoke 后帧。

### PT-20 Shutdown 总预算小于串行子预算，且 router/DB 仍有无界等待

- **置信度**：高。
- **位置**：`lan/server.py:555,1344`；`lan/scanner.py:48`；`application/gallery_service.py:136`；`application/runtime_events.py:297`；`core/database.py:459,1052`；`application/context.py:287`。
- **时序链**：LanServer stop 8s -> scanner join 2s + gallery 5s + prewarm 10s + WS/runner；window catches warning/error后继续；router inflight 与 DB write gate 无 deadline。
- **成本**：健康但串行排空可被 8s 外层假失败；一条 callback/read gate 可让 GUI 关闭无限等待；timeout 缺少 phase/straggler diagnostics。
- **加固**：single monotonic shutdown deadline，所有 phase 用 remaining budget；router/DB gate bounded drain；structured `drained/timed_out/forced/retry_pending` outcome + phase span。
- **测试**：注入 scanner/gallery/prewarm deadline、blocked callback/DB read；断言不假失败、不 hang、存在完整 shutdown summary。

## 4. P2/P3：静态候选，需 benchmark 或浏览器验证

1. **Catalog JSON1 path**：`shop_repository.py:498` 的 JSON expression + COUNT/page 是 `O(N)` 候选；无 JSON1 fallback `:551-581` 直接全量 fetch/parse/filter/slice。需 10k/100k/1m 数据、EXPLAIN/RSS/p95 测量。
2. **Metadata batch write**：`metadata_repository.py:482` 的无 chunk executemany 可能长 hold gate；需要 B=900/10k/100k WAL/hold 基准。
3. **Queue full snapshot mutation**：`reconciliation_queue_store.py:850-867` heartbeat/mutation `O(Q)`；默认 Q=200 有上界，需 Q/lease/poll 基准决定是否优化。
4. **Quicksearch**：`search_service.py:735,745,825` 的 `pop(0)` 和 repeated sort 有严格 512/10k/75ms budget；需慢盘和宽树 p95 验证。
5. **Gallery full projection**：`gallery_service.py:396-428`、`_projection_builder.py:295`、`_persistence.py:77` 有 O(F+I+N) state/JSON 峰值，但受 150k/60s 预算保护，需 RSS/GC/persist benchmark。
6. **Browse observer重建与卡片 memo失效**：`ProjectGrid.tsx:26`、`ProjectList.tsx:56`、`GalleryCard.tsx:21`，在 items identity/inline callback/context 改变时全量 observe/render；需 100/500/2000 Profiler 量化。
7. **ImageViewer/landing pointer/hero/CSS**：`ImageViewer.tsx:23-33`、`LandingPage.tsx:322-325`、`LandingPage.css:92-125`、`index.html:27`。需要 Chrome frame/LCP/CLS/GPU/heap 审计，不作为静态性能故障断言。
8. **Desktop cache maintenance**：`_base_logic.py:228`、`_loader.py:1070-1125` 可能在 UI binding/clear cache 上同步 IO，需 10k cache/慢盘验证。
9. **重连 retry storm**：`useWebSocket.ts:38`、`backoff.ts:49` 无 jitter，单 client 有上限，需 50 client 断网恢复测试量化峰值。
10. **Desktop tag tree bridge**：`_event_bridge.py:47`、`tag_tree.py:165,319` 无背压/revision gate，需 1k concurrent invalidation GUI queue 基准。

## 5. 现有防护与不应误报项

- `useCachedQuery` 有同 key in-flight dedup、AbortController、identity clear、旧响应身份检查；Realtime 有 epoch/revision/admission barrier/gap recovery。
- quicksearch、gallery traversal、thumbnail size、download path/size、ZIP worker、desktop loader 都已有输入/队列/时间预算；本报告指出的是预算之间的放大或缺少总成本预算。
- public catalog 正常 JSON1 SQL path 使用 LIMIT/OFFSET，buyer order 使用 keyset cursor；不能把所有分页写成未下推。
- Gallery card 的 `useQuota()` 使用共享 query key，不是每卡 HTTP N+1；问题是全量卡片 context/render，不是 quota request 数。
- WebSocket 有连接数、单 send timeout、authority lease、frame cap；问题是有序 outbox/backpressure与相同 authority HOL。
- 关闭流程有 cancellation、bounded local join、session close、retry和error日志；问题是顶层总 deadline、unbounded router/DB phase与诊断关联缺失。
- PerformanceRecorder/slow-query/DB lock metrics、perf baselines、nightly grid telemetry 和 shutdown stress 已存在；它们不是完整端到端性能门禁。

## 6. 性能观测基线缺口

当前 recorder 默认关闭、仅保留 200 个事件、没有 request/shutdown correlation ID。路由 metrics 主要是 request count，慢 SQL wrapper 未接入生产 managed connection；没有稳定的 event-loop lag、worker queue、WS outbox、React commit、browser long task、LCP/CLS、RSS/GPU/temp disk 或 stage-wise shutdown 指标。

建议新增最低观测合同：

```text
operation_id / shutdown_id / (epoch, revision)
  route / request attempt / identity generation
  queue_wait_ms / service_ms / lock_wait_ms / io_ms
  bytes_in/out / pixels / item_count / temp_disk_bytes
  worker/pool depth / ws outbox depth / send_ms
  event_loop_lag_ms / React commit_ms / long_task_ms
  phase outcome: drained | timed_out | cancelled | retry_pending
```

跨端时钟不可直接作单向网络 latency；服务端传 `published_at` 仅作诊断，每个进程使用 monotonic 分段测量。

## 7. 分阶段加固路线

### Phase A：先消除确定性阻塞和无界资源路径

1. 将 user login/register、Commerce/tag/activity DB 服务移出 aiohttp event loop，建立有界 crypto/DB executor。
2. 限制 thumbnail batch 的项数、总像素、encoded bytes、并发和取消；修复 Browse thumbnail 分块协议。
3. 给 ZIP 加取消、try/finally 清理、temp disk/queue budget、TTFB/transfer telemetry。
4. 修复 watcher `deque`、external-watch gallery dirty model、Gallery batch recompose 和 asset-index staging publication。
5. 修复 QueryCache entry eviction、buyer read lane、realtime query dirty/coalescing。

### Phase B：收敛全量 UI 和事件放大

1. Browse/Gallery 服务端 cursor/limit + 前端 virtual list；商城首页/详情/seller 去除旧全量 catalog。
2. 卡片 action/context 传递稳定化，observer 增量化，缩略图只处理可视 overscan。
3. Landing preview pool cap/controlled preload；下载避免 JS heap 全量聚合，节流进度更新。
4. Runtime ordered broadcast outbox、per-socket sender、truncation resync；desktop bridge latest-revision coalescing。

### Phase C：统一关停与可观测性

1. 单一 monotonic shutdown deadline 和 phase `DrainResult`；router/DB gate 与 local worker 都必须有 bounded/可重试终态。
2. 为 scanner/gallery/reconciliation/integrity/maintenance/ZIP/ffmpeg/WS 记录 queue、straggler、duration、outcome。
3. Managed DB 接入安全慢 SQL timing；route histograms、WS outbox/drop/evict、event-loop lag、temp disk 指标。
4. 建立 operation/revision/shutdown correlation，覆盖 mutation -> broadcast -> browser refresh -> close。

## 8. 动态验证与 CI 门禁矩阵

| 场景 | 关键指标 | 推荐测试位置 | 门禁 |
|---|---|---|---|
| 10 concurrent login/register | loop lag、PBKDF2 queue、HTTP p95 | `tests/lan/` 新增 async lag test | PR deterministic |
| Commerce/tag/DB lock | lock wait/hold、route p95、ticker | `tests/lan/test_concurrent_db_access.py` 扩展 | PR deterministic |
| thumbnail batch 1/24/100 | RSS、bytes、queue、cancelled | LAN integration + perf | nightly/容量 smoke |
| ZIP 0.5/1 GiB | TTFB、build、temp disk、cancel cleanup | download integration/perf | nightly/release |
| wide watcher/gallery burst | scan/rebuild rate、cache-miss time | gallery/watcher integration | PR small + nightly large |
| 100/500/2000 UI items | React commit、DOM、observer、heap | WebUI Profiler/render-counter tests | PR 100 + nightly large |
| 101/300/1000 thumbnails | request chunks、first visible, scroll frame | Playwright/browser | PR contract + nightly browser |
| 50 WS reconnect/slow same authority | outbox, gap/recovery, eviction | LAN WS integration | nightly/release |
| shutdown phase injection | total/p95/p99、worker/lease/DB state | lifecycle/shutdown integration | PR deterministic + Windows |
| Landing/4K/8K/download | LCP/CLS/long task/heap/GPU | Playwright/Chrome performance | nightly |

`pytest.ini` 默认排除 `perf/e2e`；nightly-perf 当前只跑 grid telemetry 且 `continue-on-error`。建议保留 artifact，但增加同 runner/fixture 的相对 p95 regression policy；PR 只跑确定性小规模性能 smoke，真实多 client/浏览器/大文件放 nightly/release。任何 benchmark JSON 必须包含样本数、p50/p95/p99、fixture/runner metadata，post-job 将超阈值转成可见失败或 issue。

## 9. 审计边界

本报告是静态性能与时序审计，不报告尚未测量的吞吐或绝对 SLA。P1 表示代码中已存在明确的同步、聚合、无界队列、顺序或预算不一致根因；P2/P3 候选需要在目标机器、Windows 文件系统、真实 SQLite/Pillow/ffmpeg、浏览器网络和生产规模数据下确认。全轮未修改代码、未运行服务或测试。