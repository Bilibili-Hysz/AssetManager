# AssetManager 桌面端 UI/UX 设计合理性评审报告

> 日期：2026-08-29 · 分支 `feat/quality-audit-2026-08-17` · 方法：4 路代码审查（主题体系/对话框/面板/a11y-i18n）+ 冻结审计对账 + PySide6 offscreen 真实主题 QSS 渲染目检（`tmp/ux_review/*.png`）
> 边界：渲染证据产生于 offscreen 平台，标注"需真机复核"的条目在结论中已剔除平台假象；所有代码结论带 file:line。

---

## 总评

**工程化基础扎实，交互骨架成熟，但存在一条系统性主题渲染缺口和一批可低成本修复的高危交互缺陷。**

做得好的（有证据）：
- **设计令牌体系完整**：13 个核心色 + 25 个扩展令牌（fallback lambda 链）+ properties 四类（radius/spacing/font_size/opacity），插件可注册令牌（`core/themes.py:79-151`）；全部 QSS 经 `scaled_px/scaled_pt` 缩放，`scripts/check_style_sources.py` 五类规则进 pre-commit 与 CI，历史 118 处字面 px 已清零。
- **长任务反馈体系完备**：导入可取消（window.py:1075-1099）、备份/还原后台 worker + busy 对话框（dialogs/_maintenance_tasks.py）、LAN 启停全链路反馈（sharing_settings_dialog.py:414-587）、UI 层 grep 不到主线程 sleep。
- **TabbedDialog 统一几何记忆 + 生命周期钩子**（dialogs/tabbed_dialog.py:210-280）。
- **i18n 856 key × 3 语言实测集合一致**，命名占位符、无有害拼接；快捷键有集中注册表 + 注册表生成帮助页 + 防漂移测试。
- **确认框范本已存在**：删除自定义主题 = 默认 No + 显示主题名 + 回收站兜底（settings_dialog.py:475-484）；永久删除在撤销服务缺失时拒绝执行（_actions.py:457-466，"确认框承诺了可撤销，无法兑现则拒绝"）。
- 崩溃标记 + 下次启动提示（app.py:170-181）是好的信任设计。

---

## 高严重度发现（建议优先修复）

### H1. 8 处删除确认框未指定默认按钮 —— 回车即删除
`QMessageBox.question` 静态调用不传 defaultButton 时 Qt 默认聚焦 Yes：
- `panels/file_list/_actions.py:406-408`（删文件进回收站）
- `panels/tag_tree.py:281-286`（删标签）
- `dialogs/tag_editor_dialog.py:257-261`（批量删未使用标签）
- `dialogs/sharing_settings_dialog.py:783-788、814-819`（删共享链接）
- `dialogs/settings_dialog.py:1161-1165、1216-1220`（清缓存/重建）

安全范本可照抄：`settings_dialog.py:477-484`、`window.py:977-984`、`_actions.py:745-747`（显式 `StandardButton.No`）。修复成本低、收益最高。

### H2. 深色主题下原生调色板残留（离屏渲染实证）
全局 QSS（`core/themes.py:573-707`）不含 `QCheckBox::indicator` / `QRadioButton::indicator` / `QProgressBar` / `QSlider` / `QToolTip` 任何规则（grep=0），且 app 从不设置深色 QPalette。后果（`tmp/ux_review/clean_gallery_Navy.png`、`crop_groupbox_v2.png`）：
- 深色主题下复选/单选指示器为**白色实心方块/圆**，刺眼；
- QProgressBar 未充填轨道为**纯白**（蓝色 chunk + 白轨道）；
- QSpinBox 上/下箭头深色on深底几乎不可见；
- tooltip 走原生浅色（`tooltip_bg/tooltip_text` 令牌在每个主题 JSON 里都定义了，却只有 `widgets/stylekit.py:417-418` 的局部样式在用）。

浅色主题（Silver）渲染一致无此问题。stylekit 在自己包装的控件里补过 radio indicator（stylekit.py:340-345），但 `tabbed_dialog.py:504-507 make_checkbox` 返回裸 QCheckBox。**建议：全局 QSS 补 `::indicator`/`QProgressBar`/`QSlider`/`QToolTip` 规则（一次性根治），或按主题设置 QPalette。**

### H3. 缩略图加载失败永久静默
`panels/file_list/_loader.py:706-710` 失败路径直接静默 return；`:862-864` 失败表 2000 上限**整体清空**；`_grid_widget_render.py:517-524` 失败与加载中是同一个空白占位。用户无法区分"没加载完"与"加载失败"，本会话内无自愈。提交 84a2872 在 WebUI 侧修了同构问题（分片 + 失败 60s 冷却自愈），桌面端应补等价机制（失败角标 + 冷却重试）。

### H4. 拖放语义：拖入即移动无确认 + 拖出假死
- 库内来源 drop **默认移动**、无修饰键分支、无确认（`_base_logic.py:661-703`）——移动是高危语义；
- 网格从不发起拖出（`_grid_widget_interact.py:400-404` 注释自认）；详情视图 `setDragEnabled(True)` 但模型无 `mimeData`（`_base_layout.py:254-256`）——**看起来能拖实际无效**；
- 无"拖到标签"目标。
建议对齐资源管理器惯例：默认复制、Alt=移动、库内移动可配置确认。

### H5. 点 X 静默隐藏到托盘，LAN 服务器继续运行
`window.py:1293-1299`：有托盘且非 `_force_quit` 时 `hide()+ignore()`，无任何提示（i18n 无"已最小化到托盘"文案），而 LAN 共享服务可能仍在对外服务。叠加**无单实例保护**（全库无 QLocalServer/QSharedMemory/文件锁），双开将并发写设置、争抢 LAN 端口。建议：首次隐藏托盘气泡 + 关闭行为设置项 + 单实例锁。

### H6. 网格逐项读屏不可达 + 焦点可见性缺口
自绘网格只有容器级 Alert 播报（`_grid_widget_data.py:140-146`），作者自注 per-item 为 follow-up（`:95-102`，测试 `test_file_list_grid_a11y.py` 钉死该基线）；主题 QSS 无 `QComboBox:focus`，QCheckBox/QRadioButton 仅变色（stylekit.py:337）——键盘用户在设置对话框大量 combo/复选上找不到焦点，且 1px 边框替换式 focus 会引起布局抖动（themes.py:614,633）。

---

## 中严重度发现

### M1. 设置对话框保存语义自相矛盾
外观/语言/缩放/缩略图质量**点击即存且不可回退**（settings_dialog.py:296-300、1056-1057、1157-1158），但底部仍渲染 Ok/Cancel/Apply（tabbed_dialog.py:393-402）——点 Cancel 的用户预期"放弃更改"实际不成立。sharing_settings_dialog 是另一套标准（dirty 追踪 + Apply，:365/380）。应统一为二选一。

### M2. 标签功能被模态对话框与单标签模型锁死
TagBrowserDialog `exec()` 应用模态 + 点文件行即 accept 关闭（tag_browser_dialog.py:43-46）——名为 Browser 实为一次性 picker；`_active_tag_filter: str | None` 单值（tag_tree.py:36），无 AND/OR 组合；批量打标签是单个 `QInputDialog.getItem`、"管理标签"只认 `paths[0]`（_actions.py:845-874）。标签是资产管理的核心检索手段，建议非模态化 + 多选 AND/OR 明示。

### M3. 错误呈现过度依赖弹窗且不可复制
warning 49 处/critical 7 处分级失真（主题名重名也用 warning，settings_dialog.py:430）；`settings.error_no_library` 同一句话在同一对话框弹 9 次（:786-953）；无一处 DetailedText/可复制；行内校验仅 sharing 一处（sharing_settings_dialog.py:1151-1161）。info 面板备注自动保存成功静默、失败仅日志（info.py:1404-1433）。

### M4. "可撤销"是暗功能
标签删除已入撤销栈（ed68f7e），但删除后无"Ctrl+Z 可撤销"提示；file_list 删除/粘贴等核心操作不接 Toast 体系（`_actions.py` 中 Toast 零命中）。撤销能力用户不可发现。

### M5. file_list 空态/错误态无引导无动作
四种状态均为一行灰字（_status_helpers.py:24-36）：错误态无"重试"按钮、空目录无"新建文件夹/返回上级"、过滤后空态无"清除过滤"——而 `panels/empty.py:36-38` 的引导文案组件已存在却未被复用。

### M6. i18n 英文泄漏与逻辑耦合
- `widgets/tag_chip.py:78、106-108、126-128`：`"Tag: {tag}"` 等英文硬编码进 accessibleName/tooltip（zh/ja 读屏用户读到英文）；
- `widgets/theme_preview.py:72-91`："Text input" 等英文占位符用户可见；
- `panels/file_list/_detail_model.py:279`：`if text == "Empty"` ——**以英文文案做解析逻辑**，zh/ja 下该路径静默退化为 0，属隐性 bug；
- 无键集合级 parity 门禁（`check_doc_stats.py:104-106` 只对计数，键集不同不报警）。

### M7. 快捷键多源维护 + 冲突检测薄弱
FileList 19 条快捷键走 keyPressEvent 手工分派、游离于 ShortcutManager 注册表外（`panels/file_list/_shortcuts.py:8-46`）；F4 面板帮助是第三份手写列表（`_base_layout.py:665-686`），与 `_commands.py:37-40`"single source of truth"注释矛盾；注册表冲突仅 warn-and-replace（shortcut_manager.py:63-71），无跨作用域冲突门禁；全程未用 `QKeySequence::StandardKey`（对非 QWERTY 布局不友好）。

---

## 低严重度 / 打磨项

- **默认按钮全为主色**：全局 QSS 默认 QPushButton = accent 主色（themes.py:626-630），未显式设 variant 的按钮与 primary 无法区分——视觉层级被抹平（渲染图"默认样式"与"主按钮"完全同色）。建议默认改 secondary。
- **视图只有网格/详情两种**且用下拉框切换（_base_layout.py:148-153），缺低密度列表视图；README 宣称"网格/列表/详情"与实际不符。
- **CJK 排版无显式保障**：全仓无 font-family/回退链配置（依赖系统隐式回退）；`scaled_pt` 下限 6pt（ui_scale.py:23-24）对 CJK 密集标签过小；"标签：值"拼接用半角冒号（_actions.py:889-893）。
- **搜索历史 completer 不热更新**（_base_layout.py:419-426，重建面板才可见）。
- **备份/恢复不可取消且无进度百分比**（_maintenance_tasks.py:65-75，GB 级库只能干等）。
- **新增/重命名标签走原生 QInputDialog**（tag_tree.py:219-242），与整体自定义对话框风格割裂。
- **image_viewer 快捷键齐全但无按钮**（仅底部一行提示文案），键盘依赖偏重；旋转无"重置"一键。

---

## 与既有审计的对账（避免重复立项）

**仍开放（本文档引用原锚点即可）**：stderr 重定向锁串行化图像解码（P1，_loader.py:150）；关窗/切库串行 drain 叠加（info.py:995/997、sidebar.py:280）；windowOpacity 子控件无效动画三处（info.py:874、1215，base.py:49-54 还被测试锁住）；sharing 对话框 `_closed` 防护缺口 5 处；纹理缓存无字节上限（_grid_texture_cache.py:129-135）；`_DOCK_TITLES` 重开库残留（dock_factory.py:46,265）；托盘 close 只隐藏（window.py:1296-1297）。

**已修但文档未标记**（冻结审计状态注记挂起中，以下为 git 实证）：b8fb299（tab_container 双循环、QPixmap 线程、清缩略图缓存后台化、背景滑块防抖、错误文案 i18n、LAN toggle 移出 GUI 等待、启动卡片键盘可达）；072f9b1（崩溃可见性）；fc47beb（24 主题 WCAG 对比度）；6559b6d（网格 QAccessible 基线 + px 门禁）；922c931（删主题确认+回收站）；49b7ede（ShortcutManager 接线 + 默认表清理）。**全库 UI 修复状态目前没有任何一份文档是权威现值。**

**reports 层 40 条清单**（ui-optimization-priority / panel-uiux-composition-audit，2026-08-15）：P0 四条全落地；仍开放的有 tag chip 键盘可达、面包屑当前段高亮、StyleKit 单例模式（info.py 12 处 `StyleKit.from_theme`）等。

**设计决策澄清**：MainWindow 不挂 tag_tree dock 是**有意设计**（window.py:236-239 注释，tag 功能归 TagBrowserDialog）——但该决策把标签检索锁进了模态 picker（见 M2），设计意图与交互代价需要重新权衡。

---

## 渲染目检的假象排除记录（防后续误报）

1. **"QMessageBox 深色主题白底"不成立**：offscreen 对照实验（`tmp/ux_review/probe_dialogs.py`、`bisect_msgbox.py`）+ 调色板内省证明 QMessageBox 正确跟随主题（Navy #1a1d28 / Silver #f8f9fc / Dracula #282a36）。早期"白底"截图为同名文件读取假象。
2. **"工具栏浅色带 + 图标不可见"不成立**：全应用不使用 QToolBar（grep=0），画廊中的工具栏是评审脚本虚构的结构。真实面板头部走 PanelContent 背景。
3. **"CJK 豆腐块"是 offscreen 平台字库假象**，非应用 bug；但与"无显式 CJK 回退链"的风险相关，建议真机复核一次 zh/ja 界面字体观感。

## 证据文件

`tmp/ux_review/`：clean_gallery_Navy.png / clean_gallery_Silver.png（主画廊）、crop_groupbox_v2.png（白色指示器）、crop_progress_*.png（进度条轨道）、probe_*/bisect_*（QMessageBox 对照实验）、render_gallery.py（可重跑）。
