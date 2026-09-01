# T0 止血系列实施总结 · 2026-08-30

## 背景

任务包 `docs/archive/2026-09/plans-done/task-package-2026-08-30.md` 阶段 0（止血：数据正确性 + 兑现已投入）。
T0-1/T0-2 在上一段会话完成，本轮完成 T0-3（a/b/c 三部分）并收尾。

## 完成事项

### T0-1 · 派生物 mtime 失效（`85e9cf2`）
源文件变更后重建波形/调色板（原逻辑只判"行存在"）。

### T0-2 · 路径迁移缺口（`cb03617`）
派生物/合集成员纳入路径重映射 + `clear()` 接调用点，改名不再丢派生物与合集成员。

### T0-3a · 三源标签聚合（`b547c0a`）
- `tag_repository.list_file_tags(source=...)` 按物理分区取数（file_tags / ai_asset_tags / plugin_derived_fields）
- tag 树聚合三源并标注 source；human 保留 tag_metadata 颜色/图标，ai=star、plugin=puzzle（muted）
- 非 human 只读：点击仅展开折叠、无右键编辑菜单
- 批量聚合维持单条 SQL，防 N+1（12 passed）

### T0-3b · rating 读写链路（`e141ae5`）
- `AssetRatingChanged` 域事件；`MetadataRepository.get_rating/set_rating`（0-5 校验，显式拒绝 bool）
- `get_metadata` 三合一查询（notes+urls+rating 一次 file_meta 查询），守住"业务查询恰 2 次"性能契约
- `PUT /api/rating/{path}`（复用 `_WRITE_NOTES_BROWSE` policy）；`GET /api/meta` 响应含 rating
- `migrate_path` 两处补 rating 列迁移（防改名丢评分）
- LAN 测试库 mirror v37 rating 列（fixture 用 baseline `_SCHEMA` 建库导致缺列）

### T0-3c · 信息面板评星 UI（`6afe91b`）
- 元数据区 5 星控件：favorite 金点亮 / icon_muted 未点亮；点击第 N 星写入 N，重击当前星清除
- 订阅 `AssetRatingChanged` 跨会话刷新；主题/语言/缩放变更强制重绘
- i18n 三语新增 `info.rating` / `info.rating_star`

### 回执与统计同步（`0faeefd`）
- 任务包 §8 补 T0 系列实施记录
- README 统计 `check_doc_stats --fix`：routes 70→71、domain_events 14→15、i18n 884→886

## 门禁与测试

- **pytest**：T0-3 核心集 99 passed（tag_tree 12 + T0-3b 四组 83 + 面板生命周期）；仓库契约 78 passed
- **ruff**：全绿（含 T0-3a 遗留 1 处未使用变量，已修）
- **scripts 门禁**：check_doc_stats 已 `--fix`；其余全部通过（check_package_contents 需 bundle_dir，本地不适用）
- **gen_ts_types --check**：contracts.ts up to date

## 遗留

- 6 个新提交（T0-1/T0-2/T0-3×3/回执）在 master **未推送**，网络恢复后 `git push origin master`
- T0-4（v39 FTS）先前会话已接线（bootstrap 构造 SearchIndexService），未在本轮处理
- T0-5 ShareReceivePage 访客配额渲染（pending）

## 关键教训

`git commit --amend` 永远作用于 HEAD。想将遗留文件并入更早提交时，若中途 HEAD 已变，amend 会并错提交（本轮两次错位）。正确做法：`reset --soft` 到基点 → 全部 unstage → 按文件分组依次 `add + commit`，避免 amend。
