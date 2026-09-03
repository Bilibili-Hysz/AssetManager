# 桌面端视觉组件全景清单与风格审计

> 审计范围：`AssetsManager/` 桌面端（PySide6 / Qt）全部可见视觉组件
> 审计日期：2026-09-03
> 代码规模：UI 层 4 个目录共 **33,072 行**（panels 17,514 / widgets 6,428 / dialogs 9,130 / window.py 72,620 字节）
> 方法：全量通读 + `file:line` 证据锚点，仅只读调研，未修改任何代码

---

## 0. 一句话结论

桌面端共有 **62 个可见视觉组件**，可归为 4 层：**主窗口骨架（6）→ 主面板（7）→ 对话框/浮层（21）→ 复用控件（28）**。

风格上并非"各画各的"，而是建立在 **三层设计系统** 之上：

| 层级 | 载体 | 覆盖率 | 性质 |
|---|---|---|---|
| **L1 事实标准** | `core/themes.py` token + `core/ui_scale.scaled_px/pt` | **100%** | 所有组件无一例外都在用 |
| **L2 全局浮层原语** | `widgets/elevation.py` 三级阴影 | **100%**（所有浮层） | 唯一真正统一的视觉原语 |
| **L3 名义设计系统** | `widgets/stylekit.py` StyleKit | **约 50%** | 只在"对话框/文本按钮"这条线生效 |

**关键判断**：StyleKit 是"名义设计系统"而非"事实设计系统"。真正托底全局一致性的是 `themes` token 表。命令面板、QuickLook、工作区栏、MicroTabBar、图片查看器、缩略图网格这 6 个高频组件全部绕过 StyleKit 手写样式。

---

## 1. 主窗口骨架树

```
MainWindow (QMainWindow + LanSharingMixin)                        window.py:159
│
├── ① 菜单栏行 MenuWidget  ← 自绘，原生 menuBar 被隐藏 window.py:433
│   │  布局：QHBoxLayout, margins 0, spacing 0                     window.py:638-640
│   ├── QMenuBar（setNativeMenuBar(False) + 自定义 QSS）           window.py:642-644
│   │   ├── 库 menu.library ── 新建/打开/最近库…                    window.py:401
│   │   ├── 视图 menu.view ── 面板开关 / 工作区预设                  window.py:510
│   │   ├── 工具 menu.tools                                        window.py:437
│   │   ├── 设置 menu.settings（Ctrl+,）                            —
│   │   └── 帮助 about.menu_title                                  window.py:424
│   ├── WorkspaceSection【库切换栏】                                widgets/workspace_bar.py:333
│   │   ├── QFrame 竖分隔线（1px, border_subtle）                   :346-350
│   │   ├── WorkspaceBar (QTabBar)                                 widgets/workspace_bar.py:33
│   │   │   ├── 内联 QLineEdit 重命名（双击触发）                    :294-309
│   │   │   └── QMenu 右键菜单（重命名/关闭/关闭其他）                :278-292
│   │   └── QPushButton "+"（打开库, primary, 圆角 md）             :365-390
│   └── QPushButton 共享开关（share/close 图标切换, 28×28）         window.py:661-677
│
├── ② CentralWidget ── FileListPanel【文件列表】                    window.py:683-684
│
├── ③ 左侧 Dock ── SidebarPanel【侧边栏】                           window.py:687-688
│   └── 标题栏：自定义 _build_title_bar（圆角 md 顶栏 + 齿轮/浮动/关闭）dock_factory.py:114-207
│
├── ④ 右侧 Dock ── InfoPanel【信息面板】                             window.py:694-695
│   └── 标题栏：同上                                                dock_factory.py:114
│
├── ⑤ QStatusBar                                                   window.py:727
│   ├── 临时消息区
│   └── _share_status_label（常驻右侧, accent/muted 切换）            widgets/lan_sharing.py:316-331
│
└── ⑥ 背景特效层（可选，设置项控制）
    └── ImageEffectRenderer → apply_blur / apply_mosaic / apply_kuwahara / shader
                                                                   core/bg_effects.py:102/140/167
```

**骨架风格要点**
- 菜单栏行是**自绘**的：`setMenuWidget()` + 隐藏原生 menuBar，把工作区标签栏和共享按钮塞进同一行（Linear/Figma 式的紧凑顶栏）
- Dock 标题栏是**自定义 QWidget**（`dock_factory.py:114`），不是 Qt 原生 title bar：顶圆角 md、1px `border_subtle` 描边、`header_for_dock()` 背景；右侧固定齿轮(面板扩展)/浮动/关闭三个 ghost 图标按钮，尺寸 24×24（`hit_area`）
- Dock 仅开放 `Movable | Floatable`，不可关闭到无（关闭走 `_close_dock` 菜单）

---

## 2. 主面板树（7 个）

### 2.1 FileListPanel【文件列表】★ 最高视觉密度

`panels/file_list/_base.py:42` — 继承 `PanelContent`，由 5 个 mixin 组合（Navigation/Actions/Layout/Logic/Events）

```
FileListPanel                                                    _base.py:42
├── ① Tier-1 地址导航带 _header（固定 36px）                        _base_layout.py:108
│   ├── 后退 / 前进 / 上级 三个图标按钮                             _base_layout.py:121-123
│   ├── #addressBarCapsule【胶囊地址栏】高 28                       _base_layout.py:128
│   │   ├── folder 图标 14px                                      _base_layout.py:135
│   │   └── 面包屑 _breadcrumb（动态 QPushButton + " > " 分隔）      _navigation.py:304
│   │       └── 省略按钮 " … "（>5 层时出现，弹出 QMenu）            _navigation.py:320
│   ├── refresh 按钮 22×22                                        _base_layout.py:146
│   └── 搜索框 QLineEdit 28×200（带 QCompleter 历史）               _base_layout.py:153
│
├── ② Tier-2 视图/命令带 _toolbar_widget（固定 32px）               _base_layout.py:166
│   ├── 类别过滤 QComboBox                                        _base_layout.py:173
│   ├── 排序 QComboBox（名称/日期/大小/类型）                        _base_layout.py:185
│   ├── 升降序切换按钮（arrow_up/down）                             _base_layout.py:198
│   ├── 视图切换 QComboBox（网格/详情）                              _base_layout.py:207
│   ├── 缩放 QComboBox（48/72/96/128，默认 96）                     _base_layout.py:215
│   ├── 显示隐藏文件（eye/eye_off）                                 _base_layout.py:232
│   └── 高级过滤 settings 按钮 → Popup                             _base_layout.py:235
│
├── ③ 主体（二选一，可切换）
│   ├── FileListGridWidget【网格画布】★ 全 QPainter 自绘            _grid_widget.py:40
│   └── _detail_view【详情列表】QTreeView + 5 列                    _base_layout.py:280
│
├── ④ 状态栏 _status_bar（固定 28px）                               _base_layout.py:249
│   ├── _status（条目数/选中数/总大小）
│   └── _operation_feedback（操作反馈，默认隐藏）
│
└── ⑤ 浮动弹层
    ├── _advanced_popup（QDialog, Qt.Popup）高级过滤                _base_layout.py:539
    │   ├── 修改时间起止 QDateEdit ×2
    │   ├── 大小区间 QSpinBox ×2（0–2097151 MiB）
    │   ├── 评分区间 QSpinBox ×2（0–5）
    │   ├── 扩展名 QLineEdit
    │   └── 清除(ghost) / 应用(primary)
    └── BatchRenameDialog【批量重命名】                             _batch_rename_dialog.py:17
        ├── 模式 QLineEdit（默认 "{name}_{n}"）
        └── 预览 QTableWidget 3 列（当前名/新名/状态）
```

**FileListGridWidget 自绘细节**（`_grid_widget_render.py`，全项目视觉密度最高）

| 效果 | 行号 | 参数 |
|---|---|---|
| 卡片渐变底 | :479-491 | heading 色 alpha 14→7 竖向渐变，边框 alpha 24，圆角 10 |
| Hover 抬升 | :387-388 | 放大 1.075 + 上移 5px |
| 三层弥散阴影 | :564-601 | 黑 alpha 18 / 28 / 36，圆角递减 +2/+1/+0 |
| 选中态 | :625-631 | accent 填充 alpha 80，描边 alpha 200，笔宽 1.5 |
| 键盘焦点环 | :640-651 | 先 3.5px 虚光环 alpha 65，再叠 2.0px accent 实线环 |
| 框选 Rubber band | :434-445 | accent alpha 35 填充 + 1px 描边 + 圆角 3 |
| 扩展名徽章 | :751-765 | 按类别着色，`contrast_on()` 算对比文字色，圆角 6 |
| 文件夹图标 | :656-712 | `accent*0.6 + 金 0xc9a063*0.4` 混色，三层圆角矩形 + 阴影 + 顶部高光 |
| 加载失败楔标 | :549-562 | 预览右下角 danger 色三角形 |
| 空状态 4 态 | :144-197 | 34px 图标 + 加粗文字；loading 态额外画 56×2 accent 下划线 |

动画由 `Animator`（`_animator.py:20`）驱动：**16ms QTimer ≈ 60fps**，缩略图淡入每帧 +0.12，hover 阻尼 0.30，入场交错每 tick 揭示 `len(queue)//12` 个。全程受 `reduce_motion` 短路。

### 2.2 SidebarPanel【侧边栏】

`panels/sidebar.py:112` — 继承 `StandardPanel`（Header/Toolbar/Body/Footer 四槽位）

```
SidebarPanel                                                     sidebar.py:112
├── Toolbar
│   ├── 过滤框 QLineEdit（清除按钮 + 200ms 防抖）                   sidebar.py:145
│   ├── 全部展开按钮（arrow_down）                                  sidebar.py:185
│   └── 全部折叠按钮（arrow_up）                                    sidebar.py:191
├── Body ── _tree (QTreeWidget) 4 个虚拟顶层分区                    sidebar.py:159
│   ├── ⭐ 收藏 Favorites      （star 图标, favorite 色, 加粗）      sidebar.py:374-390
│   ├── 🕐 最近文件夹 Recent    （clock 图标, recent 色）            sidebar.py:392-410
│   ├── ▦ 集合 Collections     （grid 图标, accent 色）             sidebar.py:412-448
│   └── 📁 文件系统 Filesystem  （folder/file 图标）                sidebar.py:450-472
├── Footer ── _status_bar（固定 28px, 顶部 1px 分隔线）             sidebar.py:215
└── 标题栏齿轮 → SidebarSettingsDialog                              sidebar.py:1376-1390
```

搜索命中时**整行前景变 accent + 加粗 + 背景闪烁**（`QColor(accent).setAlphaF(0.19)`），500ms 后自动消退（`sidebar.py:1129-1149`）。

### 2.3 InfoPanel【信息面板】

`panels/info.py:61` — 继承 `PanelContent`（**不走 StandardPanel**，自持 QSplitter），内部 6 个分区

```
InfoPanel                                                        info.py:61
├── ① 预览区 _preview_host（QSplitter 上段，初始高 160）            info.py:107
│   ├── _PreviewLabel 缩略图（双击发 view_fullscreen 信号）         _info_parts.py:60
│   └── 空态（48px file 图标 + info.no_file_selected）             info.py:120-135
│
├── ② MicroTabBar 微型分段栏（4 页签）                              info.py:150
│   └── 全部 / 标题 / 标签 / 备注                                   info.py:151-155
│
├── ③ 元数据卡片 meta (QGroupBox) ★ Linear 风格                    info.py:172
│   ├── _name 文件名（heading 14 加粗）
│   ├── ⭐ 星级评分行（muted 标签 + 5 个 20×20 星标按钮）           info.py:695-749
│   ├── 5 个字段行（类型/大小/摘要/日期/路径）                       info.py:193-198
│   ├── 链接字段（_DragLabel + 3 个 18×18 图标按钮）                info.py:811
│   ├── DominantPaletteStrip 主色调色带（最多 5 色，点击复制）       info.py:204
│   └── 插件动态字段容器（默认隐藏）                                 info.py:208
│
├── ④ 标签卡片 tags_grp (QGroupBox)                                info.py:220
│   ├── _tags_flow（_FlowLayout 自动换行流布局）                     info.py:226-228
│   │   └── create_tag_chip × N（彩色 chip，带关闭按钮）             info.py:1353
│   ├── + 添加标签（虚线边框 ghost）                                 info.py:235
│   ├── 管理标签（实线 ghost → TagEditorDialog）                     info.py:250
│   ├── 浏览标签（→ TagBrowserDialog）                              info.py:265
│   └── AI 打标（默认隐藏，设置开启后出现）                           info.py:283
│
├── ⑤ 备注卡片 notes_grp (QGroupBox)                               info.py:305
│   └── QTextEdit（防抖自动保存，stretch=1）
│
└── ⑥ 底部操作条 _act_bar（固定 28px，顶部 1px 分隔线）             info.py:321
    ├── 打开（primary, folder 图标）                                info.py:330
    └── 复制路径（secondary, file 图标）                             info.py:342
```

**卡片 QSS**（`info.py:421-455`）注释原文写着 *"modern, cohesive **Linear-style** card container with unbroken hairline border and translucent depth"* —— 半透明面板底（alpha 0.45）+ 发丝描边 + 圆角 md。这是全项目最明确的一次"设计意图自述"。

标签 chip 入场有**交错淡入动画**：每个延迟 50ms，150ms OutCubic，**仅前 8 个**做动画（避免大面积卡顿），并用 LRU 对象池复用（上限 96）。

### 2.4 TagTreePanel【标签树】

`panels/tag_tree.py:30` — 继承 `StandardPanel`

```
TagTreePanel                                                     tag_tree.py:30
├── Toolbar
│   ├── 过滤框 QLineEdit                                          tag_tree.py:46
│   └── 新建标签按钮（secondary, tag 图标）                         tag_tree.py:55
└── Body ── _tree (QTreeWidget)
    ├── 顶层：标签节点 "{tag}  ({count})"                           tag_tree.py:201
    │   ├── human  → 用户自定义图标/颜色
    │   ├── plugin → puzzle 图标（只读投影）                        tag_tree.py:204-212
    │   └── ai     → star 图标（只读投影）
    ├── 子层：文件名                                                tag_tree.py:216
    ├── 空态行 tagtree.no_tags                                     tag_tree.py:183-186
    └── 过滤态返回行 tagtree.show_all                               tag_tree.py:190-193
```

### 2.5 ImageViewerOverlay【图片查看器】★ 全 QPainter 自绘

`panels/image_viewer.py:312` — 继承 `QFrame`，`FramelessWindowHint | Tool | WA_TranslucentBackground`，默认 900×650

```
ImageViewerOverlay（无子 QWidget，chrome 全部手绘）                 image_viewer.py:312
├── 全屏暗化遮罩  QColor(0,0,0,180)                                 :856
├── 容器圆角 10 + panel 填充 + 1px border 描边                       :859-861
├── Header（高 36，圆角 10）
│   ├── 标题 "{name}  {idx+1} / {total}"（加粗 11pt heading）        :872-881
│   └── 关闭按钮（自绘；hover 时填充 danger 色 + 白图标）            :884-900
├── _GraphicsView 画布（QGraphicsView + QGraphicsScene）            :268
│   ├── ScrollHandDrag 抓手 + AnchorUnderMouse 光标锚定缩放
│   └── 滚轮缩放系数 1.12，钳制 [0.05, 64.0]                        :290-298
├── 缩略图条（高 64，圆角 8；当前项 2px accent 边框）                :951-988
├── EXIF 侧栏（宽 200，圆角 8；左标签 muted / 右值 body 两列）        :990-1027
└── Footer（高 28）
    ├── 快捷键提示（9pt muted）
    └── 缩放+尺寸 "{w}×{h}  {zoom}%"
```

⚠️ 该文件**明确注释不使用 QOpenGLWidget**（`image_viewer.py:282-288`）：在半透明顶层窗口上会 access violation，已记录两次 `c0000005` 崩溃，故保持光栅视口。

幻灯片 3000ms / 序列帧 12fps（`image_viewer.py:346-355`）。

### 2.6 EmptyPanel【空态占位】

`panels/empty.py:14` — 三态工厂：`for_loading()` / `for_error()` / 默认 empty，视觉全委托给 `EmptyStateWidget`

---

## 3. 浮层与对话框树（21 个）

### 3.1 独立浮层（3 个）— 全部无边框 + 透明背景 + 阴影 level 3

```
CommandPalette【命令面板】Ctrl+K                                   widgets/command_palette.py:208
├── QFrame#paletteCard（宽固定 560，圆角 md，1px border_subtle）     :236-238
├── 搜索行（16px 搜索图标 + 无边框 14pt QLineEdit）                 :247-271
├── 1px 分隔线 #paletteDivider                                     :280-282
├── 结果列表（最小 240 / 最大 380）
│   └── CommandPaletteDelegate 自绘                                :62
│       ├── 分组头 28px（caption 加粗 muted）
│       ├── 命令行 40px
│       │   ├── 选中：accent α0.22 底 + α0.45 描边 + 圆角 sm
│       │   └── hover：hover_overlay 底，无描边
│       ├── 左图标 16px（选中时 tint 转 accent）
│       └── 右侧快捷键徽章（高 20，圆角 4，panel α0.85 底）          :134-163
└── 底部提示栏（9pt, ↑↓ 选择 / Enter 执行 / Esc 关闭）

QuickLookOverlay【快速预览】空格键                                  widgets/quick_look_overlay.py:164
├── 半透明遮罩（base 色 + alpha 175 纯色填充）                       :559-563
├── QFrame#quickLookCard（占父窗 88%，480–1100 × 360–850，圆角 lg）
├── Header
│   ├── 类型图标 + 文件名（最大宽 420）
│   ├── #quickLookSpecPill 规格胶囊（accent α0.15 底, 等宽字体）     :431-440
│   ├── 索引计数 "n / total"
│   └── 关闭按钮（tooltip "Space / Esc"）
├── Canvas（QStackedWidget 双页）
│   ├── ImageCanvasWidget（SmoothPixmapTransform 居中缩放）         :47
│   ├── GenericFileWidget（48px 分类图标 + 名称/路径/元信息）        :79
│   └── 左右悬浮圆形导航按钮 36×36（圆角 18）                        :302-328
└── Footer ── 快捷键导览条（kbd 键帽样式：Space / Esc / ← → / Enter）

Toast【通知】单例                                                  widgets/toast.py:38
├── 左侧 4px 色条（info=accent / success=success / error=danger）
└── body（panel 底 + 1px border + 右侧圆角 + 阴影 level 1）
    ├── 图标 16px（可选）
    ├── 主文案（heading 12）└── 副文案（muted 11）
淡入 150ms OutCubic / 淡出 300ms InQuad，父窗底部居中，不抢焦点
```

⚠️ **QuickLook 的"毛玻璃"名不副实**：docstring（`quick_look_overlay.py:1-3`）宣称 frosted-glass，实现只是 base 色 + **硬编码 alpha 175** 的纯色矩形，**未做任何背景模糊采样**。

### 3.2 对话框体系（17 个）— 单根继承，风格高度统一

```
QDialog
└── TabbedDialog【基类/模板】★ 事实标准                              dialogs/tabbed_dialog.py:79
    │  构造时强制 setStyleSheet(dialog_css())  :104
    │  自动路由：重写 _setup_tabs → 多页分支(:107)；否则 → 单页分支(:110)
    │  几何记忆：AppSettings 持久化 dialog_geometry_{objectName}    :171-206
    │  唯一动效：150ms OutCubic 窗口淡入（受 reduce_motion 守卫）     :216-228
    │
    ├── StandardModalDialog【单页模板】三段式                        dialogs/modal_dialog.py:26
    │   │  Header（可选图标 + 标题 + 副标题）→ Canvas → Button Bar
    │   │  外边距 16 / 间距 12（比 tabbed 的 12/10 宽松）
    │   ├── ColorPickerDialog      色轮拾色器      color_picker_dialog.py:19
    │   ├── TagEditorDialog        标签编辑        tag_editor_dialog.py:19
    │   ├── TagStyleDialog         标签样式        tag_style_dialog.py:32
    │   ├── ThemePreviewDialog     主题预览        theme_preview_dialog.py:18
    │   ├── ShareQrDialog          分享二维码      share_qr_dialog.py:30
    │   ├── SidebarSettingsDialog  侧边栏设置      sidebar_settings_dialog.py:22
    │   ├── _NoSettingsDialog      无设置项提示    generic_settings_dialog.py:12
    │   └── _OperatorParamsDialog  插件参数表单    plugin_operator_dialog.py:19
    │
    ├── SettingsDialog【设置中心】★ 6 个分类页                       settings_dialog.py:84
    ├── SharingSettingsDialog【共享设置】★ 4 页 + 8 子分区           sharing_settings_dialog.py:71
    ├── ShareLinkDialog            创建分享链接     share_link_dialog.py:24
    ├── UndoPanelDialog            撤销历史        undo_panel.py:50
    ├── ActivityPanelDialog        活动记录        activity_panel.py:65
    ├── PluginManagerDialog        插件管理器      plugin_manager_dialog.py:31
    └── TagBrowserDialog           标签浏览        tag_browser_dialog.py:19

QMainWindow
└── StartupWindow【库启动器】                                       dialogs/startup.py:398

QProgressDialog
└── BusyProgressDialog（不可关闭的不确定进度）                        dialogs/_maintenance_tasks.py:45
```

#### SettingsDialog 的 6 个分类页完整树

```
SettingsDialog (QTabWidget)                                      settings_dialog.py:84
├── [1] 外观 settings.appearance                                 :279
│   ├── 主题分区
│   │   ├── _mode_btn  下拉菜单按钮（暗色/亮色/自定义）              :293-296
│   │   └── _theme_btn 下拉菜单按钮（当前主题名）
│   │        └── QMenu：分组主题（带 accent 色块图标）+ 新建/预览/导入/删除
│   ├── 背景分区：启用勾选 + 图片浏览 + 面板不透明度滑块(30-100)
│   │             + 顶栏不透明度滑块(30-100) + 清除按钮
│   └── 背景特效：效果下拉(无/模糊/马赛克/Kuwahara/Shader)
│                 + 强度滑块(1-50, 150ms 防抖) + 着色器预设下拉
├── [2] 通用 settings.general                                    :647
│   ├── 语言单选组（en / zh / ja）
│   ├── UI 缩放滑块（50-200，刻度 25）+ 百分比标签
│   └── AI 打标分组：启用开关 / Ollama 端点 / 模型名 / 最大标签数
│                    / 强制重打 / 测试连接（工作线程）/ 内联状态
├── [3] 缩略图 settings.thumbnails                                :845
│   ├── 质量单选组（fast/default/high/original）
│   └── 缓存分组：清除缓存 / 重新生成 / 进度条（默认隐藏）
├── [4] 数据库维护 settings.maintenance_title                     :1007
│   ├── 维护：WAL checkpoint / 读取大小 / 完整性检查 + 2 个内联状态
│   ├── 库健康卡片：刷新 / 富文本状态（warning 项标色）/ 打开数据目录 / 清理日志
│   ├── 缓存上限：下拉(1/2/5/10GB/无限制) + 回收 + 状态
│   └── 断链重连：扫描 / 状态 / 全部重连 / 列表（_RelinkRowWidget，上限 500）
├── [5] 备份与恢复 settings.backup_title                          :1066
│   ├── 导出元数据 JSON / 创建备份 ZIP / 恢复 / 状态
│   └── 隔离区状态（最多列 10 条）
└── [6] 插件 settings.plugins_title                               :1206
    └── PluginManagerWidget（嵌入的卡片式插件管理器）
```

#### SharingSettingsDialog 的 4 页 + 8 子分区

```
SharingSettingsDialog（左 nav_rail 216px + 右 QStackedWidget）      sharing_settings_dialog.py:71
│   响应式：宽度 < 800px 时 nav_rail 切换成顶部导航                  :216-224
├── [0] Endpoint / 概览
│   ├── 状态卡：状态圆点 + 状态文案 + "互联网访问" warning 徽章
│   │          + 启停主按钮（停止态变 danger 色）+ URL + 复制/打开/二维码
│   │          + 4 组元数据（IP / 端口 / 连接数 / 流量）
│   ├── 隧道卡（条件构建）
│   └── 最近活动卡
├── [1] 分享链接
│   ├── 过滤行：搜索 + 状态过滤 + 刷新 + 创建链接
│   ├── QTableWidget 6 列（名称/路径/权限/到期/下载数/操作）
│   └── 底栏：全选 + 批量删除 + 状态
├── [2] 访问控制
│   ├── 身份行：管理员名 + accent "管理员" 标签
│   ├── 访客策略：下载/预览/列出 三个勾选（改动即存）
│   ├── 邀请码：生成按钮 + QTableWidget 3 列 + 复制/吊销
│   └── 在线用户：QTableWidget 3 列（用户/IP/端口）
└── [3] 配置（左 170px 导航 + 右堆叠 + 底部变更摘要条）
    ├── §1 network          共享名 / 端口 / 绑定 / 自动启动 / HTTPS 证书
    ├── §2 protection       认证模式 / 密码 / 最大连接数 / 超时 / 速率限制 / 黑白名单
    ├── §3 presentation     主题色 / 欢迎语 / 页脚
    ├── §4 library_scope    5 类包含 / 隐藏文件 / 最大深度 / 排除模式 / 模糊标签
    ├── §5 diagnostics      访问日志 / 路径 / 轮转
    ├── §6 quota            免费下载配额 / 周期 / 限额 / 最小间隔
    ├── §7 mcp              只读令牌状态 + 生成/吊销
    └── §8 internet_access  隧道状态（条件构建）
```

#### StartupWindow【库启动器】— 本目录样式最重的文件

`dialogs/startup.py:398` — **QMainWindow，非模态，自带菜单栏**。⚠️ 注意：**不是首次运行向导**，无步骤页/翻页机制，只有 1 屏 2 态。

```
StartupWindow (740×500, 最小 600×400)                            startup.py:398
├── QMenuBar（非原生）：库菜单（浏览/退出）+ 设置菜单（拉起 SettingsDialog）
├── Hero 卡（qlineargradient 渐变横幅 + 底部分隔线）                 :481-514
│   ├── _hero_title  xxl 加粗
│   ├── _hero_sub    sm muted
│   └── _hero_count  caption（库数量 / 空态文案）
└── 内容行
    ├── 左 _DetailPanel（220-300px, 半透明卡 + 阴影 level 1）        :42 / :521
    │   ├── header / name(xl 加粗) / path(xs muted)
    │   ├── status 胶囊徽章（success/danger + darken 0.25 底）
    │   └── 打开(primary) / 移除(ghost)
    └── 右 _list_panel（渐变卡 + 阴影 level 1）                      :525-611
        ├── "最近" 标题
        ├── QScrollArea
        │   ├── 【有历史】_LibraryCard × N（最多 30，超出显示截断提示） :209
        │   └── 【无历史】空态：首运行标题 + 两张等权卡片                :556-584
        │       ├── _FirstRunCard 新建库（最小高 120, 渐变 panel→base）  :321
        │       └── _FirstRunCard 打开现有
        └── 底部 浏览按钮（secondary, folder 图标）
```

---

## 4. 复用控件（28 个）

### 4.1 容器 / 导航类

| 组件 | file:line | 基类 | 关键视觉 |
|---|---|---|---|
| `TabContainer` | `widgets/tab_container.py:23` | PanelContent | QTabWidget + 角部 `+`，每标签一个 FileListPanel；零自定义样式 |
| `WorkspaceBar` | `widgets/workspace_bar.py:33` | QTabBar | 选中态 `accent α0.18` 底 + `α0.40` 描边 + 顶圆角 md；**自绘 3px 胶囊指示条**贴底，位置+宽度双 `QPropertyAnimation` 200ms OutCubic |
| `MicroTabBar` | `widgets/micro_tab_bar.py:74` | QWidget | **自绘双层胶囊**：底层跑道 `input_bg α0.75` + 上层浮动药丸 `accent α0.24` 底 / `α0.52` 边；`indicator_geometry` 是 Qt Property，单动画驱动整个 QRect |
| `WorkspaceSection` | `widgets/workspace_bar.py:333` | QWidget | `[竖分隔线] [WorkspaceBar] [+ 按钮]` |
| `_FlowLayout` | `panels/_info_parts.py:71` | QLayout | 自实现自动换行流布局，`hasHeightForWidth=True` |

### 4.2 卡片 / 徽章类

| 组件 | file:line | 基类 | 关键视觉 |
|---|---|---|---|
| `PluginCard` | `widgets/plugin_ui.py:42` | QFrame | 固定高 72；状态圆点 10px（danger/success/muted）；选中 `accent α0.13`；hover 边框 `accent α0.5`；版本徽章；44×24 开关 |
| `PluginDetailPanel` | `widgets/plugin_ui.py:182` | QWidget | 阴影 level 1；名称 18pt 加粗；状态徽章实心色底 + `on_accent` 字；诊断框 `danger α0.08` 底 / `α0.19` 边 |
| `create_tag_chip` | `widgets/tag_chip.py:55` | → QWidget | 圆角 sm；有自定义色时用 `contrast_on()` 算黑白字；**明暗主题感知 hover**（暗色 +8% 亮度 / 亮色 −8%）；同义词 tooltip LRU 缓存上限 500 |
| `EmptyStateWidget` | `widgets/empty_state.py:34` | QWidget | **6 态**：directory/search/offline/empty/loading/error；44px 语义图标 + 16pt 加粗标题 + 12pt muted 副标题 + 可选按钮 |

### 4.3 自绘制控件

| 组件 | file:line | 技术 |
|---|---|---|
| `HSVWheel` | `widgets/hsv_wheel.py:28` | QPainter：色相环（**QPixmap 离屏缓存，键 = (size, value)，DPR 感知**）+ `QRadialGradient` 饱和度 + 白12/黑10 双环指示器 |
| `BrightnessSlider` | `widgets/hsv_wheel.py:162` | QLinearGradient 底黑顶亮 + 白/黑双线指示器 |
| `DominantPaletteStrip` | `widgets/dominant_palette_strip.py:22` | 半透明 panel 胶囊底；最多 5 色块（高 20）；**按 Rec.709 亮度自适应描边色**（阈值 0.52）；hover 描边加粗变 accent；点击复制 hex |
| `ImageCanvasWidget` | `widgets/quick_look_overlay.py:47` | `SmoothPixmapTransform` + `KeepAspectRatio` 居中 |
| `GenericFileWidget` | `widgets/quick_look_overlay.py:79` | 48px 分类图标（video/cube/archive/code/file） |
| `CanvasContainer` | `widgets/quick_look_overlay.py:139` | 手动 `move()` 摆放左右导航按钮（不用布局） |
| `SystemTrayManager` | `widgets/tray.py:22` | **QPainter 自绘托盘图标**：accent 圆角方（r=6）+ 居中字母 "A"，仅自绘图标时随主题重绘 |

### 4.4 委托 / 工厂

| 组件 | file:line | 作用 |
|---|---|---|
| `CommandPaletteDelegate` | `widgets/command_palette.py:62` | 见 3.1 |
| `_DetailsItemDelegate` | `panels/file_list/_ui_helpers.py:27` | 强制行高 ≥ 32px |
| `_make_nav_button()` | `panels/file_list/_ui_helpers.py:48` | ghost 图标按钮工厂，26×26，图标 16 |
| `_DragLabel` | `panels/_info_parts.py:27` | 可点击 + 可拖拽到浏览器的链接标签 |
| `_PreviewLabel` | `panels/_info_parts.py:60` | 双击发 `view_fullscreen` |

### 4.5 ThemePreviewWidget 的 10 个预览段

`widgets/theme_preview.py`，全部继承 `QGroupBox`：`_ButtonSection:38` / `_InputSection:63` / `_LabelSection:96`（7 种 label_role）/ `_ListSection:122` / `_TableSection:140` / `_DialogSection:163`（迷你对话框预览）/ `_CheckRadioSection:207` / `_SliderProgressSection:239` / `_GroupBoxSection:263` / `_ColorSwatchSection:299`（32×32 可点击色板 ×18 色）

---

## 5. 风格体系详解

### 5.1 L1 — 主题 token（`core/themes.py`）★ 事实标准

**23 套内置主题**：13 套暗色（`D_*`）+ 10 套亮色（`L_*`），位于 `Assets/Themes/`
> Amber / Charcoal / Default / Dracula / Espresso / Forest / Gruvbox / Midnight / Navy（当前默认）/ Nord / Onyx / Rosepine / Slate
> Coral / Dawn / Frost / Lavender / Lilac / Mint / Peach / Rose / Sage / Silver / Sky

**必填 token（13）**：`base` `panel` `header` `border` `heading` `body` `muted` `accent` `success` `warning` `danger` `favorite` `recent`

**派生 token（28，有回退函数）**：`on_accent` `hover_overlay` `selected_overlay` `border_focus` `input_bg` `input_text` `scrollbar_*` `disabled_*` `tooltip_*` / 7 个 `category_*` 语义文件类别色 / `border_subtle`（= `border` alpha 0.5，用于**层级分隔**而非输入框描边）/ 6 个 `icon_*` 语义图标色

**properties（Navy 实测值）**

| 类别 | 值 |
|---|---|
| `border_radius` | sm **8** / md **10** / lg **14** / xl **20** |
| `spacing` | xs **4** / sm **8** / md **12** / lg **16** / xl **24** |
| `font_size` | xxs 9 / xs 10 / caption 11 / sm 12 / md 13 / lg 14 / xl 16 / xxl 22 |
| `opacity` | hover **0.15** / disabled 0.5 |
| `animation.duration_ms` | **200** |

**metrics（`themes.metrics()`，可被主题覆写）**

| key | 值 | 用途 |
|---|---|---|
| `icon_sm` | 16 | 标准动作图标（dock chrome、面板） |
| `icon_xs` | 12 | 紧凑图标（状态栏、工作区栏） |
| `hit_area` | **24** | 图标按钮热区（无障碍下限） |
| `control_height_md` | **28** | 事实标准控件/状态栏高度 |
| `radius_xs` | 3 | 子 token 圆角（药丸轨道、分隔线） |

**全局 QSS（`themes.stylesheet()`）**：一次性为 `QMainWindow` / `QDialog` / `QDockWidget` / `QMenuBar` / `QMenu` / `QListWidget` / `QTreeWidget` / `QTabBar` / `QLabel` / `QLineEdit` / `QTextEdit` / `QComboBox` / `QSpinBox` / `QHeaderView` / `QGroupBox` / `QScrollBar` 设定基线外观。这是所有组件共享的底色。

### 5.2 L2 — 阴影（`widgets/elevation.py`）★ 唯一真正全局统一

```
_LEVELS = {
    1: (blur 18, offset 0/4,  black alpha  72),   ← 卡片、面板
    2: (blur 24, offset 0/8,  black alpha  88),
    3: (blur 30, offset 0/12, black alpha 104),   ← 顶层浮层
}
```
设计意图（模块 docstring）：**只作用于少数容器 widget，不作用于列表行**，避免滚动视图的绘制开销。

使用点：CommandPalette(3)、QuickLookOverlay(3)、Toast(1)、PluginDetailPanel(1)、StartupWindow 详情卡(1)、StartupWindow 列表面板(1)

### 5.3 L3 — StyleKit（`widgets/stylekit.py`）★ 覆盖率约 50%

**五大能力**（docstring 自述）：Token 安全解析 / QSS 集中生成 / 状态驱动样式 / 动画助手 / Widget 工厂

**核心 API**

| 类别 | API |
|---|---|
| 构造 | `from_theme(themes, px=, pt=)` |
| Token | `token(name)` / `prop(category, key)` / `font_size(key)` |
| 缩放 | `px()` / `pt()` |
| 文本 QSS | `label_css(color, size, bold, bg)` / `heading_css()` / `muted_css()` |
| 状态 QSS | `state_css()` / `state_color()`（5 态：idle/loading/success/error/retry） |
| 容器 QSS | `dialog_css()`（覆盖 20+ 种 Qt 控件）/ `tab_css()` / `nav_css()` / `status_bar_css()` |
| 控件 QSS | `button_css(variant)` / `switch_css()` |
| 工厂 | `make_heading` / `make_muted` / `make_status_badge` / `make_pill_button` |
| **派生色三件套** | `alpha()` / `lighter()` / `darker()` |
| 动画门控 | `reduce_motion()` |

**按钮变体词汇表（4 变体，全应用统一）**

| 变体 | 底 | 字 | 边框 | hover | pressed |
|---|---|---|---|---|---|
| `primary` | accent | on_accent | 无 | `lighter(accent,110)` | `darker(accent,115)` |
| `secondary` | panel | heading | 1px border_subtle | hover_overlay | `accent α0.20` |
| `ghost` | transparent | muted | 1px transparent | hover_overlay + body | `accent α0.20` |
| `danger` | danger | on_accent | 无 | `lighter(danger,110)` | `darker(danger,115)` |

> 设计意图注释（`stylekit.py:431-433`）：hover/pressed 走 canonical 的 HSV lighter/darker 配方，让**全应用所有 accent 按钮手感一致**。

**⚠️ 绕过 StyleKit 的 6 个高频组件**：CommandPalette、QuickLookOverlay、WorkspaceBar、MicroTabBar、ImageViewerOverlay、FileListGridWidget —— 全部裸读 `themes.get()["..."]` + `color_utils.alpha()` 手写样式。

### 5.4 视觉手法统计

| 手法 | 使用组件 | 代表证据 |
|---|---|---|
| **QSS setStyleSheet** | 绝大多数 | 各处 |
| **QPainter 自绘** | 网格画布、图片查看器、MicroTabBar、WorkspaceBar、CommandPalette 行、HSV 色轮、亮度条、QuickLook 遮罩、托盘图标、主题列表色块 | `_grid_widget_render.py:199` |
| **QGraphicsDropShadowEffect** | 6 处浮层/卡片 | `elevation.py:22` |
| **QGraphicsOpacityEffect + QPropertyAnimation** | Toast 淡入淡出 | `toast.py:153-168` |
| **QPropertyAnimation** | MicroTabBar（QRect 滑动）、WorkspaceBar（位置+宽度）、FileList 缩放（OutCubic 220ms）、对话框淡入、Info 预览/chip 淡入、Grid Animator | 各处 |
| **自定义 delegate** | CommandPaletteDelegate、_DetailsItemDelegate | — |
| **QPixmap 离屏缓存** | HSVWheel（DPR 感知）、GridTextureCache（LRU 200） | `hsv_wheel.py:100-132` |
| **渐变** | Grid 卡片、StartupWindow 5 处 qlineargradient、亮度条、HSV QRadialGradient | — |
| **reduce_motion 降级** | Toast、MicroTabBar、Grid Animator、Info、Sidebar、FileList 缩放 | 6 处 |

---

## 6. 一致性诊断（UX 优化锚点）

### P1 — 值得优先处理

| # | 问题 | 证据 | 影响 |
|---|---|---|---|
| 1 | **两套设置中心范式并存** | `SettingsDialog` 用 QTabWidget（`settings_dialog.py:163`），`SharingSettingsDialog` 用左导航+堆叠（`sharing_settings_dialog.py:150-160`） | 同一应用内两种心智模型 |
| 2 | **两套按钮栏顺序相反** | `TabbedDialog` 的 QDialogButtonBox 是 **OK 在最左**（`:312-328`），`StandardModalDialog` 手工布局是 **OK 在最右**（`:110-137`） | 肌肉记忆冲突 |
| 3 | **StyleKit 仅 ~50% 覆盖** | 6 个高频组件绕过（见 5.3） | 主题切换需各文件手动重刷，是最大维护负担 |
| 4 | **`ImageViewerOverlay` 圆角硬编码** | `10/8/4`（`:861,867,889,906,957,996`），未接 `themes.prop("border_radius")` | 与主题 token 脱钩 |
| 5 | **`theme_preview.py` 硬编码颜色孤岛** | 11 个 hex 回退色（`:468-485`），圆角回退 `sm=4/md=6/lg=10` **与 StyleKit（8/10）不一致** | 全 widgets 目录唯一一处 |
| 6 | **QuickLook "毛玻璃"名不副实** | docstring 称 frosted-glass，实现为 base + alpha 175 纯色（`:563`） | 预期与实现偏差 |

### P2 — 可择机收敛

| # | 问题 | 证据 |
|---|---|---|
| 7 | **树 QSS 逐字符重复** | `sidebar.py:1254-1282` 与 `tag_tree.py:91-119` 几乎完全相同，可抽公共 `tree_css()` |
| 8 | **分隔线 token 用法不一** | Info 用 `border`（`info.py:324`），Sidebar/FileList 状态栏用 `border_subtle`（`sidebar.py:1302`/`_base_layout.py:326`），Details 行用 `border-bottom border_subtle`（`_base_layout.py:733`） |
| 9 | **Info 面板两套正交可见性机制** | `MicroTabBar` 4 页签（`info.py:151-155`）与 5 个可独立开关分区（`_show_panel_menu` `info.py:932`）并存，交互上易困惑 |
| 10 | **局部 QSS 三种写法并存** | token 化（推荐）/ 半裸值（`plugin_manager_dialog.py:113-116`）/ 全裸值（`color_picker_dialog.py:178`、`_configuration_page.py:417-426`） |
| 11 | **Ctrl+K 注册表缺失** | `shortcut_manager.py:24-27` 注释称"命令面板已移除，产品无此功能"，但 `window.py:441-443,621` 实际注册了且可用 → 帮助对话框（由该注册表生成）里不会有命令面板条目 |
| 12 | **`set_header()` 能力闲置** | 8 个 `StandardModalDialog` 子类里只有 `ShareQrDialog` 用了（`:46`），头部图标/副标题能力浪费 |
| 13 | **monkey-patch 事件处理** | `theme_preview.py:317` 用 `swatch.mousePressEvent = lambda ...` 覆盖实例方法，而非子类化 |
| 14 | **`reduce_motion` 覆盖不均** | 6 处有处理，但 `ImageViewerOverlay` 无相关判断 |
| 15 | **`StartupWindow` 无真正的首运行引导** | 仅 2 张等权卡片（`:571-581`），无步骤条/翻页/进度指示 |

### 值得肯定的设计

- **无障碍基线扎实**：`hit_area` 24px 热区下限、语义图标属性（`semanticIcon`）在换主题时批量重画、`setAccessibleName` 与 `setToolTip` 成对出现、`_LibraryCard`/`_FirstRunCard` 完整键盘激活
- **几何记忆**：对话框尺寸位置持久化到 AppSettings（`tabbed_dialog.py:171-206`）
- **DPI 适配统一**：`scaled_px` / `scaled_pt` 全量使用，主题/语言/UI 缩放三总线热刷新
- **性能意识强**：Grid 纹理 LRU 缓存、chip 对象池、批量更新抑制绘制、动画对象复用、反锯齿按热路径分级开关
- **崩溃经验已沉淀为注释**：`image_viewer.py:282-288` 记录 QOpenGLWidget 在半透明顶层窗口上的 `c0000005` 事故，明确禁用

---

## 7. 快速索引：62 个可见组件

| # | 组件 | file:line | 基类 | 层级 |
|---|---|---|---|---|
| 1 | MainWindow | `window.py:159` | QMainWindow | 骨架 |
| 2 | MenuWidget 行 | `window.py:637` | QWidget | 骨架 |
| 3 | 自定义 Dock 标题栏 | `dock_factory.py:114` | QWidget | 骨架 |
| 4 | QStatusBar | `window.py:727` | QStatusBar | 骨架 |
| 5 | WorkspaceSection | `widgets/workspace_bar.py:333` | QWidget | 骨架 |
| 6 | 共享开关按钮 | `window.py:661` | QPushButton | 骨架 |
| 7 | **FileListPanel** | `panels/file_list/_base.py:42` | PanelContent | 主面板 |
| 8 | **SidebarPanel** | `panels/sidebar.py:112` | StandardPanel | 主面板 |
| 9 | **InfoPanel** | `panels/info.py:61` | PanelContent | 主面板 |
| 10 | **TagTreePanel** | `panels/tag_tree.py:30` | StandardPanel | 主面板 |
| 11 | **ImageViewerOverlay** | `panels/image_viewer.py:312` | QFrame | 主面板(浮动) |
| 12 | **FileListGridWidget** | `panels/file_list/_grid_widget.py:40` | QWidget | 主面板(内嵌) |
| 13 | EmptyPanel | `panels/empty.py:14` | PanelContent | 主面板 |
| 14 | CommandPalette | `widgets/command_palette.py:208` | QDialog | 浮层 |
| 15 | QuickLookOverlay | `widgets/quick_look_overlay.py:164` | QDialog | 浮层 |
| 16 | Toast | `widgets/toast.py:38` | QWidget(Tool) | 浮层 |
| 17 | TabbedDialog | `dialogs/tabbed_dialog.py:79` | QDialog | 对话框(基类) |
| 18 | StandardModalDialog | `dialogs/modal_dialog.py:26` | TabbedDialog | 对话框(基类) |
| 19 | SettingsDialog | `dialogs/settings_dialog.py:84` | TabbedDialog | 对话框 |
| 20 | SharingSettingsDialog | `dialogs/sharing_settings_dialog.py:71` | TabbedDialog | 对话框 |
| 21 | ShareLinkDialog | `dialogs/share_link_dialog.py:24` | TabbedDialog | 对话框 |
| 22 | UndoPanelDialog | `dialogs/undo_panel.py:50` | TabbedDialog | 对话框 |
| 23 | ActivityPanelDialog | `dialogs/activity_panel.py:65` | TabbedDialog | 对话框 |
| 24 | PluginManagerDialog | `dialogs/plugin_manager_dialog.py:31` | TabbedDialog | 对话框 |
| 25 | TagBrowserDialog | `dialogs/tag_browser_dialog.py:19` | TabbedDialog | 对话框 |
| 26 | ColorPickerDialog | `dialogs/color_picker_dialog.py:19` | StandardModalDialog | 对话框 |
| 27 | TagEditorDialog | `dialogs/tag_editor_dialog.py:19` | StandardModalDialog | 对话框 |
| 28 | TagStyleDialog | `dialogs/tag_style_dialog.py:32` | StandardModalDialog | 对话框 |
| 29 | ThemePreviewDialog | `dialogs/theme_preview_dialog.py:18` | StandardModalDialog | 对话框 |
| 30 | ShareQrDialog | `dialogs/share_qr_dialog.py:30` | StandardModalDialog | 对话框 |
| 31 | SidebarSettingsDialog | `dialogs/sidebar_settings_dialog.py:22` | StandardModalDialog | 对话框 |
| 32 | _NoSettingsDialog | `dialogs/generic_settings_dialog.py:12` | StandardModalDialog | 对话框 |
| 33 | _OperatorParamsDialog | `dialogs/plugin_operator_dialog.py:19` | StandardModalDialog | 对话框 |
| 34 | StartupWindow | `dialogs/startup.py:398` | QMainWindow | 独立窗口 |
| 35 | BusyProgressDialog | `dialogs/_maintenance_tasks.py:45` | QProgressDialog | 对话框 |
| 36 | TabContainer | `widgets/tab_container.py:23` | PanelContent | 复用控件 |
| 37 | ThemePreviewWidget | `widgets/theme_preview.py:352` | QWidget | 复用控件 |
| 38 | PluginDetailPanel | `widgets/plugin_ui.py:182` | QWidget | 复用控件 |
| 39 | SystemTrayManager | `widgets/tray.py:22` | QObject | 系统托盘 |
| 40 | WorkspaceBar | `widgets/workspace_bar.py:33` | QTabBar | 复用控件 |
| 41 | MicroTabBar | `widgets/micro_tab_bar.py:74` | QWidget | 复用控件 |
| 42 | PluginCard | `widgets/plugin_ui.py:42` | QFrame | 复用控件 |
| 43 | EmptyStateWidget | `widgets/empty_state.py:34` | QWidget | 复用控件 |
| 44 | HSVWheel | `widgets/hsv_wheel.py:28` | QWidget | 复用控件 |
| 45 | BrightnessSlider | `widgets/hsv_wheel.py:162` | QWidget | 复用控件 |
| 46 | DominantPaletteStrip | `widgets/dominant_palette_strip.py:22` | QWidget | 复用控件 |
| 47 | create_tag_chip | `widgets/tag_chip.py:55` | → QWidget | 复用控件 |
| 48 | CommandPaletteDelegate | `widgets/command_palette.py:62` | QStyledItemDelegate | 复用控件 |
| 49 | ImageCanvasWidget | `widgets/quick_look_overlay.py:47` | QWidget | 复用控件 |
| 50 | GenericFileWidget | `widgets/quick_look_overlay.py:79` | QWidget | 复用控件 |
| 51 | CanvasContainer | `widgets/quick_look_overlay.py:139` | QWidget | 复用控件 |
| 52 | _GraphicsView | `panels/image_viewer.py:268` | QGraphicsView | 复用控件 |
| 53 | _DetailsItemDelegate | `panels/file_list/_ui_helpers.py:27` | QStyledItemDelegate | 复用控件 |
| 54 | _DragLabel | `panels/_info_parts.py:27` | QLabel | 复用控件 |
| 55 | _PreviewLabel | `panels/_info_parts.py:60` | QLabel | 复用控件 |
| 56 | _FlowLayout | `panels/_info_parts.py:71` | QLayout | 布局引擎 |
| 57 | _advanced_popup | `panels/file_list/_base_layout.py:539` | QDialog(Popup) | 弹出层 |
| 58 | BatchRenameDialog | `panels/file_list/_batch_rename_dialog.py:17` | StandardModalDialog | 对话框 |
| 59 | _DetailPanel | `dialogs/startup.py:42` | QFrame | 嵌入面板 |
| 60 | _LibraryCard | `dialogs/startup.py:209` | QFrame | 嵌入面板 |
| 61 | _FirstRunCard | `dialogs/startup.py:321` | QFrame | 嵌入面板 |
| 62 | PluginManagerWidget | `dialogs/_plugin_manager_widget.py:27` | QWidget | 嵌入面板 |

> 另有 10 个 ThemePreview 预览段（`widgets/theme_preview.py:38-299`）与 `_RelinkRowWidget`（`settings_dialog.py:36`）未单独编号。

---

*本报告为只读调研产物，未修改任何代码。所有行号对应当前工作副本（2026-09-03）。*
