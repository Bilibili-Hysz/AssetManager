# Opencode 会话完整汇总 — PySide6 桌面端 UI/SVG 绘制 Bug 审计与修复

> **来源会话**：`ses_017505339ffeas793xTPQ7FLKL`（Opencode build 模式，模型 deepseek-v4-flash / variant max）
> **时间跨度**：2026-08-09 22:40 UTC ~ 2026-08-10 22:54 UTC（约 24 小时）
> **规模**：15 轮用户指令 / 263 条助手消息 / 352 次工具调用（bash 153、read 70、edit 55、task 48、write 14）
> **性质**：全程未产生任何 git commit —— 所有代码改动均处于工作区**未提交**状态
> **用途**：本文件是跨会话交接文档，新会话应先读本文件 + 文末列出的各阶段报告/计划文档

---

## 1. 任务背景

用户原始任务（2026-08-09 22:40）：

> 这是一个基于 Python PySide6 的桌面端文件管理器程序，我需要交给你一个任务：从文档和代码中了解该软件的架构设计，在桌面端的 UI 部分中逐行查找 UI，尤其是图标，SVG 部分的绘制 Bug。

任务随后扩展为一条完整的工作链（每轮用户指令即一个阶段，详见第 3 节）：

1. 第一轮 UI 绘制审计 → 写入文档 → 双子代理审计真实性
2. 并行子代理修复 → 审计子代理复审
3. 规划"界面图标 SVG 化"（emoji 与 SVG 并存、SVG 黑背景突兀）
4. RuntimeData 清空后重测 + 核查 File List 卡片 hover 动画卡顿问题
5. 检查 SVG 图标对主题色切换的响应
6. 评估改造主题系统传递图标语义色
7. 审查菜单栏组件
8. 依据架构图制定逐模块排 Bug 任务（P0/P1/P2 三轮）
9. P0 高危修复轮 → 中危修复轮（**会话在此轮验证阶段中断**）

---

## 2. 软件架构速览（会话中核实的规模数据）

| 分层 | 路径 | 规模 |
|------|------|------|
| Presentation | `window.py` `dock_factory.py` `window_coordinator.py` `window_lifecycle_coordinator.py` + `panels/` `widgets/` `dialogs/` | 桌面 UI |
| Controllers | `controllers/` | — |
| Application | `application/`（服务层：file_operation / undo / export / integrity / maintenance / runtime / tag_service 等） | — |
| Domain | `domain/` | — |
| Infra-core | `core/`（icons / themes / theme_loader / bg_effects / database / path_resolver / settings / json_store / cache / tag_library / project_data / config_migrator / tool_scheduler / crash_handler） | — |
| Infra-repo | `repositories/`（16 文件 SQL） | — |
| LAN | `lan/`（aiohttp 服务器，约 9.4k 行：server / manager / security / routes 23 个 / scanner / tunnel / ws / dto / api） | 内置局域网分享 |

关键机制（交接必备）：

- **图标系统**：所有图标统一经 `core/icons.py` 的 SVG 注册表 `icons.icon(name, color, size)` 渲染（63+ 调用点）；SVG 文件渲染进 QPixmap 后作为 QIcon 使用。
- **主题系统**：`core/themes.py` + `theme_loader.py`，JSON 驱动、热重载；`Assets/Themes/*.json` 共 22 个主题（`D_`=深色 / `L_`=浅色 / `U_`=自定义前缀）；颜色 token（heading/body/muted/accent/on_accent 等）+ 非颜色属性（opacity 等）；`themes.get()` / `themes.color()` / `themes.prop()`。
- **RuntimeData**：运行数据根目录；`Shared/<hash>.identity` 文件是库身份标记（`path_resolver.py`：`root_identity()` / `library_data_name()` / `library_data_identity_path()`），库数据按哈希槽位存放（含 `assetmanager.db` / `favorites.json`）。
- **测试基线**：README 记载最近一次全量 Python 运行为 **2790 passed, 7 skipped**；桌面核心 + LAN 全量约 1000+ 项。

---

## 3. 阶段时间线总览

| 阶段 | 时间 (UTC) | 用户指令摘要 | 产出 |
|------|-----------|-------------|------|
| 1 | 08-09 22:40~23:08 | 逐行查找 UI/图标/SVG 绘制 Bug | 13 项审计报告（5 确认 Bug + 8 次要），双子代理审计验证 |
| 2 | 08-09 23:08~23:11 | 修复任务委派并行子代理 | 11 文件 137+/27-，91 passed，审计 12/12 通过 |
| 3 | 08-09 23:11~23:20 | 规划图标 SVG 化 | 黑底根因确认（fill(0)=不透明黑）+ 迁移规划文档 |
| 4 | 08-09 23:20~08-10 00:13 | （规划批准后）执行 SVG 化 | 黑底修复、toast SVG 化、sidebar emoji 收口、迁移脚本 |
| 5 | 08-10 09:39~09:45 | RuntimeData 清空后重测 + hover 卡顿核查 | 169 passed；hover 动画未被改动（0.25ms 基准）；卡顿源=RuntimeData 污染 |
| 6 | 08-10 09:48~09:55 | 检查 SVG 图标对主题色响应 | 颜色跟随 ✓；3 个问题修复（favorite/recent 对比度、Default muted、菜单图标刷新） |
| 7 | 08-10 09:58~10:21 | 主题系统传递图标语义色 | 6 个 icon_* 语义 token，63 调用点/21 文件迁移，160 passed |
| 8 | 08-10 10:23~10:39 | 审查菜单栏组件 | 6 项修复 + 审计 6/6 通过 |
| 9 | 08-10 10:47~12:14 | 依据架构图逐模块排 Bug | 计划文档 + P0 第 1 轮 8 代理 → 8 份清单约 177 项 |
| 10 | 08-10 12:14~12:22 | （批准后）高危修复轮 | 15 高 + 4 顺带全修，370 passed，LAN 513 + 桌面 547 无回归 |
| 11 | 08-10 12:23~14:54 | 中危修复轮 | 6 组并行修复，D1/D2/E/F/G1/G2 状态各异，**会话中断于最终回归验证** |

---

## 4. 阶段 1 — 第一轮 UI 绘制审计（13 项）

审查方法：通读架构文档 + 逐文件审查 UI 绘制代码（icons.py / themes.py / _grid_widget.py / hsv_wheel.py / bg_effects.py / workspace_bar.py / sidebar.py / tray.py / dialogs / image_viewer 等），数值验证用 python 计算与 Qt offscreen 探针。随后 2 个只读探索子代理逐项复核。

### 确认 Bug（5 项）

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| 1 | `core/icons.py:113-117`（严重） | `icon()` 创建 QPixmap 未乘屏幕 DPR、未 `setDevicePixelRatio()` → 所有 63 处图标在高 DPI（125%/150%）屏幕模糊 | 按 `primaryScreen().devicePixelRatio()` 渲染物理尺寸 + setDevicePixelRatio(dpr)；缓存键扩为 `(name, tint, size, dpr)`；无屏幕回退 1.0 |
| 2 | `widgets/hsv_wheel.py:56-60`（严重） | HSV 色轮饱和度方向反转：`sat = 1.0 - r/radius` 显示为"外圈白内圈饱和"，与取色逻辑（中心白边缘饱和）相反 | `sat = r/radius`；循环起点 `int(radius)-1` 保留 1px 色相环 |
| 3 | `core/bg_effects.py:25-37` | `apply_blur` 用 QGraphicsBlurEffect 直接渲染等尺寸 pixmap，边缘无像素可采样 → 四边半透明暗晕 | 9 格平铺扩边 `pad=2*radius` → 模糊 → `copy(pad,pad,w,h)` 裁回；边缘 alpha 29%→97% |
| 4 | `widgets/workspace_bar.py:214-235` | 标签指示条仅 `_on_current_changed`/`add_library` 时更新，窗口 resize 后 `tabRect()` 变化而指示条错位 | 新增 `resizeEvent`，stop 两动画后按 `tabRect(currentIndex())` 无动画对齐 |
| 5 | `dialogs/theme_preview_dialog.py:89-94` | 先 `pixmap.fill(QColor(accent))` 填满再 `drawRoundedRect` 只描边 → 圆角从未生效，四角直角 | 透明填充 + `setBrush(accent)`+`setPen(NoPen)` 圆角填充 |

### 次要问题（8 项）

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| 6 | `_grid_widget.py:1362` | `cat[:4]` 截断分类文本（"3D Models"→"3D M"），无省略号 | 新增 `_CATEGORY_LABELS`，`elidedText(完整标签, ElideRight)`（审计修正：实为规范 key 小写碎片，非示例所示） |
| 7 | `window.py:153-158` | resize 防抖 150ms 期间直接绘制未缩放的 `processed` 原图 → 大图拖动掉帧 | dirty 期间也生成 scaled（不写缓存），防抖结束后一次性重建入缓存 |
| 8 | `themes.py:438` | `QMainWindow::separator` 无效选择器（死代码） | 删除 |
| 9 | `icons.py:75` | `_ALIASES["chevron-right"]` 永不命中（normalize 先 replace("-","_")）——死代码；`more-horizontal` 同理 | **有意未修复**（删除会改变 normalize()/has() 容错面且零用户影响，保留兼容插件调用） |
| 10 | `tray.py:59-68` | 兜底托盘图标取 `themes.get()['accent']`，主题切换后不刷新；主题 dict 空时 KeyError | `themes.get().get("accent", "#4a60b0")` 兜底 + `_generated_icon` 标志 + `theme_changed` 连接，仅兜底图标随主题重建 |
| 11 | `_grid_widget.py:1459` | 滚动条几何硬编码 8px，未随 ui_scale 缩放 | `_relayout_scrollbar()` 用 `scaled_px(8)`；resizeEvent 与 refresh_scale 均调用（含宽高≤0 守卫） |
| 12 | `_base.py:1142` | 拖拽预览 `suffix.upper()`（如 ".BLEND"）绘入 40px 图标区无省略号 | 加 `elidedText(ElideRight)`（审计修正：".blend1" 为高频特例，属"无省略号裁切"而非溢出） |
| 13 | `sidebar.py:41-52` | legacy emoji 映射语义错乱（审计扩为 4 条：💾🖥🎨🔥，溯源至 favorites.json 与 commit 8899575） | 💾→file、🖥→grid、🎨→image、🔥→star（4 条全落在 `_ICON_PATHS` 内） |

**双子代理审计结论**：13/13 全部确认为真实问题，无反驳项；3 处表述修正；额外确认测试缺口（`test_icons.py` 无 DPR 断言、`test_workspace_bar.py` 未覆盖 resize 指示条）。

---

## 5. 阶段 2 — 修复轮（11 文件，91 passed，审计 12/12）

- 3 个并行修复子代理（文件集互不相交：core 组 / widgets 组 / panels+dialogs 组；widgets 组首轮空返回后重派成功）
- 结果：**11 个文件、137 处新增 / 27 处删除**；`ruff check` 全过；定向 pytest **91 passed**（icons 3 + bg_effects 5 + workspace_bar 6 + grid 72 + tray/sidebar 5）
- 2 个只读审计子代理复审：**12/12 通过**，无回归（关键验证：icons DPR 缓存键含 dpr 且渲染尺寸正确；hsv 修复后保留 1px 色相环；bg_effects 边缘 alpha 29%→97% 且零位移；workspace_bar 动画打断无旧目标回写；emoji 4 条映射无静默 fallback）
- 审计发现的**预存在问题**（非本次引入）：`tests/unit/test_tray.py` 缺 QApplication fixture 会挂起；grid 测试未覆盖新标签/省略号与 scale 重排路径
- **重要**：工作区原有 191 个已修改文件（README 记录），本次修复为增量；`git diff` 中与 Bug 无关的 hunk（`_base.py` warnings 反馈、`window.py` integrity 调度等）为预先存在改动，已排除在修复范围外
- 文档：`docs/reports/ui-rendering-audit-2026-08-10.md` 追加「四、修复记录」

---

## 6. 阶段 3+4 — 图标 SVG 化规划与执行

### 黑底根因（本阶段最重要的发现）

用户实机观察：SVG 图标带纯黑矩形背景，浅色主题/半透明面板下突兀。渲染探针（offscreen）实测确认：

> **`core/icons.py:117` 的 `pixmap.fill(0)` —— 整数 0 被 Qt 解析为 `Qt.GlobalColor.color0`（不透明黑，alpha=255），而非透明**。16px 图标 256 像素中透明像素 = **0**，全部图标带纯黑矩形底。此前两轮审查都误判 `fill(0)` 为透明，是用户实机观察暴露的深层缺陷。

修复：`fill(0)` → `fill(Qt.GlobalColor.transparent)` + 新增透明性回归测试锁定。**探针 288 组合全过**。

### 规划（docs/plans/icon-svg-migration-2026-08-10.md）

- 阶段 0：黑底一行修复 + 回归测试
- 阶段 1：数据层 emoji 收口（写入点规范化、legacy 映射扩充、tag icon 字段启用渲染、一次性幂等迁移脚本）
- 阶段 2：图标词汇扩充 + sidebar 选择列表 6→14 个
- 阶段 3：全图标渲染探针 + 测试 + 文档

### 执行结果（组 A/B/C 并行）

1. **黑底修复**：`fill(Qt.GlobalColor.transparent)`，探针 288 组合全过（各图标名 × 尺寸 × 颜色）
2. **toast SVG 化**：`widgets/toast.py` 图标从纯文本升级为真正 SVG 渲染（level 色保留显式 hex 通道），测试同步更新语义
3. **数据层 emoji 收口**：
   - `dialogs/sidebar_favorites.py`（add/set_icon 写入点）、`dialogs/sidebar_recent.py`：`icons.normalize(..., fallback="star")` 规范化
   - `application/tag_service.py` + `repositories/tag_repository.py` + `panels/tag_tree.py` + `controllers/tag_tree_controller.py`：tag icon 写入规范化 + tag icon 字段启用渲染
   - `panels/sidebar.py`：_FAVORITE_ICON_MAP 规范化
   - 新增 `scripts/migrate_legacy_icons.py`：一次性幂等迁移（favorites.json + tag_metadata 的 legacy emoji → SVG 名），dry-run 默认、`--apply` 写回；单库失败不阻断其他库
4. **迁移脚本踩坑记录**（重要教训）：RuntimeData 被测试残留污染（10.5 万个带 db 的假库、数万 identity 文件），目录枚举/名称启发式/identity 内容均无法区分真实库与测试残留 → 改为**显式库根参数模式（默认不扫描 RuntimeData）**
5. 组 C 审计发现 2 处修复：`monitor-screen` 别名死代码、迁移脚本被残留目录淹没（即上述第 4 点）

**验证**：91 项相关测试全过（icons 5 + bg_effects 5 + workspace_bar 6 + sidebar/tag/toast 等 81 + grid 72 中相关子集），ruff 全绿。

---

## 7. 阶段 5 — RuntimeData 清理回归 + hover 动画核查

用户删除 RunTimeData 全部内容后重测，并质疑 File List 卡片 hover 动画被改动（实测不跟手、卡顿）。

**结论：**

1. **测试**：RuntimeData 清空后 **169 passed**，ruff 全绿；迁移脚本恢复正常（`libraries scanned: 10, failed: 0, 无需迁移`）
2. **hover 动画未被改动**（代码证据）：`_grid_widget.py` 本次修复 diff 仅 3 处（Bug 6 标签 elideText、Bug 11 滚动条），hover 整条路径（`_hover_progress` 插值、`_anim_tick` 16ms 定时器、lift 1.075× 缩放、`_draw_interaction_overlay`）与修复前**逐字节相同**（git diff 无任何 hover 相关 hunk）
3. **性能基准**（offscreen 实测，120 项网格 × 90 帧，含纹理预热/未预热）：无 hover 0.17ms avg / 0.34ms worst；hover 中 0.25ms avg / 0.47ms worst —— 60fps 预算 16.6ms 的 1.5%，**动画不可能造成可感知卡顿**
4. **卡顿真实嫌疑**（按可疑度排序）：
   - **RuntimeData 污染**（最可疑，用户已删除）：此前 10 万+ 测试残留目录拖慢目录枚举、文件监视、缩略图缓存与扫描路径
   - **缩略图首帧烘焙**：hover 快速掠过未烘焙行时 `_render_item` 每帧最多烘焙 12 张卡（原有行为，加载完成后平滑）
   - 对比基线：若对比更早 commit（`5dc165f`/`2fb246c` 时代），工作区累积未提交改动可能含其他性能差异
   - RAW_PIXMAP 来自 ThumbnailLoader 投递的已缩放缩略图，烘焙成本低

---

## 8. 阶段 6 — 主题色响应检查（3 个问题修复）

探针实证结论：

- **颜色跟随 ✓**：63 个 `icons.icon()` 调用点全部使用主题 token（默认 `heading`）；主题切换 → `clear_cache()` + 各面板刷新即时重建。端到端验证：Navy（深 `#e8ecf8` 浅线）→ Dawn（浅 `#241c10` 深线）→ 切回 Dracula（`#f8f8f2` 立即重建）
- **深浅方向 ✓**：深色主题浅线、浅色主题深线，无"深色变浅/浅色变深"反转

**发现并修复的 3 个问题：**

1. **浅色主题收藏/最近图标偏淡**（真缺陷）：favorite 金色 `#b89020` 在 10 个浅色主题面板上对比度仅 2.7（<3.0 不可辨）→ 改 `#6b5216`（6.7-7.0）；recent `#5a90b8`→`#35637f`（3.1→5.9）—— 批量更新 10 个浅色主题 JSON
2. **Default 主题 muted 对比不足**：`#666666` vs panel 2.67 → `#757575`（≈3.3）
3. **菜单栏 QAction 图标不随主题刷新**（window.py:240-264）：工具菜单图标创建时一次性着色，深→浅切换后旧浅色图标残留在浅色菜单上不可见 → 保存 `(action, icon_name, fallback)` 规格 + 新增 `_refresh_tools_menu_icons()`，由 `WindowCoordinator._apply_theme` 经 `_refresh_ui_icons` 调用

**验证**：ruff 全绿；pytest 77 passed；全量对比度复核 22 主题 × 7 token vs 面板/基底，**LOW 组合 0**。`on_accent` 初查 1.1 为探针背景选错（应对比 accent 而非 panel），对 accent 全部 ≥4.7，无问题。

---

## 9. 阶段 7 — 图标语义色体系改造（已落地）

**现状回答**：此前并非硬编码（颜色取自主题 token），但**语义分散**：17 处 heading、12 处 body、8 处 muted 散落 20+ 文件，同类别控件 token 不一，主题无法统一调控图标。

**改造内容：**

1. **主题系统**（`core/themes.py` `_EXTENDED_FALLBACKS`）新增 6 个图标语义 token，JSON 可覆盖，默认继承文本 token：

   | token | 继承 | 用途 |
   |-------|------|------|
   | `icon_primary` | heading | 菜单/工具栏/标题栏 |
   | `icon_secondary` | body | 树节点/列表/普通按钮 |
   | `icon_muted` | muted | 辅助按钮/占位 |
   | `icon_on_accent` | on_accent | 强调背景图标 |
   | `icon_accent` | accent | 强调色图标 |
   | `icon_disabled` | disabled_text | 禁用视觉 |

2. **`icons.icon()` 三态 color 输入**：`None`→自动取 `icon_primary`；语义 token 名→`themes.color()` 解析；显式 hex/rgba→原样使用（**"额外需求"通道**：badge 分类色、video 紫 `#c480d4`、status 多态色、toast level 色、hover 动态色均保留走此通道）

3. **63 个调用点迁移**（3 子代理、21 文件）：`t["heading"]`→`"icon_primary"` 等；sidebar favorite/recent 分派改为 `"favorite"`/`"recent"` 语义 token 名。渲染结果与迁移前**逐像素一致**（默认值=旧 hex）

**验证**：ruff 全绿；**160 passed**（含新增 4 项语义色解析测试）；遗留硬编码调用点扫描 = **0**；**覆盖能力实证**：临时主题 JSON 覆盖 `icon_primary: "#ff00ff"` → 全局默认图标渲染 (255,0,255)，一键统一图标色（期间探针脚本自身 bug：`pixmap(24)` 在图标实际 16px 时返回 16x16 越界采样，修正后通过）。

**使用方式**：主题 JSON 加 `"colors": { "icon_primary": "#88ccff", ... }` → 所有菜单/工具栏/标题栏图标即时生效，文本色不受影响。

---

## 10. 阶段 8 — 菜单栏审查（6 项修复 + 审计 6/6）

组件范围：`_menu_widget`（库菜单 / 设置 / 工具菜单 / WorkspaceSection 库标签 / 分享按钮）全链路。

| # | 严重度 | 问题 | 修复 |
|---|--------|------|------|
| 1 | **严重** | 菜单选中项文字对比度不足：`QMenu::item:selected` 用 accent 背景 + heading 文字，**17/22 主题 < 4.5**（Nord 1.74、Rose Pine 1.59 几乎不可读） | 选中项文字改 `on_accent`（修复后全部 ≥4.70） |
| 2 | 中 | 分享按钮 hover 固定白色 `alpha('#ffffff', 0.1)`，浅色主题无反馈 | 改用 `hover_overlay` token 随主题自适应 |
| 3 | 中 | 菜单 QSS 双份重复维护（window.py + window_coordinator.py，漂移风险） | window 版委托 coordinator，单一定义点 |
| 4 | 低 | 语言切换刷新缺口：键盘快捷键项、分享不可用项、分享按钮 tooltip 不刷新 | 保存引用 + 纳入 `_refresh_language`（hasattr 防御） |
| 5 | 低 | `_lan_server = None` 藏在 `_setup_tools_menu` 末尾（误导） | 移至 `__init__` |
| 6 | 低 | WorkspaceSection "+" 按钮为文本 | SVG `plus` 图标（icon_primary）+ 三语 i18n `workspace.add_library` |

核查通过项：菜单几何 `_on_menu_row_resize`（20%/80% 边界、窄窗口隐藏 workspace）、最近库菜单 aboutToShow 重建与 lambda 捕获、菜单图标全 icon_primary + 主题切换重着色、`QMenuBar::item:selected` 透明 accent 背景。

**验证**：ruff 全绿；pytest 28 passed；审计子代理 6/6 通过无回归。报告：`docs/reports/menubar-review-2026-08-10.md`。

---

## 11. 阶段 9 — 逐模块排 Bug（P0 第 1 轮，8 代理 → 约 177 项）

计划文档：`docs/plans/bug-hunting-2026-08-10.md`。架构分层 → 12 个模块任务卡，3 个优先级轮次：

- **P0（第 1 轮，已完成）**：M10 LAN（A1 server/auth/security/path_guard · A2 routes 23 个 · A3 scanner/tunnel/ws）、M6b 文件操作与撤销（B1 file_operation+undo · B2 export+integrity+maintenance）、M8 core 基础设施（C1 database/migrations/lock · C2 settings/json_store/cache · C3 runtime/reconciliation/bootstrap）
- **P1（第 2 轮，未开始）**：M6a 资产/索引/缩略图/搜索服务（D1/D2）、M9 repositories 16 文件 SQL 安全（E1a/E1b）、M6c 分享/商业：配额竞态、订单状态机、金额精度（F1/F2）
- **P2（第 3 轮，部分并入中危轮）**：M1 file_list（G1/G2）、M2 info/sidebar（H1/H2）、M3 dialogs（I1）、M4 窗口/dock（J1/J2）、M5+M7 controllers/domain（K1/K2）

**执行**：8 个只读探索代理并行（2 个首轮空返回后重试成功），产出 8 份清单归档 `docs/reports/module-*.md`，**共约 177 项缺陷（高 15 / 中 41 / 低 121）**：

| 模块清单 | 高 | 关键缺陷（摘） |
|---------|----|----------------|
| module-lan-core.md | 2 | auth **fail-open**（DB 异常放行全部请求）、启动期同款 fail-open、seller 登录无严格限流、token 进日志/Referer、注销不撤销令牌 |
| module-lan-routes.md | 4 | thumbnails/shares 内联 SVG 无 nosniff（**XSS**）、模糊图失败回退原图（隐私绕过）、ZIP 符号链接泄露库外文件、batch 缩略图无限制 DoS |
| module-lan-tools.md | 1 | cloudflared 下载无校验/无超时/残留损坏 exe、隧道崩溃无监控、start 竞态误杀、WS 广播超时/序列化无防护、DTO KeyError→500 |
| module-file-ops.md | 4 | move 静默覆盖已存在目标、delete 投影异常致撤销备份整体丢失、unique_destination 只读目录死循环、撤销删除不恢复标签/元数据 |
| module-maintenance.md | 3 | 512MB DB 备份硬上限、备份目标静默覆盖、`_exists` 断连误判 MISSING 批量删元数据 |
| module-core-db.md | 1 | migrate_path_metadata LIKE 大小写不敏感 DELETE 与 remap 大小写敏感冲突致整子树数据删除 |
| module-core-store.md | 0 | settings/JsonStore 无锁与损坏文件不修复、LRU None 误判、TagLibrary 同义词冲突/无锁、ProjectData mtime 缓存过期 |
| module-runtime.md | 1 | 双实例启动冲突阻断库打开、损坏 marker 阻断库打开、崩溃日志明文泄露、tool_scheduler args 类型无校验 |

**复核通过的检查点（无问题项）**：路径遍历核心防线（path_guard）、中间件顺序、PBKDF2+compare_digest、SQL 注入（全参数化）、下载/配额竞态（CAS 单条 UPDATE）、WebSocket 越权广播、zip slip、迁移回滚幂等性、跨库撤销隔离。

---

## 12. 阶段 10 — P0 高危修复轮（15 高 + 4 顺带全修）

3 个修复子代理并行（文件集互不相交），修复前每项经第二子代理复核真实性，修复后审计子代理复审。2 个预期行为测试随契约更新。

| 组 | 修复项 | 关键点 |
|----|--------|--------|
| **A · LAN 安全**（6 高） | ✅ | server.py `_has_active_users` DB 异常 **fail-closed**（拒绝而非放行）；manager.py `_configured_auth_status` 异常按 auth_mode 安全默认，不静默降级无认证；thumbnails.py 排除 .svg + 全局 nosniff；blur 失败返回 500 不再回落原图；shares.py 公开预览排除 .svg + nosniff；_helpers.py ZIP 打包拒绝 symlink/越界 resolved 路径 |
| **B · 文件数据安全**（8 高） | ✅ | move/rename 目标已存在禁止覆盖（lexists 检查）；删除投影清理异常降级 warning，撤销备份不再被误弃；**撤销删除恢复投影快照**（tags/meta/favorites 随备份 JSON 保存，restore 写回，含 remap）；unique_destination 仅 FileExistsError 重试 + 1000 次上限（只读目录不死循环）；备份 512MB 硬上限移除（大库 quick_check 标记 skipped）；备份目标已存在拒绝静默覆盖；integrity `_exists` 父目录不可达判 UNKNOWN 不删元数据；migrate_path_metadata DELETE 与 remap 统一精确匹配（不再误删整子树） |
| **C · 可用性**（2 高 + 2 中顺带） | ✅ | tunnel 下载超时 + 临时名 + `--version` 冒烟校验 + 原子替换；reconciliation 双实例 generation 冲突降级 warning 不再阻断库打开；损坏 legacy marker 迁移降级为空队列不阻断打开；crash_handler 崩溃日志敏感信息脱敏（token/密钥/Bearer） |

**验证**：ruff 全绿；定向测试 **370 passed, 2 skipped**（Windows 环境性：symlink 权限 + 进程终止确定性）；LAN 全量 **513** + 桌面核心 **547** 通过，无回归。

**剩余**：中危 41 项 / 低危 121 项待 P1/P2 轮；`file-ops` 第 13 项（批量 move 部分成功时撤销记录缺失，需扩展 `FileOperationResult` 契约）建议中危轮优先处理。

---

## 13. 阶段 11 — 中危修复轮（进行中，会话中断）★ 交接重点

用户指令「启动」→ 6 个修复子代理并行（约 49 项，已排除修过的 runtime 6/9/16 项）。分组与最终状态：

| 组 | 文件范围 | 状态 |
|----|---------|------|
| **D1** LAN 认证/路由 | `lan/security.py` `lan/server.py` `lan/manager.py` `lan/routes/auth.py` `lan/routes/thumbnails.py` `lan/routes/_helpers.py` | ✅ 审计 6/7 完整（含 seller 登录纳入严格限流 10 次/300 秒） |
| **D2** LAN 工具链 | `lan/scanner.py` `lan/tunnel.py` `lan/utils.py` `lan/ws.py` `lan/dto.py` | ✅ 审计 9/10 完整；1 项回归（dto `is_active` 默认值）已修复 |
| **E** 文件操作/撤销 | `application/file_operation_service.py` `application/undo_service.py` `panels/file_list/_actions.py` | ✅ 审计 12 项全落盘（跨盘移动失败清理目标残留等） |
| **F** 导出/完整性/维护 | `application/library_export_service.py` `application/database_integrity_service.py` `application/database_maintenance_service.py` | ✅ 完成（备份读源并发修改检测 3 次重试、进度回调与取消；3 个 stop 契约测试更新：新行为=等待 drain 而非抛异常；barrier 释放早于 stop 的时序调整） |
| **G1** core 存储 | `core/settings.py` `core/json_store.py` `core/cache.py` `core/tag_library.py` `core/project_data.py` `core/config_migrator.py` | ✅ 两次委派失败后主代理亲自实施 7 项（settings 损坏 JSON 修复、JsonStore 加锁、LRU None 修复、TagLibrary 同义词冲突「场景/毛发」、ProjectData 尺寸缓存 TTL 失效、未来版本配置不 quarantine 仅拒绝加载） |
| **G2** runtime/身份 | `core/path_resolver.py` `core/database.py` `application/runtime.py` `application/context.py` `core/tool_scheduler.py` `application/security_preflight.py` | ✅ 完整完成（失败回滚状态 "open"→"failed" 为预期行为变化，3 个 runtime 测试断言已更新；dto 回归已修） |

**已更新的测试**：`tests/unit/test_library_runtime.py`（3 处断言）、`tests/unit/test_database_integrity_service.py` + `test_database_maintenance_service.py`（3 个 stop 契约）、`tests/unit/test_library_export_service.py`（512MB 上限契约）。

**已知测试路径坑**：`tests/desktop/test_workspace_bar.py` 不存在（在 `tests/unit/`）、`tests/application/test_tag_service.py` 不存在（在 `tests/integration/`）、`tests/core/test_color_utils.py` 与 `tests/desktop/test_startup.py` 不存在（是 `test_startup_window.py`）。

**中断点**：最后一条助手消息为「继续验证。分片运行回归测试（先快后慢）」，会话在运行 `python -m pytest tests/core tests/unit -k "settings or cache or tag_library or json_store or config_migrator or project_data or file_operation or undo or integrity or maintenance or export or runtime or reconciliation or crash or security_preflight or tool_scheduler"` 系列分片回归时结束（最后已知通过：test_library_runtime + integrity + maintenance 定向 **64 passed**）。

---

## 14. 文档产物清单（仓库内）

| 文件 | 内容 |
|------|------|
| `docs/reports/ui-rendering-audit-2026-08-10.md` | 阶段 1/2：13 项审计 + 双子代理审计结论 + 修复记录 |
| `docs/plans/icon-svg-migration-2026-08-10.md` | 阶段 3/4/6/7：SVG 化规划、黑底根因、主题色响应修复、语义色体系 |
| `docs/reports/menubar-review-2026-08-10.md` | 阶段 8：菜单栏审查 6 项修复 + 审计附录 |
| `docs/plans/bug-hunting-2026-08-10.md` | 阶段 9/10：逐模块排 Bug 计划、P0 轮 1 结果、高危修复轮记录 |
| `docs/reports/module-{lan-core,lan-routes,lan-tools,file-ops,maintenance,core-db,core-store,runtime}.md` | 8 份模块排 Bug 清单（177 项，含行号与修复建议） |
| `scripts/migrate_legacy_icons.py` | 一次性幂等迁移（emoji → SVG 名），dry-run 默认，`--apply` 写回 |
| `scripts/icon_render_probe.py` | 图标渲染探针（透明度/颜色验证） |

---

## 15. 代码改动范围（全部未提交，与 191 个预存修改文件混在工作区）

- **core**：`icons.py` `themes.py` `bg_effects.py` `database.py` `path_resolver.py` `settings.py` `json_store.py` `cache.py` `tag_library.py` `project_data.py` `config_migrator.py` `tool_scheduler.py` `crash_handler.py`
- **application**：`file_operation_service.py` `undo_service.py` `library_export_service.py` `database_integrity_service.py` `database_maintenance_service.py` `runtime.py` `context.py` `tag_service.py` `security_preflight.py` `asset_index_reconciliation_service.py`
- **lan**：`security.py` `server.py` `manager.py` `scanner.py` `tunnel.py` `utils.py` `ws.py` `dto.py` `routes/auth.py` `routes/thumbnails.py` `routes/shares.py` `routes/_helpers.py`
- **Presentation**：`window.py` `window_coordinator.py` `widgets/toast.py` `widgets/hsv_wheel.py` `widgets/workspace_bar.py` `widgets/tray.py` `widgets/lan_sharing.py` `dialogs/theme_preview_dialog.py` `dialogs/sidebar_favorites.py` `dialogs/sidebar_recent.py` `panels/sidebar.py` `panels/tag_tree.py` `panels/file_list/_grid_widget.py` `panels/file_list/_base.py` `panels/file_list/_actions.py` `controllers/tag_tree_controller.py` `repositories/tag_repository.py`
- **资源**：`Assets/Themes/*.json`（10 个浅色主题 favorite/recent + `D_Default.json` muted）
- **i18n**：`AssetsManager/i18n/{zh,en,ja}.json`（`workspace.add_library`）
- **测试**：`tests/core/test_icons.py` `tests/desktop/test_tag_chip.py` `tests/unit/test_library_runtime.py` `tests/unit/test_database_integrity_service.py` `tests/unit/test_database_maintenance_service.py` `tests/unit/test_library_export_service.py` 等

---

## 16. 当前状态与下一步（新会话起点）

**已完成**：桌面 UI/SVG 绘制层全部审计项（13 项）、SVG 化迁移、主题语义色体系、菜单栏审查、P0 排 Bug（177 项清单）、高危修复轮（15+4 项）。

**未完成（按优先级）：**

1. **中危轮收尾**：G1/G2 落盘后**尚未跑最终全量回归**（会话中断于分片验证）；建议先跑 `python -m pytest tests/core tests/unit -k "settings or cache or tag_library or json_store or config_migrator or project_data or file_operation or undo or integrity or maintenance or export or runtime or reconciliation or crash or security_preflight or tool_scheduler"` 确认全绿，再补一轮审计复审（D1/D2/E 曾"返回空但已落盘"，虽已审计，建议抽查完整性）
2. **中危剩余项**：确认 6 组清单中未覆盖的中危项（如 `lan-tools` 未列入 D2 的项、`module-lan-core.md` 中未修的限流/令牌撤销等）
3. **P1 轮**：M6a 资产服务、M9 repositories SQL 安全、M6c 分享/商业（配额竞态、订单状态机、金额精度）
4. **P2 轮**：M1 file_list、M2 info/sidebar、M3 dialogs（sharing_settings_dialog 2161 行）、M4 窗口/dock、M5+M7 controllers/domain（约 121 项低危）
5. **file-ops 第 13 项**：批量 move 部分成功时撤销记录缺失（需扩展 `FileOperationResult` 契约）
6. **补测试**（审计发现的预存缺口）：`test_tray.py` 缺 QApplication fixture 会挂起；grid 测试补新标签/省略号与 scale 重排路径；`test_icons.py` 补 DPR 断言（部分已补，可核对）

**执行模式参考**（沿用会话既定流程）：每轮 explore 排 Bug → 修复子代理（文件集互不相交）→ 第二子代理复核真实性 → 修复后审计子代理复审 → 定向 pytest + ruff 全绿；既有 160+（现约 500+）测试保持全绿。

---

## 17. 注意事项与已知坑（新会话必读）

- **不要 commit/push**：所有改动（含 191 个预存修改）均在未提交工作区；仓库无远程 remote（此前 push 尝试 exit 128）
- **工作区 diff 混杂**：`git diff` 中与本次任务无关的 hunk 是预先存在的用户改动，修复/审计时勿误判、勿回退
- **RuntimeData 会被测试污染**：测试会产生海量残留目录（曾达 10.5 万），拖慢一切且会淹没扫描类脚本；涉及扫描/迁移的脚本应支持显式库根参数；测试前建议定期清理
- **LSP 噪音**：`_grid_widget.py:1060` 附近 "data/index is not a known attribute of None" 等报错为既有 stub 噪音，非本次引入
- **Windows 环境**：目录 symlink 测试无权限会 skip；进程终止类测试不具确定性会 skip
- **探针脚本注意**：`QIcon.pixmap(n, n)` 在图标实际尺寸 < n 时返回实际尺寸 pixmap，越界采样会得到错误像素（阶段 7 曾踩坑）
- **Qt 整数 0 陷阱**：`QPixmap.fill(0)` 是不透明黑（`Qt.GlobalColor.color0`）而非透明 —— 必须用 `fill(Qt.GlobalColor.transparent)`
- **测试文件路径**：`tests/desktop/test_workspace_bar.py`、`tests/application/test_tag_service.py`、`tests/core/test_color_utils.py`、`tests/desktop/test_startup.py` 均不存在，实际路径见第 13 节
