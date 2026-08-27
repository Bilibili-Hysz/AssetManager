# 05 · 领域层 + 仓库层薄弱项审计（2026-08-22）

**范围**：`AssetsManager/domain/`（events/event_bus/errors/asset/auth/library/share）+ `AssetsManager/repositories/` 全部 17 个仓库。
**基线**：commit `5fbf930` 脏工作树。

## 总体评估

数据层的整体质量明显高于常见桌面应用水平：全部 17 个仓库的 SQL 均通过 `?` 参数化，**未发现任何值级 SQL 注入面**（所有动态片段要么是 `"?"*n` 占位符拼接，要么是白名单标识符/固定子句，SAVEPOINT 名均为内部常量 + hex，`asset_index_repository.py:23,358` 还对外部 savepoint 名做了正则校验）。Commerce 系通过共享的 `_transaction()`（shop_repository.py:58-73）统一实现了 SAVEPOINT + 外层事务探测 + `db_write_lock`，关键并发路径（下载配额、回执核销、share claim 核销、免下载配额）都用了单语句 CAS（`WHERE download_count=? AND ... < max_downloads` + rowcount 检查），乐观锁做得相当严谨。

系统性弱点集中在四个方向：**（1）两代事务模式并存**——Commerce/metadata/tag/asset_index 走 SAVEPOINT 助手，而 share/auth/favorite/thumbnail/plugin/gallery/revoked_token 共 27 个写方法仍是"`db_write_lock` + 裸 `commit()`"旧模式，其中 19 个无条件提交且不检查 `outer_transaction`；**（2）领域层贫血**——domain/ 没有任何 Commerce 模型，订单状态机 `ORDER_STATUSES/ALLOWED_TRANSITIONS` 竟然定义在 `order_repository.py:28-34`，且存在 `create_order` 不校验状态白名单、`transition_status_by_receipt` 完全不校验这类执行位置不一致；**（3）错误映射不统一**——shop_items 把 `IntegrityError` 包装为 `DuplicateError`，而订单/配送令牌/结账记录的约束冲突直接冒泡原生 `sqlite3.IntegrityError`；**（4）若干读-改-写窗口与批量缺失**——`update_item` 的合并读取在事务外（真实丢更新风险），5 处 `migrate_path/merge` 循环逐行 execute。

event_bus 设计干净（快照后无锁派发、handler 异常隔离、弱引用边界处理正确），仅 `BaseException` 不隔离一个小缺口。errors.py 层级扁平但够用，未发现错误信息携带敏感数据。

## 主要发现（按严重度排序）

### [P1][并发正确性] ShopRepository.update_item 合并读取发生在事务外，并发部分更新会丢字段 ✓已复核
- 位置：`AssetsManager/repositories/shop_repository.py:592-628`；佐证 `application/shop_service.py:453-470`
- 证据：`current_row = self._select_item(...)` 在 `with _transaction(self._conn, "shop_item_update")` **之前**执行（592 行 vs 605 行），随后在事务内用 `fields.get("x", current["x"])` 合并旧值。服务层明确支持部分更新（`self._fields(payload, partial=True)`）。
- 影响：两个线程/两个 LAN 客户端各改不同字段（A 改 title、B 改 price）时，B 的写锁事务虽串行，但其合并基线是 B 读到的旧快照——A 已提交的 title 会被 B 用旧值覆盖。`db_write_lock` 只保证单语句原子，不覆盖这个窗口。
- 建议：把合并读取移进 `_transaction` 块内（连接锁可重入，改动一行）；或改用单语句 `UPDATE ... SET col=COALESCE(?, col)`。

### [P1][事务一致性] 6 个仓库 27 个写方法是裸 `commit()` 模式，19 个无条件提交调用方事务
- 位置：`share_repository.py:365-374, 376-388, 400-414`；`auth_repository.py:261-286, 288-329, 347-383, 387-411, 437-446, 460-480`；`favorite_repository.py:37-56, 58-65`；`thumbnail_repository.py:31-44, 46-63, 82-86, 107-111`；`plugin_metadata_repository.py:80-108, 153-172`；`gallery_home_repository.py:35-51`
- 证据：`ShareRepository.insert`（:306-334）精心检查 `outer_transaction` 并用 SAVEPOINT，而**同文件**的 `delete`（:373 直接 `self._conn.commit()`）、`increment_download`、`set_password_hash` 直接提交。auth 的 8 个写方法、thumbnail 的全部写方法（部分连 `commit=False` 开关都没有，如 `delete_entry`/`touch_access`/`upsert_entry`）同样如此。
- 影响：潜在的事务撕裂——任何组合流（如 file_operation_service.py:1152-1181 的投影清理 savepoint 链）若现在或将来调用了这些方法，会把调用方未完成的一半事务提前提交。
- 建议：把 `_transaction()` 从 shop_repository 提为共享助手并统一接入；至少给全部裸 commit 方法补 `outer_transaction` 探测。

### [P2][并发] MetadataRepository.remove_url 仍是跨连接 read-modify-write，可丢失并发写入
- 位置：`metadata_repository.py:384-403`
- 证据：docstring 自认"same non-atomic read-modify-write caveat as add_url — only atomic per connection"。同文件 `add_url`（:345-382）已改为单语句 `json_insert` + NOT EXISTS 守卫，remove_url 没有跟进。
- 影响：连接 A remove 前读到 urls=[u1,u2]，连接 B 并发 add u3 并提交，A 写回 [u1]——u3 丢失。同连接下有 `db_write_lock` 保护，风险主要在多连接/多进程场景。
- 建议：用 `json_remove` + 子查询定位索引改写为单语句，或 `BEGIN IMMEDIATE` 包裹。

### [P2][N+1/批量缺失] 5 处 migrate/merge 循环内逐行 execute，无 executemany
- 位置：`tag_repository.py:541-559`；`metadata_repository.py:599-625`；`favorite_repository.py:84-104`；`shop_buyer_repository.py:185-218`（购物车合并）、`:525-529`（心愿单合并）
- 证据：均为 `for row in rows: self._conn.execute("INSERT ...")` 模式。对比项目里已有的正面样板：`order_repository.py:478-506` 的 `update_order_status_batch` 用 executemany + IN 分块，`metadata_repository.py:488-492` 的 `batch_set_cached_file_counts` 用 executemany。
- 影响：移动大目录（migrate_path）时行数 N 即 N 次往返。
- 建议：映射后的 `(mapped, tag)` 对先收集再 `executemany`。

### [P2][贫血领域] 订单状态机与配额不变式不在 domain 层，且执行位置不一致
- 位置：`order_repository.py:28-34`（状态机定义在仓库层）；domain/ 无 Order/Cart/Quota 模型；不变式分布：购物车 999 上限 shop_buyer_repository.py:209,258；心愿单 500 上限 :522,581-589；状态机检查 application/order_service.py:502,541
- 证据（不一致实例）：`transition_status`（:418-419）和 `update_order_status_batch`（:128-129）校验 `new_status ∈ ORDER_STATUSES`，但 `create_order`（:227-228）只检查非空——可创建任意状态（如直接 `fulfilled`）的订单，绕过整个状态机；`transition_status_by_receipt`（:509-551）对两个状态均不校验。下游 `stats()`（:1382）用 `result[f"{status}_orders"]` 动态生成键，脏状态会传播为任意键名。
- 影响：目前 application 层恒传 `status=PENDING` 缓解了 create 路径，但仓库作为"白名单单一事实源"（注释自称与 service 共享）自身不完备；领域规则泄漏到仓库层也让 domain/events.py 的 15 个事件里没有任何 Commerce 生命周期事件（只有聚合级 ShopOrderChanged）。
- 建议：在 create_order 补白名单校验；把状态机与不变式上移到 domain（值对象 + 纯函数），repository 只负责持久化与 CAS。

### [P2][错误层级] sqlite3 异常包装不一致，上层需要双重 catch
- 位置：正面：shop_repository.py:386-390, 623-626（IntegrityError → DuplicateError）；反面：order_repository.py:596-609（fulfill 的 delivery token UNIQUE 冲突裸冒泡）、:806-812（insert_share_claim）、shop_buyer_repository.py:368-379（checkout_record 撞 UNIQUE）、quota_repository.py:81-95（issue 撞 token_hash UNIQUE）
- 证据：同一类"唯一约束冲突=业务错误"，shop_items 映射为 `DuplicateError`，订单/令牌/结账路径则让 `sqlite3.IntegrityError` 直接穿透到 LAN 层变成 500。
- 影响：结账幂等竞态（两个同 request_key 的并发 checkout）会以未分类异常暴露，而非幂等重放响应。
- 建议：在 `_repository_operation` 或各写路径统一把 IntegrityError 翻译为领域错误（按约束名细分）。

### [P2][索引/查询] 高频搜索路径无法使用索引
- 位置：`asset_index_repository.py:536-542`（`LOWER(name) LIKE '%q%' ESCAPE '\'`）；`tag_repository.py:314-320`（`LOWER(tag)=LOWER(?)`）
- 证据：索引定义 db_migrations.py:508-511（`idx_assets_name ON assets(name)`、`idx_assets_ext`）。前导通配符 + LOWER 函数包裹使 `idx_assets_name` 失效；正面对照：`shop_orders` 侧 keyset 分页（order_repository.py:358-362）有 `idx_shop_orders_buyer_owner_created`（schema_defs.py:245）支撑。
- 影响：大库（索引表按设计承载全库文件）每次搜索是 library_root 子集内全扫；`get_files_by_tag_case_insensitive` 是 file_tags 全表扫。
- 建议：搜索列存归一化副本（lower(name)）建索引 + 前缀匹配，或 FTS5；tag 表加 `COLLATE NOCASE` 索引列。

### [P2][event_bus] publish 只隔离 Exception，BaseException 会穿透并中断剩余 handler
- 位置：`domain/event_bus.py:129-135`
- 证据：`except Exception: _log.exception(...)`。handler 内抛出 `SystemExit`/`KeyboardInterrupt`（如 Qt 退出路径、第三方插件调用 `sys.exit`）时，后续 handler 不再执行且异常穿透发布方。
- 影响：单个坏订阅者仍能"炸掉"发布方——恰恰是审查目标场景的非 Exception 变体。重入方面没问题：快照后无锁派发，handler 内再 subscribe/publish/unsubscribe 不会死锁。
- 建议：捕获 `BaseException` 后对非 Exception 类记日志后继续（或重抛），策略二选一并写进 docstring。

### [P2][分层] domain 层并非自足：依赖 core 包
- 位置：`domain/events.py:11`（`from AssetsManager.core.event_contracts import DomainEventBase`）；`domain/asset.py:7-10`（core.constants）+ :21（函数内延迟导入 core.format_utils）
- 证据：domain/__init__.py:4 声称"no dependencies on infrastructure"。core.event_contracts 本身是纯协议，但 core 包内含 sqlite3/文件系统模块，依赖方向没有结构性约束。
- 影响：概念漂移风险——后续向 core 添加依赖会无声进入 domain。
- 建议：把 event_contracts/constants 的纯数据部分物理移入 domain，或至少加 import-linter 规则锁死 domain→core 的白名单。

### [P2][事务语义] ShareRepository.insert 以 False 吞掉约束冲突，与项目错误惯例相悖
- 位置：`share_repository.py:336-348`
- 证据：IntegrityError → 精细的 savepoint 清理 → `return False`。注释明确区分"基础设施失败必须抛"，但业务冲突只给布尔值，调用方无法区分"share id 重复"与其他约束失败；order/shop 同场景抛 `DuplicateError`。
- 影响：错误层级分裂（布尔 vs 异常两套约定并存于仓库层）。
- 建议：统一抛 `DuplicateError("share link", share_id)`。

### [P3][并发回退] complete_delivery_attempt 竞态分支可能虚报 "consumed"
- 位置：`order_repository.py:1156-1174`（同型 :1254-1272）
- 证据：attempt 状态 CAS 失败后重读，若 `current is None` 或状态既非 consumed 也非 failed，落出 if 直接 `return "consumed"`。
- 影响：极端竞态下调用方可能把未最终定的 attempt 计为已消费（token 配额已扣，语义上勉强成立，但审计状态不实）。
- 建议：不满足条件时返回重读到的原始状态或抛审计异常。

### [P3][读副作用/快照一致性] CartRepository.get 会写库；写方法返回值来自第二个事务
- 位置：`shop_buyer_repository.py:127-135`（get 创建购物车 + 过期写状态）；`:289, 317, 353`（add/update/remove 在 `_transaction` 提交后调用 `self.get`）
- 证据：`add_item` 的写事务与返回快照不在同一事务，两个事务之间同连接其他线程可插入修改。
- 影响：调用方看到的 version/items 可能不是自己刚写入的结果（购物车 UI 偶发"回跳"）；"get 即建行"也让只读探针产生写入。
- 建议：写方法在同一 savepoint 内组装返回值；提供真正的只读 `peek`。

### [P3][冗余查询] find_checkout 对同一行发两次相同 SELECT
- 位置：`shop_buyer_repository.py:387-401`
- 证据：第一次取 `order_ids,request_fingerprint`，第二次取 `checkout_group_id,created_at`——WHERE 完全相同，可合并为一条。
- 影响：每次结账幂等查询多一次往返。

### [P3][迁移漂移] asset_dir_snapshot 单列主键在裸多根连接下跨根污染
- 位置：`asset_index_repository.py:449-456`（`ON CONFLICT(dir_path) DO UPDATE SET mtime=...`）；schema 见 db_migrations.py:849-853（`dir_path TEXT PRIMARY KEY`，不含 library_root）
- 证据：UPDATE 子句不更新 library_root，A 根的行会被写入 B 根的 mtime 且归属字段不变。仅 raw 兼容路径（同连接多根）可触发；session 绑定连接一库一连接，不可达。
- 影响：当前不可达的潜伏风险，正面对照：metadata_repository.py:531-551 用 `PRAGMA table_info` 优雅兼容缺列的老 schema。

### [P3][读锁不一致] 部分 Read 未过连接锁，与共享连接规约冲突
- 位置：`favorite_repository.py:23-35`（list_paths/contains 无锁）；`plugin_metadata_repository.py:110-126, 128-151`（get_fields/get_fields_for_children 无锁）
- 证据：`thumbnail_repository.py:19-29` 与 `gallery_home_repository.py:22-28` 的 docstring 明确"共享连接上的并发读会触发 SQLITE_MISUSE/InterfaceError，必须过 db_write_lock"；locked_read 装饰器（database.py:1237-1264）就是为此而生，但这两个仓库的读路径没接。
- 影响：桌面 UI 线程 + worker 共享连接时偶发 InterfaceError（与 thumbnail 修过的问题同源）。

### [P3][审计] update_order_status_batch 的事件丢失操作者
- 位置：`order_repository.py:498-506`
- 证据：executemany 的 INSERT 里 `actor_key` 硬编码 `NULL`，对比 `transition_status` 传 `actor_key`（:440-448）。
- 影响：批量状态变更在 `shop_order_events` 审计流中无主体。

## 次要问题清单

- `order_repository.py:200-228` — `create_order` 不校验 `status ∈ ORDER_STATUSES`（应用层恒传 PENDING 缓解）
- `order_repository.py:509-551` — `transition_status_by_receipt` 对 expected/new status 均无白名单校验
- `auth_repository.py:478-480` — `consume_invite_code` 的 `except Exception: return False` 把未知异常吞成"邀请码无效"，与 insert_user（:282-286 re-raise）语义相反；insert_user_with_invite:326-329 同样吞
- `seller_profile_repository.py:56-58` — `init_tables` 缺 `@_repository_operation`；`update_profile` 的 ensure-row 与 update 是两个独立事务
- `shop_repository.py:94-110` / seller_profile:42-44 / free_download:61-63 — init 逐条 `split(";")` 执行 DDL，可换 executescript
- `metadata_repository.py:215-219`、`tag_repository.py:195-199` — `_write_scope` raw 路径无条件 commit（无视调用方已有事务），与 session 路径行为分叉
- `asset_index_repository.py:352-419` — `transaction_scope(commit=False)` 且无外层事务时留下打开的事务由调用方兜底
- `order_repository.py:1390-1395` — `export_orders` 硬编码 5000 上限，超出静默截断
- `shop_buyer_repository.py:32-48` — `_cart` 的 `expires_at` 未做 float 归一（其余字段都归一了）
- `thumbnail_repository.py:31-35` vs :82-86 — `delete_entry` 与 `delete_by_key` 完全重复
- `plugin_metadata_repository.py:129-138` — docstring 说 "direct children"，实现是全部后代
- `event_bus.py:56-66` — 非绑定方法回退为强引用，不 close 则永不释放（docstring 已声明，属已知取舍）
- `domain/share.py:46-53` — `is_path_allowed` 用 normpath 前缀匹配，与 SQL 侧 `sql_like_descendant_pattern` 的转义规则是两套实现，边界（大小写、末尾斜杠）未对齐验证
- 时间戳来源混用：Python `time.time()`（多数）与 SQL `strftime('%s','now')`（share_links 默认值、invite used_at、thumbnail last_access、asset_dir_snapshot.updated_at）并存，时钟回拨时二者可不一致；全库统一为 epoch 秒 float，无 ISO 字符串混用（良好）

## 事务/注入面统计

| 维度 | 计数 | 说明 |
|---|---|---|
| 值级 SQL 拼接（注入面） | **0** | 全部 `?` 参数化；LIKE 输入均经 `\%_` 转义（shop_repository.py:476、asset_index:537） |
| 占位符拼接（`"?"*n` / `_in_placeholders`） | 9 处 | order 6、metadata 2、tag 1 |
| 白名单标识符/固定子句拼接 | 8 处 | order WHERE×3（:333,353-362,895-903）、shop 状态/目录子句×4、seller_profile:105 |
| SAVEPOINT 名 f-string | ~30 处（7 文件） | 均为内部前缀 + `id()/monotonic_ns()` hex；asset_index 对外部名有 `^[A-Za-z_][A-Za-z0-9_]*$` 校验 |
| 循环内 execute（业务） | 5 处 | tag:547、metadata:605、favorite:89、shop_buyer:185/526 |
| 循环内 execute（DDL split） | 3 处 | shop:106、seller_profile:42、free_download:61 |
| 冗余重复查询 | 1 处 | shop_buyer find_checkout:387-401 |
| 无 SAVEPOINT 裸 commit 写方法 | **27 个**（19 个无条件提交） | share 3、auth 8、favorite 4、thumbnail 6、plugin 4、gallery 2、revoked 2 |
| 使用 SAVEPOINT 助手的写方法 | ~65 个 | `_transaction`（commerce 系）、`_write_scope`（metadata/tag）、`transaction_scope`（asset_index） |

**总体结论**：无 P0。最值得投入的三项修复是 `update_item` 的事务外读取（一行改动）、裸 commit 旧模式的统一收敛、以及 `remove_url` 的单语句化；中期方向是把状态机/不变式从仓库层上移到 domain，并统一 sqlite3→领域错误的映射策略。
