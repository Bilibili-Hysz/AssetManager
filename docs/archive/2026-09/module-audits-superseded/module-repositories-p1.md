# 模块排 Bug 清单（module-repositories-p1.md · 2026-08-11 P1 第1轮）
> 状态:**历史底稿(已过期)** · 2026-08-11 P1 轮行号级审计,行号已随代码演化失效;发现项由后续评审批次关闭 · 状态登记:2026-09-02(文档梳理轮补登)


> 来源: 只读探索代理审计（ZCode Explore），行号经源码逐一核对，调用点经 grep 交叉验证。
> 范围: `AssetsManager/repositories/` 全部 15 个仓库文件 + `__init__.py`（5734 行）。
> 结果: 高 0 / 中 5 / 低 10（性能合并为 1 条，若拆分计 4 条）。

## 检查点结论（P0 复核 — 以下结论仍成立，无问题）

| # | 复核项 | 结论 | 证据 |
|---|--------|------|------|
| C1 | SQL 全参数化 | 通过 | 15 文件所有 SQL 均为 `?` 占位；动态 SQL 仅来自固定字面量/白名单字段 |
| C2 | LIKE 通配符转义 | 通过 | sql_like_descendant_pattern 转义 `\`、`%`、`_`；各 LIKE ? ESCAPE '\' 使用正确 |
| C3 | ORDER BY / LIMIT / OFFSET | 通过 | 全部排序键为固定字面量；LIMIT/OFFSET 全参数化 |
| C4 | for_session 绑定校验 | 通过 | 均校验 session 契约、连接所有权、root map_key 匹配 |
| C5 | 会话租约 | 通过 | LibrarySession.operation() 可重入、close 排空、_publish_while_live 线性化 |
| C6 | 下载/配额竞态 CAS | 通过 | QuotaRepository.consume、FreeDownloadQuotaRepository.consume、OrderRepository.consume_download、ShareRepository.increment_download 均原子条件 UPDATE |
| C7 | 事务回滚 | 通过 | _transaction/_write_scope/transaction_scope 均 SAVEPOINT + ROLLBACK TO + 保留外层事务 |
| C8 | FK/级联/重复键 | 通过 | PRAGMA foreign_keys=ON；commerce 表 FK 齐备；upsert 全用 ON CONFLICT |
| C9 | 观察项 | 说明 | db_write_lock 为每连接粒度锁；跨连接一致性依赖 SQLite 文件锁（WAL + timeout=30）与 CAS |

## 缺陷清单

### 中（5）

**Bug 1 - plugin_metadata 子目录查询 LIKE 缺 `_` 转义（目录名含下划线时聚合错乱）**
- 位置: `repositories/plugin_metadata_repository.py:118-122`
- 描述: get_fields_for_children 手工转义只做了 `\` 与 `%`,漏掉 `_`。SQLite LIKE 中 `_` 匹配任意单字符: 目录 `My_Assets` 的模式 `My_Assets/%` 会命中 `MyXAssets/`、`My-Assets/` 等兄弟目录,把无关文件的插件元数据聚合进当前文件夹视图。
- 修复: 补 `.replace("_", "\\_")`,或直接复用 `sql_like_descendant_pattern`（注意其含路径自身,需按现有语义调整）。

**Bug 2 - complete_delivery_attempt(_by_receipt) 的 expected_download_count 是死参数（乐观校验缺失）**
- 位置: `repositories/order_repository.py:706-772`（bearer）、775-856（receipt）;调用点 `application/order_service.py:707, 779`
- 描述: 两个方法接收 expected_download_count 但 UPDATE 的 WHERE 只有 download_count<max_downloads,无 download_count=? 条件（对比 consume_download order:869-881 有严格 CAS）。服务层用消费前的快照值传入,该值永不参与校验——客户端快照过期也不会被拒绝。配额上限仍由 download_count<max_downloads 兜底、不越权,但乐观并发契约被静默架空。
- 修复: 在两条 UPDATE 的 WHERE 中补 AND download_count=?,失败时走既有 delivery_quota_exhausted 失败分支;或删掉死参数并同步调用方。

**Bug 3 - rename_tag 不迁移 tag_metadata,且目标 tag 已存在时未捕获 IntegrityError → 500**
- 位置: `repositories/tag_repository.py:448-466`
- 描述: ①UPDATE file_tags SET tag=? 只改 file_tags,tag_metadata（color/icon/category）留在旧名成为孤儿行,新名查不到元数据——改名即丢样式。②若 new_name 已存在且某文件同时挂两个 tag,UNIQUE(file_path, tag) 冲突抛 IntegrityError,_write_scope 回滚后原样上抛,tag_service.rename_tag 无捕获 → LAN/UI 500。
- 修复: 事务内同步 UPDATE tag_metadata SET tag=? WHERE tag=?（目标行存在时合并或报业务错）;对 IntegrityError 预检冲突并抛业务异常（如 ValidationError）。

**Bug 4 - create_item / update_item 重复 path 触发未捕获 IntegrityError → 500**
- 位置: `repositories/shop_repository.py:310-333`（create）、541-559（update）
- 描述: shop_items.path 有 UNIQUE 约束。create_item 对已存在 path、update_item 改到他人已占用的 path 时抛 sqlite3.IntegrityError,_transaction 回滚后上抛;shop_service.create_item 与路由均无捕获 → LAN API 500 而非 4xx,桌面端保存商品时若路径冲突直接崩溃。
- 修复: 两处 catch IntegrityError → 转业务异常（冲突 409/ValidationError）;或在 create_item/update_item 内先 get_by_path 预检并返回明确错误。

**Bug 5 - list_items 的 status 过滤发生在 SQL LIMIT 之后（结果不完整）**
- 位置: `repositories/shop_repository.py:350-380`
- 描述: list_items 先在 SQL 取最新 500 条（ORDER BY updated_at DESC LIMIT ?）,再用 Python 过滤 status（行 371-380）。当库内条目 >500 且目标状态集中在更早的记录时,返回列表短于实际匹配数甚至为空。list_catalog 无此问题（状态在 SQL 层过滤）。
- 修复: status 过滤下推 SQL（enabled+metadata CASE 表达式,参考 list_catalog:458-464 的写法）;或先全量过滤再分页。

### 低（10）

**Bug 6 - complete_delivery_attempt 状态机跨连接竞态: 审计行最终态可能与实际不符**
- 位置: `repositories/order_repository.py:767-772`、851-856
- 描述: token CAS 失败者先执行 UPDATE shop_delivery_attempts SET state='failed'...;赢家随后执行 UPDATE ... SET state='consumed' WHERE id=? AND state='reserved',rowcount 未检查,若输家已先落 failed,赢家仍返回 "consumed" 且下载照常放行——审计行显示 failed 但下载成功。配额不会被突破（CAS 兜底）,属审计/重试语义不一致。
- 修复: 检查第二次 UPDATE rowcount;为 0 时重读行、以实际状态为准返回,并记录异常。

**Bug 7 - 免费下载配额每次消费全表 DELETE 旧窗口;系统时钟回拨可致全库配额重置**
- 位置: `repositories/free_download_quota_repository.py:105-116`（DELETE 在 108-110）
- 描述: 每次 consume 都执行 DELETE FROM free_download_quota_windows WHERE window_start < ?,删除所有身份的过期窗口（自清理设计,正常无害）。但 window_start 由服务器时钟计算（非客户端可控）;一旦系统时钟回拨（NTP 校正/手动改时）,他人仍在有效期内的窗口行被删,其配额随 INSERT OR IGNORE 重建为 0 → 免费下载限额被绕过直至时钟追回。
- 修复: 仅清理本身份过期窗口（WHERE 加 identity_key=?）,并限制 start 不低于上次记录值。

**Bug 8 - transition_status / set_status 仓库层无状态白名单（潜伏越权路径）**
- 位置: `repositories/order_repository.py:264-308`（transition_status）、996-1011（set_status）
- 描述: 仓库层 transition_status 只做 WHERE id=? AND status=? CAS,不校验 new_status 合法性/可达性——fulfilled → revoked 在仓库层可行且只吊销 receipt/recovery,不吊销 delivery token。服务层 _ALLOWED_TRANSITIONS 挡住了当前全部调用点;set_status 经 grep 无任何调用者。属潜伏风险。
- 修复: 仓库层加 new_status 白名单与状态机校验（与 service 共享常量）,或删除 set_status 死代码。

**Bug 9 - AssetIndexRepository raw 模式 delete 跨 library_root 删除**
- 位置: `repositories/asset_index_repository.py:519-534`（delete_entry）、537-557（delete_path）
- 描述: 未绑定 root 的 raw 连接下,DELETE FROM assets WHERE file_path=? 不带 library_root 过滤——同一 file_path 存在于多个 root 时全部被删。当前调用点均走绑定路径（带 library_root）,仅 legacy raw 调用者受影响。
- 修复: raw 模式改为显式拒绝无 root 的删除（要求调用者传 library_root）,或按匹配到的 revision_roots 逐个限定删除。

**Bug 10 - metadata add_url/remove_url JSON 读改写跨连接丢失更新**
- 位置: `repositories/metadata_repository.py:337-368`
- 描述: 先 get_urls 读、改、再整体写回 JSON。db_write_lock 为每连接粒度,LAN 服务器与桌面端两个连接并发加/删 URL 时后写覆盖先写,URL 静默丢失。单连接内无问题。
- 修复: 接受"低损"现状,或在更新时用 json_extract/新表结构做原子 append;至少注释说明并发语义。

**Bug 11 - FavoriteRepository.add 的 count-then-insert 跨连接可超限 1 条**
- 位置: `repositories/favorite_repository.py:37-52`
- 描述: SELECT COUNT(*) 与 INSERT 之间仅靠每连接锁;两个连接并发时均通过上限检查 → 收藏数 = max+1。上限 500 且调用点捕获 OverflowError 转业务错误,影响极小。
- 修复: 无强需求;如需严格上限可改为 INSERT ... SELECT ... WHERE (SELECT COUNT(*)) < ? 单语句。

**Bug 12 - share_repository 对损坏 paths JSON 无保护**
- 位置: `repositories/share_repository.py:256`（get）、397（_row_to_dict）
- 描述: json.loads(paths_json) 无 try/except——手工改库或旧格式数据损坏时,公开分享访问路径直接 JSONDecodeError → 500（对比 metadata _decode_urls 有保护）。
- 修复: 仿照 _json_load 容错,损坏时记日志并返回空列表/标记失效。

**Bug 13 - ThumbnailRepository.delete_path 用 os.sep 而非 path_key_separator**
- 位置: `repositories/thumbnail_repository.py:81-93`
- 描述: 子项模式用 os.sep.replace("\\","\\\\") + "%" 拼接。Windows 下与 sql_like_descendant_pattern 等价;但便携式 fixture 或混用 `/` 的库路径（path_resolver.py:26-41 明确支持）下分隔符不匹配,后代缩略图条目删除不干净,遗留孤儿缓存。
- 修复: 复用 sql_like_descendant_pattern(source_path)。

**Bug 14 - auth_repository 吞掉未知异常静默返回 None（失败不可见）**
- 位置: `repositories/auth_repository.py:275-278`（insert_user）、370-373（insert_invite_code）
- 描述: 两个方法最后的裸 except Exception 记日志后返回 None/False——非 sqlite 的编程错误被当作"业务约束拒绝",注册/邀请创建静默失败。
- 修复: 区分"可预期约束错误"（IntegrityError）与其余异常（后者必须 re-raise）,与 insert_user_with_invite 的既有分层对齐。

**Bug 15 - 性能合并项（4 处，均为低）**
- `asset_index_repository.py:510-516` — LOWER(name) LIKE '%..%' 前导通配 → idx_assets_name 不可用,大库搜索全表扫描。
- `plugin_metadata_repository.py:118-122` — 前缀 LIKE 默认大小写不敏感无法走 B-tree 索引,每次点击文件夹全扫。
- `shop_repository.py:417-428` — list_catalog 每请求执行 JSON1 探测 SELECT json_valid(?)（可初始化时探测一次并缓存）。
- `storefront_analytics_repository.py:60-62` — record_unique_view_and_prune 每次视图都执行全表 prune DELETE（可用低频清理任务替代）。
- 修复: 按需优化;JSON1 探测缓存收益最直接。

## 修复分组（按文件集互不相交）

| 组 | 文件 | 修复项 |
|----|------|--------|
| A | plugin_metadata_repository.py | Bug 1、Bug 15-2 |
| B | order_repository.py | Bug 2、Bug 6、Bug 8 |
| C | tag_repository.py | Bug 3 |
| D | shop_repository.py | Bug 4、Bug 5、Bug 15-3 |
| E | free_download_quota_repository.py | Bug 7 |
| F | asset_index_repository.py | Bug 9、Bug 15-1 |
| G | metadata_repository.py + favorite_repository.py + thumbnail_repository.py | Bug 10、11、13 |
| H | share_repository.py + auth_repository.py + storefront_analytics_repository.py | Bug 12、14、15-4 |
