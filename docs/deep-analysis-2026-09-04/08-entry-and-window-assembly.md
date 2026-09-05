# 08 · 入口链与窗口装配（app.py / window.py / dock_factory / 生命周期协调）

> 状态：**DATED ANALYSIS（2026-09-04 实测快照）** · 本文是 deep-analysis 系列的一部分，索引见 [README.md](README.md)。
> 方法：主会话直读 `main.py`、`AssetsManager/app.py`、`window.py`、`window_coordinator.py`、`window_lifecycle_coordinator.py`、`dock_factory.py`，全部行数与锚点为本会话实测。

---

## 1. 启动链（进程入口 → 主窗口）

```
main.py (40 行)
 ├─ faulthandler.enable() → RuntimeData/Shared/faulthandler.log（覆盖式；必须在任何 Qt/扩展导入前挂载，
 │   否则 C++ 级 segfault 绕过 Python excepthook 不留 crash.log）      main.py:12-20
 ├─ logging.basicConfig(INFO) + PIL/urllib3 降为 WARNING               main.py:22-31
 └─ AssetsManager.app.main()                                            main.py:37-40
     │
     ├─ install_crash_handler()                                        app.py:128-129
     ├─ High-DPI：AA_UseHighDpiPixmaps + PassThrough 舍入策略          app.py:131-136
     ├─ QApplication + i18n.init()                                    app.py:138-145
     ├─ _bind_single_instance(app)                                    app.py:146
     │   └─ QLocalServer("AssetManager.SingleInstance")：探活 150ms；
     │       已在运行→提示并退出（返回 0）；其余一切失败 fail-open 放行   app.py:21-58
     ├─ themes.stylesheet() + 字号缩放（scaled_pt(base_pt)）            app.py:156-164
     │
     ├─ ApplicationBootstrap(performance_recorder=可选 PerformanceRecorder)
     │   └─ 遥测开关来自 AppSettings "performance_telemetry_enabled"     app.py:176-181
     ├─ install_tag_canonicalizer(get_library().canonical)             app.py:175
     ├─ install_dock_refresh_handlers()（dock chrome 合帧重建接线）      app.py:181
     │
     ├─ QTimer.singleShot(0, _deferred_startup)                        app.py:192-209, 376
     │   ├─ bootstrap.discover_plugins()（重盘扫描，延迟到事件循环）
     │   └─ _warm_up_gl()：预建 1x1 QOpenGLWidget.grabFramebuffer()
     │       ——防止首次打开 ImageViewer 时主窗闪烁
     │   （注释论证了顺序保证：slot 同步执行期间 Qt 不派发用户输入，
     │     因此 discover_plugins 一定先于 _on_open 中的 _bind_plugin_host）
     │
     ├─ SystemTrayManager(assets/icons/icon.ico) → app.setProperty("has_tray")  app.py:212-215
     ├─ StartupWindow() → startup.library_opened.connect(_on_open)    app.py:218-222, 372-373
     │
     └─ _on_open(path)（核心开库流程）                                  app.py:223-345
         ├─ 旧窗存在→强关旧窗；关失败则中止重开（不叠窗）                app.py:231-239
         ├─ MainWindow(bootstrap) + window._workspace.add_library(path) app.py:241-245
         ├─ 开库失败分支：
         │   ├─ 强关半初始化窗口                                        app.py:248-253
         │   └─ restore_intent_status(path) 判定「上次恢复被中断」：
         │       Retry → retry_interrupted_restore / Acknowledge →
         │       acknowledge_restore_intent(token)（fail-closed：无 token 直接报错）app.py:255-293
         ├─ window.show() → QTimer.singleShot(0, 崩溃报告对话框)
         │   ——崩溃日志先落盘，弹窗推迟到首帧之后                        app.py:294-305
         ├─ 插件加载失败：仅状态栏 20s + 日志，绝不模态阻塞开库            app.py:306-315
         ├─ window._tray_manager = tray；startup.close()                app.py:317-319
         └─ lan_auto_start 开启→1s 后 _toggle_sharing（shiboken6.isValid 防死窗）app.py:321-345
```

**启动流程的三个关键决策**：
1. **单实例锁是 best-effort 便利而非门禁**（`app.py:23-27` 注释明说），一切异常 fail-open——与项目 fail-closed 安全原则的区别在于：这里锁不住最多多开一个实例，锁死反而让用户完全无法启动。
2. **重活全部延迟到事件循环**（插件发现、GL 预热），启动窗口必须先出现——冷启动体验优先。
3. **崩溃报告出站请求只由用户点击触发**（`app.py:61-68` 注释：the app never initiates any network request for crash data by itself），GitHub issue URL 是唯一出站通道。

---

## 2. MainWindow 装配（window.py，1616 行）

### 2.1 继承结构

```python
class MainWindow(LanSharingMixin, QMainWindow)   # window.py:159
```

- `LanSharingMixin`（widgets/lan_sharing.py:39）：提供 `_toggle_sharing/_begin_share_stop/_update_share_status/_open_sharing_settings/_open_share_link_dialog` 等 LAN 分享动作，把 aiohttp 服务器生命周期从 QMainWindow 主体剥离。
- 构造参数强制注入：`bootstrap`、可选 `library_session`、`lan_server_factory`、`sharing_port` ——`window.py:200-207` 注释点名 G2 规则：**窗口是 LAN 表现层端口的组合根**，widgets/dialogs 只见注入边界，永不 import `lan.*`。

### 2.2 委托出去的职责（窗口本体已瘦身）

| 协调器 | 文件 | 职责 |
|---|---|---|
| WindowCoordinator | window_coordinator.py:53（158 行） | 主题应用/状态栏主题/主题切换动画（淡出→重建→淡入，代际号防旧动画错乱）|
| WindowLifecycleCoordinator | window_lifecycle_coordinator.py:113（330 行） | 库切换与退出时的资源有序编排（见 §4）|

### 2.3 `_setup_ui`（window.py:635-717）装配清单

| 区域 | 挂载物 | 锚点 |
|---|---|---|
| 菜单行 | `setMenuWidget(_menu_widget)`：QMenuBar(非原生) + 弹性垫片 + WorkspaceSection + 分享开关按钮 | :637-680 |
| 中央画布 | `setCentralWidget(FileListPanel())` | :683-684 |
| 左 dock | `dock.create(panel_type="sidebar")` → LeftDockWidgetArea，类型断言 SidebarPanel | :687-692 |
| 右 dock | `dock.create(panel_type="info")` → RightDockWidgetArea，类型断言 InfoPanel | :694-699 |
| 状态栏 | 分享状态指示（运行中点击=复制 URL，停止时点击=打开分享设置）+ 2s tooltip 复位 QTimer | :706-769 |
| 布局恢复 | `_restore_dock_layout()` + `_restore_workspace_tabs()` | :709-710 |
| 信号接线 | sidebar.directory_selected / file_list.file_double_clicked / info.open_requested·copy_path_requested·view_fullscreen·navigate_requested | :712-717 |

菜单结构（`_setup_menu` :399-433 / `_setup_view_menu` :509 / `_setup_tools_menu` :435-507）：

- **资料库**：打开/最近（aboutToShow 动态重建）/刷新/备份/恢复/导入/退出
- **查看**：侧栏 Ctrl+B、信息 Ctrl+I（checkable，与 dock visibilityChanged 双向同步）+ 工作区预设（默认/浏览=双 dock 全隐/检视=只留 info/重置布局=恢复 `_default_dock_state` 快照）
- **工具**：命令面板 Ctrl+K → 外部工具（`core/tool_scheduler.list_tools()` 动态挂载，当前目录传参）→ 插件管理器 → 插件贡献菜单项（`plugin_ctx.menu_contributions("tools")`，命令可用性实时查询）→ LAN 分享（`lan.is_available()` 失败则灰化+安装提示）→ 快捷键 F1 → 撤销历史 + 活动日志（H1-b 安全网面板）
- **设置** Ctrl+, / **帮助**（版本身份入口 A1）
- 原生 menuBar 被隐藏（:433），自绘菜单行接管主题化。

### 2.4 窗口级快捷键注册表化

`_register_window_shortcuts`（:606-634）把菜单动作 **adopt** 进 `ShortcutManager`（而非另建 QShortcut——注释说明：同序列双注册会让 Qt 判 ambiguous 而双双失效）。帮助对话框由注册表 + `FILE_LIST_SHORTCUTS` 表实时生成（`build_shortcuts_help_text` :130-156），文档永不漂移。

### 2.5 每库会话注入（G2 的另一半）

`_apply_scoped_services(session)`（:247-276）是所有面板获得服务的唯一通道：

```
runtime = bootstrap.runtime_for(session)
scoped  = runtime.services
├─ integrity_service.schedule()  —— 自动完整性检查；失败仅告警不阻塞
├─ schedule_startup_governance(scoped) —— 每会话一次静默缩略图缓存治理（守护线程）
└─ for name in ("file_list", "info", "sidebar", "tag_tree"):
      panel.set_scoped_services(scoped, runtime=runtime)
```

- 文件尾部 TYPE_CHECKING 块（:1605-1618）用 `_panel: ScopedServicesConsumer = cast(...)` 惯用法**锁定注入契约**：四个面板必须实现统一签名。
- `:267-270` 注释点名：**tag_tree 故意不作为挂载 dock**——标签筛选住在 TagBrowserDialog，自持实例与订阅；循环容忍属性缺失，未来在窗内挂 TagTreePanel 无需改此行。

### 2.6 dock 布局持久化

| 键 | 内容 | 锚点 |
|---|---|---|
| `window_geometry`（hex）+ `window_maximized` | 窗口几何；最大化先还原再存，窗体几何与最大化态分开存 | window.py:56-72 / 88-102 |
| `window_dock_state`（hex） | QMainWindow.saveState；畸形数据容忍+警告 | :980-998 / :1010-1025 |
| `dock_widths`（PanelState） | 各 dock 宽度（自定义 save/restore 谓词） | :996-998 |
| `workspace_tabs`（PanelState） | 多库标签条状态 | :1000-1010 |
| 各面板 `panel_state_key` | 面板自管视图状态（sidebar_depth_cfg、info_panel_layout…） | panels/base.py:156-171 |

`_default_dock_state` 在应用任何恢复前先抓取纯净快照（:1014-1016），「重置布局」菜单据此还原。

---

## 3. dock_factory（305 行）——唯一 dock 装配点

### 3.1 PANELS 注册表与两条创建路径

```python
PANELS = {
  "sidebar":       ("dock.sidebar",      SidebarPanel),
  "info":          ("dock.info",         InfoPanel),
  "tag_tree":      ("dock.tag_tree",     TagTreePanel),
  "image_viewer":  ("dock.image_viewer", ImageViewer),
  "empty":         ("dock.empty",        EmptyPanel),
}                                                        # dock_factory.py:36-42
```

`create(title, parent, area, panel_type=, widget=)`（:67-104）：
- **路径 A**（panel_type）：查注册表 → i18n key 决定标题（语言切换可刷新）→ 实例化面板类；
- **路径 B**（调用方自带 widget）：标题固定，供插件工具窗/克隆 dock 使用。

两者统一走：自定义标题栏（`_build_title_bar`）+ `_DOCK_TITLES` 登记（供 chrome 重建）+ footer 挂载（`_attach_footer`）。

### 3.2 `_DockPanel` Protocol（:55-64）——面板挂载契约

面板可选实现四个反射钩子，dock 工厂据此挂 chrome：

| 钩子 | 用途 |
|---|---|
| `title_bar_buttons() -> list[QWidget]` | 标题栏追加按钮（如设置齿轮，PanelContent 基类默认提供，generic_settings_dialog 弹出） |
| `title_bar_extension() -> QWidget` | 标题栏中部伸展区（stretch=1） |
| `footer_bar() -> QWidget` | 尾部追加进 content_layout |
| `shutdown()` | 关闭时清理（`_close_dock` :221-233 调用后 removeDockWidget + deleteLater） |

### 3.3 合帧刷新（D4）

theme/language/ui_scale 三总线信号全部接到 `_schedule_dock_refresh`（:273-279）：pending 标志 + 零间隔 TimerHandle，**一次设置应用触发三个信号也只重建一次全部标题栏**；语言在重建时重新 resolve（无需专责 handler）。`request_refresh()`（:298-305）暴露给非总线信号路径（背景透明度变化），保持 `_build_title_bar` 是 chrome QSS 唯一构造点（审计 A3）。

### 3.4 拆分即克隆

dock 右键菜单（:210-218）提供水平/垂直拆分：`panel.clone()`（PanelContent 基类 :145-148 = `__class__()` + restore_state(save_state())），无 clone 则建 EmptyPanel。SidebarPanel 克隆时共享已加载的 favs/recents 数据源（sidebar.py:117-123），避免重复读 JSON。

---

## 4. WindowLifecycleCoordinator——库切换/退出的资源编排（330 行）

这是全项目编排复杂度最高的窗口层模块，`switch_library`（:120-276）的失败矩阵有完整注释（H1/H2/H3/M4 分节），摘要如下：

### 4.1 switch_library 编排顺序

```
1. 同根且本窗口持有活会话 → 幂等直接返回                      :143-148
2. stop_lan   —— LAN stop 失败分两支（见 M4）                 :162-172, 187-198
3. stop_import —— 取消导入代际号 + BoundedPool.close(3s)       :174-185
4. （若 LAN 确已停）通知状态栏 + 托盘 off                      :200-212
5. 四面板 prepare_library_switch()（释放旧库绑定工作）          :214-221
6. （H1）窗口步失败且 LAN 未停 → 恢复 LAN + raise，旧会话保命   :226-229
7. close_old —— close_session 失败给异常 add_note 提示重试     :234-248
8. （H2）窗口步失败 → raise；_library_session 仍指旧会话可重试  :250-257
9. （H3）开新会话失败 → _rollback_open_failure：重开旧根；
   旧根也开不了 → 移除新标签 + 通知用户                       :259-266, 79-110
10. 成功：_apply_scoped_services + sidebar/file_list 导航到新根 :268-276
```

**M4 语义**（:190-198）：LAN stop 失败但服务器**还活着** → 中止切换（UI 不会误报已停止、旧会话不被销毁）；LAN stop 失败但服务器**确实死了** → 继续排干（旧会话 close 时其 runtime close 会重试 LAN stop），先向 UI 报 off 再抛错。

### 4.2 shutdown_resources（:278-330）退出顺序

```
LAN server.stop() → 导入清理 → info/sidebar/tag_tree.shutdown() →
save_dock_layout → save_workspace_tabs → file_list.shutdown()
```

设计点：file_list 最后关（它最大、持有最多后台任务）；任一步失败收集首错继续，最后统一 raise——但 `MainWindow.closeEvent`（window.py:1565-1616）捕获一切 teardown 失败、照常关窗、必要时显式 `app.quit()`，**teardown 失败绝不悬挂进程**。

### 4.3 closeEvent 的托盘语义

`window.py:1565-1576`：有托盘且非 `_force_quit` → 首次显示气球提示（`maybe_show_tray_hint` :105-127，"只提示一次"记忆持久化失败也照提示——fail-open）后 `hide()` + `event.ignore()`；`request_exit()`（:1539-1542）设 `_force_quit=True` 才真退出。菜单"退出"与托盘"退出"都走 request_exit，绕过托盘最小化。

---

## 5. 与本仓库其他分析的关系

- 面板/控制器/mixin 星系的内部结构 → 见 [07-desktop-ui.md](07-desktop-ui.md)
- `ApplicationBootstrap`/`LibraryRuntime` 的服务装配内部 → 见 [03-application.md](03-application.md)
- LAN 分享动作 mixin 的服务器生命周期 → 见 [04-lan.md](04-lan.md)
- dock chrome 的主题令牌来源（themes/icons/ui_scale）→ 见 [01-core.md](01-core.md)

---

## 6. 观察到的弱点/技术债（本层实测）

1. **window.py 仍是 1616 行的上帝类**：菜单/背景渲染/导入进度/导入 worker 池/托盘提示/快捷键帮助全部内联，尽管已外移两个协调器与 LanSharingMixin。`_ImportProgressDialog`（:75-85）等私有类嵌在模块顶部，进一步拆分空间明显。
2. **导入 worker 管理字段裸露**（`_import_generation/_token/_pool/_task/_dialog` 五连字段 + `_cleanup_import`），生命周期分散在 window.py:220-245 与 lifecycle 协调器两处回退逻辑（:174-185 的 token/pool 旧路径是兼容垫片）。
3. **`_on_open` 闭包 120 行**（app.py:223-345）：开库、恢复中断对话框、崩溃报告、插件失败、托盘、自动分享六个关注点串在一个函数里，重开库的"强关旧窗→失败中止"路径靠注释维持，回归风险集中。
4. **魔法字符串面板名遍历**（`for name in ("file_list", "info", "sidebar", "tag_tree")` 在 :267 与 :214 两处硬编码），挂载清单没有单一事实源。
5. **主题切换动画代际号**依赖 WindowCoordinator 内部协议，若两窗口并存（程序化重开窗口期间短暂重叠）动画状态无窗级隔离——当前单实例锁下风险低，但契约未文档化。

*下移至工程体系文档的项：无。本层清单至此。*
