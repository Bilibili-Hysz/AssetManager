# 02 · domain 领域层 + repositories 仓库层

> 状态：**DATED ANALYSIS（2026-09-04 实测快照）** · deep-analysis 系列之一，索引见 [README.md](README.md)。
> 方法：并行只读勘察代理全文件通读两层，并与 core/database.py、db_migrations.py、schema_defs.py、application/context.py、runtime_events.py 交叉引用；所有行数为 wc -l 实测。

---

## 1. 总览

```
domain/          8 个文件，1025 行 —— 纯领域层（值对象 + 15 个领域事件 + 事件总线 + 错误层级 + 纯密码学），零基础设施依赖
repositories/   14 个文件，6162 行 —— 12 个 SQL 仓库 + 1 个共享管线 _common.py + __init__
```

依赖方向（README.md:70）：`domain ← repositories ← application ← lan/panels`。domain 不 import 任何 SQLite/Qt；repositories 只依赖 core（database/path_resolver/schema_defs/session_contract）与 domain.errors。

一个结构细节：事件基类 `DomainEventBase` 放在 `core/event_contracts.py`（33 行），`domain.events.DomainEvent` 继承它——这让 core 插件宿主无需 import domain 即可校验事件钩子（core/event_contracts.py:1-7 模块注释说明动机）。

---

## 2. domain/ 清单与机制

| 文件 | 行数 | 内容 |
|---|---|---|
| `errors.py` | 62 | DomainError 层级（1 基类 + 6 子类） |
| `events.py` | 173 | 15 个冻结领域事件 + 基类 |
| `event_bus.py` | 145 | 进程内同步事件总线 + 弱引用订阅 |
| `auth.py` | 361 | 纯密码学：密钥/密码哈希、4 类 HMAC 令牌、强度校验 |
| `asset.py` | 117 | AssetPath / AssetType / AssetInfo + assert_under_root |
| `share.py` | 92 | ShareLink（过期/限额/路径范围判定 + to_public_dict 安全字典） |
| `library.py` | 61 | LibraryPath（确定性 RuntimeData 目录名） |
| `__init__.py` | 14 | 包说明 |

### 2.1 错误层级（errors.py）

全部为携带结构化字段的显式异常：`PathEscapeError(path, root)`（路径遍历）、`MissingPathError(path)`、`DuplicateError(entity, key)`、`NotFoundError(entity, key)`、`ValidationError(field, message)`、`OperationNotPermitted(message)`。仓储消费示例：TagRepository.rename_tag 抛 DuplicateError（tag_repository.py:523）、CollectionRepository create/rename（collection_repository.py:348,390,396）。

### 2.2 值对象

- **AssetPath**（frozen）：`absolute/relative/library_root` 三元组；`from_relative` 经 `assert_under_root`（resolve 后 is_relative_to 校验）防路径逃逸；相对路径统一 `\`→`/`。
- **AssetType**：`from_path` 借 core.format_utils.CATEGORY_MAP 分类（延迟 import，保持 domain 不依赖应用层）。
- **LibraryPath**：`root/data_dir/thumb_dir` + db_path 等派生；`_library_data_name` = `{basename}_{sha256(root)[:10]}`——同名库不同盘符不冲突。
- **ShareLink**（frozen）：is_expired / is_download_limit_reached / can_download / is_path_allowed（normpath 折叠 `..` 后前缀比较，根分享 "." 覆盖整库）/ **to_public_dict**（剥离 password_hash 的公开 API 安全字典）。

### 2.3 domain/auth.py（纯函数密码学）

- **密钥**：generate_access_key（128 bit hex）；PBKDF2-HMAC-SHA256，KEY_ITERATIONS=50,000。
- **密码**：自描述格式 `pbkdf2_sha256$iterations$salt$key`；PASSWORD_ITERATIONS=600,000（OWASP 2023）；legacy 裸 salt:key 按 100,000 回放；`needs_password_rehash` 驱动"登录成功后透明升级 cost"。成本常量调用时读取以便测试覆盖。
- **4 类 HMAC 令牌**（统一 HMAC-SHA256 截 32 hex，全部带随机 nonce 防同秒碰撞，且接受 legacy 无 nonce 格式直到过期）：单密码令牌（24h）、本地 UI 令牌（24h）、用户令牌（绑定 uid+username+role，24h；DB 查询留给调用方以保持 domain 无基础设施）、分享访问令牌（**1h**）。
- `validate_password_strength`：8-128 长度 + 大小写/数字/特殊字符 + 40 个弱密码黑名单（含去数字后缀变体匹配）。

### 2.4 15 个领域事件（events.py）

全部 `@dataclass(frozen=True)`，全部携带会话定位字段 `library_root + session_token`（会话作用域失效路由的基础）：

| # | 事件 | 行 | 语义与要点 |
|---|---|---|---|
| 1 | ShareChanged | 22 | 分享链接变更 |
| 2 | FavoritesChanged | 29 | + owner_key, paths |
| 3 | UserChanged | 38 | 用户（账户）变更 |
| 4 | InviteChanged | 45 | 邀请码变更 |
| 5 | ActivityChanged | 52 | 活动日志变更 |
| 6 | MaintenanceChanged | 59 | 维护任务完成——**纯 UI 通知，刻意不在 EVENT_DOMAINS 映射内**（:59-67 注释），Router 永不路由它；消费者直接订阅总线 |
| 7 | PresenceChanged | 74 | 在线状态变更 |
| 8 | FileSystemChanged | 83 | + kind, paths, old_paths |
| 9 | AssetTagsChanged | 95 | **双态约定**：单资产带 file_path+new_tags；目录级操作（rename_tag/delete_tag）发布恰好一个批量事件，paths 覆盖全部受影响资产而 file_path 为空，消费者必须重读（:96-102 注释） |
| 10 | TagCatalogChanged | 111 | 全库标签集合变更 |
| 11 | AssetNotesChanged | 118 | + file_path |
| 12 | AssetUrlsChanged | 126 | + file_path, new_urls |
| 13 | AssetRatingChanged | 135 | rating=None 表示清除/未评 |
| 14 | QuotaChanged | 149 | + name |
| 15 | CollectionChanged | 159 | 集合变更；**事件永不携带文件数据**——集合是查询视图/引用集，不是文件移动（:161-168 注释） |

**发布方/消费方实测**：发布全部发生在 **application 服务层**（metadata_service.py:212 发布 AssetRatingChanged、free_download_quota_service.py:156 发布 QuotaChanged、database_maintenance_service.py:323 发布 MaintenanceChanged）——仓储层不发布事件，是刻意的分层取舍：仓储保持纯存储。核心消费者是 RuntimeEventRouter（EVENT_DOMAINS 映射 13 个事件 → 13 个投影域）；其他直接订阅方：panels/info.py:383-388、dialogs/settings_dialog.py:1777-1785（排队 Qt 桥）、panels/_event_bridge.py、dialogs/undo_panel.py、lan/routes/_helpers.py。

### 2.5 event_bus.py 机制

- **线程安全**：是——`threading.Lock` 保护全部操作；单例 get_event_bus() 双检锁。
- **同步**：publish 按订阅顺序**内联**调用 handler，无队列/线程池/async。
- **弱引用双轨**：subscribe() 强引用（幂等 close 的 EventSubscription）；subscribe_weak() 用 WeakMethod（owner 死亡后 dispatch 中自动 close）；非绑定方法（lambda/函数）无法弱引用则**回退强引用**（注释：此类可调用不 pin 任何 owner）。
- **分发细节**：① 锁内做 handler 列表**快照**再锁外调用（防迭代中增删抖动）；② **单个 handler 异常被捕获只 log，不中断其余 handler**（失败隔离，但事件处理 bug 只出现在日志里）；③ 事件类型精确匹配 type(event)，无父子类路由。

---

## 3. repositories/ 清单

| 文件 | 行数 | for_session | 职责 |
|---|---|---|---|
| `_common.py` | 333 | 基类 | `_CommerceRepository` 提供 for_session + 共享管线（SAVEPOINT/CAS/BUSY 重试） |
| `tag_repository.py` | 656 | ✔ 严格契约 | 标签 CRUD（v36 三源分区：human/ai/plugin） |
| `metadata_repository.py` | 780 | ✔ 严格契约 | 备注/URL/评分/目录大小缓存 |
| `asset_index_repository.py` | 894 | ✔ 严格契约 | 惰性资产索引 + revision CAS |
| `collection_repository.py` | 543 | ✔ 严格契约 | 用户集合（v38 manual/smart） |
| `share_repository.py` | 441 | ✔ 旧方言 | 分享链接 CRUD + 条件原子自增 |
| `auth_repository.py` | 513 | ✔ 旧方言 | 用户/邀请码 + fail-closed 查询 |
| `plugin_metadata_repository.py` | 177 | ✔ 自有方言 | 插件解析键值对 |
| `free_download_quota_repository.py` | 226 | ✔（继承基类） | 访客下载配额（完整 CAS 消费） |
| `thumbnail_repository.py` | 269 | ✘ 仅 raw conn | 缩略图缓存元数据 |
| `favorite_repository.py` | 119 | ✘ 仅 raw conn | 收藏（单语句原子限额插入） |
| `gallery_home_repository.py` | 54 | ✘ 仅 raw conn | 全库画廊投影单行快照 |
| `revoked_token_repository.py` | 120 | ✘ 仅 raw conn | LAN 令牌吊销持久化（惰性 DDL） |
| `__init__.py` | 12 | — | — |

README 所称"12 个 SQL 仓库"属实（check_doc_stats.py:83-89 排除 __init__ 与下划线前缀文件）——但 README.md:64 架构图写"17 个"是陈旧数字（内部矛盾，见弱点 W-1）。

**各仓库职责表（表 ↔ 职责）**：

| 仓库 | 表 | 要点 |
|---|---|---|
| TagRepository | file_tags / ai_asset_tags / plugin_derived_fields / tag_metadata | v36 三源分区（白名单 _SOURCE_TABLES）；路径子树删除与迁移 |
| MetadataRepository | file_meta | URL 列表 JSON 列；0-5 评分 NULL=未评 |
| ThumbnailRepository | thumbnail_cache | **全元数据条件删除 CAS**；淘汰候选 |
| FavoriteRepository | library_favorites | 单语句原子 add（去重+限额一体）；LIMIT_CEILING=10,000 |
| ShareRepository | share_links | 软删除；**条件原子自增 download_count**；密码 cost 迁移 |
| AuthRepository | users / invite_codes | 邀请码原子核销（条件 UPDATE）；insert_user_with_invite 双语句原子注册；InviteCodeLookupError fail-closed |
| AssetIndexRepository | assets / asset_index_state / asset_dir_snapshot | 目录快照发布带 revision；**revision CAS**；拒绝无根删除（M9-Bug9） |
| PluginMetadataRepository | plugin_metadata | (file_path, plugin_id, field_key) 三元组 |
| FreeDownloadQuotaRepository | free_download_quota_windows | 完整 CAS 消费；identity 作用域 prune |
| GalleryHomeRepository | gallery_home（单行 id=1 CHECK） | 几十秒的全库扫描结果存一行，重启即取 |
| RevokedTokenRepository | revoked_tokens | 进程内存表死后吊销不能复活 |
| CollectionRepository | asset_collections / asset_collection_members | 成员引用增删幂等，从不移动文件；级联删除靠 v38 FK |

---

## 4. 统一模式（README 宣称的 for_session + SAVEPOINT + CAS 实测）

### 4.1 for_session 绑定（会话租约）

**协议契约**：core/session_contract.py 用**对象令牌**区分"真会话"与"结构相似的测试假件"——register_library_session 在 LibrarySession.__post_init__ 注册（application/context.py:162），require_library_session 校验。

**标准实现（TagRepository）**：
1. `for_session`（:121-138）：operation() 租约内 → 取 context.root_identity（必须 RootIdentity）→ connection_for(root) → require_managed_connection_owner → 构造 → _bind_session。
2. `_bind_session`（:152-199）四重防错：已绑其他会话→RuntimeError；**raw 操作已开始后禁止再绑**（单向门，防"发布后再改身份"）；显式 library_root 与会话不符→ValueError；连接不属于该会话→ValueError。最终经 `session._publish_while_live` **原子发布**（与 close 的精确线性化点）。
3. `_path_key`（:201-211）：绑定后所有路径先 resolve 再 is_relative_to 强制根包含性。
4. `@_repository_operation`：每个公有方法持有会话 operation() 租约。

**三套方言并存**（技术债 W-2）：新方言（require_library_session + RootIdentity：tag/collection/metadata/asset_index）、旧方言（duck-typing session.root/root_str：share/auth/_common）、自有方言（Path 比较：plugin_metadata）。

### 4.2 SAVEPOINT 模式

**通用原则**（_common._transaction :81-97）：进入即记 outer_transaction，开 `SAVEPOINT {prefix}_{monotonic_ns}`（单调时钟防同线程嵌套冲突）；成功 RELEASE 且仅当无外层事务才 commit；异常 ROLLBACK TO + RELEASE 后重抛。

**三处实现变体**：
- `_common._transaction`：最简形式。
- `_write_scope`（tag/collection/metadata）：raw 模式直接 commit、绑定模式开 SAVEPOINT；**失败清理也失败时用 exc.add_note 附带诊断而非吞掉原始异常**；可选 require_clean_transaction=True 拒绝在脏事务上变更。
- `transaction_scope`（asset_index）：支持**外部命名 savepoint**（正则白名单校验）；关键细节：**无外层事务时先显式 BEGIN 再开 SAVEPOINT**——SQLite 中最外层 SAVEPOINT 的 RELEASE 会直接提交，先 BEGIN 才能保证释放后仍可回滚（:394-398 注释）。

### 4.3 CAS 四类实测示例

**(a) 条件自增**（ShareRepository.increment_download :379-391）：
```sql
UPDATE share_links SET download_count = download_count + 1
WHERE id=? AND is_active=1
  AND (expires_at IS NULL OR expires_at > ?)
  AND (max_downloads IS NULL OR download_count < max_downloads)
```
超时/超限/停用任一不满足即 rowcount=0——**读-判-写在一条语句内完成，无 TOCTOU 窗口**。

**(b) 带期望值的双字段 CAS**（FreeDownloadQuotaRepository.consume :165-174）：
```sql
UPDATE free_download_quota_windows
SET download_count=download_count + 1, last_download_at=?
WHERE identity_key=? AND window_start=?
  AND download_count=?          -- 期望旧值
  AND download_count < ?
  AND (last_download_at=0 OR last_download_at <= ?)
```
并发写者赢走 CAS 时，在 savepoint 仍活动期间重读新状态精确报告 exhausted/rate_limited；整条在 savepoint 内 + BUSY 有界重试（重试从干净事务重放完整幂等 CAS）；过期清理刻意 identity 作用域，**防系统时钟回拨重置所有身份的桶**。

**(c) 乐观并发 revision**（AssetIndexRepository._advance_revision :273-324）：
```sql
UPDATE asset_index_state SET revision=revision+1, updated_at=?
WHERE library_root=? AND revision=?   -- expected
```
冲突 → 抛 AssetIndexRevisionConflict，扫描发布方据此感知"我基于过期的根 revision 发布"并重做。

**(d) 全行元数据条件删除**（ThumbnailRepository.delete_if_matches :196-228）：DELETE 的 WHERE 列出观察到的**全部**字段（含 NULL 安全的 `IS ?` 参数），只有"自我读取后无人改过"才删——缓存驱逐与并发 upsert 的安全竞争解法。

**(e) 单语句原子限额插入**（FavoriteRepository.add :45-65）：`INSERT ... SELECT ... WHERE NOT EXISTS(重复) AND (SELECT COUNT(*)) < max_items`——注释明言"消除 count-then-insert 窗口"。

### 4.4 _guarded_commit 与 BUSY 重试

- `_guarded_commit`（_common.py:241-257）：仅当**方法自身 DML 之前**采样到 in_transaction=False 才 commit——托管连接用 deferred 事务，事后采样无法区分"调用方持有"与"我刚开的"（docstring :247-253）。
- `_with_sqlite_busy_retry`（:260-317）：只重试 is_sqlite_busy_error；**调用方持有外层事务时彻底禁用重试**（绝不能把调用方事务回滚后在其下重放）；退避 min(0.25, 0.01×2ⁿ)、常量 30s 超时/3 次尝试。

---

## 5. 与 DatabaseManager 的关系（连接级读写门）

仓储不创建连接——**每库一条连接**，由 DatabaseManager 拥有：

1. **连接生命周期**：open_library 做 RuntimeData 身份标记 → 建连接（check_same_thread=False、timeout=30s）→ 注册 _ConnectionWriteState（每连接 RLock + closed 标志 + **library_root 归属**）。连接注册发生在 schema/迁移**之前**，失败也走同一可重试 close 契约。
2. **归属校验双 API**：require_managed_connection_owner（严格版——所有 for_session 用）与 validate_connection_owner（兼容版，放行裸连接——raw 构造路径用）。
3. **读写门三层**：_WriteGate（进程级读者/写者门，写者优先）→ db_write_lock(conn)（**所有仓储写的串行化入口**，双向死锁 fail-fast，等待/持有时间进遥测）→ locked_read（**读也过同一把连接锁**——LAN 三方线程共享一条连接，未串行化的 SELECT 与在途写事务会间歇性炸 database is locked；锁可重入，嵌套在 _write_scope 内安全）。
4. **迁移触发点**：preflight_recorded_version → executescript(_SCHEMA) → migrate_db → commit。
5. **migrate_path_metadata**：SAVEPOINT 包裹，一次性重映射 7 类投影表；缩略图文件重命名是 SQLite 无法回滚的外部副作用（docstring 明示）。

**关系总结**：DatabaseManager = 连接工厂 + 归属登记簿 + 每连接串行锁 + 全局读写门；仓储 = 拿到"已被门卫编号"的连接后，以 SAVEPOINT/CAS/_guarded_commit 构建不越权、不截断调用方事务的原子操作。

---

## 6. schema 迁移与仓库的关系

- 迁移执行器：core/db_migrations.py（CURRENT_SCHEMA_VERSION=46，MIGRATIONS 46 条）。
- **仓库适配 schema 演进的四类策略**：
  1. **契约即文档**：仓储注释直接引用迁移版本号作为 schema 唯一所有者（"migration v6 owns the schema" share_repository.py:213；v36 标签三源；v37/v38 asset_index/collection）。
  2. **init_table(s) 只是兼容垫片**：幂等建表（查 sqlite_master 跳过已存在 + 契约校验）——新库路径上根本不跑（open_library 已迁移），只服务 raw/legacy/测试连接。
  3. **缺失对象降级**：捕获 `no such table` 保持兼容行为；路径迁移对 v7/v37/v38 前的库先探测存在再迁移。
  4. **数据回填语义写进 SQL**：set_rating 的 NULL 本就是默认不回填；"v37 不回填，NULL=未评"。

---

## 7. 设计取舍（有注释佐证）

1. **每库单连接 + 连接级全串行**：用吞吐换正确性——LAN 三方线程共享一条连接，所有读写排成一条队。桌面 + 小型 LAN 下简单可靠；代价是无并发读。
2. **同步事件总线**：简单、可测试、无跨线程竞态；代价是没有背压/去抖，重投影需在 router 层做 drain/超时。
3. **SAVEPOINT 而非嵌套连接**：让仓储写可以安全嵌入调用方事务（撤销栈、文件操作事务）而不截断。
4. **CAS + 单语句复合条件 UPDATE**：把并发正确性压进 SQLite 本身（即使调用方各持不同托管连接也安全），不引入应用级锁。
5. **事件由服务层发布而非仓储发布**：仓储保持纯存储；代价是绕过服务层直接用 raw conn 写库时投影不失效（但 raw 通道被单向门 + root 校验大幅收窄）。
6. **fail-closed 贯穿**：has_active_users/has_active_invite_codes 基础设施失败必须 raise 而不能被解读为"无用户/无邀请码"（auth_repository.py:201-217, 496-513）；UnsupportedSchemaVersion 拒新库；锁序死锁 fail-fast 而非挂死。
7. **密码 cost 内嵌哈希**：未来提高 cost 是"登录时透明重戳"而非锁死。

---

## 8. 弱点 / 技术债清单

| # | 问题 | 锚点 | 严重度 |
|---|---|---|---|
| W-1 | README 数字自相矛盾："12 个仓库"(50/84/88) vs 架构图"17 个"(64) | README.md:64 vs :50 | 低 |
| W-2 | **三套会话绑定方言并存**——同一契约三份实现，漂移风险 | tag:62-69 vs share:42-50 vs plugin_metadata:42-48 | 高 |
| W-3 | **~100 行样板 × 4 文件复制粘贴**（_repository_operation/_bind_session/_write_scope 近乎逐字重复）；_CommerceRepository 基类已存在却只有 1 个使用者 | 四文件对比 | 高 |
| W-4 | **6/12 仓库无 for_session 绑定**（thumbnail/favorite/gallery_home/revoked_token 仅 raw conn）——归属/根包含性弱于其余 6 个 | 实测 grep | 中 |
| W-5 | **raw 通道的根校验是空操作**：_path_key 在 _library_root 为 None 时原样返回；asset_index 用"拒绝无根删除"补洞，tag/collection 未有同等防护 | tag:203-204 vs asset_index:781-790 | 中 |
| W-6 | **_common.py 商城遗产**：类名 _CommerceRepository、docstring 全篇 shop、COMMERCE_SCHEMAS 在迁移 v8；v11-v25 全为 shop 系迁移（ADR 0005 已剥离运行时） | _common.py:1-16 | 中 |
| W-7 | share.insert 把 IntegrityError 折叠成 False——重复 ID 与其他约束失败不可区分 | share:337-349 | 低 |
| W-8 | **revoked_tokens 双 schema 源**（迁移 v27 建表 + 仓库惰性 DDL）——DDL 漂移风险 | revoked_token:36-49 vs migrations:1518 | 中 |
| W-9 | auth.has_active_users 的 raise_on_error 参数已死（保留但被忽略） | auth:203-209 | 低 |
| W-10 | 逐行迁移 O(n) 语句（SELECT→循环 INSERT→DELETE 而非一条 UPDATE ... replace()） | tag:582-601 | 低-中 |
| W-11 | 常量双源（LIMIT_CEILING 刻意复制 favorite_service.MAX）；SlowQueryConnection 非 Connection 子类致 locked_read 对包装连接跳过加锁 | favorite:14-19; database:222-227 | 中 |
| W-12 | 事件 handler 异常静默吞掉（只 log）——失效通知丢失无重试/指标 | event_bus:130-135 | 低-中 |
| W-13 | 全局单例总线 + clear()：测试间易泄漏订阅；WeakEventSubscription 对 lambda 回退强引用 | event_bus:46-65 | 低 |
| W-14 | **性能弱点自认**：assets 表只索引 4 列，size/mtime/LIKE 全靠残差过滤 + TEMP B-TREE 排序，"加索引明确 out of scope" | asset_index:676-683 | 中 |
| W-15 | gallery_home 投影单行 JSON 无大小上限——超大库 IO 放大 | gallery_home:36-46 | 低 |
| W-16 | legacy 无 nonce 令牌格式全兼容面（有 TTL 硬界） | domain/auth.py | 低 |
| W-17 | rename_tag 冲突检查是 check-then-act——依赖"每库一连接"前提才安全；未来多连接化有 ABA 窗口 | tag:516-536 | 低（当前架构下） |
| W-18 | domain 事件混入 session_token 基础设施性字段——纯度让位于路由实用性 | events.py | 低（取舍） |

---

## 9. 总体评价

这两层呈现鲜明的工程风格：**正确性优先、防御性极强、每个坑都有编号和注释**（M9-Bug9、frozen_history_signature 防迁移改名砖库）——但代价是**样板爆炸与方言分裂**（W-2/W-3）：同一套"for_session + SAVEPOINT + CAS"思想被四五种略有差异的手写变体重复；`_common._CommerceRepository` 这个本应成为唯一基类的抽象已存在，却因商城剥离的历史包袱未能推广到全家族。重构方向明确：统一到 RootIdentity 方言 + 提取共享基类 + 收编 6 个 raw 仓库 + 清理 shop 遗产命名。

---

**关联阅读**：连接门/锁体系详解 → [01-core.md](01-core.md)；服务层如何消费仓库与发布事件 → [03-application.md](03-application.md)；auth 函数被 LAN 认证体系的使用 → [04-lan.md](04-lan.md)。
