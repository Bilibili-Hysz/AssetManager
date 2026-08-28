# AssetsManager 桌面端 UI 性能优化方案

**分析日期**：2026-08-17
**分析范围**：桌面端 UI 全链路（panels/widgets/window/dialogs/services/repositories）
**当前状态**：性能工程化程度高，热点多为边界情况而非架构缺陷

---

## 执行摘要

通过全面代码审计，识别出 12 个性能热点，按 ROI 排序后规划为 3 轮优化：

- **P0（高 ROI，低风险）**：5 项，预计总收益 200-500ms 卡顿消除 + 400MB 内存降低
- **P1（中 ROI，中风险）**：4 项，预计总收益 300-800ms 主线程释放
- **P2（低 ROI 或高风险）**：3 项，列为中长期技术债

**关键发现**：
- ✅ 已有良好实践：纹理烘焙 + 预算限流、三级缓存、全链路 cancel token、防抖/节流、SQL 分块
- ⚠️ 主要问题：拖放同步 I/O、文件夹封面扫描、resize 过度重布局、内存无界增长

---

## P0 优化（高 ROI，立即实施）

### P0-1: 网格 resize 重布局仅列数变化时重建 ⭐⭐⭐⭐⭐

**问题**：`resizeEvent` 每次都 O(N) 全量重建 GridLayout，窗口拖拽期间每秒数十次。

**根因**：首列锚定（`_x0` 固定）意味着列数不变时所有 rect 不变，但当前 `widget_width` 变化即触发重建。

**修复**：
```python
# _grid_widget_data.py: update_layout()
def update_layout(self, item_count: int, widget_width: int) -> None:
    new_cols = self._cols_for_width(widget_width)
    # 短路：列数不变时 rects 不变
    if new_cols == self._layout.cols and self._layout.count == item_count:
        return  # 零成本跳过
    self._layout = GridLayout.compute(item_count, new_cols, ...)
    self._request_frame(full=True)
```

**收益**：消除窗口拖拽期 10-100ms/次 × 数十次/秒的卡顿尖峰。

**风险**：极低（首列锚定保证 rects 几何不变性）。

**工作量**：1-2 小时（1 行短路 + 回归测试）。

---

### P0-2: InfoPanel 预览缩放防抖 + 双重触发去重 ⭐⭐⭐⭐⭐

**问题**：`resizeEvent` 每次调用 `_apply_scaled_preview`（5-15ms 主线程 SmoothTransformation），且 `eventFilter` 的 `_preview` Resize 事件会再次触发——同一 resize 双重执行。

**修复**：
```python
# info.py
def resizeEvent(self, event):
    super().resizeEvent(event)
    # 复用现有 150ms 防抖 timer
    if self._preview_rescale_timer is not None:
        self._preview_rescale_timer.stop()
    self._preview_rescale_timer = QTimer.singleShot(
        150, self._apply_scaled_preview
    )

# 去重：记录已处理的 (width, height) epoch
def _apply_scaled_preview(self):
    size = self._preview.size()
    if (size.width(), size.height()) == self._last_scaled_size:
        return  # 去重
    self._last_scaled_size = (size.width(), size.height())
    # ... 原缩放逻辑
```

**收益**：消除 dock 拖拽期 5-15ms × 2 × N 次/秒的持续 jank。

**风险**：极低（已有防抖机制，仅需扩展到 resizeEvent）。

**工作量**：2-3 小时（复用现有 timer + epoch 去重 + 回归测试）。

---

### P0-3: 文件夹封面图扫描移入缩略图 worker 管线 ⭐⭐⭐⭐

**问题**：`_first_image_cached` 在主线程 `os.scandir` 最多 500 项，每文件夹 1-5ms，滚动停顿时 10-30 文件夹 → 10-100ms 主线程尖峰。

**修复策略**：
1. 将 `find_first_image` 改为异步任务，提交到 `ThumbnailLoader` worker（现有 `_ScanTask` 已证明可行）
2. 按 mtime 持久化缓存（类似 `thumbnail_service` 的 DB 缓存），避免重复扫描
3. `_load_visible` 提交封面扫描任务，worker 完成后通过 `QMetaObject.invokeMethod` 更新主线程 `_first_image_cache`

**收益**：消除滚动停顿 10-100ms 主线程尖峰，改善滚动流畅度。

**风险**：中（需处理 worker 结果交付 + cancel token + 缓存失效），但现有 `_ScanTask` / `_thumbnail_delivery.py` 提供参考实现。

**工作量**：16-24 小时（异步化 + DB 缓存 + 交付管线 + 回归测试）。

---

### P0-4: `_icons` LRU 化或并入 `_raw_pixmaps` ⭐⭐⭐⭐

**问题**：`FileSystemModel._icons` 每目录无界增长，10k 文件目录滚完积累 400MB（96px × 10k 项）。

**修复**：
```python
# _model.py: 改用 LRUCache（复用现有 core/cache.py）
from AssetsManager.core.cache import LRUCache

class FileSystemModel:
    def __init__(self):
        self._icons = LRUCache(maxsize=800)  # 与 _raw_pixmaps 一致
        # 或：直接废弃 _icons，DecorationRole 改查 _raw_pixmaps
```

**收益**：限制峰值至 ~32MB（800 项 × 40KB），节省 370MB。

**风险**：极低（LRU 替换 dict，语义不变）。

**工作量**：1-2 小时（一行替换 + Details 视图回归测试）。

---

### P0-5: Details 标签缓存复用 TagStore `_resolve_cache` ⭐⭐⭐⭐

**问题**：`DetailModel._rebuild_tags_cache` 对每文件 `Path.resolve()`（realpath syscall），10k 文件约 50-200ms。

**修复**：
```python
# _detail_model.py
def _rebuild_tags_cache(self, entries):
    # 改用 TagStore 已有的 _resolve_cache，避免重复 syscall
    resolved = [
        self._tag_store._resolve_cache.get(
            entry.path,
            str(Path(entry.path).resolve())
        )
        for entry in entries
    ]
    # 或：缓存到 FileSystemModel._path_index
```

**收益**：消除 10k 文件切换/排序时 50-200ms 主线程 syscall。

**风险**：低（TagStore `_resolve_cache` 已验证正确，仅需对接）。

**工作量**：4-6 小时（缓存对接 + resolve 键预填充 + 回归测试）。

---

## P1 优化（中 ROI，需评估风险）

### P1-1: 拖放文件操作后台化 ⭐⭐⭐

**问题**：`_on_drop` 同步调用 `service.move_to_directory` / `copy_to_directory`（内部 `shutil.copy2` / `shutil.move`），GB 级目录冻结数十秒。

**修复**：复用 `_run_in_background` + 现有 feedback/selection 恢复机制（粘贴路径已验证可行）。

**收益**：消除大文件/文件夹拖入时数秒-数十秒 UI 冻结。

**风险**：中（需处理后台进度反馈 + 错误处理 + 取消能力）。

**工作量**：12-16 小时（后台化 + 进度对话框 + cancel token + 回归测试）。

---

### P1-2: 查看器异步解码 + 缩略图条移出 paintEvent ⭐⭐⭐

**问题**：
- `load_image` 在 UI 线程 `QImageReader.read()`，24MP 照片 100-400ms
- `_paint_strip` 在 paintEvent 内同步解码 10-20 张缩略图，首帧 150-500ms 冻结

**修复**：
1. `load_image` 改为 QThread + 信号交付（参考 `ThumbnailLoader`）
2. 缩略图条预解码缓存（`_strip_thumbs` 改为异步填充）

**收益**：消除查看器打开/翻页 100-400ms 冻结 + 首帧 150-500ms 冻结。

**风险**：中（需处理异步加载期间的占位符 + 翻页取消）。

**工作量**：20-24 小时（异步解码 + 占位符 + 缩略图条预填充 + 回归测试）。

---

### P1-3: 视频 ffmpeg 独立单线程池 ⭐⭐⭐

**问题**：`_load_video_frame` 的 ffmpeg subprocess（30s 超时）运行在 ThumbnailLoader 的 3 线程池，慢视频占住 1/3 线程。

**修复**：
```python
# _loader.py: 新增独立视频池
class ThumbnailLoader:
    def __init__(self):
        self._image_pool = BoundedThreadPoolExecutor(3, ...)
        self._video_pool = BoundedThreadPoolExecutor(1, ...)  # 独立

    def _load_video_frame(self, ...):
        return self._video_pool.submit(...)  # 改路由
```

**收益**：防止慢视频饿死图片缩略图，改善视频目录滚动流畅度。

**风险**：低（仅池隔离，不改算法）。

**工作量**：4-6 小时（独立池 + 路由修改 + 回归测试）。

---

### P1-4: `_raw_pixmaps` 按字节上限（64-128MB） ⭐⭐⭐

**问题**：`LRUCache(800)` 按条目数限，256px 档 800 项 ≈ 210MB。

**修复**：复用 `GridTextureCache._store_texture_bytes` 的字节记账模式，改为 `LRUCache(maxbytes=67108864)`（64MB）。

**收益**：限制高缩放档峰值至 64-128MB，节省 ~80-150MB。

**风险**：低（现有纹理缓存已验证可行）。

**工作量**：8-12 小时（字节记账 LRU + 交付层适配 + 回归测试）。

---

## P2 优化（低优先级或高风险）

### P2-1: 大目录扫描提交分块/延迟排序 ⭐⭐

**问题**：`_on_scan_done` 在主线程执行 `_reset_model` + `_apply_sort`，100k 文件约 300ms-1s。

**风险**：高（涉及模型重置语义，跨线程模型不可行，分块提交需改 QAbstractItemModel 协议）。

**建议**：列为中期技术债，需架构级评审。

---

### P2-2: 标签编辑对话框改单次 `list_file_tags` 分组 ⭐⭐

**问题**：`_refresh_suggestions` 对每标签调用 `get_files_by_tag`（N+1 查询），数百标签 50-200ms。

**修复**：改用 `list_file_tags` 一次分组（`tag_tree_controller` 已有参考实现）。

**收益**：数百标签时节省 50-150ms。

**工作量**：4-6 小时（改用分组查询 + 回归测试）。

---

### P2-3: 滚动带级 dirty region（audit F-07） ⭐

**问题**：滚动每帧全视口重绘，3 遍 Python 循环遍历可见行。

**当前成本**：1-3ms/帧，尚可接受。

**建议**：列为长期优化（代码已标注为遗留项），不建议短期投入。

---

## 实施策略

### 第一阶段：P0 快速胜利（1-2 周）

**目标**：消除高频卡顿 + 内存膨胀，收益明显且风险低。

**顺序**：
1. P0-1（网格 resize 短路）—— 1 天
2. P0-2（预览缩放防抖）—— 1 天
3. P0-4（`_icons` LRU）—— 0.5 天
4. P0-5（Details resolve 缓存）—— 1 天
5. P0-3（封面扫描异步化）—— 3-4 天

**验收**：
- 窗口/dock 拖拽无卡顿
- 大目录内存峰值降低 300-400MB
- Details 视图切换/排序流畅

---

### 第二阶段：P1 主线程释放（2-3 周）

**目标**：后台化耗时操作，改善响应性。

**顺序**：
1. P1-3（视频池隔离）—— 1 天
2. P1-4（pixmap 字节上限）—— 2 天
3. P1-1（拖放后台化）—— 2-3 天
4. P1-2（查看器异步）—— 3-4 天

**验收**：
- 拖入大文件夹 UI 保持响应
- 查看器打开/翻页无冻结
- 视频目录滚动不阻塞图片

---

### 第三阶段：P2 技术债评审（需求驱动）

**触发条件**：
- P2-1：用户报告 100k+ 文件目录切换卡顿
- P2-2：用户报告数百标签编辑对话框慢
- P2-3：性能分析发现滚动帧率瓶颈

**评审点**：架构变更的收益/风险比、是否有更高 ROI 的替代方案。

---

## 验证方法

### 性能基准测试

**场景**：
1. 10k 文件目录滚动（网格模式）
2. 窗口拖拽 resize
3. 拖入 1GB 文件夹
4. Details 视图切换 + 列排序
5. 查看器打开 24MP 照片
6. 视频目录滚动

**指标**：
- 主线程阻塞时长（profiling）
- 帧率（滚动/拖拽期间）
- 内存峰值（RSS）
- 用户感知卡顿（手动测试）

### 回归测试

**覆盖**：
- 网格滚动/缩放/选择
- 文件拖放/粘贴/删除
- Details 视图排序/过滤
- 查看器翻页/旋转/缩放
- 缩略图加载/取消

---

## 风险控制

### 通用原则

1. **每项优化独立分支**：便于回滚
2. **性能测试先行**：建立基准，验证收益
3. **渐进式推进**：P0 → P1 → P2，避免并行多项
4. **用户反馈驱动**：P2 项需实际需求支持

### 已知风险

- **P0-3（封面异步）**：worker 结果交付时序，需 cancel token + 缓存失效测试
- **P1-1（拖放后台）**：进度反馈 + 错误处理复杂度
- **P1-2（查看器异步）**：翻页取消 + 占位符闪烁
- **P2-1（分块提交）**：模型协议变更，架构级影响

---

## 已确认无需处理

以下项已有良好实践，不是瓶颈：

- ✅ 缩略图交付主线程 `QPixmap.fromImage`（512px 上限 + 50ms 批量）
- ✅ 滚动缩略图调度（100ms 防抖 + 视口裁剪）
- ✅ 网格纹理预算重建（12 张/帧）
- ✅ 目录大小计算（worker + TTL DB 缓存 + 取消）
- ✅ 搜索（防抖 + worker 预加载 + 路径索引）
- ✅ Tag SQL（900 参数分块）
- ✅ 库切换 drain（3-5s 超时）

---

**下一步**：
1. 用户确认优化优先级（P0 全做 / P1 选做 / P2 暂缓）
2. 建立性能基准测试脚本
3. 启动 P0-1（网格 resize 短路）作为验证性试点
