# FileList 上帝对象拆解计划（#5 / #6，2026-08-15）

目标：在不改变任何运行时行为的前提下，把 `_base.py`（FileListPanel，~1800 行）与
`_grid_widget.py`（FileListGridWidget，~1900 行）中**边界清晰、内聚**的块抽成独立协作对象/纯函数，
降低后续维护成本。

铁律：**行为零变化**。被移动的代码逐字保留，不改逻辑、不改文案、不改锁序、不改状态机；
与类状态耦合过深的块宁可少拆，也不引入行为风险。

---

## #6 — 拆 `FileListGridWidget`（`_grid_widget.py`）

抽出两个内聚的协作对象。二者只改 `_grid_widget.py` 的**内部存储**，不碰 `_base.py`
所依赖的公开表面（`update_layout`/`invalidate_textures`/`begin_zoom`/`finish_zoom`/
`set_thumb_size`/`begin_presentation`/`stop_animations`/`clear_selection`/`select_all`/
`selection_model_rows`/`_scroll_y`/`_scrollbar`/`_selection`/`_zoom_relayout_active`/`_reduce_motion` 等）。

### 6a. `GridTextureCache`（新文件 `_grid_texture_cache.py`）

迁移以下状态与方法，widget 持有一个 `self._cache` 并委托：

- 状态：`_textures`(OrderedDict[int,QPixmap])、`_path_textures`(OrderedDict[str,QPixmap])、
  `_texture_bytes`(dict[int,int])、`_texture_cache_bytes`(int)。
- 方法：`_cache_texture`（含 200 上限 LRU 淘汰）、`_clear_textures`、`_store_texture_bytes`、
  `_remove_texture_bytes`、`_refresh_texture_accounting`、`_record_texture_eviction`、
  `_capture_path_textures`。
- Pass 1 里 `_path_textures.pop(path, None)` 的路径纹理回填，改为通过 cache 的一个方法（如
  `take_path_texture(path)`）完成。

约束：
- LRU 顺序（`move_to_end`/`popitem(last=False)`）与淘汰阈值（200）不变。
- 字节统计只在 `_performance_recorder is not None` 时发生——cache 通过一个
  `recorder()` 可调用（返回 recorder 或 None）读取，保持现状。
- `_record_texture_eviction` 仍走 widget 的 `_record_performance` 语义（event 名不变）。
- 所有对 `self._textures`/`self._cache_texture` 等的引用点全部改到 `self._cache`，不得遗漏。

### 6b. `Animator`（新文件 `_animator.py`）

迁移以下动画状态与推进逻辑，widget 持有一个 `self._animator` 并委托：

- 状态：`_thumb_opacity`、`_thumbnail_rows`、`_hover_progress`、`_selection_progress`、
  `_entrance_queue`、`_entrance_visible`、`_anim_timer`、`_presented_generation`、
  `_pending_presentation`、`_reduce_motion`。
- 方法：`_anim_tick`、`_start_presentation`、`_present_pending_generation`、`begin_presentation`、
  `discard_pending_presentation`、`_apply_selection_progress`、`stop_animations`（动画部分）。

约束：
- `_anim_tick` 需要向 widget 回传「本帧变化行」并触发 `_request_frame(changed_rows, overlay=True)`
  与 `_record_performance("grid.animation_tick", ...)`——通过注入回调完成（如 `on_changed(rows)`），
  事件名与属性不变。
- 淡入 +0.12、hover/选择 0.30 阻尼、入场 `len//12` 等推进参数逐字保留。
- `_reduce_motion` 分支行为不变。

---

## #5 — 拆 `FileListPanel`（`_base.py`）安全子集

完整拆成 SelectionCoordinator/StatusPresenter/ThumbnailOrchestrator 协作类属于高风险
（这些逻辑与 `_model`/`_grid_widget`/`_detail_view` 状态强耦合）。本轮只做**纯函数**抽取，
把字符串/数值计算从面板剥离，行为不变。

### 5a. 状态/反馈纯助手（新文件 `_status_helpers.py`）

从 `_base.py` 抽出以下**无状态**计算为模块级纯函数，面板方法改为调用它们：

- `compute_total_size(model) -> int`：`_compute_total_sz` 的循环体（遍历 `model.entries`，
  对非目录 `model.cached_stat(entry).st_size` 累加，异常吞掉）。
- `status_text(*, state, view_mode, total, selected, size_str) -> str`：`_update_status` 中
  依据 `list_state`(loading/scan_error/empty_folder/empty_filtered) 与 selected/total 选择文案
  的分支（文案 key 与 `tr(...)` 参数完全一致）。
- `operation_feedback_text(*, operation, changed_count, errors, warnings, running) -> str`：
  `_show_operation_feedback` 中根据 running/errors/warnings/changed_count 选择文案的分支。

约束：
- `tr(...)` 调用与占位参数（operation/count/failed/warnings）逐字保留。
- `_update_status`/`_show_operation_feedback` 方法签名与副作用（`_status.setText`、
  `_operation_feedback.show()/start()` 定时器）保持不变，只把「算文案」的部分换成调用纯函数。

---

## 委派与门禁

- 两个子代理（#6 一个、#5 一个），**串行**执行（避免并发 pytest 相互干扰）。
- 子代理禁止 `git add/commit/push`，只允许 `git diff` 自查。
- 门禁（子代理与主智能体都跑）：
  - `python -m ruff check AssetsManager tests scripts run.py`
  - `python -m pyright`（0e0w）
  - `python -m pytest tests/desktop/test_file_list_grid_widget.py tests/desktop/test_file_list_view.py tests/desktop/test_file_list_details.py tests/desktop/test_file_list_model.py tests/unit/test_low_batch_detail_model.py -n 0 -q`
- 主智能体必须**亲自复核**：重跑门禁、审 diff、确认行为零变化后再 commit。
- 沙箱注意：pytest `-n 0` 且不传 `--basetemp`；`multiprocessing.Pipe` 类失败不算回归。
