# AssetManager 未来发展规划

> 产出日期：2026-08-30
> 基线 commit：`d548156`（schema v38）
> 产出方式：四专家并行规划（PM / 架构师 / 桌面端设计 / Web 端前端）+ team-lead 独立复核
> 性质：**规划，未实施**

---

## 零、三个改变判断的发现

### 发现一：商城是死代码，不是资源错配

这是本轮最重要的发现，它改写了我自己上一轮"62% 页面在商城"的结论。

```python
# AssetsManager/lan/routes/system.py:115-116
commerce_enabled = s.get("lan_commerce_enabled", False) is True      # 默认关闭
seller_enabled   = commerce_enabled and s.get("lan_seller_enabled", False) is True

# webui/src/components/layout/AppHeader.tsx
grep "storefront|seller|commerce"  →  零命中      # 全站无入口
```

| 事实 | 证据 |
|---|---|
| 商城**默认关闭** | `system.py:115`；`App.tsx:49` 要求 `flags.commerce && flags[feature]` |
| **全站无入口** | `AppHeader.tsx:109-128` 导航只有 Gallery + Workspace；`LandingPage.tsx:495,504` 指向 `/gallery`、`/browse` |
| **只能从桌面端开启** | 唯一写入点 `dialogs/sharing_settings_dialog.py:1279`；Web 端 AdminPage 仅 66 行 |
| **一次性投放** | 18 个页面全部来自单提交 `43742f6`（2026-08-11，15,444 行）；此后 StorefrontPage 仅 2 次提交，对比 BrowsePage 26 次 |
| **维护成本实证** | 占 dist 15 chunk / 116K（903K 的 13%）；`StorefrontCartPage` 206 行 **0 测试**；a11y 门禁 9 条路由中占 3 条（33%），且 `:39` mock 写 `commerce:true`（非生产默认） |

**结论**：这 16 个页面在默认配置下全部返回 NotFoundPage，用户进不去、发现不了。它们不是"错配的活跃功能"，是**已经死掉但没清理的代码**。

上一轮我判断"功能重心偏离主用户"——方向对，但性质判断轻了。资源的真实状态是：**沉淀在一个默认关闭、零增长、用户不可达的功能上**。

同时，商城还泄漏进了桌面端：

```
AssetsManager/application/ 下 9 个商城服务（共 57 个服务，占 16%）
shop_service / shop_authorization / shop_buyer_service / seller_auth_service
seller_profile_service / order_service / quota_service
free_download_quota_service / storefront_analytics_service
```

**桌面端每天启动会加载 9 个对创作者零价值的商城服务。**

### 发现二：两个刚建的能力是死列（第 12、13 次「生产了没人消费」）

你自己最近 23 个 commit 建的 v36 / v37 地基，**还没接消费端**：

```python
# tag_service.py:474-476
def get_all_tags(self, library_root, db_conn=None, *, source: TagSource = "human"):
                                                              # ↑ 默认 human
# controllers/tag_tree_controller.py:37-39
def get_all_tags(self):
    return self._tag_svc.get_all_tags(self._library_root)     # ← 不传 source
```

| 死列 | schema | 生产消费 | 状态 |
|---|---|---|---|
| `ai_asset_tags` / `plugin_derived_fields`（v36） | 已建 | **0 处生产写入，0 处读取** | 两张空表 |
| `file_meta.rating`（v37） | 已建（3 处定义） | **0 处** | 全库无消费者 |
| `asset_sequences` / `asset_sequence_frames`（v37） | 已建 | 0 处生产读写 | `sequence_service.py:6-7` 自述"为后续扫描保留" |
| `SearchIndexService`（v39 FTS） | 已建 | **全仓 0 处构造** | 迁移时种子一次，永不维护 |

**`SearchIndexService` 是最危险的**：v39 FTS 索引只在迁移时种子一次、从不维护、从不查询。架构师原话——**留着不维护的索引比没有更危险**，一旦接查询就静默返回过期结果。

> **我要为此负一部分责任**：上一轮我把"标签物理分表"列为最该先做的事，理由是"为 AI 预留隔离"。但我没说清楚分表只是地基、必须同时接读取端。结果你建了三张表，读取端永远走 human。

### 发现三：派生物体系有真 bug，会持续产出错误数据

这条比性能问题严重——性能让你等，正确性让你信错数据。

```python
# 对照组：缩略图（做对了）
project_service.py:759-762
    if row.source_mtime_ns is not None:
        if source_stat.st_mtime_ns != int(row.source_mtime_ns):   # 有失效比对
    elif source_stat.st_mtime != row.source_mtime:                # 有失效比对

# 派生物（缺失）
analysis.py:383
    if recorder.lookup(path, "extracted_palette") is not None:    # 只判断"行存在"
```

`derivatives.py` 写入了 `source_mtime`（`:236,240`），但**全仓没有任何一处拿它和当前 mtime 比对**（derivatives.py 之外那 65 处命中全是 thumbnail 的）。

**后果：源文件改了，音频波形和主色永远喂旧的。** `analysis.py:371-376` 注释自己写得很清楚——"factory runs only when the row is still missing"，而 `ON CONFLICT` 只更新 `created_at`。

派生物体系三个缺口：

| 缺口 | 证据 | 后果 |
|---|---|---|
| 失效不闭环 | `source_mtime` 无比较点 | 源改了喂旧数据 |
| 清理不闭环 | `clear()`（`derivatives.py:256`）**0 调用者** | 死行堆积 |
| 路径迁移不含派生物 | `_migrate_path_metadata_impl`（`database.py:1336-1486`）重映射 file_tags/file_meta/library_favorites/thumbnail_cache，**不含 asset_derivatives** | 改名后旧行 + 旧 payload 双孤儿 |

**同类问题**：`asset_collection_members.file_path` 是裸 TEXT 无外键（`schema_defs.py:526-532`），改名后合集**静默丢成员**。

---

## 一、战略定位

### 一句话定位

> 面向创作者/收藏者的**本地优先 + 局域网自托管**数字资产库——素材留在你的硬盘，桌面端负责生产整理，局域网 Web 负责分享与交付。**它不是商城。**

### 商城决策

| 选项 | 收益 | 成本 | 用户影响 | 风险 |
|---|---|---|---|---|
| A 保留强化 | 变现闭环 | 6+ 人月持续投入（支付/订单/退款/风控） | 核心用户零收益 | 收款 = 金融合规与资金风险 |
| B 冻结 | 止血最快 | 冻结≠零成本，安全补丁仍要碰 | 半成熟体验，**最差结果** | 僵尸功能持续吸注意力 |
| **C 剥离为插件包** | 核心包瘦身，交付能力保留 | 一次性 2-4 周 | 卖家转插件，创作者不受影响 | 边界划不干净会回漏 |

**推荐 C。**

考虑到"发现一"（商城已默认关闭、无入口、零增长），C 的实际成本比预估更低——它已经是事实上的死代码，剥离只是让代码状态追上现实。

创作者的真需求是"把选中的资产打包给客户、可控失效"，不是开网店。**保留分享/交付，砍掉交易闭环。**

### 差异化：三张独占牌

基于实读竞品副本 `_REF_Serpent`（Electron + React，1.5 个月 257 star）：

**Serpent 已有的**：插件/脚本/MCP（`127.0.0.1:47342`，破坏性操作带 challenge 二次确认）、云端 AI（自带 Key、人工/AI 分层）、WebDAV 同步、直开 Eagle/Billfish 库、OpenColorIO 色彩、链接文件夹 + gitignore 过滤、智能合集、序列帧折叠。

**Serpent 明确推迟的**：团队协作、多机并发、原生性能上限（10 万文件 / 2TB）。

**Eagle / Billfish**：闭源订阅、无 API、无自托管。

**我们的三张牌**：

1. **PySide6 原生桌面端** —— 真文件系统操作、大目录性能、托盘、Qt 交互，非套壳浏览器
2. **局域网自托管服务端** —— 140 路由 + SQLite WAL + 访客权限，**正是 Serpent 推迟的协作地带**
3. **Python 插件生态** —— `core/plugins` + `plugin_api`（含权限/身份/线程隔离测试），可吃 Python 生态（RAW/PSD 解码、FFmpeg、本地 ML），而 Serpent 只有 JS 一等公民

**结论：别在"单机管理器"赛道正面刚，打「原生桌面 + 局域网共享」这个交叉带。**

### 用户分层

创作者 **70%**（唯一核心）> 局域网访客 **20%**（只读消费）> 管理员 **10%**（权限/审计）> 卖家 **0%**（插件自负盈亏）

---

## 二、分端定位

| 归属 | 功能 | 理由 |
|---|---|---|
| **桌面端专属** | 导入/链接文件夹/watcher；批处理与破坏性操作（重命名/移动/删除/批量标签）；自动化规则与脚本、AI 批量入队；缩略图与派生物生成、解码器注册、格式扩展、插件运行；库维护（完整性/迁移/备份/导出）；MCP 本地暴露 | 碰磁盘 + 长任务 + 本机凭据 |
| **Web 端专属** | 访客只读浏览（LAN + 分享链接）；交付包下载与到期/口令/次数控制；跨设备零安装访问；服务端全局管理（用户/权限/路由策略/审计） | 价值来自"不在你电脑前的那个人" |
| **两端共享** | 检索语义（关键词 + 结构化过滤 + 标签 + 合集，共用查询 DSL，服务端为唯一权威）；元数据模型（人工 vs AI 分层）；查看器能力（序列帧/波形/3D/RAW-PSD）；主题与快捷键 | 避免两端语义漂移 |

**放错端的**：
1. **商城逻辑泄漏进桌面端** —— 9 个 shop_* 服务（最严重的错端）
2. 投入与价值倒挂 —— 桌面端 30 入口 vs Web 26 页面含 16 商城
3. Web 端能看合集/收藏却不能建、不能批量整理 —— 悬在消费与生产之间

---

## 三、架构演进方向

### 3.1 数据层：不拆库，拆写入域

39 次迁移里 **13 次是商城**（`db_migrations.py:1305-1318`）。判据不该是"迁移次数"，应是**写入频率与生命周期是否冲突**。

**目标形态**：同库内按前缀隔离——
- **商城域**（订单/购物车/配额）：高频写、需独立 prune
- **资产域**（assets/file_tags/file_meta/asset_index/asset_derivatives/asset_search）：随扫描批量重写

两套迁移序列 + 两套清理任务。物理拆库（ATTACH）的触发条件：商城日均写量 > 资产扫描写量。

**派生物建模**：现有 `(file_path, kind)` 主键 + `payload=False` params-only 行（`derivatives.py:215`）方向正确。缺的是**派生契约**——每个 kind 声明 `invalidate_on` / `rebuild_cost` / `max_age`，由统一 Governor 驱动。现在只有 2 个 kind 就已全漏失效。

### 3.2 连接与并发：先修正一处事实

**不是"全库串行锁"**（我上一轮的说法不准确）。WAL 已开（`database.py:399`），锁是按连接的（`_write_lock_for:549`）；全局 `_write_gate:546` 只在 legacy 无参路径生效。

**真正串行的是 `locked_read:1266-1302`——读也走写锁**，61 处把同库读写串成一条。

分三步：

| 步骤 | 改动 | 收益 | 风险 |
|---|---|---|---|
| **第 1 步**（1-2 天） | `locked_read` 改为从**只读连接池**（每库 N=4，`mode=ro`+`query_only`）借还 | 同库读读并发；零调用点改动 | 需审计 61 处中"写后立刻读"的调用点（**架构师未做此审计，这是第一步的真实工作量**） |
| 第 2 步 | `_write_gate` 降级为按库（现为跨库单例）+ `wal_autocheckpoint` 节流 | 多库互不阻塞 | 中 |
| 第 3 步 | LAN 的 `asyncio.to_thread` 换**有界 DB 专属 executor**（现默认 min(32,cpu+4) 线程全堵同一 RLock） | async 对 DB 路由不再白给 | 依赖第 1 步 |

### 3.3 分端技术边界：共享是对的，不要拆

`lan/server.py:259-281` 直接用 `bootstrap.runtime_for(session)` 组装 `LanScopedServices`，与桌面同一 bootstrap，AST 门禁守护的就是这个共享。

**三个撕裂点**：
1. 流式/进度（桌面要同步+可取消 `_loader.py:498` generation 协议；Web 要 async+Range）
2. 事务边界（`collection_repository.py:150-179`；LAN 一请求一事务 vs 桌面长生命周期 session）
3. GUI 阻塞（`wait_for_runtime(5.0)` `_loader.py:526` 被 `_base.py:133` 主线程调用）

**建议**：共享 `repositories/` + `domain/`，允许 `application/` 分叉——把需进度/取消/批量的服务抽成无 Qt/无 aiohttp 的 `_core`，两端各写适配层。

### 3.4 扩展点：够宽，缺三个生态原语

已有：`host_context.py:894-1160` 的 command/menu/tool_window/file_handler/context_menu/category/column/search_provider/theme_token + EventHook + 解码器注册表（`decoders.py:319`）。

缺：
1. **只读查询 API**（命名化资产查询 + 分页契约）—— AI/MCP/脚本要"给我满足 X 的资产"，现在只能碰 SQL
2. **派生物 kind 可扩展**（`derivatives.py:34` 是硬编码 frozenset，加一种要改代码 + 迁移）
3. **批量作业契约**（提交/进度/取消/结果）

缺这三个，AI 接入只能靠写死新 service。

### 3.5 技术债优先级

| 级别 | 内容 |
|---|---|
| **必须还** | 派生物失效（持续产出错误数据，越晚越脏）；derivatives / collection_members 的路径迁移与清理（数据正确性）；v39 FTS 接线或删表（定时炸弹） |
| **可带着走** | v36 空标签分表、v37 空序列表、rating 空列（零成本，等真消费者）；单连接串行读（第 1 步之前可带，但它是"桌面做生产"的性能上限） |
| **不该碰** | 39 次迁移历史（`db_migrations.py:1274` 已锁死，重写收益为零、风险是全量数据）；商城表物理拆分（若商城下线这 13 次迁移直接变死代码）；AST 12 层门禁（唯一阻止共享层腐烂的东西） |

---

## 四、桌面端功能规划

> 主线：**接通 + 去重 + 回收站**，不是再加第 31 个入口。

### 按工作流阶段

| 阶段 | 当前能力 | 缺口 | 建议 | 价值 | 成本 | 频率 |
|---|---|---|---|---|---|---|
| **导入** | 拖拽 `_base_logic.py:663`；剪贴板 `_actions.py:226,301`；监听默认开 120s `settings.py:25` | 导入时不查重 | 导入落库即算哈希，命中则提示"已存在 N 张" | 高 | 中 | 高频 |
| **组织** | 标签树 `tag_tree.py:185-200`；合集；批量重命名 | **rating 死列、ai 表无读取端、标签无层级** | **接通 rating + ai 标签展示**（改 1 处调用传 source） | **极高** | **低** | 高频 |
| **查找** | 名称/类别/结构化 `_model.py:432-460` | 全库无 saved_search / history | 筛选条件一键存为侧栏条目 | 高 | 低 | 高频 |
| **查看** | 序列帧 `image_viewer.py:646-660`；信息面板 `info.py:171-176` | 关闭键 28×24；无并排对比 | 并排对比（A/B 选图） | 中 | 中 | 低频专业 |
| **批处理** | 批量重命名、副本 `file_operation_service.py:935`、导出 | **全库无去重/相似检测** | 感知哈希 + 分组视图 | 高 | 中 | 高频 |
| **安全** | 撤销栈；备份/恢复 `window.py:409-410`；活动日志 | **无回收站/软删除** | 库内删除先入 `.trash` | **极高** | 低 | 高频 |
| **扩展** | 插件已完整（manager + dialog + tool_scheduler + 菜单注入） | AI 打标无 UI | 先给 ai 表接读取点，再谈生成 | 中 | 低 | 低频专业 |

### 体验债 vs 新功能：先还债，但要重新定义"债"

**这项目的病灶不是 UI 丑，是"做完了没接"**——rating 和 ai_asset_tags 就是"新功能做完了但没接"的证据。继续加新功能只会再造两个死列。

纯视觉债打包成**半天批次**顺手清掉：

1. 缩略图占位 alpha 6→~24（`_grid_widget_render.py:524-531`，一行，感知提升最大）
2. 关闭键 28×24→44×44（`image_viewer.py:886,1049`）
3. 焦点环补回（`themes.py:592`、`tag_tree.py:92`、`sidebar.py:1258`）
4. 主题预览入口（`theme_preview_dialog.py` 已存在，只差入口）
5. `_apply_sort`（`_model.py:966-991`）移出 GUI 线程——**先埋点**，实测 >100ms 才做

### 桌面端最该做的 3 件事

1. **接通 rating + ai_asset_tags** —— schema 已就绪、迁移已发，成本最低，把两个已投入的功能兑现
2. **回收站（库内软删除）** —— 创作者最怕误删，这是唯一"没了就不可逆"的缺口，且已有撤销栈可复用
3. **去重/相似检测** —— 几千到几万张资产的收藏者必然重复导入，目前**完全没有**任何检测能力

---

## 五、Web 端功能规划

### 高频页面（提交数/测试数/LOC 三路交叉）

```
BrowsePage（26 提交 / 44 用例 / 969 行 / 08-30 仍在改）
  >> LandingPage（11/29/534） > DetailPage（11/5/362）
  > ShareReceivePage（10/14/160） > Gallery*（3-5/3-4）
components/layout 最活跃（25 提交，Sidebar.tsx 433 行，合集工厂刚投入）
```

### 按角色

| 角色 | 当前能力 | 缺口 | 建议 | 价值 | 成本 |
|---|---|---|---|---|---|
| **局域网访客** | `ShareReceivePage.tsx:128-158` 密码(:95-126)、预览/下载(:139-154) | 后端 `domain/share.py:81-88` 已返回 `download_count/max_downloads/expires_in_hours`，TS 类型 `types/api.ts:361-363` 也有，**页面零渲染**；4 处 `h-screen`(73/81/89/97) 移动端裁切 | `min-h-[100dvh]` + 渲染剩余次数/到期倒计时/耗尽态 | **高**（唯一真实高频移动端场景） | **低**（纯前端，后端已就绪） |
| **创作者自己** | BrowsePage 969 行、三源检索 `aa01918`、合集 `cf10923` | **无分页**：`types/api.ts:182-189` FilesResponse 无 limit/offset；`lan/routes/files.py:28-32` 也不接受（注意 `project_service.py:192-194` 的 `to_response()` 已有 offset/limit/has_more，但 files.py 是另一套手写响应，`:118-125` 丢弃了分页字段） | files.py 复用 `to_response()` 或加 limit/offset，**再上虚拟滚动**（顺序不能反） | 高 | 中 |
| **协作者** | 8 项 capability（`contracts.ts:9-18`），`ProtectedRoute.tsx:5-11` 按 capability 守门 | 评论/协作标记**完全不存在**（无 comment 表、无 note 路由） | 本轮不做 | — | — |
| **管理员** | AdminPage 仅 66 行（测试 72 行），`:34` 裸 `min-h-screen` | 配额语义混在商城里 | 商城冻结后把「配额」剥离成独立 LAN 消费配额（`quota.py:293,307` 可复用） | 中 | 中 |

### 移动端：不做全站响应式，做访客链路优先

全站仅 15 处断点声明、分布在 6 个文件。但核心浏览层已有 JS 侧移动逻辑——`AppLayout.tsx:47` `useMediaQuery('(max-width: 768px)')`，`isMobile` 已流转到 ProjectGrid/ProjectCard/ProjectList/MasonryView。

**真实缺口只在访客入口**：`ShareReceivePage.tsx` 4 处 `h-screen`，移动端地址栏会裁切。

### 两端一致性：契约生成覆盖率仅 21%

| | 规模 |
|---|---|
| 生成契约 `contracts.ts` | **15 接口 / 124 行**（AUTO-GENERATED from `AssetsManager/lan/dto.py`，350 行） |
| 手写 `api.ts` | **71 接口 / 712 行** |

79% 靠手写，漂移风险高。**`ShareReceivePage` 漏渲染配额字段正是漂移的活样本**——类型里写了、后端也返回了，但没人渲染，测试也没发现。

**最低成本方案**：不新建机制，只扩 `dto.py` 覆盖面（把 `ShareInfoResponse`、`FilesResponse` 纳入），由 `gen_ts_types.py` 产出，CI 加一步"生成结果 diff 非空则失败"。比新造契约层便宜一个数量级。

> 生成器在仓库根 `scripts/gen_ts_types.py`，不在 `webui/` 下，前端容易不知道它存在。

### Web 端最该做的 3 件事

1. **冻结商城** —— 唯一能一次性回收 13% bundle + 33% 门禁预算 + 全部商城债的动作
2. **ShareReceivePage 访客链路改造** —— 后端/类型/i18n 三语全部到位，纯前端活，性价比最高
3. **files.py 补 limit/offset** —— 后端不分页，前端虚拟化无效（只省渲染不省传输）

---

## 六、路线图

| 阶段 | 周期 | 目标 | 关键动作 | 成功标准 |
|---|---|---|---|---|
| **阶段 0** | 0-1 周 | **止血：兑现已投入** | 接通 rating + ai_asset_tags；修派生物失效与路径迁移；ShareReceivePage 访客链路 | 修改源文件后波形/主色自动重建；改名后派生物与合集不丢；访客看到剩余次数 |
| **阶段 1** | 2-4 周 | **拆商城** | `/api/shop/*` 与 16 页面抽为 commerce 插件包（默认关闭）；桌面端移除 9 个 shop_* 依赖，只留分享交付 | 核心包 grep 不到 shop/order/cart/payment；桌面启动不加载商城服务；schema 只标归属不回退 |
| **阶段 2** | 6-8 周 | **回收站 + 去重** | 库内软删除；感知哈希去重与分组视图 | 删除可恢复；重复导入可被发现 |
| **阶段 3** | 6-8 周 | **命令网关 + 幂等** | 统一命令网关（所有变更唯一入口）+ 幂等键 + 执行前审批 + 执行日志 | 批量操作可重放/可审计/可撤销；同一幂等键重复提交只生效一次 |
| **阶段 4** | 6-8 周 | **MCP 暴露 + AI** | 命令网关直接生成 MCP tool catalog（删改类带 challenge）；AI 基于 ai_asset_tags 做人工/AI 分层、一键清空 AI 内容、自带 Key | 外部 Agent 跑通"检索→打标→入合集"；AI 永不覆盖人工内容 |
| **阶段 5**（可并行） | 4-8 周 | **性能与扩展** | 只读连接池第 1 步；大目录渐进加载；files.py 分页契约 | 5 万资产冷启 < 3s；Web 大库滚动不掉帧 |

---

## 七、需要你拍板的两个分歧

### 分歧一：批处理要不要"执行前审批"？

| 立场 | 理由 |
|---|---|
| **PM 主张做** | 它是 MCP、AI 批量、撤销栈增强、活动日志统一的共同地基；没有它，MCP 等于在无闸门系统上开后门 |
| **设计师反对** | Serpent 那套是团队/生产管线场景。**单人创作者下审批流 = 纯摩擦**，会拖慢高频操作 |

**这取决于你的用户到底是单人创作者还是有协作场景。** 如果是单人，建议只做幂等 + 日志（无摩擦），审批留到有协作需求再加。

### 分歧二：要不要做竞品库迁移（Eagle / Billfish）？

| 立场 | 理由 |
|---|---|
| **PM 主张做**（阶段 5） | 极强的获客手段 |
| **设计师反对** | 一次性需求，迁完永不打开；Eagle 无公开稳定格式规范，属持续维护负债。真要做就独立脚本，不进主程序 |

我倾向设计师：独立脚本是更合理的形态，不进主程序。

---

## 八、明确不该做的事

1. **支付/结算/退款** —— 金融合规与资金风险，与资产库身份冲突
2. **Web 端生产功能**（批处理/移动重命名/库设置）—— 把本地文件系统暴露给浏览器，权限模型无法收敛
3. **云端账号与中心化云同步** —— 先守住局域网自托管这张独占牌（WebDAV 可考虑，但那是复用现成协议，不是自建）
4. **桌面端商城界面** —— 拆出去就别回来
5. **向量/语义搜索与以图搜图** —— Serpent 明确推迟；结构化检索的埋点都还没有
6. **资产版本管理** —— 存储翻倍 + 冲突模型，单人场景 ROI 极低
7. **移动端 App** —— 响应式 Web 已覆盖"手机看一眼"这个唯一高频需求
8. **插件市场/社区** —— 先把 API 稳定下来，市场是规模问题不是功能问题
9. **合并 17 个 lucide chunk** —— 实测 19 个 icon chunk 合计 **5,663 字节**，占 dist 的 **0.6%**，收益约等于零，动手反而可能破坏 tree-shaking（**这条推翻了我上一轮的清单**）
10. **给商城页面还债**（补 Cart 测试、统一圆角、补 SellerGalleryEditor 响应式、清理 46 处 inline style）—— 若冻结决定成立，这些全部作废
11. **协作者评论系统** —— 需 schema v39 + 路由 + UI 全栈，成本最高，且与"Web=消费与分发"定位不符
12. **先上虚拟滚动再改后端** —— files.py 全量返回，前端虚拟化只省渲染不省传输

---

## 九、复核记录（team-lead 独立验证）

抽查 8 项，**全部属实**：

| 项 | 验证结果 |
|---|---|
| 商城默认关闭 | ✅ `system.py:115-116` |
| Web 端无商城入口 | ✅ `AppHeader.tsx` grep 零命中 |
| 商城单提交投放 | ✅ `43742f6` |
| 桌面端 9 个 shop 服务 | ✅ 占 `application/` 57 个服务的 16%（PM 报 8 个，实为 9 个） |
| rating 死列 | ✅ schema 3 处定义，业务消费 **0 处** |
| ai_asset_tags 无读取端 | ✅ `get_all_tags` 默认 `source="human"`，调用点不传参 |
| 派生物失效不闭环 | ✅ `derivatives.py` 无比对逻辑；对照组 `project_service.py:759-762` 有 |
| `clear()` 无调用者 | ✅ 定义 1 处，调用 **0 处** |

### 三位专家纠正了我的错误（重要）

上一轮我给专家的"已知未解决"清单里有 **3 条行号对不上**（我引的是旧报告，你 23 个 commit 后代码变了）：

| 我给的 | 实际 |
|---|---|
| `_loader.py:1376-1395` 切库阻塞 | ❌ 那是视频帧注册；真身 `_loader.py:526`，且**已加固**（5s 有界 + 超时清池 + 埋点） |
| `_model.py:899-923` 排序 | ❌ 那是 `shutdown()`；真排序 `_model.py:966-991`，且 n 是**单目录**不是全库 |
| "焦点指示器系统性关闭" | ⚠️ 全库仅 6 处，且 `QLineEdit:focus` 有边框 —— 是**不一致**，不是全局关闭 |

另有 2 条我的判断被专家推翻：
- **"全库串行锁"** → 实为 `locked_read` 让读走写锁；WAL 已开，锁是按连接的
- **"合并 17 个 lucide chunk"** → 实测仅占 0.6%，收益≈0

### 专家主动排除的（避免误报）

- 设计师差点误报：`window.py:421` `menuBar().hide()` 看着像"15 个入口全废"，回溯后确认 `window.py:512-549` 用 `setMenuWidget` 装了非原生菜单，**菜单可达**
- 架构师标注未验证：第 1 步只读连接池的"写后立刻读"审计（未做，可能推翻工期估算）
- 前端标注未验证：实际线上启用率（无埋点）、PM 的定位结论（并行中）

---

## 十、「生产了没人消费」完整清单（14 次）

| # | 基建 | 状态 |
|---|---|---|
| 1-5 | 门禁脚本 / crash.log / MaintenanceChanged / recoveryFailed / summaries | 前 4 条已修，第 5 条是误报 |
| 6 | `SearchResultSet` 诊断 + `include_status` | 已修（`adef752`） |
| 7 | `assets.size/mtime` | 已修（结构化检索 `e42e9bf`） |
| 8 | 后端三源搜索 | 已修（`aa01918`） |
| 9 | `activity_log` | 已修（`7d0e3e4`） |
| 10 | `PerformanceRecorder` 108 处埋点 | **未修** |
| 11 | `library_watcher_interval_seconds` | **未修** |
| **12** | `ai_asset_tags` / `plugin_derived_fields`（v36） | **未修 —— 两张空表** |
| **13** | `file_meta.rating`（v37） | **未修 —— 零消费者** |
| **14** | 商城 16 页面 + 9 桌面服务 | **未修 —— 默认关闭、无入口、零增长** |

外加：`SearchIndexService`（v39 FTS，全仓 0 处构造）、`asset_sequences`（v37，0 生产读写）、`host_context.columns()/search_providers()`（0 消费者）、ShareReceivePage 的配额字段（后端返回、类型有、页面零渲染）。

**这是这个项目最顽固的模式。阶段 0 的核心目标就是兑现已投入，而不是再加新东西。**
