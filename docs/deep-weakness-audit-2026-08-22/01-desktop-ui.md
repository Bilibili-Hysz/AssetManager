# 01 · 桌面 UI 层薄弱项审计（2026-08-22）

**范围**：`AssetsManager/panels/`（含 `file_list/` 17 文件）、`dialogs/`（20）、`widgets/`（14）、`window.py`、`window_coordinator.py`、`window_lifecycle_coordinator.py`、`dock_factory.py`。合计约 28.5k 行。
**基线**：commit `5fbf930` 脏工作树。行号以当日工作树为准。

## 总体评估

这套 UI 层的防御性微观纪律相当高（generation/token 防陈旧回投、TimerHandle 统一取消、weakref 回调、`_event_bridge` 强制队列投递、dock 关闭调用 `shutdown()`），但宏观上有三条系统性弱点贯穿始终：

其一，**UI 线程的有界阻塞被制度化**。库切换/关窗路径上串联了大量 `pool.drain(3000)` / `wait_for_runtime(5s)` / `ffmpeg_pool.waitForDone(10s)` 调用（info、sidebar、file_list、model 各自为政），单个超时是"有界"的，但它们在同一次 closeEvent 中**串行叠加**，最坏可造成十几秒的冻结白屏；此外 `_suppress_libpng_warnings` 的全局线程锁实际上把 3 线程缩略图池的图像解码**完全串行化**，是对"并行加载"设计的自我否定。

其二，**file_list 拆分后的隐式协议网**。5 个 mixin + grid 三 mixin + loader/model/coordinator 之间靠约 200 行 `TYPE_CHECKING` 存根声明互相"签约"，运行时零校验；同时跨模块私有访问密集（`panel._grid_widget._scroll_y`、`file_list._loader`、`server._port`、`file_list._current`），任一重命名会静默破坏多方。拆分是物理的，耦合仍是化学的。

其三，**i18n 覆盖不完整且动画语义有系统性错误**。核心破坏性操作确认框（删除/永久删除/撤销失败）是硬编码英文；而 `windowOpacity` 被反复用于**非顶层子 widget**（InfoPanel 预览淡入、tag chip 淡入、PanelContent 入场），这些动画在 Qt 里对子控件无任何视觉效果——作者在 base.py:46-53 已自认一处，但 info.py 的两处仍在"维护一个不存在的动画"。

## 主要发现（按严重度排序）

### [P1][正确性] TabContainer.restore_state 重复添加标签页 ✓已复核
- 位置：`AssetsManager/widgets/tab_container.py:208-219`
- 证据：`for path in paths[1:]: if path: self._add_tab(path)`（208-210 行）之后，218-219 行又执行了一遍 `for p in paths[1:]: self._add_tab(p)`（且无 `if p` 判断）。
- 影响：dock 拆分（dock_factory.py:231 `_split` → `clone()` → `restore_state`）后，N 个标签页变成 2N-1 个，空路径也会生成空白标签；`active` 索引与面板状态错位。每次拆分/克隆都触发。
- 建议：删除 218-219 行的第二个循环（明显的遗留死代码），补一条多标签 restore 的回归测试。

### [P1][性能] 设置对话框背景滑块拖动 = 每刻度磁盘写 + 全量背景图重解码 + 全局重样式
- 位置：`AssetsManager/dialogs/settings_dialog.py:468-495`（`_on_bg_setting_changed`）→ `window.py:298-326`（`refresh_bg` 清缓存）→ `window.py:243-256`（paintEvent 内同步 `QPixmap(path)` + blur/mosaic）
- 证据：slider `valueChanged` 直连 `_on_bg_setting_changed`，其中 `s.save()` 每刻度落盘一次；`themes.invalidate_cache()` + `parent._on_bg_style_changed()`（window.py:303）会 `themes.apply_to(app)`、重刷所有 dock 标题栏并 `refresh_bg()` 清空缓存；下一帧 paintEvent 在**绘制路径内**同步重读原图并跑 blur/mosaic。`Path(path).is_file()`（window.py:238）也是每帧磁盘 stat。
- 影响：拖动不透明度/效果强度滑块时持续掉帧；大背景图（4K+blur）时每刻度可达几十至上百毫秒。
- 建议：滑块加 debounce（参照 info.py 的 150ms 预览缩放防抖），paintEvent 中绝不做解码——改为后台解码后 `update()`；`is_file()` 结果缓存。

### [P1][性能] 全局 stderr 重定向锁把所有图像解码串行化
- 位置：`AssetsManager/panels/file_list/_loader.py:102-120`（`_suppress_libpng_warnings` 持 `_stderr_redirect_lock` 包住整个 `yield`），调用点 _loader.py:936-937、997-998、198-199
- 证据：`with _stderr_redirect_lock:` 在 `reader.read()` 全程持有模块级 `threading.Lock`；loader 池 `setMaxThreadCount(3)`（:257）、ffmpeg 池 2 线程（:37-38）、bake 任务全部走同一把锁。
- 影响：缩略图"3 线程并行"只在元数据读取阶段并行，实际像素解码全程单线程吞吐；同时重定向期间其他线程写 stderr 的日志会丢失（注释已承认）。
- 建议：只在确有 libpng 告警的格式上包锁；或改用 QImageReader 预检 header 决定是否重定向；至少把锁粒度从"整个 read"降为"dup2 切换瞬间"。

### [P1][性能/正确性] 库切换与关窗路径上串行叠加的 UI 线程阻塞等待
- 位置：
  - `panels/info.py:980-983` `_info_pool.drain(3_000)` + `_size_pool.drain(3_000)`（被 `set_scoped_services`/`prepare_library_switch`/`shutdown` 调用）
  - `panels/sidebar.py:274-275` `_preload_pool.drain(3_000)`
  - `panels/file_list/_base.py:126-127`（`wait_for_runtime` 默认 5s）、`:178`（`_loader.stop()`）
  - `panels/file_list/_loader.py:810-814`（`stop()` 内 `ffmpeg_pool.waitForDone(10_000)`，全局池，等其他面板的 ffmpeg）
  - `panels/file_list/_model.py:835-838`（scan/size 池各 drain 3s）
- 证据：window_lifecycle_coordinator.shutdown_resources 顺序调用 info→sidebar→tag_tree→file_list 的 shutdown，各池 drain 串行累加。
- 影响：正常情况毫秒级返回，但只要有一个 worker 卡在慢速 IO（网络盘、扫描巨型目录），关窗/切库就是数秒到十几秒的冻结；`ffmpeg_pool` 是**跨面板共享全局池**，一个面板关停会等待别的面板的视频抽帧任务。实际卡顿需运行时验证【疑似】，阻塞路径本身【确认】。
- 建议：把 drain 移到后台收敛线程 + 主线程只发 cancel；ffmpeg_pool 改为按面板隔离或引用计数关停。

### [P1][i18n] 核心破坏性操作确认框硬编码英文，绕过 tr()
- 位置：
  - `panels/file_list/_actions.py:375` `f"Move to Recycle Bin?\n\n{names}"`
  - `_actions.py:418-421` `"Permanently delete?...\n\nYou can undo this deletion."`
  - `_actions.py:637-644` `"Undo Failed"` / `"The previous operation could not be completed...Skip this history entry?..."`
  - `_actions.py:482` 默认名 `text="New Folder"`；`:516` `copy_label=" - Copy"`
  - `panels/file_list/_navigation.py:137` `QMessageBox.warning(..., "Error", f"Path not found:\n{path}")`
  - `panels/file_list/_model.py:443` tooltip `f"...{st.st_size:,} bytes\nModified: ..."`
  - `window.py:571` `f"The library switch failed: {exc}"`（window_lifecycle_coordinator.py:104-108 同）
- 影响：中文/日文界面下删除、永久删除、撤销失败、路径不存在等高频与高危对话框永远显示英文；语言切换后也不刷新。
- 建议：全部改走 `tr()`；`_msg(key, fallback)`（dialogs/_sharing_helpers.py 已有此机制）是现成的迁移路径。

### [P2][线程] InfoPanel 预览 QPixmap 在 worker 线程创建
- 位置：`panels/_info_parts.py:184-194、265-267`（`_FileInfoTask._load_preview` 在 BoundedPool 内调用）→ `panels/info.py:1053-1072`（`_load_preview_pixmap` 内 `QPixmap.fromImage(img)`）
- 证据：`_FileInfoTask.run()` 在池线程执行 `_run_scoped()`，其中 `self._load_preview(path, is_dir)` 直接构造 QPixmap 并经 `preview_ready` 信号发出。
- 影响：违反项目自身约定——file_list 管线（_loader.py:699-701 注释）与 image_viewer（image_viewer.py:58-64 "Only QImage crosses the thread boundary"）都严格在主线程做 QImage→QPixmap 转换。QPixmap 属 QPaintDevice，非 GUI 线程创建在部分平台/插件组合下会告警或崩溃【疑似】；同时该 pixmap 未设置 devicePixelRatio，高 DPI 屏上 InfoPanel 预览模糊【确认】。
- 建议：worker 返回 QImage，`_on_preview_ready` 在主线程 `QPixmap.fromImage` 并按 `devicePixelRatioF` 设置 DPR。

### [P2][内存] 网格纹理缓存仅按条目数（200）封顶，无字节上限
- 位置：`panels/file_list/_grid_texture_cache.py:129-135`（`_cache_texture` 的 200 条驱逐）；`_store_texture_bytes`（:121-127）只在 recorder 存在时记账，驱逐逻辑不使用字节数
- 证据：卡片纹理覆盖整卡（缩略图 + 名称 + 副标题），`_render_item` 按 `item_rect * dpr` 分配。缩放 128px + dpr 2.0 时单纹理约 (284×344)×4 ≈ 0.39MB × 200 ≈ 78MB；path 纹理缓存另有 200 条。
- 影响：大缩放 + 高 DPR + 长滚动下纹理常驻内存可观（百 MB 级），且 `texture_cache_bytes` 仅是诊断值而非约束。
- 建议：仿照 `_model._raw_pixmaps` 的 `ByteLRUCache`（256MiB 字节优先）改造；或按 thumb_size 动态调整条目上限。

### [P2][性能] ExtensionCategoryLookup 每次 get 重建整个映射字典，位于渲染热路径
- 位置：`panels/file_list/_common.py:19-27`（`_current()` 每次 build dict）→ 使用点 `_grid_widget_render.py:660`（`_draw_type_icon` 每张非图片卡）与 `_common.py:93`（`_badge_category`）
- 证据：`def get(self, extension, default=None): return self._current().get(...)`，`_current()` 遍历所有类别×扩展构造新 dict。
- 影响：每次纹理烘焙（预算 12 张/帧）对无预览文件执行 1-2 次全量字典重建；目录里非媒体文件多时白白消耗渲染预算。
- 建议：缓存 `_current()` 结果并提供失效钩子（现有的 `refresh_extension_categories()` 正好是空壳，:60-62）。

### [P2][性能] ThumbnailLoader.request() 在持锁状态下做磁盘 getmtime
- 位置：`panels/file_list/_loader.py:597-621`（`:609 current_mtime = os.path.getmtime(file_path)` 在 `self._mutex` 持有区间内）
- 证据：`request()` 由 UI 线程调用（`_load_visible` → 每个可视行）；worker 线程的 `_on_image_loaded`/`_mark_failed` 也竞争同一把 `_mutex`。
- 影响：冷缓存滚动时 UI 线程每行一次 stat 且与 worker 互斥；网络盘/慢速卷上会明显卡滚动条。
- 建议：把 mtime 校验移出锁（先读 mtime，再短暂加锁比对），或缓存目录级 mtime 批量校验。

### [P2][性能] 清空缩略图缓存在 UI 线程逐个删除文件
- 位置：`panels/file_list/_loader.py:1090-1126`（`clear_thumb_cache` 的 `for f in files: os.remove(...)` 循环在调用线程执行）；调用点 `dialogs/settings_dialog.py:1068`（`_clear_thumbnails`，主线程）、`:1084`
- 证据：:1117-1119 注释称"Delete outside the _mutex lock...must not stall the main thread"，但只是移出了 mutex，仍留在主线程同步执行。
- 影响：缓存目录数千文件时设置对话框点击"清除缓存"后 UI 冻结数秒；随后的 regenerate 前置也调用它。
- 建议：删除循环移入 `_cache_io_lock` 保护的后台任务，完成后再回报计数。

### [P2][功能失效] windowOpacity 动画用于子控件——预览淡入与 tag chip 淡入无任何视觉效果
- 位置：`panels/info.py:858-872`（`_animate_preview_in` 动画 `self._preview` 的 `b"windowOpacity"`，`_preview` 是面板内子 QLabel）；`info.py:1171-1190`（`_animate_tag_in`/`_do_fade_in` 对 chip 同样处理，包括 :1150-1152 的"复用时重置 opacity"逻辑）；`panels/base.py:46-59`（PanelContent 入场动画，注释已自认无效）
- 证据：Qt 的 `QWidget.windowOpacity` 只对顶层窗口生效；对比 `toast.py:153-155` 正确使用 `QGraphicsOpacityEffect`。
- 影响：设计中的预览渐显、chip 交错入场动画从未生效；却持续创建 QPropertyAnimation、维护 `chip._fade_anim` 引用与重置分支——纯开销 + 误导性代码。疑似层面还包括 `chip.setWindowOpacity(1.0)` 无法修复"中途隐藏的 chip"（注释声称能修复，:1145-1152）。
- 建议：改用 `QGraphicsOpacityEffect` + `QPropertyAnimation(effect, b"opacity")`（照抄 toast.py），或删除这三处动画。

### [P2][健壮性] sharing 对话框后台回调的 `_closed` 防护不一致 + 裸 singleShot lambda
- 位置：`dialogs/sharing_settings_dialog.py:661、770-771、1000`（`QTimer.singleShot(1500/2000, lambda: self._xxx.setText(...))` 无存活防护）；对比 :508 `_on_poll_result` 与 :1101 `_on_tunnel_result` 有 `self._closed` 检查，而 `_on_shares_loaded`(:709)、`_on_invites_loaded`(:862)、`_on_online_users_loaded`(:956)、`_on_activity_loaded`(:973)、`_on_batch_item_deleted`(:837) 均无
- 证据：对话框关闭（`_on_dialog_closed` 只停轮询定时器与 tunnel worker，:1337-1347）后，仍在飞的 ShareApiTask 完成回调会直接操作已关闭对话框的表格/标签。
- 影响：若 TabbedDialog 被 C++ 销毁（如 WA_DeleteOnClose 变体或父窗口重建），这些槽会抛 RuntimeError；singleShot lambda 在 1.5-2s 后触碰已销毁按钮同理【疑似，取决于对话框销毁策略】。window.py:507-514 的注释明确记录了这类问题的先例与正确做法（成员 QTimer）。
- 建议：所有跨线程完成回调统一加 `_closed` 前置检查；singleShot 改成员 QTimer（share_link_dialog.py:52 已示范正确模式）。

### [P2][架构] 演示层穿透私有成员形成隐式协议网
- 位置（代表性锚点）：
  - `dialogs/settings_dialog.py:1079-1081` `fl._loader`、`fl._lib_root`
  - `dialogs/sharing_settings_dialog.py:474、682、765` `self._server._port`
  - `window.py:363` `self.file_list._current`
  - `panels/file_list/_base_logic.py:84-101` `_cover_view_window(panel)` 读取 `panel._model/_grid_widget/_scroll_y/_grid_layout`
  - `_base_events.py:169、331、445` `self._grid_widget._scrollbar`
- 影响：Protocol 类型（settings_dialog 已为 `_ThumbnailHost` 建了 Protocol）说明作者知道正确做法，但覆盖不全；重构任一私有名会静默炸掉跨模块调用点，且 AST 门禁不拦 presentation 内部的这类耦合。
- 建议：为高频跨模块访问面（loader 控制、server 端口、当前路径、滚动位置）提炼为公开只读属性或小型 Protocol，逐步收紧。

### [P3][行为] 网格 Left/Right 键用 `next(iter(self._selection))` 取锚点
- 位置：`panels/file_list/_grid_widget_interact.py:463-471`
- 证据：set 迭代序任意，多选后按 Left/Right 的行进基准不确定。
- 影响：多选状态下方向键行为不可复现（有时从最小行、有时从任意行算 `row % cols`）。
- 建议：与 `_last_click_row` 对齐（同文件 :477-498 已有该锚点逻辑）。

### [P3][资源] dock 拆分/克隆线性放大线程池与全局注册表
- 位置：`panels/file_list/_base_logic.py:148-187`（每个 FileListPanel 独立 ThumbnailLoader→QThreadPool(3)、cover/scan/size BoundedPool）；`dock_factory.py:231-242` `_split` 无上限；`dock_factory.py:46` `_DOCK_TITLES` 全局 dict
- 影响：反复 Split 会成倍增加常驻线程与池对象（虽各自可关停）；`_DOCK_TITLES` 中被 window.py:1163-1170（插件 dock 移除路径）绕过 `_close_dock` 的 dock 会留下悬挂键，直到下一次主题刷新时 RuntimeError 自愈（dock_factory.py:264-265）。
- 建议：插件 dock 移除也走 `_close_dock` 或显式 pop；考虑拆分数上限。

### [P3][持久化] PanelState 之外仍有直接写 AppSettings 的面板代码
- 位置：`panels/file_list/_base_layout.py:634-637`（`_show_filelist_shortcuts` 直接 `settings.set/save` 标记位）；`panels/sidebar.py:1201` 与 `info.py:801-806` 混用 `persist_panel_state`
- 影响：轻微——标记位属于应用级而非视图状态，但破坏了"panels 一律经 PanelState"的注释契约（base.py:22-24），无验证机制兜底。
- 建议：要么在 PanelState 文档中明确豁免应用级键，要么收敛调用。

## 次要问题清单

- `panels/file_list/_model.py:378-393` — `_wait_for_scan` 里 `app.processEvents()`（仅测试用，但留在生产代码路径中，重入风险）
- `panels/file_list/_base_events.py:167-170` — scroll debounce 先 connect 再 disconnect 再 connect 同一槽，冗余舞蹈
- `panels/file_list/_base_logic.py:566-568` — `_first_image_cache` 满时整表 `clear()` 而非 LRU 驱逐，5000 目录后命中率周期性归零
- `panels/file_list/_grid_widget_render.py:237` — `prioritize_key` 用 `id(entries)` 判变更，CPython id 复用可能造成假命中（极低概率）
- `panels/file_list/_navigation.py:304-351` — 每次导航 deleteLater+重建整条面包屑按钮（深路径 5+ 按钮）
- `panels/sidebar.py:403-405、487-489` — `_populate`/`_load_children` 在 UI 线程同步 `os.scandir` + sorted（语言切换也触发全量重建 :1044）
- `panels/sidebar.py:951` — 每个搜索命中项一个 500ms one-shot 定时器（有 generation+RuntimeError 防护，但量大会堆积）
- `panels/info.py:282、568` — `_read_exif`（PIL 全量解码）在 UI 线程同步执行
- `panels/image_viewer.py:430-452` — `_build_image_list` UI 线程同步 scandir 整目录；`:170-178` wheel 连乘 scale 有浮点漂移（已有 [0.05,64] 钳制）
- `panels/image_viewer.py:239` — `_strip_thumbs` 随浏览增长不修剪（单目录内）
- `dialogs/sharing_settings_dialog.py:1293` — `hash_password`（PBKDF2）在 UI 线程同步执行，约百毫秒级冻结
- `dialogs/sharing_settings_dialog.py:1030-1073` — TunnelWorker QThread 类在方法内定义并动态挂到 self（`_cancel_tunnel_worker` 已处理 park 情况，尚可，但模式脆弱）
- `window.py:455、504` — 实例级猴补 `resizeEvent`/`mousePressEvent`（绕过 Qt 事件机制）
- `window.py:224-230` — 启动淡入动画持有为 `_startup_anim` 但从不 stop（窗口销毁时靠父子关系回收，可接受）
- `widgets/toast.py:41、191-202` — Toast 单例跨父窗口：一个面板的提示会立即顶掉另一处正在展示的提示
- `panels/base.py:54` — PanelContent 入场动画对嵌入式面板无效（自认），但每次 showEvent 仍创建动画对象
- `dialogs/sharing_settings_dialog.py:51-57` — `_PLANNED_ONLY_SETTINGS` 5 个设置项 UI 可改但服务端无消费者（UI 暗示已保存）

## 规模与耦合观察

**行数 Top10（范围内）**：

| # | 模块 | 行数 |
|---|---|---|
| 1 | panels/info.py | 1645 |
| 2 | dialogs/sharing_settings_dialog.py | 1347 |
| 3 | panels/sidebar.py | 1266 |
| 4 | panels/file_list/_loader.py | 1186 |
| 5 | dialogs/settings_dialog.py | 1117 |
| 6 | panels/file_list/_base_logic.py | 917 |
| 7 | panels/image_viewer.py | 912 |
| 8 | panels/file_list/_model.py | 908 |
| 9 | panels/file_list/_actions.py | 822 |
| 10 | widgets/theme_preview.py | 714 |

**耦合热点**：
- **FileListPanel mixin 星系**：5 个 mixin（Navigation/Actions/Layout/Logic/Events）+ 3 个 grid mixin + `_host.py` 契约镜像，四份文件各自以 `TYPE_CHECKING` 存根重复声明同一批宿主方法（如 `_base_logic.py:107-146`、`_base_events.py:47-123`、`_navigation.py:30-55`），合计约 200 行复制契约；`_base.py:192-198` 的 `_host_contract` 断言只在类型检查时生效，运行时零保护。
- **跨层私有访问高频对**：settings_dialog→`file_list._loader/_lib_root`；sharing_dialog→`server._port`（3 处）+ `host._toggle_sharing`；window→`file_list._current`；panel→`grid._scrollbar/_scroll_y`（6+ 处）。
- **全局可变注册表**：`dock_factory._DOCK_TITLES`（被 window.py 反向遍历）、`Toast._instance`（跨窗口单例）、`_loader.ffmpeg_pool`（跨面板共享池）。
- **每个面板自带线程池军团**：FileListPanel 每实例 1×QThreadPool(3) + cover/scan/size 三个 BoundedPool；InfoPanel 3 个池；ImageViewerOverlay 1 个池——克隆/拆分即复制整套。

**修复参照**（本仓库内已验证的正确模式）：file_list 的 generation/token 陈旧回投防线、`_background.py` 的 runnable 保活协议、`_event_bridge` 的强制队列投递、settings_dialog 缩略图再生的 Shiboken.isValid 信号桥（:1109-1117）——上述 P1/P2 的修复可以直接套用。
