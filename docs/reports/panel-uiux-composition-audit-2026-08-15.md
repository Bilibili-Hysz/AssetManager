# 桌面三主面板组件构成与 UI/UX 优化审查（2026-08-15）

> 范围：Sidebar（`panels/sidebar.py` + `_sidebar_parts.py`）、FileList（`panels/file_list/*`）、InfoPanel（`panels/info.py` + `_info_parts.py`）。
> 方法：主智能体用 workflow 并行委派 3 个 `opencode-go/deepseek-v4-pro` 只读审计子代理（file_list 首次返回 null，重试成功）；主智能体对关键结论逐项读代码复核（下文标注 ✅ 为已复核项）。本报告只做审查与建议，**未改任何代码**。
> 基线文档：`visual-drawing-audit-2026-08-15.md`、`ui-optimization-priority-2026-08-15.md`、`file-list-architecture-review-2026-08-15.md`、`HANDOVER-2026-08-15.md`。

## 0. 结论摘要

三个面板的主题 token 纪律整体已达较高水平：颜色/字号/图标绝大多数走 `themes`/`StyleKit`/`scaled_px`，历史渲染 bug 已清零。本轮的剩余问题集中为四类：

1. **UI 缩放刷新只刷 QSS 不刷几何**：InfoPanel、Sidebar 标题栏按钮在 `ui_scale_changed` 时 fixed size / spacing / 布局参数不重算（InfoPanel 甚至没有 `refresh_scaled_geometry`）。
2. **样式存在“双份定义”**：同一控件在 `__init__` 与 `_on_theme_changed` 里有两套 QSS（InfoPanel 分组框 4px↔6px 会跳变；FileList 导航按钮两套 hover）。
3. **反馈语义不准确/缺失**：Sidebar 搜索计数虚高、搜索时收藏区凭空消失；FileList 搜索结果 Toast 英文硬编码、下拉框无 tooltip/accessibleName；InfoPanel 加载/空/错误三态混在一起。
4. **已知未落地项仍有少量**：分类徽章固定 hex（P0-1）、对比色 helper 重复（P0-4）、StyleKit 重复实例化（P2-9）、tag_tree 点击不导航（P1-6）与缺 tooltip（P2-10）。

**建议路线**：先做 P0「小而快」批次（约 1 个会话、全 S 级改动），再做 P1「UX 语义」批次（M 级，含 category token），最后按需处理 P2 重构债。

---

## 1. Sidebar 侧栏

### 1.1 组件构成

| 组件 | 位置 | 职责 |
|---|---|---|
| SidebarPanel 根 | `sidebar.py:87-201` | 组装搜索条 / 树 / 状态栏，订阅 refresh/theme/language/ui_scale 总线 |
| 搜索框 QLineEdit | `sidebar.py:108-113, 647-705` | 200ms 防抖过滤；`_PreloadTask` 后台预扫 max_depth=2 |
| 展开/折叠按钮 | `sidebar.py:147-167, 757-800` | 渐进式批量展开（`_EXPAND_ALL_BATCH=8/帧`） |
| 主树 QTreeWidget | `sidebar.py:123-141, 937-956` | DropOnly 拖放、惰性展开、右键菜单、树 QSS |
| 收藏/最近虚拟头 | `sidebar.py:315-350` | 虚拟 header + child，emoji→SVG 图标迁移 |
| 文件系统分支 | `sidebar.py:352-445` | 按 `_depth/_branch_depths` 截断，`...` 占位惰性加载 |
| 底部状态栏 | `sidebar.py:175-184, 394-398` | 固定 28px，显示根数量或空态一行文本 |
| `_PreloadTask` | `_sidebar_parts.py:33-67` | 后台 scandir 深度 2，代际失效控制 |
| 标题栏齿轮 | `sidebar.py:1027-1043` | 打开 SidebarSettingsDialog；inline QSS |
| 设置对话框 | `dialogs/sidebar_settings_dialog.py:22-169` | 区段可见性 + 全局/每分支深度（31b095a 已修显示问题） |

### 1.2 审查发现（按优先级）

| ID | 级别 | 类别 | 问题 | 位置 | 建议 | 状态 |
|---|---|---|---|---|---|---|
| S-F1 ✅ | M | UX | 搜索匹配计数虚高：祖先分支被计为“匹配” | `sidebar.py:802-827` | 仅直接命中（`text in item.text(0)`）时计数 | 新 |
| S-F2 | M | 性能 | 预扫回填 O(结果×树规模) 全树 BFS | `sidebar.py:684-755` | 回填时建一次 path→item 索引，O(N)→O(1) | 新 |
| S-F3 ✅ | M | 视觉 | 齿轮按钮 QSS 固定创建时颜色/尺寸，dock 不监听 ui_scale | `sidebar.py:1038-1040`、`dock_factory.py:237` | `set_button_variant("ghost")` + dock 增 scale 刷新 | 新 |
| S-F4 ✅ | M | UX | 搜索时收藏/最近区整块隐藏且无提示 | `sidebar.py:697-699` | 保留头部并标注“不参与搜索”，或 placeholder 提示 | 新 |
| S-F5 ✅ | L | 视觉 | `accent+"30"` 拼 alpha；高亮闪烁不受 reduce_motion | `sidebar.py:838-846` | `alpha(t["accent"],0.19)` + reduce_motion 短路 | 新 |
| S-F6 ✅ | L | 一致性 | 展开/折叠按钮魔法 alpha 0.375 + inline QSS | `sidebar.py:159-167, 983-994` | ghost 变体统一，删重复 QSS | 新 |
| S-F7 | L | UX | 拖拽收藏整行实心 accent，落点不明确 | `sidebar.py:456-484` | 半透明高亮 + 目标项描边/drop 提示 | 新 |
| S-F8 ✅ | L | UX | 展开全部不持久化收藏/最近头展开态，刷新后回折叠 | `sidebar.py:774-777` | 同步 `_fav_expanded/_rec_expanded` | 新 |
| S-F9 ✅ | L | UX | 搜索预扫深度硬编码 2，无视 per-branch 配置 | `sidebar.py:665` | 深度取配置最大值并设安全上限 | 新 |
| S-F10 | L | UX | 空态仅状态栏一行 muted 文本 | `sidebar.py:394-398` | 复用 `widgets/empty.py` 语义图标空态 | 新 |
| S-F11 | L | 性能 | `clone()` 重新实例化面板，重复读盘扫描且丢 services | `sidebar.py:1077-1092` | 共享数据源引用 + 状态快照 | 新 |
| S-F12 ✅ | L | 可达性 | 搜索框/状态文本无 accessibleName；删除收藏无确认 | `sidebar.py:108-113,180,912-924` | 补 accessibleName；删除前确认/撤销 | 新 |
| S-K1 ✅ | M | UX | **已知未落地 P1-6**：tag_tree 点击只改窗口标题不导航 | `tag_tree.py:202-206`、`window.py:672-673` | `tag_tree.directory_selected → file_list.navigate_to` | 已知 |
| S-K2 ✅ | L | 可达性 | **已知未落地 P2-10**：tag_tree 新增按钮缺 tooltip | `tag_tree.py:62-66` | `setToolTip(tr("tagtree.new_tag"))` | 已知 |

---

## 2. FileList 文件列表

### 2.1 组件构成

| 组件 | 位置 | 职责 |
|---|---|---|
| FileListPanel 编排器 | `_base.py:75-341,489-814,911-1782` | 工具栏/面包屑/搜索/状态栏 + 网格/详情双视图编排（仍 1782 行） |
| Header Bar | `_base.py:116-134,477-484,518-525` | 面板标题条（样式三处重复拼 f-string） |
| Toolbar | `_base.py:136-200` | back/forward/up + 4 个 QComboBox + eye/refresh + 搜索框 |
| 导航按钮工厂 | `_ui_helpers.py:48-64` | ghost 图标按钮（`font_size` 形参未使用） |
| 面包屑 | `_navigation.py:270-321` | >5 段折叠为 `…`，全 muted 无当前段高亮 |
| 状态栏 | `_base.py:224-242,345-353,953-979` | 计数/总大小 + 4s 操作反馈；border-top 未用 `border_subtle` |
| FileListGridWidget | `_grid_widget.py:47-1718` | 自绘画布：纹理缓存、两遍绘制、hover 抬升、框选、缩放 |
| 卡片渲染 | `_grid_widget.py:1035-1099` | 整卡含副标题烘焙进纹理；卡片底色/边框 alpha 10/20 |
| 文件夹/类型绘制 | `_grid_widget.py:1223-1313` | 金色混合、阴影 `QColor(0,0,0,20)`、`lighter(120)` 等魔法值 |
| 分类徽章 | `_common.py:22-62`、`_grid_widget.py:1317-1331` | 固定 hex 映射（P0-1 未落地） |
| Details 视图 | `_detail_model.py:1-325`、`_base.py:282-328,1270-1307` | 5 列虚拟模型 + QTreeView + header 局部 QSS |
| 行高委托 | `_ui_helpers.py:27-33` | 详情行 32sp |
| GridLayout | `_grid_layout.py:1-103` | 纯几何：compute/rect_at/visible_rows |
| GridTextureCache / Animator | `_grid_texture_cache.py`、`_animator.py` | 已抽取；widget 仍深挖私有成员（耦合未封） |
| 缩略图链路 | `_thumbnail_delivery.py`、`_loader.py`、`_model.py` | 50ms 批量失效；3 线程池 + 64MB 缓存；异步扫描/排序 |
| 批重命名 | `_batch_rename.py`、`_batch_rename_dialog.py` | 纯规划 + 预览对话框 |

### 2.2 审查发现

| ID | 级别 | 类别 | 问题 | 位置 | 建议 | 状态 |
|---|---|---|---|---|---|---|
| F-01 ✅ | M | 视觉 | **P0-1 未落地**：分类徽章固定 hex，不随主题 | `_common.py:26-33` | 收敛为 `category_*` token（每主题可覆盖）+ 对比度文字判定 | 已知 |
| F-02 ✅ | L | 视觉 | 卡片 alpha 10/20/50/80/200、圆角 4/5、阴影 20 魔法数 | `_grid_widget.py:1054-1056,1206-1215,1252,1282,1304` | 提模块级派生常量 | 新 |
| F-03 | L | 视觉 | hover 抬升 `1.075/-5px` 硬编码不随缩放 | `_grid_widget.py:777-778,803,807` | `max(1, scaled_px(5))` + 主题属性 | 新 |
| F-04 ✅ | M | 一致性 | 导航按钮样式两处定义不一致（`panel+"80"` vs `alpha(0.50)`） | `_ui_helpers.py:59-63` vs `_base.py:526-531` | 单一 `_make_nav_button` 样式源 / ghost 变体 | 新 |
| F-05 ✅ | L | 可达性 | 4 个 QComboBox 无 tooltip/accessibleName | `_base.py:150-181` | 补 tooltip + accessibleName | 新 |
| F-06 ✅ | L | UX/i18n | 搜索结果 Toast 英文硬编码 | `_base.py:800` | 新增 i18n key（en/zh/ja） | 新 |
| F-07 | M | 性能 | 滚动每帧全视口重绘（历史定性，未落地） | `_grid_widget.py:1394-1401` | 短期跳过 Python 层 intersects；长期条带级失效 | 已知 |
| F-08 | L | 性能 | 目录大小副标题到达触发整卡纹理重建 | `_base.py:895-909`、`_grid_widget.py:431-455` | 副标题单独分层绘制 | 已知 |
| F-09 | L | UX | 面包屑当前段无高亮、`>` 文本分隔符 | `_navigation.py:284-312` | 末段 heading/accent + chevron 图标 | 新 |
| F-10 ✅ | L | 视觉 | 状态栏发丝线未用 `border_subtle` | `_base.py:345-349` | `border-top: 1px solid {t['border_subtle']}` | 新 |
| F-11 | L | 一致性 | cache/animator 私有成员被 widget 深挖，抽取未封口 | `_grid_widget.py` 多处 | 显式 read API / 回调参数化 | 已知 |
| F-12 | L | 可达性 | 网格无焦点可见指示；`setFocusProxy(search)` | `_grid_widget.py:1590-1651`、`_base.py:222` | 画锚点行焦点环 | 新 |
| F-13 ✅ | L | 一致性 | `_make_nav_button(font_size=…)` 死参数 | `_ui_helpers.py:48` | 删除或真正生效 | 新 |
| F-14 ✅ | L | 一致性 | **P0-2 已落地**：`#c480d4` 已移除 | `git log -S c480d4` → `84eb48a` | 无需处理 | 已修 |
| F-15 ✅ | L | 一致性 | header/详情 QSS 三处重复，无统一 chrome 刷新 | `_base.py:120-133,477-484,518-531,1270-1307` | 提取 `_apply_chrome_style()` | 已知 |

---

## 3. InfoPanel 信息面板

### 3.1 组件构成

| 组件 | 位置 | 职责 |
|---|---|---|
| InfoPanel 根 | `info.py:48-308` | QSplitter(预览/元数据) + 底部固定 Actions；订阅 domain events 与总线 |
| `_PreviewLabel` | `_info_parts.py:59-67` | 预览自绘 QLabel，双击全屏 |
| 空态/占位 | `info.py:99-114,749-770,1317-1340` | “无选中”48px 与“无预览”64px 两套语义混叠 |
| 元数据滚动区 + QGroupBox | `info.py:121-171` | 标题/文件名/5 字段/链接/插件字段 |
| `_make_field/_make_link_field` | `info.py:496-553` | label 65px + value；链接含 `_DragLabel` + 按钮组 |
| `_DragLabel` | `_info_parts.py:26-56` | 点击打开/拖拽到浏览器 |
| 标签 `_FlowLayout` + chips | `info.py:176-226`、`_info_parts.py:70-134`、`widgets/tag_chip.py` | 流式换行、≤8 个渐入；chip 无键盘焦点、hover 仅描边 |
| 笔记区 | `info.py:229-241,1121-1150` | QTextEdit + 1200ms 防抖保存 |
| Actions 固定栏 | `info.py:248-281` | 28px 固定高；仅构造时 scaled |
| 面板菜单 | `info.py:660-678` | 五区 show/hide，不持久化 |
| 异步任务 | `_info_parts.py:156-281`、`info.py:818-868` | 文件信息/预览/URL/目录大小后台加载 |

### 3.2 审查发现

| ID | 级别 | 类别 | 问题 | 位置 | 建议 | 状态 |
|---|---|---|---|---|---|---|
| I-01 ✅ | M | 视觉 | **UI 缩放只刷 QSS 不刷几何**：footer 28px、预览最小高 60、FlowLayout spacing、18px 链接按钮、齿轮 20px 均不重算 | `info.py:252,94,187,591-627,650`；`info.py:307` 仅接 `_refresh_theme` | 新增 `refresh_scaled_geometry()`，构造与刷新共用 | 新 |
| I-02 ✅ | M | 视觉 | 分组框 QSS 双套参数：构造 4/4/6/8 vs 刷新 6/8/12/10，首次刷新跳变 | `info.py:135-138` vs `info.py:318-321` | 单一 `_group_css()`；尽量复用全局 QGroupBox 规则 | 新 |
| I-03 | M | UX | 异步占位 `…` 闪烁；resize 与 eventFilter 重复全尺寸缩放（防抖只接 splitterMoved） | `info.py:1186-1210,1304-1313,720-726,292` | 三态占位 + 统一防抖 timer | 新 |
| I-04 | M | 可达性 | chips 不可键盘到达；hover 无背景反馈；关闭钮 18px 偏小 | `tag_chip.py:83-116`、`info.py:902-907` | chip 焦点环 + hover overlay + ≥20px 目标 | 新 |
| I-05 ✅ | L | UX | “无选中/无预览/加载中”三态语义混叠、图标 48↔64 跳变 | `info.py:749-770` vs `1317-1340` | 显式分离 loading/empty/fallback 三态 | 新 |
| I-06 ✅ | L | 一致性 | **P0-4 未落地**：对比色 helper 两处重复且 fallback 已分叉 | `tag_chip.py:30-35` vs `tag_style_dialog.py:126-134` | 提 `color_utils.contrast_on()` | 已知 |
| I-07 ✅ | L | 一致性 | **P2-9 未落地**：`StyleKit.from_theme` 面板内 10 处重复实例化 | `info.py:133,312,405,…` | 模块级 `sk` 单例 | 已知 |
| I-08 | L | 性能 | 切文件全量重建字段/标签/链接按钮，无复用 | `info.py:570-635,909-928,1342-1361` | 链接按钮 hide/show 复用；chip 复用池 | 新 |
| I-09 | L | UX | 加载/解码/大小失败全静默，无错误态 | `info.py:855-856,888-890`、`_info_parts.py:194-199` | `state_css("error")` 或语义图标提示 | 新 |
| I-10 ✅ | L | 一致性 | 局部圆角 3/4/6px 与 padding 魔法数，未读主题 properties | `info.py:136-138,265-266,596-597,654` | 读 `themes.prop("border_radius"/"spacing")` | 新 |
| I-11 ✅ | L | 视觉 | 分组框实线 border 而非全局 `border_subtle` 发丝线 | `info.py:136-138` vs `themes.py:535-538` | 换 `border_subtle` 或删局部覆写 | 新 |
| I-12 | L | 一致性 | 空态与 fallback 图标语义/尺寸不一致 | `info.py:764-768` vs `1330-1339` | 统一基准尺寸与图标选择逻辑 | 新 |
| I-13 | L | UX | 面板菜单五区可见性不持久化 | `info.py:660-678`、`base.py:135-139` | 走 `save_state/restore_state` | 新 |

---

## 4. 跨面板共性机会

| 机会 | 涉及面板 | 说明 |
|---|---|---|
| `category_*` 主题 token 体系 | FileList | 闭环 P0-1：22 主题提供默认值 + `_EXTENDED_FALLBACKS` 兜底，徽章文字用对比度函数 |
| `contrast_on()` 公共 helper | Info / FileList / TagStyle | 闭环 P0-4，顺带修正两处 fallback 分叉 |
| StyleKit 模块级单例 | Info / 全局 | 闭环 P2-9（DRY，非性能必需） |
| dock 标题栏按钮统一刷新链路 | Sidebar / Info / FileList | `title_bar_buttons` 统一 ghost 变体；`dock_factory` 订阅 `ui_scale_changed` |
| `border_subtle` 发丝线推广 | FileList / Info / Sidebar | 与全局 QSS 视觉语言一致 |
| 三态（loading/empty/error）空态模板 | 三面板 | 复用 `widgets/empty.py` 语义图标，统一占位视觉 |

---

## 5. 建议执行批次（待用户确认）

### P0 · 小而快（全 S 级，预计一批提交）
1. **InfoPanel 缩放几何刷新**：抽 `refresh_scaled_geometry()`（I-01）
2. **InfoPanel 分组框 QSS 单一来源**（I-02 + I-11 + I-10 顺手）
3. **FileList**：状态栏 `border_subtle`（F-10）、搜索 Toast i18n（F-06）、4 个 ComboBox tooltip/accessibleName（F-05）、`font_size` 死参数（F-13）、面包屑末段高亮（F-09）
4. **Sidebar**：匹配计数修正（S-F1）、展开态持久化（S-F8）、齿轮 ghost + dock 缩放刷新（S-F3）、`accent+"30"`→`alpha`（S-F5）
5. **已知小项**：tag_tree tooltip（S-K2）

### P1 · UX 语义（M 级，可拆分）
- 三态预览/空态组件化（I-03/I-05/S-F10）
- `category_*` token（F-01）+ `contrast_on`（I-06）
- Sidebar 搜索回填索引化（S-F2）、搜索范围提示（S-F4/F9）
- tag chips 键盘/hover 反馈（I-04）；FileList 网格焦点指示（F-12）
- 面包屑/详情 chrome 刷新单一入口（F-15/F-04）

### P2 · 债清理（按需）
- cache/animator 显式 API（F-11）、控件复用池（I-08）、布局偏好持久化（I-13）、面板 clone 共享数据源（S-F11）、滚动条带失效（F-07）

### 待产品侧决策
- Sidebar 搜索是否纳入收藏/最近区（S-F4 open question）
- 分类徽章：新增 `category_*` token 全主题铺开 vs 仅修正文字对比度
- 面包屑当前段高亮是否符合既有视觉基线
- 滚动全帧重绘是否接受现状（需真机帧率数据，非代码审查可定）

---

## 6. 复核记录（主智能体执行）

- 直接读代码确认：S-F1/F3/F4/F5/F8/F12、S-K1/K2、F-01/F-02/F-04/F-05/F-06/F-10/F-13/F-15、I-01/I-02/I-05/I-06/I-07/I-10/I-11。
- `grep c480d4` + `git log -S c480d4`：仅剩 `icons.py` 注释示例，确认 P0-2 已在 `84eb48a` 落地（F-14 标为已修）。
- 子代理输出的行号与工作区实测有小幅偏差的，本报告已按实测修正；其余未逐条复核的结论保留子代理原始判断，标注为审计建议而非最终裁决。
