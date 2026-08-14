# FileList 视图刷新链路审计（2026-08-15）

范围：`AssetsManager/panels/file_list/` 下所有会触发视图刷新的操作，追到最终 `QPainter` 落屏为止。目标：确认正确性、找出多余的刷新工作、定位性能风险。

## 1. 组件与职责

| 组件 | 职责 | 刷新相关接口 |
| --- | --- | --- |
| `_base.FileListPanel` | 工具栏/导航/动作/状态栏，连接 model 与 grid | `_post_refresh`、`_load_visible`、`_on_*` 处理器 |
| `_model.FileSystemModel` | `QAbstractListModel`，异步目录扫描、排序、过滤、目录大小 | `set_directory`、`set_sort`、`set_filter`、`refresh`、`dataChanged` |
| `_grid_widget.FileListGridWidget` | `QWidget` 自绘画布，纹理缓存 + 视口合成 | `_request_frame`、`paintEvent`、`invalidate_textures`、`commit_thumbnail_rows`、`update_layout` |
| `_grid_layout.GridLayout` | 纯几何：列/行/命中/可见行 | `compute`、`visible_rows`、`rect_at` |
| `_loader.ThumbnailLoader` | 线程池缩略图加载 + 内存/磁盘缓存 | `request`、`thumbnail_ready`、`retain_deferred` |
| `_thumbnail_delivery.ThumbnailDeliveryCoordinator` | 主线程把缩略图结果合并成批量失效 | `handle_ready`、`flush` |
| `_navigation.NavigationMixin` | 面包屑/历史/FS watcher | `navigate_to`、`_on_fs_changed` |

## 2. 刷新调度核心

### 2.1 帧请求合并（`_grid_widget._request_frame`）

所有视觉失效都走 `_request_frame(rows, full=, overlay=)`：

- 用 `_frame_queued` + `QTimer.singleShot(0, _flush_frame)` 把同一事件循环内的多次失效合并成 **一次** `update()` / `update(rect)`。
- `full=True` 时 `update()`（整块重绘）；否则把 `rows` 对应的视口矩形（overlay 加 5%+6px 抬升余量、普通加 2px）合并成一个脏矩形 `update(rect)`，让 Qt 只在脏区重绘。
- 记录 `grid.frame_request` 指标。

### 2.2 两遍绘制（`paintEvent`）

1. **Pass 1 — 纹理构建（预算受限）**：遍历可见行，`dirty` 且预算未超 `_FULL_REBUILD_TEXTURE_BUDGET=12` 时调用 `_render_item` 离屏渲染卡片 → `_cache_texture`。每帧最多构建 12 张，其余延期到下一帧（`_queue_full_rebuild_update`）。
2. **Pass 2 — 落屏**：
   - **非缩放**：先走视口合成 `_viewport_compose` 得到一张整视口纹理，`drawPixmap(0,0,viewport)`；再在其上叠画 hover 抬升卡片与交互覆盖层（选择/hover 圆角高亮）。
   - **缩放中**（`_zoom_relayout_active`）：走逐单元路径，用 `_current_visual_rect` 做几何插值，`_zoom_fallback_textures` 兜底新露出的行。

### 2.3 视口合成缓存（`_viewport_compose`）

一张 DPR 感知的离屏 `QPixmap`（`_viewport_tex`）+ ping-pong 草稿 `_viewport_scratch`：

- **全量合成**当：纹理尺寸变化（`size_changed`）、epoch 不匹配、`tex is None`、`not allow_scroll`、或 `abs(dy) >= height`。
- **增量滚动 blit**否则：把旧合成 `drawPixmap(0,-dy,tex)` 平移，只填新露出的条带 + 重绘条带与脏行。
- `allow_scroll = not self._thumb_opacity`：任何缩略图正在淡入时禁用 blit（淡入透明度需烘焙进合成图）。
- hover 抬升行通过 `skip_rows` 从合成图中排除（其槽位保持干净），再在上层单独绘制，避免与缓存合成重叠残影（`fc1e268`）。

### 2.4 动画引擎（`_anim_tick`，16ms）

统一处理四类进度：缩略图淡入（+0.12/帧）、hover 淡出（0.30 阻尼）、选择淡出（0.30 阻尼）、入场错峰（每帧揭 `len//12` 行）。每个受影响的行走 `_request_frame(changed_rows, overlay=True)`；无活动时停表。

## 3. 逐操作刷新链路

| 操作 | 链路 | 纹理是否重建 |
| --- | --- | --- |
| **导航 navigate_to / back / up** | `clear_queue` → `clear_selection` → `set_directory`(非 preserve) → `scan_started`(grid 清 `_path_textures`、置 `_scan_reset_pending`) → loading `modelReset`(grid 清纹理/清选中/epoch++) → 异步 `_ScanTask` → `scan_committed` → `update_layout` + `begin_presentation`(入场) + `_load_visible` | 是（导航跨目录丢弃路径缓存，但 loader 内存缓存仍按源路径命中，快速回填） |
| **刷新 F5 / FS watcher / 文件操作** | `_capture_selection` → `model.refresh()` = `set_directory(preserve_existing=True)`；签名相同则**不 reset** 直接 `scan_committed(scan_reused)` → `update_layout`；有变化才全量 reset | 未变化不重建；变化才重建 |
| **排序 / 过滤 / 隐藏切换 / 搜索** | `modelAboutToBeReset`→`_capture_path_textures`(按路径缓存纹理) → `modelReset`→`_on_model_reset`(epoch++/清 `_textures`) → `_base._on_grid_model_reset`→`update_layout` + `_restore_grid_selection` → `_load_visible` | 否（`_path_textures` 按路径重新映射到新行，Pass 1 直接命中） |
| **目录大小就绪** | `_on_dir_size_ready` → 更新 subtitle 缓存 → `dataChanged(SUBTITLE_ROLE)` → grid `_on_data_changed` 置 dirty/pop 纹理 → `_request_frame(row)` | 是（副标题变了必须重绘整张卡片纹理，逐目录触发，预算 12/帧 限流） |
| **缩略图就绪** | loader worker → `thumbnail_ready` → `handle_ready`(>512 降采样、QImage→QPixmap、写 `_raw_pixmaps`、`setData(DecorationRole)` 不 emit) → 50ms 批量 `flush` → `commit_thumbnail_rows`(dirty + 淡入 + `_request_frame`) | 是（仅该行，淡入 ~8 帧） |
| **滚动** | `_on_scroll`→`set_scrolling`+`_request_frame(full=True)`；`_base._on_scroll_value_changed`→100ms 去抖 `_load_visible` | 否（视口 blit + 条带重绘） |
| **hover / 选择** | `mouseMove/enter/leave/click` → 种子 `_hover_progress`/`_selection_progress` + `_request_frame(rows, overlay=True)`（部分重绘） | 否（覆盖层独立于纹理绘制） |
| **resize** | `resizeEvent`→`_relayout_scrollbar`+`update_layout`+`_request_frame(full)` | 否（复用纹理，只重排位置；视口因 `size_changed` 强制全量合成） |
| **缩放 zoom** | `begin_zoom` 捕获源/目标矩形 → 动画帧 `set_zoom_thumb_size` → `finish_zoom` + `invalidate_textures` + `update_layout` + `_load_visible` | 是（新尺寸全量重建，预算限流） |
| **主题 / UI 缩放** | `refresh_theme`/`refresh_scale` → epoch++ + `_clear_textures` + 全量 dirty + `_request_frame(full)` | 是 |

## 4. 性能预算与缓存

- 纹理构建：`_FULL_REBUILD_TEXTURE_BUDGET=12`/帧，延期队列 `_queue_full_rebuild_update`。
- 单元格纹理缓存：`_textures`（`OrderedDict`，上限 200，LRU 淘汰）＋ `_path_textures`（按路径，上限 200，跨排序/过滤存活）＋ `_raw_pixmaps`（`LRUCache(800)`，源像素图）。
- 缩略图 loader：3 线程池，准入上限 96，内存缓存 64MB，磁盘缓存；`retain_deferred` 丢弃离开视口的延迟任务。
- 缩放兜底纹理预算：`_ZOOM_FALLBACK_TEXTURE_BUDGET=2`/帧。

## 5. 发现与风险（分级）

### 已修复（本会话）
- **resize 纯黑**（`f7417ba`）：`_viewport_compose` 中纹理按新尺寸重建后，`_viewport_full_required` 因尺寸已匹配而误判“无需全量合成”，落入增量 blit 复制未填充（黑）纹理。已用 `size_changed` 强制全量合成，并加回归测试。

### 中等（性能，非正确性）
- **`_scan_reset_pending` 残留**：`preserve_existing` 刷新在“签名相同、复用扫描”路径**不发生 modelReset**，因此 grid `_on_scan_started` 置的 `_scan_reset_pending=True` 永不清零（它只在 `_on_model_reset` 里清）。后果：一次无变化的 F5/FS-watcher 之后，紧接着的**排序/过滤**会在 `_capture_path_textures` 里看到残留标志而**丢弃 `_path_textures` 且跳过捕获**，导致整屏卡片全量重渲染。建议：在 `_on_scan_committed` 的 `scan_reused` 分支显式复位该标志（或给 grid 增加 `mark_scan_settled()`）。
- **目录大小副标题更新 = 整卡重建**：`SUBTITLE_ROLE` 的 `dataChanged` 会 pop 掉该行纹理，强制 `_render_item` 重绘整张卡片（文件夹图标+名称+副标题+徽标）。目录大小是逐个异步到达的，可见目录多时会有一串整卡重建（受 12/帧 预算约束，但仍是可避免的浪费）。可考虑副标题单独分层绘制，或只把文本区域画进覆盖层。
- **滚动始终 `full=True`**：`_on_scroll` 每帧 `_request_frame(full=True)` → `update()` 全块重绘。视口 blit 让绘制本身便宜，但 Pass 1 仍会 Python 遍历**所有**可见行做 `intersects` 判断。可改为只失效“新露出的条带 + 脏行”。
- **hover 进出各触发一次全量视口合成**：因 `skip_rows` 变化会强制 `_viewport_tex=None` 全量重合成。合成本身只是把已建纹理 blit 一遍（约几十次 `drawPixmap`），成本可接受，但属于“为了简单正确”而牺牲的局部性；若后续 hover 掉帧可再优化为只重合成受影响条带。

### 观察项（设计/维护，非缺陷）
- **`_on_data_changed` 的 `RAW_PIXMAP_ROLE` 分支是死代码**：全代码库只有 `_base` 发 `SUBTITLE_ROLE` 与 `DisplayRole`，没有任何路径发 `RAW_PIXMAP_ROLE` 的 `dataChanged`。缩略图失效完全走 `ThumbnailDeliveryCoordinator.commit_thumbnail_rows`，不走模型信号。
- **`setData(DecorationRole)` 不发 `dataChanged`**（自定义实现直接写 `_icons` 返回 True）：这是刻意绕过模型信号，改由协调器批量失效。当前正确，但属于隐式约定，建议在 `_thumbnail_delivery.py` 注释中固化，避免未来有人“补发” `dataChanged` 造成双倍失效。
- **`themes.bg_enabled()` 为真时 paintEvent 不填底色**：依赖视口合成里的 `fillRect(_clr_panel)`。空态路径（0 行）走 `_draw_empty_state` 不涉及视口合成，行为正常；但若将来出现“有行但 `visible` 为空”的中间态，背景可能露出背景图而非面板色。

## 6. 建议（按收益/成本排序）

1. 修复 `_scan_reset_pending` 残留（一行级改动，消除一类全量重建）。
2. 滚动改为条带级失效（配合已有 `_viewport_compose` 的 `dirty_rows`/条带逻辑，改动小）。
3. 副标题分层绘制（中等改动，显著降低目录大小到达时的重建量）。
4. 为“缩略图失效不走 `dataChanged`”的约定补注释 / 断言，防回归。
