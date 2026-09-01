# 任务包实施调研纪要（2026-08-30，主会话实测）

> 配套 `docs/plans/task-package-2026-08-30.md`。基线：master @ 5fcc174（15 commit 已推送，远程特性分支已删）。

## 环境修正（相对任务包 §2）
- pytest/vitest/git 在本环境全程正常，§2.1/§2.2/§2.3 的沙箱 workaround 不需要（那是另一工具的沙箱问题）。
- §2.6 代理有效：`HTTPS_PROXY=http://127.0.0.1:22348`。已推送 master（183c1d0→5fcc174），远程 `feat/quality-audit-2026-08-17` 已删除（用户此前决定只留主干），本地 master upstream 已指向 origin/master。
- grep 一律 `--exclude-dir=.worktrees`（采纳 §2.4）。

## T4 标签物理分表 — 调研结论
- **存储实况**：标签在每库 SQLite 的 `file_tags` 表（DDL 在 `core/database.py:402` 的基线 schema 里，schema v1 起）；`tag_metadata` 表（v3 迁移）存 color/icon/category；规范名解析走进程级 `TagLibrary`（core/tag_library.py，全局契约，别名各库一致）。链路：TagStore(core/tag_store.py) → TagRepository(repositories/tag_repository.py, for_session + write_scope) → TagService(application/tag_service.py，发布 asset_tags_changed/tag_catalog_changed 事件；撤销走 ed68f7e 的 record_custom)。
- **迁移机制**（v35 实例为模板，db_migrations.py:1066）：幂等步骤函数（PRAGMA table_info 查列 → CREATE TABLE IF NOT EXISTS / ALTER ADD COLUMN → `validate_schema_object(s)` 对 SCHEMA_OBJECT_CONTRACT 校验）→ MIGRATIONS 元组**追加** `Migration(36, "name", fn)`（历史不可变，名字冻结）→ `CURRENT_SCHEMA_VERSION` 35→36（db_migrations.py:47）。新表还需在 `schema_defs.py:697 SCHEMA_OBJECT_CONTRACT` 加条目。**SAVEPOINT 包裹（:1194-1257）不许动**。
- **消费面**：TagService 方法（list/add/remove/rename/delete/get_tags_for_tree 等，tag_service.py:261-347）；LAN routes/tags.py（list/create/remove/rename/delete）；桌面 tag_tree/tag chips/sidebar；webui tags 工厂。
- **设计决定（最小安全版）**：v36 新建 `ai_asset_tags` / `plugin_derived_fields` 两表（形状镜像 file_tags + 独立 tag 索引）+ 契约条目；TagRepository 增加来源→表名映射与 `source` 参数（默认 "human" 走 file_tags，零行为变化）；TagService 透传 source；撤销路径仅 human 生效（source!=human 的写入暂不入撤销栈，防语义混乱）；UI 本轮不做分组展示（无非人类数据，避免空壳 UI），只在 tag_service 层留好缝。测试：迁移幂等（重复跑 v36 不炸、契约校验过）、来源隔离（写 ai 表不出现在 human 查询）、既有 tag 全家桶不回归。

## T1/T2/T3 — 锚点已核验（见会话记录），补充
- T1：webui/src/api/metadata.ts:9 签名加 `includeStatus=1`；结果提示挂 BrowsePage 搜索结果区；PARTIAL/DEGRADED 文案三语。
- T2：`library_watcher_service.py:211` `queue.pop(0)` → `collections.deque` + `popleft()`；确认 `queue` 无其他索引用法。
- T3：上限 500→10_000（取消分页展示，超出即提示；分页是 T7/后续域）；`_is_supported_target` 放开全类别（目录+所有文件，仍拒库外路径）；`repo.list_paths(owner, limit=MAX)` 同步；注意 favorite 相关测试与 LAN favorites 路由。

## T5 撤销栈 — 调研要点
- `undo_service.py`：deque(maxlen=20) 三处（:202,223,261）；纯内存；备份 `tempfile.mkdtemp`（:211）+ 7 天自删（:59,74-80）；`record_custom` 已存在（ed68f7e）。
- 改法：复合 entry type='batch'（持子 entries，undo 逆序回滚，redo 正序重放）；栈深按 entry 数；move/copy/duplicate 接 record_custom（file_operation_service.py:770/818/897）；备份目录迁到 `<library>/.AssetManager/trash/undo-backups/`（库内，随库备份），7 天自删改 90 天 + 启动清理保留；`degraded` 语义必须保留。
- 风险控制：分两个 commit（复合 entry+批量入栈 / 备份迁移+期限），备份迁移要处理旧 temp 备份的一次性收编（存在则搬，失败则留原地不删）。

## T7 结构化检索 — 调研要点
- `asset_index_repository.py`：assets 表有 size/mtime（:510-515），唯一查询 search_by_name（:536-542）LIKE。
- 方案：新增组合查询 `search_structured(name/substring, exts, size_min/max, mtime_after/before, order_by, limit, offset)` 单条 SQL（参数化，防注入；索引现状先 PRAGMA 确认，必要时补 index 迁移**不在本任务**——先 EXPLAIN 确认不退化）；桌面侧栏框升级（复用入口，sidebar.py:735 深度过滤语义保留为"目录树过滤"，新增"全库检索"模式切换）；webui BrowsePage 把 `q` 接上（metaApi.search(q, tags, category) 已有签名）+ 桌面 LAN `/api/search` 透传新参数（metadata.py 三源合并处）。
- 验收：按 mtime 范围筛出文件；Web 搜索框输入有结果；现有搜索不回归。

## 垃圾清单（实施完成后清理）
`.pytest-*`（根目录 18 个 basetemp 残留）、`.ruff_cache/`、`webui/test-results/`、`tmp/`（评审截图证据，评审已交付）、`__pycache__`（随 clean）、RuntimeData 测试残留（用 `scripts/clean_runtime.py --test-runtime`）。**保留**：`docs/reports/`（评审与设计交付文档）、`docs/diagrams/`、`.cw_skill/`、`webui/e2e/_ux_shots.spec.ts`（有用工具，转正与否由用户定，先保留）、`webui/dist`（构建产物）。
