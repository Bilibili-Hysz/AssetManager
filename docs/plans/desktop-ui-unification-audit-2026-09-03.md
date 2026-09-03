---
title: "桌面端 UI 统一化审计报告（Design System 收口的事实基准）"
type: plan
status: LIVING
date: 2026-09-03
area: desktop-ui / design-system
owner: agent（六域并行审计 + 人工交叉核验）
supersedes: none
---

# 桌面端 UI 统一化审计报告（2026-09-03）

> **目的**：作为"桌面端统一模板方案（Design System 收口）"后续全部任务的**唯一事实来源**。由 6 个领域专家子代理并行审计 + 审查者交叉核验产出。所有发现带稳定 ID（`A/B/C/D/E/F-序号`），后续任务、提交与验证直接引用这些 ID。
>
> **事实基准**：工作树 @ master `c1187a2`（2026-09-03），含未提交的 UI 优化批次（并行会话的前端优化 + 审查者修复）。行号引用以该状态为准，迁移落地后由各批次提交刷新。
>
> **一句话结论**：观点成立——**"地基统一（token/缩放/图标/中央 QSS/主题 JSON 全部健康），上层方言化"**。token 体系无错拼、24 主题 JSON 完全一致、间距几乎全走 `scaled_px`；但同一概念在模板层存在 5-15 种手绘方言、官方组件"造而不用"、中央 QSS 有 10 处缺口、主题切换存在 4 处必然 stale 的 P1 缺陷、双层/三层标题栏并存。治理路线见 §五。

> **实施状态（2026-09-03，M0/M1 已落地）**
> - **M0 ✅**：`scripts/check_inline_styles.py` + `scripts/style_ledger.json`（G1 棘轮，基线 **253 处/40 文件**，AST 口径）上线并接入 CI lint 与 pre-push；`check_style_sources.py` 扩展（QColor-hex 常量规则 + `core/themes.py` 入扫面 + `_RULE_EXEMPT`/白名单机制）；新测试 `test_theme_qss_contract.py`（G4，23 主题契约）、`test_stylekit_snapshots.py`（G5，`STYLEKIT_SNAPSHOT_UPDATE=1` 再生）、`test_theme_visual_smoke.py`（G6 像素采样 + 主题往返）。
> - **M1 ✅**：hover/pressed 五套收敛为 HSV lighter(110)/darker(115)（color_utils 新增规范算法，中央表/button_css/tabbed_dialog/_links_page/info.py 全部对齐；danger `:pressed` 补齐）；info 主按钮文字色 heading→on_accent；主题切换 stale 修复（info 标签 chip 强制重渲、file_list 面包屑入 chrome 刷新、EmptyPanel 状态化 `_apply_style` + bus 订阅）；6 处 P1 未缩放尺寸（window/4 dialogs/batch_rename）；`PANELS` 移除不可达的 `file_list_tabs`（tab_container 转为 M2 决策项）；`dock_factory.request_refresh()` 公共化并替换 window.py 手绘 dock QSS 路径；`themes.prop/color` 缺键告警。
> - **核实修正**：**B2①（StartupWindow.refresh_theme 未接线）不成立**——`startup.py:432` 的 `__init__` 已连接 `theme_changed`，无需修复。其余 B2②③④ 属实并已修复。
> - **M0 期间发现并修复**：未提交的 `micro_tab_bar.py` 携带 7 处虚构 hex fallback（`#8a94a6` 等，无任何主题使用该值），令 D4 门禁红 10 项——已改为直接 token 访问（合并主题保证键齐备）。
> - **待办**：M2（工厂补全/token 升格/孤儿回收/插件 UI 合并/SimpleDialog）→ M3（分批迁移 B1-B8）→ M4（收口）。
>
> **复检（2026-09-03，M0/M1 落地后重跑首审量化）**
> - **已消除**：主按钮 hover/pressed 5 套→1 套（HSV lighter/darker，复检全部命中新配方，残余 alpha hover_overlay 均为 ghost/secondary 语义）；主题切换必然 stale 3 处修复在位（info chip/面包屑/EmptyPanel 复检 grep 命中）；双层/三层标题路径移除；6 处 P1 未缩放尺寸缩放；dock 手绘 QSS 漂移路径删除；micro_tab_bar 虚构 hex fallback 清零（D4 门禁红 10→0）；palette 死代码移除（URL 契约恢复）；中央 QSS 补 danger:pressed（缺口 10→9）。
> - **仍成立（M2/M3 挂账）**：token 方言 border-radius 23 形态 / font-size 33 形态（较首测略增——并行会话新代码继续加别名，收敛必须靠 M2 强制点）；setStyleSheet 253/40 冻结待迁；danger 变体仍 0 调用（算法已统一，属性迁移在 B4 批）；孤儿 collapsible_panel/status_indicator 原样 + **tab_container 因 PANELS 收缩成为新孤儿（M1 预期代价）**；StyleKit 工厂利用率、空状态 6 写/分组标题 3 写/胶囊 4 写、对话框双轨（无 variant 按钮栏、PluginManagerUI 双实现）、PanelContent 死扩展点 6 个、度量漂移（icon 15/16、热区 20/22/26）、中央 QSS 其余 9 缺口、P2 stale（sharing 三页等）——全部未动，属结构性收敛。
> - **无新增违规**：M1 新代码（EmptyPanel 重构/request_refresh/信息重渲）均走规范姿势（_connect_bus/StyleKit 工厂/插值 token）。

---

## 一、头条数字（2026-09-03 实测）

| 指标 | 值 | 口径 |
|---|---|---|
| presentation 层 `setStyleSheet` | **262 处 / 40 文件** | panels/dialogs/widgets + window/window_coordinator/dock_factory；info.py 49、startup.py 44、plugin_manager_dialog 20、sharing_settings 18、_plugin_manager_widget 15 |
| token 访问方言 | **13 种** | `t[...]`×255、`t.get`×88、`themes.get()`×55、`sk.token/sk.t()`×107、`themes.color`×8，加 8 种派生形态（§B3） |
| 主按钮 hover/pressed 实现 | **5 套** | 中央 alpha(0.88/0.72)、stylekit.dialog_css(HSV lighter110/darker115)、tabbed_dialog(0.85/115)、stylekit.button_css(hover_overlay/0.18)、_links_page(0.87/0.18)——量化色差 ΔRGB≈(23,26,39)，肉眼可辨（§B4） |
| 空状态实现 | 6 种 | EmptyPanel + 5 处手绘（§C2d） |
| 标签胶囊/徽章实现 | 4 种 | TagChip + 3 处手绘（§C2b） |
| 标签页范式 | 4 种 | QTabWidget / TabContainer / WorkspaceBar / MicroTabBar（§C2c） |
| 孤儿/生产死码 | **~590 行** | collapsible_panel(104) + status_indicator(201) + tabbed_dialog._CollapsibleSection/make_collapsible（仅测试调用）+ EmptyPanel.for_loading/for_error + StyleKit 5 个死工厂 |
| PanelContent 死扩展点 | 6 个 | status_hint/_context/set_title/retranslate_ui/refresh_visual_settings/apply_app_settings 全库 0 调用（§A3） |
| 主题切换必然 stale | **4 处 P1** | StartupWindow.refresh_theme 未接线、info 标签 chip 极性、file_list 面包屑、EmptyPanel 构造期烘焙（§B2） |
| 中央 QSS 缺口 | 10 项 | QHeaderView 系/QSpinBox 按钮/QComboBox 箭头/checkbox 勾选图/输入 :disabled/QTreeView::branch/QPushButton:checked 等（§B1） |
| 未缩放像素 P1 | 6 处 | window.py:169 `resize(1200,800)` 等（§E2） |
| 双层/三层标题栏 | 1+1 | file_list 停靠双层；TabContainer 路径三层（§A6） |
| 对话框无 variant 按钮栏 | 8 个 | OK 与 Cancel 视觉无法区分主次（§D2） |
| 已有可复用资产 | 4 项 | `check_style_sources.py` 门禁已存在、`test_stylekit._render_bytes()` 像素基建、TabbedDialog 几何记忆、`buttonVariant` 机制 |

---

## 二、六域审计发现（任务来源索引）

### 域 A · 骨架与镀铬层（PanelContent / dock_factory / 主窗装配）

主窗装配实况：菜单为自建 QWidget 行内嵌 `setNativeMenuBar(False)` 的 QMenuBar（window.py:524-568）；**无任何 QToolBar**；FileListPanel 直接作中央部件不经 dock（window.py:572）；布局持久化**不用** saveState/restoreState，只存 dock 宽度。

- **A1 (P1)** file_list 内部 `_header`（_base_layout.py:107-115）与 dock 标题同文"文件列表"，停靠即双层、TabContainer 路径三层（dock 标题 + extension QTabBar + 内部 header）。→ 入 dock 去内部 header；最小改动=从 PANELS 移除 `file_list_tabs` 不可达条目。
- **A2 (P1)** InfoPanel 底部 actions bar 不在 `__init__` 布局中，全靠 `dock_factory._attach_footer`（dock_factory.py:103,108-112）副作用补挂——脱离工厂即布局残缺。→ footer 挂载收进 PanelContent 显式钩子。
- **A3 (P1)** dock chrome 存在第二条主题刷新路径：window.py:388-399 手动 setStyleSheet，圆角硬编码 7px、边框用 `border` 而非 `border_subtle`，与 `_build_title_bar` 漂移（同一 dock 换主题前后圆角 7↔10 跳变）。→ 删 window 侧路径，并入 bus 合并刷新。
- **A4 (P2)** 克隆/插件 dock `i18n_key=""`（dock_factory.py:82,101,261-262），语言切换后标题永不重译。
- **A5 (P2)** 插件 dock 卸载（window.py:1343-1350）不清 `_DOCK_TITLES`，死键滞留。→ 抽 `dock_factory.unregister()`。
- **A6 (P2)** 标题栏按钮跨刷新复用实例，tooltip/accessibleName 永不重译（dock_factory.py:94-101,263）。→ 存按钮规格而非实例。
- **A7 (P2)** `title_bar_buttons` 默认返回通用设置齿轮（base.py:114-134）——"缺省即有行为"掩盖契约。→ 默认返回 `[]`。
- **A8 (P2)** PanelContent 6 个死扩展点 + 各面板各自直连 bus。→ 删死 API，把 `on_language_changed/on_theme_changed` 固化为模板方法。
- **A9 (P2)** base.py:40-59 showEvent 入场动画对停靠子部件无效（自注释承认）且无 reduce_motion。→ 删或改 QGraphicsOpacityEffect。
- **A10 (P2)** PANELS 注册表 6 项中 4 项主窗从不挂载（tag_tree 仅对话框、viewer 浮窗、empty 死 fallback）。→ 注册表收缩或标注 mount 语义。
- **A11 (P2)** `title_bar_extension` 唯一实现（tab_container.py:48-67）主窗不可达。→ 激活或暂删。
- **A12 (P2)** dock 浮动/隐藏/关闭状态不记忆，关闭面板会话内不可恢复。→ 改用 saveState/restoreState + 恢复菜单。
- **A13 (P3)** image_viewer 自绘 HUD 无障碍缺失、语言切换无主动重绘（image_viewer.py:314-1104）。
- **A14 (P3)** 齿轮按钮构造四处近似复制（base.py:129-131/info.py:876-885/sidebar.py:1371-1383/dock_factory.py:150-155）。→ 抽公共工厂。
- **A15 (P3)** dock 标题 QLabel 无 accessibleName（dock_factory.py:132）。

### 域 B · 样式引擎（themes.py / StyleKit / token 方言 / 主题刷新链路）

- **B1 (P2)** 中央 QSS 缺口 10 项：QSpinBox::up/down-button 与箭头、QComboBox::down-arrow、QCheckBox/QRadioButton checked 无勾选图（纯色块）、输入类 `:disabled` 全缺（dialog_css 反而已有——中央落后于局部）、QTreeView::branch、QPushButton:checked、QScrollBar::handle:pressed、QToolTip 无字号、QMenu::separator/:disabled、QStatusBar 非 window 场景无来源。QPlainTextEdit/QDoubleSpinBox 全库 0 使用，纸面缺口可暂缓。缺口被各点手抄补偿：QHeaderView 在 _base_layout.py:655 与 _ui.py:25 两份近重复手写。
- **B2 (P1×4 + P2×6) 主题切换必然 stale**：①`startup.py:815` refresh_theme **定义了但从未连接** theme_changed（唯一连接在 :432 且只挂一张卡片）——StartupWindow 切主题后 hero 渐变/列表渐变/背景全部停留旧主题；②info 标签 chip 背景极性依赖 `is_dark()`（tag_chip.py:81）但 `_render_tags` 不在 `_refresh_theme` 链内——深浅切换后 chip 混合极性错误；③file_list 面包屑 `_render_bc` 仅由导航触发，`_apply_chrome_style` 只刷导航按钮（_navigation.py:306-351 vs _base_layout.py:325-337）；④EmptyPanel 五段 QSS 构造期烘焙（empty.py:23-84），dock 刷新只重建标题栏。P2：sharing 三页（endpoint/links/access）无刷新路径、color_picker/tag_style 无订阅、window_coordinator.py:93 分享进行中 accent 状态被重置吞掉。
- **B3 (P2) token 方言 13 种**：在 5 种访问方言之外，`themes.prop()` 直读 font_size 约 32 处绕过带 0 值保护的 `themes.font_size()`（prop 缺键返回 **0** → 自定义主题缺键会生成 `font-size: 0px`，themes.py:423）；`themes.prop`（无默认）与 `StyleKit.prop`（默认 0）双签名分裂；micro_tab_bar.py:401 虚构 fallback `#8a94a6`（无任何主题此值）；theme_preview.py:462-464 圆角 fallback 4/6/10 vs 实际 8/10/14（预览保真度打折）；`themes.color()` 缺 token 返回空串 → `color: ;`。
- **B4 (P1) 主按钮 hover/pressed 5 套算术**：alpha 半透明（结果依赖堆叠背景）vs QColor.lighter/darker（HSV V）vs color_utils.lighten/darken（HSL L）——Navy accent 实测 hover 三色 #5371d8 / #6a8bff / #7994f3，pressed #4961b8 vs #345dec；button_css 的 pressed `alpha(accent,0.18)` 语义（暗 overlay）与"更深的 accent"不同构。→ 收敛为不透明的 lighter/darker 一套。
- **B5 (P2) danger 变体死代码**：中央与 stylekit 均已定义、`allowed` 集合含 danger（themes.py:432），但 0 调用；危险语义由 _links_page.py:175 手绘 alpha(0.87) 双轨实现。set_button_variant 分布：ghost 11/primary 6/secondary 5/**danger 0**。
- **B6 (好消息)** 23-24 个主题 JSON colors 键集逐一 diff **全部等于 26 键基线，无缺键无错拼**；代码访问名全部落在 merged 集合内——掩盖风险是"默认值漂移"而非"键名漂移"。缺一个 JSON schema 校验（多键会被静默接受）。
- **B7 (P2, I3 新发现)** dialog 级 QSS 的 `QPushButton:focus { border: 2px solid border_focus }` 规则在 variant 属性按钮（primary/secondary）上不产生可见焦点像素（offscreen grab 实证：聚焦前后字节一致），而 widget 级 QSS 按钮（gear）可见——键盘用户在对话框里无法看到 variant 按钮的焦点位置。另：`border_focus` token ≈ accent，画在 accent 底的主按钮上环不可见（对比度问题）。M2 需查明 QSS 级联归属并改用对比色环。

### 域 C · 组件复用与孤儿（widgets/ 16 模块）

结论：**组件库的问题不是缺抽象，而是"写好了没接线 + 同款手绘绕开组件库"**。4555 行中约 305 行纯死码，stylekit 另约 80 行 0 调用 API；真实复用仅 stylekit/tag_chip/toast/elevation/tab_container 五件。

- **C1 (P1) 孤儿与死码**：collapsible_panel.py 整文件 0 引用 0 测试；status_indicator.py 生产 0 引用（仅测试，且它是 stylekit `state_icon`/`make_pulse` 唯一消费者）；**tabbed_dialog._CollapsibleSection(:79-156) + make_collapsible(:589) 也是生产死码**（唯一调用是测试）；EmptyPanel.for_loading/for_error（empty.py:60/74）0 调用；StyleKit 死工厂 make_status_badge/make_pill_button/make_fade_in/make_fade_out/state_css。→ 与手绘方二选一收敛，勿两份都留。
- **C2 (P2) 重复实现对账**：(a) CollapsiblePanel vs _CollapsibleSection 差异明细——头高 32 vs 28、有无动画、有无 :focus、有无缩放刷新（后者更完整，宜以其为基线反向补动画）；(b) 胶囊三处手绘（plugin_manager:292 / startup:166-175 自制 `_interpolate_color` 配方 / tabbed_dialog:649-655 status_style——**参数与 stylekit.state_css 逐 token 相同，等于重写了一遍**）→ 统一 `state_css`/复活 `make_status_badge`；(c) info.py:236-293 四个工具按钮同一 QSS 块**逐字复制 4 遍**（唯一差异 dashed/solid）→ 抽 `_ghost_tool_btn` 或扩 `button_css(dashed=)`；(d) 空状态 6 写 → sidebar/info 收敛到 EmptyPanel 骨架；(e) 滑动指示器双实现（workspace_bar.py:214-262 vs micro_tab_bar，同 200ms/OutCubic）→ 抽公共 mixin；(f) startup._interpolate_color 与 color_utils 数学不同（混白黑 vs 乘系数），tag_style_dialog._contrast_text 与 tag_chip.py:30 双胞胎 → 归 color_utils。
- **C3 (P2) 瞬时回执 vs 常驻状态分界规则化**：Toast（2 调用者）vs 各面板常驻状态条 vs undo/activity 内联文本——建议规则"瞬时回执→Toast、持续状态→状态条"，undo/activity 错误行改用 state_css 级 token。
- **C4 (P3)** plugin_manager_dialog.py:301 与 _plugin_manager_widget.py:299 `_add_field` 双写；info.py `_group_css` 与 stylekit.dialog_css QGroupBox 段平行（差 border_subtle）；sharing_contracts.py 放置错位（QMessageBox 业务流程件在 widgets/）；单调用者大组件（micro_tab_bar 567 行/theme_preview 714/workspace_bar 442）下次需求先复用再新建；底部按钮栏 QDialogButtonBox 与手排并存（建议非 TabbedDialog 的 QDialog 统一 QDialogButtonBox）。

### 域 D · 对话框体系（23+ 模块普查）

- **D1 (P1) 主按钮 5 套悬停/按下**（§B4 同源）：中央/ dialog_css/ tabbed_dialog.primary_btn_style/ stylekit.button_css/ _links_page 各一套。
- **D2 (P1) 8 个对话框按钮栏无 variant**——OK 与 Cancel 都是 accent 实色：color_picker:105-113、tag_style:92-100、theme_preview:44-60、_batch_rename:48-52、plugin_operator:57-62、generic_settings:26-28（连 Close 都 accent）、sidebar_settings:145-152、**sharing_settings_dialog:185-191（主对话框自己的 OK/Apply/Cancel）**。→ 统一 `themes.set_button_variant`。
- **D3 (P1) 双重造型 3 处**：plugin_manager_dialog.py:232 set variant 后 :259 整段 setStyleSheet 覆盖（variant 成死属性）；_plugin_manager_widget.py:209+236 复制同款；tabbed_dialog.py:552-559 make_gear_btn 先 ghost 后覆盖。
- **D4 (P1) danger 0 使用 + 4 处手绘危险**（_links_page:171-177 删除链接、startup:172-175 状态 chip、tabbed_dialog:663、plugin_manager 诊断框×2 份复制）。→ danger 变体落地。
- **D5 (P2) TabbedDialog 模板契约不对称**：`_setup_tabs` 分支自动 `setStyleSheet(self._dialog_qss())`（:181-184），`_build_ui` 分支要求子类自己调（8 处手动）——ShareQrDialog 漏调，成为唯一吃全局 QSS 的子类（输入框 padding/焦点边框 1px vs 2px 细节不同）。→ `__init__` 无条件应用，删 8 处重复。
- **D6 (P1) PluginManagerUI 双实现**：plugin_manager_dialog.py 与 _plugin_manager_widget.py 两份近乎复制的 PluginCard/PluginDetailPanel/主类（分别服务独立窗口与 settings 内嵌页），连 danger 诊断框 QSS 都是复制粘贴。→ 抽共享组件到 widgets/。
- **D7 (P2) startup 独立王国**：QMainWindow 非模态 show、不享 TabbedDialog 的几何记忆/淡入/总线（自己连 bus）；本地 `_interpolate_color`；状态 chip 配方自创；标题排版 xxs+letter-spacing vs make_heading 的 accent 下划线；Browse 按钮手绘轮廓不对应任何 variant；菜单栏整段手绘。token 复用本身是好的，漂移集中在"组件配方"。
- **D8 (P2)** 几何记忆只有 TabbedDialog 有（原生 QDialog 系零记忆：batch_rename resize(620,400) 固定等）；模态性三态并存无文档（exec/WindowModal/非模态）；两个单页 TabbedDialog 无关闭按钮无约定；SettingsDialog 为 DPI 重算 min-size 自造双份状态（模板缺"逻辑 min_size + 缩放重算"一等支持）。
- **D9 (P3)** dialogs/__init__.py 模块清单严重过时；tag_editor 变量名 danger 实为维护区（语义与视觉错位）；theme_preview 3 处原生 QInputDialog。

### 域 E · 度量网格与高 DPI

- **E1 分布**：`scaled_px` 883 处。主频 1(×100 边框)/16(×98 图标)/12(×92)/4(×68)——但 **6(×62)/15(×60)/14(×45)/10(×39)/2(×36) 大量游离于 spacing token（4/8/12/16/24）之外**，双体系未吸附。
- **E2 (P1×6) 未缩放像素**：window.py:169 `resize(1200,800)` 主窗首启尺寸；share_link_dialog.py:51 / share_qr_dialog.py:36 / activity_panel.py:78 / undo_panel.py:64 的 `min_size=` 未 scaled；_batch_rename_dialog.py:32 resize(620,400)。→ 照抄 settings_dialog `_logical_min_size` × scaled_px 模式。P2：tray.py 全固定像素（QPixmap(32,32)/setPixelSize(20)）、_grid_widget.py:140 setMinimumSize(100,100)。
- **E3 (P3) 缩放算术误用** 9 处（theme_preview `scaled_px(12)-1`、workspace_bar `max(2.0, float(scaled_px(3)))` 钳制混算等），无 P1/P2 级误用。
- **E4 (好消息) 24 主题 properties 全量一致**：border_radius{8,10,14,20}/spacing{4,8,12,16,24}/font_size{9,10,11,12,13,14,16,22}/animation{200} 24/24 相同；代码 296 处 `themes.prop` 访问 11 种组合全部存在于 JSON，**无 typo**。休眠 fallback 当前值恰好等于 JSON 值。
- **E5 (P2) 门禁逃逸**：check_style_sources.py 不扫 core/themes.py——中央表自带裸 `width: 6px`（:577-578）与 `border-radius: 3px`（:582，未缩放非 token）逃逸。**P2**：`themes.prop`/`StyleKit.prop` 缺键静默返 0（拼错 token 会以 0px 落地无告警）。**P3**：死 token（border_radius.xl、spacing.xl、font_size.xxs/xxl、opacity.disabled、animation.duration_ms 定义后 0 引用，而 15 处 `setDuration(100~300)` 手写）；字号双轨（11 处手写 scaled_pt 8-12 绕过 token）；dock 标题圆角 7 vs 10 漂移（window.py:396 vs dock_factory.py:118）。
- **E6 token 升格建议表**：`metrics.icon_sm`=16（现值 15/16 混用）、`metrics.icon_xs`=12、`metrics.hit_area`=24（现 20/22/26 三档）、`metrics.control_height_md`=28（事实标准已存在仅缺名）、`radius_xs`=3、`font_size.micro`→并入 xxs=9、`animation.duration_fast/slow`=100/300、spacing 档间值（2/6/10/14，~180 处）逐步吸附。

### 域 F · 门禁与迁移策略

**关键发现：样式静态门禁已存在**——`scripts/check_style_sources.py`（299 行，D4）：扫 panels/widgets/dialogs + 3 根文件，禁本地 QSS hex/命名色/字面 font-size/未缩放 px，豁免 stylekit，内置 `_PX_WHITELIST`（现仅 workspace_bar "0px"），能识别 f-string（插值内数据驱动 hex 放行——theme_preview 色板因此通过）；已挂 pre-push 与 CI lint；有守护测试 test_style_sources.py。

- **F1 (基建) 现有测试的样式断言**：11 个 desktop 测试文件触及 stylesheet；强度弱（子串包含）到强（test_stylekit.py:184-240 `_render_bytes()` grab 像素字节比较、test_micro_tab_bar.py:277-300 offscreen grab）——**像素回归基建已被验证可行**。缺口：无 golden 快照、无跨主题矩阵、无中央 QSS 覆盖契约、无 setStyleSheet 棘轮。
- **F2 CI 结构**：`test` job（ubuntu × 3.12/3.13/3.14，QT_QPA_PLATFORM=offscreen 顶层 env）跑含 tests/desktop 全量；lint job 跑 11 个静态门禁；pre-commit 快层 <2s（ruff），重层 pre-push 镜像架构门禁。
- **F3 门禁方案**（G1-G7，可行性/工作量/挂点/时机详见原审计）：
  - **G1 `check_inline_styles.py`（M，现在就能写）**：setStyleSheet 棘轮 + ledger（`scripts/style_ledger.json`，文件级计数只许降；迁移完成后退化为纯禁令）。模板：check_frontend_data_fetch.py。
  - **G2 扩展 check_style_sources（S-M，现在就能写）**：补 QColor/hex 常量语境规则 + 把 core/themes.py 纳入扫描面（堵 E5 逃逸）。
  - **G3 token 方言收敛（M，依赖 M2 前置重构）**：禁 presentation 直接 `t[...]`/import color_utils；前置=StyleKit `_alpha/_lighter/_darker` 公共化 + 255 处 `t[...]` 迁 `sk.token()`。过渡期可"冻结新增"。
  - **G4 中央 QSS 覆盖契约测试（S，现在就能写）**：断言 stylesheet() 含关键选择器清单 + 引用 token 键存在 + 中央 QSS 内零 hex。
  - **G5 StyleKit 工厂输出快照（S，现在就能写）**：各 `*_css()` 文本快照，有意变更才更新。
  - **G6 offscreen 主题截图回归（M，现在就能写）**：token 色采样断言（grab 后 Pillow 采样已知坐标 ≈ token 解析值，跨平台稳定）+ 主题往返自比断言。**勿做跨平台字节级 golden**（字体渲染抖动必然失败）。
  - **G7 24 主题 × 关键对话框矩阵（M，G6 后）**：marker 化默认 deselect，CI 独立 step。
- **F4 迁移批次**（262 处，大文件独占 + 同族同批 + 高风险基座靠后 + shell 最后）：B0 门禁基建 → B1 info(49) → B2 startup(44) → B3 插件族(35) → B4 分享族(35) → B5 对话框基座族(19，tabbed_dialog 风险最高靠后) → B6 面板族(28) → B7 micro widgets 长尾(21) → B8 shell+零头(23，含 theme_preview 永久豁免候选)。每批固定回归：desktop 测试绿 + check_style_sources 0 违规 + 棘轮下降 + G6 采样 + G5 快照。

---

## 三、治理路线（修订版 Design System 收口，四个里程碑）

> 与未采纳草案的差异：**不锁字面像素值，锁 token**（E6）；**先补工厂再立禁令**（避免大爆炸）；增加"止血接线"先行（B2 的 4 个 P1 是用户可感知 bug，不等重构）；补齐草案遗漏的方言收敛（B3）、孤儿回收（C1）、验证手段（F3）。

### M0 · 门禁与回归基建（纯增量，零行为变更）
G1 棘轮脚本（基线 262）｜G2 扫描面扩展｜G4 中央 QSS 契约｜G5 工厂快照｜G6 采样冒烟。产出：后续每一批改动都有回归网。

### M1 · 止血接线（小改动、用户可感知收益，不动架构）
1. startup.refresh_theme 接 theme_changed（B2①，一行）｜2. info `_render_tags` 入主题刷新链（B2②）｜3. file_list 面包屑重刷（B2③）｜4. EmptyPanel 补 refresh_theme（B2④）｜5. `set_button_variant(danger)` 落地替换 _links_page 手绘（B5/D4）｜6. 主按钮 hover/pressed 收敛为 lighter/darker 一套（B4/D1，删 4 套并存）｜7. 6 处 P1 未缩放尺寸（E2）｜8. 双层标题处理：PANELS 移除 file_list_tabs + file_list header 降级为中央部件模式专用（A1）｜9. dock 标题圆角 7→border_radius.md（A3/E5）｜10. `themes.prop` 缺键 0 改告警（B3/E5）。

### M2 · 工厂补全与 token 升格（结构收敛前置）
1. StyleKit `_alpha/_lighter/_darker` 公共化，color_utils.lighten/darken 标记 deprecated 代理（B4/C2f）｜2. 补工厂：button 全变体含 dashed/hover 参数、input、groupbox（含 hairline 变体）、chip/status badge（复活死工厂）、state｜3. 中央表补 B1 十缺口（QHeaderView 先行，删两份手抄）｜4. metrics token 升格（E6 表）+ 死 token 决策｜5. `themes.font_size()` 替换 32 处 prop 直读（B3）｜6. 孤儿回收：collapsible_panel 二选一合并、status_indicator 接入或删（连带 state_icon 决策）、EmptyPanel 工厂决策（C1）｜7. PanelContent 插槽契约：header 规范/footer 显式化/title_bar_buttons 默认 []/bus 模板方法/死 API 删除（A2/A7/A8）｜8. TabbedDialog.__init__ 无条件 _dialog_qss + SimpleDialog 轻模板 + 8 个无 variant 对话框迁移（D5/D2）｜9. PluginManagerUI 合并（D6）｜10. startup 配方回归共享层（D7）。

### M3 · 分批迁移（F4 批次表 B1→B8）
按批迁移 setStyleSheet → StyleKit 工厂/中央表，每批走 F4 固定回归清单。

### M4 · 收口
ledger 清空、G1 退化为纯禁令｜G3 方言强制上线｜G7 主题矩阵入 CI｜A12 saveState/restoreState 布局记忆｜image_viewer 最低限度接入（A13，可延后独立排期）。

---

## 四、验证与验收

- 每里程碑：`pytest tests/desktop tests/unit/test_style_sources.py` 绿 + `check_style_sources.py` 0 违规 + 棘轮不升 + G6 采样冒烟 + 相关域专项测试（A→test_dock_factory/test_window 组装；B→test_theme_qss_contract；C→组件专项；D→test_tabbed_dialog_visuals/test_settings_*；E→缩放回归）。
- M1 完成判据：主题切换 stale 清单清零（4 个 P1 复现路径手测通过）。
- M4 完成判据：presentation 层 setStyleSheet 仅剩 ledger 空豁免（theme_preview 类数据驱动件）；方言 13→≤4 种（t[...]经 sk.token、themes.prop/color、QPainter QColor 缓存、渐变构造）。

## 五、审计方法与可信度

六个领域子代理并行只读审计（骨架镀铬/样式引擎/组件复用/对话框/度量/门禁），全部结论带 file:line；审查者对上一轮报告的失实数字做过纠正（"42 处 setStyleSheet"实为 257→现 262；"StyleKit 仅 3 文件零星使用"实为 21-22 文件引用但工厂利用率低；make_pill_button/make_status_badge 为 0 生产调用）。两组"好消息"（主题 JSON 一致性、无错拼 token）经独立脚本比对证实。行号会随后续提交漂移，以发现 ID 为准回溯。

---

## 六、长期目标与迭代计划（Design System 收口，LIVING）

> 本节把 §三 的 M0-M4 路线固化为**可持续多会话的迭代计划**。每个迭代单元刻意保持小体量、独立可交付、门禁常绿——一次会话做一个迭代，做完即收。

### 6.1 北极星（North Star）

> **桌面端任何控件的外观只有一个产地（StyleKit 工厂或中央主题表）；任何颜色、字号、尺寸只有一个来源（token）。**

### 6.2 完成定义（Definition of Done，全部可测量）

| # | 判据 | 度量方式 |
|---|---|---|
| DoD-1 | presentation 层 setStyleSheet → 0 | G1 棘轮 ledger 清空（基线 253/40） |
| DoD-2 | token 方言 ≤4 种（sk.token/alpha/lighter/darker、themes.prop+color、QPainter QColor 缓存、渐变构造） | ✅ 零容忍纯禁令生效，setStyleSheet 段内 t 直访清零 |
| DoD-3 | 同一概念单一实现：空状态/胶囊/徽章/分组/按钮行/标签页各一个规范来源 | 孤儿清零 + 复检 grep |
| DoD-4 | 中央 QSS 缺口清零（QHeaderView 等 9 项） | G4 契约选择器清单扩展 |
| DoD-5 | 度量 token 化：icon/hit_area/control_height/radius/animation 全走 token | 复检 grep（15/26/22/28/3 漂移值清零） |
| DoD-6 | 对话框单一模板契约：TabbedDialog 自动 QSS + SimpleDialog 轻模板，无 variant 按钮栏清零 | 复检 grep + danger 变体 >0 调用 |
| DoD-7 | 验证基建常驻：G1-G7 门禁全绿 | CI + pre-push |

### 6.3 迭代单元（按依赖排序；每个 ≤ 一次会话体量）

| ID | 范围 | 关联发现 | 验收 |
|---|---|---|---|
| ~~I0~~ | ~~M0 门禁基建 + M1 止血~~ | ~~B2/B4/D1/E2/A1/A3~~ | ~~2026-09-03 完成~~ |
| **I1** | StyleKit 派生 API 公共化（`sk.alpha/lighter/darker`），弃用 `_` 私名，迁移 tabbed_dialog 调用点 | B4/G3 前置 | ruff+测试绿；快照不变；`sk._alpha` 外部调用清零 |
| I2 | 度量 token 升格：经 `_BUILTIN_EXTENDED_FALLBACK` 机制新增 `metrics`（icon_sm=16/icon_xs=12/hit_area=24/control_height=28/radius_xs=3），themes 加 `metrics()` 访问器；迁移 dock_factory(15→16)、sidebar(26→24)、workspace_bar(22→24) | E6 | 复检漂移值清零；门禁绿 |
| I3 | 孤儿回收：collapsible_panel 与 `_CollapsibleSection` 二选一（以后者为基线反向补动画）；status_indicator/tab_container 接线或删除（连带 stylekit.state_icon/make_pulse 决策） | C1 | 孤儿 grep 清零；测试同步 |
| I4 | 中央 QSS 缺口补齐：QHeaderView::section（删 _base_layout/_ui 两份手抄）、QSpinBox 按钮、QComboBox::down-arrow、输入 :disabled、QTreeView::branch、QPushButton:checked | B1 | G4 选择器清单扩展后绿 |
| I5 | PluginManagerUI 双实现合并到 widgets/（PluginCard/PluginDetailPanel 共享） | D6 | 两容器行为等价；插件族测试绿 |
| I6 | TabbedDialog 契约对称（`__init__` 无条件 `_dialog_qss`，删 8 处子类重复）+ SimpleDialog 轻模板 + 8 个无 variant 按钮栏迁移（danger 变体落地） | D2/D5/D3 | danger 调用 >0；share_qr 底板归队 |
| I7 | 死 API/死工厂清理：PanelContent 六个死扩展点删除、bus 模板方法固化；StyleKit 死工厂接线或删除 | A8/C1 | grep 清零 |
| I8 | 迁移批 B1：info.py（49 处）→ StyleKit/中央表 | F4/B1 | 棘轮 -49；desktop 测试绿 |
| I9 | 迁移批 B2：startup.py（44 处） | F4/B2 | 棘轮；G6 采样 |
| I10 | 迁移批 B3+B4：插件族（35）+ 分享族（35） | F4 | 棘轮；分享测试 |
| I11 | 迁移批 B5-B8：基座/面板/长尾/shell（83） | F4 | 棘轮；ledger 清空 |
| I12 | G3 方言门禁上线（禁 t[...] 直访/color_utils 直 import；255 处 t[...] 迁 sk.token） | F3/G3 | 门禁绿 |
| I13 | 收口：G7 24 主题矩阵入 CI；A12 saveState/restoreState 布局记忆；image_viewer 最低接入（A13，可独立排期） | A12/A13/F3/G7 | DoD 全表核验 |

### 6.4 进度账本

| 迭代 | 状态 | 完成日 | 证据 |
|---|---|---|---|
| I0（M0+M1） | ✅ | 2026-09-03 | 门禁 G1-G6 全绿；棘轮 253/40 冻结；复检 §实施状态 |
| I1 | ✅ | 2026-09-03 | `sk.alpha/lighter/darker` 公共化 + 别名弃用注记；tabbed_dialog 6 处外部私名调用清零；快照不变 |
| I2 | ✅ | 2026-09-03 | `themes.metrics()` + `_BUILTIN_METRICS`（icon_sm=16/icon_xs=12/hit_area=24/control_height_md=28/radius_xs=3，主题可经 properties.metrics 覆盖）；dock_factory 图标 15→16、热区 20→24；sidebar 26→24；workspace_bar 22→24；漂移值复检 grep 清零；G4 增 metrics 契约；779 desktop/unit 测试绿 |
| I3 | ✅ | 2026-09-03 | 删除 `widgets/collapsible_panel.py`（104 行 0 引用）、`widgets/status_indicator.py`（201 行生产 0 引用）及其测试；删除 tabbed_dialog `_CollapsibleSection`/`make_collapsible`（生产死码）及主题/缩放刷新链两处残留引用；stylekit 删除 `make_pulse`/`state_icon`（级联孤儿）；tab_container 保留（有测试，A11 认可的 M2 停靠样板，激活/删除留 M2 决策）。**新发现 B7**：dialog 级 QSS 的 `QPushButton:focus` 规则在 variant 按钮（primary/secondary）上不产生可见焦点像素（offscreen grab 实证），仅 widget 级 QSS 按钮（gear）可见——M2 需查明 QSS 级联归属并修复 a11y。棘轮 253→246/40→38 |
| I4 | ✅ | 2026-09-03 | 中央 QSS 补 6 类安全缺口：QHeaderView::section（+hover/sort-arrow 尺寸；删除 _base_layout 与 _ui 两份手抄）、输入类 `:disabled`、QMenu::separator + item:disabled、QScrollBar handle `:pressed`（×2 方向）、QToolTip 字号、QPushButton:checked（置于变体块后赢得同特异性竞争）。**缓期（需箭头/勾选图标素材，QSS 化子控件后原生 glyph 会消失）**：QSpinBox 上下按钮与箭头、QComboBox::down-arrow、QCheckBox/QRadioButton checked 勾选图、QTreeView::branch。G4 清单 +4 选择器。棘轮 246→245 |
| I5 | ✅ | 2026-09-03 | **PluginManagerUI 双实现合并**：新建 `widgets/plugin_ui.py`（PluginCard + PluginDetailPanel 规范实现 = 较丰富的 dialog 版 + 字段并集：author 字段、Loadable 徽章文案）；两容器（PluginManagerDialog / PluginManagerWidget）删除本地副本改为导入；嵌入页改接 dialog 信号路径（clicked 汇聚 toggle+select），行为对齐独立窗口。嵌入页行为变化：dot 策略/toggle 44×24 switch 样式/release 点击/更全 detail 字段。新文件经 `check_inline_styles --update --force` 入账（文件移动，净降）。棘轮 245→**230**/38；插件族 22 测试 + desktop 749 全绿 |
| I6 | ✅ | 2026-09-03 | **对话框契约统一**：①（D5）TabbedDialog `__init__` 无条件应用 `_dialog_qss`——ShareQrDialog 底板归队，7 个子类手动调用删除；②（D2）8 个对话框按钮栏全部迁移 variant：color_picker/tag_style/theme_preview(×4 按钮)/batch_rename/plugin_operator/generic_settings/sidebar_settings/sharing_settings（OK=primary、Cancel=ghost、Apply/次级=secondary）；③ danger 经 `button_css("danger")` 落地（_links_page 删除按钮迁移，生成器新增 danger 分支 + `:focus` 规则）；④（D3）plugin_ui toggle_btn 与 make_gear_btn 的 variant+setStyleSheet 双重造型清理；⑤ gear 热区 20→metrics(hit_area)。**缓期**：SimpleDialog 轻模板（variant 迁移已达成 DoD-6 的可测部分——无 variant 按钮栏清零；模板化收益递减，留 I7 后评估）。**新发现 B7 确认深化**：焦点环测试揭示 dialog 级 QSS 焦点规则对 variant 按钮不可见（widget 级可见），已在测试中如实收缩并挂账 M2。棘轮 230→**223**/35 |
| I7 | ✅ | 2026-09-03 | **死 API/死工厂清理**：PanelContent 删除 6 个死扩展点（status_hint/set_status_hint、_context/set/get_browser_context、set_title、refresh_visual_settings、apply_app_settings、PanelContent 版 retranslate_ui——复核确认 PanelContent 层级 0 调用；TabbedDialog 层级的 retranslate_ui 在用不动）；stylekit 删除 make_fade_in/make_fade_out（生产 0 调用）及动画死导入；make_status_badge/make_pill_button/state_css **保留**（G5 钉住的规范配方，B4 迁移 tabbed_dialog.status_style 时的落点）。**缓期**：bus 模板方法固化（随 I8-I11 各面板迁移同步收编）。760 测试绿；棘轮 223/35 持平 |
| I8 | ✅ | 2026-09-03 | **迁移批 B1（info.py）**：①（P2-1）四个逐字复制的幽灵工具按钮去重——提取 `_ghost_tool_style()` 单一定义，构造与主题刷新共用；② open_btn/copy_btn 迁移 `sk.button_css("primary"/"secondary")`（info.py 内最后一处手绘 accent hover 配方消灭，D1 尾巴闭合）；③ 全部 49 位点复核确认 sk.* 方言合规。**学习记录**：棘轮计数持平（49→49）——widget 级动态主题样式的 setStyleSheet 调用无法靠工厂迁移消除，info.py 的结构性收口（面板级模板设计）留 M2 评估；棘轮的实际下降来自删除与中央/variant 采纳（I3/I4 已兑现）。desktop 747 测试绿 |
| I9 | ✅ | 2026-09-03 | **迁移批 B2（startup.py）**：第 4 套颜色算术方言 `_interpolate_color`（白/黑线性混合，C2f/P2-6）删除，8 个使用点迁移 color_utils 规范算术（-0.75→darken(0.25) 状态 chip、0.06/0.03→lighten(1.06/1.03) 渐变、0.4→lighten(1.4) caption）；Browse ghost 按钮 ×2（构造+刷新）迁移 `sk.button_css("secondary")`（保留原 padding/字号，获得焦点环）。**颜色算术方言 4 套 → 3 套**（剩：color_utils HSV/HSL、StyleKit QColor 私有、alpha 透明度——前两者公式同构已对齐）。747 desktop 测试绿；棘轮 223/35 持平 |
| I10 | ✅ | 2026-09-03 | **迁移批 B3+B4（分享族 stale 修复 B2⑥⑦⑧ + 方言核验）**：endpoint/links/access 三页各增 `_apply_*_theme()`（登记式刷新——卡片帧/表头/信息对标签/行按钮（objectName 区分 primary/danger）/access 标签），`_on_theme_changed` 接线三页——切主题后分享设置全页即时重派生，不再 stale。**P2-10 复核不成立**：`_share_status_label` 全库仅 muted 样式、无 accent 状态设置点，"状态被吞"前提不存在，未改动。插件族/分享族方言核验：全部位点 sk.* 合规。**棘轮 223→231（+8，`--update --force` 入账）**：新增调用均为刷新重应用点（切主题时重派生既有 widget 样式，消除 stale——非方言面扩张），已按要求记录理由 |
| I11 | ✅ | 2026-09-03 | **基座/面板/长尾/shell 核验收尾 + I12 基线**：①全量方言扫描（AST 级 setStyleSheet 调用点分类）：StyleKit 方言 89、无色静态表（transparent/none）~68、themes 直访 26、t[...] 直访 45、QColor 直访 0——**I12/G3 的迁移面 = t 直访 45 处**（其余已在规范方言或本无颜色）；②`_contrast_text` 双胞胎（C2f）复核结项：两处均已是 `color_utils.contrast_on` 的 2 行薄委托、fallback 差异为语境设计（swatch vs chip），无收敛价值；③ G1 棘轮 231/35、G2 0 违规、760 desktop 测试绿 |
| I12 | ✅ | 2026-09-03 | **G3 方言门禁上线**：`scripts/check_style_dialects.py` + `style_dialect_ledger.json`（t 直访 **45 处/9 文件**冻结、只降不升），接入 CI lint + pre-push；`set_button_variant` 全库 danger 仍 0（生成器级 `button_css("danger")` 已 1 处在用）。**glyph 缓期项评估修正（I12 终局）**：语义图标为 icons.py 内联 path 字符串而非磁盘文件，QSS `image: url()` 不可直接引用，且 fixed 色描边破坏双主题——实现需落盘 3×2 双色 SVG 素材（亮/暗各一套描边）+ spec 打包确认 + 冻结态双主题目检，工作量 M→L，维持缓期 |
| I12 终局 | ✅ | 2026-09-03 | **45 处 t[...] 方言全部清零**（9 文件：startup 25、sidebar 4、plugin_ui 4、workspace_bar 3、window_coordinator 3、_base_layout 2、lan_sharing 2、tag_tree 1、window 1——94 个表达式迁移 themes.color/sk.token）+ 17 处混合形态段清零 + 17 个失效 `t = themes.get()` 赋值删除；G3 升级零容忍纯禁令，全库 setStyleSheet 段内裸 t[...] 残留 **0**（AST 复审）|
| 维护 | ✅ | 2026-09-03 | **Viewer 闪退根因修复**：faulthandler 取证实锤——`_PreviewGraphicsView.__init__` 在 WA_TranslucentBackground + Frameless Tool 顶层窗口上 `setViewport(QOpenGLWidget)` 直接 access violation（事件日志 16:30/16:31 两次 c0000005，栈钉 image_viewer.py:284；Qt 不支持半透明顶层 + GL 组合）。**修复**：移除 GL 视口回退光栅渲染（单图缩放查看器光栅路径足够；app.py 的 GL 打包探针保留，G2 的 QtOpenGLWidgets 要求不受影响）。验证：窗口化/离屏复现台架存活 + desktop 788 测试绿 + 三门禁绿；**用户实测确认闪退消失** |
| I13 | ✅ | 2026-09-03 | **DoD 全表核验 + 程序收官**（见 §6.6）。活跃迭代阶段（I0-I13）完成，程序转入**维护态**：三个棘轮（G1/G3/D4 静态门禁）+ 契约/快照/像素测试（G4/G5/G6）保证不回退；剩余缺口按 §6.6 结论按需领取 |
| I14 | ✅ | 2026-09-03 | **模板化落地双轨派发**（规格：desktop-templating-implementation-spec-2026-09-03.md，M2.1 基建由并行会话交付——StandardPanel/EmptyStateWidget/StandardModalDialog）。**Track A**：SidebarPanel/TagTreePanel 接入 StandardPanel 插槽（toolbar/body/footer + show_state("directory") 替代手绘空状态，i18n 键不变）；**Track B**：7 个原生 QDialog 全量收编 StandardModalDialog（手排按钮行/硬编码 resize 删除，min_size 缩放 + 几何记忆 + 模板托管 variant/Enter/Esc；theme_preview 无需豁免；batch_rename 保留 `_apply` 别名兼容）。**汇合调和验证全绿**：ruff/G1 227/35（↓4）/G3 0/G2 0/layers/desktop 765/文档门禁。双轨文件零冲突（A=panels/+workspace_bar，B=dialogs/7 文件+_batch_rename）；A 越界适配 test_sidebar_lifecycle 1 用例（已备案）；B 备案 theme_preview 边距/标题行视觉变化 |

| 复审 | ✅ | 2026-09-03 | **统一复审（re-audit-2026-09-03.md）**：门禁与 802 测试全量实跑，DoD 复验无回退。**G1 补账 settings_dialog 1→3**——三位点均为合规方言（`:133-138` nav 垫片转发 `StyleKit.nav_css()` 工厂输出；`:265` swatch token 插值，theme_preview 同豁免类），登记于 style_ledger.json `_comment`；另补记 I14 后 227/35→231/38 的 force 入账核对结论（其余 37 文件额度与实测逐一相符，无未申报扩张）。遗留：G1 红灯已清，webui 门禁（F-3）、commit 积压（F-4）见复审报告 |

### 6.5 迭代纪律

1. **一次会话一个迭代**——做完、验完、登记进度账本再收。
2. **门禁常绿才收**：ruff / check_style_sources / check_inline_styles（只许降）/ G4-G6 / 文档门禁；pyright 当前被并行会话 mixin 的 84 个存量错误阻塞，迭代内只要求"本人件零命中"。
3. **快照有意变更**必须同 commit 给理由（G5 文化）。
4. **不新增方言/孤儿**：新代码一律 `sk.token/alpha/lighter/darker` + 工厂；新组件必须先查 widgets/ 是否已有。
5. **跨会话共管文件**（info/BrowsePage/tabbed 等）改动前先 `git status` 对齐并行会话。
6. **发现 ID 是唯一索引**：任务/提交/讨论一律引用 `A1..F4`，行号漂移不追。

### 6.6 DoD 全表核验（2026-09-03，I13 收官）

| 判据 | 状态 | 证据与剩余路径 |
|---|---|---|
| DoD-1 setStyleSheet → 0 | **部分** | 262→**231/35**（棘轮冻结）；I8/I9 学习实证：widget 级动态样式的调用无法靠工厂迁移消除——完全归零需面板级模板设计（M2 评估），棘轮保证只降不升 |
| DoD-2 方言 ≤4 种 | **✅ 终局达成（I12）** | 颜色算术 4 套→1 套公式；访问方言收敛完成：setStyleSheet 段内裸 t[...]/t.get(...) **45 处全部清零**（themes.color/sk.token 替代，视觉等价——合并主题保证键齐备），G3 升级**零容忍纯禁令**（账本清空，任何回归即红）|
| DoD-3 同概念单一实现 | **✅** | 孤儿清零（collapsible_panel/status_indicator 删除，tab_container 保留挂账 M2）；插件 UI 双实现合并；_CollapsibleSection/make_collapsible/_add_field/_contrast_text 重复消除；幽灵按钮 ×4 去重 |
| DoD-4 中央 QSS 缺口 | **部分（9→3）** | QHeaderView/输入 :disabled/QMenu separator+disabled/滚动条 :pressed/QToolTip 字号/QPushButton:checked/danger:pressed 已补；**余 3 类为 glyph 依赖**（spinbox 箭头/combo 箭头/checkbox 勾选图/tree branch）——I12 修正评估：语义图标为 icons.py 内联 path 字符串而非磁盘文件，QSS `image: url()` 不可直接引用，且 fixed 色描边破坏双主题；实现需落盘 3×2 双色 SVG 素材（亮/暗各一套描边色）+ spec 打包确认 + 冻结态双主题目检，工作量 M→L，按需领取 |
| DoD-5 度量 token 化 | **部分** | `metrics()` 家族落地（icon_sm/icon_xs/hit_area/control_height_md/radius_xs）+ dock/sidebar/workspace_bar 迁移；spacing 档间值（2/6/10/14，~180 处）吸附未做——随迁移批渐进 |
| DoD-6 对话框单一契约 | **✅**（SimpleDialog 缓期） | TabbedDialog 无条件 QSS（ShareQrDialog 归队）；**无 variant 按钮栏清零**（8 对话框迁移）；danger 落地（button_css 生成器级）；双重造型清零。SimpleDialog 判定缓期：variant 迁移已达成一致性目标 |
| DoD-7 门禁常驻 | **部分（G1-G6 ✅，G7 未建）** | G1 棘轮（231/35）、G2 静态源门禁（含 themes.py）、G3 方言冻结（45/9）、G4 中央 QSS 契约、G5 工厂快照、G6 像素采样全部接入 CI lint + pre-push；**G7 24 主题矩阵**未建（G6 已覆盖单主题像素采样，矩阵价值边际，挂账） |
| 主题切换 stale（B2） | **✅ 清零** | 4 处 P1 全部修复/复核（1 处误判）；P2 六处：endpoint/links/access 三页已修，color_picker/tag_style 无订阅为 QDialog 打开期短暂状态（可接受），P2-10 前提不成立 |

**收官结论**：7 条 DoD 中 **4 条完全达成（DoD-2/3/6 + B2 stale 清零）、3 条部分达成且剩余部分均有明确路径与门禁冻结**。程序转入维护态——后续任何会话按需领取：M2 面板级模板设计（DoD-1 终点）、glyph 素材工作（DoD-4 余项）、spacing 吸附（DoD-5 余项）、G7 矩阵（DoD-7 余项）。
