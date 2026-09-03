# 桌面端视觉统一性 · 设计评审与收敛方案

> 视角：UI/UX Designer（设计评审 + 设计语言提案）  
> 日期：2026-09-03  
> 输入依据：`docs/reports/ui-inventory-2026-09-03.md`（62 个可见组件全量清单）  
> 结论性质：**提案，不含代码改动**

---

## 0. 结论先行

你的直觉是对的：界面确实"不像一套东西"。但**病灶不在颜色，也不在圆角数值**——我先做了反证：

| 检查项                         | 实测                                                     | 判定             |
| --------------------------- | ------------------------------------------------------ | -------------- |
| 硬编码 hex 色值                  | **22 处** / 33,072 行（panels 0 / widgets 14 / dialogs 8） | ✅ 色彩纪律极好       |
| QSS 裸写 `border-radius: Npx` | **0 处**（全部走 token 插值）                                  | ✅ 圆角纪律极好       |
| 动画时长分布                      | 200ms×5 / 150ms×3 / 300ms×1 / 120ms×1                  | ✅ 已聚簇在 150–200 |
| 固定控件高度分布                    | 28×6 / 24×2 / 36×1 / 32×1（28 = `control_height_md`）    | ✅ 垂直节奏统一       |

**原子层是干净的。问题出在原子之上的"组合语法"层。**

三个真实病灶，按对"整体观感"的伤害排序：

| 排序    | 病灶           | 一句话                                     | 用户感知强度 |
| ----- | ------------ | --------------------------------------- | ------ |
| **A** | **深度语言四套并存** | 卡片、浮层、缩略图各用各的投影体系，中间档还空着                | ★★★★★  |
| **B** | **两套渲染方言**   | QSS 世代与 QPainter 世代即使读同一组 token，材质手感仍不同 | ★★★★☆  |
| **C** | **组合语法缺失**   | 导航范式、按钮栏顺序、chrome 密度无成文约定               | ★★★☆☆  |

---

## 1. 病灶 A：深度语言四套并存（最高优先级）

深度（elevation）是人眼读取界面层级的第一线索。本项目存在 **4 套互不通约的深度表达**：

### A-1. 官方阶梯 `elevation.py` —— 三档，但中间档空置

```
widgets/elevation.py:16-20   _LEVELS = {1:(blur18,off4,α72) 2:(blur24,off8,α88) 3:(blur30,off12,α104)}
```

实际调用点全量清点：

| level | 使用点                                    | 证据                                                    |
| ----- | -------------------------------------- | ----------------------------------------------------- |
| **1** | Toast / PluginDetailPanel / Startup 卡片 | `toast.py:131`、`plugin_ui.py:189`、`startup.py:42,525` |
| **2** | **零使用** 🔴                             | —                                                     |
| **3** | CommandPalette / QuickLookOverlay      | `command_palette.py:329`、`quick_look_overlay.py:236`  |

> **Level 2 空置**意味着界面只有"贴地"与"最高"两档，缺失中间层。Toast（一条 2 秒即逝的轻提示）与 Startup 详情卡（常驻内容容器）共用 level 1，语义上完全不是一回事。层级是**跳**的，不是**渐变**的。

### A-2. 缩略图网格：另起炉灶，且比官方轻 2.4–2.9 倍

`panels/file_list/_grid_widget_render.py:564-601`，三层手绘堆叠矩形，**无 blur**：

| 层    | alpha  | 对比官方 level 1 (α72) |
| ---- | ------ | ------------------ |
| 外层弥散 | **18** | 0.25×              |
| 中层   | **28** | 0.39×              |
| 接触层  | **36** | 0.50×              |

**后果**：悬浮的缩略图卡片比弹出的对话框"轻"得多、且没有模糊柔边。同一个应用里两种物质感。

### A-3. 卡片层：半透明 + 发丝边，**零投影**

- InfoPanel 卡片：`info.py:421-455`，`panel` 底 alpha 0.45 + 发丝描边 + 圆角 md，注释自称 *"translucent depth"*——但没有任何阴影
- PluginCard：`plugin_ui.py:42`，hover 只变边框色，无阴影

### A-4. ImageViewerOverlay：**完全在深度体系外**

`panels/image_viewer.py:312` 靠全屏 `QColor(0,0,0,180)` 遮罩 + 容器描边建立层级，未调用 `apply_elevation`。

---

## 2. 病灶 B：两套渲染方言（材质手感分裂）

| 世代              | 组件                                                                | 渲染方式                       | 视觉特征                                     |
| --------------- | ----------------------------------------------------------------- | -------------------------- | ---------------------------------------- |
| **QSS 世代**      | Info/Sidebar/TagTree/全部对话框                                        | `setStyleSheet` + token 插值 | Qt 原生文本渲染、原生 focus rect、圆角作用于 border-box |
| **QPainter 世代** | 网格画布、ImageViewer、CommandPalette 行、MicroTabBar、WorkspaceBar、HSV 色轮 | 全自绘                        | 自管抗锯齿、自管字体、圆角作用于 path、**自带渐变/发光/多层阴影**   |

**即使两者读取完全相同的 token，观感仍然不同**，原因有三：

1. **文本**：QSS 走 Qt 字体 hinting，QPainter 常显式 `setFont` + `setRenderHint(TextAntialiasing)`，笔画粗细与灰度不同
2. **圆角基准**：QSS 圆角作用于 border-box，QPainter 作用于 path，同样的 `10` 视觉上后者略"瘦"
3. **效果加成不对称**：QPainter 世代普遍叠加了渐变底、弥散光、多层阴影；QSS 世代没有 → **自绘区域天生比 QSS 区域"高级感"更强**，形成质感断层

> 这解释了一个反直觉现象：项目明明 token 覆盖率 100%，界面却仍显割裂。**统一了数值，没统一材质。**



---

## 3. 病灶 C：组合语法缺失

| #   | 问题                 | 证据                                                                                                         | 设计影响                |
| --- | ------------------ | ---------------------------------------------------------------------------------------------------------- | ------------------- |
| C-1 | **两套设置中心范式**       | SettingsDialog 用 `QTabWidget:163`；SharingSettingsDialog 用左 nav_rail+堆叠 `:150-160`                          | 同一应用两套心智模型          |
| C-2 | **按钮栏顺序相反**        | `tabbed_dialog.py:312-328` OK 在最左；`modal_dialog.py:110-137` OK 在最右                                         | 肌肉记忆冲突，误点风险         |
| C-3 | **chrome 密度不等**    | FileList 双工具带 36+32=**68px**；Info 无工具带；Sidebar 单工具带+footer 28；TagTree 单工具带**无** footer                     | 各面板"边框占比"不同，切换时有跳变感 |
| C-4 | **分隔线 token 用法不一** | Info 用 `border`（`info.py:324`）；Sidebar/FileList 用 `border_subtle`（`sidebar.py:1302`/`_base_layout.py:326`） | 同层级分隔线深浅不一          |
| C-5 | **Info 面板两套正交可见性** | MicroTabBar 4 页签（`info.py:151-155`）+ 5 个独立开关分区（`info.py:932`）                                              | 两套机制互相打架            |

---

## 4. 产品性格定位（设计语言之锚）

在开药方前先定性格——所有后续取舍都由此推导。

### 4.1 这个产品是谁

从代码证据反推出的既有倾向：

- Info 卡片注释自称 *"Linear-style"*（`info.py:421-455`）
- 顶栏自绘紧凑、原生 menuBar 被隐藏（`window.py:433,637`）
- 大圆角（8/10/14/20）、发丝描边、半透明、弥散阴影
- 内置 23 套主题，**暗色 13 : 亮色 10**，默认 Navy（暗）

→ **既有基因 = Linear / Raycast / Arc 同族的"精密仪器"风格**：高密度、发丝线、克制用色、靠阴影而非边框建立层级。

### 4.2 但素材管理器有一个决定性约束 🔴

> **本产品的内容是"高信息密度的图像"。用户是设计师/摄影师，他们要判断素材本身的色彩、构图、质感。**

由此推出本产品最重要、也最容易被违反的一条设计法则：

### **法则：Chrome 必须退让，让缩略图成为唯一主角**

而当前主界面恰恰违反得最严重的地方，就在最高频的组件上：

| 网格卡片现状                  | 证据                               | 问题                                        |
| ----------------------- | -------------------------------- | ----------------------------------------- |
| 卡片渐变底（heading 色 α14→7）  | `_grid_widget_render.py:479-491` | 🔴 **污染用户对素材本身色彩的判断**——这不是审美问题，是**功能性缺陷** |
| 三层弥散阴影                  | `:564-601`                       | 🔴 一屏 100 张缩略图 = 100 份视觉噪音                |
| hover 放大 1.075 + 上移 5px | `:387-388`                       | 🟡 缩放导致缩略图重采样，hover 瞬间画质变糊                |
| 扩展名徽章按类别着色              | `:751-765`                       | 🟡 每张卡右下角一个彩色块，进一步抢注意力                    |
| 金色文件夹混色                 | `:656-712`                       | 🟡 装饰性混色，与内容无关                            |

**佐证**：项目专门做了 `DominantPaletteStrip`（`widgets/dominant_palette_strip.py:22`，Rec.709 亮度自适应描边）来帮助用户读取素材主色——说明用户**确实在意色彩准确性**。那么给缩略图铺一层渐变底，就是在和这个功能打架。

---

## 5. 设计语言提案

### 5.1 深度阶梯 E0–E4（收敛病灶 A）

| 级      | 名称       | 语义      | 视觉配方                                | 适用                                     |
| ------ | -------- | ------- | ----------------------------------- | -------------------------------------- |
| **E0** | Flat     | 内容容器，贴地 | `panel` α0.45 底 + 发丝边 + **无阴影**     | Info 卡片、PluginCard、侧栏分组                |
| **E1** | Raised   | 瞬时抬起    | elevation L1（blur18/off4/**α72**）   | Toast、hover 态卡片                        |
| **E2** | Floating | 常驻浮起面板  | elevation L2（blur24/off8/**α88**）   | PluginDetailPanel、Startup 卡片、QuickLook |
| **E3** | Modal    | 阻断式浮层   | elevation L3（blur30/off12/**α104**） | **CommandPalette（当前 L3 保留）**           |
| **E4** | Scrim    | 全屏阻断    | 全屏暗化遮罩 + 无自阴影                       | ImageViewerOverlay、QuickLook 遮罩        |

**关键手段：统一参数来源，而非统一渲染方式。**

`elevation.py` 目前只暴露"施加特效"的命令式 API，自绘组件用不了（它们不能挂 `QGraphicsEffect`，网格有 200 条 LRU 纹理缓存，性能上不允许）。因此：

> 新增**数据契约** `shadow_params(level) -> (blur, offset, alpha)`，让自绘组件取到**同一组数值**自己画。  
> 自绘的渲染方式可以保留（性能正确），但数值不再各写一套。

这条原则同样适用于病灶 B 的其余维度：**不追求渲染方式统一，追求参数来源统一。**

### 5.2 网格卡片减负（收敛法则违例）

| 项              | 现状                      | 建议                                     | 理由            |
| -------------- | ----------------------- | -------------------------------------- | ------------- |
| 卡片渐变底          | heading α14→7           | **移除**，改纯 `panel` 实底或极淡 α6 平色          | 消除色彩污染        |
| 常驻阴影           | 三层 α18/28/36            | **改为仅 hover/selection 时出现**，且取值接 E1 参数 | 100 份噪音 → 1 份 |
| hover 放大 1.075 | 放大 + 上移 5px             | **取消缩放，只保留上移 2px + E1 阴影**             | 避免重采样糊化       |
| 选中表达           | accent 填充 α80 + 描边 α200 | **去掉填充，只留 2px accent 描边 + α24 极淡底**    | 填充会盖住缩略图内容    |
| 扩展名徽章          | 类别着色实色块                 | 降为低对比度，或移入 hover 浮层                    | 减少常驻装饰        |

### 5.3 形式语法补全表

| 维度            | 现状                                                    | 提案                                                                                       |
| ------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **圆角**        | token sm8/md10/lg14/xl20 + `radius_xs`3；自绘裸值 3/4/5/10 | 自绘改为读 token；补 `radius_badge=6` 供徽章/小元件，消灭裸 4/5                                           |
| **动效**        | 150/200/300/120                                       | 具名档位：`instant 0 / fast 120 / base 150 / slow 200 / deliberate 300`；`themes` 增 `motion` 段 |
| **chrome 预算** | 28/32/36/68px 混用                                      | **主面板工具带统一 ≤36px，单层**；FileList Tier-1/Tier-2 合并或 Tier-2 可折叠                              |
| **分隔线**       | `border` 与 `border_subtle` 混用                         | 定义层级语义：**面板内分区用 `border_subtle`，面板边界用 `border`**                                         |
| **描边**        | 1px / 1.5px / 2px 混用                                  | 发丝 1px（静态）/ 1.5px（hover）/ 2px（焦点与选中）                                                     |

### 5.4 导航范式统一（收敛 C-1）

**建议统一到「左导航 rail + 堆叠」，改造 `SettingsDialog`。**

理由（而非偏好）：

- SharingSettings 的配置页有 **8 个子分区**（`sharing_settings_dialog.py:379-387`），三层深度 QTabWidget 表达不了
- Settings 现有 6 页（`settings_dialog.py:279-1206`）已接近 tab 上限，且未来必然继续增页
- rail 的响应式已有先例：宽度 <800px 自动切顶部导航（`:216-224`），可直接复用

成本：`settings_dialog.py` 1939 行的页容器从 `QTabWidget.addTab` 改为 rail + `QStackedWidget`，页内表单逻辑不动。

### 5.5 按钮栏统一（收敛 C-2）

统一为 **右对齐 `取消 / 确定`**（Windows 与 Qt 惯例，也是绝大多数桌面应用肌肉记忆）。  
改动点：`tabbed_dialog.py:312-328`（改 1 处，影响 14 个子类）。

---

## 6. 路线图

### P0 — 高性价比，建议先做 ✅ **已于 2026-09-03 全部实施**

> **实施记录**：
> - ① `widgets/elevation.py` 新增 `shadow_params(level)` 数据契约。
> - ② `_grid_widget_render.py` `_draw_hover_shadow` 改读 `shadow_params(1)`：三层 alpha 18/28/36 → 由 canonical α72 按 0.25/0.39/0.50 派生，纵向扩散由 off_y 派生；视觉不变、数值源统一。实施时确认：阴影本就仅在 hover 时绘制（`:404,423`），原报告"常驻噪音"表述过重，实际问题是数值源脱钩。
> - ③ 卡片渐变底（heading α14→7）改为平色 heading α6，删除 QLinearGradient 用法。
> - ④ `plugin_ui.py:189`、`plugin_manager_dialog.py:120`、`startup.py:53,536,821-822` level 1→2。
> - ⑤ `tabbed_dialog.py` 新增 `_DialogButtonBar`（手工按钮条，stretch｜Cancel｜Apply｜OK，与 StandardModalDialog 完全一致），替换 QDialogButtonBox 并保留 `button/buttons/addButton/buttonRole/accepted/rejected` 兼容接口。实施前探针实测：本机平台 QDialogButtonBox 无任何 Role 组合可排出该顺序（RTL 也不行），故采用手工布局；视觉顺序已探针验证 `Cancel | Apply | OK` ✅
> - 验证：相关测试 **163 项全部通过**（dialogs 34 + 网格/启动器/插件/Toast 129），ruff 全绿。

| # | 动作                                           | 落点                                                    | 预估改动        | 收益                     |
| - | -------------------------------------------- | ----------------------------------------------------- | ----------- | ---------------------- |
| 1 | `elevation.py` 增 `shadow_params(level)` 数据契约 | `widgets/elevation.py:16` 附近                          | ~15 行新增     | 为自绘组件提供同一数值源（后续 2 的前置） |
| 2 | 网格阴影改读 `shadow_params`，并改为仅 hover/选中触发       | `_grid_widget_render.py:387,564-601`                  | ~40 行       | 消除 100 份视觉噪音 + 统一深度手感  |
| 3 | 网格卡片渐变底改平色                                   | `_grid_widget_render.py:479-491`                      | ~12 行       | 消除素材色彩污染               |
| 4 | 启用 elevation L2，重排既有使用点                      | `toast.py:131`、`plugin_ui.py:189`、`startup.py:42,525` | 4 处 level 值 | 补上缺失的中间层               |
| 5 | 按钮栏统一右对齐                                     | `tabbed_dialog.py:312-328`                            | ~16 行       | 消除误点风险，1 处改 14 个对话框    |

### P1 — 结构性收敛 ✅ **已于 2026-09-03 全部实施**

| #  | 动作                                | 落点                                                        | 预估改动           |
| -- | --------------------------------- | --------------------------------------------------------- | -------------- |
| 6  | SettingsDialog 改左 rail 导航 ✅        | `settings_dialog.py:163` + 6 处页注册                         | ~120 行（页内逻辑不动） |
| 7  | ImageViewerOverlay 圆角接 token ✅      | `image_viewer.py:861,867,889,906,957,996`（硬编码 10/8/4）     | ~6 处           |
| 8  | 自绘圆角裸值 4/5 归到 `radius_badge=6` ✅    | `_grid_widget_render.py:656-765`                          | ~5 处           |
| 9  | 分隔线语义统一（面板内 subtle / 面板边界 border） ✅ | `info.py:324`、`sidebar.py:1302`、`_base_layout.py:326,733` | ~4 处           |
| 10 | `theme_preview.py` 硬编码 hex 孤岛 ✅     | `:468-485`（11 个 hex，圆角回退 4/6/10 与 token 8/10 冲突）          | ~20 行          |
| 11 | 动效档位具名化，`themes` 增 `motion` 段 ✅     | `core/themes.py` properties + 4 处 duration                | ~25 行          |

**P1 实施记录（2026-09-03）**：

- **#6**：通过 `TabbedDialog._create_tab_container()` 工厂钩子（新增 ~10 行）注入 `_SettingsNavShell`（`settings_dialog.py`），实现 `addTab/setTabText/setStyleSheet/setCurrentIndex/currentIndex/tabText/count/widget` 兼容面 → 6 处 `_add_tab` 页注册、主题/语言/缩放刷新路径**零改动**。shell 复用 `StyleKit.nav_css()` 与 SharingSettingsDialog 同源（216px rail、checkable 按钮、36px 最小高度、宽 < 760 逻辑 px 时顶部导航回退）。测试中 `_tabs.setCurrentIndex/widget` 等直接调用已验证兼容。
- **#7**：6 处圆角改读 `themes.prop("border_radius", "sm"/"md")` 与 `themes.metrics("radius_xs")`——容器/页眉/页脚 10→`md`(10) 视觉不变，缩略条/EXIF 8→`sm`(8) 不变，关闭按钮 hover 4→`radius_xs`(3) 最近档归一。
- **#8**：文件夹图形 6 处裸值 4/5 → 新增 metric `radius_badge=6`（`themes.py` `_BUILTIN_METRICS`），网格侧以模块常量 `_BADGE_R` 引用。
- **#9**：实测仅 `info.py:324` 动作条用全强度 `border`，其余三处已是 `border_subtle` → 统一改 `sk.token('border_subtle')`。语义规则落定：面板内固定底栏/行分隔 = subtle，面板边界 = border。
- **#10**：13 个颜色回退从任意灰 hex 改为**当前激活主题**对应 token（部分编辑的预览继承一致色系）；圆角回退 4/6/10 → 8/10/14 对齐 `core/themes.py` canonical；swatch 回退 `#888888` → `themes.color(name)`。
- **#11**：`themes.py` 新增 `_MOTION_TIERS` + `motion()` API（micro=120/fast=150/normal=200/slow=300，主题可经 `properties.animation.<tier>` 覆盖，未知 key 回退 normal 并告警）；**9 处**固定 `setDuration` 全部具名化（计划写 4 处，实际清点 10 处，其中动量缩放 `:276` 为距离驱动按方案豁免）。

### P2 — 择机 ✅ **已于 2026-09-03 全部实施**

| #  | 动作                                        | 落点                                                                     |
| -- | ----------------------------------------- | ---------------------------------------------------------------------- |
| 12 | 树 QSS 抽公共 `tree_css()` ✅                | `sidebar.py:1254-1282` 与 `tag_tree.py:91-119`（几乎逐字符重复）                 |
| 13 | FileList 双工具带：Tier-2 可折叠 + 状态持久化 ✅    | `_base_layout.py:108,166`（单条合并否决：5 个下拉控件塞入 Tier-1 会挤压面包屑并超载密度） |
| 14 | Info 可见性真值收敛为 `_apply_section_visibility()` ✅ | `info.py:151-155` vs `info.py:932`（两套 UI 保留，真值函数唯一，顺带修复 tab 过滤态下菜单勾选状态误读 isHidden） |
| 15 | 补 `shortcut_manager.py` 缺失条目 ✅             | `shortcut_manager.py:24-27`（Ctrl+K/Ctrl+B/Ctrl+I 入种子；**勘误**：注释称"产品无此功能"过时，window.py:620-630 早已动态注册三者；仅 Ctrl+P 确实不存在） |
| 16 | QuickLook "毛玻璃" docstring 名实相符 ✅          | `quick_look_overlay.py:1-3` vs `:563`（择改文档而非加模糊采样，避免性能开销）     |
| 17 | ~~ImageViewerOverlay 补 reduce_motion~~ **误报** ✅ | `image_viewer.py` 实测**零装饰动画**（zoom 瞬时 transform、hover 即时变色、仅 2 个功能性 QTimer），无需改动 |

---

## 7. 明确**不建议**做的事

过度收敛会破坏现有优点，以下几条请务必不要动：

1. ❌ **不要强推所有组件走 StyleKit。** 自绘组件绕开它是**正确的性能取舍**（网格 200 条 LRU 纹理缓存、16ms QTimer 60fps）。正确做法是"参数来源统一"，不是"渲染方式统一"。
2. ❌ **不要为了统一把网格自绘改成 QSS/QGraphicsEffect。** 会直接摧毁滚动性能。
3. ❌ **不要动 `hit_area=24` 热区下限。** 这是扎实的无障碍基线，全项目 24px 下限 + `semanticIcon` 批量重画 + `setAccessibleName`/`setToolTip` 成对出现，属于值得保留的资产。
4. ❌ **不要给列表行加阴影。** `elevation.py:1-6` 的 docstring 明确说明"只作用于容器 widget，不作用于列表行"以避免滚动绘制开销——这个判断是对的。
5. ❌ **不要改 `image_viewer.py:282-288` 禁用 QOpenGLWidget 的决定。** 那里记录了两次半透明顶层窗口上的 `c0000005` 崩溃，是拿事故换来的结论。

---

## 8. 验收标准（可测）

| 指标                        | 当前              | 目标            |
| ------------------------- | --------------- | ------------- |
| `shadow_params` 覆盖的自绘组件   | 0 / 1           | **1 / 1**（网格） |
| elevation 档位实际使用数         | 2 / 3           | **3 / 3**     |
| 自绘圆角裸值处数                  | ~7（3/4/5/10）    | **0**         |
| 硬编码 hex（排除 theme_preview） | 22              | **≤ 11**      |
| 按钮栏顺序范式                   | 2 种             | **1 种**       |
| 设置中心导航范式                  | 2 种             | **1 种**       |
| 网格卡片常驻装饰层数（静态态）           | 4（渐变底+阴影+边框+徽章） | **≤ 2**       |

---

*本文件为设计提案，未修改任何代码。所有行号对应当前工作副本（2026-09-03）。*
