# AssetManager 使用者视角：功能与架构优化方案

> 产出日期：2026-08-30（扫描于 08-29 夜间至 08-30 凌晨）
> 性质：**方案，未实施**。全文基于只读代码扫描（UI/UX 设计师 + 架构师双线并行 + team-lead 独立复核）
> 基线 commit：`522e0c3`（本地）／`5fad2d1`（远程）
>
> 姊妹文档：`artifacts/health-audit-2026-08-28/ux-findings.md`（第一轮整改清单，多数已闭环）
> 扫描时请排除 `.worktrees/`（主树完整副本，会污染 grep 计数）

---

## 零、三个核心判断

### 判断一：功能重心偏离了主用户

| | 功能分布 | 判断 |
|---|---|---|
| **桌面端**（主界面，创作者每天用） | 主菜单 15 项 + 侧栏 15 项 = **30 个入口** | 克制、合理 |
| **Web 端**（局域网访客用） | 26 个页面中 **16 个是商城**（Storefront 11 + Seller 5 + Legacy 2）= **62%** | 严重偏科 |
| **服务端** | 140 条路由，`/api/shop/*` 引用 59 处 | 同上 |

这是通过"两套界面的功能分布对比"得出的，单看任一端都发现不了。一个**个人资产库管理工具**把六成 Web 页面投在电商链路上，而主用户（创作者/收藏者）每天面对的桌面端反而功能克制。

顺带澄清两条容易误判的：
- `LegacyStorefront{Item,Gallery}Page` **不是死代码** —— `App.tsx:178,181` 有真实路由（`/store/gallery/:tag`、`/store/*`）
- `theme_preview_dialog.py` **已接线**（`settings_dialog.py:433`），内置主题能否预览是另一回事（受 `is_custom` 限制）

### 判断二：用户以为有一张安全网，其实那张网有三个洞

创作者最怕"资产丢了"。这个项目给了撤销/重做，但安全网的实际强度与用户预期严重不符：

| 用户以为 | 实际 |
|---|---|
| Ctrl+Z 能撤回我刚做的操作 | 栈深硬顶 **20**（`undo_service.py:202,223,261`），批量删除逐文件入栈（`_actions.py:499-502`）→ 删 50 张只有最后 20 张能撤，且一次只恢复 1 张 |
| 我明天回来还能撤 | **重启即空**：纯内存 deque（`:221-224`），无持久化 |
| 我上个月删的应该还在备份里 | 备份落**系统 temp**（`:211` `tempfile.mkdtemp`），**7 天后被自己的启动清理删掉**（`:59 _STALE_AFTER_SECONDS = 7*24*60*60` + `:74-80` `_run_startup_cleanup`） |

第三条最扎心：用户两个月前误删的文件，以为 Ctrl+Z 还救得回来，其实备份早被软件删了，且全程零提示。

### 判断三：「生产了但没人消费」已经出现 **11 次**

这是贯穿两轮审计的结构性模式。前 5 次已修或已澄清，本轮新增 6 次：

| # | 基建（造出来了） | 执行（没人接） |
|---|---|---|
| 1-5 | 门禁脚本 / crash.log / MaintenanceChanged / recoveryFailed / summaries | 前 4 条已修，第 5 条经核实是误报（Web 端其实用了） |
| **6** | `SearchResultSet` 全套诊断（status/sources/dropped_count/fallback_used，`search_service.py:99-230`）+ `include_status` 参数（`lan/routes/metadata.py:127,168-189`） | 前端 `metadata.ts:9` 的签名里**根本没有这个参数**，零消费者 |
| **7** | `assets` 表的 `size`/`mtime` 两列（`asset_index_repository.py:510-515`） | 唯一查询 `search_by_name`（`:536-542`）只 LIKE name，这两列**从未出现在任何 WHERE/ORDER BY** |
| **8** | 后端三源搜索（scanner → indexed → merge，158 行代码，`lan/routes/metadata.py:138-157`） | Web 端从未触发：`BrowsePage.tsx:156` 恒传空 `q` 空 `category` |
| **9** | `activity_log` 表 + `recent()`（`schema_defs.py:108-117`；`lan/routes/users.py:122`） | 只写 LAN 登录/下载/分享（`auth.py:24`、`downloads.py:284`、`shares.py:152`），**桌面文件操作零写入** |
| **10** | `PerformanceRecorder`：生产埋点 **108 处** | `recent()` 生产调用 **0 处**；开关 `performance_telemetry_enabled`（`app.py:110`）也仅此一处读取、无 UI 写入方 → 默认关闭，**埋点全白写** |
| **11** | `library_watcher_interval_seconds`（`settings.py:24`，默认 120.0） | **0 处 UI 写入** → 用户拷了 200 张图进库，最长等 2 分钟才可见，界面零提示，也找不到设置项 |

---

## 一、第一梯队：补上安全网的三个洞（最高 ROI）

### 1.1 撤销栈：批量复合 entry + 持久化

**痛点**（`undo_service.py:202` / `_actions.py:499-502`）：删 50 张只有最后 20 张能撤，一次恢复 1 张；重启即空。

**方案**：
- 引入复合 entry（type=`batch`，持子 entry 列表），一次 Ctrl+Z 回滚整批；栈深按 **entry 数**而非操作数计
- `move_to_directory` / `copy_to_directory` / `duplicate` 接 `record_custom`（`file_operation_service.py:770/818/897`，目前完全不入栈）
- 备份目录移入**库内回收站**而非系统 temp，取消 7 天自删（或延长到 90 天 + 到期前提示）

**用户收益**：批量操作敢用了。这比加任何新功能都更能提升使用意愿。
**成本**：中

### 1.2 活动日志：把桌面操作写进已有的 activity_log

**痛点**：表和数据读取 API 都在，只写 LAN 安全事件，桌面文件操作零写入。用户"不知道什么时候误删的"。

**方案**：把重命名/移动/删除/批量打标/导入逐条落库，做「活动」面板：按天分组、可跳转到路径、删除类可一键还原。

**用户收益**：创作者最怕的不是误删，是"不知道什么时候误删的"。有回溯才有安全感。
**成本**：中

---

## 二、第二梯队：找得到（检索能力是最大空白）

### 2.1 全库结构化检索（唯一能同时救桌面和 Web 的改动）

**痛点**：
- 唯一查询谓词是 `name LIKE`（`asset_index_repository.py:536-542`），`size`/`mtime` 从不进 WHERE/ORDER BY
- 桌面过滤管线只有 hidden/exclude/类型/深度/子串/类别六项（`asset_filters.py:344-376`），**无时间无大小**
- 侧栏搜索是"目录树过滤"，深度硬顶 5 层（`sidebar.py:735-737`）
- Web 端 `metaApi.search(q, tags, category)` 在 `BrowsePage.tsx:156` 只传 tag，`q` 恒空

**方案**：`AssetIndexRepository` 加组合 search（name/tags/ext/size_min-max/mtime_after-before/order_by/limit/offset）单条 SQL；桌面把侧栏那个框**升级**成全库检索（复用入口，不开新窗口）；Web 把 `q` 接上。

**用户收益**：从"我记得大概什么时候"→ 三秒定位，且不必先想好标签。
**成本**：中

### 2.2 跨库检索

**痛点**：`SearchService` 绑定单个 LibrarySession，library_root 不匹配直接 raise（`search_service.py:673-677`）。多库是主打特性，但检索被切成 N 个孤岛。

**方案**：加 `SearchCoordinator`，对每个已打开库并行跑同一 query（各库自有 session/连接，天然不争锁），结果按库分组。
**成本**：中

### 2.3 搜索截断必须可见

**痛点**：quicksearch 有 512 目录 / 1 万条目 / 1000 匹配 / 75ms 四道截断（`search_service.py:58-63`），返回体**无 truncated 标志**。用户搜一个常见词"看起来就这些"，直接得出"我这张图不在库里"的错误结论。

**方案**：前端默认传 `include_status=1`（后端已支持），`PARTIAL/DEGRADED` 时在列表下方显示一行"仅扫描前 N 个目录，结果可能不全"。
**成本**：小 —— **这条很便宜但伤害"找得到"，建议优先做**

---

## 三、第三梯队：并发与响应

| 问题 | 证据 | 用户感知 | 建议 | 成本 |
|---|---|---|---|---|
| 单库单连接 + 全库串行锁，WAL 多读并发等于没开 | `database.py:916-921` 单连接；`:1225,1228` 读写门；`:1266-1302` `locked_read`；61 处 `@locked_read` + 约 90 处 `db_write_lock` | A 打开 2000 子目录的文件夹（冷缓存数秒），B 的翻页/缩略图/搜索一起等 | 读走独立只读连接池，只写走锁 | 大 |
| 冷缓存打开大目录 = 每个子目录一次全量 scandir | `asset_service.py:34` 默认 True；`:106,110` 每子目录 `_scan_dir_summary`；`:344-357` mtime 键，`:351` mtime 变即 miss | N 子目录 = N 次全扫。2000 子目录 ≈ 2 万次条目访问，SSD 1-3s，NAS 可达 20-100s。同步盘碰过任一子目录，该项立刻失效 | 计数改异步 + 占位（先出名字，数字后到） | 中 |
| Web 端列表无分页 | `_project_files` 逐文件 stat（`project_service.py:1004`）且无 limit（`:993-1018`） | 手机上打开 3000 文件的目录等十几秒 | 首屏 N 条 + 总数，滚动续取；size/mtime 直接读 assets 索引 | 中 |
| image/thumbnail 零 ETag 零 Cache-Control | 全 `lan/` grep ETag 命中 **0**；`image.py`/`thumbnails.py` 无缓存头（对比 `favorites.py:91`、`gallery.py:59` 都设了 no-store） | 每次回滚重拉全部缩略图字节 | 用 thumbnail cache key + mtime 做 ETag，304 短路 | 小（advisory） |
| watcher 用 `list.pop(0)` 出队，O(n²) | `library_watcher_service.py:211`；`:49` MAX_DIRECTORIES=50_000 | 5000 目录可忽略；50000 目录单轮额外数秒 | 换 `deque.popleft()`，**一行** | 小 |

---

## 四、其他值得做的（小成本）

| 项 | 证据 | 建议 |
|---|---|---|
| 收藏上限 500 且只支持图片 | `favorite_service.py:16` MAX=500，超限 `:165-170` 抛错；`_is_supported_target`（`:106-109`）只放行目录 + IMAGE_EXTS | 几万张图的用户第一周就用完 500 个，且是静默失败；桌面端无此限制（`sidebar_favorites.py`），两端行为不一致。放开上限与类型 |
| 命名集合（智能文件夹） | 组织手段只有标签，扁平无层级无别名（`tag_service.py` 通篇无 parent/alias；`tag_metadata` 只有 color/icon/category） | 把 §2.1 的筛选条件序列化成命名集合存 `saved_views`，侧栏与 Web 共用。**集合必须是查询视图，不能物理移动文件** |
| 批量元数据编辑（可选） | 元数据只有单文件 notes/urls（`metadata_service.py:231/245`），无批量 | 标注为**可选**——这是推断，非代码证据读出的痛点 |

---

## 五、明确不该做的事

这一节和前面同等重要。这个项目的问题**不是功能太少，而是功能太多没闭环**。

1. **别做多端同步/云同步。** 本地资产库，几千到几万张大文件，做同步等于重做 Dropbox。用户真需求是"局域网随时能看"，已解决；该补的是 Share 链接的失效与恢复（正在做）。
2. **别做 AI 自动打标 / 以图搜图。** 库里没有任何向量或特征索引，也没有模型运行时；而连"按修改时间筛选"都还没有。**先让结构化筛选扎实，AI 打标的价值才接得住**——否则只是给一个没人用的面板。
3. **别现在重构 Storefront 第二套设计系统。** 商业链路正在高频变更（最近 6 个 commit 全在这），此刻动样式必然与变更流撞车。等链路稳定后再做，且目标是"收敛到 token"不是"重写"。
4. **别给集合/智能文件夹加副本语义**（物理移动或复制文件到集合目录）。创作者最怕工具动他的文件组织。
5. **别在桌面端新增第三个搜索入口。** 已有侧栏过滤框 + 标签树面板 + 标签浏览器对话框，三套入口够多了。正确做法是把侧栏那个框升级成全库检索。
6. **别把"加分页/虚拟滚动"单独立项。** 它们是 §3 的实现手段，不是独立需求；单独立项会做出"Web 端有分页、桌面端和 API 仍然全量"的半截方案。
7. **别动 `db_migrations`。** v1→v35 用 SAVEPOINT 整体包裹（`:1194-1257`），失败整体回滚，跨进程 1 次重试（`:1270-1284`）。全项目最扎实的一段。
8. **别重写 `JsonStore`。** 已是 tempfile + fsync + os.replace 原子写，还带坏文件隔离（`:119-141`、`:85-103`）。够了。
9. **别动 `LibraryLock`。** PID 存活探测 + 陈旧锁恢复都在（`:25-55`、`:155-180`）。它是唯一挡住"两实例同写一个库"的东西，风险收益比极差。
10. **别全量重写连接生命周期。** 只做"读连接独立"，写路径保持现状。改出来的回归会比现在的卡顿严重得多。
11. **别给 thumbnail 的 8192 key 缓存做 LRU。** 现在是 FIFO（`thumbnail_service.py:170-172`），key 只是短字符串，命中率差异不值。
12. **别为 shop/commerce 链路做性能投入。** 用户是创作者/收藏者，这条电商链路是沉没成本。

---

## 六、复核记录（team-lead 独立验证）

抽查 9 项，**8 项属实、1 项误报**。

**属实：**
- 撤销栈深 20 / 批量逐文件入栈 —— `undo_service.py:202,223,261,712` + `_actions.py:499-502`
- 撤销备份 7 天自删 / 落系统 temp —— `:59 _STALE_AFTER_SECONDS`、`:74-80`、`:211`
- `size`/`mtime` 从未进 WHERE/ORDER BY —— grep 为空
- 收藏上限 500 + 只支持图片 —— `favorite_service.py:16,106-109`
- `activity_log` 只写 LAN 事件 —— 仅 `auth.py:24`、`downloads.py:284`
- `PerformanceRecorder` 埋点 108 处 / `recent()` 生产调用 0 处
- `library_watcher_interval_seconds` 0 处 UI 写入
- watcher `pop(0)` + MAX_DIRECTORIES=50_000 —— `library_watcher_service.py:211,49`

**误报（已拦下）：**
> 设计师报"sidebar.py:87 用 `\U0001f50d` emoji 作搜索图标，属 emoji 违规"

实为误判。该行属于 `_FAVORITE_ICON_MAP`（`sidebar.py:71-97`），是一张 **emoji → 语义图标名的翻译表**：
```python
:300   return _FAVORITE_ICON_MAP.get(legacy, icons.normalize(legacy, fallback="star"))
:308   item.setIcon(0, icons.icon(normalized, color=tint, size=scaled_px(18)))
```
早期版本允许用户用 emoji 给收藏项命名（"⭐ 我的素材"），这段代码把 emoji **翻译**成 `core/icons.py` 的语义图标并渲染成 SVG。方向是 emoji → 图标，**是解药不是病**。

**主动排除（避免误报，两位专家自行划掉）：**
- refresh warnings 有消费者（`_actions.py:75-97`）
- reconciliation_queue 与 LibraryWatcherService 均已接线（`bootstrap.py:448/517`）
- 桌面收藏、最近文件夹、批量重命名、排序都已落地
- `directory_cache` 是否真无上限增长 —— 路径未走通，划为待确认
- ETag 真实收益 —— 无法验证浏览器启发式缓存，标 advisory
- 桌面端网格是否已有虚拟化 —— 未读 `_grid_widget_data.py`，"列表无分页"只报 Web 端

---

## 七、建议的实施顺序

按"用户感知强度 ÷ 成本"排：

1. **搜索截断可见**（§2.3）—— 一行参数 + 一行提示，止住"我这张图不在库里"的错误结论
2. **watcher `popleft()`**（§3）—— 一行
3. **收藏上限与类型放开**（§4）—— 小改，止住静默失败
4. **全库结构化检索**（§2.1）—— 唯一同时救桌面和 Web 的改动
5. **撤销栈复合 entry + 备份入库回收站**（§1.1）—— 补上安全网最大的两个洞
6. **活动日志接 activity_log**（§1.2）—— 表已存在，补写入方
7. **大目录计数异步化**（§3）—— 中期
8. **只读连接池**（§3）—— 大工程，最后做，且只做读路径

**暂缓**：跨库检索（§2.2）、命名集合（§4）—— 等 §2.1 落地后它们的价值才接得住。

---

## 附：环境提示

`.worktrees/grid-zoom-interpolation-fix/` 是主树的一份完整副本，grep 统计时容易污染计数，后续排查建议排除。
