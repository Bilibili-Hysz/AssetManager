# 数据流文档（03-data-flow.md）

> 审查日期：2026-08-11 · 工作区实况 · 每条链路含文件:行号锚点

## 0. 数据流总原则

1. **WebSocket 只是失效提示**：`projection_invalidated` 仅告知"哪些投影域过期"；权威数据一律 HTTP snapshot。
2. **断线恢复用游标**：前端维护 `{epoch, revision}`，恢复时 GET `/api/revision` 对账，缺口触发全量重取。
3. **会话隔离**：领域事件带 `session_token` + `library_root`，RuntimeEventRouter 校验后归一化为根内 POSIX 相对路径。
4. **桌面与 Web 双通道**：桌面面板直接订阅 EventBus（弱引用+Qt 桥）；Web 经 LAN WS 收投影失效。

---

## A. 信号/事件链路（概要，详见 04）

```
服务层变更 → EventBus.publish(会话事件)
   → RuntimeEventRouter._dispatch_event（校验 session_token/root，归一化 paths，next_revision）
   → InvalidationEvent(epoch, revision, domains, paths)
   → ① lan/api.py on_invalidation → ws_manager.broadcast("projection_invalidated")
   → ② panels/tag_tree RuntimeEventSubscription（桌面）
   → 前端 RealtimeContext：cursor 推进 / gap 检测 → recover() → notify(domains) → useInvalidation 回调 → 重拉 HTTP
```

---

## B. 端到端数据流（6 条链路）

### B1. 打开库（桌面→会话→LAN）

1. `app.py:135` `library_opened.connect(_on_open)` → `_on_open`（app.py:76-98）关闭旧窗 → `MainWindow(bootstrap)` → `workspace.add_library(path)`
2. `window.py:72` `library_service.open_session(path)` → `_open`（library_service.py:459-557）：`root_identity` 规范化（:124）→ `_acquire_library_lock`（:387，跨进程 QLockFile）→ 生命周期栅栏 → `LibrarySession.from_context`（:500）→ 发布 `LibraryOpened`（:554）
3. `window.py:77,80` `bootstrap.runtime_for(session)`（bootstrap.py:324-408）：构建 `LibraryScopedServices`（Auth/Share 共享 token_secret）→ 注册 3 个 lifecycle adapter → `reconciliation_service.start()`；`LibraryRuntime` 建 `RuntimeEventRouter`（runtime.py:32）
4. LAN 启动：`lan_sharing.py:215-260` → preflight 快照 → `ShareManager.start`（lan/manager.py:66-119）→ `LanServer(runtime=...)`（lan/__init__.py:41-80）→ `_LanServerImpl.start`（lan/server.py:464-525）后台 asyncio 线程
5. 路由安装（lan/api.py:144-291）→ webui `AuthContext.connect()` GET `/api/info`（system.py:21-60）引导

### B2. 浏览目录

- **Web**：`BrowsePage.tsx:40` useProjects → `filesApi.list` → `GET /api/files`（routes/files.py:15-60）→ `require_permission("browse")` → PathGuard.validate → `AssetService.list_directory`（asset_service.py:90-130：os.scandir + 摘要缓存 set_batch）→ `DirectoryListing`；缩略图 `GET /api/thumbnails/{path}`（ThumbnailService：cache key=sha256(path|mtime)[:16]，磁盘缓存→原图）+ 前端 `useThumbnailCache` batch 256px base64（sessionStorage 300 LRU）
- **桌面**：`file_list/_model.py` 不走 AssetService——直接 os.scandir 后台扫描（QRunnable）+ `_loader.py` QThreadPool(3) QImageReader 并行缩略图（BAKE 512）——**同一目录两种实现，语义对照靠 tests/lan 与 tests/desktop 分别覆盖**
- **失效**：文件变更 → FileOperationService `_notify_session_projection`（file_operation_service.py:378）→ `FileSystemChanged` → FILES/TREE/HOME/PROJECT_DETAIL/FAVORITES 域 → 前端 BrowsePage（['files','metadata','tags','project_detail']，按 event.paths 局部刷新）

### B3. 搜索（双轨）

1. 快速：`useSearch` → `GET /api/quicksearch`（routes/quicksearch.py:54-91）→ `SearchService.quick_search`（75ms 预算/512 目录/1 万条目/1000 匹配）
2. 完整：`GET /api/search`（routes/metadata.py:100-170）——带 tags → `search_by_tags_detailed`（file_tags，去重）；带 q → 主轨 `search_by_name_detailed`（内存 scanner 实时）→ 无结果回退 `search_by_name_indexed_detailed`（assets 表；DB 异常降级 ERROR source）
3. `SearchResultSet`（search_service.py:93-224）：多源 merge、逐源状态（COMPLETE/PARTIAL/DEGRADED/PATH_REJECTED/...）、`_contained_relative_path` 拒绝越界索引行（commonpath+反 `..`）
4. 前端：结果状态驱动 BrowsePage 搜索模式 / DetailPage 标签搜索

### B4. 分享创建与消费

1. **创建**（桌面）：`share_link_dialog.py` → ShareService.create_share（绑定 token_secret）→ `_publish_changed` → `ShareChanged` → SHARES 域广播；（LAN）`POST /api/shares`（manage_links 权限，≤100 路径）→ 拼 `{protocol}://{ip}:{port}/s/{id}`
2. **消费**：`GET /s/{id}`（SPA）→ ShareReceivePage → `GET /api/shares/{id}/info` → 密码验证 `POST /api/shares/{id}/verify`（PBKDF2 全量执行防时序 + 每分享失败计数 5/60s → 429 + Retry-After）→ 签发 scoped `share_token` cookie（path=/api/shares/{id}，1h）
3. **下载**：`GET /api/shares/{id}/download/{path}` → `validate_access`（存在/密码 token/过期/限额/路径作用域；401=需验证，其余折叠 404 防探测）→ **先构造 FileResponse 再 `increment_download`**（原子条件 UPDATE，超限 429）
4. **撤销**：`DELETE /api/shares/{id}`（admin 或创建者）→ is_active=0 即时阻断下载与令牌

### B5. 结账购买（买家→订单→投递→下载）

1. **购物车**：StorefrontCartPage → `POST /api/shop/cart/items`（版本乐观锁）→ CartRepository；guest 身份=签名 cookie token（`shop_cart_token`，365d）
2. **结账**：`POST /api/shop/cart/checkout`（shop.py:840-874）——`Idempotency-Key` 头/body；`ShopBuyerService.checkout`：单事务（cart_checkout：金额=item.price_cents×qty，价格/币种变更未确认 → PriceChangedError；request_key casefold+sha256 幂等）→ `OrderService.create_order`（_create_order 用校验时 item 透传定价）→ 事务外 `publish_order_events`（ShopOrderChanged/ActivityChanged/QuotaChanged → ORDERS/ACTIVITY/QUOTA 域）→ receipt 写入 HttpOnly cookie（`shop_order_receipt_{id}`，30d）
3. **履约**：seller `POST .../fulfill`（状态 confirmed→fulfilled，生成 delivery token 仅存 sha256）→ rotate（继承剩余配额+作废旧令牌）/revoke（全部令牌 revoked_at）
4. **下载**：`GET /api/shop/delivery/{token}/download`（shop.py:1088-1124）：`resolve_delivery(consume=False)` 先备好文件/ZIP（_delivery_file_response）→ **文件就绪后才 consume** → 失败走 `fail_delivery_attempt`（不耗配额）；配额 CAS：`complete_delivery_attempt(expected_download_count 条件更新)` + `_serialized_repository_operation` 串行化，竞态失败 → OperationNotPermitted("Download limit reached")
5. **免费配额**（普通下载）：`GET /api/download/*` → `consume_free_download_quota`（匿名身份=签名 cookie `am_quota_id`，默认 20 次/日 + 5s 最小间隔；**先准备响应成功再扣减**，429 时清理临时 ZIP）

### B6. 备份恢复

1. 桌面入口：`window.py:643-650` → `LibrarySettingsAdapter` → `create_backup/validate_backup/restore_backup`
2. **备份**（library_export_service.py:439-596）：目标禁覆盖 → 会话租约内 `_snapshot_database`（**独立只读连接 SQLite backup API**，锁内仅初始化）→ ZIP_DEFLATED 流式写入（manifest 上限 100k/64MB/512GB；持续变更文件 3 次后跳过+warning）→ progress/cancel 钩子（校验段亦含取消点）→ 生成后自校验 `validate_backup` → 原子发布
3. **恢复**（:1049-1100）：`_ensure_restore_admission`（失败状态机 RestoreFailureState）→ archive 预检（禁链接/需 overwrite 确认）→ LibraryLock → staging（`.{name}.restore-{uuid}`）→ 校验 → quick_check → 旧 data_dir 移 `_orphaned/restore-backups` → 替换 → installed quick_check；失败按 mutation_phase 毒化并隔离
4. **保留令牌 + ACK**：restore 失败写 `_root_restore_recovery`（token=f"{key}:{generation}:{urandom}:1"）→ `restore_state_provider/restore_acknowledger` CAS 确认；`restore_reservation` 上下文管理器在 library_service.py:311-362（_open 前置检查 `_restore_reservations`）

---

## C. 桌面内部数据流（Qt 信号体系）

- **面板间**：signal_bus（7 信号，低频协调）+ 面板直连（sidebar.directory_selected → MainWindow._on_sidebar_navigate → file_list.navigate_to）
- **域事件桥**：`panels/_event_bridge.py` DomainEventSubscription（EventBus 弱订阅 → Qt 信号 Queued 到 GUI 线程）——file_list 订阅 FileSystemChanged（500ms 防抖刷新）、info 订阅 AssetTagsChanged/AssetNotesChanged/AssetUrlsChanged（session_token 校验）
- **模型信号**：FileSystemModel（scan_started/scan_committed/state_changed/dir_size_ready）→ grid/detail 呈现；ThumbnailLoader.thumbnail_ready → ThumbnailDeliveryCoordinator（50ms 批量合并）
- **运行时投影**：TagTreePanel 用 RuntimeEventSubscription（ProjectionDomain.TAGS + epoch/generation 校验）

## D. 关键路径速查（文件:行号索引）

| 链路 | 锚点 |
|---|---|
| 打开库 | app.py:76-98 → library_service.py:459-557 → bootstrap.py:324-408 → lan/manager.py:66-119 → lan/server.py:464-525 |
| 事件广播桥 | lan/api.py:293-347（on_invalidation → ws_manager.broadcast） |
| 前端恢复 | webui/src/stores/RealtimeContext.tsx:89-189（recover/缺口检测）→ lan/routes/system.py:104-111（/api/revision） |
| 结账幂等 | lan/routes/shop.py:840-874 + shop_buyer_service.checkout + order_service._create_order |
| 投递配额 CAS | order_service.py:696-800（resolve_delivery）+ order_repository.complete_delivery_attempt |
| 备份 | library_export_service.py:439-596（创建）/ :1049-1100（恢复） |
| 投影域映射 | application/runtime_events.py:80-102 |
