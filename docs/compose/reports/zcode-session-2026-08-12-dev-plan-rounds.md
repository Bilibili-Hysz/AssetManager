# ZCode 会话汇总 — 开发计划四轮实施（2026-08-12）

> **来源会话**：ZCode（deepseek-v4-flash），2026-08-12
> **任务**：基于全量审查的开发计划（安全收口 → 一致性 → 性能 → 前端功能）四轮实施
> **性质**：每轮语义化提交（无远程）
> **验证**：后端 3086 passed（xdist 113s）/ 前端 vitest 591 + tsc strict 0 错误 / ruff 全绿

## 第一轮：LAN 路径面收口（安全）

- **PathGuard**：新增 `InvalidPathError`——显式拒绝 C0 控制字符（`\x00-\x1f\x7f`，消除 Python 版本相关的 500/404 不确定行为）；Windows 上拒绝 root 内路径段含 `:`（NTFS ADS 流，防读取文件树外数据）
- `_helpers.py`：`validate_path`/`validated_existing_key` 捕获 `PathGuardError` → 400（escape 400 / missing 404 顺序保留）
- **10 处双重 unquote 全部移除**（downloads/thumbnails/metadata/shares/tags/gallery/image）——aiohttp match_info/query 单次解码契约；含字面 `%xx` 的文件名从 404/错文件变为正确命中（2 个回归测试实证）
- 验证：3080 passed

## 第二轮：数据一致性

- **reconciliation 心跳封顶**：续约截止 `renew_until + lease_seconds`（300s+30s）——卡死 worker 的租约会过期（原无限续约导致永久 RUNNING）
- **10s 周期 sweeper**：`recover_expired_running` 定期回收过期任务（卡死 worker 是唯一 claimer 时也能自愈）
- **add_url 原子化**：单条 `json_insert` append（跨连接无丢失更新）+ `json_valid` 畸形兜底 + `NOT EXISTS` 去重——测试证实双连接并发写不丢
- 验证：3082 passed

## 第三轮：性能

- **/api/home**：目录预览全覆盖时跳过 `thumbnail_cache` 全表扫描 + 每行 2 stat（提前退出）；v24 加 `idx_thumb_cache_mtime` 索引
- **/api/gallery/home**：30s TTL 缓存（全库遍历 + 每图 PIL 头部解码的重开销消除）
- **DB 迁移 v24**：`asset_dir_snapshot` 独立表（dir mtime）——避免混入 assets 表污染 count/remove/query 语义（初版加列方案因 13 个测试语义变化而重构）
- **M6a-18**：索引快速路径比较 dir_mtime 快照 vs 活目录——匹配 → SKIPPED，失配/NULL → 重扫回填；空目录也 SKIPPED
- 调试亮点：定位"upsert 未提交持写锁导致 CAS 无限等待"（`_repository_operation` 不自动提交）
- 验证：3085 passed

## 第四轮：前端功能

- **A4 单文件下载 blob 化**：`window.open` → blob + Content-Disposition 文件名 + 延迟 revoke；HTTP 失败以 ApiError 呈现（BrowsePage toast）；契约测试重写
- **BuyerOrders keyset 分页**：后端 `(created_at, id)` keyset 谓词 + base64url opaque cursor + `next_cursor`（行数==limit 时）；前端 load-more 按钮（loading/retry 态）；分页测试验证页间不相交/稳定排序
- 验证：后端 3086 passed / 前端 vitest 591 passed

## 文档同步

- `docs/full-review/06-audit-results.md` 待办表：8 项标记 ✅（#3/#4/#5/#11/#12/#14/#15/#16）

## 后续候选

- **M4 投递令牌 URL 明文**（delivery_url 含裸令牌，前后端配合改短 id/header）
- **架构统一**（桌面/LAN 双实现）、CI/远程仓库、发布流程——长期项
- 剩余低危清单（lan-tools scanner/tunnel/ws/dto 系列、runtime 系列、core-store 系列）
