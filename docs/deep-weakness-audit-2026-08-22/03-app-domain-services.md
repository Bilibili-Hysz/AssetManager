# 03 · 应用层领域服务薄弱项审计（2026-08-22）

**范围**：`AssetsManager/application/` 中的元数据/缩略图/搜索/项目/画廊/认证/分享/商城/配额/卖家系列服务（含 `gallery/` 子包与 `__init__.py` 导出面），并对 `repositories/` 与 `lan/routes/` 做了交叉验证。数据管线模块见 02 文档。
**基线**：commit `5fbf930` 脏工作树。

## 总体评估

这一层代码的总体质量显著高于常见桌面应用项目：路径安全（`assert_under_root`、reparse/软链接过滤、TOCTOU 复验）、凭据处理（token 只存 SHA-256、receipt 走 HttpOnly cookie）、配额原子性（`free_download_quota_repository`、`QuotaRepository.consume`、`increment_download`、`transition_status` 全部用条件 UPDATE/CAS）、订单状态机（`ALLOWED_TRANSITIONS` + expected_status CAS）和幂等下载（request_key 三态 reserved/consumed/failed + 重放豁免）都做得很扎实。会话绑定检查在每个服务里重复出现，虽然啰嗦但形成了统一的防错线。

主要薄弱点集中在三处：一是**缓存失效路径不完整**——`file_meta.cached_file_count` 既无 mtime 校验也无 TTL 也无任何写路径失效（与同表 `cached_size` 的 mtime+TTL 双校验形成鲜明且不一致的对照）；二是 **ShopService 的 metadata 整体替换语义**会让 status-only 更新静默清掉商品画廊图；三是若干**无界/无预算的读路径**（项目列表 N+1 文件系统扫描、按标签搜索无结果上限且 tags 数量不受限）。配额与结账的原子性验证未发现可超发/超卖路径：跨进程并发同幂等键 checkout 由 `UNIQUE(cart_id, checkout_generation, request_key)` 兜底，败者订单随 savepoint 回滚，只是错误形状是 500 而非幂等重放。未发现 P0 级问题。

## 主要发现（按严重度排序）

### [P1][缓存一致性] 项目 file_count 缓存永久陈旧：无 mtime 校验、无 TTL、无失效写路径 ✓已复核
- 位置：`AssetsManager/application/project_service.py:1001-1007`、`:519-553`；`AssetsManager/repositories/metadata_repository.py:433-445`
- 证据：`_file_count` 先查资产索引，索引为空则直接返回 `get_cached_file_count(str(path))`——该查询只判断 `cached_file_count IS NOT NULL`，不比对目录 mtime；写入侧 `set_cached_file_count` 也只存计数。全库 grep 确认没有任何代码在文件增删后清除该列；文件移动只通过 `COALESCE` 原样搬运计数。
- 影响：项目列表/详情的 `file_count` 在目录内容变化后无限期陈旧（索引缺失的库尤其如此）；与同表 `cached_size` 的"mtime + 30s TTL"双保险形成不一致的双标准。
- 建议：给 `file_meta` 增加 `cached_file_count_mtime`（或复用 `cached_mtime`），读时校验；或在 `_on_file_system_changed` / watcher 路径上对受影响目录清除计数。

### [P1][正确性/数据丢失] `ShopService.update_item`：status-only 或 metadata-only 更新整体覆盖 metadata，清空商品画廊图
- 位置：`AssetsManager/application/shop_service.py:195-200`（`_fields`）、`:457-467`（`update_item` 仅在 payload 含 `gallery_paths` 时才从 current 合并）；`AssetsManager/repositories/shop_repository.py:618`（`_json_dump(fields.get("metadata", ...))` 整列替换）
- 证据：partial 更新中 `if not partial or "metadata" in payload or "status" in payload:` → `payload={"status":"draft"}` 时 `raw_metadata={}`，`fields["metadata"]={"status":"draft"}`；`update_item` 因 `"gallery_paths" not in payload` 跳过合并；repo 端 `UPDATE ... metadata=?` 整体写入。
- 影响：任何只改 status（active/draft/archived 切换）或只传 metadata 的 PATCH 都会静默丢掉已配置的 `image_paths`（商品画廊）及其他 metadata 键。
- 建议：`update_item` 中当 `"status" in payload` 且 `"metadata" not in payload` 时，以 `current["metadata"]` 为底再写入 status；或 repo 端做 JSON 合并。

### [P2][缓存一致性/竞态] Gallery 增量应用与全量重建的 generation 竞态可丢失窗口期事件
- 位置：`AssetsManager/application/gallery/_incremental.py:90-97`（事件在 `_generation_lock` 下取 seq）、`:234`（`change.seq > state.generation` 过滤）；`gallery_service.py:443-455`（全量构建结束后才 bump generation）
- 证据：全量 walk 是非原子快照。若磁盘变更发生在"父目录已扫描完毕、构建尚未收尾"之间：事件 seq=N 入队；构建完成时 `_home_generation += 1` → `state.generation ≥ N` → 该事件被丢弃，而快照又未包含此变更。
- 影响：投影脏读持续到下一次 FS 事件触发 apply、或 30s 内存 TTL 过期触发重建。窗口为单次 walk 时长（大库可达数十秒），自愈但真实存在。
- 建议：构建开始前先记录 base generation，完成后仅将 `state.generation` 提升到"构建开始前已入队事件的 seq 上界"；或构建收尾时把 walk 期间入队的事件强制重新入队。

### [P2][幂等结账] 跨进程并发同幂等键：UNIQUE 兜底防重复，但败者以 IntegrityError 500 冒出而非幂等重放
- 位置：`shop_buyer_service.py:453-476`（`find_checkout` 查不到即走创建路径）、`:537-544`（`checkout_record` INSERT）；`shop_buyer_repository.py:356-379`；唯一约束在 `core/schema_defs.py:437`
- 证据：同连接下 aiohttp 单线程串行无碍；跨进程（桌面+LAN 同时 checkout）时两个事务都 `find_checkout=None`，都创建订单，第二个 INSERT 撞 UNIQUE，IntegrityError 穿透变 500；其 savepoint 回滚保证不重复下单（无超发）。
- 影响：客户端看到 500 而非 `idempotent: true` 的重放响应；重试可恢复。
- 建议：捕获 IntegrityError 后重读 `find_checkout` 走重放分支。

### [P2][配额语义错位] `QuotaService.consume(name, amount)` 把配额名当作 delivery token_hash 使用
- 位置：`quota_service.py:56-71`；`quota_repository.py:105-124`（`consume(self, token_hash, amount)`）
- 证据：`repo.consume(key, units)` 的第一参数是 SHA-256 token hash；用 `"orders"` 之类的名字查询必然 miss → 恒抛 `OperationNotPermitted`。另 `get_quota` 硬编码 `period="daily"`（quota_service.py:47），而底层 `QuotaRepository.get_quota` 是 delivery-token 生命期总量聚合，无任何周期语义。该服务只被 `get_commerce_services` 装配（`lan/routes/shop/_common.py:85`），`.quota` 无任何路由调用——属死接线。
- 影响：潜在地雷——一旦有调用方按"命名配额"语义使用即得到错误行为；`period: "daily"` 对 WebUI 是误导契约。
- 建议：要么删除 QuotaService 的 consume/period 伪装并标注 deprecated，要么实现真正的命名配额表。

### [P2][性能] 项目列表 N+1 文件系统扫描 + 每条目 TOCTOU 复验风暴
- 位置：`project_service.py:481-495`（每 entry 前后 `_revalidate_public_target`）、`:891-932`（`_entry_to_item`：`_first_image` scandir + `_dir_size` + `_tags` + `_notes`）、`:673-736`（`_attach_baked_thumbnails` 对全部缩略图行 stat）
- 证据：`_revalidate_public_target` → `_admit_public_target` 对 lexical 与 resolved 两条链逐组件 lstat，O(entries × depth)；每候选目录再各做一次子目录 scandir 与目录大小计算；`_attach_baked_thumbnails` 在任一项目缺 preview 时对 thumbnail 表全量行做 `source.stat()`。
- 影响：宽目录（数百子目录）或大缩略图表下 `/api/projects`、home 端点延迟显著；LAN 单请求可占用数秒磁盘。
- 建议：每请求做一次（而非每 entry）复验；`_first_image`/`_dir_size` 结果按目录缓存或复用 gallery 投影；baked 缩略图匹配限定在缺 preview 的项目路径前缀内。

### [P2][性能/DoS 面] `search_by_tags` 无结果上限，tags 数量在路由层不受限
- 位置：`search_service.py:364-371`（每个 tag 一次查询，结果集不设 limit）；`lan/routes/metadata.py:113-122`（`oversized_query` 只检查 `q`，`tags` 参数不检查长度/个数）
- 证据：`tags=a,b,c,...` 最多可塞约数千个 tag（受 aiohttp 请求行上限约束），每个触发一次 DB 查询并在 Python 侧做全量 containment/过滤；结果列表无上限返回。
- 影响：单请求可制造上千次顺序查询与超大响应；对照 `quick_search` 的 0.075s/512 目录预算，此端点是搜索面唯一无预算入口。
- 建议：服务层限制 tags 数（如 ≤32）与单源结果数（如 ≤500）；路由对 `tags` 参数复用 `oversized_query`。

### [P3][越权脚枪] `OrderService.confirm`（无凭据变体）保留在导出面
- 位置：`order_service.py:513-518`
- 证据：仅凭数字 order_id 即可将 pending → confirmed，无 receipt/owner 校验。路由层实际只用 `confirm_by_receipt`（`lan/routes/shop/orders.py:104-107`），`confirm` 仅测试调用。
- 影响：任何未来调用方（插件/新路由）接入即造成越权确认；与 `revoke_delivery` 显式要求 seller 的防御深度风格不一致。
- 建议：删除或改为要求 receipt/owner 断言的内部方法。

### [P3][事务/封装] checkout 内裸 SQL 绕过仓储封装
- 位置：`shop_buyer_service.py:545-548`
- 证据：`conn.execute("DELETE FROM shop_cart_items WHERE cart_id=?")`、`UPDATE shop_carts SET status='converted'...` 直接在应用层执行，且用 `time.time()` 而非注入 clock；同文件其余全部经由 CartRepository。
- 影响：表结构变更时此处会静默失配；与 `_prepare_cart_mutation`（repo 内做同样的事）逻辑重复且存在分叉风险。
- 建议：下沉为 `CartRepository.mark_converted(cart_id)`。

### [P3][数据导出] `export_orders` 静默截断 5000 行；CSV 含 `buyer_owner_key`
- 位置：`order_service.py:1039-1054`；`order_repository.py:1388-1391`
- 证据：`list_orders(limit=5000)` 硬编码且不告警；blocked 集合只剔除 `delivery_token_hash/token_hash/delivery_path`，`buyer_owner_key`（匿名买家的 guest token SHA-256）随 CSV 导出。
- 影响：超过 5000 单的库导出不完整且无提示；匿名凭据哈希外流到 CSV（离线爆破不可行，属信息面扩大）。
- 建议：分页导出或在截断时返回计数；把 `buyer_owner_key` 加入 blocked。

### [P3][事件遗漏] 下载消费不发布 ShopOrderChanged/QuotaChanged
- 位置：`order_service.py:754-832`（`resolve_delivery` 全程无 `_publish`）
- 证据：`download_count`/`last_download_at` 更新后无事件；对照 fulfill/rotate/revoke 均发布。
- 影响：卖家订单页与配额 UI 不会因买家下载而实时刷新。
- 建议：consume 成功分支补 `_publish(order_id)`。

### [P3][输入校验] 标签名不拒控制字符，与 catalog 查询的规范不一致
- 位置：`tag_service.py:25-34`；对照 `shop_service.py:74-75`（`normalize_catalog_query` 拒绝 Cc 类字符）
- 证据：`_validated_tag_name` 只做 strip/长度（≤200）；`\n`、`\r`、零宽字符可入库并进入 WebUI/CSV。
- 建议：与 catalog 查询统一加 `unicodedata.category == "Cc"`（可再补 Cf）拒绝。

### [P3][缓存卫生] TagService 路径 resolve 缓存无失效；rename/delete_tag N+1
- 位置：`tag_service.py:134-147`（10000 条满后整表 clear，之前永不失效）、`:304-331`（每文件一次 `get_tags` 查询 + 每文件一个事件）
- 证据：目录改名或 symlink 目标变更后，旧 raw path 仍映射旧 resolved key；重命名一个大标签（万级文件）产生万级查询与事件。
- 建议：缓存条目附带 mtime 粗校验或容量满时改 LRU；批量读取 tags 后合并发布事件。

### [P3][导出面泄漏] `application/__init__.py` 导出 bootstrap 装配内部类型与管线符号
- 位置：`application/__init__.py:125`、`:180-187`（`LanRuntimeServices`/`LibraryScopedServices`/`RuntimeSharingServices`），以及 reconciliation 队列 20+ 个内部符号（`:57-79`）
- 证据：这些是 DI 装配/管线的实现细节，却位于包级 `__all__`；反而 OrderService/ShopService 等真正的领域服务不在包面（需深层导入）。
- 影响：任何外部代码 `from AssetsManager.application import *` 即依赖无契约保证的符号。
- 建议：装配类型移回 bootstrap 模块 `__all__`；包面只保留领域服务与 DTO。

### [P3][行为不一致] `AssetService.list_directory` 不过滤 symlink/reparse，无条目上限
- 位置：`asset_service.py:103-115`（`list(os.scandir(target))`）、`:208`（`entry.is_dir()` 跟随符号链接）
- 证据：project_service 与 gallery 对链接/junction/OneDrive 占位符做了系统性过滤（`_is_link_or_reparse`、`_visible_entries`），此服务完全不做；导航进 symlink 目标会被路由层 `PathGuard.resolve` 的根包含检查拦下，但列表本身会展示越界链接且 `absolute_path` 指向库外。单目录条目数亦无上限（对照 gallery 的 150k 预算）。
- 建议：复用 `asset_filters`/gallery 的 reparse 判定过滤列表项；加每目录条目软上限。

## 次要问题清单

- `metadata_service.set_notes`（:226-233）服务层不限长度；LAN 路由限 4000，桌面路径依赖调用者自律
- `order_service._create_order`（:253-254）邮箱校验仅 `"@" not in`，`"@@"` 可通过；buyer_name 不拒控制字符
- `_decode_order_cursor`（:100-113）`float()` 接受 `nan/inf`，SQL 比较恒 false，无实害但未拒
- `shop_cart_checkouts` 无任何清理/TTL（全库无 DELETE），幂等记录无限增长（量级低）
- `thumbnail_service._cache`（:28-30）模块级全局、按 raw path 跨库共享，相对路径 + 相同 mtime 理论上可串键；FIFO 驱逐而非 LRU
- `metadata_service._size_cache_ts`（:56）无界增长（按访问过的目录数）
- `plugin_service` 多处直读 `manager._host_context` 私有属性（:61-64,71,86）；模块导入副作用 `set_category_registry_provider`（:20）
- `gallery_service.get_home_cached` 在持有 `_home_cache_lock` 时做持久层 DB 读（:251），慢盘会阻塞所有读缓存者
- seller 会话（`seller_auth_service.py:97-113`）管理员降权/停用即时闭环，但密码轮换不失效既有 12h 会话
- `gallery/_incremental._recompute_cover`（:871-897）PIL 解码不经预算（`budget=None` 恒可解码）
- `QuotaService.get_quota` 的 `min_interval_seconds: 0` / `reset_at: None` 与 free-download 配置面不一致（:45-53）
- `shop_service._gallery`/`_path` 在无事务包裹下做文件存在性 I/O（TOCTOU 良性）
- `search_service.search_by_name` 的 `limit` 参数服务层不 clamp（当前路由只用默认 200）
- `asset_filters.rebuild` 中 `FILTER_CATEGORIES` 以 display label 为键做 `setdefault`，两个插件同 label 时静默丢后者
- `probe_environment`（`security_preflight.py:244-248`）只绑 IPv4 `0.0.0.0`，IPv6-only 占用探测不到
- `storefront_analytics_service._visitor_hash` 正常；`record_storefront_view` 的 prune 每请求一次（量小可接受）

## 规模与复杂度观察

- 精读的六个大文件（order 1072 / project 1056 / gallery/_incremental 1015 / search 861 / shop_buyer 646 / thumbnail 467）合计约 5100 行；mixin 拆分（gallery 三 mixin + types + facade）使单一文件保持在千行左右。
- 防御性校验代码（session/provider 归属检查、`_record` 兜底）在 20+ 个服务中逐字重复，估计占这层代码 15-20%；值得提取到公共基类/装饰器（`_CommerceRepository` 已示范了一半）。
- 复杂度热点集中在 gallery 增量引擎（`_apply_dir_event` 三个分支各 60-100 行、依赖大量隐式状态不变式）与 order 配送幂等三态机（reserve/complete/fail × bearer/receipt 两轴共 6 个方法，逻辑高度对称但手工保持一致）——这两处是未来回归风险最高的区域，建议补表驱动测试。
- 跨层重复实现的三处逻辑值得统一：邮箱校验（order vs seller_profile 的 `_EMAIL_PATTERN`）、控制字符拒绝（catalog vs tag）、目录摘要扫描（project `_first_image` vs asset `_scan_dir_summary` vs gallery `_visible_entries`，三者 mtime/缓存策略各不相同，正是 P1 file_count 问题的土壤）。
