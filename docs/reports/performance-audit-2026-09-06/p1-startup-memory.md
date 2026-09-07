# 性能审查 P1 · 启动链与内存基线（2026-09-06）

> 状态：**STAGE RESULT（基础性能审查第一棒，主线程执行——子代理派发三次 provider 错误后改主线程）**
> 环境：Windows 11 x64、Python 3.14.3、PySide6 6.11.0、offscreen。测量脚本：`scripts/perf/startup_probe.py`（分段计时 + RSS 采样，每配置独立进程规避同进程多 MainWindow 的 ShortcutManager 已登记生命周期缺口）。

## 1. 导入链（`python -X importtime -c "import main"`，3 次中位）

- **总导入 0.36s**——健康，无行动项
- Top 自累积：`core.themes` 25ms、`PySide6.QtWidgets` 25ms、shiboken 签名库 ~36ms 合计、`core.settings` 7ms——无超过 25ms 的单件，无可延迟导入的候选（PySide6 桌面进程本就需早建 QApplication）

## 2. 启动分段（1k 文件样本库，独立进程 ×N）

| 段 | 中位 | 备注 |
|---|---|---|
| QApplication 创建 | 0.10s | |
| app 模块导入（bootstrap 之前） | 0.72s | |
| ApplicationBootstrap 构造 | 0.60–0.90s | **波动源：启动时对"上次库"（本机 F:\Blender 外置盘）做完整性检查**——外置盘在位与否直接影响此段 |
| open_session | 0.11s | |
| MainWindow 构造 + 会话接线 | 0.46s | |
| 扫描就绪（1k 文件） | **0.05s** | 扫描管线极快 |
| **总计（可交互）** | **≈2.0–2.3s** | RSS：导入后 77MB → 就绪 107MB（+30MB 含 UI+库+扫描） |

结论：**启动性能健康**，无需要行动的瓶颈。RSS 107MB 对 PySide6 应用属正常水位。

## 3. 缓存盘点（8 个模块级缓存，全部有界）

| 缓存 | 上界机制 |
|---|---|
| sequence_service._SCAN_CACHE | max=8 + 锁 |
| thumbnail_service._cache | max=8192 + 锁 |
| icons._CACHE | max=4096（OrderedDict） |
| file_list _model 纹理缓存 | 256MiB + 2000 条 |
| _grid_texture_cache | 200 条 |
| tag_chip._synonyms_cache | 500 |
| project_data 尺寸缓存 | TTL 30s |
| library_service 正则缓存 | 模式数天然有界 |

**无无界增长缓存**——缓存卫生优秀。

## 4. 重要发现与修复（超出测量范围的产品缺陷）

**PF-1（已修，commit 待推）· MainWindow 构造次序缺陷升级为实锤**：性能探针在本机真实持久化 settings 下**首启动即段错误**——`window.py` 原次序 `_restore_window_geometry`(:226) 先于 `_bg_*` 字段(:228-236)与 `_startup_anim_done`(:258) 初始化；持久化最大化标志经 `showMaximized`→`showEvent`（读 `_startup_anim_done`）与 `resizeEvent`（读 `_bg_resize_timer`）双路径触发未初始化字段访问，PySide6 下为 C 级 abort 非可捕获异常。质量轮登记的"真机用户命中即崩"由本探针**在真实条件下复现**。修复：两组事件处理字段全部提升到几何恢复之前 + 删除 :258 的重复赋值（原次序会在恢复期 showEvent 置位后被重置，造成二次淡入）。验证：探针存活出数 + window 系测试 + 基线模块绿。

## 5. 登记项

- bootstrap 0.6–0.9s 的波动源（上次库完整性检查打外置盘）——若要优化属产品行为决策（跳过外置盘/异步化），登记不修
- 探针 `scan_settle` 信号初版用错属性名导致恒等 5s 超时——已修正为 `_wait_for_scan()`+fade 收敛双条件（探针自身 bug，非应用）

无证据即 unverified——本文档自身也是这个纪律的适用对象。
