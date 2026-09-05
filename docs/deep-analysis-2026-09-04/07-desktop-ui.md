# 07 · 桌面 UI 层（panels / dialogs / widgets / i18n / background / controllers）

> 状态：**DATED ANALYSIS（2026-09-04 实测快照）** · deep-analysis 系列之一，索引见 [README.md](README.md)。
> 方法：并行只读勘察代理全量通读 dialogs/（26+6 文件）、widgets/（19 组件）、i18n/、background/、panels/ 辅助模块；主窗口/dock/file_list 星系由主会话自营（[08-entry-and-window-assembly.md](08-entry-and-window-assembly.md)）。全部行数 wc -l 实测。

---

## 1. panels/ 全景与辅助模块

panels/ 共 39 文件 17,656 行。主体结构（FileListPanel mixin 星系、SidebarPanel、InfoPanel、TagTreePanel、ImageViewer、PanelContent/StandardPanel 基类、dock 挂载协议）已在 [08-entry-and-window-assembly.md](08-entry-and-window-assembly.md) §2-§3 详述，此处补辅助模块。

### 1.1 _event_bridge.py（87 行）——域事件 → Qt 信号桥

三个桥类（DomainEventSubscription / CategoryRegistrySubscription / RuntimeEventSubscription），模式一致：**订阅回调里只 emit 信号，槽以 QueuedConnection 连接**（:23 注释：域事件可能来自 worker 线程，direct connection 会在发布线程执行 UI 代码）；subscribe_weak 弱订阅 + close() 幂等。消费方：panels/base.py:71（PanelContent 统一入口 _connect_domain_event，shutdown 统一 close）、dialogs/settings_dialog.py:1784、file_list、tag_tree、application/asset_filters。

### 1.2 panel_state.py（82 行）——面板状态持久化契约

PanelState 把 owner 的 save_state()/restore_state() duck-type 面绑到一个 AppSettings 键；read/persist/load 统一校验（非 dict 无效、异常返回 None/False）。**单一 save/restore 契约**——所有面板持久化 UI 键走同一路径；消费方 window.py 的 dock_widths 与 workspace_tabs 两实例。

### 1.3 _info_parts.py（299 行）——Info 面板实例无关件

从 info.py 逐字搬出：_DragLabel（点击打开/拖到浏览器）、_PreviewLabel（双击全屏，accept 防宿主 eventFilter 二次触发开两个 viewer）、_FlowLayout（标签 chip 换行的完整 QLayout 实现）、_FileInfoTask/_LinkScanTask（CancellableRunnable 后台任务族）、_AsyncRequest（generation+session+path 请求代次）。

### 1.4 _sidebar_parts.py（100 行）——侧栏实例无关件

VTYPE_FS 虚拟树节点类型、_PreloadTask（CancellableRunnable + auto-delete，:52-58 注释详解 run() 内 emit 后 pool 回收 C++ runnable 的时序）；**取消令牌每 64 个条目才轮询一次**（_WALK_POLL_EVERY :23——每条一次锁获取在大树上可测地拖慢热路径）。

### 1.5 _ai_tag_common.py（43 行）——AI 标签共享门面

Info 面板单图按钮与 FileList 批量动作共用：`ai_tagging_enabled()`（**fail-closed**——typed getter 缺失或值非精确 True 即关闭）、`ai_tag_error_text(kind)`（错误 kind → 三语文案 key）。

### 1.6 批量重命名归属澄清

批量重命名不在 dialogs/，而在 panels/file_list/：_batch_rename.py（117 行纯规划——Windows 保留名 + casefold 碰撞检查，零 UI 依赖）+ _batch_rename_dialog.py（97 行 StandardModalDialog 预览；occupied 收集惰性化 + 上限 5000——全量 iterdir+resolve 在 GUI 线程会冻住对话框）。

---

## 2. dialogs/ 全景（26 顶层 .py + sharing_settings/ 6 文件，共 9356 行）

### 2.1 对话框体系骨架：两级基类

- **TabbedDialog(QDialog)**（tabbed_dialog.py:139，659 行）——全部对话框统一主题模板：
  - **双形态自动分派**：子类覆写 `_setup_tabs` 走标签页布局，否则走单页 _build_ui——一个基类同时服务多页设置窗与单页弹窗。
  - **QSS 单点级联**（:164，audit D5）：`__init__` 强制施加一次（注释：ShareQrDialog 曾忘记施加）。
  - **几何记忆**：`dialog_geometry_{objectName|类名}` 键持久化（hex saveGeometry），showEvent 恢复、closeEvent/done 双路径保存；畸形数据忽略。
  - **总线生命周期**：showEvent 才连接 theme_changed（懒连接防泄漏）；仅 `supports_runtime_refresh=True` 的子类才连 language/ui_scale；全关闭路径断开。
  - **`_DialogButtonBar`**：手造按钮栏复刻固定顺序（stretch|Cancel|Apply|OK），替换平台相关的 QDialogButtonBox（设计语言统一 P0-5，消除"一个应用两套肌肉记忆"）。
  - **widget 工厂**：make_heading/make_input/make_radio_group/make_browse_row... 全部走主题 token + scaled_px/pt。
- **StandardModalDialog(TabbedDialog)**（modal_dialog.py:26，177 行）——单页模态模板：header（图标+标题+副标题）、可选滚动画布、三段按钮栏、setup_content 子类钩子。

### 2.2 对话框逐个清单（按行数降序）

| 文件 | 行数 | 基类 | 职责与要点 |
|---|---|---|---|
| settings_dialog.py | 2052 | TabbedDialog | 全局设置中心六页（§2.3） |
| sharing_settings_dialog.py | 1334 | TabbedDialog+5 mixin | 共享系统管理外壳（§2.4） |
| startup.py | 894 | QMainWindow | 启动窗/库选择器（§2.5） |
| share_link_dialog.py | 334 | TabbedDialog | 创建分享链接；成员 QTimer 防销毁竞态；经 _share_api.ShareCreationTask 异步创建 |
| tag_editor_dialog.py | 290 | StandardModalDialog | 单文件标签编辑；_DeleteUnusedWorker(QThread) 后台删除，closeEvent 给 2s 宽限防 "QThread destroyed while running" |
| undo_panel.py | 250 | TabbedDialog | 撤销历史面板（H1-b E-C2）；**诚实边界 docstring**：仅会话内 LIFO + 删除类 90 天备份，不假装回收站 |
| theme_preview_dialog.py | 238 | StandardModalDialog | 左主题列表 + 右实时预览；脏编辑可路由进 save-as-custom 而不关闭 |
| plugin_manager_dialog.py | 226 | TabbedDialog | 独立插件管理器（组件与设置页内嵌版同源） |
| color_picker_dialog.py | 207 | StandardModalDialog | HSV 色轮 + 双模式数值输入 |
| activity_panel.py | 183 | TabbedDialog | activity_log 只读视图（H1-b E-C3）；读错误渲染为内联提示不抛异常 |
| sidebar_settings_dialog.py | 157 | StandardModalDialog | 收藏/最近/过滤栏可见性 + 全局深度 + **每分支深度覆盖** |
| tag_style_dialog.py | 139 | StandardModalDialog | 标签颜色/图标/分类（G2-1）；持久化归调用方 |
| share_qr_dialog.py | 83 | StandardModalDialog | QR 展示；segno 可选依赖，导入失败优雅降级 |
| plugin_operator_dialog.py | 80 | StandardModalDialog | 插件 CommandOperator 参数表单：从 params schema 动态生成，secret 走密码回显 |
| tag_browser_dialog.py | 52 | TabbedDialog | **宿主 panels.tag_tree.TagTreePanel**；_on_dialog_closed 调 shutdown 释放订阅 |
| generic_settings_dialog.py | 38 | StandardModalDialog | 面板无专属设置时的占位（单 Close 按钮隐藏 Cancel） |

### 2.3 设置对话框深读（settings_dialog.py，2052 行）

- **导航外壳** `_SettingsNavShell`（:77-182）：非 QTabWidget 的"左侧 216px 导航栏 + QStackedWidget"，但实现 QTabWidget 兼容小接口（addTab/setTabText/setStyleSheet），经 TabbedDialog 的 `_create_tab_container` 钩子注入——**setStyleSheet 直接吸收 tab QSS 转译为 rail 语法**；宽度 <760 逻辑像素切顶部按钮排。
- **六页**：
  1. **Appearance**：主题单选行带色板 swatch + 模式（暗/亮/跟随系统）+ 新建/预览/导入导出主题；**背景区**：启用/路径/不透明度双滑杆/效果（none/blur/mosaic/kuwahara/shader）+ **强度滑杆 150ms 防抖**（每 tick 否则触发 settings 保存 + 全窗口重绘）+ shader 预设下拉；路径为空时自动关闭背景（QSignalBlocker 防递归）。
  2. **General**：语言单选 + UI 缩放滑杆（50-200% 实时生效）+ **AI 标签组**（Ollama 本地优先：endpoint/model/最大标签数/测试连接）。
  3. **Thumbnails**：质量四档 + 缓存清除（带进度信号）/全部重建（异步）。
  4. **Maintenance**：checkpoint/库大小/integrity/健康刷新、缓存上限逐出、活动日志按保留天数清理、**断链扫描与重链**（结果行上限 500 防孤儿库刷爆）。
  5. **Backup**：元数据导出、备份/恢复——经 _maintenance_tasks.MaintenanceTaskRunner 共享后台执行（主窗菜单与设置对话框共用同一契约）。
  6. **Plugins**：内嵌 PluginManagerWidget（audit I5/D6：消两处漂移拷贝）。
- **事件桥**：DomainEventSubscription 订阅维护域事件，按 session_token 过滤——设置对话框本身也是域事件消费者。

### 2.4 共享设置深读（外壳 1334 行 + sharing_settings/ 1181 行）

```python
class SharingSettingsDialog(TabbedDialog, SharedUiMixin, EndpointPageMixin,
                            LinksPageMixin, AccessPageMixin, ConfigurationPageMixin)
```

- **注入端口**：LanControlPort/ShareSettingsPort（application/desktop_ports）——对话框不 import lan。
- **设置分类学**（诚实边界）：`_PLANNED_ONLY_SETTINGS`（5 个键**尚无服务端消费者**，摘要标注 "planned" 而非谎称已保存）；`_DIALOG_LIVE_SETTINGS`（quota 4 键立即生效）。变更摘要区分 立即生效（HOT）/ 需重启（RESTART）/ 计划中（PLANNED）；apply 与 accept 分离，支持 discard。
- **后台线程纪律**：状态轮询 QThreadPool+QRunnable（2s QTimer，仅运行中）；隧道开关专用 TunnelWorker(QThread) 带 cancel；_on_dialog_closed 停 timer + 撤 worker + 幂等标志。
- **分层怪象**：links/invites/online/activity 全部经 `_share_api.py`（requests + 10s 超时）**打本机 LAN HTTP API——桌面进程用 HTTP 客户端访问自己进程内的服务器**（见弱点 W2）。
- 分包 6 文件 = 构造 + 视觉，逻辑留外壳；跨 mixin 契约全靠**类级属性注解**（40+ 个 Any）。

### 2.5 启动窗口（startup.py，894 行）

三个卡片类（_DetailPanel 详情卡 / _LibraryCard 历史项——Enter/Space 双击语义、Tab 聚焦即选中 / _FirstRunCard 首次运行空态）+ StartupWindow(QMainWindow)：RECENT_LIBRARIES_MAX=30；_populate 容错非字符串条目（防 Path 崩溃）、有效在前缺失在后、重填充保持选择；新建库非空目录先确认（索引既成库根）；closeEvent 显式断开 bus 连接；主题/语言手动全量刷新。

---

## 3. widgets/ 全清单（19 组件，6764 行）

| 组件 | 行数 | 机制要点 |
|---|---|---|
| command_palette.py | 925 | **Ctrl+K 命令面板**：三种前缀模式（`>` 命令/`#` 标签/`@` 收藏）；**子序列模糊匹配**（"drk" 命中 "Dark Mode"）；聚合内置命令+库标签+收藏；按方法名 duck-type 调宿主 |
| theme_preview.py | 721 | 10 个 section 实时预览 + ColorSwatch 可点击换色 |
| stylekit.py | 648 | 样式工具箱：token 安全查找、QSS 生成器、动画 + reduce_motion 降级；**零 AssetsManager import**（可独立复用） |
| quick_look_overlay.py | 615 | 空格键媒体预览浮层：平滑缩放画布 + 预加载前后项；挂载点 file_list/_base_events.py:798 |
| micro_tab_bar.py | 564 | 浮动胶囊 tab 条：pill 指示器动画 200ms（reduce_motion 直切）；挂载点 InfoPanel 元数据区分页 |
| lan_sharing.py | 488 | **LanSharingMixin**（MainWindow 混入）：_toggle_sharing（含安全预检）、异步停服、状态更新、打开共享设置/分享链接对话框 |
| workspace_bar.py | 442 | 多库标签条：右键菜单/双击内联重命名/拖拽排序/复制库检测；save/restore_state 容错 |
| plugin_ui.py | 384 | 插件卡片 + 详情面板的**唯一正典实现**（消两处漂移拷贝） |
| toast.py | 356 | 通知条**单例**：三级色 token、无障碍告警、shiboken isValid 父窗销毁守卫 |
| quick_tagger_overlay.py | 263 | T 键即时打标浮层：QCompleter 补全全库标签、多文件模式 |
| tab_container.py | 250 | 文件列表多 tab 容器：每 tab 独立 FileListPanel；**title_bar_extension() 把内部 tab 条外置给 dock 标题栏**（dock_factory:142 探测该钩子）；shutdown 级联停子面板 |
| hsv_wheel.py | 218 | HSV 色轮（hue 环离屏缓存）+ 亮度条 |
| empty_state.py | 163 | 6 种 kind 统一空/加载/错误占位 |
| shortcut_manager.py | 160 | **全局快捷键注册表**（单例）：注册键规范化、冲突 last-wins + warning；**description 存 i18n key** 使帮助对话框随语言重译 |
| sharing_contracts.py | 133 | 展示层共享契约：HOT/RESTART 设置键映射 + confirm_security_preflight；**存在意义：打断 lan_sharing↔dialog 双向 import** |
| tag_chip.py | 130 | chip 工厂 + tag_color_from（legacy store 优雅返回 None）；同义词 tooltip 缓存上限 500 |
| tray.py | 125 | 系统托盘：关窗隐藏；生成式 fallback 图标（无文件时画 "A" 随主题重生成）；QMenu 无父窗故显式 deleteLater |
| dominant_palette_strip.py | 123 | 主色胶囊条：最多 5 色块、相对亮度判断前景色 |
| elevation.py | 55 | 统一深度词汇表：3 级 shadow；shadow_params 数据接口给不能挂 QGraphicsEffect 的自绘控件用 |

---

## 4. i18n/ 机制（103 行 + 三语 json）

- **字典结构**：**扁平点号字符串键**（如 "settings.appearance"），非嵌套——_lookup 就是单层 dict.get。
- **tr(key, **kwargs)**：当前语言 → **英语回退** → 仍缺则 log warning 并**返回原始 key**；kwargs 经 str.format 插值。
- **set_language**：校验 → 切语言 → 持久化 → **`bus().language_changed.emit(code)` 广播**。
- **三语实测**：en/zh/ja 各 **1060 keys**（含 _meta），命名空间分布 sharing 269 / settings 151 / filelist 145 / info 46...——**三语键数完全对齐**；但 `_meta.version` en=1、zh/ja=2（版本字段无消费逻辑，漂移无告警）。
- **语言切换信号流**：SettingsDialog._on_lang_clicked → i18n.set_language → bus().language_changed → TabbedDialog（仅 supports_runtime_refresh=True 者）刷按钮文案/标签页标题/retranslate_ui；StartupWindow 手动逐控件；panels/base、dock_factory、window 菜单、workspace_bar、empty_state 各自重标。消费面：59 个 .py import i18n。
- **关键契约缺口（W1）**：`tr()` **不支持 default 参数**——但代码里大量 `tr("x", default="Y")` 写法（modal_dialog.py:43-47、startup.py:98-103、command_palette 多处、plugin_ui.py:187 等），default 实际是被 str.format 忽略的死参数；缺键返回原始 key 而非默认值——**全库至少 6+ 处依赖一个不存在的回退机制**。

---

## 5. background/ 是什么（784 行）

**桌面主窗背景渲染层**——静态壁纸图 + GLSL 效果链（非"后台任务"）。设计：壁纸源恒为静态图片；效果 GL 管线（GPU 优先）+ CPU 回退；全窗合成是 MainWindow 普通 paintEvent。

| 文件 | 行数 | 职责 |
|---|---|---|
| model.py | 56 | EffectSpec（none/blur/mosaic/kuwahara/shader + intensity 1-50 + shader_key）+ EffectChain |
| pipeline.py | 130 | ImageEffectRenderer：**GL 优先 + CPU 回退**——blur/mosaic/kuwahara GL 失败自动落 CPU；**shader 效果 GL-only**，无 GL 降级原图 + warning（永不黑屏） |
| cpu.py | 30 | 复用 core.bg_effects 的已验证实现 |
| gl/shaders.py | 152 | GLSL 1.20 子集（兼容 GL2.1+/GLES2(ANGLE)/Qt 软件 GL）：blur 可分离两趟+镜延拓、kuwahara 四象限最小方差、Shadertoy 包装——**语义与 CPU 对手严格一致** |
| gl/presets.py | 50 | Shadertoy 风格预设（plasma、grid-flow） |
| gl/renderer.py | 355 | 纹理/FBO ping-pong/回读/静帧与实时绘制；GL 常量以裸 int 自带（PySide6 不在 QOpenGLFunctions 暴露 GL_*）；失败一律回退不崩溃 |

挂载：设置外观页 shader 预设下拉消费 presets.preset_keys()；强度变化 → themes.invalidate_cache() → 主窗 _on_bg_style_changed → paintEvent 走 ImageEffectRenderer.render()。

---

## 6. 挂载关系总图

```
app.py ── SystemTrayManager (widgets/tray, app.py:212)
       └─ StartupWindow (dialogs/startup) ──library_opened──► 主流程；startup.close() 后进入 MainWindow

window.py（MainWindow = LanSharingMixin + QMainWindow）
 ├─ WorkspaceSection (widgets/workspace_bar)  library_switched → _on_switch_library
 ├─ LanSharingMixin (widgets/lan_sharing) ──► SharingSettingsDialog / ShareLinkDialog
 ├─ 懒开对话框：SettingsDialog / PluginManagerDialog / UndoPanelDialog
 │              ActivityPanelDialog / CommandPalette / PluginOperatorDialog
 ├─ ShortcutManager（注册菜单级快捷键；帮助对话框种子）
 └─ 切库时重开 StartupWindow (:818)

dock_factory ── 挂载 SidebarPanel / InfoPanel / TagTreePanel / ImageViewer / EmptyPanel
              └─ title_bar_extension 钩子 ← TabContainer（外置 tab 条）

panels/info ── EmptyStateWidget / MicroTabBar / DominantPaletteStrip / create_tag_chip
              / TagEditorDialog / TagBrowserDialog
panels/sidebar ── SidebarSettingsDialog / SidebarFavorites / SidebarRecentFolders（每库 json）
panels/file_list ── QuickLookOverlay(Space) / QuickTaggerOverlay(T) / Toast / BatchRenameDialog
                    / _ai_tag_common 门面
panels/base ── PanelContent 契约：save/restore_state + PanelState + _connect_domain_event

主题/语言/缩放三条总线把上述一切与主窗联动（theme_changed → QSS 级联 + tray 图标重生成；
language_changed → §4 信号流；ui_scale_changed → refresh_scaled_geometry 链）
```

---

## 7. 设计取舍与弱点清单

**值得肯定的结构决策**：
1. **对话框生命周期 = 即开即建 + 身份几何记忆**（非单例）：每次 open 新建实例，跨次记忆由 dialog_geometry_{identity} 承载；bus 连接 showEvent 懒连 + 全路径断开；`_on_dialog_closed` 幂等钩子统一收尾。权衡：无"已开则聚焦"语义，重复打开会多实例并存。
2. **mixin 拆分 vs 类型安全**：sharing_settings 五个分页 mixin 让 1334 行外壳只留逻辑，但跨 mixin 契约全靠类级属性注解 + Any。
3. **`_create_tab_container` 工厂**：让左 rail 外壳伪装 QTabWidget，复用 TabbedDialog 全部 tab 管理代码——聪明但隐晦。
4. **主题单 QSS 级联 + StyleKit 生成式样式**：对话框级一次 setStyleSheet 级联全部子控件；代价是主题切换全量重建字符串，控件多的窗有一次可感重排。
5. **共享契约下沉**：sharing_contracts.py 专断双向 import；plugin_ui.py 消漂移拷贝——两个"防漂移"模块都带审计编号注释。
6. **诚实边界哲学**：undo_panel 不假装跨会话撤销；_PLANNED_ONLY_SETTINGS 明示"未接服务端"；activity 读错误降级为内联提示。

**弱点/技术债**：

| # | 问题 | 证据 |
|---|---|---|
| W1 | **`tr(key, default=...)` 是幻觉参数**——i18n.tr 不识别 default，缺键返回原始 key；全库 6+ 处依赖这个不存在的回退 | i18n/__init__.py:36-50 vs modal_dialog.py:43-47 等 |
| W2 | **HTTP 自环分层**：SharingSettingsDialog 用 requests 打自己进程内的 LAN 服务器——多一层认证/序列化/失败面，应有进程内端口直调 | dialogs/_share_api.py |
| W3 | **语言热刷新覆盖不全**：language_changed 仅连 supports_runtime_refresh=True 的对话框——SharingSettings/UndoPanel/ActivityPanel/ShareLink/ShareQr 未声明，已开窗文案冻结直至重开；StartupWindow 完全手写，三套机制并存 | tabbed_dialog.py:187-190 |
| W4 | **SettingsDialog 巨石**：2052 行六页六域 + Protocol duck-type 宿主探测——应再按 Tab 拆文件 | settings_dialog.py 全文 |
| W5 | **私有 API 穿透**：_sharing_helpers 直接 import i18n._lookup；settings_dialog 访问 themes._current/_get_loader() | _sharing_helpers.py:22、settings_dialog.py:271 |
| W6 | 三语 _meta.version 漂移（en=1, zh/ja=2）无告警 | i18n json |
| W7 | SidebarFavorites/Recent 构造时先落 tempfile.gettempdir()，set_library_root 才迁库数据目录——窗口期契约靠调用顺序 | sidebar_favorites.py:19-20 |
| W8 | Toast 单例：新通知顶掉旧通知（含进行中的动画/无障碍事件） | toast.py |
| W9 | SharingSettingsDialog 2s 轮询——无推送订阅，窗开着就有持续 HTTP 噪声 | sharing_settings_dialog.py:126 |
| W10 | _DialogButtonBar 半兼容面：addButton 恒设为 _apply_btn，未来第三种按钮角色会静默错位 | tabbed_dialog.py:110-116 |
| W11 | 五 mixin + 外壳 + TabbedDialog 三层间 40+ Any 注解属性——重命名无静态检查兜底 | _configuration_page.py:26-70 |
| W12 | 扁平 i18n 键 1060 个无分组校验工具——三语同步全靠纪律（当前对齐是事实，非机制保证） | i18n |

**总评**：这一层工程自觉明显高于均值——审计编号注释、设计语言统一里程碑、"诚实边界"文档化、防漂移契约模块、广泛的无障碍与 DPI 支持。主要债务集中在 SettingsDialog 巨石、HTTP 自环分层、`tr(default=)` 幻觉参数与语言热刷新覆盖缺口四处。

---

**关联阅读**：窗口装配与 dock 协议 → [08-entry-and-window-assembly.md](08-entry-and-window-assembly.md)；file_list mixin 星系 → 同文 §2；i18n 数据被构建打包 → [06-engineering.md](06-engineering.md)；i18n 与 webui 词典是两套体系 → [05-webui.md](05-webui.md)。
