# FileList 模块架构审查（2026-08-15）

> 状态更新（同会话收尾）：§6 的 **#1–#8 已全部落地并提交**——#1 合并 Toast、#2 `FileSystemModel` 访问器、#3 统一自然排序、#4 删死代码、#5 抽状态/反馈纯助手、#6 拆 `GridTextureCache`/`Animator`、#7 `FileListHost` Protocol、#8 首图收敛。详见提交 `2cec322`、`a1e8a17`、`60fee44`、`f808baa`、`575541a`。

范围：`AssetsManager/panels/file_list/`（约 5900 行）及其直接协作对象（`controllers/file_list_controller.py`、`application/asset_filters.py`）。目标：评估模块划分、职责边界、耦合与重复，给出可执行的重构建议，不做代码改动。

## 1. 模块地图

| 文件 | 行数 | 职责 | 性质 |
| --- | ---: | --- | --- |
| `__init__.py` | 8 | 导出 `FileListPanel` | 门面 |
| `_base.py` | 1675 | `FileListPanel` 主体 + 组合 mixin 的胶水 | **上帝对象** |
| `_grid_widget.py` | 1741 | 自绘网格画布（纹理缓存/动画/交互/缩放/改名/主题） | **上帝对象** |
| `_loader.py` | 1013 | 缩略图线程池 + 内存/磁盘缓存 + 延迟队列 | 大而内聚 |
| `_model.py` | 674 | `FileSystemModel`：异步扫描/排序/过滤/目录大小 | 模型 |
| `_actions.py` | 657 | `ActionsMixin`：剪贴板/文件操作/撤销/标签/批量重命名 | mixin |
| `_navigation.py` | 286 | `NavigationMixin`：面包屑/历史/FS watcher | mixin |
| `_detail_model.py` | 292 | Details 视图的虚拟模型（读 `FileSystemModel`） | 模型 |
| `_batch_rename.py` | 100 | 纯批量重命名规划/校验 | **纯逻辑 ✓** |
| `_grid_layout.py` | 91 | 纯几何：列/行/命中/可见行 | **纯逻辑 ✓** |
| `_batch_rename_dialog.py` | 82 | 重命名预览对话框 | 视图 |
| `_ui_helpers.py` | 80 | 无状态 UI 助手（按钮/占位/首图/命令组） | 助手 |
| `_thumbnail_delivery.py` | 66 | 主线程缩略图批量失效协调 | 协调器 |
| `_commands.py` | 59 | 命令投影（快捷键↔命令ID、上下文菜单） | 纯逻辑 ✓ |
| `_background.py` | 56 | 通用后台 QRunnable 包装 | 基础设施 |
| `_common.py` | 53 | 常量 + 徽标映射 | 常量 |
| `_toast.py` | 48 | 本地简易 Toast | 视图 |
| `_shortcuts.py` | 41 | 键盘分发 | 分发 |

## 2. 组合结构

`FileListPanel(NavigationMixin, ActionsMixin, PanelContent)`：

- `PanelContent`（基类）：`content_layout`、bus/domain-event 连接、`shutdown`。
- `NavigationMixin`：导航 + 文件系统监听。
- `ActionsMixin`：剪贴板/文件操作/撤销/标签。
- `_base.py` 主体：工具栏、搜索、状态栏、视图切换、缩略图编排、选择捕获/恢复、扫描生命周期、主题/缩放/语言刷新、拖放、上下文菜单构建。

网格画布（`_grid_widget`）与详情视图（`_detail_view` + `_detail_model`）是 `FileListPanel` **组合**的两个子视图，共享同一个 `FileSystemModel`。这是优点——画布没有继承面板。

数据流：`FileSystemModel` ⇄ `FileListGridWidget`（信号）；`ThumbnailLoader` → `ThumbnailDeliveryCoordinator` → `GridWidget`；`FileSystemModel` → `DetailModel`；`FileListPanel` 居中编排。

## 3. 优点（保持）

- **纯逻辑抽离干净**：`_batch_rename.py`（规划/校验）、`_grid_layout.py`（几何）、`_commands.py`（命令投影）、`_common.py`（映射）都是无 Qt 状态、可单元测试的纯函数。
- **模型/视图分离**：`FileSystemModel`（异步扫描 + 排序过滤）与画布解耦；缩略图加载正确线程化（QThreadPool + 内存/磁盘缓存 + 延迟队列 + generation 失效）。
- **服务注入合规**：通过端口（`file_operation_service`/`tag_service`/`metadata_service`/`thumbnail_service`）注入，不持有 Connection/Repository，符合五条边界规则。
- **代际令牌防陈旧**：`scan_generation`、`dir_size_gen`、loader `runtime_generation` 用于丢弃过期异步结果，模式一致。
- **预算限流**：纹理重建 12/帧、缩放目标 6/帧，绑定每帧开销。

## 4. 架构问题（按严重度）

### 🔴 4.1 上帝对象

- **`_base.py`（1675 行）** 集成了：工具栏/搜索/面包屑/状态栏、视图切换、缩略图编排（`_load_visible`/`_on_thumbnail_ready`）、选择捕获/恢复（`_capture_grid_selection`/`_select_grid_paths`/`_selected_detail_paths`）、扫描生命周期（`_on_scan_started`/`_on_scan_committed`）、操作反馈、拖放、命令菜单构建（`_build_context_menu`/`_selected_commands`/`_empty_commands`）、主题/缩放/语言刷新。任何操作都要在这里分支 `grid vs Details`。
- **`_grid_widget.py`（1741 行）** 混合了「渲染」（纹理缓存、占位、缩放、合成）与「交互」（鼠标/键盘/框选/改名编辑器/滚轮缩放）与「动画引擎」与「主题/缩放度量」。渲染缓存 + 动画引擎本身约 400+ 行，值得独立成 `GridTextureCache` + `Animator`。

### 🔴 4.2 跨模块访问私有状态

`FileSystemModel` 的 `_entries`/`_raw_entries`/`_path_index`/`_stat_cache`/`_icons`/`_raw_pixmaps`/`_subtitle_cache`/`_dir_size_cache` 被四处直接访问：

- `_base.py`（`_capture_grid_selection` 读 `_path_index`，`_compute_total_sz` 读 `_cached_stat`，`_on_dir_size_ready` 写 `_subtitle_cache`）
- `_detail_model.py`（`set_source` 读 `_entries`，`_icon_for` 读 `_icons`，`_size/_date_sort_value` 读 `_cached_stat`/`_dir_size_cache`/`_subtitle_cache`）
- `_thumbnail_delivery.py`（写 `_raw_pixmaps`）
- `_grid_widget.py`（读 `_path_index` 等）

没有访问器边界，模型内部一改就牵动四个调用方。

### 🔴 4.3 双视图堆栈导致的手工状态翻译

网格是自绘 `QWidget`（`_selection: set[int]`），详情是 `QTreeView` + `QItemSelectionModel`。二者共享 `FileSystemModel` 但选择/编辑/命中/排序机制完全不同，`_base.py` 里用 `_pending_selection_paths`/`_pending_detail_paths`/`_pending_operation_selection` 手工互译。这是 `_base.py` 复杂度的主要来源，也是「grid vs Details」分支散布各处的根因。

### 🟡 4.4 重复实现

1. **两个 Toast**：`file_list/_toast.py`（48 行，简易）与 `AssetsManager/widgets/toast.py`（带 elevation/图标/级别/阴影边距）。面板用的是本地版，两者已分叉。
2. **自然排序**：`_detail_model._natural_key` 复制了 `asset_filters.natural_key`（`FileSystemModel._apply_sort` 用的同一套）。`DetailModel._do_sort` 还重实现了「目录置顶 + size/date/tags」排序语义，与 `_apply_sort` 部分重复，存在漂移风险。
3. **「首图」逻辑四处实现**：`asset_filters.find_first_image`、`controllers/file_list_controller.find_first_image/_scan_first_image`、`lan/routes/_helpers.find_first_image`、`file_list/_ui_helpers._first_image_in`。其中控制器里那套（`find_first_image`/`_scan_first_image`/`clear_first_image_cache`/`compute_status_text`/`compute_total_size`）**全代码库无调用者，是死代码**。

### 🟡 4.5 `FileListController` 是杂物袋

`controllers/file_list_controller.py` 里混着：纯格式化（`format_total_size_suffix`/`compute_total_size`/`compute_status_text`）、搜索历史持久化、以及一半死代码（首图扫描）。它叫 "Controller" 但几乎不控制任何流程——真正的控制流都在 `FileListPanel`。职责不内聚。

### 🟡 4.6 mixin 隐式接口

`NavigationMixin`/`ActionsMixin` 通过 `TYPE_CHECKING` 声明期望的主机属性（`_model`/`_loader`/`_current`/`_view_mode`…），并直接深挖 `_model`/`_detail_model` 内部。没有显式 Protocol 约束，宿主与 mixin 是脆弱的隐式契约。

### 🟡 4.7 目录大小的职责分散

目录大小异步计算（QThreadPool + 队列 + 限流）在 `FileSystemModel`；缓存更新 + `dataChanged` 发射在 `_base._on_dir_size_ready`（还直接写 `_model._subtitle_cache`）；`_detail_model` 又直接读这些缓存做排序/显示。一条「目录大小」链路横跨三处。

### 🟢 4.8 次要

- 主题/缩放/语言刷新手工铺开（`_on_theme_changed`/`_on_ui_scale_changed`/`_refresh_language`/`_apply_detail_theme`/`refresh_theme`/`refresh_scale`），无统一的「重刷 chrome」契约。
- `_background._orphan_ops` 模块级全局集合防 GC（正确，但是隐晦的全局状态）。
- `_base._toast()` 与 `_show_operation_feedback()` 两条反馈通道并存。

## 5. 边界合规

- 应用参数/返回值无 URL/HTTP 语义 ✓
- 表现层不持有 Connection/Repository，只用注入端口 ✓
- 校验集中在服务层；`_batch_rename` 的校验属于 UI 预览层，可接受 ✓
- 各端只组装自己的服务 ✓

（跨模块访问 `FileSystemModel` 私有属性属于**表现层内部**的耦合，不违反上述边界规则，但仍是 4.2 的可维护性问题。）

## 6. 建议（按收益/成本排序）

1. **合并两个 Toast**（成本低）：面板改用 `widgets/toast.py`，删除 `_toast.py`。
2. **给 `FileSystemModel` 加访问器/只读视图**（成本中，收益高）：暴露 `entry_at`/`path_at`/`cached_stat`/`dir_size(subtitle)`/`icon_for`/`raw_pixmap`，替换四处的 `_私有` 直读。
3. **统一自然排序**：`DetailModel` 复用 `asset_filters.natural_key`（及 `sort_key_for_entry`），删本地 `_natural_key`。
4. **删除死代码**：清理 `FileListController` 的 `find_first_image`/`_scan_first_image`/`clear_first_image_cache`/`compute_status_text`/`compute_total_size`（确认无调用后）。
5. **拆 `FileListPanel`**（成本高，收益高）：抽出 `SelectionCoordinator`（grid↔detail 选择互译）、`StatusPresenter`、`ThumbnailOrchestrator`，让 `_base.py` 退回「组装者」。
6. **拆 `FileListGridWidget`**：`GridTextureCache`（纹理 LRU + 预算 + 路径缓存）与 `Animator`（淡入/hover/选择/入场）独立成协作对象。
7. **为 mixin 定义显式 `Protocol` 宿主接口**，替换 `TYPE_CHECKING` 隐式假设。
8. **收敛「首图」为单一实现**（跨模块）：以 `asset_filters.find_first_image` 为准，其余删除或转调。

## 7. 结论

模块的**纯逻辑层与线程化边界**设计良好，服务注入合规；主要债务集中在两个上帝对象（`_base`、`_grid_widget`）、跨模块私有状态直读、双视图堆栈的手工选择翻译，以及若干跨模块重复（Toast/自然排序/首图）。这些都是「可维护性/演进速度」层面的债，而非当前正确性缺陷；建议按 §6 顺序逐步偿还，优先做 1–4（低风险高收益），5–8 作为后续结构优化。
