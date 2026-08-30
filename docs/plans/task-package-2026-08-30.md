# AssetManager 整改任务包（交托执行手册）

> 打包日期：2026-08-30
> 基线 commit：本地 `522e0c3` ／ 远程 `5fad2d1`（**本地有 6 个未推送 commit，开工前先确认**）
> 面向：接管执行的智能体。**本文件自包含，无需回看历史对话。**

---

## 0. 开工前必读

### 三条铁律

1. **先跑门禁，再动手；改完再跑一遍门禁。** 门禁红就是没做完。
2. **每个任务单独一个 commit**，按 conventional commit 风格（本项目历史：`fix(scope) 描述` / `chore(scope) 描述` / `test(scope) 描述`）。
3. **不确定就停手问，不要猜。** 这个项目已经有多处"看起来坏了其实没坏、看起来没坏其实坏了"的坑（见 §2.4）。

### 上游文档（本任务包的依据，需要细节时查阅）

| 文档 | 内容 |
|---|---|
| `docs/plans/ux-improvement-plan-2026-08-30.md` | 使用者视角方案：3 个核心判断 + 三梯队 + 12 条"不该做" + 复核记录 |
| `docs/reports/serpent-reference-study-2026-08-30.md` | 同类竞品 Serpent 实现方案拆解 + 对上游方案的两条修正 |
| `artifacts/health-audit-2026-08-28/ux-findings.md` | 第一轮五专家扫描清单（多数已闭环，剩余部分见 §5） |
| `artifacts/health-audit-2026-08-28/overview.md` | 工程治理尽调 |

---

## 1. 项目速览

| 项 | 值 |
|---|---|
| 路径 | `D:\~Vibe-Coding\Projects\AssetsManager_old-bak` |
| 桌面端 | PySide6 (Qt)，`AssetsManager/` 282 个 .py / 约 9.6 万行 |
| 服务端 | aiohttp，140 条路由，SQLite(WAL) + 17 个仓库，schema 迁移 v1→v35 |
| Web 端 | `webui/` React 18 + Vite + TS + Tailwind，224 个 .ts/.tsx，26 页面 |
| 分层 | 有 AST 门禁守护（12 层依赖 DAG），**不是烂架构** |
| i18n | 三语（en/zh/ja），**856 key 完全对齐** |
| 用户 | 主体是创作者/收藏者（本地几千到几万张资产）；次要为局域网访客、卖家、管理员 |

**已知的产品能力**：文件浏览（网格/列表/详情 + 缩略图）、多资产库、图片查看器、标签系统、撤销/重做、24 主题、背景特效、插件系统、系统托盘、多标签工作区、局域网分享、商城（Storefront/Seller/Commerce）。

---

## 2. 环境操作手册（**必读，全部踩过坑**）

### 2.1 跑 Python 测试：必须清掉 safe-delete shim

默认环境下 pytest 会话清理会被沙箱拦截，报 `INTERNALERROR`（不是代码问题）：

```bash
PY="C:/Users/86177/AppData/Local/Programs/Python/Python314/python.exe"
env -u CODEBUDDY_SAFE_DELETE_SANDBOX -u CODEBUDDY_SAFE_DELETE_BIN_DIR \
    -u CODEBUDDY_SAFE_DELETE_BULK_GUARD -u CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR \
    -u CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD -u CODEBUDDY_SAFE_DELETE_REPORT_PATH \
    -u PYTHONPATH -u NODE_OPTIONS \
    $PY -m pytest <路径> -q -p no:cacheprovider --override-ini="addopts=-ra"
```

**若必须覆盖 addopts**（pytest.ini 里有 `--basetemp`）：加 `--override-ini="addopts=-ra"`。

### 2.2 WebUI 测试：本地跑不了，交给 CI

`webui/scripts/run-vitest.mjs` 检测到路径含 `~`（本项目路径 `D:\~Vibe-Coding\...` 正中）会用 `subst` 映射临时盘符，沙箱下 `EPERM` 失败。

**替代验证**：`npm run typecheck` + `npm run build`（约 8 秒，能抓类型与构建错误）。vitest 交给 CI（CI 十三 job 已全绿，改坏会立刻暴露）。

### 2.3 Git：分支指针会莫名丢失（已出现 4 次）

`git commit` 实际成功（对象与 reflog 都在），但 `.git/refs/heads/feat/*` 文件消失，随后 `git log` 报"分支无任何提交"。**`git update-ref` 会静默失败**（无报错但 ref 没建成）。

**提交后的标准收尾动作**：

```bash
git add <文件>
git commit -q -m "..." -m "..."
SHA=$(tail -1 .git/logs/HEAD | awk '{print $2}')
mkdir -p .git/refs/heads/feat
printf "$SHA\n" > .git/refs/heads/feat/quality-audit-2026-08-17
git log --oneline -1        # 验证
```

每次 commit 后都执行，不要偷懒。

### 2.4 排查时排除 `.worktrees/`

`.worktrees/grid-zoom-interpolation-fix/` 是主树的完整副本，grep 统计会被污染翻倍。所有全仓 grep 加 `--exclude-dir=.worktrees`。

### 2.5 门禁：改完全部跑一遍

```bash
PY="C:/Users/86177/AppData/Local/Programs/Python/Python314/python.exe"
$PY -m ruff check AssetsManager tests scripts run.py
for s in check_boundaries check_layers check_style_sources check_route_capabilities \
         check_frontend_data_fetch check_doc_stats check_documents; do
  printf "%-32s " "$s"; timeout 180 $PY "scripts/$s.py" >/dev/null 2>&1 && echo PASS || echo FAIL
done
$PY scripts/gen_ts_types.py --check
$PY scripts/gen_web_tokens.py --check
```

**注意 `check_doc_stats`**：README 顶部有一行 `<!-- stats: ... -->` 统计注释，改动若影响文件/页面/key 数量必须同步更新，否则门禁红。

> 新增 i18n key 时尤其注意：`i18n_en=856 i18n_zh=856 i18n_ja=856`，三处都要改，正文里的表格也要改。

### 2.6 推送：SSL 握手失败先重试

环境有代理（`HTTPS_PROXY=http://127.0.0.1:22348`），失败多为代理抖动。**直接重试，第二次通常成功**，不要改 git 配置。

```bash
timeout 200 git push origin feat/quality-audit-2026-08-17
```

### 2.7 下载外网资源

Python `urllib` 不过代理，**用 `curl`**。SSL 抖动时重试 2-3 次。

---

## 3. 任务清单

> 分四批。**必须按顺序**：**阶段 0 是止血**（数据正确性 + 兑现已投入），优先于一切；
> P0 是小而确定的；P1 需要设计决策；P2 是大工程。
> 每个任务给出：目标 / 证据 / 改法 / 验收 / 风险。

---

### 🚨 阶段 0：止血（2026-08-30 新增，优先于 T1–T10）

> 来源：发展规划 `docs/plans/development-roadmap-2026-08-30.md`（四专家团产出）。
> 前两项是**数据正确性 bug**，比任何新功能都紧急。

#### T0-1 · 修派生物失效（真 bug：持续产出错误数据）

- **证据**：`AssetsManager/application/media/derivatives.py:236,240` 写入 `source_mtime`，但**全仓无任何比较点**。
  对照组（做对了）：`AssetsManager/application/project_service.py:759-762` 有完整 mtime 比对。
- **后果**：`AssetsManager/application/media/analysis.py:383` 只判断"行存在"（`:371-376` 注释自述 "factory runs only when the row is still missing"），`ON CONFLICT` 只更新 `created_at`。
  **源文件改了，音频波形和主色永远喂旧的，且静默。**
- **改法**：读取时比对 `source_mtime` 与当前 `os.path.getmtime()`，不等则重建（照抄 `project_service.py:759-762` 的模式）
- **验收**：修改一个已生成波形的音频文件，重新打开后波形重建
- **风险**：低

#### T0-2 · 修派生物与合集的路径迁移缺口

- **证据**：
  - `AssetsManager/core/database.py:1336-1486` `_migrate_path_metadata_impl` 重映射 file_tags / file_meta / library_favorites / thumbnail_cache，**不含 `asset_derivatives`**
  - `AssetsManager/core/schema_defs.py:526-532` `asset_collection_members.file_path` 是**裸 TEXT 无外键**
  - `AssetsManager/application/media/derivatives.py:256` `clear()` **0 调用者**
- **后果**：文件改名后，派生物旧行 + 旧 payload 双孤儿；合集**静默丢成员**
- **改法**：把 `asset_derivatives` 与 `asset_collection_members` 纳入路径重映射；给 `clear()` 接一个调用点（删除/改名时清理）
- **验收**：改名后派生物与合集成员都不丢
- **风险**：中（涉及迁移逻辑）

#### T0-3 · 接通 rating 与 ai_asset_tags（兑现已投入）

- **证据**：
  - `AssetsManager/application/tag_service.py:474-476` `get_all_tags(..., source: TagSource = "human")` 默认 human
  - `AssetsManager/controllers/tag_tree_controller.py:37-39` 调用**不传 source** → v36 建的 `ai_asset_tags` / `plugin_derived_fields` 是**两张空表**
  - `file_meta.rating`（v37）schema 定义 3 处，**业务消费 0 处**
- **改法**：① `tag_tree_controller` 的 tag 查询增加 source 参数并透传；② 信息面板加评星 UI，写入 rating
- **验收**：AI 标签可被写入并展示；评分可设置并用于排序/筛选
- **风险**：低。**成本最低的兑现动作**——schema 与迁移已完成，只差接线

#### T0-4 · v39 FTS 索引：接线或删表（定时炸弹）

- **证据**：`SearchIndexService`（`AssetsManager/application/search_index_service.py:54`）**全仓 0 处构造**；
  3 个注入点（`asset_index_service.py:177` / `metadata_service.py:51` / `tag_service.py:90`）默认 None
- **后果**：v39 FTS 只在迁移时种子一次、永不维护、永不查询。
  **留着不维护的索引比没有更危险**——一旦接查询就静默返回过期结果
- **改法**：二选一——接入维护与查询，或删除该表与索引
- **风险**：低（删表）/ 中（接线）

#### T0-5 · ShareReceivePage 访客链路（后端已就绪，纯前端）

- **证据**：后端 `AssetsManager/domain/share.py:81-88` 已返回 `download_count` / `max_downloads` / `expires_in_hours`；
  TS 类型 `webui/src/types/api.ts:361-363` 也有；但 `webui/src/pages/ShareReceivePage.tsx` **零渲染**
- **改法**：渲染剩余次数与到期倒计时 + 配额耗尽态；4 处 `h-screen`（`:73,81,89,97`）改 `min-h-[100dvh]`（移动端地址栏会裁切）
- **验收**：访客能看到还剩几次、何时过期
- **风险**：低。**后端、类型、i18n 三语全部到位，纯前端活**

---

### P0：小改动，立即可做

> ⚠️ **注意**：T1–T8 用户已在 2026-08-30 前自行完成（见 §4）。
> 保留条目仅供对照与验收，**不要重复做**。

---

#### T1 · 搜索截断必须可见

- **目标**：止住用户"我这张图不在库里"的错误结论
- **证据**：`AssetsManager/application/search_service.py:58-63`（limit 20/上限 100、512 目录、1 万条目、1000 匹配、75ms 四道截断）；`lan/routes/metadata.py:127,168-189`（`include_status` 参数已实现，只在 `include_status=1` 时下发 status/sources/dropped_count/fallback_used）
- **改法**：前端 `webui/src/api/metadata.ts:9` 的签名加上 `include_status` 参数并默认传 1；结果区在 `status` 为 PARTIAL/DEGRADED 时显示一行提示"仅扫描前 N 个目录，结果可能不全"
- **验收**：`npm run typecheck` + `npm run build` 通过；人为构造超过 512 目录的查询能看见提示
- **风险**：低

---

#### T2 · watcher 出队改 `deque.popleft()`

- **证据**：`AssetsManager/application/library_watcher_service.py:211` `path, _depth = queue.pop(0)`；`:49` `MAX_DIRECTORIES = 50_000`
- **改法**：队列类型改为 `collections.deque`，`pop(0)` → `popleft()`。**一行**
- **验收**：`ruff` 通过；相关测试通过
- **风险**：极低

---

#### T3 · 收藏上限与类型放开

- **证据**：`AssetsManager/application/favorite_service.py:16` `MAX_FAVORITES_PER_OWNER = 500`，超限 `:165-170` 抛 `ValidationError`（**静默失败**）；`_is_supported_target`（`:106-109`）只放行目录 + `IMAGE_EXTS`，视频/模型/压缩包一律不能收藏。桌面端无此限制（`dialogs/sidebar_favorites.py`），两端行为不一致
- **改法**：上限取消或大幅提高 + 分页展示；类型放开到全类别
- **验收**：`ruff` + favorite 相关测试
- **风险**：低。注意 LAN 端列表接口 `repo.list_paths(owner, limit=MAX_FAVORITES_PER_OWNER)`（`:133`）要同步

---

#### T4 · 标签物理分表（**最小起步，推荐第一个做**）

- **目标**：为将来接入 AI / 插件标签预留隔离，防止 AI 标签污染用户人工组织
- **依据**：竞品 Serpent 把 `human_asset_tags` / `ai_asset_tags` / `plugin_derived_fields` 分成三张独立表，各自独立索引
- **为何现在做**：当前标签系统只有人工标签，**这是做分表成本最低的窗口**；一旦混入 AI 标签再拆就伤筋动骨
- **证据**：`AssetsManager/application/tag_service.py`（通篇无 parent/alias）、`AssetsManager/panels/tag_tree.py`（扁平两层，`:169` `_populate()` 全量重建）、`AssetsManager/controllers/tag_tree_controller.py`
- **改法**：
  1. 新建 `ai_asset_tags` / `plugin_derived_fields` 表（迁移版本 v36）
  2. 现有 tags 表语义收敛为"人工标签"
  3. `tag_service` 的查询接口增加 tag source 参数
  4. UI 层标签树按来源分组展示
- **验收**：`ruff`；`test_tag_service_adapter` / `test_tag_tree_controller` 通过；**撤销栈功能不受影响**（见 T5 的依赖说明）
- **风险**：中。涉及 schema 迁移，**务必先读 `§2.5` 的 db_migrations 保护说明**

> ⚠️ **不要动 `core/db_migrations.py` 的 SAVEPOINT 包裹结构**（`:1194-1257`），那是全项目最扎实的一段。只新增迁移步骤。

---

### P1：中成本，需要设计决策

---

#### T5 · 撤销栈：批量复合 entry + 备份持久化

> **依赖**：若先做 T4，需确认标签撤销（刚在 `ed68f7e` 补上）在分表后仍工作。

- **目标**：补上"安全网"最大的两个洞
- **证据**：
  - 栈深硬顶 20：`AssetsManager/application/undo_service.py:202,223,261`（`deque(maxlen=20)`）；`:712`
  - 批量删除逐文件入栈：`AssetsManager/panels/file_list/_actions.py:499-502`（`commit_delete(entry)` 循环）
  - 重启即空：`:221-224` 纯内存 deque
  - 备份 7 天自删：`:59` `_STALE_AFTER_SECONDS = 7*24*60*60`；`:74-80` `_run_startup_cleanup`；备份落系统 temp `:211` `tempfile.mkdtemp`
  - `move_to_directory`/`copy_to_directory`/`duplicate` 不入栈：`file_operation_service.py:770/818/897`
- **改法**：
  1. 引入复合 entry（`type=batch`，持子 entry 列表），一次 Ctrl+Z 回滚整批；栈深按 **entry 数**而非操作数计
  2. `move`/`copy`/`duplicate` 接 `record_custom`（该方法已在 `ed68f7e` 中加入）
  3. 备份目录移入**库内回收站**，取消或大幅延长 7 天自删
- **验收**：删 50 个文件后一次 Ctrl+Z 全部恢复；重启后（若不持久化则至少给出明确提示）
- **风险**：中。撤销涉及文件系统真实改动，务必保留 `degraded` 标记语义（`:degraded` 字段）

---

#### T6 · 活动日志：把桌面操作写进已有的 activity_log

- **证据**：表与 API 都在（`schema_defs.py:108-117`；`lan/routes/users.py:122`），但只写 LAN 登录/下载/分享（`auth.py:24`、`downloads.py:284`、`shares.py:152`），**桌面文件操作零写入**
- **改法**：重命名/移动/删除/批量打标/导入逐条落库；做「活动」面板（按天分组、可跳转路径、删除类可一键还原）
- **验收**：桌面执行一个删除后，activity_log 出现对应记录
- **风险**：中。注意不要阻塞主线程（写入走后台线程）

---

#### T7 · 全库结构化检索

- **证据**：
  - `AssetsManager/repositories/asset_index_repository.py:536-542` 唯一查询只 `name LIKE`；`size`/`mtime` 两列（`:510-515`）**从未进任何 WHERE/ORDER BY**
  - 桌面过滤管线只有 hidden/exclude/类型/深度/子串/类别六项（`AssetsManager/application/asset_filters.py:344-376`），**无时间无大小**
  - 侧栏搜索是目录树过滤，深度硬顶 5 层（`AssetsManager/panels/sidebar.py:735-737`）
  - Web 端 `webui/src/api/metadata.ts:9` 的 `search(q, tags, category)` 在 `BrowsePage.tsx:156` 只传 tag，`q` 恒空 → **后端三源搜索（`lan/routes/metadata.py:138-157`，158 行）从未被触发**
- **改法**：`AssetIndexRepository` 加组合 search（name/tags/ext/size_min-max/mtime_after-before/order_by/limit/offset）单条 SQL；桌面把侧栏那个框**升级**成全库检索（**复用入口，不要新增第三个搜索入口**）；Web 把 `q` 接上
- **验收**：能按修改时间范围筛出文件；Web 端搜索框输入有结果
- **风险**：中。**先确认索引存在**，否则全表扫描会更慢

---

#### T8 · 自动化三件套（幂等 + 执行日志 + 执行前审批）

- **依据**：Serpent 的 `automation-idempotency-store` / `automation-execution-journal` / `automation-file-plan-approval` / `automation-readonly-command-executor`
- **目标**：让批处理可信。直接补上安全网的第四、五个洞——**批量操作没有执行前确认、中断后重跑会重复**
- **证据（本项目现状）**：批量打标签（`522e0c3` 刚做）、批量 ZIP、批量导入均**直接执行**，无幂等无审批无日志
- **改法**：先做最小版——批量文件操作生成**执行计划**（路径清单 + 动作），用户确认后才执行；计划 id 入幂等存储，重复提交不产生副作用；执行结果入日志
- **验收**：批量操作前出现计划预览；重复提交同一计划不重复执行
- **风险**：中。改动面较大，建议先挑**批量删除**一个场景做通

---

### P2：大工程，最后做

---

#### T9 · 大目录响应优化

- **证据**：`AssetsManager/application/asset_service.py:34` `scan_summaries` 默认 True；`:106,110` 对每个子目录调 `_scan_dir_summary`；`:344-357` 缓存以 mtime 为键，`:351` mtime 变即 miss
- **体验**：N 子目录 = N 次全扫。2000 子目录约 2 万次条目访问，SSD 1-3s，NAS 可达 20-100s；同步盘碰过任一子目录该项立刻失效
- **改法**：计数改异步 + 占位（先出名字，数字后到）
- **注意**：Web 端已实现 list cheap + hydrate on demand（`useProjects.ts:42` 传 `summaries: false`、`BrowsePage.tsx:216` 按 48 分批、`ProjectGrid.tsx:28` IntersectionObserver）——**不要重复做，也不要误以为没做**
- **风险**：中

---

#### T10 · 只读连接池（**只做读路径**）

- **证据**：`AssetsManager/core/database.py:916-921` 每库只建一个 sqlite3 连接（WAL 在 `:399` 已开）；`:1225,1228` db_write_lock；`:1266-1302` `locked_read`；61 处 `@locked_read` + 约 90 处 `db_write_lock`
- **体验**：WAL 的多读并发等于没开——A 打开 2000 子目录的文件夹，B 的翻页/缩略图/搜索一起等
- **改法**：读走独立只读连接池（每线程一连接），只写走锁；`locked_read` 降级为兼容垫片
- **风险**：**高**。**写路径保持现状**，只动读。改出来的回归会比现在的卡顿严重得多

---

## 4. 已完成事项（**不要重复做**）

| 项 | commit |
|---|---|
| 缩略图批量请求分片 50/批（>100 张目录全灭） | `84a2872` |
| 24 主题 muted/border 对比度全部达 WCAG | `fc47beb` |
| Inter 字体自托管（移除 Google Fonts CDN） | `41cd215` |
| 删除自定义主题加确认 + 回收站 | `922c931` |
| 崩溃对用户可见（crash.pending + 启动提示） | `072f7b9` |
| 测试会话清理加 30s 预算 | `40e3c66` |
| clean_runtime 新增 --test-runtime | `8414181` |
| 依赖加语义上限 | `50e7896` |
| 标签删除入撤销栈 | `ed68f7e` |
| i18n 统计同步 852→856 | `5fad2d1` |
| pytest basetemp / .gitattributes / 僵尸配置清理 / 文档勘误 / pre-commit | 更早 |

用户在 `5fad2d1` 之后又自行完成 6 个 commit（批量打标签、卖家配额卡片、claim 失败分支、a11y 门禁扩面、表单行内校验、Gate 入口合并），**均未推送**。

---

## 5. 明确不做的事（**违反即回退**）

1. **别做多端同步/云同步** —— 自建同步引擎等于重做 Dropbox。
   > 已修正：若将来要做，**走 WebDAV 复用现成协议**（NAS/Nextcloud），不要自建服务端。见 Serpent 研究报告 §3.1。

2. **别做 AI 自动打标/以图搜图（自建路线）** —— 库里没有向量索引或模型运行时。
   > 已修正：可以接**外部 API**（Anthropic/通义/Gemini）+ **标签物理分表**，或先做 **MCP 暴露**让外部 Agent 调用。前置条件仍是**先补齐结构化检索（T7）**。见 Serpent 研究报告 §3.2。

3. **别现在重构 Storefront 第二套设计系统** —— 商城链路正在高频变更，此刻动样式必然撞车。等链路稳定后目标是"收敛到 token"而非重写。

4. **别给集合/智能文件夹加副本语义** —— 创作者最怕工具动他的文件组织。集合必须是查询视图。

5. **别在桌面端新增第三个搜索入口** —— 已有侧栏过滤框 + 标签树面板 + 标签浏览器对话框。正确做法是升级侧栏那个框（T7）。

6. **别把"加分页/虚拟滚动"单独立项** —— 它们是 T9 的实现手段，单独立项会做出"Web 端有分页、桌面端和 API 仍然全量"的半截方案。

7. **别动 `core/db_migrations.py` 的 SAVEPOINT 包裹**（`:1194-1257`）—— 全项目最扎实的一段。

8. **别重写 `JsonStore`** —— 已是 tempfile + fsync + os.replace 原子写，还带坏文件隔离。

9. **别动 `LibraryLock`** —— 唯一挡住"两实例同写一个库"的东西，风险收益比极差。

10. **别给 thumbnail 的 8192 key 缓存做 LRU** —— 现在 FIFO 足够，key 只是短字符串。

11. **别为 shop/commerce 链路做性能投入** —— 主用户是创作者，这条链路是沉没成本。

12. **别重做已修复项**（§4 表格）。

---

## 6. 参考资源

### 竞品副本（可自由阅读，勿提交进本仓库）

```
D:\~Vibe-Coding\Projects\_REF_Serpent
```

完整克隆（93 MB / 1268 commits / 4 分支），node_modules 未安装。

**建议重点阅读**：

| 文件 | 学什么 |
|---|---|
| `src/worker/library-service.ts` | 表设计（**该文件 43,822 行，是反面教材，只看 schema 部分**） |
| `src/worker/ai/` | 多供应商适配器（anthropic / dashscope / gemini） |
| `src/main/automation-*` | 幂等 + 执行日志 + 计划审批 + 只读沙箱 |
| `src/worker/eagle-library.ts` | 竞品库迁移 |
| `src/worker/zip-import-stream.ts` | 流式 ZIP 导入 |
| `src/main/ai-queue-scheduler.ts` | AI 请求队列调度 |

`library-performance` 分支相对 main 独有提交数为 0，工作已合并回主干。

### 关键数据点（复用时无需重新扫描）

- 本项目 Web 端：26 页面中 **16 个是商城**（62%）；服务端 140 路由，`/api/shop/*` 引用 59 处
- 桌面端：主菜单 15 项 + 侧栏 15 项 = 30 个入口（规模合理）
- Serpent：667 文件 / 10.9 万行 TS / Electron / 1.5 个月 / 257 star / 零电商

---

## 7. 执行顺序建议

```
T4 标签物理分表        ← 推荐先做，时机窗口，纯加法
 ↓
T1 搜索截断可见  T2 popleft  T3 收藏放开     ← 三个小改动，可并行
 ↓
T5 撤销栈复合 entry    ← 依赖 T4 的撤销兼容性确认
 ↓
T7 全库结构化检索      ← 解锁后续 AI 可能性
 ↓
T6 活动日志  T8 自动化三件套
 ↓
T9 大目录优化  →  T10 只读连接池（最高风险，最后做）
```

**每日收尾**：跑 §2.5 全部门禁 → 每个任务单独 commit → §2.3 恢复 ref → 最后统一 push（§2.6）。

---

## 8. 执行状态（2026-08-30，主会话实施回执）

**已实施（commits 均在 master，已推送）**：

| 任务 | Commit(s) | 备注 |
|---|---|---|
| T1 搜索截断可见 | `adef752` | include_status 接入 + PARTIAL/DEGRADED 提示三语 |
| T2 watcher popleft | `cca686c` | 附 FIFO 顺序回归测试 |
| T3 收藏放开 | `f367af9` | 500→10000 + 全类别；仓库层镜像常量（架构门禁禁反向 import） |
| T4 标签物理分表 | `11c4051` | 迁移 v36（ai/plugin 两表 + source 参数）；幂等与三源隔离有测试 |
| T5 撤销栈 | `00cac55` `0503c91` | batch 复合 entry（删 50 一次恢复）；备份迁 data_dir/undo_backups、90 天（temp legacy 7 天）；**回归修复 `53e4a65`**：库备份排除 undo_backups 子树（T5b 曾把已删文件副本打进 .assetbackup） |
| T6 活动日志 | `7d0e3e4` | 桌面文件/批量打标/导入写 activity_log（批量一行、记录失败不影响操作）；Web AdminPage 面板零改动兼容 |
| T7 结构化检索 | `e42e9bf` `64e1fe8` `aa01918` | 仓储组合查询 + LAN indexed-only + 桌面高级过滤弹层 + Web q 通路；EXPLAIN 确认走索引未加新索引 |
| T0-1 派生物 mtime | `85e9cf2` | 派生物 mtime 失效真 bug：源文件变更后重建波形/调色板（**未推送**） |
| T0-2 路径迁移缺口 | `cb03617` | 派生物/合集成员纳入路径重映射 + clear() 接调用点，改名不再丢派生物与合集成员（**未推送**） |
| T0-3 rating + ai 标签 | `b547c0a` `e141ae5` `6afe91b` | T0-3a 三源标签聚合（tag 树接通 ai/plugin 分表，非 human 只读）；T0-3b rating 读写链路（事件+仓库+服务+`PUT /api/rating`+迁移补列）；T0-3c 信息面板 5 星 UI（点击写入/重击清除，跨会话刷新）（**未推送**） |

**T0 止血系列进度**：T0-1 / T0-2 / T0-3 已实施并通过测试（T0-3 相关 99 passed），提交在 master 未推送；T0-4（v39 FTS 接线或删表）与 T0-5（ShareReceivePage 访客链路）未开始。

**缓办（证据驱动，非搁置）**：
- **T9**：前提已过时——桌面 file_list 不消费 `asset_service.list`（自带 scandir + 本地过滤）；Web 主列表传 `summaries:false`（useProjects.ts:42），昂贵路径只剩有界按需 hydrate（`files.py:145`）。消费者审计详见 `outputs/task-package-research-2026-08-30.md`。
- **T10**：任务包自评最高风险；且 `docs/perf-baseline-2026-08-29.md` D3 实测网格帧成本与 DB 并发度无关，收益预期需重估。建议单独立项 + 真机 NAS 场景验证后再做。
- **T8**：前提部分满足——批量删除已有确认弹窗（清单+计数），T6 落了执行日志；剩余缺口的幂等存储建议独立设计（当前无脚本化重放场景）。

**环境修正**：§2.1/§2.2/§2.3 的 workaround 属另一工具沙箱，本环境 pytest/vitest/git 全程正常；§2.6 代理有效并已推送。`tmp/` 内 57 个 `pytest-codex*/g6-6*/r1*` 子目录受删除保护沙箱托管（icacls 亦拒绝），未强攻，约 40KB。
